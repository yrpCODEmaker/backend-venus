"""
Venus Backend — Base de datos SQLite con aiosqlite.

Provee conexión async a SQLite con WAL mode, creación de las 12 tablas
del esquema Venus, y seed del usuario administrador inicial.

Reemplaza la combinación PostgreSQL + SQLAlchemy + Alembic por SQL directo,
manteniendo la misma estructura de tablas documentada en la arquitectura.

Cambios (Fase 1 — Permisos granulares):
  - Nueva tabla `user_permissions` con relación 1:1 a `usuarios`.
  - Permisos booleanos por dominio: facturas, fabricación, stock, catálogo, clientes.
  - Visibilidad de datos entre usuarios: `puede_ver_datos_de_otros`, `prefijos_visibles`.
  - Seed: admin recibe acceso total; usuarios regulares recibirán permisos restringidos al crearse.
"""

import aiosqlite
import bcrypt

from config import settings


# ---------------------------------------------------------------------------
# DDL — Definición de las 12 tablas
# ---------------------------------------------------------------------------
# Notas de mapeo PostgreSQL → SQLite:
#   - VARCHAR(N) → TEXT (SQLite no diferencia)
#   - SERIAL → INTEGER PRIMARY KEY AUTOINCREMENT
#   - BOOLEAN → INTEGER (0/1)
#   - JSONB → TEXT (JSON como string)
#   - TIMESTAMP → TEXT (ISO 8601)
#   - ON DELETE CASCADE → funciona con PRAGMA foreign_keys=ON

_DDL = """
-- 1. Usuarios del sistema (solo backend, PK autoincremental)
CREATE TABLE IF NOT EXISTS usuarios (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    username     TEXT    UNIQUE NOT NULL,
    hashed_pw    TEXT    NOT NULL,
    rol          TEXT    NOT NULL DEFAULT 'user',
    prefix       TEXT    UNIQUE,
    activo       INTEGER NOT NULL DEFAULT 1,
    totp_secret  TEXT,
    totp_enabled INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT    DEFAULT (datetime('now'))
);

-- 2. Clientes (PK con prefijo = TEXT)
CREATE TABLE IF NOT EXISTS clientes (
    id         TEXT PRIMARY KEY,
    nombre     TEXT NOT NULL,
    apellido   TEXT NOT NULL,
    telefono   TEXT,
    email      TEXT,
    domicilio  TEXT,
    prioridad  INTEGER DEFAULT 0,
    updated_at TEXT,
    deleted_at TEXT
);

-- 3. Imágenes (PK con prefijo)
CREATE TABLE IF NOT EXISTS images (
    id           TEXT PRIMARY KEY,
    aspect_ratio TEXT,
    hash         TEXT,
    file_path    TEXT NOT NULL,
    updated_at   TEXT,
    deleted_at   TEXT
);

-- 4. Catálogo — plantillas genéricas (FK → images)
CREATE TABLE IF NOT EXISTS catalogo (
    id          TEXT PRIMARY KEY,
    nombre      TEXT NOT NULL,
    tipo        TEXT,
    area        TEXT,
    precio_base REAL,
    image_id    TEXT REFERENCES images(id),
    updated_at  TEXT,
    deleted_at  TEXT
);

-- 5. Stock — variantes del catálogo (FK → catalogo, images)
CREATE TABLE IF NOT EXISTS stock (
    id          TEXT PRIMARY KEY,
    catalogo_id TEXT REFERENCES catalogo(id),
    tela        TEXT,
    material    TEXT,
    descripcion TEXT,
    cantidad    INTEGER,
    precio      REAL,
    image_id    TEXT REFERENCES images(id),
    updated_at  TEXT,
    deleted_at  TEXT
);

-- 6. Facturas (FK → clientes) — Hard Delete con cascada
CREATE TABLE IF NOT EXISTS facturas (
    id                 TEXT PRIMARY KEY,
    cliente_id         TEXT REFERENCES clientes(id),
    cliente            TEXT,
    fecha              TEXT,
    total              REAL,
    monto_pagado       REAL    DEFAULT 0,
    saldo_pendiente    REAL,
    items_id           TEXT,
    entrega_domicilio  INTEGER,
    direccion_entrega  TEXT,
    estatus_entrega    TEXT,
    garantia_hasta     TEXT,
    status_garantia    TEXT,
    venc_garantia      TEXT,
    facturacion_rapida INTEGER DEFAULT 0,
    declarado_perdida  INTEGER DEFAULT 0,
    declarado_perdonado INTEGER DEFAULT 0,
    pago_parcial        INTEGER DEFAULT 0,
    updated_at         TEXT
);

-- 7. Pagos / abonos (FK → facturas, cascada)
CREATE TABLE IF NOT EXISTS pagos (
    id         TEXT PRIMARY KEY,
    factura_id TEXT REFERENCES facturas(id) ON DELETE CASCADE,
    monto      REAL NOT NULL,
    fecha      TEXT,
    nota       TEXT,
    created_at TEXT
);

-- 8. Ítems de factura (FK → facturas cascada, stock, catalogo, images)
CREATE TABLE IF NOT EXISTS items (
    id               TEXT PRIMARY KEY,
    factura_id       TEXT REFERENCES facturas(id) ON DELETE CASCADE,
    stock_id         TEXT REFERENCES stock(id),
    catalogo_id      TEXT REFERENCES catalogo(id),
    image_id         TEXT REFERENCES images(id),
    imagenes_apoyo   TEXT DEFAULT '[]',
    nombre           TEXT,
    cantidad         INTEGER,
    tipo             TEXT,
    subtotal         REAL,
    tela             TEXT,
    material         TEXT,
    descripcion      TEXT,
    area             TEXT,
    tipo_mueble      TEXT,
    status           TEXT,
    fecha_procesando TEXT,
    fecha_procesado  TEXT,
    created_at       TEXT,
    updated_at       TEXT
);

-- 9. Envíos (FK → facturas, cascada)
CREATE TABLE IF NOT EXISTS envios (
    id                TEXT PRIMARY KEY,
    factura_id        TEXT REFERENCES facturas(id) ON DELETE CASCADE,
    estado            TEXT,
    direccion_entrega TEXT,
    fecha_programada  TEXT,
    fecha_enviado     TEXT,
    fecha_entregado   TEXT,
    notas             TEXT,
    created_at        TEXT,
    updated_at        TEXT
);

-- 10. Cola de trabajos (FK → facturas, cascada, UNIQUE factura_id)
CREATE TABLE IF NOT EXISTS cola_trabajos (
    id         TEXT PRIMARY KEY,
    factura_id TEXT UNIQUE REFERENCES facturas(id) ON DELETE CASCADE,
    created_at TEXT
);

-- 11. Configuración por usuario (PK con prefijo)
CREATE TABLE IF NOT EXISTS configuracion (
    id         TEXT PRIMARY KEY,
    clave      TEXT NOT NULL,
    valor      TEXT NOT NULL,
    updated_at TEXT
);

-- 12. Permisos granulares por usuario (relación 1:1 con usuarios)
-- Permisos de facturas
-- Permisos de fabricación (items/trabajos)
-- Permisos de envíos
-- Permisos de stock
-- Permisos de catálogo
-- Permisos de clientes
-- Visibilidad de datos entre usuarios
CREATE TABLE IF NOT EXISTS user_permissions (
    user_id                INTEGER PRIMARY KEY REFERENCES usuarios(id) ON DELETE CASCADE,

    -- Facturas
    facturas_ver           INTEGER NOT NULL DEFAULT 1,
    facturas_emitir        INTEGER NOT NULL DEFAULT 0,
    facturas_modificar     INTEGER NOT NULL DEFAULT 0,

    -- Fabricación (items/trabajos)
    fabricacion_ver_estados      INTEGER NOT NULL DEFAULT 1,
    fabricacion_modificar_estados INTEGER NOT NULL DEFAULT 0,
    fabricacion_mandar_envio      INTEGER NOT NULL DEFAULT 0,

    -- Stock
    stock_crear            INTEGER NOT NULL DEFAULT 0,
    stock_modificar        INTEGER NOT NULL DEFAULT 0,
    stock_eliminar         INTEGER NOT NULL DEFAULT 0,

    -- Catálogo
    catalogo_crear         INTEGER NOT NULL DEFAULT 0,
    catalogo_modificar     INTEGER NOT NULL DEFAULT 0,
    catalogo_eliminar      INTEGER NOT NULL DEFAULT 0,

    -- Clientes
    clientes_crear         INTEGER NOT NULL DEFAULT 0,
    clientes_modificar     INTEGER NOT NULL DEFAULT 0,
    clientes_eliminar      INTEGER NOT NULL DEFAULT 0,

    -- Visibilidad de datos entre usuarios
    puede_ver_datos_de_otros INTEGER NOT NULL DEFAULT 0,
    prefijos_visibles        TEXT    NOT NULL DEFAULT '[]',  -- JSON array de prefijos

    updated_at TEXT DEFAULT (datetime('now'))
);

-- 13. Materiales y catálogos auxiliares (categorías, elementos, color)
CREATE TABLE IF NOT EXISTS materiales (
    id         TEXT PRIMARY KEY,
    categoria  TEXT NOT NULL,
    elementos  TEXT NOT NULL DEFAULT '[]',
    color      TEXT DEFAULT NULL,
    updated_at TEXT DEFAULT (datetime('now'))
);

-- 14. Finanzas y Nóminas
CREATE TABLE IF NOT EXISTS empleados (
    id                TEXT PRIMARY KEY,
    nombre            TEXT NOT NULL,
    telefono          TEXT,
    telefono_familiar TEXT,
    rol               TEXT,
    salario_fijo      REAL DEFAULT 0,
    gana_comision     INTEGER DEFAULT 0,
    dia_cobro         INTEGER,
    created_at        TEXT,
    updated_at        TEXT
);

CREATE TABLE IF NOT EXISTS comisiones_empleado (
    id          TEXT PRIMARY KEY,
    empleado_id TEXT REFERENCES empleados(id) ON DELETE CASCADE,
    catalogo_id TEXT REFERENCES catalogo(id) ON DELETE CASCADE,
    monto       REAL NOT NULL,
    UNIQUE(empleado_id, catalogo_id)
);

CREATE TABLE IF NOT EXISTS gastos_perfiles (
    id         TEXT PRIMARY KEY,
    nombre     TEXT NOT NULL,
    tipo       TEXT NOT NULL,
    dia_pago   INTEGER,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS gastos_registros (
    id         TEXT PRIMARY KEY,
    perfil_id  TEXT REFERENCES gastos_perfiles(id) ON DELETE CASCADE,
    monto      REAL NOT NULL,
    fecha      TEXT NOT NULL,
    nota       TEXT,
    created_at TEXT
);
"""


# ---------------------------------------------------------------------------
# Conexión y dependencia FastAPI
# ---------------------------------------------------------------------------
async def get_db():
    """
    Dependencia inyectable de FastAPI.

    Abre una conexión SQLite con WAL mode y foreign keys habilitadas.
    La conexión se cierra automáticamente al terminar el request.
    """
    db = await aiosqlite.connect(settings.DATABASE_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
    finally:
        await db.close()


async def migrate_prefix_hyphens(db: aiosqlite.Connection):
    """
    Migra los registros existentes en la BD para que todos los IDs tengan el prefijo
    separado por un guion ('-'), por ejemplo 'P-1' o 'y-ye897e4b'.
    """
    cursor = await db.execute("SELECT DISTINCT prefix FROM usuarios WHERE prefix IS NOT NULL AND prefix != ''")
    prefixes = [row[0] for row in await cursor.fetchall()]
    if "admin" not in prefixes:
        prefixes.append("admin")

    prefixes.sort(key=len, reverse=True)

    await db.execute("PRAGMA foreign_keys=OFF")

    tables_and_fk = [
        ("clientes", "id", [("facturas", "cliente_id")]),
        ("catalogo", "id", [("stock", "catalogo_id"), ("items", "catalogo_id")]),
        ("images", "id", [("catalogo", "image_id"), ("stock", "image_id"), ("items", "image_id")]),
        ("stock", "id", [("items", "stock_id")]),
        ("facturas", "id", [("items", "factura_id"), ("pagos", "factura_id"), ("envios", "factura_id"), ("cola_trabajos", "factura_id")]),
        ("items", "id", []),
        ("pagos", "id", []),
        ("envios", "id", []),
        ("cola_trabajos", "id", []),
        ("configuracion", "id", []),
    ]

    for p in prefixes:
        hyphen_p = f"{p}-"
        for table, id_col, fk_list in tables_and_fk:
            c = await db.execute(
                f"SELECT {id_col} FROM {table} WHERE {id_col} LIKE ? AND {id_col} NOT LIKE ?",
                (f"{p}%", f"{hyphen_p}%")
            )
            rows = await c.fetchall()
            for (old_id,) in rows:
                if not old_id or old_id.startswith(hyphen_p):
                    continue
                if old_id.startswith(p):
                    rest = old_id[len(p):]
                    new_id = f"{p}-{rest}"

                    for fk_table, fk_col in fk_list:
                        await db.execute(
                            f"UPDATE {fk_table} SET {fk_col} = ? WHERE {fk_col} = ?",
                            (new_id, old_id)
                        )

                    await db.execute(
                        f"UPDATE {table} SET {id_col} = ? WHERE {id_col} = ?",
                        (new_id, old_id)
                    )

    await db.execute("PRAGMA foreign_keys=ON")
    await db.commit()


# ---------------------------------------------------------------------------
# Inicialización y seed
# ---------------------------------------------------------------------------
async def init_db(db_path: str | None = None):
    """
    Crea todas las tablas (IF NOT EXISTS), ejecuta el seed del admin y migra prefijos con guion.
    """
    path = db_path or settings.DATABASE_PATH

    async with aiosqlite.connect(path) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")
        await db.executescript(_DDL)

        # Migración: Añadir columnas declarado_perdida y declarado_perdonado a facturas si no existen
        try:
            await db.execute("ALTER TABLE facturas ADD COLUMN declarado_perdida INTEGER DEFAULT 0")
        except Exception:
            pass  # Ya existe
        try:
            await db.execute("ALTER TABLE facturas ADD COLUMN declarado_perdonado INTEGER DEFAULT 0")
        except Exception:
            pass  # Ya existe
        try:
            await db.execute("ALTER TABLE facturas ADD COLUMN pago_parcial INTEGER DEFAULT 0")
        except Exception:
            pass  # Ya existe
        try:
            await db.execute("ALTER TABLE images ADD COLUMN hash TEXT")
        except Exception:
            pass  # Ya existe
        try:
            await db.execute("ALTER TABLE items ADD COLUMN imagenes_apoyo TEXT DEFAULT '[]'")
        except Exception:
            pass  # Ya existe
        try:
            await db.execute("ALTER TABLE usuarios ADD COLUMN totp_secret TEXT")
        except Exception:
            pass  # Ya existe
        try:
            await db.execute("ALTER TABLE usuarios ADD COLUMN totp_enabled INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass  # Ya existe

        hashed = bcrypt.hashpw(
            settings.ADMIN_DEFAULT_PASSWORD.encode("utf-8"),
            bcrypt.gensalt(),
        ).decode("utf-8")
        
        admin_username = settings.ADMIN_DEFAULT_USERNAME
        admin_prefix = admin_username[0].upper() if admin_username else "A"

        await db.execute(
            """
            INSERT OR IGNORE INTO usuarios (username, hashed_pw, rol, prefix, activo)
            VALUES (?, ?, 'admin', ?, 1)
            """,
            (admin_username, hashed, admin_prefix),
        )
        await db.execute(
            """
            UPDATE usuarios SET prefix = ? WHERE username = ? AND (prefix IS NULL OR prefix != ?)
            """,
            (admin_prefix, admin_username, admin_prefix)
        )

        await db.execute(
            """
            INSERT OR IGNORE INTO user_permissions (
                user_id,
                facturas_ver, facturas_emitir, facturas_modificar,
                fabricacion_ver_estados, fabricacion_modificar_estados, fabricacion_mandar_envio,
                stock_crear, stock_modificar, stock_eliminar,
                catalogo_crear, catalogo_modificar, catalogo_eliminar,
                clientes_crear, clientes_modificar, clientes_eliminar,
                puede_ver_datos_de_otros, prefijos_visibles
            )
            SELECT id,
                   1, 1, 1,
                   1, 1, 1,
                   1, 1, 1,
                   1, 1, 1,
                   1, 1, 1,
                   1, '[]'
            FROM usuarios WHERE username = ?
            """,
            (admin_username,)
        )
        await db.commit()

        # Ejecutar migración automática de guiones en IDs
        await migrate_prefix_hyphens(db)

        # Seed inicial de materiales si la tabla está vacía
        cursor = await db.execute("SELECT COUNT(*) FROM materiales")
        if (await cursor.fetchone())[0] == 0:
            import json
            await db.execute(
                "INSERT INTO materiales (id, categoria, elementos, color) VALUES (?, ?, ?, ?)",
                ("MAT-1", "Materiales", json.dumps(["Madera Pino", "Madera Caoba", "MDF", "Metal", "Cristal"]), None)
            )
            await db.execute(
                "INSERT INTO materiales (id, categoria, elementos, color) VALUES (?, ?, ?, ?)",
                ("MAT-2", "Telas", json.dumps(["Lino", "Terciopelo", "Sintético", "Cuero", "Yute"]), json.dumps(["Rojo", "Azul", "Verde", "Gris", "Beige", "Negro", "Blanco"]))
            )
            await db.execute(
                "INSERT INTO materiales (id, categoria, elementos, color) VALUES (?, ?, ?, ?)",
                ("MAT-3", "tipo_mueble", json.dumps(["Sofá", "Cama", "Mesa", "Silla", "Gavetero", "Juego de Habitación"]), None)
            )
            await db.execute(
                "INSERT INTO materiales (id, categoria, elementos, color) VALUES (?, ?, ?, ?)",
                ("MAT-4", "areas", json.dumps(["Tapicería", "Ebanistería", "Metales", "Cristalería", "Mixto"]), None)
            )
            await db.commit()
