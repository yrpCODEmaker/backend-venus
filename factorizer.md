# 🛠️ Plan de Refactorización Integral del Backend (factorizer.md)

Este documento presenta una auditoría técnica profunda y exhaustiva del proyecto `backend_venus`. Identifica los cuellos de botella arquitectónicos, la deuda técnica acumulada, las violaciones de principios de diseño (SRP, DRY, Clean Architecture) y detalla **qué partes necesitan ser refactorizadas, por qué y cómo abordarlas** sin romper la simplicidad ni la compatibilidad con los clientes desktop (Flet) y web.

---

## 📊 1. Diagnóstico General del Código

| Métrica / Aspecto | Estado Actual | Evaluación |
| :--- | :---: | :--- |
| **Líneas Totales de Código Python** | **6,985 líneas** | Tamaño medio-pequeño, pero altamente concentrado en pocos archivos gigantes. |
| **Archivo más grande (`routers/operacional.py`)** | **1,794 líneas** | 🚨 **Monolítico**: Acumula más del 25% de todo el backend. |
| **Segundo archivo más grande (`schemas.py`)** | **843 líneas** | ⚠️ **Monolítico**: Más de 45 modelos Pydantic mezclados sin separación de dominio. |
| **Tercer archivo más grande (`services/factura_service.py`)** | **741 líneas** | ⚠️ **Complejo**: Lógica transaccional pesada con mezcla de validación y SQL directo. |
| **Número de Módulos / Routers** | 7 routers, 5 services | Buena intención de capas, pero con responsabilidades desbalanceadas. |

---

## 🎯 2. Partes que Necesitan Refactorización y Justificación

---

### 🔴 PRIORIDAD ALTA (Impacto Crítico en Mantenibilidad y Escalabilidad)

#### 1. Descomposición del Monolito `routers/operacional.py` (1,794 líneas)
* **Ubicación:** [`routers/operacional.py`](file:///home/thatdev/Documentos/venus/backend-venus/routers/operacional.py)
* **Problema:** 
  Este archivo contiene más de 30 endpoints de al menos **8 dominios de negocio completamente distintos**:
  1. Facturas (creación, edición, listado, reportes, perdón de deuda, declaración de pérdida).
  2. Ítems y Producción Kanban (cambio de estados, fotos de referencia, imágenes de apoyo, asignaciones).
  3. Clientes (CRUD y soft delete).
  4. Catálogo de productos (CRUD, variantes y soft delete).
  5. Stock e Inventario (CRUD, ajustes de cantidad `delta`).
  6. Envíos y Despachos (estados, reprogramación, garantías).
  7. Pagos y Abonos (registro y balance financiero).
  8. Configuración, Empresa, Materiales y Descarga de Facturas (PDF/PNG).
* **Por qué refactorizar:**
  - **Violación del Principio de Responsabilidad Única (SRP):** Cualquier cambio en el inventario o clientes obliga a tocar el mismo archivo donde residen las facturas y la generación de PDFs.
  - **Dificultad de Pruebas y Revisión de Código:** Genera conflictos de merge constantes y dificulta localizar errores puntuales.
  - **Sobrecarga de Imports y Dependencias:** Mezcla dependencias de PDFs, hashing, utilidades de imagen y base de datos en un solo módulo.
* **Propuesta de Refactorización:**
  Dividir en submódulos especializados dentro del paquete `routers/`:
  - `routers/facturas.py`: Gestión de facturas, balances y reportes.
  - `routers/items.py`: Tableros Kanban de producción, estados de ítems y fotos.
  - `routers/clientes.py`: CRUD y búsqueda de clientes.
  - `routers/catalogo.py` y `routers/stock.py`: Gestión de catálogo y stock.
  - `routers/envios_pagos.py`: Despachos, entregas y cobros.
  - `routers/configuracion.py`: Configuración global, empresa y catálogos de materiales.
  - `routers/invoices_export.py`: Endpoints de descarga PDF y PNG.

---

#### 2. Modularización del Archivo `schemas.py` (843 líneas)
* **Ubicación:** [`schemas.py`](file:///home/thatdev/Documentos/venus/backend-venus/schemas.py)
* **Problema:** 
  Contiene más de 45 modelos Pydantic en un solo archivo plano. Se mezclan:
  - Modelos de Autenticación y 2FA (`UserCreateIn`, `TokenOut`, `TOTPSetupOut`).
  - Modelos de Sincronización Desktop (`SyncPayloadIn`, `SyncPushResponse`).
  - Modelos Operacionales y CRUD (`FacturaCreateIn`, `StockUpdateIn`, `ClienteOut`).
  - Modelos de Nóminas y Finanzas (`EmpleadoIn`, `GastoRegistroIn`).
  - Modelos de Materiales y Configuración (`EmpresaConfigIn`, `MaterialOut`).
* **Por qué refactorizar:**
  - Crecimiento desordenado: Se hace difícil saber si ya existe un schema de entrada o salida para una entidad.
  - Inconsistencias de tipado: Algunos campos usan `Union[List[str], str]`, otros `Optional[str]`, y otros validadores ad-hoc repetidos (`@model_validator`).
* **Propuesta de Refactorización:**
  Convertir `schemas.py` en un paquete `schemas/`:
  ```text
  schemas/
  ├── __init__.py        # Re-exporta todos los modelos (compatibilidad 100% hacia atrás)
  ├── auth.py            # Tokens, usuarios, 2FA, permisos
  ├── facturas.py        # Facturas, ítems, pagos, envíos
  ├── inventario.py      # Catálogo, stock, imágenes, materiales
  ├── clientes.py        # Clientes y direcciones
  ├── sync.py            # Payloads de sincronización Push/Pull
  └── finanzas.py        # Nóminas, gastos y comisiones
  ```

---

#### 3. Reducción de Boilerplate SQL y Extracción de Repositorios / Helpers de DB
* **Ubicación:** [`routers/operacional.py`](file:///home/thatdev/Documentos/venus/backend-venus/routers/operacional.py), [`routers/admin.py`](file:///home/thatdev/Documentos/venus/backend-venus/routers/admin.py), [`services/factura_service.py`](file:///home/thatdev/Documentos/venus/backend-venus/services/factura_service.py)
* **Problema:**
  En casi todos los endpoints se repiten bloques idénticos de 10 a 20 líneas para:
  - Mapear cursores SQLite a diccionarios: `cols = [d[0] for d in cursor.description]; row_dict = dict(zip(cols, r))`.
  - Parsear JSON embebido con bloques `try...except json.loads`.
  - Construir cláusulas dinámicas de filtrado por fecha, búsqueda y paginación.
* **Por qué refactorizar:**
  - Código duplicado (~400 líneas de puro código repetitivo).
  - Fragilidad: Si se agrega una columna o se cambia el formato de serialización, hay que editar decenas de endpoints manualmente.
* **Propuesta de Refactorización:**
  Crear utilidades ligeras en `services/db_utils.py` o en `database.py`:
  - `fetch_one_dict(cursor)` y `fetch_all_dict(cursor)`.
  - `parse_json_fields(data_dict, ["colores", "imagenes_apoyo", "area"])`.
  - `paginate_query(base_query, limit, offset, order_by)`.

---

### 🟡 PRIORIDAD MEDIA (Robustez, Resiliencia y Consistencia)

#### 4. Rutas y Lógica Embebidas en `main.py`
* **Ubicación:** [`main.py`](file:///home/thatdev/Documentos/venus/backend-venus/main.py#L230-L286)
* **Problema:**
  En `main.py` existe una ruta directa `GET /api/v1/sync/image/{image_id}` con lógica completa de autenticación JWT manual, consulta SQL a `images` y resolución de archivos en disco, saltándose los routers.
* **Por qué refactorizar:**
  - `main.py` debe ser únicamente el punto de entrada, configuración de middleware, lifespan e inclusión de routers.
  - Genera duplicación de lógica con [`routers/sync.py`](file:///home/thatdev/Documentos/venus/backend-venus/routers/sync.py) y [`services/image_service.py`](file:///home/thatdev/Documentos/venus/backend-venus/services/image_service.py).
* **Propuesta de Refactorización:**
  Mover el endpoint a `routers/sync.py` (o `routers/images.py`) y reutilizar `services/image_service.py`.

---

#### 5. Resiliencia de Tareas en Segundo Plano (`_warranty_cron` en `main.py`)
* **Ubicación:** [`main.py`](file:///home/thatdev/Documentos/venus/backend-venus/main.py#L48-L56)
* **Problema:**
  El cron de expiración de garantías se ejecuta con un bucle `while True` y `asyncio.sleep(86400)` dentro de la tarea del lifespan.
* **Por qué refactorizar:**
  - Si ocurre un fallo no capturado o un bloqueo de conexión en SQLite durante el ciclo, la tarea puede morir silenciosamente sin que FastAPI lo note, dejando de verificar garantías indefinidamente.
  - Al reiniciar el servidor se verifica de inmediato, pero no tiene registro de métricas de ejecución.
* **Propuesta de Refactorización:**
  - Implementar un runner con manejo de excepciones global, backoff exponencial ante fallos de conexión e intervalo configurable.

---

#### 6. Estandarización de Transacciones ACID
* **Ubicación:** [`routers/operacional.py`](file:///home/thatdev/Documentos/venus/backend-venus/routers/operacional.py) vs [`services/factura_service.py`](file:///home/thatdev/Documentos/venus/backend-venus/services/factura_service.py)
* **Problema:**
  - `factura_service.py` maneja transacciones explícitas con `BEGIN TRANSACTION` y `ROLLBACK`.
  - Varios endpoints en `routers/operacional.py` (ej. borrado de catálogo con sus variantes o actualización múltiple de stock) ejecutan múltiples sentencias `await db.execute(...)` seguidas de `await db.commit()` sin un bloque `try...except db.rollback()`.
* **Por qué refactorizar:**
  - Si una operación intermedia falla (por ejemplo, violación de FK o error de I/O), la base de datos puede quedar en un estado inconsistente parcial.
* **Propuesta de Refactorización:**
  Crear un context manager asíncrono `async with transaction(db):` que garantice `rollback()` automático en caso de cualquier excepción.

---

#### 7. Unificación de la Estrategia de Prefijos e IDs
* **Ubicación:** [`services/sync.py`](file:///home/thatdev/Documentos/venus/backend-venus/services/sync.py), [`services/factura_service.py`](file:///home/thatdev/Documentos/venus/backend-venus/services/factura_service.py#L40-L55), [`database.py`](file:///home/thatdev/Documentos/venus/backend-venus/database.py#L296-L350)
* **Problema:**
  La lógica para parsear prefijos con guion (`"P-1"`, `"y-ye897e4b"`) y compatibilidad histórica sin guion (`"P1"`) se encuentra duplicada en 3 lugares con implementaciones ligeramente diferentes (regex, `lstrip`, `split("-", 1)`).
* **Por qué refactorizar:**
  - Si se añade un nuevo formato de ID o se modifica el comportamiento de los prefijos, hay riesgo de inconsistencias entre la sincronización y las operaciones REST.
* **Propuesta de Refactorización:**
  Centralizar todas las funciones de parsing, normalización y generación de candidatos de IDs en métodos estáticos de `PrefixTransformer` (en `services/sync.py`).

---

### 🟢 PRIORIDAD BAJA (Buenas Prácticas y Limpieza de Código)

#### 8. Centralización de Fechas y Eliminación de `datetime.utcnow()`
* **Problema:** 
  `_now_iso()` está definido de forma idéntica en múltiples archivos (`factura_service.py`, `operacional.py`, `sync.py`). Además, en algunas consultas SQL se usa `datetime('now')` y en Python `datetime.now(timezone.utc)`.
* **Propuesta:** 
  Crear `utils/dates.py` con funciones estándar como `now_iso()`, `today_str()` y parseadores tolerantes a fallos.

#### 9. Limpieza de Migraciones Inline en `database.py`
* **Ubicación:** [`database.py`](file:///home/thatdev/Documentos/venus/backend-venus/database.py#L367-L396)
* **Problema:**
  `init_db()` contiene 8 bloques `try...except: pass` para hacer `ALTER TABLE ADD COLUMN`. 
* **Propuesta:**
  Empaquetar las migraciones incrementales en una lista de scripts versionados o una función de migración estructurada para mantener `init_db()` limpio y legible.

---

## 🗺️ 3. Plan de Ejecución Recomendado (Paso a Paso)

Para realizar esta refactorización sin interrumpir el funcionamiento ni romper los clientes existentes:

```text
Fase 1: Modularización de Schemas
  └─ Crear paquete schemas/ con submódulos y __init__.py retrocompatible.

Fase 2: Extracción de Helpers de Acceso a Datos
  └─ Crear db_utils.py (fetch_dict, parsing JSON, context manager de transacciones).

Fase 3: Descomposición de routers/operacional.py
  ├─ 3.1: Extraer routers/facturas.py y routers/items.py
  ├─ 3.2: Extraer routers/clientes.py y routers/inventario.py (catalogo/stock)
  ├─ 3.3: Extraer routers/configuracion.py y routers/envios_pagos.py
  └─ 3.4: Re-exportar o registrar en main.py sin alterar prefijos ni URLs.

Fase 4: Limpieza de main.py e IDs
  ├─ Mover ruta de imágenes de main.py a su router correspondiente.
  └─ Unificar generador de IDs en PrefixTransformer.

Fase 5: Verificación de Suite de Tests
  └─ Ejecutar suite completa (pytest) garantizando 100% de tests aprobados.
```

---

## 💡 4. Conclusión

El backend `backend_venus` tiene una **base técnica sólida, rápida y bien orientada** (FastAPI + aiosqlite en WAL mode, sin ORM pesado). Sin embargo, el crecimiento de funcionalidades ha concentrado demasiada lógica en `routers/operacional.py` y `schemas.py`. 

La refactorización propuesta **no requiere cambiar de tecnologías ni modificar la API pública**: consiste en redistribuir el código por dominios limpios, eliminar boilerplate repetitivo y asegurar la consistencia transaccional del sistema.
