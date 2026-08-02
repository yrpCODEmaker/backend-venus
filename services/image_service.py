"""
Venus Backend — Servicio de procesamiento y desduplicación de imágenes.

Provee funciones utilitarias para:
- Calcular la relación de aspecto (width / height) de imágenes recibidas en bytes.
- Calcular el hash SHA-256 de archivos binarios de imagen.
- Desduplicar imágenes por hash al procesar subidas (catálogo, stock, sync).
"""

from datetime import datetime, timezone
import hashlib
import io
import os
import aiosqlite
from PIL import Image

from config import settings
from services.factura_service import _gen_id


def calculate_aspect_ratio(content: bytes) -> str:
    """
    Calcula la relación de aspecto (ancho / alto) de una imagen recibida como bytes.
    Retorna el valor como un string formateado a 4 decimales (ej: '1.7778', '1.0', '0.75').
    En caso de error o archivo corrupto/inválido, retorna '1.0' como fallback por defecto.
    """
    if not content:
        return "1.0"
    try:
        with Image.open(io.BytesIO(content)) as img:
            width, height = img.size
            if height > 0:
                ratio = round(width / height, 4)
                return str(ratio)
    except Exception:
        pass
    return "1.0"


def calculate_hash(content: bytes) -> str:
    """Calcula el hash SHA-256 hexadecimal de los bytes de la imagen."""
    if not content:
        return ""
    return hashlib.sha256(content).hexdigest()


async def get_or_create_image(
    db: aiosqlite.Connection,
    content: bytes,
    filename: str | None,
    prefix: str,
    target_id: str | None = None,
) -> dict:
    """
    Procesa una imagen recibida en bytes desduplicando mediante su hash SHA-256.

    - Si ya existe una imagen en la BD con el mismo hash y no ha sido eliminada:
      - Reutiliza la imagen existente (mismo image_id y misma ruta de archivo físico en disco).
    - Si no existe:
      - Guarda físicamente el archivo en el directorio del usuario /uploads/{prefix}/.
      - Calcula aspect_ratio y hash.
      - Inserta el nuevo registro en la tabla `images`.

    Retorna un diccionario con: id, file_path, aspect_ratio, hash, reused.
    """
    img_hash = calculate_hash(content)
    aspect_ratio = calculate_aspect_ratio(content)
    now = datetime.now(timezone.utc).isoformat()

    # 1. Buscar si ya existe una imagen activa con el mismo hash
    if img_hash:
        cursor = await db.execute(
            "SELECT id, file_path, aspect_ratio, hash FROM images WHERE hash = ? AND deleted_at IS NULL",
            (img_hash,),
        )
        existing = await cursor.fetchone()
        if existing:
            existing_id = existing["id"]
            file_path = existing["file_path"]
            existing_aspect = existing["aspect_ratio"] or aspect_ratio

            # Si target_id es indicado (ej: en sync push/upload_image), aseguramos/actualizamos target_id
            # reutilizando la misma ruta física y el mismo hash
            if target_id and target_id != existing_id:
                await db.execute(
                    """
                    INSERT INTO images (id, aspect_ratio, hash, file_path, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        aspect_ratio = excluded.aspect_ratio,
                        hash = excluded.hash,
                        file_path = excluded.file_path,
                        updated_at = excluded.updated_at
                    """,
                    (target_id, existing_aspect, img_hash, file_path, now),
                )
                return {
                    "id": target_id,
                    "file_path": file_path,
                    "aspect_ratio": existing_aspect,
                    "hash": img_hash,
                    "reused": True,
                }

            return {
                "id": existing_id,
                "file_path": file_path,
                "aspect_ratio": existing_aspect,
                "hash": img_hash,
                "reused": True,
            }

    # 2. Si no existe previamente, guardar archivo físico e insertar en `images`
    user_dir = os.path.join(settings.UPLOAD_DIR, prefix)
    os.makedirs(user_dir, exist_ok=True)

    image_id = target_id or _gen_id(prefix)
    ext = os.path.splitext(filename)[1] if filename else ".jpg"
    if not ext:
        ext = ".jpg"
    unique_name = f"{image_id}{ext}"
    file_path_disk = os.path.join(user_dir, unique_name)

    with open(file_path_disk, "wb") as f:
        f.write(content)

    remote_path = f"/uploads/{prefix}/{unique_name}"

    await db.execute(
        """
        INSERT INTO images (id, aspect_ratio, hash, file_path, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            aspect_ratio = excluded.aspect_ratio,
            hash = excluded.hash,
            file_path = excluded.file_path,
            updated_at = excluded.updated_at
        """,
        (image_id, aspect_ratio, img_hash, remote_path, now),
    )

    return {
        "id": image_id,
        "file_path": remote_path,
        "aspect_ratio": aspect_ratio,
        "hash": img_hash,
        "reused": False,
    }
