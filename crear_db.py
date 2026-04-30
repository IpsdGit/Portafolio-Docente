import sqlite3
import os
from werkzeug.security import generate_password_hash

ruta_db = os.path.join(os.path.dirname(__file__), 'portafolio.db')
conexion = sqlite3.connect(ruta_db)
cursor   = conexion.cursor()

# --- Tabla de Usuarios ---
cursor.execute('''
CREATE TABLE IF NOT EXISTS Usuarios (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre   TEXT NOT NULL,
    correo   TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    rol      TEXT NOT NULL
)
''')

# --- Tabla de Documentos ---
cursor.execute('''
CREATE TABLE IF NOT EXISTS Documentos (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id       INTEGER NOT NULL,
    nombre_actividad TEXT,
    tipo_formacion   TEXT,
    institucion      TEXT,
    fecha_emision    TEXT,
    horas            INTEGER,
    estado           TEXT DEFAULT 'Pendiente',
    url_archivo      TEXT,
    fecha_registro   DATETIME,
    comentario_admin TEXT,
    FOREIGN KEY(usuario_id) REFERENCES Usuarios(id)
)
''')

# --- Usuarios de prueba (solo si la tabla está vacía) ---
cursor.execute("SELECT COUNT(*) FROM Usuarios")
if cursor.fetchone()[0] == 0:
    cursor.execute(
        "INSERT INTO Usuarios (nombre, correo, password, rol) VALUES (?, ?, ?, ?)",
        ('Admin General',  'admin@unah.edu.hn',
         generate_password_hash('Admin2026!'), 'Administrador')
    )
    cursor.execute(
        "INSERT INTO Usuarios (nombre, correo, password, rol) VALUES (?, ?, ?, ?)",
        ('Profesor Prueba', 'profesor@unah.edu.hn',
         generate_password_hash('Docente2026!'), 'Docente')
    )
    print("Usuarios de prueba creados:")
    print("  Admin    → admin@unah.edu.hn   / Admin2026!")
    print("  Docente  → profesor@unah.edu.hn / Docente2026!")
else:
    print("La base de datos ya tiene usuarios registrados.")

conexion.commit()
conexion.close()
print("Base de datos lista.")