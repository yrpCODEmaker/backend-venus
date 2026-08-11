"""
Venus Backend — Configuración centralizada.

Lee variables desde .env y provee valores por defecto para desarrollo local o producción.
Usa pydantic-settings que lee automáticamente el archivo .env.

Estrategia de Almacenamiento (Base de datos y Fotos):
  1. Si '/mnt/db' está disponible (Linux), almacena la BD en '/mnt/db/venus.db'
     y las fotos en '/mnt/db/uploads'.
  2. Si '/mnt/db' NO está disponible, usa el directorio 'home' del usuario
     ('~/venus_storage') como fallback automático.

Seguridad:
  - SECRET_KEY NO tiene valor por defecto en código. Debe estar definida en .env
    (desarrollo) o como secreto del contenedor (producción).
  - En entorno 'production', el arranque aborta si SECRET_KEY está ausente,
    es débil o usa el valor inseguro conocido.
"""

import json
import os
import sys
from typing import Optional
from pydantic_settings import BaseSettings

# ---------------------------------------------------------------------------
# Configuración de empresa (company_config.json)
# ---------------------------------------------------------------------------
COMPANY_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "company_config.json")

_COMPANY_DEFAULTS = {
    "nombre": "Venus Muebles",
    "logo_path": None,
    "ubicacion": "",
    "telefono": "",
    "rnc": None,
}


def get_company_config() -> dict:
    """
    Carga y retorna la configuración de empresa desde company_config.json.
    """
    try:
        with open(COMPANY_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[Venus] Error leyendo company_config.json ({e}). Usando defaults.")
        return dict(_COMPANY_DEFAULTS)


def save_company_config(data: dict) -> dict:
    """
    Guarda y persiste los datos de la empresa en company_config.json.
    """
    current = get_company_config()
    updated = {
        "nombre": data.get("nombre", current.get("nombre", _COMPANY_DEFAULTS["nombre"])),
        "rnc": data.get("rnc") if data.get("rnc") else None,
        "telefono": data.get("telefono", current.get("telefono", "")),
        "ubicacion": data.get("ubicacion", current.get("ubicacion", "")),
        "logo_path": data.get("logo_path", current.get("logo_path")),
    }
    with open(COMPANY_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(updated, f, ensure_ascii=False, indent=2)
    return updated


# ---------------------------------------------------------------------------
# Detección inteligente de almacenamiento (/mnt/db -> home -> ./ local)
# ---------------------------------------------------------------------------
def _resolve_default_storage() -> tuple[str, str]:
    """
    Determina la ubicación por defecto para la BD SQLite y las fotos subidas.

    Prioridad:
      1. '/mnt/db' si está disponible y accesible en Linux.
      2. '~/venus_storage' (Home del usuario).
      3. Directorio local del proyecto.
    """
    mnt_path = "/mnt/db"

    # 1. Intentar /mnt/db en Linux / POSIX
    if os.name != "nt":
        try:
            if not os.path.exists(mnt_path):
                os.makedirs(mnt_path, exist_ok=True)
            if os.access(mnt_path, os.W_OK):
                return (
                    os.path.join(mnt_path, "venus.db"),
                    os.path.join(mnt_path, "uploads"),
                )
        except Exception:
            pass  # Fallback si no hay permiso en /mnt/db

    # 2. Fallback a directorio 'home' (~/venus_storage)
    try:
        home_dir = os.path.expanduser("~")
        venus_home = os.path.join(home_dir, "venus_storage")
        os.makedirs(venus_home, exist_ok=True)
        if os.access(venus_home, os.W_OK):
            return (
                os.path.join(venus_home, "venus.db"),
                os.path.join(venus_home, "uploads"),
            )
    except Exception:
        pass

    # 3. Fallback final a desarrollo local
    return ("./venus.db", "./uploads")


_default_db_path, _default_upload_dir = _resolve_default_storage()

_KNOWN_INSECURE_KEYS = {
    "dev-secret-key-do-not-use-in-production",
    "secret",
    "changeme",
    "",
}


class Settings(BaseSettings):
    """Configuración centralizada del backend Venus."""

    # ── Entorno ──
    ENV: str = "local"  # 'local' | 'production'

    # ── Base de datos ──
    DATABASE_PATH: str = _default_db_path

    # ── JWT ──
    SECRET_KEY: Optional[str] = None
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60

    # ── Archivos ──
    UPLOAD_DIR: str = _default_upload_dir

    # ── Seed ──
    ADMIN_DEFAULT_PASSWORD: str = "admin123"

    # ── Seguridad Avanzada (2FA, Rate Limit, GeoIP) ──
    TOTP_ISSUER: str = "Venus App"
    MAX_FAILED_LOGIN_ATTEMPTS: int = 3
    ACCOUNT_LOCKOUT_MINUTES: int = 5
    ALLOWED_COUNTRY_CODES: list[str] = ["DO"]
    GEOIP_DB_PATH: str = "./GeoLite2-Country.mmdb"

    model_config = {"env_file": ".env"}

    def model_post_init(self, __context) -> None:
        """Validaciones de seguridad y preparación de directorios al arrancar."""
        # Crear directorios para BD y Fotos automáticamente según la ruta activa
        db_dir = os.path.dirname(os.path.abspath(self.DATABASE_PATH))
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        os.makedirs(self.UPLOAD_DIR, exist_ok=True)

        # SECRET_KEY obligatoria siempre
        if not self.SECRET_KEY:
            _abort(
                "SECRET_KEY no está configurada. "
                "Defínela en .env (local) o como secreto del contenedor (producción)."
            )

        # En producción rechazar claves débiles o conocidas
        if self.ENV == "production":
            if self.SECRET_KEY in _KNOWN_INSECURE_KEYS or len(self.SECRET_KEY) < 32:
                _abort(
                    "SECRET_KEY insegura detectada en entorno 'production'. "
                    "Genera una clave fuerte con: python -c \"import secrets; print(secrets.token_hex(32))\""
                )


def _abort(msg: str) -> None:
    """Imprime el error y aborta el proceso sin traceback confuso."""
    print(f"\n[VENUS SECURITY ERROR] {msg}\n", file=sys.stderr)
    sys.exit(1)


settings = Settings()
