# ==============================================================================
# Venus Backend — Dockerfile (Alpine Linux)
# ==============================================================================
FROM python:3.11-alpine

# Evitar generación de bytecode .pyc y forzar buffer directo en stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Instalar dependencias del sistema operativo en Alpine
# Incluye herramientas de compilación y librerías gráficas para WeasyPrint (Cairo/Pango/GObject)
RUN apk add --no-cache \
    build-base \
    libffi-dev \
    python3-dev \
    cairo \
    pango \
    gdk-pixbuf \
    fontconfig \
    font-dejavu \
    harfbuzz \
    jpeg-dev \
    zlib-dev \
    openjpeg-dev \
    libxml2-dev \
    libxslt-dev

# Copiar requirements e instalar dependencias de Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código fuente completo
COPY . .

# Crear directorios para persistencia de datos y subida de imágenes
RUN mkdir -p /app/data /app/uploads

# Exponer el puerto por defecto de FastAPI / Uvicorn
EXPOSE 8000

# Comando de inicio del servidor Uvicorn
CMD ["uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"]
