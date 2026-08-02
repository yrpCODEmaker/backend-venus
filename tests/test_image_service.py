"""
Venus Backend — Tests unitarios para el servicio de procesamiento de imágenes.
"""

import io
import pytest
from PIL import Image

from services.image_service import calculate_aspect_ratio, calculate_hash


def _create_sample_image_bytes(width: int, height: int, fmt: str = "PNG") -> bytes:
    """Genera bytes de una imagen sintética en memoria con las dimensiones especificadas."""
    img = Image.new("RGB", (width, height), color="red")
    buffer = io.BytesIO()
    img.save(buffer, format=fmt)
    return buffer.getvalue()


def test_calculate_aspect_ratio_square():
    content = _create_sample_image_bytes(200, 200)
    assert calculate_aspect_ratio(content) == "1.0"


def test_calculate_aspect_ratio_landscape():
    # 1600 x 900 -> 1.777777... -> 1.7778
    content = _create_sample_image_bytes(1600, 900)
    assert calculate_aspect_ratio(content) == "1.7778"


def test_calculate_aspect_ratio_portrait():
    # 600 x 800 -> 0.75
    content = _create_sample_image_bytes(600, 800)
    assert calculate_aspect_ratio(content) == "0.75"


def test_calculate_aspect_ratio_jpeg_format():
    # 800 x 600 -> 1.3333
    content = _create_sample_image_bytes(800, 600, fmt="JPEG")
    assert calculate_aspect_ratio(content) == "1.3333"


def test_calculate_aspect_ratio_invalid_bytes():
    assert calculate_aspect_ratio(b"not_an_image_data") == "1.0"
    assert calculate_aspect_ratio(b"") == "1.0"


def test_calculate_hash():
    content = b"sample_image_data"
    h1 = calculate_hash(content)
    h2 = calculate_hash(content)
    assert len(h1) == 64
    assert h1 == h2
    assert calculate_hash(b"") == ""


@pytest.mark.asyncio
async def test_get_or_create_image_deduplication(tmp_path):
    import aiosqlite
    from database import _DDL
    from services.image_service import get_or_create_image

    db_path = str(tmp_path / "test_dedup.db")
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(_DDL)
        db.row_factory = aiosqlite.Row

        img_bytes = _create_sample_image_bytes(100, 100)

        # 1. Primera subida: no existía previamente (reused == False)
        res1 = await get_or_create_image(db, img_bytes, "sofa.png", "L")
        assert res1["reused"] is False
        assert res1["hash"] != ""
        id1 = res1["id"]

        # 2. Segunda subida con idéntico contenido: desduplicada (reused == True, mismo id)
        res2 = await get_or_create_image(db, img_bytes, "sofa_copia.png", "L")
        assert res2["reused"] is True
        assert res2["id"] == id1
        assert res2["file_path"] == res1["file_path"]
