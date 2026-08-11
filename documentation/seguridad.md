# Seguridad del Backend Venus

Fecha: 2026-08-02  
Estado: **Vulnerabilidades críticas resueltas**

---

## Vulnerabilidades corregidas

Basadas en el análisis documentado en `vulnerabilidades.md`.

---

### 1. JWT con secreto hardcodeado — CRITICAL ✅ Resuelto

**Archivos modificados:** `config.py`, `.env`

**Problema:** `SECRET_KEY` tenía el valor `"dev-secret-key-do-not-use-in-production"` como default en el código fuente. Cualquier atacante con acceso al repositorio podía forjar tokens JWT válidos y hacerse pasar por cualquier usuario, incluido el admin.

**Solución implementada:**

- `SECRET_KEY` ya no tiene ningún valor por defecto en el código (`Optional[str] = None`).
- La clase `Settings` valida en `model_post_init`:
  - Si `SECRET_KEY` es `None` o vacía → `sys.exit(1)` con mensaje claro.
  - Si `ENV=production` y la clave es corta (< 32 chars) o está en la lista de claves inseguras conocidas → `sys.exit(1)`.
- El `.env` local ahora tiene una clave generada con `secrets.token_hex(32)`.

**Para producción:** Ver sección *Pasos en producción* al final de este documento.

---

### 2. Lectura arbitraria de archivos (LFI) via `file_path` — CRITICAL ✅ Resuelto

**Archivos modificados:** `schemas.py`, `services/sync.py`, `routers/sync.py`

**Problema:** El cliente controlaba el campo `images[].file_path` en el payload de sincronización. Este valor se persistía sin validación y luego se usaba directamente en `FileResponse`, permitiendo que un atacante enviara `../../etc/passwd` y leyera archivos arbitrarios del servidor.

**Solución implementada en 3 capas:**

#### Capa 1 — Validación en el schema (`schemas.py`)

El `@field_validator("file_path")` en `ImageIn` rechaza con HTTP 422 cualquier ruta que contenga:
- Path traversal (`..`)
- Rutas absolutas Unix (`/etc/passwd`)
- Prefijos de unidad Windows (`C:\`, `D:/`)
- Rutas UNC (`\\servidor\share`, `//servidor`)
- Null bytes o caracteres de control

#### Capa 2 — Neutralización en el servicio (`services/sync.py`)

En `transform_image`, el `file_path` enviado por el cliente **siempre se descarta** (`d["file_path"] = None`). El backend genera su propia ruta al guardar la imagen física mediante `/upload_image`. Un valor malicioso que llegue al schema nunca se persiste en la BD.

#### Capa 3 — Guard en el router (`routers/sync.py`)

En `GET /sync/image/{id}`, la ruta leída desde la BD se resuelve con `Path.resolve()` y se verifica que esté dentro de `UPLOAD_DIR` con `is_relative_to()`. Si la ruta escapó del directorio permitido → HTTP 403.

---

### 4. Capas de Seguridad Avanzadas (Rate Limiting, 2FA/TOTP, Anti-Ingeniería Inversa, Smart Login) ✅ Implementado

**Archivos modificados:** `config.py`, `database.py`, `schemas.py`, `services/auth.py`, `routers/auth.py`

#### 4.1 Control de Intentos Fallidos y Bloqueo (En Memoria - Opción 1B)
- Se implementó la clase `LoginRateLimiter` para rastrear intentos fallidos por usuario sin persistencia innecesaria en disco.
- Al alcanzar **3 intentos fallidos consecutivos**:
  - Si el usuario **tiene 2FA activo**: Se exige código OTP de 6 dígitos para autenticar.
  - Si el usuario **NO tiene 2FA activo**: Se bloquea la cuenta por **5 minutos** (HTTP 429 Too Many Requests con cabecera `Retry-After`).
- Al iniciar sesión con éxito, el contador de fallos se reinicia automáticamente.

#### 4.2 Autenticación de Dos Factores (2FA / TOTP)
- Implementado utilizando `pyotp` y `qrcode` (RFC 6238).
- Flujo en Configuración de Usuario:
  - `POST /api/v1/auth/2fa/setup`: Genera clave secreta y código QR en Base64 PNG + URL `otpauth://`.
  - `POST /api/v1/auth/2fa/enable`: Valida 1 código OTP ingresado por el usuario para confirmar la sincronización de la app autenticadora antes de activar `totp_enabled = 1`.
  - `POST /api/v1/auth/2fa/disable`: Desactiva 2FA previa confirmación de clave o código OTP.
  - `GET /api/v1/auth/2fa/status`: Consulta el estado de activación de 2FA.

#### 4.3 Regla Anti-Ingeniería Inversa (Detección de Probing / Sonda)
- Si un cliente envía un `otp_code` en el request de inicio de sesión cuando la cuenta **NO requiere OTP** (`totp_enabled == 0`, intentos < 3 y IP segura), el backend lo detecta como intento de sonda o ingeniería inversa.
- **Acción:** La cuenta se bloquea automáticamente por **5 minutos** retornando HTTP 429.

#### 4.4 Inicio de Sesión Inteligente (Detección por IP / GeoIP)
- Inspecciona la IP del cliente (`X-Forwarded-For`, `X-Real-IP`, o `client.host`).
- Mediante la librería `geoip2` y la base de datos GeoIP local `GeoLite2-Country.mmdb`, valida si la IP proviene de un país fuera del listado permitido (por defecto `['DO']`).
- Si la IP es extranjera o sospechosa, se requiere verificación obligatoria por código OTP.

---

## Credenciales administrativas por defecto — HIGH ✅ Parcialmente resuelto

**Archivos:** `config.py`, `database.py`

**Estado:** La contraseña `admin123` del usuario seed se mantiene como default en `ADMIN_DEFAULT_PASSWORD` para facilitar el primer login. El usuario debe **cambiarla desde la aplicación después del primer acceso**.

El riesgo se mitiga porque:
- La contraseña se almacena siempre hasheada con bcrypt.
- Solo se inserta con `INSERT OR IGNORE` (no reemplaza si ya existe).
- En producción, si se configura `ADMIN_DEFAULT_PASSWORD` en el entorno del contenedor, sobreescribe el default.

---

## Tests de seguridad

Archivo: [`tests/test_security.py`](../tests/test_security.py)

```
pytest tests/test_security.py -v
# 30 passed in 0.28s
```

Cobertura:
- 7 tests de validación de `SECRET_KEY` (ausente, vacía, insegura, fuerte).
- 12 tests de rutas maliciosas en `ImageIn.file_path`.
- 5 tests de rutas seguras aceptadas.
- 6 tests de path-traversal en la lógica de resolución del router.

---

## Pasos en producción — Lo que debes hacer tú

> [!IMPORTANT]
> Estas acciones son **obligatorias** antes de desplegar en producción.

### 1. Generar una SECRET_KEY fuerte

En tu máquina o en el CI:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Guarda el resultado. **No lo pongas en ningún archivo del repositorio.**

### 2. Configurar los secretos en el contenedor Docker

En tu `docker-compose.yml` o en el sistema de secretos de tu plataforma:

```yaml
environment:
  ENV: production
  SECRET_KEY: <tu_clave_de_64_chars>
  ADMIN_DEFAULT_PASSWORD: <contraseña_fuerte_para_primer_login>
  DATABASE_PATH: /data/venus.db
  UPLOAD_DIR: /data/uploads
```

O con secretos Docker Swarm / Kubernetes secrets — lo que uses.

### 3. Verificar que el arranque falla sin clave

Sin `SECRET_KEY` configurada, el servidor debe imprimir:

```
[VENUS SECURITY ERROR] SECRET_KEY no está configurada. ...
```

y **no arrancar**. Esto es comportamiento correcto.

### 4. Cambiar la contraseña del admin en el primer login

Después del primer arranque, entra a la app con `admin123` y cámbiala desde el panel de administración. Una vez cambiada, la variable `ADMIN_DEFAULT_PASSWORD` ya no tiene efecto.
