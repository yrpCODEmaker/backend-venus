"""
Venus Backend — Servicio de sincronización.

Contiene:
- PrefixTransformer: conversión de IDs locales (int) ↔ remotos (str con prefijo)
- process_push: recibe payload del cliente, transforma IDs, ejecuta UPSERTs con LWW
- process_pull: retorna registros modificados desde last_sync con IDs enteros
"""

import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

import aiosqlite


# ===========================================================================
# PREFIX TRANSFORMER
# ===========================================================================

class PrefixTransformer:
    """
    Convierte IDs enteros locales a IDs de string con prefijo para la BD remota,
    y viceversa. Cubre todas las entidades sincronizables.
    """

    def __init__(self, prefix: str):
        self.prefix = (prefix or "").rstrip("-")

    def to_remote(self, local_id: Optional[int]) -> Optional[str]:
        return f"{self.prefix}-{local_id}" if local_id is not None else None

    def to_local(self, remote_id: Optional[str]) -> Optional[Union[int, str]]:
        """
        Quita el prefijo del servidor si coincide con el del usuario.
        Retorna int si es numérico, o str si es un ID generado en el servidor.
        """
        if not remote_id:
            return None
        
        # Formato con guion (ej: 'P-1', 'y-ye897e4b')
        if "-" in remote_id:
            parts = remote_id.split("-", 1)
            if parts[0] == self.prefix:
                try:
                    return int(parts[1])
                except ValueError:
                    return parts[1]
            return remote_id

        # Compatibilidad sin guion (ej: 'P1')
        if remote_id.startswith(self.prefix):
            stripped = remote_id[len(self.prefix):]
            if not stripped:
                return None
            try:
                return int(stripped)
            except ValueError:
                return stripped

        return remote_id

    # --- Helpers genéricos ---

    def _base_transform(self, data, pk_field="local_id", fk_map: dict = None) -> dict:
        """
        Transformación genérica: convierte PK y un mapa de FKs.
        fk_map: {"campo": "campo"} — nombre del campo a transformar.
        """
        d = data.model_dump()
        d["id"] = self.to_remote(getattr(data, pk_field))
        if fk_map:
            for dict_key, attr_name in fk_map.items():
                d[dict_key] = self.to_remote(getattr(data, attr_name))
        return d

    # --- Transformadores por entidad ---

    def transform_cliente(self, data) -> dict:
        return self._base_transform(data)

    def transform_image(self, data) -> dict:
        d = self._base_transform(data)
        # SEGURIDAD: el file_path del cliente nunca se persiste directamente.
        # El backend genera su propia ruta al recibir la imagen física via /upload_image.
        # Persisitir una ruta controlada por el cliente abriría un vector LFI.
        d["file_path"] = None
        return d

    def transform_catalogo(self, data) -> dict:
        return self._base_transform(data, fk_map={"image_id": "image_id"})

    def transform_stock(self, data) -> dict:
        return self._base_transform(data, fk_map={
            "catalogo_id": "catalogo_id",
            "image_id": "image_id",
        })

    def transform_factura(self, data) -> dict:
        """Transforma incluyendo el CSV de items_id."""
        d = self._base_transform(data, fk_map={"cliente_id": "cliente_id"})
        # "1,2,3" → "L1,L2,L3"
        if data.items_id:
            ids = [i.strip() for i in data.items_id.split(",")]
            d["items_id"] = ",".join(
                self.to_remote(int(i)) for i in ids if i
            )
        return d

    def transform_pago(self, data) -> dict:
        return self._base_transform(data, fk_map={"factura_id": "factura_id"})

    def transform_item(self, data) -> dict:
        return self._base_transform(data, fk_map={
            "factura_id": "factura_id",
            "stock_id": "stock_id",
            "catalogo_id": "catalogo_id",
            "image_id": "image_id",
        })

    def transform_envio(self, data) -> dict:
        return self._base_transform(data, fk_map={"factura_id": "factura_id"})

    def transform_cola_trabajo(self, data) -> dict:
        return self._base_transform(data, fk_map={"factura_id": "factura_id"})

    def transform_configuracion(self, data) -> dict:
        return self._base_transform(data)


# ===========================================================================
# UPSERT HELPER — Last-Write-Wins
# ===========================================================================

async def _upsert_rows(
    db: aiosqlite.Connection,
    table: str,
    rows: List[dict],
    columns: List[str],
    lww_column: str = "updated_at",
):
    """
    Ejecuta INSERT ... ON CONFLICT(id) DO UPDATE con Last-Write-Wins.

    Solo sobrescribe si el registro entrante tiene updated_at más reciente.
    Para tablas sin updated_at (pagos, cola_trabajos) se usa created_at.
    """
    if not rows:
        return 0

    count = 0
    # Construir el SQL dinámicamente
    placeholders = ", ".join(["?"] * len(columns))
    col_list = ", ".join(columns)

    # SET clause: actualiza todos los campos excepto 'id'
    update_cols = [c for c in columns if c != "id"]
    set_clause = ", ".join(f"{c} = excluded.{c}" for c in update_cols)

    # WHERE clause: solo actualizar si el nuevo registro es más reciente
    where_clause = f"{table}.{lww_column} < excluded.{lww_column}"

    sql = f"""
        INSERT INTO {table} ({col_list})
        VALUES ({placeholders})
        ON CONFLICT(id) DO UPDATE SET {set_clause}
        WHERE {where_clause}
    """

    for row in rows:
        values = []
        for col in columns:
            val = row.get(col)
            # Serializar dicts/lists a JSON string para campos TEXT
            if isinstance(val, (dict, list)):
                val = json.dumps(val, default=str)
            elif isinstance(val, datetime):
                val = val.isoformat()
            elif isinstance(val, bool):
                val = int(val)
            values.append(val)

        cursor = await db.execute(sql, values)
        count += cursor.rowcount

    return count


# ===========================================================================
# PROCESS PUSH
# ===========================================================================

# Mapeo de entidades: (tabla, columnas, transform_method, lww_column)
# El orden respeta dependencias FK
_ENTITY_CONFIG = [
    ("clientes", [
        "id", "nombre", "apellido", "telefono", "email", "domicilio",
        "prioridad", "updated_at", "deleted_at",
    ], "transform_cliente", "updated_at"),

    ("images", [
        "id", "aspect_ratio", "hash", "file_path", "updated_at", "deleted_at",
    ], "transform_image", "updated_at"),

    ("configuracion", [
        "id", "clave", "valor", "updated_at",
    ], "transform_configuracion", "updated_at"),

    ("catalogo", [
        "id", "nombre", "tipo", "area", "precio_base", "image_id",
        "updated_at", "deleted_at",
    ], "transform_catalogo", "updated_at"),

    ("stock", [
        "id", "catalogo_id", "tela", "material", "descripcion",
        "cantidad", "precio", "image_id", "updated_at", "deleted_at",
    ], "transform_stock", "updated_at"),

    ("facturas", [
        "id", "cliente_id", "cliente", "fecha", "total", "monto_pagado",
        "saldo_pendiente", "items_id", "entrega_domicilio",
        "direccion_entrega", "estatus_entrega", "garantia_hasta",
        "status_garantia", "venc_garantia", "facturacion_rapida", "updated_at",
    ], "transform_factura", "updated_at"),

    ("pagos", [
        "id", "factura_id", "monto", "fecha", "nota", "created_at",
    ], "transform_pago", "created_at"),

    ("items", [
        "id", "factura_id", "stock_id", "catalogo_id", "image_id",
        "nombre", "cantidad", "tipo", "subtotal", "tela", "material",
        "descripcion", "area", "tipo_mueble", "status",
        "fecha_procesando", "fecha_procesado", "created_at", "updated_at",
    ], "transform_item", "updated_at"),

    ("envios", [
        "id", "factura_id", "estado", "direccion_entrega",
        "fecha_programada", "fecha_enviado", "fecha_entregado",
        "notas", "created_at", "updated_at",
    ], "transform_envio", "updated_at"),

    ("cola_trabajos", [
        "id", "factura_id", "created_at",
    ], "transform_cola_trabajo", "created_at"),
]

# Mapeo nombre_payload → nombre_tabla para lookup
_PAYLOAD_TO_TABLE = {
    "clientes": "clientes",
    "images": "images",
    "configuracion": "configuracion",
    "catalogo": "catalogo",
    "stock": "stock",
    "facturas": "facturas",
    "pagos": "pagos",
    "items": "items",
    "envios": "envios",
    "cola_trabajos": "cola_trabajos",
}


async def process_push(
    db: aiosqlite.Connection,
    payload,  # PushSyncPayload
    prefix: str,
) -> Dict[str, int]:
    """
    Procesa un Push Sync: transforma IDs con prefijo y ejecuta UPSERTs.

    Retorna un dict con la cantidad de registros insertados/actualizados por tabla.
    """
    transformer = PrefixTransformer(prefix)
    results = {}

    for table, columns, transform_method, lww_col in _ENTITY_CONFIG:
        # Obtener la lista de datos del payload
        payload_key = table  # Los nombres coinciden
        items_data = getattr(payload, payload_key, [])

        if not items_data:
            results[table] = 0
            continue

        # Transformar cada registro
        transform_fn = getattr(transformer, transform_method)
        transformed = [transform_fn(item) for item in items_data]

        # Ejecutar UPSERT
        count = await _upsert_rows(db, table, transformed, columns, lww_col)
        results[table] = count

    await db.commit()
    return results


# ===========================================================================
# PROCESS PULL
# ===========================================================================

# Columnas para pull (lo que se retorna al cliente)
_PULL_CONFIG = [
    ("clientes", [
        "id", "nombre", "apellido", "telefono", "email", "domicilio",
        "prioridad", "updated_at", "deleted_at",
    ], ["id"]),

    ("images", [
        "id", "aspect_ratio", "hash", "file_path", "updated_at", "deleted_at",
    ], ["id"]),

    ("configuracion", [
        "id", "clave", "valor", "updated_at",
    ], ["id"]),

    ("catalogo", [
        "id", "nombre", "tipo", "area", "precio_base", "image_id",
        "updated_at", "deleted_at",
    ], ["id", "image_id"]),

    ("stock", [
        "id", "catalogo_id", "tela", "material", "descripcion",
        "cantidad", "precio", "image_id", "updated_at", "deleted_at",
    ], ["id", "catalogo_id", "image_id"]),

    ("facturas", [
        "id", "cliente_id", "cliente", "fecha", "total", "monto_pagado",
        "saldo_pendiente", "items_id", "entrega_domicilio",
        "direccion_entrega", "estatus_entrega", "garantia_hasta",
        "status_garantia", "venc_garantia", "facturacion_rapida", "updated_at",
    ], ["id", "cliente_id"]),

    ("pagos", [
        "id", "factura_id", "monto", "fecha", "nota", "created_at",
    ], ["id", "factura_id"]),

    ("items", [
        "id", "factura_id", "stock_id", "catalogo_id", "image_id",
        "nombre", "cantidad", "tipo", "subtotal", "tela", "material",
        "descripcion", "area", "tipo_mueble", "status",
        "fecha_procesando", "fecha_procesado", "created_at", "updated_at",
    ], ["id", "factura_id", "stock_id", "catalogo_id", "image_id"]),

    ("envios", [
        "id", "factura_id", "estado", "direccion_entrega",
        "fecha_programada", "fecha_enviado", "fecha_entregado",
        "notas", "created_at", "updated_at",
    ], ["id", "factura_id"]),

    ("cola_trabajos", [
        "id", "factura_id", "created_at",
    ], ["id", "factura_id"]),
]


async def process_pull(
    db: aiosqlite.Connection,
    prefix: str,
    last_sync: Optional[str] = None,
) -> Dict[str, List[dict]]:
    """
    Procesa un Pull Sync: retorna registros del usuario (filtrados por prefijo)
    modificados desde last_sync, con IDs convertidos de vuelta a enteros.
    """
    transformer = PrefixTransformer(prefix)
    result = {}

    for table, columns, id_columns in _PULL_CONFIG:
        col_list = ", ".join(columns)

        # Filtrar por prefijo: solo registros de este usuario
        # Los IDs de este usuario empiezan con su prefijo
        conditions = [f"id LIKE '{prefix}%'"]

        # Determinar la columna de tiempo para el delta
        time_col = "updated_at" if "updated_at" in columns else "created_at"

        if last_sync:
            conditions.append(f"{time_col} > ?")
            params = (last_sync,)
        else:
            params = ()

        where = " AND ".join(conditions)
        sql = f"SELECT {col_list} FROM {table} WHERE {where}"

        cursor = await db.execute(sql, params)
        rows = await cursor.fetchall()

        # Convertir a dicts con IDs enteros (prefijo eliminado)
        records = []
        for row in rows:
            record = {}
            for i, col in enumerate(columns):
                val = row[i]
                if col in id_columns and val is not None:
                    # Convertir ID remoto → local (entero)
                    record["local_id" if col == "id" else col] = transformer.to_local(val)
                elif col == "items_id" and val is not None:
                    # "L1,L2,L3" → "1,2,3"
                    ids = [s.strip() for s in val.split(",") if s.strip()]
                    record[col] = ",".join(
                        str(transformer.to_local(i)) for i in ids
                    )
                elif col == "cliente" and val is not None:
                    # JSON string → dict
                    try:
                        record[col] = json.loads(val)
                    except (json.JSONDecodeError, TypeError):
                        record[col] = val
                elif col == "valor" and table == "configuracion" and val is not None:
                    try:
                        record[col] = json.loads(val)
                    except (json.JSONDecodeError, TypeError):
                        record[col] = val
                elif col == "prioridad" and val is not None:
                    record[col] = bool(val)
                elif col == "entrega_domicilio" and val is not None:
                    record[col] = bool(val)
                else:
                    record[col] = val
            records.append(record)

        result[table] = records

    return result
