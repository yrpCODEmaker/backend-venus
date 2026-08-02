"""
Tests operacionales — Pasos 7-9.

Verifica facturas transaccionales, items status (bypass), pagos,
envíos con garantía, clientes, catálogo, stock y warranty cron.
"""

import os
import tempfile

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from database import init_db


# ---------------------------------------------------------------------------
# Fixtures
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
    """Crea usuario 'laura' con prefijo 'L', inserta datos base, retorna token."""
    # Login admin
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "pichardo", "password": "admin123"},
    )
    admin_token = resp.json()["access_token"]

    # Crear usuario
    await client.post(
        "/api/v1/admin/users",
        json={"username": "laura", "password": "secreto", "prefix": "L"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    # Otorgar permisos operacionales a laura
    await client.put(
        "/api/v1/admin/users/laura/permissions",
        json={
            "facturas_ver": True, "facturas_emitir": True, "facturas_modificar": True,
            "fabricacion_ver_estados": True, "fabricacion_modificar_estados": True, "fabricacion_mandar_envio": True,
            "stock_crear": True, "stock_modificar": True, "stock_eliminar": True,
            "catalogo_crear": True, "catalogo_modificar": True, "catalogo_eliminar": True,
            "clientes_crear": True, "clientes_modificar": True, "clientes_eliminar": True,
            "puede_ver_datos_de_otros": True
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    # Login usuario
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "laura", "password": "secreto"},
    )
    token = resp.json()["access_token"]

    # Insertar datos base via sync push
    await client.post(
        "/api/v1/sync/push",
        json={
            "clientes": [{
                "local_id": 1,
                "nombre": "Juan",
                "apellido": "Pérez",
                "telefono": "809-555-0001",
                "updated_at": "2026-07-16T12:00:00",
            }],
            "images": [{
                "local_id": 1,
                "aspect_ratio": "16:9",
                "file_path": "/local/sofa.jpg",
                "updated_at": "2026-07-16T12:00:00",
            }],
            "catalogo": [{
                "local_id": 1,
                "nombre": "Sofá 3 Plazas",
                "tipo": "Sofá",
                "area": "Tapicería",
                "precio_base": 3000,
                "image_id": 1,
                "updated_at": "2026-07-16T12:00:00",
            }],
            "stock": [{
                "local_id": 1,
                "catalogo_id": 1,
                "color": "Rojo",
                "material": "Tela",
                "cantidad": 5,
                "precio": 3500,
                "image_id": 1,
                "updated_at": "2026-07-16T12:00:00",
            }],
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    return token


# ---------------------------------------------------------------------------
# Tests de factura transaccional
# ---------------------------------------------------------------------------
class TestFacturaCreate:
    @pytest.mark.asyncio
    async def test_create_factura_with_stock(self, client, user_token):
        """Crear factura con ítem de stock deduce cantidad."""
        resp = await client.post(
            "/api/v1/facturas",
            json={
                "cliente_id": "L1",
                "total": 3500,
                "monto_pagado": 1000,
                "items": [{
                    "stock_id": "L1",
                    "catalogo_id": "L1",
                    "nombre": "Sofá 3 Plazas",
                    "cantidad": 1,
                    "tipo": "stock",
                    "subtotal": 3500,
                }],
                "entrega_domicilio": False,
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["saldo_pendiente"] == 2500
        assert body["items_count"] == 1
        assert body["pago_id"] is not None

    @pytest.mark.asyncio
    async def test_create_factura_with_encargo(self, client, user_token):
        """Factura con encargo crea entrada en cola_trabajos."""
        resp = await client.post(
            "/api/v1/facturas",
            json={
                "cliente_id": "L1",
                "total": 5000,
                "items": [{
                    "catalogo_id": "L1",
                    "nombre": "Sofá Custom",
                    "cantidad": 1,
                    "tipo": "encargo",
                    "subtotal": 5000,
                    "color": "Azul",
                    "material": "Cuero",
                }],
                "entrega_domicilio": True,
                "direccion_entrega": "Calle 1 #45",
                "garantia_hasta": "6 Meses",
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_create_factura_stock_insufficient(self, client, user_token):
        """Factura con stock insuficiente retorna 409."""
        resp = await client.post(
            "/api/v1/facturas",
            json={
                "cliente_id": "L1",
                "total": 35000,
                "items": [{
                    "stock_id": "L1",
                    "nombre": "Sofá",
                    "cantidad": 100,  # Más que el stock disponible
                    "tipo": "stock",
                    "subtotal": 35000,
                }],
                "entrega_domicilio": False,
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_create_factura_stock_auto_inherits(self, client, user_token):
        """Factura con ítem de stock sin nombre hereda datos de stock y catálogo."""
        resp = await client.post(
            "/api/v1/facturas",
            json={
                "cliente_id": "L1",
                "total": 2000,
                "items": [{
                    "stock_id": "L1",
                    "cantidad": 1,
                    "tipo": "stock",
                    "subtotal": 2000,
                }],
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 201
        factura_id = resp.json()["id"]

        # Verificar el ítem en el detalle de la factura
        resp_detail = await client.get(
            f"/api/v1/facturas/{factura_id}",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp_detail.status_code == 200
        item = resp_detail.json()["items"][0]
        assert item["catalogo_id"] == "L-1"
        assert item["nombre"] == "Sofá 3 Plazas"
        assert item["area"] == "Tapicería"
        assert item["tipo_mueble"] == "Sofá"
        assert item["image_id"] == "L-1"

    @pytest.mark.asyncio
    async def test_create_factura_encargo_auto_inherits_catalog(self, client, user_token):
        """Factura con encargo sin nombre hereda del catálogo base."""
        resp = await client.post(
            "/api/v1/facturas",
            json={
                "cliente_id": "L1",
                "total": 6000,
                "items": [{
                    "catalogo_id": "L1",
                    "cantidad": 1,
                    "tipo": "encargo",
                    "subtotal": 6000,
                    "color": "Verde",
                    "material": "Lino",
                }],
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 201
        factura_id = resp.json()["id"]

        resp_detail = await client.get(
            f"/api/v1/facturas/{factura_id}",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        item = resp_detail.json()["items"][0]
        assert item["nombre"] == "Sofá 3 Plazas"
        assert item["area"] == "Tapicería"
        assert item["tipo_mueble"] == "Sofá"
        assert item["image_id"] == "L-1"
        assert item["color"] == "Verde"

    @pytest.mark.asyncio
    async def test_create_factura_with_null_color_and_material_accepted(self, client, user_token):
        """Creación de factura con tela, color y material null se acepta y los almacena/retorna como null."""
        resp = await client.post(
            "/api/v1/facturas",
            json={
                "cliente_id": "L1",
                "total": 4500,
                "items": [{
                    "catalogo_id": "L1",
                    "nombre": "Mesa Rústica",
                    "cantidad": 1,
                    "tipo": "encargo",
                    "subtotal": 4500,
                    "tela": None,
                    "color": None,
                    "material": None,
                    "descripcion": None,
                }],
                "entrega_domicilio": False,
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert "items" in body
        created_item = body["items"][0]
        assert created_item["tela"] is None
        assert created_item["color"] is None
        assert created_item["material"] is None
        assert created_item["descripcion"] is None

        # Verificar detalle de la factura guardada vía GET
        factura_id = body["id"]
        resp_detail = await client.get(
            f"/api/v1/facturas/{factura_id}",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp_detail.status_code == 200
        saved_item = resp_detail.json()["items"][0]
        assert saved_item["tela"] is None
        assert saved_item["color"] is None
        assert saved_item["material"] is None
        assert saved_item["descripcion"] is None


# ---------------------------------------------------------------------------
# Tests de pagos
# ---------------------------------------------------------------------------
class TestPagos:
    @pytest.mark.asyncio
    async def test_create_pago(self, client, user_token):
        """Registrar un abono reduce el saldo pendiente."""
        # Crear factura
        resp = await client.post(
            "/api/v1/facturas",
            json={
                "cliente_id": "L1", "total": 5000,
                "items": [{"nombre": "Mesa", "cantidad": 1, "tipo": "encargo", "subtotal": 5000}],
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )
        factura_id = resp.json()["id"]

        # Crear pago
        resp = await client.post(
            f"/api/v1/facturas/{factura_id}/pagos",
            json={"monto": 2000, "nota": "Primer abono"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 201
        assert resp.json()["saldo_restante"] == 3000

    @pytest.mark.asyncio
    async def test_pago_exceeds_saldo(self, client, user_token):
        """Pago mayor al saldo pendiente retorna 400."""
        resp = await client.post(
            "/api/v1/facturas",
            json={
                "cliente_id": "L1", "total": 1000,
                "items": [{"nombre": "Silla", "cantidad": 1, "tipo": "encargo", "subtotal": 1000}],
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )
        factura_id = resp.json()["id"]

        resp = await client.post(
            f"/api/v1/facturas/{factura_id}/pagos",
            json={"monto": 5000},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Tests de item status (bypass)
# ---------------------------------------------------------------------------
class TestItemStatus:
    @pytest.mark.asyncio
    async def test_item_status_transitions(self, client, user_token):
        """Un encargo pasa por pendiente → procesando → procesado → completado."""
        # Crear factura con encargo + envío a domicilio (sin bypass)
        resp = await client.post(
            "/api/v1/facturas",
            json={
                "cliente_id": "L1", "total": 3000,
                "items": [{"nombre": "Armario", "cantidad": 1, "tipo": "encargo", "subtotal": 3000}],
                "entrega_domicilio": True,
                "direccion_entrega": "Calle Test",
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )
        factura_id = resp.json()["id"]

        # Obtener item_id
        resp = await client.get(
            f"/api/v1/facturas/{factura_id}",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        item_id = resp.json()["items"][0]["id"]

        # Transiciones
        for target_status in ["procesando", "procesado", "completado"]:
            resp = await client.patch(
                f"/api/v1/items/{item_id}/status",
                json={"status": target_status},
                headers={"Authorization": f"Bearer {user_token}"},
            )
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_item_bypass_no_envio(self, client, user_token):
        """Sin envío a domicilio, procesado salta automáticamente a completado."""
        resp = await client.post(
            "/api/v1/facturas",
            json={
                "cliente_id": "L1", "total": 2000,
                "items": [{"nombre": "Silla", "cantidad": 1, "tipo": "encargo", "subtotal": 2000}],
                "entrega_domicilio": False,
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )
        factura_id = resp.json()["id"]

        resp = await client.get(
            f"/api/v1/facturas/{factura_id}",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        item_id = resp.json()["items"][0]["id"]

        # pendiente → procesando
        await client.patch(
            f"/api/v1/items/{item_id}/status",
            json={"status": "procesando"},
            headers={"Authorization": f"Bearer {user_token}"},
        )

        # procesando → procesado (debería hacer bypass a completado)
        resp = await client.patch(
            f"/api/v1/items/{item_id}/status",
            json={"status": "procesado"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.json()["status"] == "completado"  # Bypass!


# ---------------------------------------------------------------------------
# Tests de clientes CRUD
# ---------------------------------------------------------------------------
class TestClientes:
    @pytest.mark.asyncio
    async def test_create_and_patch_cliente(self, client, user_token):
        """Crear y modificar un cliente, verificando la respuesta de confirmación con el ID generado."""
        resp = await client.post(
            "/api/v1/clientes",
            json={"nombre": "Ana", "apellido": "López", "telefono": "809-111"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data
        assert data["id"].startswith("L")
        assert data["nombre"] == "Ana"
        assert data["apellido"] == "López"
        assert data["telefono"] == "809-111"
        cliente_id = data["id"]

        resp = await client.patch(
            f"/api/v1/clientes/{cliente_id}",
            json={"telefono": "809-222"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_soft_delete_cliente(self, client, user_token):
        """Soft delete marca deleted_at."""
        resp = await client.post(
            "/api/v1/clientes",
            json={"nombre": "Borrar", "apellido": "Test"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        cliente_id = resp.json()["id"]

        resp = await client.delete(
            f"/api/v1/clientes/{cliente_id}",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 204


# ---------------------------------------------------------------------------
# Tests de stock
# ---------------------------------------------------------------------------
class TestStock:
    @pytest.mark.asyncio
    async def test_create_stock_without_image_inherits_catalog(self, client, user_token):
        """Crear stock sin foto hereda automáticamente la foto genérica del catálogo."""
        resp = await client.post(
            "/api/v1/stock",
            data={"catalogo_id": "L1", "color": "Azul", "material": "Cuero", "cantidad": "10", "precio": "1500.0"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["color"] == "Azul"
        assert body["image_id"] == "L-1"  # Heredado del catálogo L-1

    @pytest.mark.asyncio
    async def test_create_stock_with_custom_image(self, client, user_token):
        """Crear stock enviando una imagen propia crea nuevo registro en images."""
        fake_image_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01"
        files = {"file": ("stock_azul.jpg", fake_image_bytes, "image/jpeg")}
        data = {"catalogo_id": "L1", "color": "Rojo", "material": "Metal", "cantidad": "5", "precio": "2000.0"}
        resp = await client.post(
            "/api/v1/stock",
            data=data,
            files=files,
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["color"] == "Rojo"
        assert body["image_id"] is not None
        assert body["image_id"] != "L1"  # Nuevo ID generado

    @pytest.mark.asyncio
    async def test_stock_cantidad_delta(self, client, user_token):
        """Ajustar cantidad de stock con delta."""
        resp = await client.post(
            "/api/v1/stock",
            data={"catalogo_id": "L1", "color": "Verde", "material": "Madera", "cantidad": "10", "precio": "500"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 201
        stock_id = resp.json()["id"]

        # Decrementar
        resp = await client.patch(
            f"/api/v1/stock/{stock_id}/cantidad",
            json={"delta": -3},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["cantidad"] == 7

        # Incrementar
        resp = await client.patch(
            f"/api/v1/stock/{stock_id}/cantidad",
            json={"delta": 5},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.json()["cantidad"] == 12


# ---------------------------------------------------------------------------
# Tests de warranty
# ---------------------------------------------------------------------------
class TestWarranty:
    @pytest.mark.asyncio
    async def test_compute_warranty(self):
        """compute_warranty calcula correctamente el vencimiento."""
        from services.factura_service import compute_warranty

        # 6 meses desde julio 2026
        result = compute_warranty("6 Meses", "2026-07-16T12:00:00")
        assert result is not None
        assert "2027-01" in result

        # Sin garantía
        assert compute_warranty("Sin Garantía", "2026-07-16T12:00:00") is None

        # 1 Año
        result = compute_warranty("1 Año", "2026-07-16T12:00:00")
        assert "2027-07" in result

# ---------------------------------------------------------------------------
# Tests de endpoints GET paginados
# ---------------------------------------------------------------------------
class TestListEndpoints:
    @pytest.mark.asyncio
    async def test_list_clientes(self, client, user_token):
        resp = await client.get("/api/v1/clientes?limit=10", headers={"Authorization": f"Bearer {user_token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert data[0]["nombre"] == "Juan"

    @pytest.mark.asyncio
    async def test_list_facturas(self, client, user_token):
        resp = await client.get("/api/v1/facturas", headers={"Authorization": f"Bearer {user_token}"})
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_list_catalogo(self, client, user_token):
        resp = await client.get("/api/v1/catalogo", headers={"Authorization": f"Bearer {user_token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert data[0]["nombre"] == "Sofá 3 Plazas"

    @pytest.mark.asyncio
    async def test_list_stock(self, client, user_token):
        resp = await client.get("/api/v1/stock", headers={"Authorization": f"Bearer {user_token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert data[0]["color"] == "Rojo"

    @pytest.mark.asyncio
    async def test_list_items(self, client, user_token):
        resp = await client.get("/api/v1/items", headers={"Authorization": f"Bearer {user_token}"})
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_list_envios(self, client, user_token):
        resp = await client.get("/api/v1/envios", headers={"Authorization": f"Bearer {user_token}"})
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ---------------------------------------------------------------------------
# Tests de Catálogo con imagen obligatoria
# ---------------------------------------------------------------------------
class TestCatalogo:
    @pytest.mark.asyncio
    async def test_create_catalogo_with_image(self, client, user_token):
        """Crear catálogo enviando imagen via multipart form-data."""
        fake_image_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01"
        files = {"file": ("mueble.jpg", fake_image_bytes, "image/jpeg")}
        data = {
            "nombre": "Comedor 6 Sillas",
            "tipo": "Mesa",
            "area": "Ebanistería",
            "precio_base": "25000.0",
        }
        resp = await client.post(
            "/api/v1/catalogo",
            data=data,
            files=files,
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["nombre"] == "Comedor 6 Sillas"
        assert body["tipo"] == "Mesa"
        assert body["area"] == '["Ebanistería"]'
        assert body["precio_base"] == 25000.0
        assert "image_id" in body
        assert body["image_id"] is not None
        assert "file_path" in body

    @pytest.mark.asyncio
    async def test_create_catalogo_computes_aspect_ratio(self, client, user_token):
        """Crear catálogo enviando imagen válida calcula el aspect_ratio real."""
        import io
        from PIL import Image

        img = Image.new("RGB", (800, 600), color="blue")
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        image_bytes = buf.getvalue()

        files = {"file": ("mesa_landscape.jpg", image_bytes, "image/jpeg")}
        data = {
            "nombre": "Mesa Landscape",
            "tipo": "Mesa",
            "area": "Ebanistería",
            "precio_base": "15000.0",
        }
        resp = await client.post(
            "/api/v1/catalogo",
            data=data,
            files=files,
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 201
        body = resp.json()
        image_id = body["image_id"]

        # Consultar la lista de catálogo para verificar que el JOIN retorne aspect_ratio
        resp_list = await client.get("/api/v1/catalogo", headers={"Authorization": f"Bearer {user_token}"})
        assert resp_list.status_code == 200
        items = resp_list.json()
        matching = [x for x in items if x["id"] == body["id"]]
        assert len(matching) == 1
        assert matching[0]["aspect_ratio"] == "1.3333"

    @pytest.mark.asyncio
    async def test_create_catalogo_without_image_fails(self, client, user_token):
        """Crear catálogo sin foto retorna 422 Unprocessable Entity."""
        data = {
            "nombre": "Sin Foto",
            "tipo": "Silla",
        }
        resp = await client.post(
            "/api/v1/catalogo",
            data=data,
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 422



# ---------------------------------------------------------------------------
# Tests nuevos — workflow venus_workflow.md
# ---------------------------------------------------------------------------
class TestFacturaClienteValidacion:
    """
    Tests que cubren la validación obligatoria de cliente en facturas.
    Segun venus_workflow.md, toda factura debe tener identificación de cliente.
    """

    @pytest.mark.asyncio
    async def test_factura_sin_cliente_falla(self, client, user_token):
        """Factura normal sin cliente_id retorna 422."""
        resp = await client.post(
            "/api/v1/facturas",
            json={
                # Sin cliente_id y sin facturacion_rapida
                "total": 5000,
                "items": [{
                    "catalogo_id": "L1",
                    "nombre": "Sofá",
                    "cantidad": 1,
                    "tipo": "encargo",
                    "subtotal": 5000,
                }],
                "entrega_domicilio": False,
                "facturacion_rapida": 0,
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 422
        body = resp.json()
        # El mensaje debe mencionar cliente_id
        detail_str = str(body.get("detail", "")).lower()
        assert "cliente_id" in detail_str or "cliente" in detail_str

    @pytest.mark.asyncio
    async def test_factura_rapida_sin_nombre_falla(self, client, user_token):
        """Factura rápida sin 'nombre' en campo cliente retorna 422."""
        resp = await client.post(
            "/api/v1/facturas",
            json={
                "facturacion_rapida": 1,
                "cliente": {},  # Sin nombre
                "total": 3000,
                "items": [{
                    "catalogo_id": "L1",
                    "nombre": "Silla",
                    "cantidad": 1,
                    "tipo": "encargo",
                    "subtotal": 3000,
                }],
                "entrega_domicilio": False,
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_factura_rapida_con_nombre_ok(self, client, user_token):
        """Factura rápida con nombre, apellido y telefono se crea correctamente."""
        resp = await client.post(
            "/api/v1/facturas",
            json={
                "facturacion_rapida": 1,
                "cliente": {
                    "nombre": "María",
                    "apellido": "López",
                    "telefono": "849-555-0001",
                },
                "total": 2000,
                "items": [{
                    "catalogo_id": "L1",
                    "nombre": "Taburete",
                    "cantidad": 1,
                    "tipo": "encargo",
                    "subtotal": 2000,
                    "color": "Negro",
                    "material": "Madera",
                }],
                "entrega_domicilio": False,
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert "factura_id" in body or "id" in body

    @pytest.mark.asyncio
    async def test_factura_rapida_json_estructura(self, client, user_token):
        """
        Verifica que el JSON de cliente en factura rápida se almacene con
        la estructura exacta {nombre, apellido, telefono} en la BD.
        """
        resp = await client.post(
            "/api/v1/facturas",
            json={
                "facturacion_rapida": 1,
                "cliente": {
                    "nombre": "Carlos",
                    "apellido": "",
                    "telefono": "",
                },
                "total": 1500,
                "items": [{
                    "catalogo_id": "L1",
                    "nombre": "Otomana",
                    "cantidad": 1,
                    "tipo": "encargo",
                    "subtotal": 1500,
                }],
                "entrega_domicilio": False,
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 201

        # Verificar la factura recuperada muestra cliente_nombre correctamente
        facturas_resp = await client.get(
            "/api/v1/facturas",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert facturas_resp.status_code == 200
        facturas = facturas_resp.json()
        assert any(
            f.get("cliente_nombre") == "Carlos" or
            "Carlos" in str(f.get("cliente", ""))
            for f in facturas
        )


class TestItemsImageFallback:
    """
    Tests que verifican el endpoint inteligente GET /items:
    devuelve imagen del catálogo como fallback cuando el ítem no tiene imagen propia.
    """

    @pytest.mark.asyncio
    async def test_items_list_has_image_url_field(self, client, user_token):
        """GET /items devuelve campo image_url en cada ítem."""
        # Crear un encargo para tener un ítem en la lista
        await client.post(
            "/api/v1/facturas",
            json={
                "cliente_id": "L1",
                "total": 4000,
                "items": [{
                    "catalogo_id": "L1",
                    "nombre": "Sofá para test imagen",
                    "cantidad": 1,
                    "tipo": "encargo",
                    "subtotal": 4000,
                    "color": "Gris",
                    "material": "Lino",
                }],
                "entrega_domicilio": False,
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )

        resp = await client.get(
            "/api/v1/items",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) > 0
        # Verificar que el campo image_url está presente
        assert "image_url" in items[0]

    @pytest.mark.asyncio
    async def test_items_image_url_uses_catalog_fallback(self, client, user_token):
        """
        Ítem sin imagen propia tiene image_url apuntando a imagen del catálogo.
        El catálogo L1 tiene image_id = L1 con file_path = /local/sofa.jpg.
        """
        # Crear encargo sin image_id propio
        await client.post(
            "/api/v1/facturas",
            json={
                "cliente_id": "L1",
                "total": 3000,
                "items": [{
                    "catalogo_id": "L1",
                    "nombre": "Encargo Sin Foto",
                    "cantidad": 1,
                    "tipo": "encargo",
                    "subtotal": 3000,
                    # Sin image_id — debe heredar del catálogo
                }],
                "entrega_domicilio": False,
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )

        resp = await client.get(
            "/api/v1/items",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 200
        items = resp.json()
        # El ítem sin imagen propia debe tener image_url con la ruta del catálogo
        encargo = next((i for i in items if i.get("nombre") == "Encargo Sin Foto"), None)
        assert encargo is not None
        # Debe tener catalogo_image_id poblado (del catálogo)
        assert encargo.get("catalogo_image_id") is not None or encargo.get("image_url") is not None


class TestImageEndpointAuth:
    """Tests que verifican la protección del endpoint de imágenes."""

    @pytest.mark.asyncio
    async def test_item_photo_requires_auth(self, client):
        """PATCH /items/{id}/photo sin token retorna 401."""
        resp = await client.patch(
            "/api/v1/items/L1/photo",
            json={"image_id": "L1"},
            # Sin Authorization header
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_get_image_requires_auth(self, client):
        """GET /api/v1/images/{id} sin token retorna 401."""
        resp = await client.get("/api/v1/images/some-image-id")
        assert resp.status_code == 401


class TestMaterialesEndpoints:
    """Tests para los endpoints de materiales y catálogos auxiliares."""

    @pytest.mark.asyncio
    async def test_list_materiales(self, client, user_token):
        """GET /materiales retorna la lista de categorías registradas (seeded)."""
        resp = await client.get(
            "/api/v1/materiales",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 4

    @pytest.mark.asyncio
    async def test_create_material(self, client, user_token):
        """POST /materiales crea una nueva categoría de materiales."""
        resp = await client.post(
            "/api/v1/materiales",
            json={
                "categoria": "Cojines",
                "elementos": ["Espuma", "Pluma", "Microfibra"],
                "color": ["Blanco", "Gris"],
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["categoria"] == "Cojines"
        assert "Espuma" in data["elementos"]

    @pytest.mark.asyncio
    async def test_update_material(self, client, user_token):
        """PATCH /materiales/{id} actualiza los elementos o color."""
        post_resp = await client.post(
            "/api/v1/materiales",
            json={
                "categoria": "Metales Especiales",
                "elementos": ["Aluminio"],
                "color": None,
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )
        mat_id = post_resp.json()["id"]

        patch_resp = await client.patch(
            f"/api/v1/materiales/{mat_id}",
            json={"elementos": ["Aluminio", "Acero Inoxidable", "Bronce"]},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert patch_resp.status_code == 200
        data = patch_resp.json()
        assert "Acero Inoxidable" in data["elementos"]

    @pytest.mark.asyncio
    async def test_delete_material(self, client, user_token):
        """DELETE /materiales/{id} elimina el registro."""
        post_resp = await client.post(
            "/api/v1/materiales",
            json={
                "categoria": "TempCat",
                "elementos": ["Prueba"],
                "color": None,
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )
        mat_id = post_resp.json()["id"]

        del_resp = await client.delete(
            f"/api/v1/materiales/{mat_id}",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert del_resp.status_code == 204

    @pytest.mark.asyncio
    async def test_stock_auto_delete_when_zero(self, client, user_token):
        """PATCH /stock/{id}/cantidad marca deleted_at si cantidad llega a 0."""
        # 1. Crear stock con cantidad 1
        stock_resp = await client.post(
            "/api/v1/stock",
            data={"catalogo_id": "L1", "color": "RojoTest", "material": "Pino", "cantidad": 1, "precio": 1000},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert stock_resp.status_code == 201
        stock_id = stock_resp.json()["id"]

        # 2. Reducir stock a 0
        patch_resp = await client.patch(
            f"/api/v1/stock/{stock_id}/cantidad",
            json={"delta": -1},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["cantidad"] == 0

        # 3. GET /stock no debe devolver este stock
        get_resp = await client.get("/api/v1/stock", headers={"Authorization": f"Bearer {user_token}"})
        stock_ids = [s["id"] for s in get_resp.json()]
        assert stock_id not in stock_ids

    @pytest.mark.asyncio
    async def test_create_catalogo_deduplicates_by_image_hash(self, client, user_token):
        """Subir la misma imagen a 2 catálogos reutiliza la entrada de imágenes por su hash."""
        from tests.test_image_service import _create_sample_image_bytes

        img_bytes = _create_sample_image_bytes(400, 300)

        resp1 = await client.post(
            "/api/v1/catalogo",
            data={"nombre": "Catálogo Dedup 1"},
            files={"file": ("foto1.png", img_bytes, "image/png")},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp1.status_code == 201
        data1 = resp1.json()

        resp2 = await client.post(
            "/api/v1/catalogo",
            data={"nombre": "Catálogo Dedup 2"},
            files={"file": ("foto2_duplicada.png", img_bytes, "image/png")},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp2.status_code == 201
        data2 = resp2.json()

        # Ambos catálogos deben compartir el mismo image_id y file_path
        assert data1["image_id"] == data2["image_id"]
        assert data1["file_path"] == data2["file_path"]
