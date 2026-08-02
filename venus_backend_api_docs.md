# Venus Backend — Documentación de API REST

API REST de sincronización y gestión de datos para el sistema Venus (Fábrica de Muebles — Ebanistería y Tapicería). Soporta respaldo remoto, sincronización multi-dispositivo offline-first y gestión de usuarios multi-inquilino.

**Versión:** 0.1.0 (OpenAPI 3.1)  
**Base URL:** `http://localhost:8000` (o IP del servidor de despliegue)  
**Autenticación:** JWT Bearer (`Authorization: Bearer <token>`)

---

## Índice de Módulos

1. [Sistema](#1-sistema)
2. [Autenticación](#2-autenticación)
3. [Administración](#3-administración)
4. [Sincronización Desktop](#4-sincronización-desktop)
5. [Operacional](#5-operacional)
   - [Facturas](#-facturas)
   - [Ítems (Producción / Kanban)](#-ítems-producción--kanban)
   - [Pagos / Abonos](#-pagos--abonos)
   - [Envíos](#-envíos)
   - [Clientes](#-clientes)
   - [Catálogo](#-catálogo)
   - [Stock (Inventario)](#-stock-inventario)
   - [Configuración](#-configuración)

---

## 1. Sistema

### `GET /health`
* **Nombre:** Health Check
* **Descripción:** Verifica que el servidor backend esté activo y respondiendo solicitudes.
* **Autenticación:** No requerida.
* **Respuesta 200 OK:**
  ```json
  {
    "status": "ok",
    "service": "venus-backend"
  }
  ```

---

## 2. Autenticación

### `POST /api/v1/auth/login`
* **Nombre:** Login de Usuario
* **Descripción:** Autentica un usuario con su `username` y `password`, retornando un Token JWT de acceso (Bearer).
* **Autenticación:** No requerida.
* **Request Body:** `application/x-www-form-urlencoded` (estándar OAuth2)
  * `username` (string, requerido)
  * `password` (string, requerido)
* **Respuesta 200 OK:**
  ```json
  {
    "access_token": "eyJhbGci...",
    "token_type": "bearer",
    "expires_in": 86400
  }
  ```
* **Errores:**
  * `401 Unauthorized`: Credenciales inválidas.
  * `403 Forbidden`: Usuario desactivado.

### `GET /api/v1/auth/me`
* **Nombre:** Perfil de Usuario Autenticado
* **Descripción:** Retorna la información, rol y prefijo asignado al usuario actualmente autenticado mediante su token JWT.
* **Autenticación:** Requerida (Bearer Token).
* **Respuesta 200 OK:**
  ```json
  {
    "username": "pichardo",
    "rol": "admin",
    "prefix": "P",
    "activo": true
  }
  ```
* **Errores:**
  * `401 Unauthorized`: Token inválido o expirado.

---

## 3. Administración

> **Nota:** Todos los endpoints de administración son de uso exclusivo para el usuario administrador (`pichardo`, rol: `admin`).
>
> **Estado de la sección:** Incluye endpoints actuales y una especificación **planificada** para la siguiente iteración de gestión avanzada de usuarios/permisos.

### `GET /api/v1/admin/users`
* **Nombre:** Listar Usuarios
* **Descripción:** Retorna el listado completo de usuarios registrados en la base de datos central.
* **Autenticación:** Requerida (Solo Admin).
* **Respuesta 200 OK:**
  ```json
  [
    {
      "username": "laura",
      "rol": "user",
      "prefix": "L",
      "activo": true
    }
  ]
  ```

### `POST /api/v1/admin/users`
* **Nombre:** Crear Usuario
* **Descripción:** Crea un nuevo usuario regular asignándole su prefijo único de multi-inquilino.
* **Autenticación:** Requerida (Solo Admin).
* **Request Body:** `application/json` (`UserCreateIn`)
  ```json
  {
    "username": "carlos",
    "password": "secreto123",
    "prefix": "C"
  }
  ```
* **Respuesta 201 Created:** Retorna `UserOut`.
* **Errores:**
  * `409 Conflict`: Si el `username` o el `prefix` ya están registrados.

### `PATCH /api/v1/admin/users/{username}/toggle`
* **Nombre:** Activar / Desactivar Usuario
* **Descripción:** Alterna el estado activo/inactivo de una cuenta de usuario. El administrador no puede desactivar su propia cuenta.
* **Autenticación:** Requerida (Solo Admin).
* **Parámetros:**
  * `username` (path, string, requerido): Nombre del usuario a modificar.
* **Respuesta 200 OK:** Retorna `UserOut` con el nuevo estado.
* **Errores:**
  * `400 Bad Request`: Si el admin intenta desactivar su propio usuario.
  * `404 Not Found`: Usuario no encontrado.

### `PUT /api/v1/admin/users/{username}` *(Planificado)*
* **Nombre:** Modificar Usuario y Permisos
* **Descripción:** Permite al administrador actualizar datos de cuenta (usuario activo, rol) y el mapa de permisos funcionales del usuario.
* **Autenticación:** Requerida (Solo Admin).
* **Parámetros:**
  * `username` (path, string, requerido): Nombre del usuario a modificar.
* **Request Body:** `application/json`
  ```json
  {
    "activo": true,
    "rol": "user",
    "permisos": {
      "facturas": {
        "ver": true,
        "emitir": true,
        "modificar": false
      },
      "fabricacion": {
        "ver_estados": true,
        "modificar_estados": false,
        "mandar_envio": false
      },
      "stock": {
        "crear": true,
        "modificar": true,
        "eliminar": false
      },
      "catalogo": {
        "crear": true,
        "modificar": true,
        "eliminar": false
      },
      "clientes": {
        "crear": true,
        "modificar": true,
        "eliminar": false
      },
      "usuarios": {
        "puede_ver_datos_de_otros": false,
        "prefijos_visibles": ["L", "M"]
      }
    }
  }
  ```
* **Respuesta 200 OK:** Estado actualizado del usuario con su objeto de permisos.
* **Errores:**
  * `400 Bad Request`: Payload inválido o reglas de seguridad violadas.
  * `404 Not Found`: Usuario no encontrado.

### `DELETE /api/v1/admin/users/{username}` *(Planificado)*
* **Nombre:** Eliminar Usuario
* **Descripción:** Elimina una cuenta de usuario administrada por el admin. Debe protegerse la eliminación del usuario administrador principal.
* **Autenticación:** Requerida (Solo Admin).
* **Parámetros:**
  * `username` (path, string, requerido): Usuario a eliminar.
* **Respuesta 204 No Content**
* **Errores:**
  * `400 Bad Request`: Si se intenta eliminar al admin principal.
  * `404 Not Found`: Usuario no encontrado.

### `GET /api/v1/admin/users/{username}/permissions` *(Planificado)*
* **Nombre:** Consultar Permisos de Usuario
* **Descripción:** Devuelve el detalle completo de permisos funcionales y alcance de visibilidad de datos para un usuario.
* **Autenticación:** Requerida (Solo Admin).
* **Parámetros:**
  * `username` (path, string, requerido): Usuario objetivo.
* **Respuesta 200 OK:** Objeto `permisos` por módulo (`facturas`, `fabricacion`, `stock`, `catalogo`, `clientes`, `usuarios`).
* **Errores:**
  * `404 Not Found`: Usuario no encontrado.

### `PUT /api/v1/admin/users/{username}/permissions` *(Planificado)*
* **Nombre:** Reemplazar Permisos de Usuario
* **Descripción:** Reemplaza de forma total el conjunto de permisos del usuario para mantener consistencia y auditoría.
* **Autenticación:** Requerida (Solo Admin).
* **Parámetros:**
  * `username` (path, string, requerido): Usuario objetivo.
* **Request Body:** `application/json` con el objeto `permisos`.
* **Respuesta 200 OK:** Permisos actualizados.
* **Errores:**
  * `400 Bad Request`: Estructura de permisos inválida.
  * `404 Not Found`: Usuario no encontrado.

### `PATCH /api/v1/admin/users/{username}/data-visibility` *(Planificado)*
* **Nombre:** Ajustar Visibilidad de Datos Entre Usuarios
* **Descripción:** Define qué prefijos de otros usuarios puede consultar el usuario objetivo para lectura de información cruzada.
* **Autenticación:** Requerida (Solo Admin).
* **Parámetros:**
  * `username` (path, string, requerido): Usuario objetivo.
* **Request Body:** `application/json`
  ```json
  {
    "puede_ver_datos_de_otros": true,
    "prefijos_visibles": ["L", "M", "R"]
  }
  ```
* **Respuesta 200 OK:** Configuración de visibilidad actualizada.
* **Errores:**
  * `400 Bad Request`: Prefijos inválidos o inconsistencia en reglas de visibilidad.
  * `404 Not Found`: Usuario no encontrado.

---

## 4. Sincronización Desktop

> **Nota:** Endpoints para clientes locales (Flet / Desktop). Los usuarios con rol `admin` reciben `403 Forbidden` al intentar sincronizar.

### `POST /api/v1/sync/push`
* **Nombre:** Subida Masiva de Cambios (Push)
* **Descripción:** Recibe el payload con los cambios locales generados en SQLite local. Aplica la transformación de IDs enteros a IDs prefijados (`PrefixTransformer`) y ejecuta UPSERTs con resolución de conflictos **Last-Write-Wins (LWW)** basándose en `updated_at`.
* **Autenticación:** Requerida (Usuario regular con prefijo).
* **Request Body:** `application/json` (`PushSyncPayload`)
  ```json
  {
    "clientes": [],
    "images": [],
    "catalogo": [],
    "stock": [],
    "facturas": [],
    "pagos": [],
    "items": [],
    "envios": [],
    "cola_trabajos": [],
    "configuracion": []
  }
  ```
* **Respuesta 200 OK:**
  ```json
  {
    "status": "ok",
    "upserted": {
      "clientes": 2,
      "facturas": 1,
      "items": 3
    }
  }
  ```

### `GET /api/v1/sync/pull`
* **Nombre:** Descarga Delta de Cambios (Pull)
* **Descripción:** Devuelve todos los registros modificados o creados después de la fecha `last_sync`. Los IDs en la respuesta vienen des-prefijados (convertidos a enteros) para permitir un UPSERT directo en la base de datos SQLite local del cliente.
* **Autenticación:** Requerida (Usuario regular con prefijo).
* **Parámetros:**
  * `last_sync` (query, string ISO 8601, opcional): Ej: `2026-07-15T00:00:00Z`. Si se omite, retorna todo el historial del usuario.
* **Respuesta 200 OK:** Objeto JSON con colecciones de entidades des-prefijadas (`clientes`, `images`, `catalogo`, `stock`, `facturas`, `pagos`, `items`, `envios`, `cola_trabajos`, `configuracion`).

### `POST /api/v1/sync/upload_image`
* **Nombre:** Subir Imagen Física
* **Descripción:** Recibe el archivo de imagen física desde la aplicación desktop, lo almacena en disco bajo `/uploads/{prefix}/` y vincula la ruta remota en la tabla `images` usando el `local_image_id`.
* **Autenticación:** Requerida (Usuario regular con prefijo).
* **Request Body:** `multipart/form-data`
  * `local_image_id` (integer, Form, requerido): ID entero local de la imagen.
  * `file` (UploadFile / Binary, File, requerido): Archivo de la imagen.
* **Respuesta 200 OK:**
  ```json
  {
    "remote_path": "/uploads/L/10_a1b2c3d4.jpg",
    "local_image_id": 10
  }
  ```

### `GET /api/v1/sync/image/{local_image_id}`
* **Nombre:** Descargar Imagen Física
* **Descripción:** Transmite el archivo binario de la imagen remota correspondiente al `local_image_id` del usuario autenticado.
* **Autenticación:** Requerida (Usuario regular con prefijo).
* **Parámetros:**
  * `local_image_id` (path, integer, requerido): ID local de la imagen.
* **Respuesta 200 OK:** Flujo binario de archivo (`FileResponse`).
* **Errores:**
  * `404 Not Found`: Si la imagen o el archivo físico no existen en el servidor.

---

## 5. Operacional

### 🧾 Facturas

#### `GET /api/v1/facturas`
* **Nombre:** Listar Facturas
* **Descripción:** Retorna el listado de facturas perteneciente al usuario autenticado de forma paginada y filtrada.
* **Autenticación:** Requerida.
* **Parámetros:**
  * `search` (query, string, opcional): Filtra por ID de factura o por nombre/apellido del cliente.
  * `start_date` (query, string, opcional): Fecha mínima ISO.
  * `end_date` (query, string, opcional): Fecha máxima ISO.
  * `limit` (query, integer, opcional, por defecto: `50`): Límite de registros.
  * `offset` (query, integer, opcional, por defecto: `0`): Paginación.
* **Respuesta 200 OK:** Lista de facturas (`list[dict]`).

#### `POST /api/v1/facturas`
* **Nombre:** Crear Factura Transaccional
* **Descripción:** Crea una factura mediante una transacción ACID completa (valida cliente, crea factura, crea ítems, descuenta stock de ítems stock, registra abono inicial opcional, inserta en cola de trabajos y crea registro de envío si aplica domicilio).
* **Autenticación:** Requerida.
* **Request Body:** `application/json` (`FacturaCreateIn`)
  ```json
  {
    "cliente_id": "L1",
    "total": 35000.0,
    "monto_pagado": 10000.0,
    "entrega_domicilio": true,
    "direccion_entrega": "Av. Central #12",
    "garantia_hasta": "6 Meses",
    "items": [
      {
        "stock_id": "L1",
        "catalogo_id": "L1",
        "nombre": "Sofá 3 Plazas",
        "cantidad": 1,
        "tipo": "stock",
        "subtotal": 35000.0,
        "color": "Gris",
        "material": "Terciopelo"
      }
    ]
  }
  ```
* **Respuesta 201 Created:** Confirmación con el ID de la factura creada y resumen transaccional.
  ```json
  {
    "id": "LRa1b2c3d4",
    "factura_id": "LRa1b2c3d4",
    "cliente_id": "L1",
    "total": 35000.0,
    "monto_pagado": 10000.0,
    "saldo_pendiente": 25000.0,
    "items_count": 1,
    "items_id": "LRe5f6g7h8",
    "pago_id": "LRp9i0j1k2"
  }
  ```
* **Errores:**
  * `403 Forbidden`: Los usuarios admin sin prefijo no pueden crear facturas directamente.
  * `409 Conflict`: Stock insuficiente para ítems tipo stock.

#### `GET /api/v1/facturas/{factura_id}`
* **Nombre:** Detalle de Factura
* **Descripción:** Obtiene los datos completos de una factura específica, incluyendo sus arreglos de `items` y de `pagos`.
* **Autenticación:** Requerida.
* **Parámetros:**
  * `factura_id` (path, string, requerido): ID de la factura.
* **Respuesta 200 OK:** Objeto con la factura, `items: []` y `pagos: []`.
* **Errores:**
  * `404 Not Found`: Factura no encontrada.

#### `PATCH /api/v1/facturas/{factura_id}`
* **Nombre:** Actualizar Factura
* **Descripción:** Modifica de forma parcial campos específicos de una factura (`cliente_id`, `direccion_entrega`, `garantia_hasta`, `estatus_entrega`).
* **Autenticación:** Requerida.
* **Parámetros:**
  * `factura_id` (path, string, requerido): ID de la factura.
* **Request Body:** `application/json` (`FacturaUpdateIn`)
* **Respuesta 200 OK:** `{"status": "updated", "factura_id": "..."}`
* **Errores:**
  * `400 Bad Request`: Si no se especifica ningún campo a actualizar.
  * `404 Not Found`: Factura no encontrada.

#### `DELETE /api/v1/facturas/{factura_id}`
* **Nombre:** Eliminar Factura
* **Descripción:** Elimina una factura en cascada (*hard delete*) y reintegra automáticamente la cantidad de stock a los ítems asociados que fueron de tipo `stock`.
* **Autenticación:** Requerida.
* **Parámetros:**
  * `factura_id` (path, string, requerido): ID de la factura.
* **Respuesta 204 No Content**

#### `POST /api/v1/facturas/{factura_id}/dispatch`
* **Nombre:** Despacho Masivo de Factura
* **Descripción:** Transiciona todos los ítems asociados a la factura al estado `completado` y gestiona automáticamente el estado de su envío.
* **Autenticación:** Requerida.
* **Parámetros:**
  * `factura_id` (path, string, requerido): ID de la factura.
* **Respuesta 200 OK:** Resumen del despacho.

---

### 🔨 Ítems (Producción / Kanban)

#### `GET /api/v1/items`
* **Nombre:** Listar Ítems
* **Descripción:** Retorna los ítems de fabricación para visualización en los tableros Kanban de producción.
* **Autenticación:** Requerida.
* **Parámetros:**
  * `status` (query, string, opcional): `'pendiente'`, `'procesando'`, `'procesado'`, `'completado'`.
  * `area` (query, string, opcional): `'Tapicería'`, `'Ebanistería'`, `'Metales'`, etc.
  * `tipo` (query, string, opcional): `'encargo'` o `'stock'`.
  * `limit` (query, integer, opcional, por defecto: `50`).
  * `offset` (query, integer, opcional, por defecto: `0`).
* **Respuesta 200 OK:** Lista de ítems (`list[dict]`).

#### `POST /api/v1/facturas/{factura_id}/items`
* **Nombre:** Agregar Ítem a Factura
* **Descripción:** Agrega un nuevo ítem a una factura existente.
* **Autenticación:** Requerida.
* **Parámetros:**
  * `factura_id` (path, string, requerido): ID de la factura.
* **Request Body:** `application/json` (`ItemAddIn`)
  ```json
  {
    "nombre": "Mesa Auxiliar",
    "cantidad": 1,
    "tipo": "encargo",
    "subtotal": 5000.0,
    "area": "Ebanistería",
    "tipo_mueble": "Mesa"
  }
  ```
* **Respuesta 201 Created:** `{"item_id": "...", "factura_id": "..."}`
* **Errores:**
  * `404 Not Found`: Factura no encontrada.

#### `PATCH /api/v1/items/{item_id}`
* **Nombre:** Modificar Ítem
* **Descripción:** Actualiza las especificaciones técnicas o precio de un ítem (`color`, `material`, `descripcion`, `subtotal`).
* **Autenticación:** Requerida.
* **Parámetros:**
  * `item_id` (path, string, requerido): ID del ítem.
* **Request Body:** `application/json` (`ItemUpdateIn`)
* **Respuesta 200 OK:** `{"status": "updated", "item_id": "..."}`

#### `PATCH /api/v1/items/{item_id}/status`
* **Nombre:** Transición de Estado de Ítem
* **Descripción:** Cambia el estado en el flujo Kanban (`pendiente` → `procesando` → `procesado` → `completado`). Si la factura no requiere envío a domicilio, al llegar a `procesado` transiciona automáticamente a `completado` (*bypass*).
* **Autenticación:** Requerida.
* **Parámetros:**
  * `item_id` (path, string, requerido): ID del ítem.
* **Request Body:** `application/json` (`ItemStatusUpdate`)
  ```json
  {
    "status": "procesando"
  }
  ```
* **Respuesta 200 OK:** Estado actualizado del ítem.

#### `PATCH /api/v1/items/{item_id}/photo`
* **Nombre:** Foto de Referencia de Ítem
* **Descripción:** Actualiza el `image_id` asignado a un ítem.
* **Autenticación:** Requerida.
* **Parámetros:**
  * `item_id` (path, string, requerido): ID del ítem.
  * `factura_id` (query, string, requerido): ID de la factura contenedora.
* **Request Body:** `application/json` (`ItemPhotoUpdate`)
  ```json
  {
    "image_id": "LRe5f6g7h8"
  }
  ```
* **Respuesta 200 OK:** `{"status": "updated", "item_id": "..."}`

#### `DELETE /api/v1/items/{item_id}`
* **Nombre:** Eliminar Ítem
* **Descripción:** Elimina el ítem de la factura y reintegra la cantidad al stock si el ítem era de tipo `'stock'`.
* **Autenticación:** Requerida.
* **Parámetros:**
  * `item_id` (path, string, requerido): ID del ítem.
* **Respuesta 204 No Content**

---

### 💳 Pagos / Abonos

#### `POST /api/v1/facturas/{factura_id}/pagos`
* **Nombre:** Registrar Abono
* **Descripción:** Registra un pago o abono a una factura, reduciendo automáticamente su `saldo_pendiente`.
* **Autenticación:** Requerida.
* **Parámetros:**
  * `factura_id` (path, string, requerido): ID de la factura.
* **Request Body:** `application/json` (`PagoCreateIn`)
  ```json
  {
    "monto": 5000.0,
    "nota": "Abono vía transferencia"
  }
  ```
* **Respuesta 201 Created:**
  ```json
  {
    "pago_id": "LRp12345",
    "monto": 5000.0,
    "saldo_restante": 10000.0
  }
  ```
* **Errores:**
  * `400 Bad Request`: Si el monto excede el saldo pendiente.
  * `404 Not Found`: Factura no encontrada.

#### `GET /api/v1/facturas/{factura_id}/pagos`
* **Nombre:** Listar Abonos
* **Descripción:** Retorna el historial de todos los pagos registrados a una factura.
* **Autenticación:** Requerida.
* **Parámetros:**
  * `factura_id` (path, string, requerido): ID de la factura.
* **Respuesta 200 OK:** Lista de pagos (`list[dict]`).

---

### 🚚 Envíos

#### `GET /api/v1/envios`
* **Nombre:** Listar Envíos
* **Descripción:** Obtiene los registros de entregas a domicilio filtrados por estado.
* **Autenticación:** Requerida.
* **Parámetros:**
  * `estado` (query, string, opcional): `'Pendiente de Envío'`, `'En Ruta'`, `'Entregado'`.
  * `limit` (query, integer, opcional, por defecto: `50`).
  * `offset` (query, integer, opcional, por defecto: `0`).
* **Respuesta 200 OK:** Lista de envíos (`list[dict]`).

#### `PATCH /api/v1/envios/{envio_id}/status`
* **Nombre:** Estado de Envío
* **Descripción:** Actualiza el estado logístico del envío. Al cambiar a `'Entregado'`, calcula y activa automáticamente la fecha de vencimiento de la garantía en la factura asociada.
* **Autenticación:** Requerida.
* **Parámetros:**
  * `envio_id` (path, string, requerido): ID del envío.
* **Request Body:** `application/json` (`EnvioStatusUpdate`)
  ```json
  {
    "estado": "Entregado"
  }
  ```
* **Respuesta 200 OK:** Estado actualizado del envío.

#### `PATCH /api/v1/envios/{envio_id}`
* **Nombre:** Modificar Envío
* **Descripción:** Modifica los detalles logísticos de una entrega (`direccion_entrega`, `fecha_programada`, `notas`).
* **Autenticación:** Requerida.
* **Parámetros:**
  * `envio_id` (path, string, requerido): ID del envío.
* **Request Body:** `application/json` (`EnvioUpdateIn`)
* **Respuesta 200 OK:** `{"status": "updated", "envio_id": "..."}`

---

### 👥 Clientes

#### `GET /api/v1/clientes`
* **Nombre:** Listar Clientes
* **Descripción:** Obtiene el listado de clientes activos (no eliminados).
* **Autenticación:** Requerida.
* **Parámetros:**
  * `search` (query, string, opcional): Nombre, apellido o teléfono.
  * `limit` (query, integer, opcional, por defecto: `50`).
  * `offset` (query, integer, opcional, por defecto: `0`).
* **Respuesta 200 OK:** Lista de clientes (`list[dict]`).

#### `POST /api/v1/clientes`
* **Nombre:** Crear Cliente
* **Descripción:** Crea un cliente nuevo en el sistema y confirma la creación retornando su ID junto con los datos registrados.
* **Autenticación:** Requerida.
* **Request Body:** `application/json` (`ClienteCreateIn`)
  ```json
  {
    "nombre": "María",
    "apellido": "García",
    "telefono": "809-555-0102",
    "email": "maria@example.com",
    "domicilio": "Calle Las Flores #8",
    "prioridad": false
  }
  ```
* **Respuesta 201 Created:**
  ```json
  {
    "id": "LRa1b2c3d4",
    "nombre": "María",
    "apellido": "García",
    "telefono": "809-555-0102",
    "email": "maria@example.com",
    "domicilio": "Calle Las Flores #8",
    "prioridad": false
  }
  ```

#### `PATCH /api/v1/clientes/{cliente_id}`
* **Nombre:** Actualizar Cliente
* **Descripción:** Modifica parcialmente la información de un cliente.
* **Autenticación:** Requerida.
* **Parámetros:**
  * `cliente_id` (path, string, requerido): ID del cliente.
* **Request Body:** `application/json` (`ClienteUpdateIn`)
* **Respuesta 200 OK:** `{"status": "updated", "cliente_id": "..."}`

#### `DELETE /api/v1/clientes/{cliente_id}`
* **Nombre:** Eliminar Cliente (Soft Delete)
* **Descripción:** Marca la fecha de eliminación (`deleted_at`) en el registro del cliente sin borrar sus datos físicos.
* **Autenticación:** Requerida.
* **Parámetros:**
  * `cliente_id` (path, string, requerido): ID del cliente.
* **Respuesta 204 No Content**

---

### 📖 Catálogo

#### `GET /api/v1/catalogo`
* **Nombre:** Listar Catálogo
* **Descripción:** Retorna las plantillas genéricas activas del catálogo. Realiza automáticamente un `LEFT JOIN` con la tabla `images` para incluir los atributos de la imagen (`file_path`, `image_src`, `url_imagen` y `aspect_ratio`) directamente en cada objeto devuelto.
* **Autenticación:** Requerida.
* **Parámetros:**
  * `search` (query, string, opcional): Búsqueda por nombre de plantilla.
  * `limit` (query, integer, opcional, por defecto: `50`).
  * `offset` (query, integer, opcional, por defecto: `0`).
* **Respuesta 200 OK:** Lista de modelos del catálogo (`list[dict]`).

#### `POST /api/v1/catalogo`
* **Nombre:** Crear Plantilla de Catálogo (Con foto obligatoria)
* **Descripción:** Registra un nuevo modelo genérico en el catálogo adjuntando obligatoriamente su foto en un formulario `multipart/form-data`. El backend guarda la imagen física en disco (`/uploads/{prefix}/`), registra la entrada en la tabla `images` y asocia su `image_id` al modelo.
* **Autenticación:** Requerida.
* **Request Body:** `multipart/form-data`
  * `nombre` (string, Form, requerido): Nombre de la plantilla (ej: `"Juego de Habitación King"`).
  * `tipo` (string, Form, opcional): Ej: `"Cama"`.
  * `area` (string, Form, opcional): Ej: `"Ebanistería"`.
  * `precio_base` (number/float, Form, opcional).
  * `file` (UploadFile / Binary, File, requerido): Imagen de la plantilla.
* **Respuesta 201 Created:**
  ```json
  {
    "id": "LRa1b2c3d4",
    "nombre": "Juego de Habitación King",
    "tipo": "Cama",
    "area": "Ebanistería",
    "precio_base": 45000.0,
    "image_id": "LRe5f6g7h8",
    "file_path": "/uploads/L/LRe5f6g7h8.jpg"
  }
  ```

#### `PATCH /api/v1/catalogo/{catalogo_id}`
* **Nombre:** Modificar Catálogo
* **Descripción:** Modifica los campos de una plantilla de catálogo.
* **Autenticación:** Requerida.
* **Parámetros:**
  * `catalogo_id` (path, string, requerido): ID de la plantilla.
* **Request Body:** `application/json` (`CatalogoUpdateIn`)
* **Respuesta 200 OK:** `{"status": "updated", "catalogo_id": "..."}`

#### `DELETE /api/v1/catalogo/{catalogo_id}`
* **Nombre:** Eliminar Catálogo (Soft Delete)
* **Descripción:** Marca `deleted_at`. Rechaza la solicitud con error `409 Conflict` si existen ítems o variantes de stock activas vinculadas a esta plantilla.
* **Autenticación:** Requerida.
* **Parámetros:**
  * `catalogo_id` (path, string, requerido): ID de la plantilla.
* **Respuesta 204 No Content**
* **Errores:**
  * `409 Conflict`: Si hay stock activo asociado.

---

### 📦 Stock (Inventario)

#### `GET /api/v1/stock`
* **Nombre:** Listar Stock
* **Descripción:** Obtiene el inventario actual con datos consolidados del catálogo relacionado (`catalogo_nombre`, `tipo`, `area`). Realiza un `LEFT JOIN` con la tabla `images` (usando `COALESCE(s.image_id, c.image_id)`) para incluir la ruta y URL de la imagen (`file_path`, `image_src`, `url_imagen` y `aspect_ratio`) directamente en cada variante devuelta.
* **Autenticación:** Requerida.
* **Parámetros:**
  * `search` (query, string, opcional): Búsqueda por nombre de catálogo, color o material.
  * `limit` (query, integer, opcional, por defecto: `50`).
  * `offset` (query, integer, opcional, por defecto: `0`).
* **Respuesta 200 OK:** Lista de variantes de stock (`list[dict]`).

#### `POST /api/v1/stock`
* **Nombre:** Crear Variante de Stock
* **Descripción:** Registra una variante de stock asociada a una plantilla de catálogo. Hereda automáticamente la foto genérica del catálogo si no se adjunta un archivo en `file`. Si se sube una imagen física, la guarda en `/uploads/{prefix}/` y asigna su nuevo `image_id`.
* **Autenticación:** Requerida.
* **Request Body:** `multipart/form-data`
  * `catalogo_id` (string, Form, requerido): ID del catálogo base.
  * `color` (string, Form, opcional).
  * `material` (string, Form, opcional).
  * `descripcion` (string, Form, opcional).
  * `cantidad` (integer, Form, opcional, por defecto: `0`).
  * `precio` (number/float, Form, opcional).
  * `file` (UploadFile / Binary, File, opcional): Foto personalizada de la variante.
* **Respuesta 201 Created:**
  ```json
  {
    "id": "LRs1t2u3v4",
    "catalogo_id": "LRa1b2c3d4",
    "color": "Gris Plomo",
    "material": "Terciopelo",
    "descripcion": "Stock entrega inmediata",
    "cantidad": 5,
    "precio": 35000.0,
    "image_id": "LRe5f6g7h8"
  }
  ```
* **Errores:**
  * `404 Not Found`: Si el `catalogo_id` indicado no existe.

#### `PATCH /api/v1/stock/{stock_id}`
* **Nombre:** Modificar Variante de Stock
* **Descripción:** Modifica los campos específicos de una variante de stock.
* **Autenticación:** Requerida.
* **Parámetros:**
  * `stock_id` (path, string, requerido): ID de la variante.
* **Request Body:** `application/json` (`StockUpdateIn`)
* **Respuesta 200 OK:** `{"status": "updated", "stock_id": "..."}`

#### `PATCH /api/v1/stock/{stock_id}/cantidad`
* **Nombre:** Ajustar Cantidad de Stock
* **Descripción:** Aplica un cambio relativo (`delta` positivo o negativo) a la cantidad existente en inventario (mantenimiento de límite mínimo 0).
* **Autenticación:** Requerida.
* **Parámetros:**
  * `stock_id` (path, string, requerido): ID de la variante.
* **Request Body:** `application/json` (`StockCantidadUpdate`)
  ```json
  {
    "delta": -2
  }
  ```
* **Respuesta 200 OK:** `{"stock_id": "...", "cantidad": 3}`

#### `DELETE /api/v1/stock/{stock_id}`
* **Nombre:** Eliminar Variante de Stock (Soft Delete)
* **Descripción:** Marca `deleted_at` en el registro de stock.
* **Autenticación:** Requerida.
* **Parámetros:**
  * `stock_id` (path, string, requerido): ID de la variante.
* **Respuesta 204 No Content**

---

### ⚙️ Configuración

#### `GET /api/v1/config`
* **Nombre:** Obtener Configuración
* **Descripción:** Retorna el diccionario con la configuración del usuario autenticado (datos de la empresa, listas de colores, materiales, tipos y áreas).
* **Autenticación:** Requerida.
* **Respuesta 200 OK:**
  ```json
  {
    "empresa_nombre": "Ebanistería Venus",
    "colores": ["Blanco", "Negro", "Gris", "Caoba"],
    "materiales": ["Roble", "Pino", "Terciopelo", "Cuerina"],
    "tipos": ["Cama", "Sofá", "Mesa", "Gabinete"],
    "areas": ["Ebanistería", "Tapicería", "Metales"]
  }
  ```

#### `PUT /api/v1/config`
* **Nombre:** Guardar / Reemplazar Configuración
* **Descripción:** Reemplaza completamente los parámetros de configuración asociados al usuario autenticado.
* **Autenticación:** Requerida.
* **Request Body:** `application/json` (`ConfigUpdateIn`)
  ```json
  {
    "empresa_nombre": "Venus Custom Furniture",
    "colores": ["Blanco", "Negro", "Gris", "Nogal"],
    "materiales": ["Roble", "Pino", "Lino"],
    "tipos": ["Cama", "Sofá", "Mesa"],
    "areas": ["Ebanistería", "Tapicería"]
  }
  ```
* **Respuesta 200 OK:**
  ```json
  {
    "status": "updated"
  }
  ```
