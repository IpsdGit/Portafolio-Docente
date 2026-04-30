import sqlite3
import os

ruta_db  = os.path.join(os.path.dirname(__file__), 'portafolio.db')
conexion = sqlite3.connect(ruta_db)
cursor   = conexion.cursor()

# Agregar columnas nuevas si no existen (migracion segura)
columnas_nuevas = [
    ("fecha_registro",   "DATETIME"),
    ("comentario_admin", "TEXT"),
]

cursor.execute("PRAGMA table_info(Documentos)")
columnas_existentes = {row[1] for row in cursor.fetchall()}

for nombre_col, tipo_col in columnas_nuevas:
    if nombre_col not in columnas_existentes:
        cursor.execute(f"ALTER TABLE Documentos ADD COLUMN {nombre_col} {tipo_col}")
        print(f"  ✔ Columna '{nombre_col}' agregada.")
    else:
        print(f"  · Columna '{nombre_col}' ya existe.")

conexion.commit()
conexion.close()
print("Migración de tabla Documentos completada.")