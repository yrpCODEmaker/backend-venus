"""
Tests para database.py — Paso 1.

Verifica la creación de tablas, WAL mode, foreign keys y seed admin.
"""

import os
import tempfile

import aiosqlite
import pytest
import pytest_asyncio

from database import init_db


# ---------------------------------------------------------------------------
# Fixture: base de datos temporal para cada test
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def db_path():
    """Crea un archivo SQLite temporal y lo elimina al finalizar."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    # Limpieza: eliminar archivo principal y archivos WAL/SHM
    for ext in ("", "-wal", "-shm"):
        try:
            os.unlink(path + ext)
        except FileNotFoundError:
            pass


@pytest_asyncio.fixture
async def initialized_db(db_path):
    """Base de datos temporal ya inicializada con init_db."""
    await init_db(db_path)
    return db_path


# ---------------------------------------------------------------------------
# Tests de creación de tablas
# ---------------------------------------------------------------------------
EXPECTED_TABLES = sorted([
    "catalogo",
    "clientes",
    "cola_trabajos",
    "comisiones_empleado",
    "configuracion",
    "empleados",
    "envios",
    "facturas",
    "gastos_perfiles",
    "gastos_registros",
    "images",
    "items",
    "materiales",
    "pagos",
    "stock",
    "user_permissions",
    "usuarios",
])


@pytest.mark.asyncio
async def test_init_db_creates_all_tables(initialized_db):
    """init_db debe crear exactamente las 11 tablas del esquema Venus."""
    async with aiosqlite.connect(initialized_db) as db:
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        tables = sorted(row[0] for row in await cursor.fetchall())

    assert tables == EXPECTED_TABLES


@pytest.mark.asyncio
async def test_init_db_is_idempotent(db_path):
    """Llamar init_db dos veces no debe dar error (CREATE TABLE IF NOT EXISTS)."""
    await init_db(db_path)
    await init_db(db_path)  # Segunda llamada — debe ser silenciosa

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        tables = sorted(row[0] for row in await cursor.fetchall())

    assert tables == EXPECTED_TABLES


# ---------------------------------------------------------------------------
# Tests de WAL mode
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_wal_mode_enabled(initialized_db):
    """La base de datos debe estar en modo WAL después de init_db."""
    async with aiosqlite.connect(initialized_db) as db:
        cursor = await db.execute("PRAGMA journal_mode")
        row = await cursor.fetchone()

    assert row[0] == "wal"


# ---------------------------------------------------------------------------
# Tests de foreign keys
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_foreign_keys_enforced(initialized_db):
    """Las foreign keys deben estar habilitadas y rechazar inserciones inválidas."""
    async with aiosqlite.connect(initialized_db) as db:
        await db.execute("PRAGMA foreign_keys=ON")

        # Intentar insertar un pago con factura_id inexistente
        with pytest.raises(aiosqlite.IntegrityError):
            await db.execute(
                "INSERT INTO pagos (id, factura_id, monto) VALUES (?, ?, ?)",
                ("P1", "FACTURA_INEXISTENTE", 100.0),
            )


# ---------------------------------------------------------------------------
# Tests del seed admin
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_admin_user_seeded(initialized_db):
    """El usuario 'pichardo' debe existir con rol 'admin' después de init_db."""
    async with aiosqlite.connect(initialized_db) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT username, rol, prefix, activo FROM usuarios WHERE username = ?",
            ("pichardo",),
        )
        user = await cursor.fetchone()

    assert user is not None
    assert user["username"] == "pichardo"
    assert user["rol"] == "admin"
    assert user["prefix"] == "P"  # Admin tiene prefijo P
    assert user["activo"] == 1


@pytest.mark.asyncio
async def test_admin_password_is_hashed(initialized_db):
    """La contraseña del admin debe estar hasheada con bcrypt, no en texto plano."""
    async with aiosqlite.connect(initialized_db) as db:
        cursor = await db.execute(
            "SELECT hashed_pw FROM usuarios WHERE username = ?",
            ("pichardo",),
        )
        row = await cursor.fetchone()

    hashed = row[0]
    # bcrypt hashes empiezan con '$2b$' o '$2a$'
    assert hashed.startswith("$2b$") or hashed.startswith("$2a$")
    # No debe ser texto plano
    assert hashed != "admin123"


# ---------------------------------------------------------------------------
# Tests de estructura de tablas (columnas clave)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_facturas_table_has_expected_columns(initialized_db):
    """La tabla facturas debe tener las columnas clave del esquema."""
    async with aiosqlite.connect(initialized_db) as db:
        cursor = await db.execute("PRAGMA table_info(facturas)")
        columns = {row[1] for row in await cursor.fetchall()}

    expected_columns = {
        "id", "cliente_id", "cliente", "fecha", "total",
        "monto_pagado", "saldo_pendiente", "items_id",
        "entrega_domicilio", "direccion_entrega", "estatus_entrega",
        "garantia_hasta", "status_garantia", "venc_garantia",
        "facturacion_rapida", "updated_at",
    }
    assert expected_columns.issubset(columns)


@pytest.mark.asyncio
async def test_items_table_has_expected_columns(initialized_db):
    """La tabla items debe tener las columnas clave del esquema."""
    async with aiosqlite.connect(initialized_db) as db:
        cursor = await db.execute("PRAGMA table_info(items)")
        columns = {row[1] for row in await cursor.fetchall()}

    expected_columns = {
        "id", "factura_id", "stock_id", "catalogo_id", "image_id",
        "nombre", "cantidad", "tipo", "subtotal", "tela",
        "material", "descripcion", "area", "tipo_mueble",
        "status", "fecha_procesando", "fecha_procesado",
        "created_at", "updated_at",
    }
    assert expected_columns.issubset(columns)


@pytest.mark.asyncio
async def test_cascade_delete_items_on_factura_delete(initialized_db):
    """Al borrar una factura, sus items deben borrarse en cascada."""
    async with aiosqlite.connect(initialized_db) as db:
        await db.execute("PRAGMA foreign_keys=ON")

        # Insertar cliente, factura e item
        await db.execute(
            "INSERT INTO clientes (id, nombre, apellido, updated_at) VALUES (?, ?, ?, datetime('now'))",
            ("C1", "Juan", "Pérez"),
        )
        await db.execute(
            "INSERT INTO facturas (id, cliente_id, total, updated_at) VALUES (?, ?, ?, datetime('now'))",
            ("F1", "C1", 1000.0),
        )
        await db.execute(
            "INSERT INTO items (id, factura_id, nombre, cantidad, tipo, subtotal, status, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))",
            ("I1", "F1", "Sofá", 1, "encargo", 1000.0, "pendiente"),
        )
        await db.commit()

        # Borrar factura
        await db.execute("DELETE FROM facturas WHERE id = ?", ("F1",))
        await db.commit()

        # Verificar cascada: item ya no existe
        cursor = await db.execute("SELECT COUNT(*) FROM items WHERE factura_id = ?", ("F1",))
        count = (await cursor.fetchone())[0]

    assert count == 0
