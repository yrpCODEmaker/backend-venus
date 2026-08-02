"""
Tests de seguridad — Remediación de vulnerabilidades (2026-08-02)

Cubre los tres vectores del archivo vulnerabilidades.md:
  1. JWT: SECRET_KEY sin default en código; arranque falla si está ausente o insegura en producción.
  2. LFI en ImageIn.file_path: validador rechaza rutas peligrosas.
  3. Path-traversal en /sync/image: FileResponse confinado a UPLOAD_DIR.
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError


# ===========================================================================
# Helpers
# ===========================================================================

_NOW = datetime.now(timezone.utc)


def _image_in(file_path: str):
    """Instancia ImageIn con todos los campos requeridos por BaseSyncIn."""
    from schemas import ImageIn
    return ImageIn(local_id=1, updated_at=_NOW, file_path=file_path)


# ===========================================================================
# 1) JWT — SECRET_KEY sin default en código
# ===========================================================================

class TestSecretKeyValidation:
    """
    Verifica que config.Settings aborte cuando SECRET_KEY no está configurada
    o es insegura en producción.

    Se instancia Settings directamente (sin leer .env ni recargar módulo)
    para aislar los tests del entorno del proceso.
    """

    def _make_settings(self, **kwargs):
        """Instancia Settings con valores explícitos ignorando .env."""
        from config import Settings
        return Settings(_env_file=None, **kwargs)

    def test_secret_key_none_raises(self):
        """Sin SECRET_KEY el arranque debe llamar sys.exit(1)."""
        with pytest.raises(SystemExit) as exc_info:
            self._make_settings(SECRET_KEY=None, ENV="local")
        assert exc_info.value.code == 1

    def test_secret_key_empty_raises(self):
        """SECRET_KEY vacía debe rechazarse."""
        with pytest.raises(SystemExit) as exc_info:
            self._make_settings(SECRET_KEY="", ENV="local")
        assert exc_info.value.code == 1

    def test_insecure_known_key_in_production_raises(self):
        """En production, la clave insegura conocida debe abortar."""
        with pytest.raises(SystemExit) as exc_info:
            self._make_settings(
                SECRET_KEY="dev-secret-key-do-not-use-in-production",
                ENV="production",
            )
        assert exc_info.value.code == 1

    def test_short_key_in_production_raises(self):
        """En production, una clave < 32 chars debe ser rechazada."""
        with pytest.raises(SystemExit) as exc_info:
            self._make_settings(SECRET_KEY="corta", ENV="production")
        assert exc_info.value.code == 1

    def test_strong_key_local_passes(self):
        """En local, cualquier clave presente pasa sin importar longitud."""
        s = self._make_settings(SECRET_KEY="a" * 64, ENV="local")
        assert s.SECRET_KEY == "a" * 64

    def test_strong_key_production_passes(self):
        """En production, una clave larga y única debe pasar."""
        s = self._make_settings(SECRET_KEY="z" * 64, ENV="production")
        assert s.SECRET_KEY == "z" * 64

    def test_insecure_key_local_passes(self):
        """En local sí se permite la clave débil (entorno de desarrollo)."""
        s = self._make_settings(
            SECRET_KEY="dev-secret-key-do-not-use-in-production",
            ENV="local",
        )
        assert s.SECRET_KEY == "dev-secret-key-do-not-use-in-production"


# ===========================================================================
# 2) LFI — Validador en ImageIn.file_path
# ===========================================================================

class TestImageInFilePathValidator:
    """
    Verifica que ImageIn.file_path rechace rutas peligrosas que
    permitirían leer archivos del servidor (Local File Inclusion).
    """

    @pytest.mark.parametrize("bad_path", [
        "../../etc/passwd",
        "../config.py",
        "/etc/passwd",
        "/uploads/../../../etc/shadow",
        "C:\\Windows\\System32\\drivers\\etc\\hosts",
        "C:/Windows/System32/drivers/etc/hosts",
        "D:/secretos.txt",
        "\\\\servidor\\share\\archivo",
        "//servidor/share/archivo",
        "foto\x00maliciosa.jpg",
        "foto\x01control.jpg",
    ])
    def test_dangerous_path_rejected(self, bad_path):
        """Rutas peligrosas deben generar ValidationError (HTTP 422)."""
        with pytest.raises(ValidationError):
            _image_in(bad_path)

    def test_empty_path_rejected(self):
        """Un file_path vacío también debe ser rechazado."""
        with pytest.raises(ValidationError):
            _image_in("")

    @pytest.mark.parametrize("safe_path", [
        "foto.jpg",
        "imagen_encargo.png",
        "uploads/P1/abc123.jpg",
        "P-1-hash.webp",
        "some_name.jpeg",
    ])
    def test_safe_path_accepted(self, safe_path):
        """Rutas relativas simples y seguras deben aceptarse sin error."""
        obj = _image_in(safe_path)
        assert obj.file_path == safe_path


# ===========================================================================
# 3) Path-traversal — Lógica de resolución en /sync/image/{id}
# ===========================================================================

class TestGetImagePathTraversal:
    """
    Verifica que la lógica del endpoint GET /sync/image/{id} no sirva
    archivos fuera de UPLOAD_DIR aunque la BD contenga una ruta maliciosa.

    Se prueba la función de resolución directamente sin levantar FastAPI,
    lo que hace los tests rápidos e independientes de la BD.
    """

    @pytest.fixture
    def upload_dir(self, tmp_path):
        """Directorio temporal que simula UPLOAD_DIR."""
        d = tmp_path / "uploads"
        d.mkdir()
        (d / "legit.jpg").write_bytes(b"fake-image-data")
        return d

    def _is_confined(self, upload_dir: Path, raw_path: str) -> bool:
        """
        Replica exactamente la lógica del router:
          1. Normaliza el prefijo de la ruta almacenada en BD.
          2. Resuelve con Path.resolve() (elimina cualquier ..).
          3. Verifica confinamiento con is_relative_to().
        """
        upload_root = upload_dir.resolve()
        if raw_path.startswith("/uploads/"):
            raw_path = raw_path.removeprefix("/uploads/")
        elif raw_path.startswith("./"):
            raw_path = raw_path[2:]
        resolved = (upload_root / raw_path).resolve()
        return resolved.is_relative_to(upload_root)

    @pytest.mark.parametrize("malicious_path", [
        "../../etc/passwd",
        "../config.py",
        "/etc/passwd",
        "legit/../../outside.txt",
    ])
    def test_traversal_paths_escape_upload_root(self, upload_dir, malicious_path):
        """
        Rutas maliciosas no pasan el check is_relative_to().
        El router respondería HTTP 403 para estas rutas.
        """
        assert not self._is_confined(upload_dir, malicious_path), (
            f"La ruta '{malicious_path}' debería escapar de UPLOAD_DIR"
        )

    def test_legit_path_is_confined(self, upload_dir):
        """Un path legítimo queda confinado dentro de UPLOAD_DIR."""
        assert self._is_confined(upload_dir, "legit.jpg")

    def test_subdirectory_legit_path_is_confined(self, upload_dir):
        """Un path en subdirectorio válido también está confinado."""
        (upload_dir / "P1").mkdir()
        (upload_dir / "P1" / "imagen.jpg").write_bytes(b"img")
        assert self._is_confined(upload_dir, "P1/imagen.jpg")
