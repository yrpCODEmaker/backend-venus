"""
Venus Backend — Schemas Pydantic.

Todos los schemas de validación en un solo archivo:
- Auth: login, token, usuario
- Admin: permisos granulares, edición integral de usuario, visibilidad de datos
- Sync In: entrada del cliente (IDs como int)
- Sync Out: salida al cliente (IDs como int, prefijo eliminado)
- Operacional: schemas para endpoints REST (pagos, facturas, items, etc.)

Los schemas de entrada (In) siempre esperan `int` de los clientes
tal como lo envía SQLite local. La transformación a `str` con prefijo
ocurre internamente en el PrefixTransformer.

Cambios (Fase 2 — Permisos granulares):
  - UserPermissionsOut / UserPermissionsIn: contrato de lectura y escritura de permisos.
  - AdminUserUpdateIn: edición integral de usuario (username, password, prefix).
  - DataVisibilityPatchIn: ajuste parcial de visibilidad entre usuarios.
  - UserOut: ahora incluye campo `permissions` opcional.
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator


# ===========================================================================
# AUTH
# ===========================================================================

class LoginRequest(BaseModel):
    """Credenciales de login."""
    username: str
    password: str


class TokenResponse(BaseModel):
    """Respuesta del endpoint de login."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(BaseModel):
    """Datos públicos de un usuario (sin contraseña)."""
    username: str
    rol: str
    prefix: Optional[str] = None
    activo: bool
    permissions: Optional["UserPermissionsOut"] = None


class UserCreateIn(BaseModel):
    """Payload para crear un nuevo usuario (solo admin)."""
    username: str
    password: str
    prefix: Optional[str] = None


# ---------------------------------------------------------------------------
# ADMIN — Permisos granulares y gestión integral de usuarios
# ---------------------------------------------------------------------------

class UserPermissionsOut(BaseModel):
    """
    Permisos granulares de un usuario por dominio.

    Todos los campos son booleanos. El campo `prefijos_visibles` contiene
    la lista de prefijos de otros usuarios cuyos datos puede ver este usuario.
    """
    # Facturas
    facturas_ver: bool = True
    facturas_emitir: bool = False
    facturas_modificar: bool = False
    facturas_declarar_perdida: bool = False
    facturas_perdonar_deuda: bool = False
    # Fabricación
    fabricacion_ver_estados: bool = True
    fabricacion_modificar_estados: bool = False
    fabricacion_mandar_envio: bool = False
    # Stock
    stock_crear: bool = False
    stock_modificar: bool = False
    stock_eliminar: bool = False
    # Catálogo
    catalogo_crear: bool = False
    catalogo_modificar: bool = False
    catalogo_eliminar: bool = False
    # Clientes
    clientes_crear: bool = False
    clientes_modificar: bool = False
    clientes_eliminar: bool = False
    # Finanzas y Nóminas
    finanzas_ver: bool = False
    nominas_gestionar: bool = False
    gastos_gestionar: bool = False
    # Visibilidad
    puede_ver_datos_de_otros: bool = False
    prefijos_visibles: List[str] = Field(default_factory=list)


class UserPermissionsIn(BaseModel):
    """
    Escritura completa de permisos de un usuario por parte del admin.

    Todos los campos son opcionales: solo se actualizan los enviados.
    Permite reemplazar los permisos de forma total o parcial mediante
    el endpoint PUT /admin/users/{username}/permissions.
    """
    # Facturas
    facturas_ver: Optional[bool] = None
    facturas_emitir: Optional[bool] = None
    facturas_modificar: Optional[bool] = None
    facturas_declarar_perdida: Optional[bool] = None
    facturas_perdonar_deuda: Optional[bool] = None
    # Fabricación
    fabricacion_ver_estados: Optional[bool] = None
    fabricacion_modificar_estados: Optional[bool] = None
    fabricacion_mandar_envio: Optional[bool] = None
    # Stock
    stock_crear: Optional[bool] = None
    stock_modificar: Optional[bool] = None
    stock_eliminar: Optional[bool] = None
    # Catálogo
    catalogo_crear: Optional[bool] = None
    catalogo_modificar: Optional[bool] = None
    catalogo_eliminar: Optional[bool] = None
    # Clientes
    clientes_crear: Optional[bool] = None
    clientes_modificar: Optional[bool] = None
    clientes_eliminar: Optional[bool] = None
    # Finanzas y Nóminas
    finanzas_ver: Optional[bool] = None
    nominas_gestionar: Optional[bool] = None
    gastos_gestionar: Optional[bool] = None
    # Visibilidad
    puede_ver_datos_de_otros: Optional[bool] = None
    prefijos_visibles: Optional[List[str]] = None


class AdminUserUpdateIn(BaseModel):
    """
    Edición integral de un usuario por parte del admin.

    Permite cambiar el nombre de usuario, la contraseña y el prefijo.
    Todos los campos son opcionales: solo se actualizan los enviados.
    Regla crítica: el admin principal no puede cambiar su propio prefijo ni rol.
    """
    username: Optional[str] = Field(None, min_length=3, description="Nuevo nombre de usuario")
    password: Optional[str] = Field(None, min_length=6, description="Nueva contraseña")
    prefix: Optional[str] = Field(None, min_length=1, description="Nuevo prefijo único")


class DataVisibilityPatchIn(BaseModel):
    """
    Ajuste parcial de visibilidad de datos entre usuarios.

    Controla qué prefijos de otros usuarios puede ver el usuario objetivo.
    Solo el admin puede modificar este campo.
    Los prefijos deben corresponder a usuarios existentes en el sistema.
    """
    puede_ver_datos_de_otros: Optional[bool] = None
    prefijos_visibles: Optional[List[str]] = Field(
        None,
        description="Lista de prefijos de usuarios cuyos datos puede ver este usuario"
    )


# ===========================================================================
# SYNC IN — Entrada del cliente (IDs como int)
# ===========================================================================

class BaseSyncIn(BaseModel):
    """Esquema base de entrada. El cliente envía IDs enteros."""
    local_id: int
    updated_at: datetime
    deleted_at: Optional[datetime] = None


class ClienteIn(BaseSyncIn):
    """Cliente sincronizado desde el desktop."""
    nombre: str
    apellido: str
    telefono: Optional[str] = None
    email: Optional[str] = None
    domicilio: Optional[str] = None
    prioridad: bool = False


class ImageIn(BaseSyncIn):
    """Imagen sincronizada desde el desktop."""
    aspect_ratio: Optional[str] = None
    hash: Optional[str] = None
    file_path: str  # Referencia local; el backend siempre genera su propia ruta al guardar

    @field_validator("file_path")
    @classmethod
    def sanitize_file_path(cls, v: str) -> str:
        """
        Rechaza rutas que puedan explotar un LFI.

        Reglas:
          - Sin path traversal (..).
          - Sin rutas absolutas Unix (/).
          - Sin prefijos de unidad Windows (C:\\, D:\\, etc.).
          - Sin rutas UNC (\\\\server).
          - Sin caracteres de control ni null bytes.
        """
        if not v:
            raise ValueError("file_path no puede estar vacío")

        # Null bytes y caracteres de control
        if "\x00" in v or any(ord(c) < 32 for c in v):
            raise ValueError("file_path contiene caracteres no permitidos")

        # Path traversal
        if ".." in v:
            raise ValueError("file_path no puede contener '..' (path traversal)")

        # Ruta absoluta Unix
        if v.startswith("/"):
            raise ValueError("file_path no puede ser una ruta absoluta")

        # Prefijo de unidad Windows (ej: C:\\, D:/)
        if re.match(r'^[A-Za-z]:[/\\]', v):
            raise ValueError("file_path no puede ser una ruta de unidad Windows")

        # Ruta UNC (\\\\servidor)
        if v.startswith("\\\\") or v.startswith("//"):
            raise ValueError("file_path no puede ser una ruta UNC")

        return v


class CatalogoIn(BaseSyncIn):
    """Plantilla de catálogo sincronizada."""
    nombre: str
    tipo: Optional[str] = None
    area: Optional[str] = None
    precio_base: Optional[float] = None
    image_id: Optional[int] = None  # FK local → transformada a "{prefix}{image_id}"


class StockIn(BaseSyncIn):
    """Variante de stock sincronizada."""
    catalogo_id: int  # FK local
    tela: Optional[str] = None
    color: Optional[str] = None
    material: Optional[str] = None
    descripcion: Optional[str] = None
    cantidad: int = 0
    precio: Optional[float] = None
    image_id: Optional[int] = None

    @model_validator(mode="after")
    def populate_tela(self) -> "StockIn":
        if not self.tela and self.color:
            self.tela = self.color
        return self


class FacturaIn(BaseSyncIn):
    """Factura sincronizada desde el desktop."""
    cliente_id: Optional[int] = None  # FK local; None si es factura rápida
    cliente: Optional[Dict[str, Any]] = None  # JSON raw para factura rápida
    fecha: datetime
    total: float
    monto_pagado: float = 0.0
    saldo_pendiente: float
    items_id: str  # CSV de IDs locales: "1,2,3"
    entrega_domicilio: bool
    direccion_entrega: Optional[str] = None
    estatus_entrega: str = "No Aplica"
    garantia_hasta: str = "Sin Garantía"
    status_garantia: Optional[str] = None
    venc_garantia: Optional[str] = None
    facturacion_rapida: int = 0
    declarado_perdida: int = 0
    declarado_perdonado: int = 0


class PagoIn(BaseModel):
    """Pago/abono sincronizado."""
    local_id: int
    factura_id: int  # FK local
    monto: float
    fecha: datetime
    nota: Optional[str] = None
    created_at: datetime


class ItemIn(BaseModel):
    """Ítem de factura sincronizado."""
    local_id: int
    factura_id: int  # FK local
    stock_id: Optional[int] = None
    catalogo_id: Optional[int] = None
    image_id: Optional[int] = None
    nombre: str
    cantidad: int
    tipo: str  # 'encargo' | 'stock'
    subtotal: float
    tela: Optional[str] = None
    color: Optional[str] = None
    material: Optional[str] = None
    descripcion: Optional[str] = None
    area: Optional[str] = None
    tipo_mueble: Optional[str] = None
    status: str  # pendiente | procesando | procesado | completado
    fecha_procesando: Optional[datetime] = None
    fecha_procesado: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def populate_tela(self) -> "ItemIn":
        if not self.tela and self.color:
            self.tela = self.color
        return self


class EnvioIn(BaseModel):
    """Envío sincronizado."""
    local_id: int
    factura_id: int  # FK local
    estado: str  # 'Pendiente de Envío' | 'En Ruta' | 'Entregado'
    direccion_entrega: Optional[str] = None
    fecha_programada: Optional[datetime] = None
    fecha_enviado: Optional[datetime] = None
    fecha_entregado: Optional[datetime] = None
    notas: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ColaTrabajoIn(BaseModel):
    """Cola de trabajos sincronizada."""
    local_id: int
    factura_id: int  # FK local
    created_at: datetime


class ConfiguracionIn(BaseSyncIn):
    """Configuración sincronizada (empresa, colores, materiales, etc.)."""
    clave: str
    valor: Any  # Valor flexible (string, array, objeto JSON)


class PushSyncPayload(BaseModel):
    """Payload maestro del Push Sync. El prefix se lee del JWT."""
    clientes: List[ClienteIn] = []
    images: List[ImageIn] = []
    catalogo: List[CatalogoIn] = []
    stock: List[StockIn] = []
    facturas: List[FacturaIn] = []
    pagos: List[PagoIn] = []
    items: List[ItemIn] = []
    envios: List[EnvioIn] = []
    cola_trabajos: List[ColaTrabajoIn] = []
    configuracion: List[ConfiguracionIn] = []


# ===========================================================================
# OPERACIONAL — Schemas para endpoints REST
# ===========================================================================

class PagoCreateIn(BaseModel):
    """Crear un abono desde endpoint REST."""
    monto: float = Field(..., gt=0)
    nota: Optional[str] = None


class ItemStatusUpdate(BaseModel):
    """Actualizar el estado de producción de un ítem."""
    status: str  # pendiente | procesando | procesado | completado


class EnvioStatusUpdate(BaseModel):
    """Actualizar el estado de un envío."""
    estado: str  # 'Pendiente de Envío' | 'En Ruta' | 'Entregado'


class EnvioUpdateIn(BaseModel):
    """Actualizar detalles logísticos de un envío."""
    direccion_entrega: Optional[str] = None
    fecha_programada: Optional[datetime] = None
    notas: Optional[str] = None


class ClienteRapidoSchema(BaseModel):
    """
    Estructura obligatoria del JSON de cliente para facturas rápidas.

    Según el workflow Venus, una factura rápida debe almacenar en la columna
    `cliente` un JSON con {nombre, apellido, telefono} para identificar al
    cliente ocasional sin registrarlo en la tabla de clientes.
    """
    nombre: str = Field(..., min_length=1, description="Nombre del cliente ocasional")
    apellido: str = Field(default="", description="Apellido del cliente (puede estar vacío)")
    telefono: str = Field(default="", description="Teléfono del cliente (puede estar vacío)")


class FacturaCreateItemIn(BaseModel):
    """Ítem dentro del payload de creación de factura."""
    stock_id: Optional[str] = None
    catalogo_id: Optional[str] = None
    image_id: Optional[str] = None
    nombre: Optional[str] = None
    cantidad: int = Field(..., ge=1)
    tipo: str  # 'encargo' | 'stock'
    subtotal: float
    tela: Optional[str] = None
    color: Optional[str] = None
    material: Optional[str] = None
    descripcion: Optional[str] = None
    area: Optional[str] = None
    tipo_mueble: Optional[str] = None

    @model_validator(mode="after")
    def populate_tela(self) -> "FacturaCreateItemIn":
        if not self.tela and self.color:
            self.tela = self.color
        return self


class FacturaCreateIn(BaseModel):
    """
    Crear factura transaccional con ítems y pago opcional.

    Reglas de validación (workflow Venus):
    - Si facturacion_rapida == 0 (cliente registrado): cliente_id es obligatorio.
    - Si facturacion_rapida == 1 (venta rápida): el campo 'cliente' es obligatorio
      y debe contener al menos 'nombre'. Se almacena como JSON estructurado
      {nombre, apellido, telefono} en la columna cliente de la tabla facturas.
    """
    cliente_id: Optional[str] = None
    cliente: Optional[ClienteRapidoSchema] = None  # JSON estructurado para factura rápida
    total: float
    monto_pagado: float = 0.0
    items: List[FacturaCreateItemIn]
    entrega_domicilio: bool = False
    direccion_entrega: Optional[str] = None
    garantia_hasta: str = "Sin Garantía"
    facturacion_rapida: int = 0

    @model_validator(mode="after")
    def validar_cliente_obligatorio(self) -> "FacturaCreateIn":
        """
        Valida que la factura tenga siempre identificación de cliente.

        - Factura normal (facturacion_rapida=0): requiere cliente_id.
        - Factura rápida (facturacion_rapida=1): requiere cliente con nombre.
        """
        if self.facturacion_rapida == 0:
            if not self.cliente_id:
                raise ValueError(
                    "Una factura normal requiere 'cliente_id'. "
                    "Si es una venta ocasional, marca 'facturacion_rapida=1' y proporciona el campo 'cliente'."
                )
        else:  # facturacion_rapida == 1
            if not self.cliente or not self.cliente.nombre:
                raise ValueError(
                    "Una factura rápida requiere el campo 'cliente' con al menos 'nombre'. "
                    "Formato: {\"nombre\": \"Juan\", \"apellido\": \"Pérez\", \"telefono\": \"809-555-0000\"}"
                )
        return self


class FacturaUpdateIn(BaseModel):
    """Actualización parcial de factura."""
    cliente_id: Optional[str] = None
    direccion_entrega: Optional[str] = None
    garantia_hasta: Optional[str] = None
    estatus_entrega: Optional[str] = None


class ItemUpdateIn(BaseModel):
    """Modificar características de un ítem."""
    tela: Optional[str] = None
    material: Optional[str] = None
    descripcion: Optional[str] = None
    subtotal: Optional[float] = None


class ItemPhotoUpdate(BaseModel):
    """Actualizar la foto de referencia de un ítem."""
    image_id: str


class ItemAddIn(BaseModel):
    """Agregar un nuevo ítem a una factura existente."""
    stock_id: Optional[str] = None
    catalogo_id: Optional[str] = None
    image_id: Optional[str] = None
    nombre: str
    cantidad: int = Field(..., ge=1)
    tipo: str
    subtotal: float
    tela: Optional[str] = None
    material: Optional[str] = None
    descripcion: Optional[str] = None
    area: Optional[str] = None
    tipo_mueble: Optional[str] = None


class ClienteCreateIn(BaseModel):
    """Crear un cliente desde endpoint REST."""
    nombre: str
    apellido: str
    telefono: Optional[str] = None
    email: Optional[str] = None
    domicilio: Optional[str] = None
    prioridad: bool = False


class ClienteUpdateIn(BaseModel):
    """Actualización parcial de cliente."""
    nombre: Optional[str] = None
    apellido: Optional[str] = None
    telefono: Optional[str] = None
    email: Optional[str] = None
    domicilio: Optional[str] = None
    prioridad: Optional[bool] = None


class CatalogoCreateIn(BaseModel):
    """Crear una plantilla de catálogo."""
    nombre: str
    tipo: Optional[str] = None
    area: Optional[str] = None
    precio_base: Optional[float] = None
    image_id: Optional[str] = None


class CatalogoUpdateIn(BaseModel):
    """Actualización parcial de catálogo."""
    nombre: Optional[str] = None
    tipo: Optional[str] = None
    area: Optional[str] = None
    precio_base: Optional[float] = None
    image_id: Optional[str] = None


class StockCreateIn(BaseModel):
    """Crear una variante de stock."""
    catalogo_id: str
    tela: Optional[str] = None
    material: Optional[str] = None
    descripcion: Optional[str] = None
    cantidad: int = 0
    precio: Optional[float] = None
    image_id: Optional[str] = None


class StockUpdateIn(BaseModel):
    """Actualización parcial de stock."""
    tela: Optional[str] = None
    material: Optional[str] = None
    descripcion: Optional[str] = None
    precio: Optional[float] = None
    image_id: Optional[str] = None


class StockCantidadUpdate(BaseModel):
    """Ajuste de cantidad de stock (delta positivo o negativo)."""
    delta: int  # +3 o -2


class ConfigUpdateIn(BaseModel):
    """Reemplazo total de configuración del usuario."""
    empresa_nombre: Optional[str] = None
    colores: Optional[List[str]] = None
    materiales: Optional[List[str]] = None
    tipos: Optional[List[str]] = None
    areas: Optional[List[str]] = None


class MaterialOut(BaseModel):
    """Respuesta al consultar un registro de materiales/categorías."""
    id: str
    categoria: str
    elementos: List[str] = []
    color: Optional[Union[List[str], str]] = None
    updated_at: Optional[str] = None


class MaterialCreateIn(BaseModel):
    """Crear un nuevo registro en la tabla de materiales."""
    categoria: str
    elementos: List[str] = []
    color: Optional[Union[List[str], str]] = None


class MaterialUpdateIn(BaseModel):
    """Actualización parcial de un registro de materiales."""
    categoria: Optional[str] = None
    elementos: Optional[List[str]] = None
    color: Optional[Union[List[str], str]] = None


# ===========================================================================
# SYNC OUT — Salida al cliente (IDs des-prefijados)
# ===========================================================================

class ClienteSyncOut(BaseModel):
    local_id: Union[int, str]
    nombre: str
    apellido: Optional[str] = None
    telefono: Optional[str] = None
    email: Optional[str] = None
    ubicacion: Optional[Dict[str, Any]] = None
    prioridad: int = 0
    updated_at: Optional[str] = None
    deleted_at: Optional[str] = None


class CatalogoSyncOut(BaseModel):
    local_id: Union[int, str]
    nombre: str
    tipo: Optional[str] = None
    area: Optional[str] = None
    precio_base: Optional[float] = None
    image_id: Optional[Union[int, str]] = None
    updated_at: Optional[str] = None
    deleted_at: Optional[str] = None


class StockSyncOut(BaseModel):
    local_id: Union[int, str]
    catalogo_id: Union[int, str]
    tela: Optional[str] = None
    material: Optional[str] = None
    descripcion: Optional[str] = None
    cantidad: int = 0
    precio: Optional[float] = None
    image_id: Optional[Union[int, str]] = None
    updated_at: Optional[str] = None
    deleted_at: Optional[str] = None


class ImageSyncOut(BaseModel):
    local_id: Union[int, str]
    aspect_ratio: Optional[str] = None
    file_path: Optional[str] = None
    updated_at: Optional[str] = None
    deleted_at: Optional[str] = None


class FacturaSyncOut(BaseModel):
    local_id: Union[int, str]
    cliente_id: Optional[Union[int, str]] = None
    fecha: str
    total: float
    monto_pagado: float = 0.0
    items_id: Optional[str] = None
    entrega_domicilio: int = 0
    direccion_entrega: Optional[str] = None
    estatus_entrega: Optional[str] = None
    garantia_hasta: Optional[str] = None
    status_garantia: str = "Vigente"
    updated_at: Optional[str] = None
    deleted_at: Optional[str] = None


class ItemSyncOut(BaseModel):
    local_id: Union[int, str]
    factura_id: Union[int, str]
    stock_id: Optional[Union[int, str]] = None
    catalogo_id: Optional[Union[int, str]] = None
    image_id: Optional[Union[int, str]] = None
    nombre: str
    cantidad: int
    tipo: str
    subtotal: float
    tela: Optional[str] = None
    material: Optional[str] = None
    descripcion: Optional[str] = None
    area: Optional[str] = None
    tipo_mueble: Optional[str] = None
    status: str
    fecha_procesando: Optional[str] = None
    fecha_procesado: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    deleted_at: Optional[str] = None


class EnvioSyncOut(BaseModel):
    local_id: Union[int, str]
    factura_id: Union[int, str]
    estado: str = "Pendiente"
    direccion_entrega: Optional[str] = None
    fecha_programada: Optional[str] = None
    fecha_enviado: Optional[str] = None
    fecha_entregado: Optional[str] = None
    notas: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    deleted_at: Optional[str] = None


class PagoSyncOut(BaseModel):
    local_id: Union[int, str]
    factura_id: Union[int, str]
    monto: float
    metodo: Optional[str] = None
    nota: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    deleted_at: Optional[str] = None


class ColaTrabajosSyncOut(BaseModel):
    local_id: Union[int, str]
    factura_id: Union[int, str]
    item_id: Union[int, str]
    status: str = "pendiente"
    area: str
    prioridad: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    deleted_at: Optional[str] = None


class ConfiguracionSyncOut(BaseModel):
    local_id: Union[int, str]
    clave: str
    valor: Any
    updated_at: Optional[str] = None
    deleted_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Finanzas, Nóminas y Gastos
# ---------------------------------------------------------------------------

class EmpleadoBase(BaseModel):
    nombre: str
    telefono: Optional[str] = None
    telefono_familiar: Optional[str] = None
    rol: Optional[str] = None
    salario_fijo: float = 0
    gana_comision: bool = False
    dia_cobro: Optional[int] = None

class EmpleadoIn(EmpleadoBase):
    pass

class EmpleadoOut(EmpleadoBase):
    id: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

class ComisionEmpleadoBase(BaseModel):
    catalogo_id: str
    monto: float

class ComisionEmpleadoIn(ComisionEmpleadoBase):
    pass

class ComisionEmpleadoOut(ComisionEmpleadoBase):
    id: str
    empleado_id: str

class GastoPerfilBase(BaseModel):
    nombre: str
    tipo: str
    dia_pago: Optional[int] = None

class GastoPerfilIn(GastoPerfilBase):
    pass

class GastoPerfilOut(GastoPerfilBase):
    id: str
    created_at: Optional[str] = None

class GastoRegistroBase(BaseModel):
    perfil_id: str
    monto: float
    fecha: str
    nota: Optional[str] = None

class GastoRegistroIn(GastoRegistroBase):
    pass

class GastoRegistroOut(GastoRegistroBase):
    id: str
    created_at: Optional[str] = None

class DashboardMetricsOut(BaseModel):
    ingresos_facturas: float
    gastos_operativos: float
    nomina_sueldos_fijos: float
    nomina_comisiones: float
    ganancia_neta: float
    items_procesados: int
    top_muebles: List[dict]
    top_areas: List[dict]
