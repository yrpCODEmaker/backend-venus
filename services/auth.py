"""
Venus Backend — Servicio de autenticación.

Gestiona JWT, hashing de contraseñas y dependencias de seguridad para FastAPI.
Usa bcrypt directamente (sin passlib) para compatibilidad con bcrypt 5.x.

Cambios (Fase 4 — Guards de permisos granulares):
  - `get_current_user` ahora carga los permisos del usuario desde `user_permissions`.
  - `require_permission(action)` — factory que genera dependencias para validar
    permisos granulares por acción en cualquier endpoint operacional.
    El admin siempre tiene acceso total sin consultar la tabla de permisos.
"""

import base64
import io
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional, Tuple

import aiosqlite
import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

import pyotp
import qrcode

try:
    import geoip2.database
    _HAS_GEOIP = True
except ImportError:
    _HAS_GEOIP = False

from config import settings
from database import get_db

# OAuth2 scheme para extraer el token del header Authorization
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


# ---------------------------------------------------------------------------
# Rate Limiter de Inicios de Sesión (En Memoria - Opción 1B)
# ---------------------------------------------------------------------------
class LoginRateLimiter:
    """Gestiona el contador de intentos fallidos y bloqueos de cuenta en memoria."""

    def __init__(self):
        self._failed_attempts: dict[str, int] = {}
        self._locked_until: dict[str, datetime] = {}

    def is_locked(self, username: str) -> Tuple[bool, int]:
        """
        Retorna (True, segundos_restantes) si la cuenta está bloqueada.
        Limpia automáticamente si el tiempo de bloqueo ya expiró.
        """
        user_key = username.lower().strip()
        until = self._locked_until.get(user_key)
        if until:
            now = datetime.now(timezone.utc)
            if now < until:
                remaining_seconds = int((until - now).total_seconds())
                return True, max(1, remaining_seconds)
            else:
                # El tiempo expiro, liberar bloqueo
                del self._locked_until[user_key]
                self._failed_attempts[user_key] = 0
        return False, 0

    def record_failed_attempt(self, username: str) -> Tuple[int, bool, int]:
        """
        Registra un intento fallido para el usuario.
        Retorna: (intentos_acumulados, se_bloqueo_ahora, segundos_bloqueo)
        """
        user_key = username.lower().strip()
        current = self._failed_attempts.get(user_key, 0) + 1
        self._failed_attempts[user_key] = current

        if current >= settings.MAX_FAILED_LOGIN_ATTEMPTS:
            return current, True, settings.ACCOUNT_LOCKOUT_MINUTES * 60
        return current, False, 0

    def lock_account(self, username: str, minutes: int = settings.ACCOUNT_LOCKOUT_MINUTES) -> int:
        """
        Fuerza un bloqueo inmediato de la cuenta por 'minutes' minutos.
        Utilizado para la regla Anti-Ingeniería Inversa (envío de OTP sin solicitar).
        Retorna la cantidad de segundos bloqueados.
        """
        user_key = username.lower().strip()
        lock_until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        self._locked_until[user_key] = lock_until
        self._failed_attempts[user_key] = settings.MAX_FAILED_LOGIN_ATTEMPTS
        return minutes * 60

    def reset_attempts(self, username: str) -> None:
        """Resetea el contador de intentos fallidos y bloqueos para un usuario."""
        user_key = username.lower().strip()
        self._failed_attempts.pop(user_key, None)
        self._locked_until.pop(user_key, None)

    def get_failed_attempts(self, username: str) -> int:
        """Retorna la cantidad actual de intentos fallidos registrados."""
        user_key = username.lower().strip()
        return self._failed_attempts.get(user_key, 0)


# Instancia global del rate limiter en memoria
rate_limiter = LoginRateLimiter()


# ---------------------------------------------------------------------------
# Autenticación de Dos Factores (TOTP / QR)
# ---------------------------------------------------------------------------
def generate_totp_secret() -> str:
    """Genera una clave secreta base32 para TOTP."""
    return pyotp.random_base32()


def generate_totp_qr(secret: str, username: str) -> Tuple[str, str]:
    """
    Genera el enlace otpauth:// y un código QR renderizado en una imagen Base64 PNG.
    Retorna (qr_code_base64_data_uri, otpauth_url).
    """
    totp = pyotp.TOTP(secret)
    otpauth_url = totp.provisioning_uri(name=username, issuer_name=settings.TOTP_ISSUER)

    # Generar QR
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=6,
        border=4,
    )
    qr.add_data(otpauth_url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    qr_b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
    data_uri = f"data:image/png;base64,{qr_b64}"

    return data_uri, otpauth_url


def verify_totp_code(secret: str, code: str) -> bool:
    """Verifica si un código OTP de 6 dígitos es válido para la clave secreta dada."""
    if not secret or not code:
        return False
    totp = pyotp.TOTP(secret)
    # Permite ventana de tolerancia de 1 paso previo/posterior (30 seg)
    return totp.verify(code.strip(), valid_window=1)


# ---------------------------------------------------------------------------
# Geolocalización de IP (Smart Login / Detección de IP Sospechosa)
# ---------------------------------------------------------------------------
def is_suspicious_ip(ip_address: Optional[str]) -> bool:
    """
    Verifica si una dirección IP proviene de un país no autorizado o es sospechosa.

    Considera seguras (no sospechosas):
    - IPs locales o de bucle invertido (127.0.0.1, ::1, 10.x.x.x, 192.168.x.x, 172.16.x.x-172.31.x.x).
    - IPs de países listados en settings.ALLOWED_COUNTRY_CODES.
    """
    if not ip_address:
        return False

    ip = ip_address.strip()

    # IPs locales / privadas son confiables por definición
    if (
        ip in ("127.0.0.1", "::1", "localhost")
        or ip.startswith("10.")
        or ip.startswith("192.168.")
        or ip.startswith("172.16.") or ip.startswith("172.17.")
        or ip.startswith("172.18.") or ip.startswith("172.19.")
        or ip.startswith("172.20.") or ip.startswith("172.30.")
        or ip.startswith("172.31.")
    ):
        return False

    # Si existe base de datos GeoIP y la librería está cargada
    if _HAS_GEOIP and os.path.exists(settings.GEOIP_DB_PATH):
        try:
            with geoip2.database.Reader(settings.GEOIP_DB_PATH) as reader:
                response = reader.country(ip)
                country_code = response.country.iso_code
                if country_code and country_code not in settings.ALLOWED_COUNTRY_CODES:
                    return True  # IP proviene de país fuera del permitido -> Sospechosa
                return False
        except Exception:
            pass  # En caso de IP no encontrada en BD, fallback a seguro o según regla

    return False


# ---------------------------------------------------------------------------
# Hashing de contraseñas
# ---------------------------------------------------------------------------
def hash_password(password: str) -> str:
    """Hashea una contraseña con bcrypt."""
    return bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt(),
    ).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica una contraseña contra su hash bcrypt."""
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------
def create_access_token(data: dict, expires_minutes: Optional[int] = None) -> str:
    """
    Crea un JWT firmado con los claims proporcionados.

    Claims esperados: sub (username), role, prefix.
    Agrega automáticamente 'exp' (expiración).
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes or settings.JWT_EXPIRE_MINUTES
    )
    to_encode["exp"] = expire
    return jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


# ---------------------------------------------------------------------------
# Dependencias de FastAPI
# ---------------------------------------------------------------------------
async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: aiosqlite.Connection = Depends(get_db),
) -> dict:
    """
    Dependencia que decodifica el JWT y retorna los datos del usuario.

    Verifica:
    1. Que el token sea válido y no esté expirado
    2. Que el usuario exista en la BD
    3. Que el usuario esté activo

    Retorna un dict con: username, rol, prefix, activo.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token inválido o expirado",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    # Verificar que el usuario existe y está activo
    cursor = await db.execute(
        "SELECT username, rol, prefix, activo, id FROM usuarios WHERE username = ?",
        (username,),
    )
    row = await cursor.fetchone()

    if row is None:
        raise credentials_exception

    user = {
        "username": row[0],
        "rol": row[1],
        "prefix": row[2],
        "activo": bool(row[3]),
        "id": row[4],
        "permissions": {},  # Se cargará si es necesario
    }

    if not user["activo"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuario desactivado",
        )

    # Cargar permisos del usuario desde user_permissions
    perm_cursor = await db.execute(
        "SELECT * FROM user_permissions WHERE user_id = ?", (user["id"],)
    )
    perm_row = await perm_cursor.fetchone()
    if perm_row is not None:
        keys = [col[0] for col in perm_cursor.description]
        perm_dict = dict(zip(keys, perm_row))
        # Parsear prefijos_visibles como lista
        perm_dict["prefijos_visibles"] = json.loads(
            perm_dict.get("prefijos_visibles", "[]") or "[]"
        )
        user["permissions"] = perm_dict

    return user


async def require_admin(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """
    Dependencia que verifica que el usuario autenticado sea admin.
    Retorna el usuario si es admin, lanza 403 si no.
    """
    if current_user["rol"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere rol de administrador",
        )
    return current_user


def require_permission(action: str) -> Callable:
    """
    Factory de dependencias para validar permisos granulares por acción.

    Uso en un endpoint:
        current_user: dict = Depends(require_permission("facturas_emitir"))

    Acciones válidas (columnas en user_permissions):
        Facturas   : facturas_ver, facturas_emitir, facturas_modificar
        Fabricación: fabricacion_ver_estados, fabricacion_modificar_estados,
                     fabricacion_mandar_envio
        Stock      : stock_crear, stock_modificar, stock_eliminar
        Catálogo   : catalogo_crear, catalogo_modificar, catalogo_eliminar
        Clientes   : clientes_crear, clientes_modificar, clientes_eliminar

    El admin (rol='admin') siempre pasa sin consultar la tabla de permisos.
    Un usuario sin registro en user_permissions recibe acceso denegado.
    """
    async def _guard(current_user: dict = Depends(get_current_user)) -> dict:
        # El admin siempre tiene acceso total
        if current_user.get("rol") == "admin":
            return current_user

        perms = current_user.get("permissions", {})
        if not perms:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Sin permisos configurados. Contacte al administrador.",
            )

        if not perms.get(action, False):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"No tienes permiso para realizar esta acción: '{action}'",
            )
        return current_user

    return _guard
