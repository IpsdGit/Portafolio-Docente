# -*- coding: utf-8 -*-
# migrar_v2.py
# Migracion segura para Portafolio Docente v2.
# Crea las tablas nuevas si no existen, sin tocar datos anteriores.
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import sqlite3
import os

ruta_db  = os.path.join(os.path.dirname(__file__), 'portafolio.db')
conexion = sqlite3.connect(ruta_db)
cursor   = conexion.cursor()

# ─────────────────────────────────────────
#  TABLA: PerfilDocente
# ─────────────────────────────────────────
cursor.execute('''
CREATE TABLE IF NOT EXISTS PerfilDocente (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id         INTEGER UNIQUE NOT NULL,
    curriculum         TEXT,
    facultad           TEXT,
    departamento       TEXT,
    filosofia_ensenanza TEXT,
    premios            TEXT,
    responsabilidad    TEXT DEFAULT 'Ninguna',
    foto_url           TEXT,
    FOREIGN KEY(usuario_id) REFERENCES Usuarios(id)
)
''')
print("  ✔ Tabla 'PerfilDocente' verificada.")

# ─────────────────────────────────────────
#  TABLA: MisClases
# ─────────────────────────────────────────
cursor.execute('''
CREATE TABLE IF NOT EXISTS MisClases (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id           INTEGER NOT NULL,
    periodo              TEXT NOT NULL,
    nombre_espacio       TEXT NOT NULL,
    disenio_curricular   TEXT,
    codigo               TEXT,
    naturaleza           TEXT,
    modalidad            TEXT,
    uv_ca                TEXT,
    descripcion_minima   TEXT,
    fecha_creacion       DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(usuario_id) REFERENCES Usuarios(id)
)
''')
print("  ✔ Tabla 'MisClases' verificada.")

# ─────────────────────────────────────────
#  TABLA: EvidenciasClase
# ─────────────────────────────────────────
cursor.execute('''
CREATE TABLE IF NOT EXISTS EvidenciasClase (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    clase_id        INTEGER NOT NULL,
    tipo_evidencia  TEXT NOT NULL,
    nombre          TEXT NOT NULL,
    url_archivo     TEXT NOT NULL,
    fecha_registro  DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(clase_id) REFERENCES MisClases(id)
)
''')
print("  ✔ Tabla 'EvidenciasClase' verificada.")

conexion.commit()
conexion.close()
print("\n✅ Migración v2 completada. Todas las tablas están listas.")
