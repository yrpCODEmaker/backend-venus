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

import json
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

import aiosqlite
import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from config import settings
from database import get_db

# OAuth2 scheme para extraer el token del header Authorization
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


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
