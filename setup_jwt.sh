#!/bin/bash
# ==============================================================================
# Venus Backend — Script de Configuración de JWT Secret Key para Debian / Linux
# ==============================================================================
# Genera una clave JWT segura de 64 caracteres hexadecimales si no existe y la
# establece en el archivo .env y en el entorno de Debian para que docker compose
# la inyecte de manera segura al contenedor Alpine sin requerir intervención manual.
# ==============================================================================

set -e

ENV_FILE=".env"

echo "======================================================"
echo " Venus Backend — Configuración de Clave Secreta JWT   "
echo "======================================================"

# 1. Generar la clave secreta con openssl, python3 o /dev/urandom
if command -v openssl >/dev/null 2>&1; then
    NEW_SECRET_KEY=$(openssl rand -hex 32)
elif command -v python3 >/dev/null 2>&1; then
    NEW_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
else
    NEW_SECRET_KEY=$(head -c 32 /dev/urandom | xxd -p | tr -d '\n')
fi

if [ -z "$NEW_SECRET_KEY" ]; then
    echo "[ERROR] No se pudo generar la clave secreta JWT."
    exit 1
fi

echo "[✔] Clave JWT de 64 caracteres (hex) generada correctamente."

# 2. Configurar o actualizar la variable SECRET_KEY en .env
if [ -f "$ENV_FILE" ]; then
    if grep -q "^SECRET_KEY=" "$ENV_FILE"; then
        # Actualiza clave en .env existente
        sed -i 's/^SECRET_KEY=.*/SECRET_KEY='"$NEW_SECRET_KEY"'/' "$ENV_FILE"
        echo "[✔] Variable SECRET_KEY actualizada en $ENV_FILE"
    else
        echo "SECRET_KEY=$NEW_SECRET_KEY" >> "$ENV_FILE"
        echo "[✔] Variable SECRET_KEY agregada a $ENV_FILE"
    fi
else
    echo "SECRET_KEY=$NEW_SECRET_KEY" > "$ENV_FILE"
    echo "[✔] Archivo $ENV_FILE creado con la variable SECRET_KEY"
fi

# 3. Exportar para la sesión de shell actual en Debian
export SECRET_KEY="$NEW_SECRET_KEY"

# 4. Añadir a ~/.bashrc para que persista entre reinicios de shell en Debian
if [ -f "$HOME/.bashrc" ]; then
    if ! grep -q "SECRET_KEY=" "$HOME/.bashrc"; then
        echo "export SECRET_KEY=\"$NEW_SECRET_KEY\"" >> "$HOME/.bashrc"
        echo "[✔] Variable SECRET_KEY agregada a $HOME/.bashrc para entorno Debian"
    fi
fi

echo ""
echo "======================================================"
echo " ¡Configuración Exitosa!                              "
echo "======================================================"
echo " La variable SECRET_KEY está lista para Docker Compose."
echo " Para desplegar el servidor backend en Alpine ejecuta: "
echo "   docker compose up -d --build                       "
echo "======================================================"
