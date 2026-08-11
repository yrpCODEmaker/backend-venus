"""
Venus Backend — Servicio de lógica de negocio para facturas.

Contiene la lógica transaccional compleja:
- create_factura: transacción ACID (7 pasos)
- delete_factura: hard delete + restauración de stock
- dispatch_factura: despacho masivo
- update_item_status: máquina de estados con bypass
- update_envio_status: activación de garantía
- compute_warranty: cálculo de vencimiento
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

import aiosqlite
from fastapi import HTTPException, status

from services.sync import PrefixTransformer


# ===========================================================================
# HELPERS
# ===========================================================================

def _now_iso() -> str:
    """Retorna el timestamp actual en ISO 8601."""
    return datetime.now(timezone.utc).isoformat()


def _gen_id(prefix: str) -> str:
    """Genera un ID único con prefijo separado por un guion (ej: y-ye897e4b)."""
    prefix_clean = (prefix or "admin").rstrip("-")
    short_uuid = uuid.uuid4().hex[:8]
    return f"{prefix_clean}-{short_uuid}"


def _id_candidates(id_val: Optional[str]) -> tuple[str, ...]:
    """
    Genera candidatos de búsqueda de ID tanto con guion como sin guion
    para máxima compatibilidad (ej: 'L1' y 'L-1', 'yye897e4b' y 'y-ye897e4b').
    """
    if not id_val:
        return ()
    if "-" in id_val:
        parts = id_val.split("-", 1)
        return (id_val, f"{parts[0]}{parts[1]}")
    import re
    match = re.match(r"^([A-Za-z]+)(.+)$", id_val)
    if match:
        return (id_val, f"{match.group(1)}-{match.group(2)}")
    return (id_val,)


# ===========================================================================
# WARRANTY
# ===========================================================================

_WARRANTY_MONTHS = {
    "1 Mes": 1,
    "3 Meses": 3,
    "6 Meses": 6,
    "1 Año": 12,
    "2 Años": 24,
}


def compute_warranty(garantia_hasta: str, fecha_entregado: str) -> Optional[str]:
    """
    Calcula la fecha de vencimiento de la garantía.

    Retorna ISO 8601 string o None si no aplica.
    """
    if not garantia_hasta or garantia_hasta == "Sin Garantía":
        return None

    months = _WARRANTY_MONTHS.get(garantia_hasta)
    if months is None:
        return None

    try:
        dt = datetime.fromisoformat(fecha_entregado)
    except (ValueError, TypeError):
        dt = datetime.now(timezone.utc)

    # Sumar meses manualmente
    new_month = dt.month + months
    new_year = dt.year + (new_month - 1) // 12
    new_month = ((new_month - 1) % 12) + 1
    try:
        venc = dt.replace(year=new_year, month=new_month)
    except ValueError:
        # Día inválido (ej: 31 de febrero) → último día del mes
        import calendar
        last_day = calendar.monthrange(new_year, new_month)[1]
        venc = dt.replace(year=new_year, month=new_month, day=last_day)

    return venc.isoformat()


# ===========================================================================
# CHECK COLA_TRABAJOS
# ===========================================================================

async def _check_and_remove_from_cola(db: aiosqlite.Connection, factura_id: str):
    """
    Verifica si la factura cumple las condiciones para salir de cola_trabajos
    y la elimina si corresponde.

    Condiciones para eliminar de la cola (segun workflow Venus):
    (A) Todos los items de la factura estan en estado 'procesado' o 'completado'.
    (B) Si la factura tiene entrega a domicilio, el envio debe estar en 'Entregado'.

    Si ambas condiciones se cumplen, se elimina la fila de cola_trabajos.
    """
    # Verificar que no haya items en estado pendiente o procesando
    cursor = await db.execute(
        """
        SELECT COUNT(*) FROM items
        WHERE factura_id = ? AND status IN ('pendiente', 'procesando')
        """,
        (factura_id,),
    )
    items_pending = (await cursor.fetchone())[0]

    if items_pending > 0:
        # Aun hay items sin terminar, no se puede remover de la cola
        return

    # Verificar si la factura tiene entrega a domicilio
    cursor = await db.execute(
        "SELECT entrega_domicilio FROM facturas WHERE id = ?",
        (factura_id,),
    )
    factura_row = await cursor.fetchone()
    if not factura_row:
        return

    tiene_envio = bool(factura_row[0])

    if tiene_envio:
        # Verificar que el envio este en estado 'Entregado'
        cursor = await db.execute(
            "SELECT estado FROM envios WHERE factura_id = ? ORDER BY created_at DESC LIMIT 1",
            (factura_id,),
        )
        envio_row = await cursor.fetchone()
        if not envio_row or envio_row[0] != "Entregado":
            # El envio aun no fue entregado, no se puede remover de la cola
            return

    # Ambas condiciones cumplidas: eliminar de cola_trabajos
    await db.execute(
        "DELETE FROM cola_trabajos WHERE factura_id = ?",
        (factura_id,),
    )


# ===========================================================================
# CREATE FACTURA (Transacción ACID - 7 pasos)
# ===========================================================================

async def create_factura(
    db: aiosqlite.Connection,
    data,  # FacturaCreateIn
    prefix: str,
) -> dict:
    """
    Crea una factura transaccional con todos sus componentes.

    Pasos:
    1. Validar cliente_id (si no es factura rápida)
    2. INSERT factura con saldo_pendiente calculado
    3. INSERT pago inicial (si monto_pagado > 0)
    4. Para cada ítem: validar stock → deducir → asignar status → INSERT
    5. UPDATE facturas.items_id con CSV de IDs generados
    6. INSERT en cola_trabajos (si aplica)
    7. Retornar factura completa
    """
    transformer = PrefixTransformer(prefix)
    now = _now_iso()
    factura_id = _gen_id(prefix)

    try:
        # --- Paso 1: Validar cliente ---
        cliente_id_remote = None
        if data.facturacion_rapida == 0 and data.cliente_id is not None:
            cands = _id_candidates(data.cliente_id)
            placeholders = ",".join(["?"] * len(cands))
            cursor = await db.execute(
                f"SELECT id FROM clientes WHERE id IN ({placeholders}) AND deleted_at IS NULL",
                cands,
            )
            row = await cursor.fetchone()
            if not row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Cliente con id {data.cliente_id} no encontrado",
                )
            cliente_id_remote = row[0]

        # --- Paso 2: INSERT factura ---
        pago_parcial_val = getattr(data, "pago_parcial", 0)
        if pago_parcial_val == 0:
            monto_pagado_effective = data.total
            saldo = 0.0
        else:
            monto_pagado_effective = float(data.monto_pagado)
            saldo = max(0.0, data.total - monto_pagado_effective)

        # Serializar cliente: si es factura rapida, asegurar estructura {nombre, apellido, telefono}
        cliente_json = None
        if data.cliente:
            cliente_dict = {
                "nombre": data.cliente.nombre,
                "apellido": data.cliente.apellido or "",
                "telefono": data.cliente.telefono or "",
            }
            cliente_json = json.dumps(cliente_dict, ensure_ascii=False)

        await db.execute(
            """
            INSERT INTO facturas (
                id, cliente_id, cliente, fecha, total, monto_pagado,
                saldo_pendiente, items_id, entrega_domicilio,
                direccion_entrega, estatus_entrega, garantia_hasta,
                status_garantia, facturacion_rapida, pago_parcial, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, 'No Aplica', ?, ?, ?)
            """,
            (
                factura_id, cliente_id_remote, cliente_json, now,
                data.total, monto_pagado_effective, saldo,
                int(data.entrega_domicilio), data.direccion_entrega,
                "No Aplica", data.garantia_hasta,
                data.facturacion_rapida, pago_parcial_val, now,
            ),
        )

        # --- Paso 3: Pago inicial ---
        pago_id = None
        if monto_pagado_effective > 0:
            pago_id = _gen_id(prefix)
            pago_nota = "Pago completo inicial" if pago_parcial_val == 0 else "Pago parcial inicial"
            await db.execute(
                """
                INSERT INTO pagos (id, factura_id, monto, fecha, nota, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (pago_id, factura_id, monto_pagado_effective, now, pago_nota, now),
            )

        # --- Paso 4: Items ---
        item_ids = []
        created_items = []
        has_non_completed = False

        for item_data in data.items:
            item_id = _gen_id(prefix)
            item_ids.append(item_id)

            fields_set = getattr(item_data, "model_fields_set", set())

            stock_id_remote = item_data.stock_id
            catalogo_id_remote = item_data.catalogo_id
            image_id_remote = item_data.image_id
            item_color = getattr(item_data, "tela", None) if "tela" in fields_set else getattr(item_data, "color", None)
            item_material = item_data.material
            item_descripcion = item_data.descripcion
            item_nombre = item_data.nombre
            item_area = item_data.area
            item_tipo_mueble = item_data.tipo_mueble

            # 1. Si viene de stock, consultar stock para heredar datos y deducir cantidad
            if item_data.tipo == "stock":
                if stock_id_remote:
                    cands = _id_candidates(stock_id_remote)
                    placeholders = ",".join(["?"] * len(cands))
                    cursor = await db.execute(
                        f"SELECT id, catalogo_id, tela, material, descripcion, cantidad, image_id FROM stock WHERE id IN ({placeholders}) AND deleted_at IS NULL",
                        cands,
                    )
                    stock_row = await cursor.fetchone()
                    if not stock_row:
                        raise HTTPException(
                            status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Stock con id {stock_id_remote} no encontrado",
                        )
                    stock_id_remote = stock_row["id"]

                    if stock_row["cantidad"] < item_data.cantidad:
                        display_name = item_nombre or f"Stock {stock_id_remote}"
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail=f"Stock insuficiente para '{display_name}'",
                        )

                    # Deducir cantidad en stock
                    new_stock_qty = stock_row["cantidad"] - item_data.cantidad
                    if new_stock_qty <= 0:
                        await db.execute(
                            "UPDATE stock SET cantidad = 0, deleted_at = ?, updated_at = ? WHERE id = ?",
                            (now, now, stock_id_remote),
                        )
                    else:
                        await db.execute(
                            "UPDATE stock SET cantidad = ?, updated_at = ? WHERE id = ?",
                            (new_stock_qty, now, stock_id_remote),
                        )

                    # Heredar propiedades de stock solo si no vinieron en el payload (ni como valor ni como null explícito)
                    if not catalogo_id_remote:
                        catalogo_id_remote = stock_row["catalogo_id"]
                    if item_color is None and "tela" not in fields_set and "color" not in fields_set:
                        item_color = stock_row["tela"]
                    if item_material is None and "material" not in fields_set:
                        item_material = stock_row["material"]
                    if item_descripcion is None and "descripcion" not in fields_set:
                        item_descripcion = stock_row["descripcion"]
                    if not image_id_remote:
                        image_id_remote = stock_row["image_id"]

                # Status de stock según envío
                if data.entrega_domicilio:
                    item_status = "procesado"
                    has_non_completed = True
                else:
                    item_status = "completado"
            else:
                # Encargo: siempre pendiente
                item_status = "pendiente"
                has_non_completed = True

            # 2. Si hay catalogo_id_remote (explícito o heredado de stock), heredar nombre, area, tipo_mueble e image_id
            if catalogo_id_remote:
                cands = _id_candidates(catalogo_id_remote)
                placeholders = ",".join(["?"] * len(cands))
                cursor = await db.execute(
                    f"SELECT id, nombre, tipo, area, image_id FROM catalogo WHERE id IN ({placeholders}) AND deleted_at IS NULL",
                    cands,
                )
                cat_row = await cursor.fetchone()
                if cat_row:
                    catalogo_id_remote = cat_row["id"]
                    if not item_nombre:
                        item_nombre = cat_row["nombre"]
                    if not item_tipo_mueble:
                        item_tipo_mueble = cat_row["tipo"]
                    if not item_area:
                        item_area = cat_row["area"]
                    if not image_id_remote:
                        image_id_remote = cat_row["image_id"]

            if not item_nombre:
                item_nombre = "Ítem sin nombre"

            # Validar existencia de referencias FK para evitar violaciones de clave foránea
            if image_id_remote:
                cands_img = _id_candidates(str(image_id_remote))
                ph_img = ",".join(["?"] * len(cands_img))
                c_img = await db.execute(
                    f"SELECT id FROM images WHERE id IN ({ph_img})",
                    cands_img,
                )
                img_row = await c_img.fetchone()
                if img_row:
                    image_id_remote = img_row[0]   # usar el ID exacto que está en la BD
                else:
                    image_id_remote = None

            if catalogo_id_remote:
                c_cat = await db.execute("SELECT id FROM catalogo WHERE id = ?", (catalogo_id_remote,))
                if not await c_cat.fetchone():
                    catalogo_id_remote = None

            if stock_id_remote:
                c_stk = await db.execute("SELECT id FROM stock WHERE id = ?", (stock_id_remote,))
                if not await c_stk.fetchone():
                    stock_id_remote = None

            raw_apoyo = getattr(item_data, "imagenes_apoyo", None)
            if isinstance(raw_apoyo, list):
                apoyo_json = json.dumps(raw_apoyo, ensure_ascii=False)
            elif isinstance(raw_apoyo, str) and raw_apoyo.strip():
                apoyo_json = raw_apoyo
            else:
                apoyo_json = "[]"

            await db.execute(
                """
                INSERT INTO items (
                    id, factura_id, stock_id, catalogo_id, image_id, imagenes_apoyo,
                    nombre, cantidad, tipo, subtotal, tela, material,
                    descripcion, area, tipo_mueble, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id, factura_id, stock_id_remote, catalogo_id_remote,
                    image_id_remote, apoyo_json, item_nombre, item_data.cantidad,
                    item_data.tipo, item_data.subtotal, item_color,
                    item_material, item_descripcion,
                    item_area, item_tipo_mueble, item_status,
                    now, now,
                ),
            )

            created_items.append({
                "id": item_id,
                "factura_id": factura_id,
                "stock_id": stock_id_remote,
                "catalogo_id": catalogo_id_remote,
                "image_id": image_id_remote,
                "imagenes_apoyo": json.loads(apoyo_json) if apoyo_json else [],
                "nombre": item_nombre,
                "cantidad": item_data.cantidad,
                "tipo": item_data.tipo,
                "subtotal": item_data.subtotal,
                "tela": item_color,
                "color": item_color,
                "material": item_material,
                "descripcion": item_descripcion,
                "area": item_area,
                "tipo_mueble": item_tipo_mueble,
                "status": item_status,
                "created_at": now,
                "updated_at": now,
            })

        # --- Paso 5: Actualizar items_id ---
        items_csv = ",".join(item_ids)
        await db.execute(
            "UPDATE facturas SET items_id = ? WHERE id = ?",
            (items_csv, factura_id),
        )

        # --- Paso 6: Cola de trabajos ---
        if has_non_completed or data.entrega_domicilio:
            cola_id = _gen_id(prefix)
            await db.execute(
                "INSERT INTO cola_trabajos (id, factura_id, created_at) VALUES (?, ?, ?)",
                (cola_id, factura_id, now),
            )

            # Crear envío si es a domicilio
            if data.entrega_domicilio:
                envio_id = _gen_id(prefix)
                await db.execute(
                    """
                    INSERT INTO envios (
                        id, factura_id, estado, direccion_entrega,
                        created_at, updated_at
                    ) VALUES (?, ?, 'Pendiente de Envío', ?, ?, ?)
                    """,
                    (envio_id, factura_id, data.direccion_entrega, now, now),
                )

        await db.commit()

        # --- Paso 7: Retornar factura completa ---
        return {
            "id": factura_id,
            "factura_id": factura_id,
            "cliente_id": cliente_id_remote,
            "total": data.total,
            "monto_pagado": data.monto_pagado,
            "saldo_pendiente": saldo,
            "items_count": len(item_ids),
            "items_id": items_csv,
            "items": created_items,
            "pago_id": pago_id,
        }

    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creando factura: {str(e)}",
        )


# ===========================================================================
# DELETE FACTURA (Hard Delete + Restaurar Stock)
# ===========================================================================

async def delete_factura(db: aiosqlite.Connection, factura_id: str):
    """
    Elimina una factura y restaura el stock de sus ítems tipo 'stock'.
    La cascada SQL se encarga de eliminar items, pagos, envíos y cola_trabajos.
    """
    # Verificar que la factura existe
    cursor = await db.execute("SELECT id FROM facturas WHERE id = ?", (factura_id,))
    if not await cursor.fetchone():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Factura no encontrada",
        )

    # Restaurar stock para ítems tipo 'stock'
    cursor = await db.execute(
        "SELECT stock_id, cantidad FROM items WHERE factura_id = ? AND tipo = 'stock' AND stock_id IS NOT NULL",
        (factura_id,),
    )
    stock_items = await cursor.fetchall()
    for stock_id, qty in stock_items:
        await db.execute(
            "UPDATE stock SET cantidad = cantidad + ?, updated_at = ? WHERE id = ?",
            (qty, _now_iso(), stock_id),
        )

    # DELETE factura (cascada elimina items, pagos, envios, cola_trabajos)
    await db.execute("DELETE FROM facturas WHERE id = ?", (factura_id,))
    await db.commit()


# ===========================================================================
# DISPATCH FACTURA
# ===========================================================================

async def dispatch_factura(db: aiosqlite.Connection, factura_id: str) -> dict:
    """
    Completa masivamente todos los ítems de una factura.
    Si tiene entrega_domicilio, crea envío si no existe.
    """
    now = _now_iso()

    # Verificar factura
    cursor = await db.execute(
        "SELECT id, entrega_domicilio FROM facturas WHERE id = ?",
        (factura_id,),
    )
    factura = await cursor.fetchone()
    if not factura:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Factura no encontrada",
        )

    # Completar todos los ítems
    await db.execute(
        """
        UPDATE items SET
            status = 'completado',
            fecha_procesado = CASE WHEN fecha_procesado IS NULL THEN ? ELSE fecha_procesado END,
            updated_at = ?
        WHERE factura_id = ? AND status != 'completado'
        """,
        (now, now, factura_id),
    )

    # Si tiene envío a domicilio y no tiene envío creado, crear uno
    if factura[1]:  # entrega_domicilio
        cursor = await db.execute(
            "SELECT id FROM envios WHERE factura_id = ?",
            (factura_id,),
        )
        if not await cursor.fetchone():
            cursor2 = await db.execute(
                "SELECT direccion_entrega FROM facturas WHERE id = ?",
                (factura_id,),
            )
            factura_row = await cursor2.fetchone()
            prefix = factura_id[:1]  # Extraer prefijo del ID
            envio_id = _gen_id(prefix)
            await db.execute(
                """
                INSERT INTO envios (
                    id, factura_id, estado, direccion_entrega, created_at, updated_at
                ) VALUES (?, ?, 'Pendiente de Envío', ?, ?, ?)
                """,
                (envio_id, factura_id, factura_row[0] if factura_row else None, now, now),
            )

    # Verificar si se puede remover de cola_trabajos
    await _check_and_remove_from_cola(db, factura_id)
    await db.commit()

    return {"factura_id": factura_id, "status": "dispatched"}


# ===========================================================================
# UPDATE ITEM STATUS (Máquina de estados con bypass)
# ===========================================================================

_VALID_TRANSITIONS = {
    "pendiente": ["procesando"],
    "procesando": ["procesado"],
    "procesado": ["completado"],
    "completado": [],
}


async def update_item_status(
    db: aiosqlite.Connection,
    item_id: str,
    new_status: str,
) -> dict:
    """
    Actualiza el status de un ítem con la máquina de estados.

    Transiciones: pendiente → procesando → procesado → completado
    Bypass: si procesado + factura sin envío → salta a completado
    """
    now = _now_iso()

    # Obtener ítem actual
    cursor = await db.execute(
        "SELECT id, factura_id, status FROM items WHERE id = ?",
        (item_id,),
    )
    item = await cursor.fetchone()
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ítem no encontrado",
        )

    current_status = item[2]
    factura_id = item[1]

    # Validar transición
    valid = _VALID_TRANSITIONS.get(current_status, [])
    if new_status not in valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Transición inválida: {current_status} → {new_status}",
        )

    # Aplicar según transición
    if new_status == "procesando":
        await db.execute(
            "UPDATE items SET status = ?, fecha_procesando = ?, updated_at = ? WHERE id = ?",
            (new_status, now, now, item_id),
        )
    elif new_status == "procesado":
        # Check bypass: si la factura NO tiene envío → completado directo
        cursor = await db.execute(
            "SELECT entrega_domicilio FROM facturas WHERE id = ?",
            (factura_id,),
        )
        factura = await cursor.fetchone()
        if factura and not factura[0]:
            # Bypass: saltar a completado
            new_status = "completado"

        await db.execute(
            "UPDATE items SET status = ?, fecha_procesado = ?, updated_at = ? WHERE id = ?",
            (new_status, now, now, item_id),
        )
    elif new_status == "completado":
        await db.execute(
            "UPDATE items SET status = ?, updated_at = ? WHERE id = ?",
            (new_status, now, item_id),
        )

    # Si completado: verificar si todos los ítems están completados
    if new_status == "completado":
        await _check_and_remove_from_cola(db, factura_id)

    await db.commit()

    return {"item_id": item_id, "status": new_status}


# ===========================================================================
# UPDATE ENVIO STATUS (con activación de garantía)
# ===========================================================================

async def update_envio_status(
    db: aiosqlite.Connection,
    envio_id: str,
    new_estado: str,
) -> dict:
    """
    Actualiza el estado de un envío.
    Al llegar a 'Entregado', activa la garantía de la factura.
    """
    now = _now_iso()

    cursor = await db.execute(
        "SELECT id, factura_id, estado FROM envios WHERE id = ?",
        (envio_id,),
    )
    envio = await cursor.fetchone()
    if not envio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Envío no encontrado",
        )

    factura_id = envio[1]

    if new_estado == "En Ruta":
        await db.execute(
            "UPDATE envios SET estado = ?, fecha_enviado = ?, updated_at = ? WHERE id = ?",
            (new_estado, now, now, envio_id),
        )

    elif new_estado == "Entregado":
        await db.execute(
            "UPDATE envios SET estado = ?, fecha_entregado = ?, updated_at = ? WHERE id = ?",
            (new_estado, now, now, envio_id),
        )

        # Activar garantía
        cursor = await db.execute(
            "SELECT garantia_hasta FROM facturas WHERE id = ?",
            (factura_id,),
        )
        factura = await cursor.fetchone()
        if factura and factura[0]:
            venc = compute_warranty(factura[0], now)
            if venc:
                await db.execute(
                    """
                    UPDATE facturas SET
                        status_garantia = 'Vigente',
                        venc_garantia = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (venc, now, factura_id),
                )

        # Verificar cola_trabajos
        await _check_and_remove_from_cola(db, factura_id)

    else:
        await db.execute(
            "UPDATE envios SET estado = ?, updated_at = ? WHERE id = ?",
            (new_estado, now, envio_id),
        )

    await db.commit()

    return {"envio_id": envio_id, "estado": new_estado, "factura_id": factura_id}
