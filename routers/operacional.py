"""
Venus Backend — Router operacional.

Endpoints REST para operaciones CRUD granulares:
- Facturas (CRUD transaccional, dispatch)
- Items (status, modificar, foto, eliminar)
- Pagos (crear, listar)
- Envíos (status, modificar)
- Clientes (CRUD + soft delete)
- Catálogo (CRUD + soft delete)
- Stock (CRUD + ajuste de cantidad + soft delete)
- Configuración (GET/PUT)

Cambios (Fase 4 — Guards de permisos granulares):
  - Todos los endpoints de escritura/borrado usan `require_permission(action)` como dependencia.
  - Endpoints de lectura (GET) protegidos con `facturas_ver`, `fabricacion_ver_estados`, etc.
  - El admin siempre tiene acceso total (bypass automático en require_permission).
"""

import json
import os
import uuid
from typing import Optional

import aiosqlite
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from config import settings
from database import get_db
from schemas import (
    CatalogoCreateIn,
    CatalogoUpdateIn,
    ClienteCreateIn,
    ClienteUpdateIn,
    ConfigUpdateIn,
    EnvioStatusUpdate,
    EnvioUpdateIn,
    FacturaCreateIn,
    FacturaUpdateIn,
    ItemAddIn,
    ItemPhotoUpdate,
    ItemStatusUpdate,
    ItemUpdateIn,
    PagoCreateIn,
    StockCantidadUpdate,
    StockCreateIn,
    StockUpdateIn,
    MaterialOut,
    MaterialCreateIn,
    MaterialUpdateIn,
)
from services.auth import get_current_user, require_permission
from services.image_service import calculate_aspect_ratio, get_or_create_image
from services.factura_service import (
    _gen_id,
    _now_iso,
    create_factura,
    delete_factura,
    dispatch_factura,
    update_envio_status,
    update_item_status,
)
from services.sync import PrefixTransformer

router = APIRouter(prefix="/api/v1", tags=["Operacional"])


def _normalize_area_to_json(area_input: Optional[str]) -> Optional[str]:
    if not area_input:
        return None
    area_input = area_input.strip()
    if not area_input:
        return None

    # Si ya es un JSON array string válido
    if area_input.startswith("[") and area_input.endswith("]"):
        try:
            parsed = json.loads(area_input)
            if isinstance(parsed, list):
                clean_list = [str(x).strip() for x in parsed if str(x).strip()]
                return json.dumps(clean_list, ensure_ascii=False)
        except Exception:
            pass

    # Si viene separado por comas
    parts = [p.strip() for p in area_input.split(",") if p.strip()]
    return json.dumps(parts, ensure_ascii=False)


def get_allowed_prefixes_clause(current_user: dict, id_field: str = "id") -> tuple[str, list]:
    """
    Construye la cláusula SQL WHERE y sus parámetros basándose en la visibilidad del usuario.
    - Si es admin O tiene 'puede_ver_datos_de_otros' == True: ve TODO (1=1).
    - De lo contrario, consulta los registros de su propio prefijo + prefijos_visibles.
    """
    if current_user.get("rol") == "admin":
        return "1=1", []

    perms = current_user.get("permissions", {})
    if perms.get("puede_ver_datos_de_otros"):
        return "1=1", []

    user_prefix = current_user.get("prefix", "")
    prefijos_visibles = perms.get("prefijos_visibles") or []

    all_prefixes = list(set(([user_prefix] if user_prefix else []) + list(prefijos_visibles)))
    all_prefixes = [p for p in all_prefixes if p]

    if not all_prefixes:
        return "1=1", []

    clause = "(" + " OR ".join([f"{id_field} LIKE ?" for _ in all_prefixes]) + ")"
    params = [f"{p}%" for p in all_prefixes]
    return clause, params

# FACTURAS
# ===========================================================================

@router.get("/facturas")
async def list_facturas(
    search: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    current_user: dict = Depends(require_permission("facturas_ver")),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Lista las facturas del usuario de forma paginada y filtrada."""
    clause, clause_params = get_allowed_prefixes_clause(current_user, "f.id")
    
    query = f"""
        SELECT f.*, 
               COALESCE(c.nombre, json_extract(f.cliente, '$.nombre')) as cliente_nombre,
               COALESCE(c.apellido, json_extract(f.cliente, '$.apellido')) as cliente_apellido
        FROM facturas f
        LEFT JOIN clientes c ON f.cliente_id = c.id
        WHERE {clause}
    """
    params = clause_params.copy()
    
    if search:
        query += " AND (f.id LIKE ? OR f.cliente_id IN (SELECT id FROM clientes WHERE nombre LIKE ? OR apellido LIKE ?))"
        search_term = f"%{search}%"
        params.extend([search_term, search_term, search_term])
        
    if start_date:
        query += " AND f.fecha >= ?"
        params.append(start_date)
        
    if end_date:
        query += " AND f.fecha <= ?"
        params.append(end_date)
        
    query += " ORDER BY f.fecha DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    
    cursor = await db.execute(query, params)
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in await cursor.fetchall()]


@router.post("/facturas", status_code=status.HTTP_201_CREATED)
async def create_factura_endpoint(
    data: FacturaCreateIn,
    current_user: dict = Depends(require_permission("facturas_emitir")),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Crea una factura transaccional con ítems y pago inicial."""
    prefix = current_user.get("prefix")
    if not prefix:
        raise HTTPException(status_code=403, detail="Admin no puede crear facturas directamente.")
    return await create_factura(db, data, prefix)


@router.get("/facturas/{factura_id}")
async def get_factura(
    factura_id: str,
    current_user: dict = Depends(require_permission("facturas_ver")),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Retorna el detalle de una factura con sus ítems y pagos."""
    cursor = await db.execute("SELECT * FROM facturas WHERE id = ?", (factura_id,))
    factura = await cursor.fetchone()
    if not factura:
        raise HTTPException(status_code=404, detail="Factura no encontrada")

    cols = [d[0] for d in cursor.description]
    factura_dict = dict(zip(cols, factura))

    # Ítems
    cursor = await db.execute("SELECT * FROM items WHERE factura_id = ?", (factura_id,))
    items_cols = [d[0] for d in cursor.description]
    items = [dict(zip(items_cols, row)) for row in await cursor.fetchall()]

    # Pagos
    cursor = await db.execute(
        "SELECT * FROM pagos WHERE factura_id = ? ORDER BY fecha DESC", (factura_id,)
    )
    pagos_cols = [d[0] for d in cursor.description]
    pagos = [dict(zip(pagos_cols, row)) for row in await cursor.fetchall()]

    for item in items:
        item["color"] = item.get("tela")

    factura_dict["items"] = items
    factura_dict["pagos"] = pagos
    return factura_dict


@router.patch("/facturas/{factura_id}")
async def patch_factura(
    factura_id: str,
    data: FacturaUpdateIn,
    current_user: dict = Depends(require_permission("facturas_modificar")),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Actualiza campos parciales de una factura."""
    updates = []
    values = []
    prefix = current_user.get("prefix", "")

    if data.cliente_id is not None:
        updates.append("cliente_id = ?")
        values.append(data.cliente_id)
    if data.direccion_entrega is not None:
        updates.append("direccion_entrega = ?")
        values.append(data.direccion_entrega)
    if data.garantia_hasta is not None:
        updates.append("garantia_hasta = ?")
        values.append(data.garantia_hasta)
    if data.estatus_entrega is not None:
        updates.append("estatus_entrega = ?")
        values.append(data.estatus_entrega)

    if not updates:
        raise HTTPException(status_code=400, detail="No hay campos para actualizar")

    updates.append("updated_at = ?")
    values.append(_now_iso())
    values.append(factura_id)

    sql = f"UPDATE facturas SET {', '.join(updates)} WHERE id = ?"
    cursor = await db.execute(sql, values)
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Factura no encontrada")
    await db.commit()
    return {"status": "updated", "factura_id": factura_id}


@router.patch("/facturas/{factura_id}/perdida")
async def declarar_factura_perdida(
    factura_id: str,
    current_user: dict = Depends(require_permission("facturas_declarar_perdida")),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Marca una factura como pérdida (el cliente desapareció)."""
    sql = "UPDATE facturas SET declarado_perdida = 1, updated_at = ? WHERE id = ?"
    cursor = await db.execute(sql, (_now_iso(), factura_id))
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Factura no encontrada")
    await db.commit()
    return {"status": "updated", "factura_id": factura_id, "declarado_perdida": 1}


@router.patch("/facturas/{factura_id}/perdonar")
async def declarar_factura_perdonada(
    factura_id: str,
    current_user: dict = Depends(require_permission("facturas_perdonar_deuda")),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Perdona el saldo restante de una factura."""
    sql = "UPDATE facturas SET declarado_perdonado = 1, updated_at = ? WHERE id = ?"
    cursor = await db.execute(sql, (_now_iso(), factura_id))
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Factura no encontrada")
    await db.commit()
    return {"status": "updated", "factura_id": factura_id, "declarado_perdonado": 1}


@router.delete("/facturas/{factura_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_factura_endpoint(
    factura_id: str,
    current_user: dict = Depends(require_permission("facturas_modificar")),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Hard delete de factura con restauración de stock."""
    await delete_factura(db, factura_id)


@router.post("/facturas/{factura_id}/dispatch")
async def dispatch_factura_endpoint(
    factura_id: str,
    current_user: dict = Depends(require_permission("fabricacion_mandar_envio")),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Despacho masivo: completa todos los ítems y gestiona envío."""
    return await dispatch_factura(db, factura_id)


# ===========================================================================
# ITEMS
# ===========================================================================

@router.get("/items")
async def list_items(
    status: Optional[str] = None,
    area: Optional[str] = None,
    tipo: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    current_user: dict = Depends(require_permission("fabricacion_ver_estados")),
    db: aiosqlite.Connection = Depends(get_db),
):
    """
    Lista los ítems para Kanban de producción.

    Incluye resolución inteligente de imagen:
    - Si el ítem tiene su propia image_id, devuelve la ruta de esa imagen.
    - Si el ítem NO tiene imagen propia, devuelve la imagen genérica del catálogo
      al que pertenece (segun venus_workflow.md).
    """
    clause, clause_params = get_allowed_prefixes_clause(current_user, "i.id")

    query = f"""
        SELECT
            i.*,
            COALESCE(item_img.file_path, cat_img.file_path) AS resolved_file_path,
            COALESCE(item_img.aspect_ratio, cat_img.aspect_ratio) AS resolved_aspect_ratio,
            CASE
                WHEN item_img.file_path IS NOT NULL THEN i.image_id
                ELSE c.image_id
            END AS resolved_image_id,
            c.image_id AS catalogo_image_id,
            COALESCE(cl.nombre, json_extract(f.cliente, '$.nombre')) AS cliente_nombre,
            COALESCE(cl.apellido, json_extract(f.cliente, '$.apellido')) AS cliente_apellido
        FROM items i
        LEFT JOIN catalogo c ON i.catalogo_id = c.id
        LEFT JOIN facturas f ON i.factura_id = f.id
        LEFT JOIN clientes cl ON f.cliente_id = cl.id
        LEFT JOIN images item_img ON i.image_id = item_img.id
        LEFT JOIN images cat_img ON c.image_id = cat_img.id
        WHERE {clause}
    """
    params = clause_params.copy()

    if status:
        query += " AND i.status = ?"
        params.append(status)

    if area:
        query += " AND i.area = ?"
        params.append(area)

    if tipo:
        query += " AND i.tipo = ?"
        params.append(tipo)

    query += " ORDER BY i.created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    cursor = await db.execute(query, params)
    cols = [d[0] for d in cursor.description]
    rows = await cursor.fetchall()

    base_url = settings.BASE_URL if hasattr(settings, "BASE_URL") else ""
    result = []
    for row in rows:
        d = dict(zip(cols, row))
        file_path = d.get("resolved_file_path")
        if file_path:
            if file_path.startswith("http://") or file_path.startswith("https://"):
                d["image_url"] = file_path
            else:
                clean = file_path if file_path.startswith("/") else f"/{file_path}"
                d["image_url"] = f"{base_url}{clean}"
        else:
            d["image_url"] = None
        result.append(d)

    return result


@router.post("/facturas/{factura_id}/items", status_code=status.HTTP_201_CREATED)
async def add_item_to_factura(
    factura_id: str,
    data: ItemAddIn,
    current_user: dict = Depends(require_permission("facturas_emitir")),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Agrega un nuevo ítem a una factura existente."""
    prefix = current_user.get("prefix", "")
    transformer = PrefixTransformer(prefix)

    # Verificar factura
    cursor = await db.execute("SELECT id FROM facturas WHERE id = ?", (factura_id,))
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Factura no encontrada")

    now = _now_iso()
    item_id = _gen_id(prefix)

    await db.execute(
        """
        INSERT INTO items (
            id, factura_id, stock_id, catalogo_id, image_id,
            nombre, cantidad, tipo, subtotal, tela, material,
            descripcion, area, tipo_mueble, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pendiente', ?, ?)
        """,
        (
            item_id, factura_id,
            data.stock_id,
            data.catalogo_id,
            data.image_id,
            data.nombre or "Producto", data.cantidad, data.tipo, data.subtotal,
            data.tela, data.material, data.descripcion,
            data.area, data.tipo_mueble, now, now,
        ),
    )
    await db.commit()
    return {"item_id": item_id, "factura_id": factura_id}


@router.patch("/items/{item_id}")
async def patch_item(
    item_id: str,
    data: ItemUpdateIn,
    current_user: dict = Depends(require_permission("fabricacion_modificar_estados")),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Modifica características de un ítem."""
    updates = []
    values = []

    for field in ["tela", "material", "descripcion", "subtotal"]:
        val = getattr(data, field)
        if val is not None:
            updates.append(f"{field} = ?")
            values.append(val)

    if not updates:
        raise HTTPException(status_code=400, detail="No hay campos para actualizar")

    updates.append("updated_at = ?")
    values.append(_now_iso())
    values.append(item_id)

    cursor = await db.execute(
        f"UPDATE items SET {', '.join(updates)} WHERE id = ?", values
    )
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Ítem no encontrado")
    await db.commit()
    return {"status": "updated", "item_id": item_id}


@router.patch("/items/{item_id}/status")
async def patch_item_status(
    item_id: str,
    data: ItemStatusUpdate,
    current_user: dict = Depends(require_permission("fabricacion_modificar_estados")),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Actualiza el estado de producción con máquina de estados y bypass."""
    return await update_item_status(db, item_id, data.status)


@router.patch("/items/{item_id}/photo")
async def patch_item_photo(
    item_id: str,
    data: ItemPhotoUpdate,
    current_user: dict = Depends(require_permission("fabricacion_modificar_estados")),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Actualiza solo el image_id (foto) de un ítem."""
    cursor = await db.execute(
        "UPDATE items SET image_id = ?, updated_at = ? WHERE id = ?",
        (data.image_id, _now_iso(), item_id),
    )
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Ítem no encontrado")
    await db.commit()
    return {"status": "updated", "item_id": item_id}


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    item_id: str,
    current_user: dict = Depends(require_permission("fabricacion_modificar_estados")),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Elimina un ítem. Si era tipo stock, restaura la cantidad."""
    cursor = await db.execute(
        "SELECT stock_id, cantidad, tipo FROM items WHERE id = ?", (item_id,)
    )
    item = await cursor.fetchone()
    if not item:
        raise HTTPException(status_code=404, detail="Ítem no encontrado")

    # Restaurar stock si aplica
    if item[2] == "stock" and item[0]:
        await db.execute(
            "UPDATE stock SET cantidad = cantidad + ?, updated_at = ? WHERE id = ?",
            (item[1], _now_iso(), item[0]),
        )

    await db.execute("DELETE FROM items WHERE id = ?", (item_id,))
    await db.commit()


# ===========================================================================
# PAGOS
# ===========================================================================

@router.post("/facturas/{factura_id}/pagos", status_code=status.HTTP_201_CREATED)
async def create_pago(
    factura_id: str,
    data: PagoCreateIn,
    current_user: dict = Depends(require_permission("facturas_emitir")),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Registra un abono a una factura."""
    cursor = await db.execute(
        "SELECT saldo_pendiente FROM facturas WHERE id = ?", (factura_id,)
    )
    factura = await cursor.fetchone()
    if not factura:
        raise HTTPException(status_code=404, detail="Factura no encontrada")

    if factura[0] < data.monto:
        raise HTTPException(
            status_code=400,
            detail=f"Monto ({data.monto}) excede el saldo pendiente ({factura[0]})",
        )

    now = _now_iso()
    prefix = current_user.get("prefix", "")
    pago_id = _gen_id(prefix)

    await db.execute(
        "INSERT INTO pagos (id, factura_id, monto, fecha, nota, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (pago_id, factura_id, data.monto, now, data.nota, now),
    )
    await db.execute(
        """
        UPDATE facturas SET
            monto_pagado = monto_pagado + ?,
            saldo_pendiente = saldo_pendiente - ?,
            updated_at = ?
        WHERE id = ?
        """,
        (data.monto, data.monto, now, factura_id),
    )
    await db.commit()
    return {"pago_id": pago_id, "monto": data.monto, "saldo_restante": factura[0] - data.monto}


@router.get("/facturas/{factura_id}/pagos")
async def list_pagos(
    factura_id: str,
    current_user: dict = Depends(require_permission("facturas_ver")),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Lista todos los pagos de una factura."""
    cursor = await db.execute(
        "SELECT * FROM pagos WHERE factura_id = ? ORDER BY fecha DESC",
        (factura_id,),
    )
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in await cursor.fetchall()]


# ===========================================================================
# ENVÍOS
# ===========================================================================

@router.get("/envios")
async def list_envios(
    estado: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    current_user: dict = Depends(require_permission("fabricacion_ver_estados")),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Lista los envíos (entregas a domicilio)."""
    clause, clause_params = get_allowed_prefixes_clause(current_user, "e.id")
    
    query = f"""
        SELECT e.*,
               COALESCE(cl.nombre, json_extract(f.cliente, '$.nombre')) AS cliente_nombre,
               COALESCE(cl.apellido, json_extract(f.cliente, '$.apellido')) AS cliente_apellido
        FROM envios e
        LEFT JOIN facturas f ON e.factura_id = f.id
        LEFT JOIN clientes cl ON f.cliente_id = cl.id
        WHERE {clause}
    """
    params = clause_params.copy()
    
    if estado:
        query += " AND estado = ?"
        params.append(estado)
        
    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    
    cursor = await db.execute(query, params)
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in await cursor.fetchall()]


@router.patch("/envios/{envio_id}/status")
async def patch_envio_status(
    envio_id: str,
    data: EnvioStatusUpdate,
    current_user: dict = Depends(require_permission("fabricacion_mandar_envio")),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Actualiza estado de envío. Al entregar, activa garantía."""
    return await update_envio_status(db, envio_id, data.estado)


@router.patch("/envios/{envio_id}")
async def patch_envio(
    envio_id: str,
    data: EnvioUpdateIn,
    current_user: dict = Depends(require_permission("fabricacion_mandar_envio")),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Modifica detalles logísticos de un envío."""
    updates = []
    values = []

    if data.direccion_entrega is not None:
        updates.append("direccion_entrega = ?")
        values.append(data.direccion_entrega)
    if data.fecha_programada is not None:
        updates.append("fecha_programada = ?")
        values.append(data.fecha_programada.isoformat())
    if data.notas is not None:
        updates.append("notas = ?")
        values.append(data.notas)

    if not updates:
        raise HTTPException(status_code=400, detail="No hay campos para actualizar")

    updates.append("updated_at = ?")
    values.append(_now_iso())
    values.append(envio_id)

    cursor = await db.execute(
        f"UPDATE envios SET {', '.join(updates)} WHERE id = ?", values
    )
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Envío no encontrado")
    await db.commit()
    return {"status": "updated", "envio_id": envio_id}


# ===========================================================================
# CLIENTES
# ===========================================================================

@router.get("/clientes")
async def list_clientes(
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    current_user: dict = Depends(require_permission("clientes_crear")),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Obtiene el listado de clientes."""
    clause, clause_params = get_allowed_prefixes_clause(current_user, "c.id")
    
    query = f"SELECT c.* FROM clientes c WHERE {clause} AND c.deleted_at IS NULL"
    params = clause_params.copy()
    
    if search:
        query += " AND (nombre LIKE ? OR apellido LIKE ? OR telefono LIKE ?)"
        search_term = f"%{search}%"
        params.extend([search_term, search_term, search_term])
        
    query += " ORDER BY nombre ASC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    
    cursor = await db.execute(query, params)
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in await cursor.fetchall()]


@router.post("/clientes", status_code=status.HTTP_201_CREATED)
async def create_cliente(
    data: ClienteCreateIn,
    current_user: dict = Depends(require_permission("clientes_crear")),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Crea un cliente nuevo y retorna el id del cliente creado con la confirmación de sus datos."""
    prefix = current_user.get("prefix", "")
    cliente_id = _gen_id(prefix)
    now = _now_iso()

    await db.execute(
        """
        INSERT INTO clientes (id, nombre, apellido, telefono, email, domicilio, prioridad, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (cliente_id, data.nombre, data.apellido, data.telefono,
         data.email, data.domicilio, int(data.prioridad), now),
    )
    await db.commit()
    return {
        "id": cliente_id,
        "nombre": data.nombre,
        "apellido": data.apellido,
        "telefono": data.telefono,
        "email": data.email,
        "domicilio": data.domicilio,
        "prioridad": data.prioridad,
    }


@router.patch("/clientes/{cliente_id}")
async def patch_cliente(
    cliente_id: str,
    data: ClienteUpdateIn,
    current_user: dict = Depends(require_permission("clientes_modificar")),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Modifica parámetros del cliente."""
    updates = []
    values = []

    for field in ["nombre", "apellido", "telefono", "email", "domicilio"]:
        val = getattr(data, field)
        if val is not None:
            updates.append(f"{field} = ?")
            values.append(val)

    if data.prioridad is not None:
        updates.append("prioridad = ?")
        values.append(int(data.prioridad))

    if not updates:
        raise HTTPException(status_code=400, detail="No hay campos para actualizar")

    updates.append("updated_at = ?")
    values.append(_now_iso())
    values.append(cliente_id)

    cursor = await db.execute(
        f"UPDATE clientes SET {', '.join(updates)} WHERE id = ?", values
    )
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    await db.commit()
    return {"status": "updated", "cliente_id": cliente_id}


@router.delete("/clientes/{cliente_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cliente(
    cliente_id: str,
    current_user: dict = Depends(require_permission("clientes_eliminar")),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Soft delete: marca deleted_at."""
    cursor = await db.execute(
        "UPDATE clientes SET deleted_at = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL",
        (_now_iso(), _now_iso(), cliente_id),
    )
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    await db.commit()


# ===========================================================================
# CATÁLOGO
# ===========================================================================

@router.get("/catalogo")
async def list_catalogo(
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    current_user: dict = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Obtiene plantillas de catálogo con información de imagen."""
    clause, clause_params = get_allowed_prefixes_clause(current_user, "c.id")

    query = f"""
        SELECT c.*, img.file_path, img.aspect_ratio 
        FROM catalogo c 
        LEFT JOIN images img ON c.image_id = img.id
        WHERE {clause} AND c.deleted_at IS NULL
    """
    params = clause_params.copy()
    
    if search:
        query += " AND c.nombre LIKE ?"
        params.append(f"%{search}%")
        
    query += " ORDER BY c.nombre ASC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    
    cursor = await db.execute(query, params)
    cols = [d[0] for d in cursor.description]
    rows = await cursor.fetchall()
    result = []
    for row in rows:
        d = dict(zip(cols, row))
        
        area_val = d.get("area")
        if area_val:
            import json
            try:
                parsed = json.loads(area_val)
                d["area"] = parsed if isinstance(parsed, list) else [str(parsed)]
            except Exception:
                d["area"] = [str(area_val)]
        else:
            d["area"] = []

        file_path = d.get("file_path")
        if file_path:
            if file_path.startswith("http://") or file_path.startswith("https://") or file_path.startswith("data:"):
                d["image_src"] = file_path
                d["url_imagen"] = d.get("url_imagen") or file_path
            else:
                d["image_src"] = file_path if file_path.startswith("/") else f"/{file_path}"
                d["url_imagen"] = d.get("url_imagen") or d["image_src"]
        result.append(d)
    return result


@router.post("/catalogo", status_code=status.HTTP_201_CREATED)
async def create_catalogo(
    nombre: str = Form(...),
    tipo: Optional[str] = Form(None),
    area: Optional[str] = Form(None),
    precio_base: Optional[float] = Form(None),
    file: UploadFile = File(...),
    current_user: dict = Depends(require_permission("catalogo_crear")),
    db: aiosqlite.Connection = Depends(get_db),
):
    """
    Crea una plantilla genérica de catálogo recibiendo la foto obligatoria mediante multipart/form-data.

    Guarda la imagen física en /uploads/{prefix}/, registra la imagen en la tabla `images`,
    y vincula el `image_id` generado a la nueva plantilla de catálogo.
    """
    prefix = current_user.get("prefix") or "admin"
    now = _now_iso()

    content = await file.read()
    img_data = await get_or_create_image(db, content, file.filename, prefix)
    image_id = img_data["id"]
    remote_path = img_data["file_path"]

    # 2. Insertar registro en tabla `catalogo`
    catalogo_id = _gen_id(prefix)
    final_area = _normalize_area_to_json(area)
    
    await db.execute(
        """
        INSERT INTO catalogo (id, nombre, tipo, area, precio_base, image_id, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (catalogo_id, nombre, tipo, final_area, precio_base, image_id, now),
    )
    await db.commit()

    return {
        "id": catalogo_id,
        "nombre": nombre,
        "tipo": tipo,
        "area": final_area,
        "precio_base": precio_base,
        "image_id": image_id,
        "file_path": remote_path,
    }


@router.put("/catalogo/{catalogo_id}")
@router.patch("/catalogo/{catalogo_id}")
async def update_catalogo(
    catalogo_id: str,
    nombre: Optional[str] = Form(None),
    tipo: Optional[str] = Form(None),
    area: Optional[str] = Form(None),
    precio_base: Optional[float] = Form(None),
    file: Optional[UploadFile] = File(None),
    current_user: dict = Depends(require_permission("catalogo_modificar")),
    db: aiosqlite.Connection = Depends(get_db),
):
    """
    Actualización versionada de catálogo (Soft-delete de la versión anterior + creación de copia modificada).
    Preserva la integridad referencial de facturas e ítems antiguos y genera un nuevo ID para la versión activa.
    """
    prefix = current_user.get("prefix") or "admin"
    now = _now_iso()

    # 1. Buscar la versión actual activa del catálogo
    cands = _id_candidates(catalogo_id)
    placeholders = ",".join(["?"] * len(cands))
    cursor = await db.execute(
        f"SELECT id, nombre, tipo, area, precio_base, image_id FROM catalogo WHERE id IN ({placeholders}) AND deleted_at IS NULL",
        cands,
    )
    old_row = await cursor.fetchone()
    if not old_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Modelo de catálogo '{catalogo_id}' no encontrado o ya eliminado",
        )
    old_id, old_nombre, old_tipo, old_area, old_precio_base, old_image_id = old_row

    # 2. Soft-delete de la versión anterior para preservar facturas históricas
    await db.execute(
        "UPDATE catalogo SET deleted_at = ? WHERE id = ?",
        (now, old_id),
    )

    # 3. Procesar nueva foto si fue enviada
    final_image_id = old_image_id
    remote_path = None
    if file is not None and file.filename:
        content = await file.read()
        img_data = await get_or_create_image(db, content, file.filename, prefix)
        final_image_id = img_data["id"]
        remote_path = img_data["file_path"]

    # 4. Crear nueva copia modificada con ID nuevo
    new_catalogo_id = _gen_id(prefix)
    final_nombre = nombre if nombre is not None and nombre != "" else old_nombre
    final_tipo = tipo if tipo is not None and tipo != "" else old_tipo
    final_precio = precio_base if precio_base is not None else old_precio_base
    
    if area is not None and area != "":
        final_area = _normalize_area_to_json(area)
    else:
        final_area = old_area

    await db.execute(
        """
        INSERT INTO catalogo (id, nombre, tipo, area, precio_base, image_id, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (new_catalogo_id, final_nombre, final_tipo, final_area, final_precio, final_image_id, now),
    )
    await db.commit()

    return {
        "id": new_catalogo_id,
        "old_id": old_id,
        "nombre": final_nombre,
        "tipo": final_tipo,
        "area": final_area,
        "precio_base": final_precio,
        "image_id": final_image_id,
        "file_path": remote_path,
        "status": "updated",
        "catalogo_id": new_catalogo_id
    }


@router.delete("/catalogo/{catalogo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_catalogo(
    catalogo_id: str,
    current_user: dict = Depends(require_permission("catalogo_eliminar")),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Soft delete de catálogo. 409 si hay stock o ítems activos referenciándolo."""
    # Verificar referencias activas
    cursor = await db.execute(
        "SELECT COUNT(*) FROM stock WHERE catalogo_id = ? AND deleted_at IS NULL",
        (catalogo_id,),
    )
    count = await cursor.fetchone()
    if count and count[0] > 0:
        raise HTTPException(
            status_code=409,
            detail="No se puede eliminar: hay stock activo referenciando este catálogo",
        )

    cursor = await db.execute(
        "UPDATE catalogo SET deleted_at = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL",
        (_now_iso(), _now_iso(), catalogo_id),
    )
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Catálogo no encontrado")
    await db.commit()


# ===========================================================================
# STOCK
# ===========================================================================

@router.get("/stock")
async def list_stock(
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    current_user: dict = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Obtiene inventario actual con información de la imagen de catálogo/stock."""
    clause, clause_params = get_allowed_prefixes_clause(current_user, "s.id")

    query = f"""
        SELECT s.*, c.nombre as catalogo_nombre, c.tipo, c.area,
               COALESCE(s.image_id, c.image_id) AS image_id,
               img.file_path, img.aspect_ratio
        FROM stock s 
        LEFT JOIN catalogo c ON s.catalogo_id = c.id
        LEFT JOIN images img ON COALESCE(s.image_id, c.image_id) = img.id
        WHERE {clause} AND s.deleted_at IS NULL AND s.cantidad > 0
    """
    params = clause_params.copy()
    
    if search:
        query += " AND (c.nombre LIKE ? OR s.tela LIKE ? OR s.material LIKE ?)"
        search_term = f"%{search}%"
        params.extend([search_term, search_term, search_term])
        
    query += " ORDER BY s.updated_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    
    cursor = await db.execute(query, params)
    cols = [d[0] for d in cursor.description]
    rows = await cursor.fetchall()
    result = []
    for row in rows:
        d = dict(zip(cols, row))
        
        area_val = d.get("area")
        if area_val:
            import json
            try:
                parsed = json.loads(area_val)
                d["area"] = parsed if isinstance(parsed, list) else [str(parsed)]
            except Exception:
                d["area"] = [str(area_val)]
        else:
            d["area"] = []

        file_path = d.get("file_path")
        if file_path:
            if file_path.startswith("http://") or file_path.startswith("https://") or file_path.startswith("data:"):
                d["image_src"] = file_path
                d["url_imagen"] = d.get("url_imagen") or file_path
            else:
                d["image_src"] = file_path if file_path.startswith("/") else f"/{file_path}"
                d["url_imagen"] = d.get("url_imagen") or d["image_src"]
        d["color"] = d.get("tela")
        result.append(d)
    return result


@router.post("/stock", status_code=status.HTTP_201_CREATED)
async def create_stock(
    catalogo_id: str = Form(...),
    tela: Optional[str] = Form(None),
    color: Optional[str] = Form(None),
    material: Optional[str] = Form(None),
    descripcion: Optional[str] = Form(None),
    cantidad: int = Form(0),
    precio: Optional[float] = Form(None),
    file: Optional[UploadFile] = File(None),
    current_user: dict = Depends(require_permission("stock_crear")),
    db: aiosqlite.Connection = Depends(get_db),
):
    """
    Crea una variante de stock vinculada a un catálogo mediante multipart/form-data.

    Hereda la foto genérica del catálogo si no se sube una imagen propia.
    Si se adjunta una imagen física, la guarda en /uploads/{prefix}/, registra en `images` y asigna su ID.
    """
    prefix = current_user.get("prefix") or "admin"
    now = _now_iso()
    final_tela = tela or color

    # 1. Validar que el catálogo existe y recuperar su image_id por defecto
    from services.factura_service import _id_candidates
    cands = _id_candidates(catalogo_id)
    placeholders = ",".join(["?"] * len(cands))
    cursor = await db.execute(
        f"SELECT id, image_id FROM catalogo WHERE id IN ({placeholders}) AND deleted_at IS NULL",
        cands,
    )
    cat = await cursor.fetchone()
    if not cat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Catálogo '{catalogo_id}' no encontrado",
        )
    catalogo_id = cat["id"]
    catalogo_image_id = cat["image_id"]
    final_image_id = catalogo_image_id

    # 2. Procesar imagen opcional si se envió un archivo
    if file and file.filename:
        content = await file.read()
        img_data = await get_or_create_image(db, content, file.filename, prefix)
        final_image_id = img_data["id"]

    # 3. Insertar variante de stock
    stock_id = _gen_id(prefix)
    await db.execute(
        """
        INSERT INTO stock (id, catalogo_id, tela, material, descripcion, cantidad, precio, image_id, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (stock_id, catalogo_id, final_tela, material, descripcion, cantidad, precio, final_image_id, now),
    )
    await db.commit()

    return {
        "id": stock_id,
        "catalogo_id": catalogo_id,
        "tela": final_tela,
        "color": final_tela,
        "material": material,
        "descripcion": descripcion,
        "cantidad": cantidad,
        "precio": precio,
        "image_id": final_image_id,
    }


@router.patch("/stock/{stock_id}")
async def patch_stock(
    stock_id: str,
    data: StockUpdateIn,
    current_user: dict = Depends(require_permission("stock_modificar")),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Modifica una variante de stock."""
    prefix = current_user.get("prefix", "")
    transformer = PrefixTransformer(prefix)
    updates = []
    values = []

    for field in ["tela", "material", "descripcion", "precio"]:
        val = getattr(data, field)
        if val is not None:
            updates.append(f"{field} = ?")
            values.append(val)

    if data.image_id is not None:
        updates.append("image_id = ?")
        values.append(transformer.to_remote(data.image_id))

    if not updates:
        raise HTTPException(status_code=400, detail="No hay campos para actualizar")

    updates.append("updated_at = ?")
    values.append(_now_iso())
    values.append(stock_id)

    cursor = await db.execute(
        f"UPDATE stock SET {', '.join(updates)} WHERE id = ?", values
    )
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Stock no encontrado")
    await db.commit()
    return {"status": "updated", "stock_id": stock_id}


@router.patch("/stock/{stock_id}/cantidad")
async def patch_stock_cantidad(
    stock_id: str,
    data: StockCantidadUpdate,
    current_user: dict = Depends(require_permission("stock_modificar")),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Ajusta la cantidad de stock con un delta (+/-). Mínimo 0."""
    cursor = await db.execute(
        "SELECT cantidad FROM stock WHERE id = ? AND deleted_at IS NULL",
        (stock_id,),
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Stock no encontrado")

    new_qty = max(0, row[0] + data.delta)
    if new_qty <= 0:
        await db.execute(
            "UPDATE stock SET cantidad = 0, deleted_at = ?, updated_at = ? WHERE id = ?",
            (_now_iso(), _now_iso(), stock_id),
        )
    else:
        await db.execute(
            "UPDATE stock SET cantidad = ?, updated_at = ? WHERE id = ?",
            (new_qty, _now_iso(), stock_id),
        )
    await db.commit()
    return {"stock_id": stock_id, "cantidad": new_qty}


@router.delete("/stock/{stock_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_stock(
    stock_id: str,
    current_user: dict = Depends(require_permission("stock_eliminar")),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Soft delete de stock."""
    cursor = await db.execute(
        "UPDATE stock SET deleted_at = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL",
        (_now_iso(), _now_iso(), stock_id),
    )
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Stock no encontrado")
    await db.commit()


# ===========================================================================
# CONFIGURACIÓN
# ===========================================================================

@router.get("/config")
async def get_config(
    current_user: dict = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Retorna toda la configuración de la empresa (materiales, colores, datos)."""
    cursor = await db.execute("SELECT clave, valor FROM configuracion")
    rows = await cursor.fetchall()
    config = {}
    for clave, valor in rows:
        try:
            config[clave] = json.loads(valor)
        except (json.JSONDecodeError, TypeError):
            config[clave] = valor

    # Cargar catálogos dinámicos desde la tabla materiales de la base de datos
    cursor_mat = await db.execute("SELECT id, categoria, elementos, color FROM materiales")
    mat_rows = await cursor_mat.fetchall()

    mat_list = []
    telas_list = []
    colores_list = set()
    tipos_list = []
    areas_list = []
    materiales_tabla = []

    for row_id, cat, elem_str, color_str in mat_rows:
        try:
            elems = json.loads(elem_str) if elem_str else []
        except Exception:
            elems = []

        try:
            colors = json.loads(color_str) if color_str else (color_str if color_str else None)
        except Exception:
            colors = color_str

        cat_lower = cat.lower().strip()
        if cat_lower == "materiales":
            mat_list.extend(elems)
        elif cat_lower == "telas":
            telas_list.extend(elems)
        elif cat_lower in ("tipo_mueble", "tipos"):
            tipos_list.extend(elems)
        elif cat_lower == "areas":
            areas_list.extend(elems)

        if isinstance(colors, list):
            for c in colors:
                if c and str(c).lower() != "none":
                    colores_list.add(c)
        elif isinstance(colors, str) and colors.lower() != "none":
            colores_list.add(colors)

        materiales_tabla.append({
            "id": row_id,
            "categoria": cat,
            "elementos": elems,
            "color": colors
        })

    if mat_list:
        config["materiales"] = mat_list
    if telas_list:
        config["telas"] = telas_list
    if tipos_list:
        config["tipos"] = tipos_list
    if areas_list:
        config["areas"] = areas_list
    if colores_list:
        config["colores"] = sorted(list(colores_list))

    all_mat_telas = list(dict.fromkeys(telas_list + mat_list))
    if all_mat_telas:
        config["materiales_telas"] = all_mat_telas

    config["materiales_tabla"] = materiales_tabla
    return config


@router.put("/config")
async def put_config(
    data: ConfigUpdateIn,
    current_user: dict = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Reemplaza toda la configuración del usuario."""
    prefix = current_user.get("prefix") or "admin"
    now = _now_iso()

    # Borrar config existente
    await db.execute("DELETE FROM configuracion WHERE id LIKE ?", (f"{prefix}%",))

    # Insertar nuevas entradas
    config_data = data.model_dump(exclude_none=True)
    for i, (clave, valor) in enumerate(config_data.items()):
        config_id = f"{prefix}cfg{i}"
        valor_json = json.dumps(valor, ensure_ascii=False) if isinstance(valor, (list, dict)) else str(valor)
        await db.execute(
            "INSERT INTO configuracion (id, clave, valor, updated_at) VALUES (?, ?, ?, ?)",
            (config_id, clave, valor_json, now),
        )

    await db.commit()
    return {"status": "updated"}


def _format_ubicacion(d: dict) -> dict:
    if "ubicacion" in d and isinstance(d["ubicacion"], str):
        try:
            d["ubicacion"] = json.loads(d["ubicacion"])
        except Exception:
            pass
    return d


# ===========================================================================
# MATERIALES / CATÁLOGOS AUXILIARES
# ===========================================================================
from typing import List
from services.factura_service import _id_candidates

@router.get("/materiales", response_model=List[MaterialOut])
async def list_materiales(
    categoria: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    """
    Obtiene los registros de la tabla de materiales (Materiales, Telas, tipo_mueble, areas).
    Permite filtrar opcionalmente por categoría.
    """
    if categoria:
        cursor = await db.execute(
            "SELECT id, categoria, elementos, color, updated_at FROM materiales WHERE categoria = ?",
            (categoria,)
        )
    else:
        cursor = await db.execute(
            "SELECT id, categoria, elementos, color, updated_at FROM materiales ORDER BY id ASC"
        )
    rows = await cursor.fetchall()
    result = []
    for row_id, cat, elem_str, color_str, updated_at in rows:
        try:
            elem = json.loads(elem_str) if elem_str else []
        except Exception:
            elem = []

        try:
            color = json.loads(color_str) if color_str else color_str
        except Exception:
            color = color_str

        result.append(
            MaterialOut(
                id=row_id,
                categoria=cat,
                elementos=elem,
                color=color,
                updated_at=updated_at,
            )
        )
    return result


@router.post("/materiales", response_model=MaterialOut, status_code=status.HTTP_201_CREATED)
async def create_material(
    data: MaterialCreateIn,
    current_user: dict = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    """
    Crea un nuevo registro/categoría en la tabla de materiales.
    """
    prefix = current_user.get("prefix") or "M"
    mat_id = _gen_id(prefix)
    now = _now_iso()

    elem_json = json.dumps(data.elementos or [], ensure_ascii=False)
    color_json = json.dumps(data.color, ensure_ascii=False) if isinstance(data.color, (list, dict)) else data.color

    await db.execute(
        """
        INSERT INTO materiales (id, categoria, elementos, color, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (mat_id, data.categoria, elem_json, color_json, now),
    )
    await db.commit()

    return MaterialOut(
        id=mat_id,
        categoria=data.categoria,
        elementos=data.elementos or [],
        color=data.color,
        updated_at=now,
    )


@router.patch("/materiales/{material_id}", response_model=MaterialOut)
async def update_material(
    material_id: str,
    data: MaterialUpdateIn,
    current_user: dict = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    """
    Actualiza parcialmente un registro de materiales (elementos, color o categoría).
    """
    cands = _id_candidates(material_id)
    placeholders = ",".join(["?"] * len(cands))
    cursor = await db.execute(
        f"SELECT id, categoria, elementos, color FROM materiales WHERE id IN ({placeholders})",
        cands,
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Registro de materiales '{material_id}' no encontrado",
        )

    real_id, cur_cat, cur_elem_str, cur_color_str = row
    try:
        cur_elem = json.loads(cur_elem_str) if cur_elem_str else []
    except Exception:
        cur_elem = []

    try:
        cur_color = json.loads(cur_color_str) if cur_color_str else cur_color_str
    except Exception:
        cur_color = cur_color_str

    new_cat = data.categoria if data.categoria is not None else cur_cat
    new_elem = data.elementos if data.elementos is not None else cur_elem
    new_color = data.color if data.color is not None else cur_color
    now = _now_iso()

    elem_json = json.dumps(new_elem, ensure_ascii=False)
    color_json = json.dumps(new_color, ensure_ascii=False) if isinstance(new_color, (list, dict)) else new_color

    await db.execute(
        """
        UPDATE materiales
        SET categoria = ?, elementos = ?, color = ?, updated_at = ?
        WHERE id = ?
        """,
        (new_cat, elem_json, color_json, now, real_id),
    )
    await db.commit()

    return MaterialOut(
        id=real_id,
        categoria=new_cat,
        elementos=new_elem,
        color=new_color,
        updated_at=now,
    )


@router.delete("/materiales/{material_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_material(
    material_id: str,
    current_user: dict = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
):
    """
    Elimina un registro de la tabla de materiales.
    """
    cands = _id_candidates(material_id)
    placeholders = ",".join(["?"] * len(cands))
    cursor = await db.execute(
        f"SELECT id FROM materiales WHERE id IN ({placeholders})",
        cands,
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Registro de materiales '{material_id}' no encontrado",
        )

    real_id = row[0]
    await db.execute("DELETE FROM materiales WHERE id = ?", (real_id,))
    await db.commit()
    return None
