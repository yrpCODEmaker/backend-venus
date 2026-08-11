"""
Venus Backend — Router de autenticación.

Endpoints:
- POST /api/v1/auth/login  → Devuelve JWT dado username + password
- GET  /api/v1/auth/me     → Retorna info del usuario autenticado + permisos
"""

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from config import settings
from database import get_db
from schemas import LoginRequest, TokenResponse, UserOut, UserPermissionsOut
from services.auth import (
    create_access_token,
    get_current_user,
    verify_password,
)

router = APIRouter(prefix="/api/v1/auth", tags=["Autenticación"])


from typing import Optional

import aiosqlite
from fastapi import APIRouter, Body, Depends, Form, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm

from config import settings
from database import get_db
from schemas import (
    LoginRequest,
    TokenResponse,
    TwoFactorDisableRequest,
    TwoFactorSetupResponse,
    TwoFactorStatusResponse,
    TwoFactorVerifyRequest,
    UserOut,
    UserPermissionsOut,
)
from services.auth import (
    create_access_token,
    generate_totp_qr,
    generate_totp_secret,
    get_current_user,
    is_suspicious_ip,
    rate_limiter,
    verify_password,
    verify_totp_code,
)

router = APIRouter(prefix="/api/v1/auth", tags=["Autenticación"])


@router.post("/login", response_model=TokenResponse)
async def login(
    request: Request,
    username: Optional[str] = Form(None),
    password: Optional[str] = Form(None),
    otp_code: Optional[str] = Form(None),
    login_body: Optional[LoginRequest] = Body(None),
    db: aiosqlite.Connection = Depends(get_db),
):
    """
    Autentica un usuario y retorna un JWT.

    Soporta:
    - OAuth2 Form-Data estándar (`username`, `password`, `otp_code` opcional).
    - Body JSON (`LoginRequest`).
    - Control de intentos fallidos (3 fallos -> 5 min bloqueo o reto 2FA si tiene TOTP activo).
    - Regla Anti-Ingeniería Inversa: Si se envía OTP sin requerirse, bloqueo inmediato de 5 min.
    - Inicio Inteligente: Exige OTP automáticamente si la IP es sospechosa/extranjera.
    """
    # Determinar parámetros de entrada (Form vs JSON Body)
    final_username = username or (login_body.username if login_body else None)
    final_password = password or (login_body.password if login_body else None)
    final_otp = otp_code or (login_body.otp_code if login_body else None)

    # También revisar header X-OTP-Code como fallback
    if not final_otp:
        final_otp = request.headers.get("X-OTP-Code")

    if not final_username or not final_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debe proporcionar usuario y contraseña",
        )

    # Extract Client IP
    client_ip = request.headers.get("x-forwarded-for") or request.headers.get("x-real-ip")
    if client_ip and "," in client_ip:
        client_ip = client_ip.split(",")[0].strip()
    if not client_ip and request.client:
        client_ip = request.client.host

    # 1. Verificar si la cuenta ya se encuentra bloqueada en memoria
    is_locked, remaining_secs = rate_limiter.is_locked(final_username)
    if is_locked:
        minutes_remaining = max(1, (remaining_secs + 59) // 60)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Cuenta bloqueada temporalmente por demasiados intentos fallidos. Reintente en {minutes_remaining} minutos ({remaining_secs} segundos).",
            headers={"Retry-After": str(remaining_secs)},
        )

    # 2. Buscar usuario en BD
    cursor = await db.execute(
        "SELECT id, username, hashed_pw, rol, prefix, activo, totp_secret, totp_enabled FROM usuarios WHERE username = ?",
        (final_username,),
    )
    row = await cursor.fetchone()

    if row is None:
        rate_limiter.record_failed_attempt(final_username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales inválidas",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id, db_user, hashed_pw, rol, prefix, activo, totp_secret, totp_enabled = row

    if not activo:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuario desactivado",
        )

    totp_enabled = bool(totp_enabled)
    failed_attempts = rate_limiter.get_failed_attempts(final_username)
    suspicious_ip = is_suspicious_ip(client_ip)

    # Evaluar si la cuenta requiere OTP obligatoriamente
    requires_otp = totp_enabled or (failed_attempts >= settings.MAX_FAILED_LOGIN_ATTEMPTS and totp_enabled) or suspicious_ip

    # 3. Regla Anti-Ingeniería Inversa (Detección de Probing / Sonda)
    # Si se envía un código OTP pero la cuenta NO tiene 2FA activado ni está en modo reto OTP,
    # se considera intento de ingeniería inversa y se bloquea la cuenta inmediatamente por 5 minutos.
    if final_otp and not requires_otp:
        lock_secs = rate_limiter.lock_account(final_username, minutes=5)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Anomalía detectada: Se envió un código OTP sin haber sido solicitado. Cuenta bloqueada por 5 minutos por seguridad.",
            headers={"Retry-After": str(lock_secs)},
        )

    # 4. Verificar Contraseña
    if not verify_password(final_password, hashed_pw):
        current_attempts, se_bloqueo, lock_secs = rate_limiter.record_failed_attempt(final_username)
        if se_bloqueo and not totp_enabled:
            # Si llegó a 3 intentos y NO tiene 2FA, bloquear cuenta por 5 min
            rate_limiter.lock_account(final_username, minutes=settings.ACCOUNT_LOCKOUT_MINUTES)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Cuenta bloqueada por {settings.ACCOUNT_LOCKOUT_MINUTES} minutos tras 3 intentos fallidos.",
                headers={"Retry-After": str(settings.ACCOUNT_LOCKOUT_MINUTES * 60)},
            )
        elif current_attempts >= settings.MAX_FAILED_LOGIN_ATTEMPTS and totp_enabled:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Credenciales inválidas. Se requiere verificación por código OTP para acceder.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Credenciales inválidas",
                headers={"WWW-Authenticate": "Bearer"},
            )

    # 5. Si la contraseña es correcta pero la cuenta exige OTP (2FA, IP sospechosa, etc.)
    if requires_otp:
        if not final_otp:
            # Exigir código OTP
            return TokenResponse(
                access_token=None,
                token_type="bearer",
                expires_in=None,
                requires_otp=True,
                message="Se requiere código de autenticación (OTP) de 6 dígitos.",
            )

        # Validar código OTP provisto
        if not totp_secret or not verify_totp_code(totp_secret, final_otp):
            current_attempts, se_bloqueo, lock_secs = rate_limiter.record_failed_attempt(final_username)
            if se_bloqueo:
                rate_limiter.lock_account(final_username, minutes=settings.ACCOUNT_LOCKOUT_MINUTES)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Código OTP incorrecto. Demasiados intentos. Cuenta bloqueada por {settings.ACCOUNT_LOCKOUT_MINUTES} minutos.",
                    headers={"Retry-After": str(settings.ACCOUNT_LOCKOUT_MINUTES * 60)},
                )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Código OTP inválido o desincronizado",
                headers={"WWW-Authenticate": "Bearer"},
            )

    # 6. Éxito total — Limpiar contador de fallos y generar JWT
    rate_limiter.reset_attempts(final_username)
    token = create_access_token({
        "sub": db_user,
        "role": rol,
        "prefix": prefix,
    })

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=settings.JWT_EXPIRE_MINUTES * 60,
        requires_otp=False,
        message="Inicio de sesión exitoso",
    )


@router.get("/me", response_model=UserOut)
async def get_me(
    current_user: dict = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Retorna el perfil completo del usuario autenticado, incluyendo sus permisos granulares."""
    username = current_user["username"]
    rol = current_user["rol"]

    # El admin siempre tiene permisos totales — construirlos sin consultar BD
    if rol == "admin":
        perms = UserPermissionsOut(
            facturas_ver=True, facturas_emitir=True, facturas_modificar=True,
            fabricacion_ver_estados=True, fabricacion_modificar_estados=True, fabricacion_mandar_envio=True,
            stock_crear=True, stock_modificar=True, stock_eliminar=True,
            catalogo_crear=True, catalogo_modificar=True, catalogo_eliminar=True,
            clientes_crear=True, clientes_modificar=True, clientes_eliminar=True,
            puede_ver_datos_de_otros=True, prefijos_visibles=[]
        )
    else:
        # Buscar permisos del usuario en BD
        cursor = await db.execute(
            """
            SELECT up.facturas_ver, up.facturas_emitir, up.facturas_modificar,
                   up.fabricacion_ver_estados, up.fabricacion_modificar_estados, up.fabricacion_mandar_envio,
                   up.stock_crear, up.stock_modificar, up.stock_eliminar,
                   up.catalogo_crear, up.catalogo_modificar, up.catalogo_eliminar,
                   up.clientes_crear, up.clientes_modificar, up.clientes_eliminar,
                   up.puede_ver_datos_de_otros, up.prefijos_visibles
            FROM user_permissions up
            JOIN usuarios u ON up.user_id = u.id
            WHERE u.username = ?
            """,
            (username,)
        )
        row = await cursor.fetchone()

        if row is None:
            # Sin registro: devolver permisos por defecto (solo lectura)
            perms = UserPermissionsOut(
                facturas_ver=True, fabricacion_ver_estados=True
            )
        else:
            import json as _json
            prefijos = []
            if row[16]:
                try:
                    prefijos = _json.loads(row[16])
                except Exception:
                    prefijos = []
            perms = UserPermissionsOut(
                facturas_ver=bool(row[0]),
                facturas_emitir=bool(row[1]),
                facturas_modificar=bool(row[2]),
                fabricacion_ver_estados=bool(row[3]),
                fabricacion_modificar_estados=bool(row[4]),
                fabricacion_mandar_envio=bool(row[5]),
                stock_crear=bool(row[6]),
                stock_modificar=bool(row[7]),
                stock_eliminar=bool(row[8]),
                catalogo_crear=bool(row[9]),
                catalogo_modificar=bool(row[10]),
                catalogo_eliminar=bool(row[11]),
                clientes_crear=bool(row[12]),
                clientes_modificar=bool(row[13]),
                clientes_eliminar=bool(row[14]),
                puede_ver_datos_de_otros=bool(row[15]),
                prefijos_visibles=prefijos
            )

    return UserOut(
        username=username,
        rol=rol,
        prefix=current_user["prefix"],
        activo=current_user["activo"],
        permissions=perms,
    )


# ---------------------------------------------------------------------------
# Endpoints de Configuración de Autenticación de Dos Factores (2FA)
# ---------------------------------------------------------------------------

@router.post("/2fa/setup", response_model=TwoFactorSetupResponse)
async def setup_2fa(
    current_user: dict = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    """
    Inicia la configuración de 2FA para el usuario autenticado.

    Genera una clave secreta y un código QR en Base64 PNG. Guardando la clave
    secreta de forma preliminar en la BD hasta que el usuario la confirme con /2fa/enable.
    """
    username = current_user["username"]
    secret = generate_totp_secret()
    qr_b64, otpauth_url = generate_totp_qr(secret, username)

    # Almacenar secreto preliminarmente (sin habilitar 2FA todavía)
    await db.execute(
        "UPDATE usuarios SET totp_secret = ? WHERE username = ?",
        (secret, username),
    )
    await db.commit()

    return TwoFactorSetupResponse(
        secret=secret,
        qr_code_base64=qr_b64,
        otpauth_url=otpauth_url,
    )


@router.post("/2fa/enable", response_model=TwoFactorStatusResponse)
async def enable_2fa(
    payload: TwoFactorVerifyRequest,
    current_user: dict = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    """
    Activa 2FA para la cuenta tras validar un código OTP generado por la app.
    """
    username = current_user["username"]

    cursor = await db.execute(
        "SELECT totp_secret FROM usuarios WHERE username = ?",
        (username,),
    )
    row = await cursor.fetchone()
    if not row or not row[0]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debe iniciar la configuración de 2FA primero mediante /2fa/setup",
        )

    secret = row[0]
    if not verify_totp_code(secret, payload.otp_code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Código OTP inválido o desincronizado. Verifique la hora de su dispositivo e intente de nuevo.",
        )

    await db.execute(
        "UPDATE usuarios SET totp_enabled = 1 WHERE username = ?",
        (username,),
    )
    await db.commit()

    return TwoFactorStatusResponse(enabled=True)


@router.post("/2fa/disable", response_model=TwoFactorStatusResponse)
async def disable_2fa(
    payload: TwoFactorDisableRequest,
    current_user: dict = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    """
    Desactiva 2FA para la cuenta del usuario autenticado. Requiere validar contraseña o código OTP.
    """
    username = current_user["username"]

    cursor = await db.execute(
        "SELECT hashed_pw, totp_secret, totp_enabled FROM usuarios WHERE username = ?",
        (username,),
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")

    hashed_pw, secret, enabled = row
    if not enabled:
        return TwoFactorStatusResponse(enabled=False)

    # Validar credenciales o código OTP para autorizar desactivación
    authorized = False
    if payload.password and verify_password(payload.password, hashed_pw):
        authorized = True
    elif payload.otp_code and secret and verify_totp_code(secret, payload.otp_code):
        authorized = True

    if not authorized:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Se requiere contraseña válida o código OTP actual para desactivar la autenticación de dos factores.",
        )

    await db.execute(
        "UPDATE usuarios SET totp_enabled = 0, totp_secret = NULL WHERE username = ?",
        (username,),
    )
    await db.commit()

    return TwoFactorStatusResponse(enabled=False)


@router.get("/2fa/status", response_model=TwoFactorStatusResponse)
async def status_2fa(
    current_user: dict = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Retorna el estado actual de la autenticación de 2 factores (activado/desactivado)."""
    username = current_user["username"]

    cursor = await db.execute(
        "SELECT totp_enabled FROM usuarios WHERE username = ?",
        (username,),
    )
    row = await cursor.fetchone()
    enabled = bool(row[0]) if row and row[0] is not None else False

    return TwoFactorStatusResponse(enabled=enabled)
