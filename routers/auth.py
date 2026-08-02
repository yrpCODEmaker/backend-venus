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


@router.post("/login", response_model=TokenResponse)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: aiosqlite.Connection = Depends(get_db),
):
    """
    Autentica un usuario y retorna un JWT.

    Acepta form-data (OAuth2 estándar) con 'username' y 'password'.
    """
    # Buscar usuario por username
    cursor = await db.execute(
        "SELECT username, hashed_pw, rol, prefix, activo FROM usuarios WHERE username = ?",
        (form_data.username,),
    )
    row = await cursor.fetchone()

    if row is None or not verify_password(form_data.password, row[1]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales inválidas",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not row[4]:  # activo
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuario desactivado",
        )

    # Crear token con claims: sub, role, prefix
    token = create_access_token({
        "sub": row[0],     # username
        "role": row[2],    # rol
        "prefix": row[3],  # prefix (None para admin)
    })

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=settings.JWT_EXPIRE_MINUTES * 60,
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
