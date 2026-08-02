# Arquitectura del Backend de Venus (Simplificada)

Este documento describe la arquitectura actual del backend del proyecto Venus. El sistema ha sido refactorizado para abandonar ORMs pesados (SQLAlchemy) y migraciones (Alembic) a favor de un esquema de base de datos rápido, directo y puramente basado en SQLite asíncrono (aiosqlite) con el modo WAL (Write-Ahead Logging) habilitado para maximizar el rendimiento.

## 1. Filosofía de la Arquitectura
*   **Ligero y Rápido:** No se utiliza SQLAlchemy ni ORMs; todas las queries se ejecutan como SQL directo para una máxima velocidad.
*   **Concurrencia:** Utiliza SQLite en modo WAL (`PRAGMA journal_mode=WAL`), lo que permite que múltiples procesos lean concurrentemente sin bloquear escrituras.
*   **Offline-First & Sincronización:** El backend expone endpoints de sincronización (Push/Pull) que permiten a clientes desktop (Flet) subir su estado local y descargar deltas (`updated_at > last_sync`).
*   **Gestión Multi-Inquilino (Multi-tenant lite):** Cada usuario registrado tiene un prefijo de una letra (ej. "L" para Laura). Los IDs locales que sube un cliente (ej. ID `5`) se transforman automáticamente en el servidor a IDs remotos con prefijo (ej. `"L5"`), aislando completamente los datos de cada ebanista sin requerir tablas separadas.
*   **Consolidación de Schemas:** Todos los modelos Pydantic (validación de datos) se centralizan en un único archivo `schemas.py`.

## 2. Tecnologías y Librerías Principales
*   `fastapi`: Framework web asíncrono de alto rendimiento.
*   `aiosqlite`: Driver asíncrono para SQLite.
*   `pydantic`: Validación de datos mediante los Schemas.
*   `python-jose`: Generación y validación de tokens JWT.
*   `bcrypt`: Hashing seguro de contraseñas de usuarios.

## 3. Estructura de Directorios

```text
backend_venus/
│
├── database.py              # Gestión de la base de datos (aiosqlite + WAL + DDL)
├── main.py                  # Punto de entrada de FastAPI (Lifespan, Cron)
├── schemas.py               # Todos los schemas Pydantic (Auth, Sync, Operacional)
├── config.py                # Pydantic Settings (.env, DATABASE_PATH)
├── .env                     # Variables de entorno
├── requirements.txt         # Dependencias
│
├── routers/                 # Controladores HTTP
│   ├── admin.py             # CRUD de usuarios (Solo Admin)
│   ├── auth.py              # Login y perfil (/me)
│   ├── operacional.py       # Endpoints REST (Facturas, Items, Pagos, Stock, etc.)
│   └── sync.py              # Push, Pull y Upload/Get de imágenes
│
├── services/                # Lógica de negocio encapsulada
│   ├── auth.py              # Seguridad, JWT y RBAC
│   ├── factura_service.py   # Operaciones transaccionales (create, dispatch, status)
│   └── sync.py              # PrefixTransformer y lógica LWW (Last-Write-Wins)
│
└── tests/                   # Suite de pruebas unitarias y de integración (60 tests)
    ├── test_auth.py
    ├── test_database.py
    ├── test_operacional.py
    ├── test_prefix.py
    └── test_sync.py
```

## 4. Detalles de Implementación Clave

### A. La Base de Datos (database.py)
*   **DDL Puro:** Las 11 tablas (usuarios, clientes, facturas, items, envios, pagos, catalogo, stock, cola_trabajos, configuracion, images) se definen utilizando sentencias `CREATE TABLE IF NOT EXISTS`.
*   **Seed Automático:** Al iniciar (`init_db`), si la tabla `usuarios` está vacía, se crea un usuario administrador por defecto (username: `pichardo`) con rol `admin`.
*   **Tipos de Datos Simples:** Los booleanos se manejan como `INTEGER` (0 o 1). Las fechas se guardan como cadenas ISO 8601 en campos `TEXT`.

### B. El Mecanismo de Sincronización (services/sync.py)
*   **PrefixTransformer:** Convierte los IDs numéricos generados por SQLite local en el cliente a cadenas con prefijo en el servidor (ej. Cliente 1 subido por Laura (prefijo 'L') pasa a ser "L1"). Al hacer un `Pull`, se elimina el prefijo para que el cliente reciba de nuevo IDs enteros.
*   **Last-Write-Wins (LWW):** En un `Push`, los registros entrantes se insertan usando `INSERT ... ON CONFLICT(id) DO UPDATE`. La actualización solo ocurre si el `updated_at` (o `created_at`) entrante es estrictamente más reciente que el almacenado en el servidor.
*   **Baja por Deltas (Pull):** El cliente pasa el timestamp de su última sincronización (`last_sync`). El servidor devuelve únicamente los registros con un `updated_at` o `created_at` superior a esa fecha.

### C. Lógica Transaccional (services/factura_service.py)
*   La creación de una factura vía los endpoints operacionales implica hasta 7 pasos ejecutados en una sola transacción SQL:
    1.  Verificar cliente.
    2.  Insertar factura (con saldo calculado).
    3.  Insertar pago inicial (si aplica).
    4.  Insertar cada ítem (deduciendo stock si es un ítem de "stock").
    5.  Actualizar la cadena `items_id` en la factura.
    6.  Insertar en `cola_trabajos` (si hay ítems pendientes o envío a domicilio).
    7.  Crear `envio` (si aplica).
*   **Bypass de Estados:** Si un encargo pasa a estado `procesado` y la factura NO tiene envío a domicilio, el sistema lo promueve automáticamente a estado `completado`.

### D. Seguridad y JWT
*   `services/auth.py` utiliza `bcrypt` directamente en vez de `passlib` (para evitar conflictos de dependencias con versiones modernas de bcrypt).
*   El JWT incrusta los claims `sub` (username), `role` (`admin` o `user`) y `prefix` (`L`, `M`, etc.).
*   Solo los administradores pueden crear nuevos usuarios y gestionar cuentas (activar/desactivar).

### E. Cron de Garantías (main.py)
*   Una tarea asíncrona permanente (`asyncio.create_task`) despierta cada 24 horas y marca como "Expirada" cualquier factura cuyo `venc_garantia` haya superado la fecha actual.

## 5. El Flujo de Trabajo Típico

1.  **Registro:** El dueño (`pichardo`) entra, accede al endpoint `/api/v1/admin/users` y crea una cuenta para un ebanista nuevo, asignándole el prefijo `"T"`.
2.  **Login Flet:** La app desktop del ebanista hace login, recibe un JWT.
3.  **Sincronización:** Cada 5 minutos (o manual), la app desktop dispara `/api/v1/sync/push` con todos los cambios recientes. El servidor transforma los IDs y hace upserts seguros.
4.  **Operación Remota (App Web futura):** El dueño puede consultar o modificar datos desde un portal web utilizando los endpoints operacionales (los IDs ya incluyen prefijo en la web). Las facturas nuevas generadas remotamente obtienen IDs como `"TRc9a7b1..."`.
5.  **Descarga (Pull):** La app desktop dispara `/api/v1/sync/pull?last_sync=...`, recibe los datos modificados por el dueño (o facturas nuevas), y su PrefixTransformer local ignora los prefijos para integrarlos a SQLite sin problemas.
