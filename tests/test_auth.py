"""
Tests para auth y admin — Paso 3.

Verifica login, /me, creación de usuarios, toggle y permisos RBAC.
"""

import os
import tempfile

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from database import init_db


# ---------------------------------------------------------------------------
# Fixture: app con base de datos temporal
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def app():
    """Crea una instancia de FastAPI con BD temporal."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    # Sobreescribir config ANTES de importar la app
    from config import settings
    original_path = settings.DATABASE_PATH
    settings.DATABASE_PATH = db_path

    await init_db(db_path)

    # Re-importar main para obtener la app (usa la config actualizada)
    from main import app as fastapi_app

    yield fastapi_app

    # Restaurar
    settings.DATABASE_PATH = original_path
    for ext in ("", "-wal", "-shm"):
        try:
            os.unlink(db_path + ext)
        except FileNotFoundError:
            pass


@pytest_asyncio.fixture
async def client(app):
    """Cliente HTTP async para testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def admin_token(client):
    """Token JWT del admin 'pichardo'."""
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "pichardo", "password": "admin123"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


@pytest_asyncio.fixture
async def user_token(client, admin_token):
    """Crea un usuario 'laura' con prefijo 'L' y retorna su token."""
    # Crear usuario
    resp = await client.post(
        "/api/v1/admin/users",
        json={"username": "laura", "password": "secreto123", "prefix": "L"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201

    # Login
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "laura", "password": "secreto123"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


# ---------------------------------------------------------------------------
# Tests de login
# ---------------------------------------------------------------------------
class TestLogin:
    @pytest.mark.asyncio
    async def test_login_admin_success(self, client):
        """El admin 'pichardo' puede hacer login con credenciales correctas."""
        resp = await client.post(
            "/api/v1/auth/login",
            data={"username": "pichardo", "password": "admin123"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"
        assert body["expires_in"] > 0

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, client):
        """Login con contraseña incorrecta retorna 401."""
        resp = await client.post(
            "/api/v1/auth/login",
            data={"username": "pichardo", "password": "wrong"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_login_nonexistent_user(self, client):
        """Login con usuario inexistente retorna 401."""
        resp = await client.post(
            "/api/v1/auth/login",
            data={"username": "noexiste", "password": "test"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Tests de /me
# ---------------------------------------------------------------------------
class TestMe:
    @pytest.mark.asyncio
    async def test_me_returns_admin_info(self, client, admin_token):
        """GET /me retorna los datos del admin autenticado."""
        resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["username"] == "pichardo"
        assert body["rol"] == "admin"
        assert body["prefix"] == "P"

    @pytest.mark.asyncio
    async def test_me_without_token(self, client):
        """GET /me sin token retorna 401."""
        resp = await client.get("/api/v1/auth/me")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_me_with_invalid_token(self, client):
        """GET /me con token inválido retorna 401."""
        resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer invalid.token.here"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Tests de admin - crear usuarios
# ---------------------------------------------------------------------------
class TestCreateUser:
    @pytest.mark.asyncio
    async def test_create_user_success(self, client, admin_token):
        """El admin puede crear un usuario con prefijo."""
        resp = await client.post(
            "/api/v1/admin/users",
            json={"username": "carlos", "password": "pass123", "prefix": "C"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["username"] == "carlos"
        assert body["rol"] == "user"
        assert body["prefix"] == "C"
        assert body["activo"] is True

    @pytest.mark.asyncio
    async def test_create_user_duplicate_username(self, client, admin_token):
        """No se puede crear un usuario con username duplicado."""
        await client.post(
            "/api/v1/admin/users",
            json={"username": "maria", "password": "pass", "prefix": "M"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        resp = await client.post(
            "/api/v1/admin/users",
            json={"username": "maria", "password": "pass2", "prefix": "M2"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_create_user_duplicate_prefix(self, client, admin_token):
        """No se puede crear un usuario con prefijo duplicado."""
        await client.post(
            "/api/v1/admin/users",
            json={"username": "user1", "password": "pass", "prefix": "X"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        resp = await client.post(
            "/api/v1/admin/users",
            json={"username": "user2", "password": "pass", "prefix": "X"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_create_user_as_non_admin(self, client, user_token):
        """Un usuario normal no puede crear otros usuarios (403)."""
        resp = await client.post(
            "/api/v1/admin/users",
            json={"username": "hacker", "password": "pass", "prefix": "H"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Tests de admin - listar usuarios
# ---------------------------------------------------------------------------
class TestListUsers:
    @pytest.mark.asyncio
    async def test_list_users(self, client, admin_token):
        """El admin puede listar todos los usuarios."""
        resp = await client.get(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        users = resp.json()
        assert isinstance(users, list)
        # Al menos el admin 'pichardo' debe existir
        usernames = [u["username"] for u in users]
        assert "pichardo" in usernames

    @pytest.mark.asyncio
    async def test_list_users_as_non_admin(self, client, user_token):
        """Un usuario normal no puede listar usuarios (403)."""
        resp = await client.get(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Tests de admin - toggle usuario
# ---------------------------------------------------------------------------
class TestToggleUser:
    @pytest.mark.asyncio
    async def test_toggle_user_deactivate(self, client, admin_token):
        """El admin puede desactivar un usuario."""
        # Crear usuario primero
        await client.post(
            "/api/v1/admin/users",
            json={"username": "pedro", "password": "pass", "prefix": "PE"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        # Desactivar
        resp = await client.patch(
            "/api/v1/admin/users/pedro/toggle",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["activo"] is False

    @pytest.mark.asyncio
    async def test_toggle_user_reactivate(self, client, admin_token):
        """Toggle doble reactiva al usuario."""
        await client.post(
            "/api/v1/admin/users",
            json={"username": "ana", "password": "pass", "prefix": "A"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        # Desactivar
        await client.patch(
            "/api/v1/admin/users/ana/toggle",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        # Reactivar
        resp = await client.patch(
            "/api/v1/admin/users/ana/toggle",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["activo"] is True

    @pytest.mark.asyncio
    async def test_cannot_toggle_self(self, client, admin_token):
        """El admin no puede desactivarse a sí mismo."""
        resp = await client.patch(
            "/api/v1/admin/users/pichardo/toggle",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_deactivated_user_cannot_login(self, client, admin_token):
        """Un usuario desactivado no puede hacer login."""
        # Crear y desactivar
        await client.post(
            "/api/v1/admin/users",
            json={"username": "blocked", "password": "pass", "prefix": "BL"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        await client.patch(
            "/api/v1/admin/users/blocked/toggle",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        # Intentar login
        resp = await client.post(
            "/api/v1/auth/login",
            data={"username": "blocked", "password": "pass"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_toggle_nonexistent_user(self, client, admin_token):
        """Toggle de usuario inexistente retorna 404."""
        resp = await client.patch(
            "/api/v1/admin/users/fantasma/toggle",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404
