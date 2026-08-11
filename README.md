# backend-venus

Backend REST API para **Venus Muebles**, construido con **Python + FastAPI**.

Este servicio centraliza la información de usuarios y datos sincronizados desde clientes locales (app desktop), y la expone para consumo de la aplicación web.

## Características

- API REST con FastAPI
- Estructura simple y mantenible
- Seguridad básica para gestión de usuarios y contraseñas
- Documentación automática de endpoints (`/docs` y `/redoc`)
- Preparado para ejecución local y en contenedor Docker

## Requisitos

- Python 3.10+ (recomendado 3.11)
- `pip`
- (Opcional) Docker

## Instalación local

1. Clona el repositorio:

```bash
git clone https://github.com/yrpCODEmaker/backend-venus.git
cd backend-venus
```

2. Crea y activa un entorno virtual:

```bash
python -m venv .venv
# Windows (PowerShell)
.\.venv\Scripts\Activate.ps1
# Windows (CMD)
.\.venv\Scripts\activate.bat
# Linux/macOS
source .venv/bin/activate
```

3. Instala dependencias:

```bash
pip install -r requirements.txt
```

> Si el proyecto usa archivo `.env`, crea uno en la raíz con las variables necesarias.

## Ejecutar con Uvicorn (accesible desde otras máquinas)

Para exponer el backend en todas las interfaces de red y permitir acceso desde otros dispositivos de la red (por ejemplo, frontend en otra máquina), ejecuta:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

- `--host 0.0.0.0` permite escuchar en todas las interfaces.
- `--port 8000` define el puerto del servicio.
- `--reload` útil en desarrollo (reinicio automático).

### URLs importantes

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

### Acceso desde otra máquina

Si el backend corre en una máquina de la red local con IP `192.168.1.50`, el frontend debe usar:

- `http://192.168.1.50:8000`

Además, verifica:

- Firewall del sistema permita el puerto `8000`
- El router/red permita comunicación entre dispositivos
- Configuración CORS del backend incluya el origen del frontend

## Levantar el backend con Docker

### 1) Construir imagen

Desde la raíz del proyecto (donde está el `Dockerfile`):

```bash
docker build -t backend-venus:latest .
```

### 2) Ejecutar contenedor

```bash
docker run --name backend-venus -p 8000:8000 backend-venus:latest
```

Esto publica el servicio en `http://localhost:8000`.

Si necesitas pasar variables de entorno:

```bash
docker run --name backend-venus -p 8000:8000 --env-file .env backend-venus:latest
```

### 3) Ver logs y detener

```bash
docker logs -f backend-venus
```

```bash
docker stop backend-venus
```

```bash
docker rm backend-venus
```

## Ejemplo de desarrollo con Docker (hot reload)

Si tu Dockerfile/compose está preparado para desarrollo, normalmente se monta volumen y se usa reload. Ejemplo genérico:

```bash
docker run --name backend-venus-dev -p 8000:8000 -v ${PWD}:/app backend-venus:latest
```

## Pruebas

Si el proyecto usa `pytest`:

```bash
pytest -q
```

## Estructura (resumen)

- `app/` lógica de la API (rutas, modelos, servicios)
- `tests/` pruebas automatizadas
- `documentation/` documentación funcional/técnica
- `endpoints.md` catálogo de endpoints

## Notas

- Mantener la arquitectura sencilla y robusta.
- Actualizar `documentation/` y `endpoints.md` cuando haya cambios funcionales o de API.
- Para integración con frontend en otra máquina, usar URL con IP real del host backend, no `localhost`.
