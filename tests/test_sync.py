"""
Tests de sincronización — Pasos 5 y 6.

Verifica push, pull, upload_image y descarga de imagen.
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
async def admin_token(client):
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "pichardo", "password": "admin123"},
    )
    return resp.json()["access_token"]


@pytest_asyncio.fixture
async def user_setup(client, admin_token):
    """Crea usuario 'laura' con prefijo 'L' y retorna (token, prefix)."""
    await client.post(
        "/api/v1/admin/users",
        json={"username": "laura", "password": "secreto", "prefix": "L"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "laura", "password": "secreto"},
    )
    return resp.json()["access_token"], "L"


@pytest_asyncio.fixture
async def user_token(user_setup):
    return user_setup[0]


# ---------------------------------------------------------------------------
# Tests de Push
# ---------------------------------------------------------------------------
class TestPush:
    @pytest.mark.asyncio
    async def test_push_clientes(self, client, user_token):
        """Push de clientes ejecuta UPSERT correctamente."""
        resp = await client.post(
            "/api/v1/sync/push",
            json={
                "clientes": [
                    {
                        "local_id": 1,
                        "nombre": "Juan",
                        "apellido": "Pérez",
                        "telefono": "809-555-0001",
                        "updated_at": "2026-07-16T12:00:00",
                    },
                    {
                        "local_id": 2,
                        "nombre": "María",
                        "apellido": "García",
                        "updated_at": "2026-07-16T12:00:00",
                    },
                ]
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["upserted"]["clientes"] == 2

    @pytest.mark.asyncio
    async def test_push_empty_payload(self, client, user_token):
        """Push con payload vacío retorna contadores en 0."""
        resp = await client.post(
            "/api/v1/sync/push",
            json={},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert all(v == 0 for v in body["upserted"].values())

    @pytest.mark.asyncio
    async def test_push_lww_newer_wins(self, client, user_token):
        """Un registro más nuevo sobrescribe al antiguo (LWW)."""
        # Primero: insertar con timestamp viejo
        await client.post(
            "/api/v1/sync/push",
            json={
                "clientes": [{
                    "local_id": 10,
                    "nombre": "Viejo",
                    "apellido": "Nombre",
                    "updated_at": "2026-07-15T00:00:00",
                }]
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )

        # Segundo: actualizar con timestamp más nuevo
        await client.post(
            "/api/v1/sync/push",
            json={
                "clientes": [{
                    "local_id": 10,
                    "nombre": "Nuevo",
                    "apellido": "Nombre",
                    "updated_at": "2026-07-16T00:00:00",
                }]
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )

        # Pull para verificar
        resp = await client.get(
            "/api/v1/sync/pull",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        clientes = resp.json()["clientes"]
        match = [c for c in clientes if c["local_id"] == 10]
        assert len(match) == 1
        assert match[0]["nombre"] == "Nuevo"

    @pytest.mark.asyncio
    async def test_push_lww_older_ignored(self, client, user_token):
        """Un registro más viejo NO sobrescribe al existente (LWW)."""
        # Primero: insertar con timestamp nuevo
        await client.post(
            "/api/v1/sync/push",
            json={
                "clientes": [{
                    "local_id": 20,
                    "nombre": "Correcto",
                    "apellido": "Test",
                    "updated_at": "2026-07-16T12:00:00",
                }]
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )

        # Segundo: intentar con timestamp más viejo
        await client.post(
            "/api/v1/sync/push",
            json={
                "clientes": [{
                    "local_id": 20,
                    "nombre": "Incorrecto",
                    "apellido": "Test",
                    "updated_at": "2026-07-15T00:00:00",
                }]
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )

        # Pull para verificar que se mantuvo el nombre correcto
        resp = await client.get(
            "/api/v1/sync/pull",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        clientes = resp.json()["clientes"]
        match = [c for c in clientes if c["local_id"] == 20]
        assert match[0]["nombre"] == "Correcto"

    @pytest.mark.asyncio
    async def test_push_admin_denied(self, client, admin_token):
        """El admin no puede hacer push (no tiene prefijo)."""
        resp = await client.post(
            "/api/v1/sync/push",
            json={"clientes": []},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Tests de Pull
# ---------------------------------------------------------------------------
class TestPull:
    @pytest.mark.asyncio
    async def test_pull_returns_pushed_data(self, client, user_token):
        """Pull retorna los datos previamente pusheados con IDs enteros."""
        # Push
        await client.post(
            "/api/v1/sync/push",
            json={
                "clientes": [{
                    "local_id": 1,
                    "nombre": "Test",
                    "apellido": "Pull",
                    "updated_at": "2026-07-16T12:00:00",
                }]
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )

        # Pull
        resp = await client.get(
            "/api/v1/sync/pull",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "clientes" in body
        assert len(body["clientes"]) == 1
        assert body["clientes"][0]["local_id"] == 1  # ID entero, no "L1"
        assert body["clientes"][0]["nombre"] == "Test"

    @pytest.mark.asyncio
    async def test_pull_delta_with_last_sync(self, client, user_token):
        """Pull con last_sync solo retorna registros más recientes."""
        # Push registro viejo
        await client.post(
            "/api/v1/sync/push",
            json={
                "clientes": [{
                    "local_id": 100,
                    "nombre": "Viejo",
                    "apellido": "V",
                    "updated_at": "2026-07-14T00:00:00",
                }]
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )

        # Push registro nuevo
        await client.post(
            "/api/v1/sync/push",
            json={
                "clientes": [{
                    "local_id": 101,
                    "nombre": "Nuevo",
                    "apellido": "N",
                    "updated_at": "2026-07-16T12:00:00",
                }]
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )

        # Pull delta
        resp = await client.get(
            "/api/v1/sync/pull?last_sync=2026-07-15T00:00:00",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        clientes = resp.json()["clientes"]
        ids = [c["local_id"] for c in clientes]
        assert 101 in ids
        assert 100 not in ids  # Demasiado viejo

    @pytest.mark.asyncio
    async def test_pull_empty_tables(self, client, user_token):
        """Pull sin datos previos retorna listas vacías."""
        resp = await client.get(
            "/api/v1/sync/pull",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        for table_data in body.values():
            assert isinstance(table_data, list)


# ---------------------------------------------------------------------------
# Tests de push complejo (múltiples entidades con FKs)
# ---------------------------------------------------------------------------
class TestPushComplex:
    @pytest.mark.asyncio
    async def test_push_full_workflow(self, client, user_token):
        """Push completo con clientes, imágenes, catálogo, stock, factura, items."""
        payload = {
            "clientes": [{
                "local_id": 1,
                "nombre": "Carlos",
                "apellido": "Mendez",
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
                "tela": "Rojo",
                "material": "Tela",
                "cantidad": 2,
                "precio": 3500,
                "image_id": 1,
                "updated_at": "2026-07-16T12:00:00",
            }],
            "facturas": [{
                "local_id": 1,
                "cliente_id": 1,
                "fecha": "2026-07-16T10:00:00",
                "total": 3500,
                "saldo_pendiente": 3500,
                "items_id": "1",
                "entrega_domicilio": False,
                "updated_at": "2026-07-16T12:00:00",
            }],
            "items": [{
                "local_id": 1,
                "factura_id": 1,
                "stock_id": 1,
                "catalogo_id": 1,
                "image_id": 1,
                "nombre": "Sofá 3 Plazas",
                "cantidad": 1,
                "tipo": "stock",
                "subtotal": 3500,
                "tela": "Rojo",
                "material": "Tela",
                "status": "procesado",
                "area": "Tapicería",
                "tipo_mueble": "Sofá",
                "created_at": "2026-07-16T10:00:00",
                "updated_at": "2026-07-16T12:00:00",
            }],
        }

        resp = await client.post(
            "/api/v1/sync/push",
            json=payload,
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["upserted"]["clientes"] == 1
        assert body["upserted"]["catalogo"] == 1
        assert body["upserted"]["stock"] == 1
        assert body["upserted"]["facturas"] == 1
        assert body["upserted"]["items"] == 1

        # Verificar pull
        resp = await client.get(
            "/api/v1/sync/pull",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        pull = resp.json()
        assert len(pull["clientes"]) == 1
        assert len(pull["facturas"]) == 1
        # Verificar que el items_id se transformó de vuelta
        assert pull["facturas"][0]["items_id"] == "1"
        assert pull["items"][0]["factura_id"] == 1


# ---------------------------------------------------------------------------
# Tests de upload_image
# ---------------------------------------------------------------------------
class TestUploadImage:
    @pytest.mark.asyncio
    async def test_upload_image_calculates_aspect_ratio(self, client, user_token):
        """upload_image guarda la imagen física y registra su aspect_ratio real."""
        import io
        from PIL import Image

        # Crear imagen vertical 600x800 -> aspect_ratio = 0.75
        img = Image.new("RGB", (600, 800), color="green")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        image_bytes = buf.getvalue()

        files = {"file": ("foto_vertical.png", image_bytes, "image/png")}
        data = {"local_image_id": "42"}

        resp = await client.post(
            "/api/v1/sync/upload_image",
            data=data,
            files=files,
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["local_image_id"] == 42
        assert body["aspect_ratio"] == "0.75"
        assert "remote_path" in body
