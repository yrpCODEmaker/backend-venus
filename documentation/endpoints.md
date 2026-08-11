# Documentación de Endpoints — Venus Backend API REST

Esta documentación describe la API REST completa de Venus Backend (FastAPI + SQLite WAL), organizada por módulos funcionales, con sus tipos de datos, cuerpos de solicitud, parámetros y respuestas.

> **Última actualización:** Fase 7 — Endpoints de descarga de facturas en PDF y PNG.

---

## 1. Administración (`/api/v1/admin`)

> **Permisos:** Exclusivos para el usuario administrador (`pichardo`, rol: `admin`).

### `GET` `/api/v1/admin/users`
* **Resumen:** Listar Usuarios
* **Descripción:** Lista todos los usuarios registrados en el sistema.

**Respuestas:**
- **200 OK**:
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

---

### `POST` `/api/v1/admin/users`
* **Resumen:** Crear Usuario
* **Descripción:** Crea un nuevo usuario regular asignándole un prefijo único.

**Request Body:** `application/json`
```json
{
  "username": "carlos",
  "password": "secreto123",
  "prefix": "C"
}
```

**Respuestas:**
- **201 Created**: Usuario creado exitosamente.
- **409 Conflict**: Si el `username` o el `prefix` ya están en uso.

---

### `PATCH` `/api/v1/admin/users/{username}/toggle`
* **Resumen:** Activar/Desactivar Usuario
* **Descripción:** Alterna el estado activo/inactivo de un usuario. El admin no puede desactivarse a sí mismo.

**Parámetros:**
- `username` [path] (string, Requerido): Username del usuario objetivo.

**Respuestas:**
- **200 OK**: Retorna el nuevo estado del usuario.
- **400 Bad Request**: Si intenta desactivar su propia cuenta admin.
- **404 Not Found**: Usuario no encontrado.

---

### `PUT` `/api/v1/admin/users/{username}`
* **Resumen:** Editar Usuario
* **Descripción:** Edita campos del usuario (username, contraseña, prefijo). Solo se actualizan los campos enviados. El admin no puede cambiar su propio prefijo.

**Parámetros:**
- `username` [path] (string, Requerido): Username actual del usuario.

**Request Body:** `application/json`
```json
{
  "username": "carlos_nuevo",
  "password": "nuevapass123",
  "prefix": "CN"
}
```

**Respuestas:**
- **200 OK**: Retorna el usuario actualizado.
- **400 Bad Request**: Sin campos a actualizar, o intento de cambiar prefijo propio (admin).
- **404 Not Found**: Usuario no encontrado.
- **409 Conflict**: Nuevo username o prefijo ya en uso.

---

### `DELETE` `/api/v1/admin/users/{username}`
* **Resumen:** Eliminar Usuario
* **Descripción:** Elimina permanentemente un usuario y sus permisos (ON DELETE CASCADE). El admin no puede eliminarse a sí mismo.

**Parámetros:**
- `username` [path] (string, Requerido): Username del usuario a eliminar.

**Respuestas:**
- **204 No Content**: Usuario eliminado exitosamente.
- **400 Bad Request**: Intento de auto-eliminación del admin.
- **404 Not Found**: Usuario no encontrado.

---

### `GET` `/api/v1/admin/users/{username}/permissions`
* **Resumen:** Leer Permisos de Usuario
* **Descripción:** Retorna los permisos granulares del usuario por dominio (facturas, fabricación, stock, catálogo, clientes) y configuración de visibilidad. Si no tiene registro, se crea con valores restrictivos por defecto.

**Parámetros:**
- `username` [path] (string, Requerido): Username del usuario.

**Respuestas:**
- **200 OK**:
  ```json
  {
    "facturas_ver": true,
    "facturas_emitir": false,
    "facturas_modificar": false,
    "fabricacion_ver_estados": true,
    "fabricacion_modificar_estados": false,
    "fabricacion_mandar_envio": false,
    "stock_crear": false,
    "stock_modificar": false,
    "stock_eliminar": false,
    "catalogo_crear": false,
    "catalogo_modificar": false,
    "catalogo_eliminar": false,
    "clientes_crear": false,
    "clientes_modificar": false,
    "clientes_eliminar": false,
    "puede_ver_datos_de_otros": false,
    "prefijos_visibles": []
  }
  ```
- **404 Not Found**: Usuario no encontrado.

---

### `PUT` `/api/v1/admin/users/{username}/permissions`
* **Resumen:** Actualizar Permisos de Usuario
* **Descripción:** Actualiza permisos granulares (actualización parcial: solo los campos enviados se modifican). Valida que los prefijos en `prefijos_visibles` correspondan a usuarios existentes.

**Parámetros:**
- `username` [path] (string, Requerido): Username del usuario.

**Request Body:** `application/json` (todos los campos son opcionales)
```json
{
  "facturas_emitir": true,
  "clientes_crear": true,
  "stock_crear": true,
  "prefijos_visibles": ["P", "M"]
}
```

**Respuestas:**
- **200 OK**: Retorna los permisos actualizados completos.
- **400 Bad Request**: Sin campos a actualizar.
- **404 Not Found**: Usuario no encontrado.
- **422 Unprocessable Entity**: Prefijo en `prefijos_visibles` no existe en el sistema.

---

### `PATCH` `/api/v1/admin/users/{username}/data-visibility`
* **Resumen:** Ajustar Visibilidad de Datos
* **Descripción:** Controla si el usuario puede ver datos de otros usuarios y cuáles prefijos. Los prefijos enviados deben pertenecer a usuarios registrados en el sistema.

**Parámetros:**
- `username` [path] (string, Requerido): Username del usuario.

**Request Body:** `application/json` (todos los campos son opcionales)
```json
{
  "puede_ver_datos_de_otros": true,
  "prefijos_visibles": ["P", "C"]
}
```

**Respuestas:**
- **200 OK**: Retorna la configuración de permisos actualizada.
- **400 Bad Request**: Sin campos a actualizar.
- **404 Not Found**: Usuario no encontrado.
- **422 Unprocessable Entity**: Prefijo no existe.

---

> **Nota sobre guards en endpoints operacionales:** A partir de esta fase, los endpoints operacionales (facturas, ítems, envíos, stock, catálogo, clientes) validan permisos granulares. El admin (`rol=admin`) siempre tiene acceso total. Los usuarios regulares necesitan los permisos correspondientes habilitados en su registro `user_permissions`.
>
> | Dominio | Permiso requerido para GET | Permiso para POST/PATCH/DELETE |
> |---------|---------------------------|--------------------------------|
> | Facturas | `facturas_ver` | `facturas_emitir` / `facturas_modificar` |
> | Ítems | `fabricacion_ver_estados` | `fabricacion_modificar_estados` |
> | Envíos | `fabricacion_ver_estados` | `fabricacion_mandar_envio` |
> | Clientes | `clientes_crear` | `clientes_modificar` / `clientes_eliminar` |
> | Catálogo | `catalogo_crear` | `catalogo_modificar` / `catalogo_eliminar` |
> | Stock | `stock_crear` | `stock_modificar` / `stock_eliminar` |

## 2. Autenticación (`/api/v1/auth`)

### `POST` `/api/v1/auth/login`
* **Resumen:** Login de Usuario con Seguridad Avanzada (Rate Limit, 2FA, IP Inteligente)
* **Descripción:** Autentica un usuario y retorna un Token JWT de acceso (Bearer).
  * **Control de intentos:** Tras 3 intentos fallidos, bloquea la cuenta por 5 minutos si no tiene 2FA, o exige código OTP si tiene 2FA.
  * **Regla Anti-Ingeniería Inversa:** Si se envía `otp_code` sin requerirse, bloquea la cuenta por 5 minutos.
  * **Smart Login:** Exige OTP automáticamente si la IP del cliente proviene del exterior o es sospechosa.

**Request Body:** `application/x-www-form-urlencoded` o `application/json` (`LoginRequest`)
```json
{
  "username": "pichardo",
  "password": "admin123",
  "otp_code": "123456"
}
```

**Respuestas:**
- **200 OK (Autenticado):**
  ```json
  {
    "access_token": "eyJhbGci...",
    "token_type": "bearer",
    "expires_in": 3600,
    "requires_otp": false,
    "message": "Inicio de sesión exitoso"
  }
  ```
- **200 OK (Requiere OTP):**
  ```json
  {
    "access_token": null,
    "token_type": "bearer",
    "expires_in": null,
    "requires_otp": true,
    "message": "Se requiere código de autenticación (OTP) de 6 dígitos."
  }
  ```
- **401 Unauthorized:** Credenciales inválidas o código OTP incorrecto.
- **403 Forbidden:** Cuenta desactivada.
- **429 Too Many Requests:** Cuenta bloqueada por 5 minutos tras 3 intentos fallidos o por detección de ingeniería inversa.

---

### `POST` `/api/v1/auth/2fa/setup`
* **Resumen:** Configurar 2FA / Generar QR
* **Descripción:** Genera la clave secreta TOTP preliminar y el código QR en Base64 PNG para escanear en la app autenticadora.

**Headers:** `Authorization: Bearer <token>`

**Respuestas:**
- **200 OK:**
  ```json
  {
    "secret": "JBSWY3DPEHPK3PXP",
    "qr_code_base64": "data:image/png;base64,iVBORw0KGgo...",
    "otpauth_url": "otpauth://totp/Venus%20App:pichardo?secret=JBSWY3DPEHPK3PXP&issuer=Venus%20App"
  }
  ```

---

### `POST` `/api/v1/auth/2fa/enable`
* **Resumen:** Activar 2FA
* **Descripción:** Valida 1 código OTP generado por la app autenticadora para confirmar la sincronización y habilitar `totp_enabled = 1`.

**Headers:** `Authorization: Bearer <token>`

**Request Body:** `application/json`
```json
{
  "otp_code": "123456"
}
```

**Respuestas:**
- **200 OK:** `{"enabled": true}`
- **400 Bad Request:** Código OTP inválido o no se ha llamado primero a `/2fa/setup`.

---

### `POST` `/api/v1/auth/2fa/disable`
* **Resumen:** Desactivar 2FA
* **Descripción:** Desactiva la autenticación de dos factores para el usuario.

**Headers:** `Authorization: Bearer <token>`

**Request Body:** `application/json`
```json
{
  "password": "admin123"
}
```

**Respuestas:**
- **200 OK:** `{"enabled": false}`
- **400 Bad Request:** Se requiere contraseña válida o código OTP para desactivar.

---

### `GET` `/api/v1/auth/2fa/status`
* **Resumen:** Estado de 2FA
* **Descripción:** Consulta si el usuario autenticado tiene activa la autenticación de dos factores.

**Headers:** `Authorization: Bearer <token>`

**Respuestas:**
- **200 OK:** `{"enabled": true}`

---

### `GET` `/api/v1/auth/me`
* **Resumen:** Perfil del Usuario Autenticado
* **Descripción:** Retorna la información y rol del usuario autenticado vía JWT.

**Respuestas:**
- **200 OK**:
  ```json
  {
    "username": "pichardo",
    "rol": "admin",
    "prefix": "P",
    "activo": true
  }
  ```
- **401 Unauthorized**: Token inválido o expirado.

---

## 3. Operacional (`/api/v1`)

### 🧾 Facturas

#### `GET` `/api/v1/facturas`
* **Resumen:** Listar Facturas
* **Descripción:** Retorna el listado de facturas del usuario, paginado y filtrado.

**Parámetros Query:**
- `search` (string, opcional): Búsqueda por ID de factura o nombre/apellido del cliente.
- `start_date` (string ISO, opcional): Fecha mínima.
- `end_date` (string ISO, opcional): Fecha máxima.
- `limit` (integer, por defecto: 50): Límite de resultados.
- `offset` (integer, por defecto: 0): Salto para paginación.

**Respuestas:**
- **200 OK**: Lista de facturas.

---

#### `POST` `/api/v1/facturas`
* **Resumen:** Crear Factura Transaccional
* **Descripción:** Ejecuta una transacción ACID completa (7 pasos): valida cliente, inserta factura, inserta ítems, descuenta stock, crea abono inicial, cola de trabajos y registro de envío.

> **⚠️ REGLA DE CLIENTE OBLIGATORIO (venus_workflow.md)**
> - **Factura normal** (`facturacion_rapida: 0`): el campo `cliente_id` es **requerido**. Sin él, retorna `422`.
> - **Factura rápida** (`facturacion_rapida: 1`): el campo `cliente_id` se omite, pero `cliente` es **requerido** con la estructura `{nombre, apellido, telefono}`. Al menos `nombre` debe estar presente. Sin él, retorna `422`.
> - El JSON de cliente rápido se almacena en BD con estructura consistente `{"nombre": "...", "apellido": "...", "telefono": "..."}` (cadenas vacías si no se proveen).

> **📥 cola_trabajos — inserción automática**
> Los ítems de tipo `'encargo'` ingresan automáticamente a la cola de fabricación. La factura se elimina de `cola_trabajos` cuando:
> - (A) Todos los ítems pasan a `procesado` o `completado` **Y**
> - (B) Si tiene entrega a domicilio, el envío llega a estado `Entregado`.

> **🎨 Parámetros de Ítems Opcionales / Nullable**
> Los campos `tela`, `color`, `material` y `descripcion` en cada ítem son opcionales. Si se envían como `null` o se omiten en el payload, el backend los acepta sin error, almacena `NULL` en la base de datos y los retorna como `null` en las respuestas JSON.

**Ejemplo — Factura Normal:**
```json
{
  "cliente_id": "L1",
  "total": 35000.0,
  "monto_pagado": 10000.0,
  "entrega_domicilio": true,
  "direccion_entrega": "Av. Central #12",
  "garantia_hasta": "6 Meses",
  "facturacion_rapida": 0,
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

**Ejemplo — Factura Rápida (sin cliente registrado):**
```json
{
  "facturacion_rapida": 1,
  "cliente": {
    "nombre": "María",
    "apellido": "López",
    "telefono": "849-555-0001"
  },
  "total": 2000.0,
  "items": [
    {
      "catalogo_id": "L1",
      "nombre": "Taburete",
      "cantidad": 1,
      "tipo": "encargo",
      "subtotal": 2000.0,
      "color": "Negro",
      "material": "Madera"
    }
  ]
}
```

**Respuestas:**
- **201 Created**: Factura creada exitosamente. Retorna el ID de la factura creada y sus detalles.
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
- **409 Conflict**: Stock insuficiente para ítems tipo 'stock'.
- **422 Unprocessable Entity**: Falta `cliente_id` o el campo `cliente` en factura rápida es inválido.

---

#### `GET` `/api/v1/facturas/{factura_id}`
* **Resumen:** Detalle de Factura
* **Descripción:** Retorna la información de una factura incluyendo sus ítems y lista de pagos.

**Parámetros:**
- `factura_id` [path] (string, Requerido): ID de la factura (ej: `"LR1a2b3c4d"`).

**Respuestas:**
- **200 OK**: Detalle de la factura con arrays `items` y `pagos`.
- **404 Not Found**: Factura no encontrada.

---

#### `PATCH` `/api/v1/facturas/{factura_id}`
* **Resumen:** Actualización Parcial de Factura
* **Descripción:** Modifica campos de dirección, cliente, garantía o estatus de entrega.

**Request Body:** `application/json`
```json
{
  "direccion_entrega": "Nueva Dirección #45",
  "garantia_hasta": "1 Año"
}
```

**Respuestas:**
- **200 OK**: Factura actualizada.
- **404 Not Found**: Factura no encontrada.

---

#### `DELETE` `/api/v1/facturas/{factura_id}`
* **Resumen:** Eliminar Factura
* **Descripción:** Realiza un *hard delete* en cascada de la factura y restaura las cantidades de stock asociadas a sus ítems.

**Respuestas:**
- **204 No Content**: Factura eliminada.

---

#### `POST` `/api/v1/facturas/{factura_id}/dispatch`
* **Resumen:** Despacho Masivo de Factura
* **Descripción:** Cambia el estado de todos los ítems a `completado` y programa o completa su entrega.

**Respuestas:**
- **200 OK**: Factura despachada.

---

#### `GET` `/api/v1/facturas/{factura_id}/download/pdf`
* **Resumen:** Descargar Factura en PDF
* **Descripción:** Genera y descarga la factura como archivo PDF. La información de empresa (nombre, logo, teléfono, ubicación, RNC) se carga desde `company_config.json` en la raíz del proyecto. Si el campo `rnc` es `null` o vacío, no se menciona el RNC en la factura.
* **Permiso requerido:** `facturas_ver`

**Parámetros:**
- `factura_id` [path] (string, Requerido): ID de la factura.

**Respuestas:**
- **200 OK**: Archivo PDF descargable.
  - `Content-Type: application/pdf`
  - `Content-Disposition: attachment; filename="factura_{id}.pdf"`
- **401 Unauthorized**: Token no proporcionado o inválido.
- **404 Not Found**: Factura no encontrada.

---

#### `GET` `/api/v1/facturas/{factura_id}/download/png`
* **Resumen:** Descargar Factura en PNG
* **Descripción:** Genera y descarga la factura como imagen PNG de alta resolución (150 DPI). Idéntica visualmente al PDF. La info de empresa se carga desde `company_config.json`.
* **Permiso requerido:** `facturas_ver`

**Parámetros:**
- `factura_id` [path] (string, Requerido): ID de la factura.

**Respuestas:**
- **200 OK**: Imagen PNG descargable.
  - `Content-Type: image/png`
  - `Content-Disposition: attachment; filename="factura_{id}.png"`
- **401 Unauthorized**: Token no proporcionado o inválido.
- **404 Not Found**: Factura no encontrada.

> **⚙️ Configuración de empresa para facturas:**
> Edita `company_config.json` en la raíz del proyecto para cambiar el nombre, logo, teléfono, ubicación o RNC de la empresa sin modificar código.
>
> ```json
> {
>   "nombre": "Venus Muebles",
>   "logo_path": null,
>   "ubicacion": "Santo Domingo, RD",
>   "telefono": "+1 (809) 000-0000",
>   "rnc": null
> }
> ```

---

### 🔨 Ítems (Producción / Kanban)

#### `GET` `/api/v1/items`
* **Resumen:** Listar Ítems (Kanban con Imagen Inteligente)
* **Descripción:** Obtiene los ítems para los tableros Kanban de producción.

> **🖼️ Imagen Inteligente (venus_workflow.md)**
> El endpoint realiza un `JOIN` automático con la tabla `catalogo` e `images`.
> - Si el ítem tiene una imagen propia (`image_id`), devuelve su `image_url`.
> - Si el ítem **NO** tiene imagen propia, devuelve la URL de la imagen genérica del catálogo al que pertenece.
> - El campo `image_url` siempre está presente en la respuesta (puede ser `null` si no hay imagen).
> - El campo `catalogo_image_id` indica si se está usando la imagen del catálogo como fallback.

**Parámetros Query:**
- `status` (string, opcional): `'pendiente' | 'procesando' | 'procesado' | 'completado'`.
- `area` (string, opcional): `'Tapicería' | 'Ebanistería' | 'Metales'`.
- `tipo` (string, opcional): `'encargo' | 'stock'`.
- `limit` (integer, por defecto: 50)
- `offset` (integer, por defecto: 0)

**Respuestas:**
- **200 OK**: Lista de ítems de producción con `image_url` resuelta.
  ```json
  [
    {
      "id": "LRi1a2b3c4",
      "factura_id": "LRa1b2c3d4",
      "nombre": "Sofá Custom",
      "tipo": "encargo",
      "status": "pendiente",
      "area": "Tapicería",
      "image_url": "http://localhost:8000/uploads/L/cat_sofa.jpg",
      "catalogo_image_id": "L1",
      "resolved_image_id": "L1"
    }
  ]
  ```

---

#### `POST` `/api/v1/facturas/{factura_id}/items`
* **Resumen:** Agregar Ítem a Factura
* **Descripción:** Agrega una nueva línea de pedido a una factura activa.

**Request Body:** `application/json`
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

**Respuestas:**
- **201 Created**: Ítem agregado.

---

#### `PATCH` `/api/v1/items/{item_id}`
* **Resumen:** Modificar Ítem
* **Descripción:** Modifica color, material, descripción o subtotal de un ítem.

**Respuestas:**
- **200 OK**: Ítem actualizado.

---

#### `PATCH` `/api/v1/items/{item_id}/status`
* **Resumen:** Transición de Estado de Ítem
* **Descripción:** Avance en el flujo de fabricación (`pendiente` → `procesando` → `procesado` → `completado`). Si la factura NO tiene entrega a domicilio, `procesado` realiza un *bypass* automático a `completado`.

**Request Body:** `application/json`
```json
{
  "status": "procesando"
}
```

**Respuestas:**
- **200 OK**: Retorna el nuevo estado.

---

#### `PATCH` `/api/v1/items/{item_id}/photo`
* **Resumen:** Foto de Referencia de Ítem
* **Descripción:** Asigna o reemplaza el `image_id` asignado a un ítem.
* **Autenticación requerida:** Sí (JWT Bearer).

> **🔒 Requiere autenticación.** Sin token válido retorna `401 Unauthorized`.

---

#### `DELETE` `/api/v1/items/{item_id}`
* **Resumen:** Eliminar Ítem
* **Descripción:** Elimina el ítem y restaura la cantidad de stock si era de tipo `'stock'`.

---

### 💳 Pagos / Abonos

#### `POST` `/api/v1/facturas/{factura_id}/pagos`
* **Resumen:** Registrar Abono
* **Descripción:** Registra un nuevo pago o abono a una factura activa. Reduce automáticamente el `saldo_pendiente` e incrementa el `monto_pagado` de la factura.

**Parámetros:**
- `factura_id` [path] (string, Requerido): ID de la factura (ej: `"LRa1b2c3d4"`).

**Request Body:** `application/json`
```json
{
  "monto": 5000.0,
  "nota": "Abono transferencia bancaria"
}
```

**Respuestas:**
- **201 Created**: Pago registrado exitosamente.
  ```json
  {
    "pago_id": "LRp12345678",
    "monto": 5000.0,
    "saldo_restante": 10000.0
  }
  ```
- **400 Bad Request**: Si el monto excede el saldo pendiente actual.
- **404 Not Found**: Si la factura especificada no existe.

---

#### `GET` `/api/v1/facturas/{factura_id}/pagos`
* **Resumen:** Listar Abonos
* **Descripción:** Retorna el historial de pagos y abonos registrados a la factura.

**Parámetros:**
- `factura_id` [path] (string, Requerido): ID de la factura (ej: `"LRa1b2c3d4"`).

**Respuestas:**
- **200 OK**: Lista de pagos registrados.
  ```json
  [
    {
      "id": "LRp12345678",
      "factura_id": "LRa1b2c3d4",
      "monto": 5000.0,
      "fecha": "2026-07-25T18:00:00Z",
      "nota": "Abono transferencia bancaria",
      "created_at": "2026-07-25T18:00:00Z"
    }
  ]
  ```

---

### 🚚 Envíos

#### `GET` `/api/v1/envios`
* **Resumen:** Listar Envíos
* **Descripción:** Muestra los envíos a domicilio (`'Pendiente de Envío' | 'En Ruta' | 'Entregado'`).

---

#### `PATCH` `/api/v1/envios/{envio_id}/status`
* **Resumen:** Cambiar Estado de Envío
* **Descripción:** Actualiza la logística. Al pasar a `'Entregado'`, calcula y activa automáticamente la fecha de vencimiento de la garantía en la factura.

---

### 👥 Clientes

#### `GET` `/api/v1/clientes`
* **Resumen:** Listar Clientes
* **Descripción:** Retorna los clientes activos (no eliminados).

**Parámetros Query:** `search`, `limit`, `offset`.

---

#### `POST` `/api/v1/clientes`
* **Resumen:** Crear Cliente
* **Descripción:** Registra un cliente nuevo y confirma su creación retornando el ID generado junto a los datos del cliente.

**Request Body:** `application/json`
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

**Respuestas:**
- **201 Created**: Confirmación de creación del cliente con su ID generado.
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

---

#### `PATCH` `/api/v1/clientes/{cliente_id}`
* **Resumen:** Actualizar Cliente

#### `DELETE` `/api/v1/clientes/{cliente_id}`
* **Resumen:** Eliminar Cliente (Soft Delete)

---

### 📖 Catálogo

#### `GET` `/api/v1/catalogo`
* **Resumen:** Listar Catálogo
* **Descripción:** Obtiene las plantillas genéricas de catálogo activas con su información de imagen (`file_path`, `image_src`, `url_imagen`, `aspect_ratio`).

---

#### `POST` `/api/v1/catalogo`
* **Resumen:** Crear Plantilla de Catálogo (Con foto obligatoria)
* **Descripción:** Crea un modelo en el catálogo subiendo obligatoriamente su foto mediante un formulario `multipart/form-data`. El backend guarda la imagen en disco (`/uploads/{prefix}/`), la registra en la tabla `images` y vincula el `image_id` resultante al nuevo registro de catálogo.

**Request Body:** `multipart/form-data`
- `nombre` (string, Form, Requerido): Nombre del modelo (ej: `"Juego de Habitación King"`).
- `tipo` (string, Form, Opcional): Tipo de mueble (ej: `"Cama"`).
- `area` (string, Form, Opcional): Área productiva (ej: `"Ebanistería"`).
- `precio_base` (number, Form, Opcional): Precio base sugerido.
- `file` (UploadFile / Binary, Requerido): Archivo físico de la imagen.

**Respuestas:**
- **201 Created**:
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
- **422 Unprocessable Entity**: Si se omite la foto o algún parámetro requerido.

---

#### `PATCH` `/api/v1/catalogo/{catalogo_id}`
* **Resumen:** Modificar Catálogo

#### `DELETE` `/api/v1/catalogo/{catalogo_id}`
* **Resumen:** Eliminar Catálogo (Soft Delete)
* **Descripción:** Marca `deleted_at`. Rechaza con `409 Conflict` si existen ítems o stock activo referenciando esta plantilla.

---

### 📦 Stock (Inventario)

#### `GET` `/api/v1/stock`
* **Descripción:** Obtiene las variantes de inventario actual consolidando datos de catálogo y resolviendo la ruta de la imagen (`file_path`, `image_src`, `url_imagen`). *Nota: El stock con cantidad <= 0 o marcado como eliminado (`deleted_at IS NOT NULL`) es automáticamente excluido.*

#### `POST` `/api/v1/stock`
* **Resumen:** Crear Variante de Stock (Con imagen opcional)
* **Descripción:** Crea una variante de stock asociada a un catálogo mediante `multipart/form-data`. Hereda automáticamente la foto genérica del catálogo si no se sube una imagen propia. Si se envía una imagen en el campo `file`, se guarda en disco en `/uploads/{prefix}/`, se inserta en la tabla `images` y se asigna su nuevo `image_id`.

**Request Body:** `multipart/form-data`
- `catalogo_id` (string, Form, Requerido): ID del catálogo al que pertenece.
- `color` (string, Form, Opcional): Color específico de la variante.
- `material` (string, Form, Opcional): Material de la variante.
- `descripcion` (string, Form, Opcional): Detalles adicionales.
- `cantidad` (integer, Form, Opcional, por defecto `0`): Cantidad inicial en stock.
- `precio` (number, Form, Opcional): Precio de venta de la variante.
- `file` (UploadFile / Binary, Opcional): Archivo de imagen propia para esta variante.

**Respuestas:**
- **201 Created**:
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
- **404 Not Found**: Si el catálogo indicado no existe.

#### `PATCH` `/api/v1/stock/{stock_id}/cantidad`
* **Descripción:** Aplica un `delta` (+/-) a la cantidad existente (mínimo 0). *Si la cantidad resultante llega a 0, el ítem de stock se elimina automáticamente de forma lógica (`deleted_at`).*

```json
{
  "delta": -2
}
```

---

### ⚙️ Configuración

#### `GET` `/api/v1/config`
* **Resumen:** Obtener Configuración
* **Descripción:** Retorna la configuración global del usuario (empresa, colores, materiales, tipos, áreas).

#### `PUT` `/api/v1/config`
* **Resumen:** Guardar Configuración
* **Descripción:** Reemplaza la configuración del usuario.

---

### 🧵 Materiales y Catálogos Auxiliares (`/api/v1/materiales`)

#### `GET` `/api/v1/materiales`
* **Resumen:** Listar Materiales y Catálogos Auxiliares
* **Descripción:** Retorna los registros de la tabla `materiales` (categorías, elementos, color).
* **Parámetros Query:**
  - `categoria` (string, opcional): Filtrar por categoría (ej. `"Materiales"`, `"Telas"`, `"tipo_mueble"`, `"areas"`).

**Respuestas:**
- **200 OK**:
  ```json
  [
    {
      "id": "MAT-1",
      "categoria": "Materiales",
      "elementos": ["Madera Pino", "Madera Caoba", "MDF", "Metal", "Cristal"],
      "color": null,
      "updated_at": "2026-07-28 20:00:00"
    },
    {
      "id": "MAT-2",
      "categoria": "Telas",
      "elementos": ["Lino", "Terciopelo", "Sintético", "Cuero", "Yute"],
      "color": ["Rojo", "Azul", "Verde", "Gris", "Beige", "Negro", "Blanco"],
      "updated_at": "2026-07-28 20:00:00"
    }
  ]
  ```

---

#### `POST` `/api/v1/materiales`
* **Resumen:** Crear Categoría o Registro de Materiales
* **Descripción:** Registra una nueva categoría en la tabla de materiales.

**Request Body:** `application/json`
```json
{
  "categoria": "Cojines",
  "elementos": ["Espuma", "Pluma", "Microfibra"],
  "color": ["Blanco", "Gris"]
}
```

**Respuestas:**
- **201 Created**: Categoría creada exitosamente.

---

#### `PATCH` `/api/v1/materiales/{material_id}`
* **Resumen:** Actualizar Registro de Materiales
* **Descripción:** Modifica la lista de elementos, color o categoría de un registro de materiales.

**Request Body:** `application/json`
```json
{
  "elementos": ["Espuma", "Pluma", "Microfibra", "Viscoelástica"]
}
```

---

#### `DELETE` `/api/v1/materiales/{material_id}`
* **Resumen:** Eliminar Registro de Materiales
* **Descripción:** Elimina una fila de la tabla `materiales`.

**Respuestas:**
- **204 No Content**: Registro eliminado.

---

## 4. Sincronización Desktop (`/api/v1/sync`)

> **Restricción:** Exclusivo para usuarios regulares autenticados con prefijo (los admins son rechazados con 403 Forbidden en endpoints de sincronización).

### `POST` `/api/v1/sync/push`
* **Resumen:** Subida Masiva de Cambios (Push)
* **Descripción:** Recibe el payload completo del cliente desktop (IDs locales enteros). Aplica PrefixTransformer (`"5"` → `"L5"`) y ejecuta UPSERTs con lógica **Last-Write-Wins (LWW)** basándose en `updated_at`.

---

### `GET` `/api/v1/sync/pull`
* **Resumen:** Descarga Delta (Pull)
* **Descripción:** Devuelve todos los registros modificados desde `last_sync`. Transforma los IDs eliminando el prefijo (`"L5"` → `5`) para su inserción directa en la base de datos local SQLite del cliente.

**Parámetros Query:**
- `last_sync` (string ISO, opcional): Timestamp de la última sincronización.

---

### `POST` `/api/v1/sync/upload_image`
* **Resumen:** Subir Imagen Física (Desktop)
* **Descripción:** Recibe una imagen enviada por la app desktop (`multipart/form-data`: `local_image_id`, `file`), la guarda en `/uploads/{prefix}/`, calcula su relación de aspecto (`aspect_ratio = width / height`) mediante `Pillow` y actualiza/inserta la ruta y el `aspect_ratio` en la tabla `images`.

---

### `GET` `/api/v1/sync/image/{local_image_id}`
* **Resumen:** Descargar Imagen Física
* **Descripción:** Retorna el archivo binario de la imagen solicitada por su ID local.

---

## 5. Imágenes Protegidas

### `GET` `/api/v1/images/{image_id}`
* **Resumen:** Servir Imagen con Autenticación
* **Descripción:** Sirve el archivo físico de una imagen con autenticación JWT requerida.

> **🔒 Seguridad (venus_workflow.md):** Las imágenes son activos privados del negocio. Solo usuarios con sesión activa pueden visualizar imágenes del catálogo, stock e ítems. El frontend debe usar **este endpoint** en lugar de acceder a `/uploads/...` directamente.

**Parámetros:**
- `image_id` [path] (string, Requerido): ID de la imagen en la tabla `images` (ej: `"L1"`).

**Headers:**
- `Authorization: Bearer {token}` (Requerido)

**Respuestas:**
- **200 OK**: Archivo de imagen servido directamente (binary).
- **401 Unauthorized**: Sin token válido.
- **404 Not Found**: Imagen no encontrada en BD o el archivo no existe en disco.

---

## 6. Sistema

### `GET` `/health`
* **Resumen:** Health Check
* **Descripción:** Retorna `{"status": "ok"}` para validar que el servicio está activo.

*Última actualización: 2026-08-02 — Desduplicación de imágenes por hash SHA-256*
- Cálculo de hash SHA-256 en la subida de imágenes (`POST /catalogo`, `PUT/PATCH /catalogo/{id}`, `POST /stock`, `POST /sync/upload_image`) y almacenamiento en la nueva columna `hash TEXT` de la tabla `images`.
- Desduplicación automática de imágenes: si el hash ya existe en la BD backend, no se duplica el archivo físico en disco ni el registro, reutilizando el `image_id` existente para vincularlo al ítem/modelo correspondiente.
- Soporte para parámetros `null` en `tela`, `color`, `material` y `descripcion` de ítems en `POST /api/v1/facturas`, almacenándolos como `NULL` en base de datos y retornándolos como `null` en la respuesta JSON.
- Cálculo de relación de aspecto (`aspect_ratio`) mediante Pillow en subidas de imágenes.
- Validación de cliente obligatorio en `POST /facturas` con soporte `ClienteRapidoSchema`.
- `GET /items` con imagen inteligente (fallback a catálogo via JOIN).
- `PATCH /items/{id}/photo` requiere autenticación JWT.
- Nuevo endpoint `GET /api/v1/images/{id}` con protección JWT.
- `_check_and_remove_from_cola` verifica envío antes de limpiar cola_trabajos.
