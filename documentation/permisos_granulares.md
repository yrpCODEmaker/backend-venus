# Documentación: Permisos Granulares por Módulo

**Fecha de implementación:** 2026-07-28  
**Fase:** Implementación completa (6 fases)  
**Archivo de plan:** `plan_implementacion.md`

---

## Resumen de Cambios

Se implementó el sistema de gestión de usuarios y permisos granulares para Venus Backend. El admin puede ahora controlar de forma precisa qué acciones puede realizar cada usuario en cada módulo del sistema.

---

## Arquitectura de Permisos

### Tabla `user_permissions` (nueva en `database.py`)

Relación `1:1` con `usuarios` (FK `user_id`, `ON DELETE CASCADE`).

| Grupo | Columnas |
|-------|----------|
| Facturas | `facturas_ver`, `facturas_emitir`, `facturas_modificar` |
| Fabricación | `fabricacion_ver_estados`, `fabricacion_modificar_estados`, `fabricacion_mandar_envio` |
| Stock | `stock_crear`, `stock_modificar`, `stock_eliminar` |
| Catálogo | `catalogo_crear`, `catalogo_modificar`, `catalogo_eliminar` |
| Clientes | `clientes_crear`, `clientes_modificar`, `clientes_eliminar` |
| Visibilidad | `puede_ver_datos_de_otros`, `prefijos_visibles` (JSON array) |

**Valores por defecto:**
- Admin (`pichardo`): acceso total (seed idempotente en `init_db`).
- Usuario regular nuevo: `facturas_ver=1`, `fabricacion_ver_estados=1`, resto en `0`.

---

## Archivos Modificados

### `database.py`
- DDL ampliado de 11 a 12 tablas (nueva: `user_permissions`).
- `init_db()` ahora hace seed de permisos totales al admin.

### `schemas.py`
- `UserOut`: campo `permissions: Optional[UserPermissionsOut]` añadido.
- `UserPermissionsOut`: schema de lectura de permisos.
- `UserPermissionsIn`: schema de escritura parcial de permisos.
- `AdminUserUpdateIn`: edición integral de usuario (username, password, prefix).
- `DataVisibilityPatchIn`: ajuste de visibilidad por prefijos.

### `routers/admin.py` (reescrito)
Nuevos endpoints:
- `PUT /api/v1/admin/users/{username}` — editar usuario
- `DELETE /api/v1/admin/users/{username}` — eliminar usuario
- `GET /api/v1/admin/users/{username}/permissions` — leer permisos
- `PUT /api/v1/admin/users/{username}/permissions` — escribir permisos
- `PATCH /api/v1/admin/users/{username}/data-visibility` — visibilidad

Helpers internos: `_get_user_or_404`, `_get_or_create_permissions`, `_row_to_permissions_out`.

### `services/auth.py`
- `get_current_user()`: ahora incluye `id` y carga `permissions` desde `user_permissions`.
- `require_permission(action)`: factory de dependencias FastAPI para validar permisos. El admin siempre hace bypass.

### `routers/operacional.py`
- Import de `require_permission` añadido.
- Todos los endpoints usan `require_permission(acción)` en lugar de `get_current_user` directo.

### `tests/test_admin.py` (nuevo)
27 tests organizados en 4 clases:
- `TestUserCRUD`: 13 tests de ciclo de vida de usuarios.
- `TestPermissions`: 5 tests de lectura/escritura de permisos.
- `TestDataVisibility`: 3 tests de visibilidad de datos.
- `TestOperationalGuards`: 6 tests de guards en módulos operacionales.

**Resultado:** ✅ 27/27 tests pasando.

### `pytest.ini` (nuevo)
Configuración `asyncio_mode = auto` para soporte de tests async.

---

## Reglas de Negocio Implementadas

1. **Admin indestructible**: No puede eliminarse ni bloquearse a sí mismo.
2. **Prefijo del admin inmutable**: No puede cambiar su propio prefijo (integridad multi-tenant).
3. **Prefijos válidos en visibilidad**: `prefijos_visibles` solo acepta prefijos de usuarios existentes. Devuelve 422 si el prefijo no existe.
4. **Permisos auto-creados**: Si un usuario no tiene registro en `user_permissions`, se crea automáticamente con valores restrictivos al consultarlo.
5. **Admin bypass**: El rol `admin` siempre pasa todos los guards sin consultar la tabla de permisos.
6. **Permisos en cascade**: Al eliminar un usuario, sus permisos se eliminan automáticamente (FK `ON DELETE CASCADE`).

---

## Guards por Endpoint

| Endpoint | Permiso requerido |
|----------|-------------------|
| `GET /facturas` | `facturas_ver` |
| `POST /facturas` | `facturas_emitir` |
| `PATCH /facturas/{id}` | `facturas_modificar` |
| `DELETE /facturas/{id}` | `facturas_modificar` |
| `POST /facturas/{id}/dispatch` | `fabricacion_mandar_envio` |
| `GET /items` | `fabricacion_ver_estados` |
| `POST /facturas/{id}/items` | `facturas_emitir` |
| `PATCH /items/{id}` | `fabricacion_modificar_estados` |
| `PATCH /items/{id}/status` | `fabricacion_modificar_estados` |
| `PATCH /items/{id}/photo` | `fabricacion_modificar_estados` |
| `DELETE /items/{id}` | `fabricacion_modificar_estados` |
| `POST /facturas/{id}/pagos` | `facturas_emitir` |
| `GET /facturas/{id}/pagos` | `facturas_ver` |
| `GET /envios` | `fabricacion_ver_estados` |
| `PATCH /envios/{id}/status` | `fabricacion_mandar_envio` |
| `PATCH /envios/{id}` | `fabricacion_mandar_envio` |
| `GET/POST /clientes` | `clientes_crear` |
| `PATCH /clientes/{id}` | `clientes_modificar` |
| `DELETE /clientes/{id}` | `clientes_eliminar` |
| `GET/POST /catalogo` | `catalogo_crear` |
| `PATCH /catalogo/{id}` | `catalogo_modificar` |
| `DELETE /catalogo/{id}` | `catalogo_eliminar` |
| `GET/POST /stock` | `stock_crear` |
| `PATCH /stock/{id}` | `stock_modificar` |
| `PATCH /stock/{id}/cantidad` | `stock_modificar` |
| `DELETE /stock/{id}` | `stock_eliminar` |
