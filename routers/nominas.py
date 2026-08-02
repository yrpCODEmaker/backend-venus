from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
import uuid
import datetime

from database import get_db
from schemas import (
    EmpleadoIn, EmpleadoOut,
    ComisionEmpleadoIn, ComisionEmpleadoOut
)
from services.auth import require_permission

router = APIRouter(prefix="/api/v1/nominas", tags=["Nóminas"])

@router.get("/empleados", response_model=List[EmpleadoOut])
async def get_empleados(db = Depends(get_db), user: dict = Depends(require_permission("nominas_gestionar"))):
    async with db.execute("SELECT * FROM empleados") as cursor:
        rows = await cursor.fetchall()
    empleados = []
    for row in rows:
        empleados.append({
            "id": row["id"],
            "nombre": row["nombre"],
            "telefono": row["telefono"],
            "telefono_familiar": row["telefono_familiar"],
            "rol": row["rol"],
            "salario_fijo": row["salario_fijo"],
            "gana_comision": bool(row["gana_comision"]),
            "dia_cobro": row["dia_cobro"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        })
    return empleados

@router.post("/empleados", response_model=EmpleadoOut)
async def create_empleado(empleado: EmpleadoIn, db = Depends(get_db), user: dict = Depends(require_permission("nominas_gestionar"))):
    emp_id = str(uuid.uuid4())
    now = datetime.datetime.utcnow().isoformat()
    
    await db.execute("""
        INSERT INTO empleados (id, nombre, telefono, telefono_familiar, rol, salario_fijo, gana_comision, dia_cobro, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        emp_id, empleado.nombre, empleado.telefono, empleado.telefono_familiar, empleado.rol,
        empleado.salario_fijo, 1 if empleado.gana_comision else 0, empleado.dia_cobro, now, now
    ))
    await db.commit()
    
    return {**empleado.dict(), "id": emp_id, "created_at": now, "updated_at": now}

@router.patch("/empleados/{empleado_id}", response_model=EmpleadoOut)
async def update_empleado(empleado_id: str, empleado: EmpleadoIn, db = Depends(get_db), user: dict = Depends(require_permission("nominas_gestionar"))):
    now = datetime.datetime.utcnow().isoformat()
    
    async with db.execute("SELECT id, created_at FROM empleados WHERE id = ?", (empleado_id,)) as cursor:
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Empleado no encontrado")
    
    await db.execute("""
        UPDATE empleados
        SET nombre = ?, telefono = ?, telefono_familiar = ?, rol = ?, salario_fijo = ?, gana_comision = ?, dia_cobro = ?, updated_at = ?
        WHERE id = ?
    """, (
        empleado.nombre, empleado.telefono, empleado.telefono_familiar, empleado.rol,
        empleado.salario_fijo, 1 if empleado.gana_comision else 0, empleado.dia_cobro, now, empleado_id
    ))
    await db.commit()
    
    return {**empleado.dict(), "id": empleado_id, "created_at": row["created_at"], "updated_at": now}

@router.delete("/empleados/{empleado_id}")
async def delete_empleado(empleado_id: str, db = Depends(get_db), user: dict = Depends(require_permission("nominas_gestionar"))):
    await db.execute("DELETE FROM empleados WHERE id = ?", (empleado_id,))
    await db.commit()
    return {"message": "Empleado eliminado"}

# ---------------------------------------------------------------------------
# COMISIONES DE EMPLEADOS
# ---------------------------------------------------------------------------

@router.get("/empleados/{empleado_id}/comisiones", response_model=List[ComisionEmpleadoOut])
async def get_comisiones(empleado_id: str, db = Depends(get_db), user: dict = Depends(require_permission("nominas_gestionar"))):
    async with db.execute("SELECT * FROM comisiones_empleado WHERE empleado_id = ?", (empleado_id,)) as cursor:
        rows = await cursor.fetchall()
    
    return [dict(row) for row in rows]

@router.post("/empleados/{empleado_id}/comisiones", response_model=ComisionEmpleadoOut)
async def create_comision(empleado_id: str, comision: ComisionEmpleadoIn, db = Depends(get_db), user: dict = Depends(require_permission("nominas_gestionar"))):
    com_id = str(uuid.uuid4())
    
    try:
        await db.execute("""
            INSERT INTO comisiones_empleado (id, empleado_id, catalogo_id, monto)
            VALUES (?, ?, ?, ?)
        """, (com_id, empleado_id, comision.catalogo_id, comision.monto))
        await db.commit()
    except Exception as e:
        raise HTTPException(status_code=400, detail="Error al agregar comisión (posible duplicado)")
        
    return {**comision.dict(), "id": com_id, "empleado_id": empleado_id}

@router.delete("/comisiones/{comision_id}")
async def delete_comision(comision_id: str, db = Depends(get_db), user: dict = Depends(require_permission("nominas_gestionar"))):
    await db.execute("DELETE FROM comisiones_empleado WHERE id = ?", (comision_id,))
    await db.commit()
    return {"message": "Comisión eliminada"}
