#!/bin/bash
# ==============================================================================
# Venus Backend — Asistente de Configuración (Setup)
# ==============================================================================
# Genera el entorno para Producción interactivamente.
# ==============================================================================

ENV_FILE=".env"

# Funciones de ayuda para preguntas interactivas
ask() {
    local prompt="$1"
    local default_val="$2"
    local var_name="$3"
    read -p "$prompt [$default_val]: " input
    if [ -z "$input" ]; then
        eval $var_name="'$default_val'"
    else
        eval $var_name="'$input'"
    fi
}

ask_yes_no() {
    local prompt="$1"
    local var_name="$2"
    while true; do
        read -p "$prompt [y/N]: " yn
        case $yn in
            [Yy]* ) eval $var_name=1; break;;
            [Nn]* | "" ) eval $var_name=0; break;;
            * ) echo "Por favor, responde 'y' o 'n'.";;
        esac
    done
}

echo "======================================================"
echo " Venus Backend — Asistente de Configuración           "
echo "======================================================"
echo ""

# 1. Chequeo de .env existente
UPDATE_ENV=1
if [ -f "$ENV_FILE" ]; then
    echo "El archivo $ENV_FILE ya existe."
    ask_yes_no "¿Deseas actualizarlo?" UPDATE_ENV
    if [ "$UPDATE_ENV" -eq 0 ]; then
        START_CONTAINER=0
        ask_yes_no "¿Deseas levantar el contenedor?" START_CONTAINER
        if [ "$START_CONTAINER" -eq 1 ]; then
            echo "Levantando contenedor..."
            set +e
            OUTPUT=$(docker compose up -d --build 2>&1)
            STATUS=$?
            set -e
            if [ $STATUS -ne 0 ]; then
                echo ""
                echo "[ERROR] El levantamiento del contenedor ha fallado. Detalles:"
                echo "$OUTPUT"
                exit 1
            fi
            echo "[✔] Contenedor levantado exitosamente."
        fi
        exit 0
    fi
fi

# 2. Pedir parámetros de Administrador
echo ""
echo "--- Configuración de credenciales de Administrador ---"
ask "Usuario administrador" "admin" ADMIN_USER
ask "Contraseña administrador" "admin" ADMIN_PASS

# 3. Configuración de JWT
echo ""
echo "--- Configuración de Seguridad (JWT) ---"
ask_yes_no "¿Deseas generar la clave JWT (SECRET_KEY) automáticamente?" AUTO_JWT
if [ "$AUTO_JWT" -eq 1 ]; then
    set +e
    if command -v openssl >/dev/null 2>&1; then
        JWT_SECRET=$(openssl rand -hex 32 2>&1)
        STATUS=$?
    elif command -v python3 >/dev/null 2>&1; then
        JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))" 2>&1)
        STATUS=$?
    else
        # Fallback en caso de que no haya openssl ni python3
        JWT_SECRET=$(head -c 32 /dev/urandom | xxd -p | tr -d '\n' 2>&1)
        STATUS=$?
    fi
    set -e
    
    if [ $STATUS -ne 0 ]; then
        echo ""
        echo "[ERROR] La generación de la clave secreta ha fallado. Detalles:"
        echo "$JWT_SECRET"
        exit 1
    fi
    echo "[✔] Clave JWT generada automáticamente."
else
    ask "Ingresa tu SECRET_KEY personalizado" "cambiame-en-produccion-por-algo-seguro" JWT_SECRET
fi

# 4. Configuración de Almacenamiento
echo ""
echo "--- Configuración de Almacenamiento ---"
ask_yes_no "¿Deseas modificar la ruta donde se guarda la base de datos?" MOD_DB
if [ "$MOD_DB" -eq 1 ]; then
    ask "Ruta de la base de datos (DATABASE_PATH)" "/mnt/db/venus.db" DB_PATH
else
    DB_PATH=""
fi

ask_yes_no "¿Deseas modificar la ruta donde se suben las fotos?" MOD_UPLOAD
if [ "$MOD_UPLOAD" -eq 1 ]; then
    ask "Ruta de las fotos (UPLOAD_DIR)" "/mnt/db/uploads" UPLOAD_DIR
else
    UPLOAD_DIR=""
fi

# 5. Escribir .env
echo ""
echo "Generando $ENV_FILE..."
cat <<EOF > "$ENV_FILE"
# ── Configuración generada por asistente ──
ENV=production

# ── Almacenamiento ──
EOF

if [ -n "$DB_PATH" ]; then
    echo "DATABASE_PATH=$DB_PATH" >> "$ENV_FILE"
fi
if [ -n "$UPLOAD_DIR" ]; then
    echo "UPLOAD_DIR=$UPLOAD_DIR" >> "$ENV_FILE"
fi

cat <<EOF >> "$ENV_FILE"

# ── JWT ──
SECRET_KEY=$JWT_SECRET
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=60

# ── Seed (usuario y contraseña inicial) ──
ADMIN_DEFAULT_USERNAME=$ADMIN_USER
ADMIN_DEFAULT_PASSWORD=$ADMIN_PASS
EOF
echo "[✔] Archivo $ENV_FILE guardado exitosamente."

# 6. Levantar contenedor automáticamente
echo ""
ask_yes_no "¿Deseas levantar el contenedor automáticamente ahora?" START_CONTAINER_END
if [ "$START_CONTAINER_END" -eq 1 ]; then
    echo "Levantando contenedor..."
    set +e
    OUTPUT=$(docker compose up -d --build 2>&1)
    STATUS=$?
    set -e
    if [ $STATUS -ne 0 ]; then
        echo ""
        echo "[ERROR] El levantamiento del contenedor ha fallado. Detalles:"
        echo "$OUTPUT"
        exit 1
    fi
    echo "[✔] Contenedor levantado exitosamente."
fi

echo ""
echo "======================================================"
echo " ¡Configuración Completada!                           "
echo "======================================================"
exit 0
