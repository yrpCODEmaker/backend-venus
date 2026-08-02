"""
Venus Backend — Router de sincronización.

Endpoints:
- POST /api/v1/sync/push              → Subida masiva de datos del cliente
- GET  /api/v1/sync/pull              → Bajada delta de registros modificados
- POST /api/v1/sync/upload_image      → Subida de imagen física
- GET  /api/v1/sync/image/{image_id}  → Descarga de imagen
"""

import os
from pathlib import Path
import uuid

import aiosqlite
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from config import settings
from database import get_db
from schemas import PushSyncPayload
from services.auth import get_current_user
from services.image_service import calculate_aspect_ratio, get_or_create_image
from services.sync import PrefixTransformer, process_pull, process_push

router = APIRouter(prefix="/api/v1/sync", tags=["Sincronización"])


@router.post("/push")
async def sync_push(
    payload: PushSyncPayload,
    current_user: dict = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    """
    Recibe el payload completo del cliente con todos los cambios locales.

    Transforma IDs enteros a IDs con prefijo (PrefixTransformer) y ejecuta
    UPSERTs con Last-Write-Wins en todas las tablas.
    """
    prefix = current_user.get("prefix")
    if current_user.get("rol") == "admin" or not prefix:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo usuarios regulares pueden sincronizar.",
        )

    results = await process_push(db, payload, prefix)
    return {"status": "ok", "upserted": results}


@router.get("/pull")
async def sync_pull(
    last_sync: str = None,
    current_user: dict = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    """
    Retorna todos los registros del usuario modificados desde last_sync.

    Los IDs se retornan como enteros (prefijo eliminado) para que el
    cliente pueda hacer UPSERT directo en su SQLite local.

    Query params:
        last_sync: ISO 8601 timestamp (ej: 2026-07-15T00:00:00Z)
    """
    prefix = current_user.get("prefix")
    if current_user.get("rol") == "admin" or not prefix:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo usuarios regulares pueden sincronizar.",
        )

    data = await process_pull(db, prefix, last_sync)
    return data


@router.post("/upload_image")
async def upload_image(
    local_image_id: int = Form(...),
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    """
    Sube una imagen física al servidor.

    La imagen se guarda en /uploads/{prefix}/{filename} y se registra
    la ruta remota en la tabla images.
    """
    prefix = current_user.get("prefix")
    if current_user.get("rol") == "admin" or not prefix:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El admin no realiza subida de imágenes.",
        )

    content = await file.read()
    remote_id = f"{prefix}{local_image_id}"
    img_data = await get_or_create_image(db, content, file.filename, prefix, target_id=remote_id)
    await db.commit()

    return {
        "remote_path": img_data["file_path"],
        "local_image_id": local_image_id,
        "aspect_ratio": img_data["aspect_ratio"],
        "hash": img_data["hash"],
    }


@router.get("/image/{local_image_id}")
async def get_image(
    local_image_id: int,
    current_user: dict = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Descarga una imagen por su ID local."""
    prefix = current_user.get("prefix")
    if current_user.get("rol") == "admin" or not prefix:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El admin no realiza descarga de imágenes.",
        )

    remote_id = f"{prefix}{local_image_id}"
    cursor = await db.execute(
        "SELECT file_path FROM images WHERE id = ?", (remote_id,)
    )
    row = await cursor.fetchone()

    if not row or not row[0]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Imagen no encontrada",
        )

    # ── Resolución segura de rutas (anti path-traversal) ──────────────────────
    # Calculamos la raíz absoluta de uploads una sola vez.
    upload_root = Path(settings.UPLOAD_DIR).resolve()

    raw_path: str = row[0]

    # Normalizar separadores y quitar prefijos como "/uploads/" o "./"
    if raw_path.startswith("/uploads/"):
        raw_path = raw_path.removeprefix("/uploads/")
    elif raw_path.startswith("./"):
        raw_path = raw_path[2:]

    # Resolver la ruta completa y verificar que esté dentro de upload_root.
    # Path.resolve() elimina cualquier ".." en la ruta, haciendo que un intento
    # de escalar directorios apunte fuera del directorio permitido.
    resolved = (upload_root / raw_path).resolve()

    if not resolved.is_relative_to(upload_root):
        # La ruta escapó del directorio permitido → rechazar sin revelar detalles
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado",
        )

    if not resolved.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Archivo de imagen no encontrado en disco",
        )

    return FileResponse(str(resolved))

