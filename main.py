"""
Venus Backend — Punto de entrada principal.

Servidor FastAPI para sincronización de datos del sistema Venus
(Fábrica de muebles — Ebanistería y Tapicería).
"""

import asyncio
from contextlib import asynccontextmanager
from typing import Optional

import aiosqlite
import os
from fastapi import FastAPI, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from database import init_db, get_db
from routers import admin as admin_router
from routers import auth as auth_router
from routers import operacional as operacional_router
from routers import sync as sync_router
from routers import nominas as nominas_router
from routers import finanzas as finanzas_router
from services.auth import get_current_user


# ---------------------------------------------------------------------------
# Tarea programada: expiración de garantías
# ---------------------------------------------------------------------------
async def _check_expired_warranties():
    """Marca como 'Expirada' las garantías cuya fecha de vencimiento ya pasó."""
    async with aiosqlite.connect(settings.DATABASE_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("""
            UPDATE facturas
            SET status_garantia = 'Expirada',
                updated_at = datetime('now')
            WHERE venc_garantia IS NOT NULL
              AND venc_garantia < datetime('now')
              AND status_garantia = 'Vigente'
        """)
        await db.commit()


async def _warranty_cron():
    """Ejecuta check_expired_warranties cada 24 horas."""
    while True:
        try:
            await _check_expired_warranties()
        except Exception as e:
            print(f"⚠️ Error en warranty cron: {e}")
        await asyncio.sleep(86400)  # 24 horas


# ---------------------------------------------------------------------------
# Lifespan: lógica de startup / shutdown
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Eventos del ciclo de vida del servidor.
    - Startup: inicializa BD, check de garantías, lanza cron.
    - Shutdown: cancela cron.
    """
    # ── Startup ──
    print("🚀 Venus Backend iniciando...")
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    await init_db()
    print("✅ Base de datos inicializada.")

    # Check inmediato de garantías expiradas
    await _check_expired_warranties()
    print("✅ Garantías verificadas.")

    # Lanzar cron de garantías
    cron_task = asyncio.create_task(_warranty_cron())

    yield

    # ── Shutdown ──
    cron_task.cancel()
    print("🛑 Venus Backend detenido.")


# ---------------------------------------------------------------------------
# Instancia principal de FastAPI
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Venus Backend",
    description=(
        "API de sincronización para el sistema Venus. "
        "Respaldo remoto, sincronización multi-dispositivo y gestión multi-usuario "
        "para una fábrica de muebles personalizados."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Archivos estáticos (/uploads)
# ---------------------------------------------------------------------------
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")

# ---------------------------------------------------------------------------
# CORS — Permitir conexiones desde el cliente desktop (Flet)
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En producción, restringir a orígenes conocidos
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Health Check
# ---------------------------------------------------------------------------
@app.get("/health", tags=["Sistema"])
async def health_check():
    """Verifica que el servidor está corriendo."""
    return {"status": "ok", "service": "venus-backend"}


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(auth_router.router)
app.include_router(admin_router.router)
app.include_router(sync_router.router)
app.include_router(operacional_router.router)
app.include_router(nominas_router.router)
app.include_router(finanzas_router.router)


# ---------------------------------------------------------------------------
# Endpoint protegido de imágenes
# ---------------------------------------------------------------------------
async def _get_image_user(
    db: aiosqlite.Connection = Depends(get_db),
    request: Request = None,
) -> dict:
    """
    Dependencia especial para el endpoint de imágenes.
    Requiere el JWT en el Header 'Authorization: Bearer {token}'.
    """
    from fastapi import Request
    from jose import JWTError, jwt

    raw_token = None

    if request is not None:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            raw_token = auth_header[7:]

    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token requerido para acceder a imágenes",
            headers={"WWW-Authenticate": "Bearer"},
        )

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token inválido o expirado",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(
            raw_token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    cursor = await db.execute(
        "SELECT username, rol, prefix, activo FROM usuarios WHERE username = ?",
        (username,),
    )
    row = await cursor.fetchone()
    if not row or not row[3]:
        raise credentials_exception

    return {"username": row[0], "rol": row[1], "prefix": row[2]}


@app.get("/api/v1/images/{image_id}", tags=["Imágenes"])
async def get_image_protected(
    image_id: str,
    request: Request,
    token: Optional[str] = None,
    db: aiosqlite.Connection = Depends(get_db),
):
    """
    Sirve un archivo de imagen con autenticación JWT requerida.

    Según el workflow Venus, las imágenes son activos privados del negocio
    y solo deben ser accesibles por usuarios autenticados (operarios, admin).

    Acepta el token:
    - Header Authorization: Bearer {token}
    - Query param: ?token={token}
    """
    # Validar autenticación — el token puede llegar por header o por query param
    from jose import JWTError, jwt

    raw_token = token  # query param tiene prioridad si se envía
    if not raw_token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            raw_token = auth_header[7:]

    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token requerido para acceder a imágenes",
            headers={"WWW-Authenticate": "Bearer"},
        )

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token inválido o expirado",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(raw_token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    cursor = await db.execute("SELECT username, activo FROM usuarios WHERE username = ?", (username,))
    row = await cursor.fetchone()
    if not row or not row[1]:
        raise credentials_exception

    # Buscar la imagen — exacto primero, luego con prefijos alternativos
    cursor = await db.execute(
        "SELECT file_path FROM images WHERE id = ?",
        (image_id,),
    )
    row = await cursor.fetchone()
    if not row:
        # Intentar variantes: con/sin prefijo
        for variant in [f"P-{image_id}", image_id.lstrip("P-"), f"P{image_id}"]:
            cursor = await db.execute("SELECT file_path FROM images WHERE id = ?", (variant,))
            row = await cursor.fetchone()
            if row:
                break
    if not row:
        raise HTTPException(status_code=404, detail="Imagen no encontrada")

    file_path = row[0]

    # Resolver ruta absoluta
    if file_path.startswith("/uploads/") or file_path.startswith("uploads/"):
        relative = file_path.lstrip("/")
        abs_path = os.path.join(settings.UPLOAD_DIR, os.path.relpath(relative, "uploads"))
    elif os.path.isabs(file_path):
        abs_path = file_path
    else:
        abs_path = os.path.join(settings.UPLOAD_DIR, file_path)

    if not os.path.exists(abs_path):
        # Segundo intento: buscar solo por nombre de archivo bajo UPLOAD_DIR
        fname = os.path.basename(file_path)
        for root, _, files in os.walk(settings.UPLOAD_DIR):
            if fname in files:
                abs_path = os.path.join(root, fname)
                break
        else:
            raise HTTPException(status_code=404, detail="Archivo de imagen no encontrado en disco")

    return FileResponse(abs_path)
