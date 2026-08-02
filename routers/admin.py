"""
Venus Backend — Router de administración.

Endpoints exclusivos del admin 'pichardo':
- POST   /api/v1/admin/users                              → Crear usuario con prefijo
- GET    /api/v1/admin/users                              → Listar todos los usuarios
- PATCH  /api/v1/admin/users/{username}/toggle            → Activar/desactivar usuario
- PUT    /api/v1/admin/users/{username}                   → Editar usuario (username, pw, prefix)
- DELETE /api/v1/admin/users/{username}                   → Eliminar usuario
- GET    /api/v1/admin/users/{username}/permissions       → Leer permisos del usuario
- PUT    /api/v1/admin/users/{username}/permissions       → Escribir/actualizar permisos
- PATCH  /api/v1/admin/users/{username}/data-visibility   → Ajustar visibilidad de datos

Reglas críticas:
- El admin principal ('pichardo') no puede eliminarse ni bloquearse a sí mismo.
- Solo `admin` puede editar permisos y visibilidad.
- `prefijos_visibles` solo puede contener prefijos de usuarios existentes.
- Al crear un usuario se le asigna automáticamente un registro de permisos restrictivos.

Cambios (Fase 3 — Endpoints admin de permisos):
  - Endpoints PUT, DELETE para gestión completa del ciclo de vida de usuario.
  - Endpoints GET/PUT de permisos y PATCH de visibilidad.
  - Helper interno `_get_user_or_404` para reutilización.
  - Helper interno `_get_or_create_permissions` para acceso idempotente a user_permissions.
"""

import json

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, status

from database import get_db
from schemas import (
    AdminUserUpdateIn,
    DataVisibilityPatchIn,
    UserCreateIn,
    UserOut,
    UserPermissionsIn,
    UserPermissionsOut,
)
from services.auth import hash_password, require_admin

router = APIRouter(prefix="/api/v1/admin", tags=["Administración"])


# ===========================================================================
# HELPERS INTERNOS
# ===========================================================================

async def _generate_unique_prefix(username: str, db: aiosqlite.Connection) -> str:
    """
    Genera automáticamente un prefijo único para un nuevo usuario.
    Intenta primera letra, primeras dos letras, o letra + número.
    """
    cursor = await db.execute("SELECT prefix FROM usuarios WHERE prefix IS NOT NULL AND prefix != ''")
    existing_prefixes = set(row[0].upper().rstrip("-") for row in await cursor.fetchall())

    clean_name = "".join(c for c in username if c.isalnum()).upper()

    # 1. Primera letra
    if clean_name and clean_name[0] not in existing_prefixes:
        return clean_name[0]

    # 2. Dos primeras letras
    if len(clean_name) >= 2 and clean_name[:2] not in existing_prefixes:
        return clean_name[:2]

    # 3. Primera letra + número (ej: C1, C2...)
    base_char = clean_name[0] if clean_name else "U"
    for i in range(1, 100):
        cand = f"{base_char}{i}"
        if cand not in existing_prefixes:
            return cand

    import uuid
    return f"U{uuid.uuid4().hex[:3]}".upper()


async def _get_user_or_404(username: str, db: aiosqlite.Connection) -> dict:
    """Retorna fila de usuario o lanza 404."""
    cursor = await db.execute(
        "SELECT id, username, rol, prefix, activo FROM usuarios WHERE username = ?",
        (username,),
    )
    row = await cursor.fetchone()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Usuario '{username}' no encontrado",
        )
    return {"id": row[0], "username": row[1], "rol": row[2], "prefix": row[3], "activo": bool(row[4])}


async def _get_or_create_permissions(user_id: int, db: aiosqlite.Connection) -> dict:
    """
    Retorna el registro de permisos del usuario, creándolo con valores
    por defecto (restrictivos) si aún no existe.
    """
    cursor = await db.execute(
        "SELECT * FROM user_permissions WHERE user_id = ?", (user_id,)
    )
    row = await cursor.fetchone()
    if row is None:
        # Crear con valores por defecto (usuario regular)
        await db.execute(
            """
            INSERT OR IGNORE INTO user_permissions (user_id)
            VALUES (?)
            """,
            (user_id,),
        )
        await db.commit()
        cursor = await db.execute(
            "SELECT * FROM user_permissions WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()

    # Construir dict a partir del Row de aiosqlite
    keys = [col[0] for col in cursor.description]
    return dict(zip(keys, row))


def _row_to_permissions_out(prow: dict) -> UserPermissionsOut:
    """Convierte un dict de user_permissions a UserPermissionsOut."""
    prefijos = json.loads(prow.get("prefijos_visibles", "[]") or "[]")
    return UserPermissionsOut(
        facturas_ver=bool(prow["facturas_ver"]),
        facturas_emitir=bool(prow["facturas_emitir"]),
        facturas_modificar=bool(prow["facturas_modificar"]),
        fabricacion_ver_estados=bool(prow["fabricacion_ver_estados"]),
        fabricacion_modificar_estados=bool(prow["fabricacion_modificar_estados"]),
        fabricacion_mandar_envio=bool(prow["fabricacion_mandar_envio"]),
        stock_crear=bool(prow["stock_crear"]),
        stock_modificar=bool(prow["stock_modificar"]),
        stock_eliminar=bool(prow["stock_eliminar"]),
        catalogo_crear=bool(prow["catalogo_crear"]),
        catalogo_modificar=bool(prow["catalogo_modificar"]),
        catalogo_eliminar=bool(prow["catalogo_eliminar"]),
        clientes_crear=bool(prow["clientes_crear"]),
        clientes_modificar=bool(prow["clientes_modificar"]),
        clientes_eliminar=bool(prow["clientes_eliminar"]),
        puede_ver_datos_de_otros=bool(prow["puede_ver_datos_de_otros"]),
        prefijos_visibles=prefijos,
    )


# ===========================================================================
# ENDPOINTS — Gestión de usuarios
# ===========================================================================

@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    data: UserCreateIn,
    admin: dict = Depends(require_admin),
    db: aiosqlite.Connection = Depends(get_db),
):
    """
    Crea un nuevo usuario con su prefijo único.

    Tras la creación asigna automáticamente un registro de permisos
    restrictivos (solo lectura de facturas y fabricación). Solo admin.
    """
    # Verificar que el username no exista
    cursor = await db.execute(
        "SELECT 1 FROM usuarios WHERE username = ?", (data.username,)
    )
    if await cursor.fetchone():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"El usuario '{data.username}' ya existe",
        )

    # Auto-generar o validar prefijo
    if not data.prefix or not data.prefix.strip():
        data.prefix = await _generate_unique_prefix(data.username, db)
    else:
        data.prefix = data.prefix.strip().upper()
        # Verificar que el prefijo no exista
        cursor = await db.execute(
            "SELECT 1 FROM usuarios WHERE UPPER(prefix) = ?", (data.prefix,)
        )
        if await cursor.fetchone():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"El prefijo '{data.prefix}' ya está en uso",
            )

    hashed = hash_password(data.password)
    await db.execute(
        """
        INSERT INTO usuarios (username, hashed_pw, rol, prefix, activo)
        VALUES (?, ?, 'user', ?, 1)
        """,
        (data.username, hashed, data.prefix),
    )

    # Obtener el ID del usuario recién creado
    cursor = await db.execute(
        "SELECT id FROM usuarios WHERE username = ?", (data.username,)
    )
    new_user_row = await cursor.fetchone()
    new_user_id = new_user_row[0]

    # Crear permisos por defecto (restrictivos) para usuario regular
    await db.execute(
        """
        INSERT OR IGNORE INTO user_permissions (user_id)
        VALUES (?)
        """,
        (new_user_id,),
    )
    await db.commit()

    return UserOut(
        username=data.username,
        rol="user",
        prefix=data.prefix,
        activo=True,
    )


@router.get("/users", response_model=list[UserOut])
async def list_users(
    admin: dict = Depends(require_admin),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Lista todos los usuarios registrados. Solo admin."""
    cursor = await db.execute(
        "SELECT username, rol, prefix, activo FROM usuarios ORDER BY created_at"
    )
    rows = await cursor.fetchall()
    return [
        UserOut(
            username=row[0],
            rol=row[1],
            prefix=row[2],
            activo=bool(row[3]),
        )
        for row in rows
    ]


@router.patch("/users/{username}/toggle", response_model=UserOut)
async def toggle_user(
    username: str,
    admin: dict = Depends(require_admin),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Activa/desactiva un usuario. Solo admin. No se puede desactivar a sí mismo."""
    if username == admin["username"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No puedes desactivarte a ti mismo",
        )

    user = await _get_user_or_404(username, db)

    new_status = 0 if user["activo"] else 1
    await db.execute(
        "UPDATE usuarios SET activo = ? WHERE username = ?",
        (new_status, username),
    )
    await db.commit()

    return UserOut(
        username=user["username"],
        rol=user["rol"],
        prefix=user["prefix"],
        activo=bool(new_status),
    )


@router.put("/users/{username}", response_model=UserOut)
async def update_user(
    username: str,
    data: AdminUserUpdateIn,
    admin: dict = Depends(require_admin),
    db: aiosqlite.Connection = Depends(get_db),
):
    """
    Edita un usuario existente (username, contraseña, prefix).

    Reglas:
    - El admin no puede cambiar su propio prefijo (para no romper multi-tenant).
    - El nuevo username o prefix no puede estar en uso por otro usuario.
    - Al menos un campo debe ser enviado.
    """
    user = await _get_user_or_404(username, db)

    if not data.username and not data.password and not data.prefix:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debes proporcionar al menos un campo a actualizar",
        )

    # Regla: admin no puede cambiarse su propio prefijo
    if username == admin["username"] and data.prefix and data.prefix != user["prefix"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El admin no puede cambiar su propio prefijo",
        )

    # Verificar que el nuevo username no esté en uso (si se está cambiando)
    if data.username and data.username != username:
        cursor = await db.execute(
            "SELECT 1 FROM usuarios WHERE username = ?", (data.username,)
        )
        if await cursor.fetchone():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"El username '{data.username}' ya está en uso",
            )

    # Verificar que el nuevo prefix no esté en uso
    if data.prefix and data.prefix != user["prefix"]:
        cursor = await db.execute(
            "SELECT 1 FROM usuarios WHERE prefix = ?", (data.prefix,)
        )
        if await cursor.fetchone():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"El prefijo '{data.prefix}' ya está en uso",
            )

    # Construir la actualización dinámica
    fields = []
    params = []
    if data.username:
        fields.append("username = ?")
        params.append(data.username)
    if data.password:
        fields.append("hashed_pw = ?")
        params.append(hash_password(data.password))
    if data.prefix:
        fields.append("prefix = ?")
        params.append(data.prefix)

    params.append(username)
    await db.execute(
        f"UPDATE usuarios SET {', '.join(fields)} WHERE username = ?",
        params,
    )
    await db.commit()

    # Retornar el estado actualizado
    updated = await _get_user_or_404(data.username or username, db)
    return UserOut(
        username=updated["username"],
        rol=updated["rol"],
        prefix=updated["prefix"],
        activo=updated["activo"],
    )


@router.delete("/users/{username}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    username: str,
    admin: dict = Depends(require_admin),
    db: aiosqlite.Connection = Depends(get_db),
):
    """
    Elimina permanentemente un usuario.

    Reglas críticas:
    - El admin principal no puede eliminarse a sí mismo.
    - La eliminación es en cascada: se eliminan sus permisos (ON DELETE CASCADE).
    """
    if username == admin["username"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El admin no puede eliminarse a sí mismo",
        )

    await _get_user_or_404(username, db)

    await db.execute("DELETE FROM usuarios WHERE username = ?", (username,))
    await db.commit()


# ===========================================================================
# ENDPOINTS — Permisos y visibilidad
# ===========================================================================

@router.get("/users/{username}/permissions", response_model=UserPermissionsOut)
async def get_user_permissions(
    username: str,
    admin: dict = Depends(require_admin),
    db: aiosqlite.Connection = Depends(get_db),
):
    """
    Lee los permisos granulares de un usuario.

    Si el usuario aún no tiene registro de permisos (usuarios migrados),
    se crea automáticamente con valores por defecto restrictivos.
    Solo admin.
    """
    user = await _get_user_or_404(username, db)
    prow = await _get_or_create_permissions(user["id"], db)
    return _row_to_permissions_out(prow)


@router.put("/users/{username}/permissions", response_model=UserPermissionsOut)
async def update_user_permissions(
    username: str,
    data: UserPermissionsIn,
    admin: dict = Depends(require_admin),
    db: aiosqlite.Connection = Depends(get_db),
):
    """
    Actualiza los permisos granulares de un usuario.

    Solo se actualizan los campos enviados (actualización parcial).
    El registro se crea si no existe. Solo admin.
    """
    user = await _get_user_or_404(username, db)
    prow = await _get_or_create_permissions(user["id"], db)

    # Construir actualización dinámica
    fields = []
    params = []

    perm_fields = [
        "facturas_ver", "facturas_emitir", "facturas_modificar",
        "fabricacion_ver_estados", "fabricacion_modificar_estados", "fabricacion_mandar_envio",
        "stock_crear", "stock_modificar", "stock_eliminar",
        "catalogo_crear", "catalogo_modificar", "catalogo_eliminar",
        "clientes_crear", "clientes_modificar", "clientes_eliminar",
        "puede_ver_datos_de_otros",
    ]
    for field in perm_fields:
        val = getattr(data, field, None)
        if val is not None:
            fields.append(f"{field} = ?")
            params.append(1 if val else 0)

    if data.prefijos_visibles is not None:
        # Validar que todos los prefijos correspondan a usuarios existentes
        for pref in data.prefijos_visibles:
            cursor = await db.execute(
                "SELECT 1 FROM usuarios WHERE prefix = ?", (pref,)
            )
            if not await cursor.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"El prefijo '{pref}' no corresponde a ningún usuario existente",
                )
        fields.append("prefijos_visibles = ?")
        params.append(json.dumps(data.prefijos_visibles))

    if not fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debes proporcionar al menos un permiso a actualizar",
        )

    fields.append("updated_at = datetime('now')")
    params.append(user["id"])

    await db.execute(
        f"UPDATE user_permissions SET {', '.join(fields)} WHERE user_id = ?",
        params,
    )
    await db.commit()

    # Releer y retornar el estado actualizado
    updated_prow = await _get_or_create_permissions(user["id"], db)
    return _row_to_permissions_out(updated_prow)


@router.patch("/users/{username}/data-visibility", response_model=UserPermissionsOut)
async def patch_data_visibility(
    username: str,
    data: DataVisibilityPatchIn,
    admin: dict = Depends(require_admin),
    db: aiosqlite.Connection = Depends(get_db),
):
    """
    Ajusta la visibilidad de datos entre usuarios.

    Controla si el usuario puede ver datos de otros usuarios y cuáles prefijos.
    Los prefijos enviados deben corresponder a usuarios existentes.
    Solo admin.
    """
    user = await _get_user_or_404(username, db)
    await _get_or_create_permissions(user["id"], db)

    fields = []
    params = []

    if data.puede_ver_datos_de_otros is not None:
        fields.append("puede_ver_datos_de_otros = ?")
        params.append(1 if data.puede_ver_datos_de_otros else 0)

    if data.prefijos_visibles is not None:
        # Validar que los prefijos existan
        for pref in data.prefijos_visibles:
            cursor = await db.execute(
                "SELECT 1 FROM usuarios WHERE prefix = ?", (pref,)
            )
            if not await cursor.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"El prefijo '{pref}' no corresponde a ningún usuario existente",
                )
        fields.append("prefijos_visibles = ?")
        params.append(json.dumps(data.prefijos_visibles))

    if not fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debes proporcionar al menos un campo de visibilidad a actualizar",
        )

    fields.append("updated_at = datetime('now')")
    params.append(user["id"])

    await db.execute(
        f"UPDATE user_permissions SET {', '.join(fields)} WHERE user_id = ?",
        params,
    )
    await db.commit()

    updated_prow = await _get_or_create_permissions(user["id"], db)
    return _row_to_permissions_out(updated_prow)
