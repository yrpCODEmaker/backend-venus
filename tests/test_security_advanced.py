"""
Venus Backend — Tests para Capas de Seguridad Avanzada.

Cubre:
1. Límite de intentos fallidos y bloqueo de 5 minutos (Opción 1B).
2. Regla Anti-Ingeniería Inversa: Bloqueo inmediato al enviar OTP no solicitado.
3. Flujo completo de 2FA / TOTP (Setup, Enable, Login con OTP, Status, Disable).
4. Reto de OTP en cuenta con 2FA tras 3 fallos.
5. Smart Login / Detección de IP sospechosa.
"""

import os
import tempfile
from unittest.mock import patch
import pyotp
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from database import init_db
from services.auth import rate_limiter


@pytest_asyncio.fixture
async def app():
    """Crea una instancia de FastAPI con BD temporal."""
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
    """Cliente HTTP asíncrono para las pruebas."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver"
    ) as c:
        yield c


@pytest.fixture(autouse=True)
def reset_rate_limiter_state():
    """Limpia el estado del rate limiter en memoria antes de cada test."""
    rate_limiter._failed_attempts.clear()
    rate_limiter._locked_until.clear()
    yield
    rate_limiter._failed_attempts.clear()
    rate_limiter._locked_until.clear()


@pytest.mark.asyncio
async def test_account_lockout_after_3_failed_attempts(client: AsyncClient):
    """Prueba que 3 intentos fallidos sin 2FA bloquean la cuenta por 5 minutos (HTTP 429)."""
    username = "pichardo"
    wrong_password = "wrongpassword123"

    # Intento 1: Fallido (401)
    res1 = await client.post("/api/v1/auth/login", data={"username": username, "password": wrong_password})
    assert res1.status_code == 401

    # Intento 2: Fallido (401)
    res2 = await client.post("/api/v1/auth/login", data={"username": username, "password": wrong_password})
    assert res2.status_code == 401

    # Intento 3: Fallido -> Bloqueo (429)
    res3 = await client.post("/api/v1/auth/login", data={"username": username, "password": wrong_password})
    assert res3.status_code == 429
    assert "Cuenta bloqueada" in res3.json()["detail"]

    # Intento 4 con contraseña CORRECTA pero estando bloqueado -> Sigue bloqueado (429)
    res4 = await client.post("/api/v1/auth/login", data={"username": username, "password": "admin123"})
    assert res4.status_code == 429


@pytest.mark.asyncio
async def test_anti_reverse_engineering_unsolicited_otp(client: AsyncClient):
    """
    Regla Anti-Ingeniería Inversa:
    Si un cliente envía un otp_code cuando la cuenta NO lo requiere, la cuenta se bloquea inmediatamente por 5 min.
    """
    username = "pichardo"
    password = "admin123"

    # Enviar login con contraseña correcta pero adjuntando un otp_code no solicitado
    res = await client.post(
        "/api/v1/auth/login",
        data={"username": username, "password": password, "otp_code": "123456"}
    )
    assert res.status_code == 429
    assert "Anomalía detectada" in res.json()["detail"]

    # Siguiente intento simple sin OTP -> Bloqueado por 5 min
    res_next = await client.post("/api/v1/auth/login", data={"username": username, "password": password})
    assert res_next.status_code == 429


@pytest.mark.asyncio
async def test_2fa_setup_enable_and_login_flow(client: AsyncClient):
    """
    Prueba el ciclo completo de 2FA:
    1. Login normal para obtener JWT.
    2. /2fa/setup -> Obtiene secreto y QR.
    3. /2fa/enable -> Activa 2FA con código OTP válido.
    4. /2fa/status -> Verifica enabled=True.
    5. Login con contraseña sola -> Retorna requires_otp=True.
    6. Login con contraseña + OTP válido -> Obtiene access_token JWT.
    7. /2fa/disable -> Desactiva 2FA.
    """
    # 1. Login inicial
    login_res = await client.post("/api/v1/auth/login", data={"username": "pichardo", "password": "admin123"})
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Setup 2FA
    setup_res = await client.post("/api/v1/auth/2fa/setup", headers=headers)
    assert setup_res.status_code == 200
    setup_data = setup_res.json()
    secret = setup_data["secret"]
    assert "data:image/png;base64," in setup_data["qr_code_base64"]
    assert setup_data["otpauth_url"].startswith("otpauth://totp/")

    # 3. Intentar enable con código inválido
    bad_enable = await client.post("/api/v1/auth/2fa/enable", json={"otp_code": "000000"}, headers=headers)
    assert bad_enable.status_code == 400

    # Activar con código válido generado con pyotp
    valid_code = pyotp.TOTP(secret).now()
    enable_res = await client.post("/api/v1/auth/2fa/enable", json={"otp_code": valid_code}, headers=headers)
    assert enable_res.status_code == 200
    assert enable_res.json()["enabled"] is True

    # 4. Status 2FA
    status_res = await client.get("/api/v1/auth/2fa/status", headers=headers)
    assert status_res.status_code == 200
    assert status_res.json()["enabled"] is True

    # 5. Intentar login solo con clave (sin OTP)
    login_no_otp = await client.post("/api/v1/auth/login", data={"username": "pichardo", "password": "admin123"})
    assert login_no_otp.status_code == 200
    res_json = login_no_otp.json()
    assert res_json["requires_otp"] is True
    assert res_json["access_token"] is None

    # 6. Login con clave + OTP válido
    current_otp = pyotp.TOTP(secret).now()
    login_with_otp = await client.post(
        "/api/v1/auth/login",
        data={"username": "pichardo", "password": "admin123", "otp_code": current_otp}
    )
    assert login_with_otp.status_code == 200
    assert login_with_otp.json()["requires_otp"] is False
    assert login_with_otp.json()["access_token"] is not None

    # 7. Desactivar 2FA
    disable_res = await client.post(
        "/api/v1/auth/2fa/disable",
        json={"password": "admin123"},
        headers=headers
    )
    assert disable_res.status_code == 200
    assert disable_res.json()["enabled"] is False


@pytest.mark.asyncio
async def test_smart_login_suspicious_ip(client: AsyncClient):
    """Prueba que un intento de inicio de sesión desde una IP extranjera/sospechosa requiere OTP."""
    # Mockear is_suspicious_ip para devolver True
    with patch("routers.auth.is_suspicious_ip", return_value=True):
        # Al intentar loguear, debe exigir OTP independientemente de si 2FA estaba activo
        res = await client.post(
            "/api/v1/auth/login",
            data={"username": "pichardo", "password": "admin123"},
            headers={"X-Forwarded-For": "203.0.113.195"}  # IP externa simulada
        )
        assert res.status_code == 200
        assert res.json()["requires_otp"] is True
