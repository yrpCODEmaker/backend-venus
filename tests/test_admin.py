"""
Venus Backend — Tests de administración y permisos granulares.

Cubre:
1. CRUD de usuarios (crear, listar, editar, eliminar, toggle).
2. Lectura y escritura de permisos (GET/PUT /permissions).
3. Ajuste de visibilidad de datos (PATCH /data-visibility).
4. Reglas críticas de seguridad:
   - El admin no puede eliminarse ni bloquearse a sí mismo.
   - No se puede cambiar el prefijo del admin.
   - `prefijos_visibles` solo acepta prefijos de usuarios existentes.
5. Guards en módulos operacionales:
   - Un usuario sin permiso `facturas_emitir` recibe 403 al crear factura.
   - Un usuario sin permiso `clientes_crear` recibe 403 al ver clientes.
   - El admin siempre tiene acceso total.

Estrategia:
- Usa una BD SQLite en memoria (:memory:) inyectada vía override de `get_db`.
- No depende de red ni de archivos externos.
- Cada test es idempotente gracias al fixture `app_client` que reinicializa la BD.
"""

import json
import pytest
import pytest_asyncio
import aiosqlite

from httpx import AsyncClient, ASGITransport
from fastapi import status

from main import app
from database import init_db, get_db
from services.auth import create_access_token


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DB_PATH_TEST = ":memory:"

@pytest_asyncio.fixture
async def db_conn():
    """Conexión SQLite en memoria con todas las tablas inicializadas."""
    # init_db necesita una ruta; usamos un archivo temporal único por test
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        tmp_path = f.name
    await init_db(db_path=tmp_path)

    conn = await aiosqlite.connect(tmp_path)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA foreign_keys=ON")

    yield conn

    await conn.close()
    os.unlink(tmp_path)


@pytest_asyncio.fixture
async def app_client(db_conn):
    """
    AsyncClient con override de get_db apuntando a la BD en memoria del test.
    Los tokens se generan directamente sin hacer POST /login.
    """
    async def override_get_db():
        yield db_conn

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client

    app.dependency_overrides.clear()


def admin_token() -> str:
    """Token JWT de admin 'pichardo' (rol=admin, prefix=P)."""
    return create_access_token({"sub": "pichardo", "role": "admin", "prefix": "P"})


def user_token(username: str, prefix: str) -> str:
    """Token JWT para un usuario regular."""
    return create_access_token({"sub": username, "role": "user", "prefix": prefix})


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ===========================================================================
# Tests de CRUD de usuarios
# ===========================================================================

class TestUserCRUD:
    async def test_list_users_as_admin(self, app_client):
        """El admin puede listar usuarios."""
        resp = await app_client.get(
            "/api/v1/admin/users",
            headers=auth_headers(admin_token()),
        )
        assert resp.status_code == status.HTTP_200_OK
        users = resp.json()
        usernames = [u["username"] for u in users]
        assert "pichardo" in usernames

    async def test_list_users_forbidden_for_regular_user(self, app_client, db_conn):
        """Un usuario regular no puede listar usuarios."""
        # Crear usuario regular
        await _create_test_user(db_conn, "juan", "X")
        resp = await app_client.get(
            "/api/v1/admin/users",
            headers=auth_headers(user_token("juan", "X")),
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    async def test_create_user_success(self, app_client):
        """El admin puede crear un usuario con prefijo único."""
        resp = await app_client.post(
            "/api/v1/admin/users",
            json={"username": "maria", "password": "secret123", "prefix": "M"},
            headers=auth_headers(admin_token()),
        )
        assert resp.status_code == status.HTTP_201_CREATED
        data = resp.json()
        assert data["username"] == "maria"
        assert data["prefix"] == "M"
        assert data["rol"] == "user"
        assert data["activo"] is True

    async def test_create_user_duplicate_username(self, app_client):
        """409 al crear usuario con username duplicado."""
        await app_client.post(
            "/api/v1/admin/users",
            json={"username": "carlos", "password": "pass123", "prefix": "C"},
            headers=auth_headers(admin_token()),
        )
        resp = await app_client.post(
            "/api/v1/admin/users",
            json={"username": "carlos", "password": "other", "prefix": "D"},
            headers=auth_headers(admin_token()),
        )
        assert resp.status_code == status.HTTP_409_CONFLICT

    async def test_create_user_duplicate_prefix(self, app_client):
        """409 al crear usuario con prefijo duplicado."""
        await app_client.post(
            "/api/v1/admin/users",
            json={"username": "pedro", "password": "pass123", "prefix": "PE"},
            headers=auth_headers(admin_token()),
        )
        resp = await app_client.post(
            "/api/v1/admin/users",
            json={"username": "pepe", "password": "pass123", "prefix": "PE"},
            headers=auth_headers(admin_token()),
        )
        assert resp.status_code == status.HTTP_409_CONFLICT

    async def test_update_user_password(self, app_client):
        """El admin puede cambiar la contraseña de un usuario."""
        await app_client.post(
            "/api/v1/admin/users",
            json={"username": "ana", "password": "oldpass", "prefix": "AN"},
            headers=auth_headers(admin_token()),
        )
        resp = await app_client.put(
            "/api/v1/admin/users/ana",
            json={"password": "newpass123"},
            headers=auth_headers(admin_token()),
        )
        assert resp.status_code == status.HTTP_200_OK

    async def test_update_user_no_fields_raises_400(self, app_client):
        """400 si no se proporciona ningún campo para actualizar."""
        await app_client.post(
            "/api/v1/admin/users",
            json={"username": "luis", "password": "pass123", "prefix": "LU"},
            headers=auth_headers(admin_token()),
        )
        resp = await app_client.put(
            "/api/v1/admin/users/luis",
            json={},
            headers=auth_headers(admin_token()),
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    async def test_admin_cannot_change_own_prefix(self, app_client):
        """El admin no puede cambiar su propio prefijo."""
        resp = await app_client.put(
            "/api/v1/admin/users/pichardo",
            json={"prefix": "Q"},
            headers=auth_headers(admin_token()),
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    async def test_delete_user_success(self, app_client):
        """El admin puede eliminar un usuario regular."""
        await app_client.post(
            "/api/v1/admin/users",
            json={"username": "todelete", "password": "pass123", "prefix": "TD"},
            headers=auth_headers(admin_token()),
        )
        resp = await app_client.delete(
            "/api/v1/admin/users/todelete",
            headers=auth_headers(admin_token()),
        )
        assert resp.status_code == status.HTTP_204_NO_CONTENT

    async def test_admin_cannot_delete_himself(self, app_client):
        """El admin no puede eliminarse a sí mismo."""
        resp = await app_client.delete(
            "/api/v1/admin/users/pichardo",
            headers=auth_headers(admin_token()),
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    async def test_delete_nonexistent_user_raises_404(self, app_client):
        """404 al intentar eliminar un usuario que no existe."""
        resp = await app_client.delete(
            "/api/v1/admin/users/nobody",
            headers=auth_headers(admin_token()),
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    async def test_toggle_user_activation(self, app_client):
        """El admin puede activar/desactivar un usuario."""
        await app_client.post(
            "/api/v1/admin/users",
            json={"username": "toggling", "password": "pass123", "prefix": "TG"},
            headers=auth_headers(admin_token()),
        )
        resp = await app_client.patch(
            "/api/v1/admin/users/toggling/toggle",
            headers=auth_headers(admin_token()),
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["activo"] is False

    async def test_toggle_self_raises_400(self, app_client):
        """El admin no puede desactivarse a sí mismo con toggle."""
        resp = await app_client.patch(
            "/api/v1/admin/users/pichardo/toggle",
            headers=auth_headers(admin_token()),
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


# ===========================================================================
# Tests de permisos granulares
# ===========================================================================

class TestPermissions:
    async def test_get_admin_permissions_total_access(self, app_client):
        """El admin tiene todos los permisos activados."""
        resp = await app_client.get(
            "/api/v1/admin/users/pichardo/permissions",
            headers=auth_headers(admin_token()),
        )
        assert resp.status_code == status.HTTP_200_OK
        perms = resp.json()
        # Todos los permisos del admin deben ser True
        bool_fields = [
            "facturas_ver", "facturas_emitir", "facturas_modificar",
            "fabricacion_ver_estados", "fabricacion_modificar_estados", "fabricacion_mandar_envio",
            "stock_crear", "stock_modificar", "stock_eliminar",
            "catalogo_crear", "catalogo_modificar", "catalogo_eliminar",
            "clientes_crear", "clientes_modificar", "clientes_eliminar",
            "puede_ver_datos_de_otros",
        ]
        for field in bool_fields:
            assert perms[field] is True, f"El admin debería tener {field}=True"

    async def test_get_regular_user_permissions_defaults(self, app_client):
        """Un usuario regular tiene permisos restrictivos por defecto."""
        await app_client.post(
            "/api/v1/admin/users",
            json={"username": "newuser", "password": "pass123", "prefix": "NU"},
            headers=auth_headers(admin_token()),
        )
        resp = await app_client.get(
            "/api/v1/admin/users/newuser/permissions",
            headers=auth_headers(admin_token()),
        )
        assert resp.status_code == status.HTTP_200_OK
        perms = resp.json()
        # Por defecto: solo lectura (ver estados)
        assert perms["facturas_ver"] is True
        assert perms["fabricacion_ver_estados"] is True
        # Sin permisos de escritura
        assert perms["facturas_emitir"] is False
        assert perms["stock_crear"] is False
        assert perms["clientes_crear"] is False

    async def test_update_permissions_partial(self, app_client):
        """El admin puede otorgar permisos específicos a un usuario."""
        await app_client.post(
            "/api/v1/admin/users",
            json={"username": "operator", "password": "pass123", "prefix": "OP"},
            headers=auth_headers(admin_token()),
        )
        resp = await app_client.put(
            "/api/v1/admin/users/operator/permissions",
            json={
                "facturas_emitir": True,
                "clientes_crear": True,
                "stock_crear": True,
            },
            headers=auth_headers(admin_token()),
        )
        assert resp.status_code == status.HTTP_200_OK
        perms = resp.json()
        assert perms["facturas_emitir"] is True
        assert perms["clientes_crear"] is True
        assert perms["stock_crear"] is True
        # Los no enviados no cambian
        assert perms["catalogo_crear"] is False

    async def test_update_permissions_empty_raises_400(self, app_client):
        """400 si no se envía ningún permiso."""
        await app_client.post(
            "/api/v1/admin/users",
            json={"username": "emptyperms", "password": "pass123", "prefix": "EP"},
            headers=auth_headers(admin_token()),
        )
        resp = await app_client.put(
            "/api/v1/admin/users/emptyperms/permissions",
            json={},
            headers=auth_headers(admin_token()),
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    async def test_permissions_endpoint_forbidden_for_regular_user(self, app_client, db_conn):
        """Un usuario regular no puede ver ni editar permisos."""
        await _create_test_user(db_conn, "spy", "SP")
        resp = await app_client.get(
            "/api/v1/admin/users/pichardo/permissions",
            headers=auth_headers(user_token("spy", "SP")),
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN


# ===========================================================================
# Tests de visibilidad de datos
# ===========================================================================

class TestDataVisibility:
    async def test_patch_data_visibility_success(self, app_client):
        """El admin puede habilitar visibilidad de datos entre usuarios."""
        # Crear un segundo usuario para tener su prefijo disponible
        await app_client.post(
            "/api/v1/admin/users",
            json={"username": "viewer", "password": "pass123", "prefix": "VW"},
            headers=auth_headers(admin_token()),
        )
        await app_client.post(
            "/api/v1/admin/users",
            json={"username": "target", "password": "pass123", "prefix": "TT"},
            headers=auth_headers(admin_token()),
        )
        resp = await app_client.patch(
            "/api/v1/admin/users/viewer/data-visibility",
            json={
                "puede_ver_datos_de_otros": True,
                "prefijos_visibles": ["P", "TT"],
            },
            headers=auth_headers(admin_token()),
        )
        assert resp.status_code == status.HTTP_200_OK
        perms = resp.json()
        assert perms["puede_ver_datos_de_otros"] is True
        assert "P" in perms["prefijos_visibles"]
        assert "TT" in perms["prefijos_visibles"]

    async def test_invalid_prefix_in_visibility_raises_422(self, app_client):
        """422 si se incluye un prefijo que no corresponde a ningún usuario."""
        await app_client.post(
            "/api/v1/admin/users",
            json={"username": "vuser2", "password": "pass123", "prefix": "VU"},
            headers=auth_headers(admin_token()),
        )
        resp = await app_client.patch(
            "/api/v1/admin/users/vuser2/data-visibility",
            json={"prefijos_visibles": ["NONEXISTENT"]},
            headers=auth_headers(admin_token()),
        )
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    async def test_visibility_empty_raises_400(self, app_client):
        """400 si no se envía ningún campo de visibilidad."""
        await app_client.post(
            "/api/v1/admin/users",
            json={"username": "vuser3", "password": "pass123", "prefix": "V3"},
            headers=auth_headers(admin_token()),
        )
        resp = await app_client.patch(
            "/api/v1/admin/users/vuser3/data-visibility",
            json={},
            headers=auth_headers(admin_token()),
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


# ===========================================================================
# Tests de guards en módulos operacionales
# ===========================================================================

class TestOperationalGuards:
    async def test_admin_can_list_facturas(self, app_client):
        """El admin puede acceder a GET /facturas sin permisos extra."""
        resp = await app_client.get(
            "/api/v1/facturas",
            headers=auth_headers(admin_token()),
        )
        assert resp.status_code == status.HTTP_200_OK

    async def test_user_without_facturas_ver_gets_403(self, app_client, db_conn):
        """
        Un usuario sin permiso `facturas_ver` recibe 403 en GET /facturas.

        Nota: los permisos por defecto incluyen facturas_ver=1, por lo que
        primero revocamos ese permiso manualmente en la BD de test.
        """
        await _create_test_user(db_conn, "nofactura", "NF")
        # Revocar facturas_ver
        await db_conn.execute(
            "UPDATE user_permissions SET facturas_ver = 0 WHERE user_id = "
            "(SELECT id FROM usuarios WHERE username = 'nofactura')"
        )
        await db_conn.commit()

        resp = await app_client.get(
            "/api/v1/facturas",
            headers=auth_headers(user_token("nofactura", "NF")),
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    async def test_user_without_facturas_emitir_gets_403_on_create(self, app_client, db_conn):
        """Un usuario sin `facturas_emitir` recibe 403 al intentar crear factura."""
        await _create_test_user(db_conn, "nocreate", "NC")
        # El permiso facturas_emitir=0 por defecto, no necesita revocar

        resp = await app_client.post(
            "/api/v1/facturas",
            json={
                "cliente_id": "NC1",
                "total": 100.0,
                "items": [],
                "facturacion_rapida": 0,
            },
            headers=auth_headers(user_token("nocreate", "NC")),
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    async def test_user_with_facturas_emitir_can_create(self, app_client, db_conn):
        """Un usuario con `facturas_emitir=1` pasa el guard (puede fallar por lógica de negocio, no por permisos)."""
        await _create_test_user(db_conn, "creator", "CR")
        # Otorgar permiso
        await db_conn.execute(
            "UPDATE user_permissions SET facturas_emitir = 1 WHERE user_id = "
            "(SELECT id FROM usuarios WHERE username = 'creator')"
        )
        await db_conn.commit()

        resp = await app_client.post(
            "/api/v1/facturas",
            json={
                "cliente_id": "CR1",
                "total": 100.0,
                "items": [],
                "facturacion_rapida": 0,
            },
            headers=auth_headers(user_token("creator", "CR")),
        )
        # Puede ser 201, 404, 422 (lógica de negocio), pero NO 403
        assert resp.status_code != status.HTTP_403_FORBIDDEN

    async def test_user_without_clientes_crear_gets_403_on_list(self, app_client, db_conn):
        """Un usuario sin `clientes_crear` recibe 403 al listar clientes."""
        await _create_test_user(db_conn, "nocliente", "NCL")
        # clientes_crear=0 por defecto

        resp = await app_client.get(
            "/api/v1/clientes",
            headers=auth_headers(user_token("nocliente", "NCL")),
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    async def test_admin_can_access_all_modules(self, app_client):
        """El admin tiene acceso de lectura a todos los módulos sin restricciones."""
        endpoints = [
            "/api/v1/facturas",
            "/api/v1/items",
            "/api/v1/envios",
            "/api/v1/clientes",
            "/api/v1/catalogo",
            "/api/v1/stock",
        ]
        for endpoint in endpoints:
            resp = await app_client.get(
                endpoint,
                headers=auth_headers(admin_token()),
            )
            # El admin nunca debe recibir 403 en ningún módulo
            assert resp.status_code != status.HTTP_403_FORBIDDEN, (
                f"Admin recibió 403 en {endpoint}"
            )


# ===========================================================================
# Helpers internos para tests
# ===========================================================================

async def _create_test_user(db_conn: aiosqlite.Connection, username: str, prefix: str):
    """Crea un usuario regular de prueba directamente en la BD."""
    import bcrypt
    hashed = bcrypt.hashpw(b"testpass123", bcrypt.gensalt()).decode()
    await db_conn.execute(
        """
        INSERT OR IGNORE INTO usuarios (username, hashed_pw, rol, prefix, activo)
        VALUES (?, ?, 'user', ?, 1)
        """,
        (username, hashed, prefix),
    )
    # Crear permisos por defecto
    await db_conn.execute(
        """
        INSERT OR IGNORE INTO user_permissions (user_id)
        SELECT id FROM usuarios WHERE username = ?
        """,
        (username,),
    )
    await db_conn.commit()
