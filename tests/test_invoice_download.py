"""
Tests para los endpoints de descarga de facturas en PDF y PNG.

Verifica que:
- Los endpoints responden 200 con el Content-Type correcto
- La respuesta tiene bytes no vacíos
- El endpoint retorna 404 para facturas inexistentes
- El helper build_invoice_context construye el contexto correctamente
- El template HTML se renderiza sin errores
"""

import io
import os
import tempfile

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from database import init_db


# ---------------------------------------------------------------------------
# Fixtures (reutilizamos el mismo patrón que test_operacional.py)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def app():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    from config import settings
    original_path = settings.DATABASE_PATH
    settings.DATABASE_PATH = db_path

    await init_db(db_path)

    from main import app as fastapi_app
    yield fastapi_app

    settings.DATABASE_PATH = original_path
    for ext in ("", "-wal", "-shm"):
        try:
            os.unlink(db_path + ext)
        except FileNotFoundError:
            pass


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def user_token(client):
    """Crea usuario 'vendedor1' con prefijo 'V', le asigna permisos, retorna (token, headers)."""
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "pichardo", "password": "admin123"},
    )
    admin_token = resp.json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # Crear usuario con prefijo 'V'
    await client.post(
        "/api/v1/admin/users",
        json={
            "username": "vendedor1",
            "password": "Seguro123!",
            "prefix": "V",
        },
        headers=admin_headers,
    )

    # Asignar permisos necesarios
    await client.put(
        "/api/v1/admin/users/vendedor1/permissions",
        json={
            "facturas_ver": True,
            "facturas_emitir": True,
            "clientes_crear": True,
            "clientes_modificar": True,
            "puede_ver_datos_de_otros": True,
        },
        headers=admin_headers,
    )

    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "vendedor1", "password": "Seguro123!"},
    )
    token = resp.json()["access_token"]
    return token, {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def factura_id(client, user_token):
    """Crea una factura de prueba con un ítem de encargo y retorna su ID."""
    _, headers = user_token

    # Crear un cliente primero
    resp = await client.post(
        "/api/v1/clientes",
        json={
            "nombre": "María",
            "apellido": "García",
            "telefono": "809-555-0001",
        },
        headers=headers,
    )
    assert resp.status_code == 201
    cliente_id = resp.json()["id"]

    # Crear factura con un ítem de encargo
    resp = await client.post(
        "/api/v1/facturas",
        json={
            "cliente_id": cliente_id,
            "total": 15000.00,
            "monto_pagado": 5000.00,
            "entrega_domicilio": False,
            "garantia_hasta": "6 Meses",
            "facturacion_rapida": 0,
            "items": [
                {
                    "nombre": "Sofá 3 Plazas",
                    "cantidad": 1,
                    "tipo": "encargo",
                    "subtotal": 15000.00,
                    "material": "Cuero genuino",
                    "tela": "Marrón",
                    "descripcion": "Con patas doradas",
                    "area": "Tapicería",
                    "tipo_mueble": "Sofá",
                }
            ],
        },
        headers=headers,
    )
    assert resp.status_code == 201, f"Fallo al crear factura: {resp.text}"
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# Tests del servicio invoice_pdf_service (unit)
# ---------------------------------------------------------------------------

class TestBuildInvoiceContext:
    """Verifica que build_invoice_context genera el contexto correctamente."""

    def test_cliente_nombre_desde_join(self):
        from services.invoice_pdf_service import build_invoice_context
        factura = {
            "id": "v-abc12345",
            "fecha": "2026-08-01T10:00:00",
            "cliente_nombre": "María",
            "cliente_apellido": "García",
            "total": 15000.0,
            "monto_pagado": 5000.0,
            "saldo_pendiente": 10000.0,
            "entrega_domicilio": 0,
            "garantia_hasta": "6 Meses",
            "direccion_entrega": None,
        }
        items = [{
            "nombre": "Sofá 3 Plazas",
            "cantidad": 1,
            "tipo": "encargo",
            "subtotal": 15000.0,
            "material": "Cuero",
            "tela": "Marrón",
            "descripcion": None,
        }]
        company = {
            "nombre": "Venus Muebles",
            "logo_path": None,
            "ubicacion": "Santo Domingo",
            "telefono": "809-000-0000",
            "rnc": None,
        }
        ctx = build_invoice_context(factura, items, company)

        assert ctx["cliente_nombre"] == "María García"
        assert ctx["total"] == 15000.0
        assert ctx["monto_pagado"] == 5000.0
        assert ctx["saldo_pendiente"] == 10000.0
        assert ctx["factura_id"] == "v-abc12345"
        assert len(ctx["items"]) == 1
        assert ctx["company"]["nombre"] == "Venus Muebles"

    def test_cliente_nombre_desde_json_embebido(self):
        import json
        from services.invoice_pdf_service import build_invoice_context
        factura = {
            "id": "v-xyz99999",
            "fecha": "2026-08-01T10:00:00",
            "cliente_nombre": None,
            "cliente_apellido": None,
            "cliente": json.dumps({"nombre": "Pedro", "apellido": "Ramírez", "telefono": "829-999-1111"}),
            "total": 8000.0,
            "monto_pagado": 0,
            "saldo_pendiente": 8000.0,
            "entrega_domicilio": 0,
            "garantia_hasta": None,
            "direccion_entrega": None,
        }
        ctx = build_invoice_context(factura, [], {"nombre": "Venus", "logo_path": None, "rnc": None, "ubicacion": "", "telefono": ""})
        assert ctx["cliente_nombre"] == "Pedro Ramírez"
        assert ctx["cliente_telefono"] == "829-999-1111"

    def test_rnc_none_in_context(self):
        from services.invoice_pdf_service import build_invoice_context
        factura = {
            "id": "v-000", "fecha": "2026-08-01", "cliente_nombre": "Test", "cliente_apellido": "",
            "total": 1000.0, "monto_pagado": 0, "saldo_pendiente": 1000.0,
            "entrega_domicilio": 0, "garantia_hasta": None, "direccion_entrega": None,
        }
        company_sin_rnc = {"nombre": "Venus", "logo_path": None, "rnc": None, "ubicacion": "", "telefono": ""}
        ctx = build_invoice_context(factura, [], company_sin_rnc)
        # El campo rnc viene del company dict; el template lo chequea con {% if company.rnc %}
        assert ctx["company"]["rnc"] is None

    def test_attributes_cleaning_in_context(self):
        from services.invoice_pdf_service import build_invoice_context
        factura = {
            "id": "v-clean", "fecha": "2026-08-01", "cliente_nombre": "Test", "cliente_apellido": "",
            "total": 1000.0, "monto_pagado": 0, "saldo_pendiente": 1000.0,
            "entrega_domicilio": 0, "garantia_hasta": None, "direccion_entrega": None,
        }
        items = [
            {
                "nombre": "Otoman",
                "cantidad": 1,
                "tipo": "encargo",
                "subtotal": 1000.0,
                "material": '["Madera Pino"]',
                "tela": '["Lino"]',
            },
            {
                "nombre": "Mesa",
                "cantidad": 1,
                "tipo": "encargo",
                "subtotal": 1000.0,
                "material": None,
                "tela": "null",
            }
        ]
        ctx = build_invoice_context(factura, items, {"nombre": "Venus", "logo_path": None, "rnc": None, "ubicacion": "", "telefono": ""})
        assert ctx["items"][0]["material"] == "Madera Pino"
        assert ctx["items"][0]["tela"] == "Lino"
        assert ctx["items"][1]["material"] is None
        assert ctx["items"][1]["tela"] is None


class TestCleanAttributeValue:
    """Pruebas unitarias para la función _clean_attribute_value."""

    def test_clean_json_array_string(self):
        from services.invoice_pdf_service import _clean_attribute_value
        assert _clean_attribute_value('["Madera Pino"]') == "Madera Pino"
        assert _clean_attribute_value('["Lino"]') == "Lino"
        assert _clean_attribute_value('["Madera Pino", "Roble"]') == "Madera Pino, Roble"

    def test_clean_python_list(self):
        from services.invoice_pdf_service import _clean_attribute_value
        assert _clean_attribute_value(["Madera Pino"]) == "Madera Pino"

    def test_clean_null_values(self):
        from services.invoice_pdf_service import _clean_attribute_value
        assert _clean_attribute_value(None) is None
        assert _clean_attribute_value("") is None
        assert _clean_attribute_value("null") is None
        assert _clean_attribute_value("[]") is None
        assert _clean_attribute_value('[""]') is None

    def test_clean_plain_strings(self):
        from services.invoice_pdf_service import _clean_attribute_value
        assert _clean_attribute_value("madera pino") == "madera pino"
        assert _clean_attribute_value("Lino") == "Lino"


class TestRenderTemplate:
    """Verifica que el template HTML se renderiza sin errores."""

    def _make_context(self, rnc=None):
        from services.invoice_pdf_service import build_invoice_context
        factura = {
            "id": "v-test0001",
            "fecha": "2026-08-01T12:00:00",
            "cliente_nombre": "Ana",
            "cliente_apellido": "López",
            "total": 5000.0,
            "monto_pagado": 2000.0,
            "saldo_pendiente": 3000.0,
            "entrega_domicilio": 0,
            "garantia_hasta": "1 Mes",
            "direccion_entrega": None,
        }
        items = [
            {"nombre": "Otoman", "cantidad": 1, "tipo": "encargo", "subtotal": 2500.0, "material": '["Madera Pino"]', "tela": '["Lino"]', "descripcion": ""},
            {"nombre": "Silla", "cantidad": 4, "tipo": "stock", "subtotal": 2500.0, "material": None, "tela": "Rojo", "descripcion": None},
        ]
        company = {"nombre": "Venus Muebles", "logo_path": None, "ubicacion": "SD", "telefono": "809-0000", "rnc": rnc}
        return build_invoice_context(factura, items, company)

    def test_html_renders_without_error(self):
        from services.invoice_pdf_service import _render_invoice_html
        html = _render_invoice_html(self._make_context())
        assert "Venus Muebles" in html
        assert "v-test0001" in html
        assert "Ana López" in html
        assert "Otoman" in html
        assert "Mat: Madera Pino Tela: Lino" in html
        assert '["Madera Pino"]' not in html
        assert '["Lino"]' not in html
        assert "·" not in html
        assert "5000.00" in html
        assert "2000.00" in html
        assert "3000.00" in html
        assert "Total debido" in html

    def test_rnc_not_in_html_when_none(self):
        from services.invoice_pdf_service import _render_invoice_html
        html = _render_invoice_html(self._make_context(rnc=None))
        assert "RNC:" not in html

    def test_rnc_in_html_when_set(self):
        from services.invoice_pdf_service import _render_invoice_html
        html = _render_invoice_html(self._make_context(rnc="123-45678-9"))
        assert "RNC:" in html
        assert "123-45678-9" in html


# ---------------------------------------------------------------------------
# Tests de los endpoints HTTP
# ---------------------------------------------------------------------------

class TestDownloadEndpoints:
    """Verifica los endpoints GET /facturas/{id}/download/pdf y /png."""

    @pytest.mark.asyncio
    async def test_download_pdf_returns_200_with_pdf_bytes(self, client, user_token, factura_id):
        _, headers = user_token
        resp = await client.get(f"/api/v1/facturas/{factura_id}/download/pdf", headers=headers)
        assert resp.status_code == 200, f"Respuesta inesperada: {resp.text}"
        assert resp.headers["content-type"] == "application/pdf"
        assert len(resp.content) > 100  # PDF tiene contenido real
        assert resp.content[:4] == b"%PDF"  # Firma mágica del formato PDF

    @pytest.mark.asyncio
    async def test_download_png_returns_200_with_png_bytes(self, client, user_token, factura_id):
        _, headers = user_token
        resp = await client.get(f"/api/v1/facturas/{factura_id}/download/png", headers=headers)
        assert resp.status_code == 200, f"Respuesta inesperada: {resp.text}"
        assert resp.headers["content-type"] == "image/png"
        assert len(resp.content) > 100
        assert resp.content[:8] == b"\x89PNG\r\n\x1a\n"  # Firma mágica PNG

    @pytest.mark.asyncio
    async def test_download_pdf_404_for_missing_factura(self, client, user_token):
        _, headers = user_token
        resp = await client.get("/api/v1/facturas/v-noexiste99/download/pdf", headers=headers)
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_download_png_404_for_missing_factura(self, client, user_token):
        _, headers = user_token
        resp = await client.get("/api/v1/facturas/v-noexiste99/download/png", headers=headers)
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_download_requires_auth(self, client, factura_id):
        """Sin token debe retornar 401."""
        resp = await client.get(f"/api/v1/facturas/{factura_id}/download/pdf")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_pdf_content_disposition_header(self, client, user_token, factura_id):
        _, headers = user_token
        resp = await client.get(f"/api/v1/facturas/{factura_id}/download/pdf", headers=headers)
        if resp.status_code == 200:
            assert "attachment" in resp.headers.get("content-disposition", "")
            assert ".pdf" in resp.headers.get("content-disposition", "")

    @pytest.mark.asyncio
    async def test_png_content_disposition_header(self, client, user_token, factura_id):
        _, headers = user_token
        resp = await client.get(f"/api/v1/facturas/{factura_id}/download/png", headers=headers)
        if resp.status_code == 200:
            assert "attachment" in resp.headers.get("content-disposition", "")
            assert ".png" in resp.headers.get("content-disposition", "")


class TestGroupInvoiceItems:
    """Pruebas para la función interna de agrupación de ítems."""
    def test_group_invoice_items(self):
        from routers.operacional import _group_invoice_items
        items = [
            {
                "id": "1", "nombre": "Silla", "catalogo_id": "C1", "color": "Rojo", 
                "tela": "Cuero", "material": "Madera", "cantidad": 1, "subtotal": 1000.0
            },
            {
                "id": "2", "nombre": "Silla", "catalogo_id": "C1", "color": "Rojo", 
                "tela": "Cuero", "material": "Madera", "cantidad": 1, "subtotal": 1000.0
            },
            {
                "id": "3", "nombre": "Mesa", "catalogo_id": "C2", "color": "Cafe", 
                "tela": None, "material": "Cristal", "cantidad": 1, "subtotal": 5000.0
            }
        ]
        
        grouped = _group_invoice_items(items)
        assert len(grouped) == 2
        
        sillas = next(i for i in grouped if i["nombre"] == "Silla")
        assert sillas["cantidad"] == 2
        assert sillas["subtotal"] == 2000.0
        
        mesas = next(i for i in grouped if i["nombre"] == "Mesa")
        assert mesas["cantidad"] == 1
        assert mesas["subtotal"] == 5000.0


class TestCompanyConfigEndpoints:
    """Pruebas para los endpoints de configuración de empresa y su persistencia."""

    @pytest.mark.asyncio
    async def test_get_and_put_empresa_config(self, client, user_token):
        token, user_headers = user_token

        # 1. Login admin
        admin_resp = await client.post(
            "/api/v1/auth/login",
            data={"username": "pichardo", "password": "admin123"},
        )
        admin_headers = {"Authorization": f"Bearer {admin_resp.json()['access_token']}"}

        # 2. GET inicial por usuario regular
        resp = await client.get("/api/v1/config/empresa", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "nombre" in data

        # 3. PUT /config/empresa por admin (o usuario con permiso configuracion_modificar)
        put_resp = await client.put(
            "/api/v1/config/empresa",
            json={
                "nombre": "Muebles Venus VIP",
                "rnc": "131-99999-1",
                "telefono": "809-777-8888",
                "ubicacion": "Santiago, RD",
            },
            headers=admin_headers,
        )
        assert put_resp.status_code == 200
        assert put_resp.json()["empresa"]["nombre"] == "Muebles Venus VIP"
        assert put_resp.json()["empresa"]["rnc"] == "131-99999-1"

        # 4. Verificar que GET /config/empresa y GET /config reflejan los cambios
        get_resp = await client.get("/api/v1/config/empresa", headers=user_headers)
        assert get_resp.status_code == 200
        assert get_resp.json()["nombre"] == "Muebles Venus VIP"
        assert get_resp.json()["rnc"] == "131-99999-1"

        cfg_resp = await client.get("/api/v1/config", headers=user_headers)
        assert cfg_resp.status_code == 200
        assert cfg_resp.json()["empresa"]["nombre"] == "Muebles Venus VIP"
        assert cfg_resp.json()["empresa"]["rnc"] == "131-99999-1"

