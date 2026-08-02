import sqlite3
import os

DB_PATH = 'C:/Users/yrpc1/OneDrive/Documentos/Python/backend_venus/venus.db'

def migrate():
    if not os.path.exists(DB_PATH):
        print(f"Base de datos no encontrada en {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # Renombrar columna en stock
        print("Renombrando 'color' a 'tela' en la tabla 'stock'...")
        cursor.execute("ALTER TABLE stock RENAME COLUMN color TO tela;")
        print("Exito en 'stock'.")
    except sqlite3.OperationalError as e:
        print(f"Error al migrar 'stock' (tal vez ya existe o no hay columna color): {e}")

    try:
        # Renombrar columna en items
        print("Renombrando 'color' a 'tela' en la tabla 'items'...")
        cursor.execute("ALTER TABLE items RENAME COLUMN color TO tela;")
        print("Exito en 'items'.")
    except sqlite3.OperationalError as e:
        print(f"Error al migrar 'items': {e}")

    conn.commit()
    conn.close()
    print("Migración finalizada.")

if __name__ == '__main__':
    migrate()
