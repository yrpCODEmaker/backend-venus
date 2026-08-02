from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List, Optional
import uuid
import datetime
from collections import defaultdict
import json

from database import get_db
from schemas import (
    GastoPerfilIn, GastoPerfilOut,
    GastoRegistroIn, GastoRegistroOut,
    DashboardMetricsOut
)
from services.auth import require_permission

router = APIRouter(prefix="/api/v1/finanzas", tags=["Finanzas"])

@router.get("/gastos/perfiles", response_model=List[GastoPerfilOut])
async def get_gastos_perfiles(db = Depends(get_db), user: dict = Depends(require_permission("gastos_gestionar"))):
    async with db.execute("SELECT * FROM gastos_perfiles") as cursor:
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]

@router.post("/gastos/perfiles", response_model=GastoPerfilOut)
async def create_gasto_perfil(perfil: GastoPerfilIn, db = Depends(get_db), user: dict = Depends(require_permission("gastos_gestionar"))):
    perfil_id = str(uuid.uuid4())
    now = datetime.datetime.utcnow().isoformat()
    await db.execute("""
        INSERT INTO gastos_perfiles (id, nombre, tipo, dia_pago, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (perfil_id, perfil.nombre, perfil.tipo, perfil.dia_pago, now))
    await db.commit()
    return {**perfil.dict(), "id": perfil_id, "created_at": now}

@router.delete("/gastos/perfiles/{perfil_id}")
async def delete_gasto_perfil(perfil_id: str, db = Depends(get_db), user: dict = Depends(require_permission("gastos_gestionar"))):
    await db.execute("DELETE FROM gastos_perfiles WHERE id = ?", (perfil_id,))
    await db.commit()
    return {"message": "Perfil eliminado"}

# ---------------------------------------------------------------------------
# GASTOS REGISTROS
# ---------------------------------------------------------------------------

@router.get("/gastos/registros", response_model=List[GastoRegistroOut])
async def get_gastos_registros(db = Depends(get_db), user: dict = Depends(require_permission("gastos_gestionar"))):
    async with db.execute("SELECT * FROM gastos_registros ORDER BY fecha DESC") as cursor:
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]

@router.post("/gastos/registros", response_model=GastoRegistroOut)
async def create_gasto_registro(registro: GastoRegistroIn, db = Depends(get_db), user: dict = Depends(require_permission("gastos_gestionar"))):
    reg_id = str(uuid.uuid4())
    now = datetime.datetime.utcnow().isoformat()
    await db.execute("""
        INSERT INTO gastos_registros (id, perfil_id, monto, fecha, nota, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (reg_id, registro.perfil_id, registro.monto, registro.fecha, registro.nota, now))
    await db.commit()
    return {**registro.dict(), "id": reg_id, "created_at": now}

@router.delete("/gastos/registros/{registro_id}")
async def delete_gasto_registro(registro_id: str, db = Depends(get_db), user: dict = Depends(require_permission("gastos_gestionar"))):
    await db.execute("DELETE FROM gastos_registros WHERE id = ?", (registro_id,))
    await db.commit()
    return {"message": "Registro eliminado"}


# ---------------------------------------------------------------------------
# METRICAS Y DASHBOARD
# ---------------------------------------------------------------------------

@router.get("/metricas", response_model=DashboardMetricsOut)
async def get_metricas(
    start_date: str = Query(..., description="Fecha de inicio en YYYY-MM-DD"),
    end_date: str = Query(..., description="Fecha de fin en YYYY-MM-DD"),
    db = Depends(get_db), 
    user: dict = Depends(require_permission("finanzas_ver"))
):
    try:
        start_dt = datetime.datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de fecha inválido. Usa YYYY-MM-DD.")
    
    # Asegurarnos de cubrir todo el día final
    end_dt = end_dt.replace(hour=23, minute=59, second=59)

    # 1. INGRESOS (Pagos recibidos en el rango)
    async with db.execute("""
        SELECT SUM(monto) as total_ingresos
        FROM pagos
        WHERE fecha >= ? AND fecha <= ?
    """, (start_dt.isoformat(), end_dt.isoformat())) as cursor:
        row = await cursor.fetchone()
        ingresos_facturas = row["total_ingresos"] or 0.0

    # 2. GASTOS OPERATIVOS
    async with db.execute("""
        SELECT SUM(monto) as total_gastos
        FROM gastos_registros
        WHERE fecha >= ? AND fecha <= ?
    """, (start_date, end_date)) as cursor:
        row = await cursor.fetchone()
        gastos_operativos = row["total_gastos"] or 0.0

    # 3. NOMINA SUELDOS FIJOS
    async with db.execute("SELECT salario_fijo, dia_cobro FROM empleados WHERE salario_fijo > 0 AND dia_cobro IS NOT NULL") as cursor:
        empleados = await cursor.fetchall()
    
    nomina_sueldos_fijos = 0.0
    # Calcular cuántas veces cayó el dia_cobro en el rango para cada empleado
    delta = (end_dt - start_dt).days + 1
    for i in range(delta):
        current_day = start_dt + datetime.timedelta(days=i)
        for emp in empleados:
            if emp["dia_cobro"] == current_day.day:
                nomina_sueldos_fijos += emp["salario_fijo"]

    # 4. NOMINA COMISIONES & ESTADISTICAS DE ITEMS
    # Buscamos todos los ítems que tengan fecha_procesado en el rango
    # Y cruzamos con las comisiones.
    query_items = """
        SELECT i.id, i.catalogo_id, i.nombre, i.area, i.tipo_mueble, i.fecha_procesado, 
               f.entrega_domicilio, e.estado as envio_estado, e.updated_at as envio_updated
        FROM items i
        JOIN facturas f ON i.factura_id = f.id
        LEFT JOIN envios e ON e.factura_id = f.id
        WHERE i.status = 'Procesado'
    """
    async with db.execute(query_items) as cursor:
        items_procesados_db = await cursor.fetchall()

    # Pre-cargar comisiones (map de catalogo_id -> suma de montos)
    async with db.execute("SELECT catalogo_id, SUM(monto) as total_comision FROM comisiones_empleado GROUP BY catalogo_id") as cursor:
        comisiones_rows = await cursor.fetchall()
        comisiones_map = {row["catalogo_id"]: row["total_comision"] for row in comisiones_rows}

    nomina_comisiones = 0.0
    count_procesados = 0
    top_muebles_map = defaultdict(int)
    top_areas_map = defaultdict(int)

    for item in items_procesados_db:
        es_valido = False
        
        # Validar si cumple condición de fechas
        if item["entrega_domicilio"] == 1:
            if item["envio_estado"] == "Entregado" and item["envio_updated"]:
                if start_dt.isoformat() <= item["envio_updated"] <= end_dt.isoformat():
                    es_valido = True
        else:
            if item["fecha_procesado"]:
                if start_dt.isoformat() <= item["fecha_procesado"] <= end_dt.isoformat():
                    es_valido = True
        
        if es_valido:
            count_procesados += 1
            if item["catalogo_id"] in comisiones_map:
                nomina_comisiones += comisiones_map[item["catalogo_id"]]
            
            # Sumar a métricas
            mueble_key = item["tipo_mueble"] or item["nombre"]
            top_muebles_map[mueble_key] += 1
            
            # El area podría estar en JSON
            areas = []
            try:
                areas_parsed = json.loads(item["area"])
                if isinstance(areas_parsed, list):
                    areas = areas_parsed
                else:
                    areas = [item["area"]]
            except:
                areas = [item["area"]]
                
            for a in areas:
                if a and a != 'null':
                    top_areas_map[a] += 1

    # Ordenar top muebles
    top_muebles = [{"name": k, "value": v} for k, v in top_muebles_map.items()]
    top_muebles = sorted(top_muebles, key=lambda x: x["value"], reverse=True)[:5]

    top_areas = [{"name": k, "value": v} for k, v in top_areas_map.items()]
    top_areas = sorted(top_areas, key=lambda x: x["value"], reverse=True)[:5]

    ganancia_neta = ingresos_facturas - gastos_operativos - nomina_sueldos_fijos - nomina_comisiones

    return {
        "ingresos_facturas": ingresos_facturas,
        "gastos_operativos": gastos_operativos,
        "nomina_sueldos_fijos": nomina_sueldos_fijos,
        "nomina_comisiones": nomina_comisiones,
        "ganancia_neta": ganancia_neta,
        "items_procesados": count_procesados,
        "top_muebles": top_muebles,
        "top_areas": top_areas
    }
