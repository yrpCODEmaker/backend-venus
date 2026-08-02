"""
Venus Backend — Configuración centralizada.

Lee variables desde .env y provee valores por defecto para desarrollo local.
Usa pydantic-settings que lee automáticamente el archivo .env.

Seguridad:
  - SECRET_KEY NO tiene valor por defecto en código. Debe estar definida en .env
    (desarrollo) o como secreto del contenedor (producción).
  - En entorno 'production', el arranque aborta si SECRET_KEY está ausente,
    es débil o usa el valor inseguro conocido.
  - ADMIN_DEFAULT_PASSWORD mantiene su default para facilitar el primer login;
    se debe cambiar desde la app después del primer acceso.
"""

import sys
from typing import Optional

from pydantic_settings import BaseSettings

_KNOWN_INSECURE_KEYS = {
    "dev-secret-key-do-not-use-in-production",
    "secret",
    "changeme",
    "",
}


class Settings(BaseSettings):
    """Configuración del backend Venus."""

    # ── Entorno ──
    ENV: str = "local"  # 'local' | 'production'

    # ── Base de datos ──
    DATABASE_PATH: str = "./venus.db"

    # ── JWT ──
    # Sin default: debe venir de variable de entorno (.env en local, secreto Docker en prod)
    SECRET_KEY: Optional[str] = None
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60

    # ── Archivos ──
    UPLOAD_DIR: str = "./uploads"

    # ── Seed ──
    ADMIN_DEFAULT_PASSWORD: str = "admin123"

    model_config = {"env_file": ".env"}

    def model_post_init(self, __context) -> None:
        """Validaciones de seguridad al arrancar."""
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

