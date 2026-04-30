import sqlite3, os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from werkzeug.security import generate_password_hash

db  = os.path.join(os.path.dirname(__file__), 'portafolio.db')
con = sqlite3.connect(db)
con.row_factory = sqlite3.Row

print("=== USUARIOS ACTUALES EN LA BASE DE DATOS ===")
usuarios = con.execute('SELECT id, nombre, correo, rol, password FROM Usuarios').fetchall()
for u in usuarios:
    pwd = u['password']
    formato = "HASH OK" if (pwd.startswith('pbkdf2:') or pwd.startswith('scrypt:')) else "TEXTO PLANO"
    print(f"  [{u['id']}] {u['correo']} | {u['rol']} | {formato}")

print("\n=== RESETEANDO CONTRASENAS ===")
# Resetear admin
con.execute("UPDATE Usuarios SET password=? WHERE correo='admin@unah.edu.hn'",
            (generate_password_hash('Admin2026!'),))
print("  admin@unah.edu.hn  -> Admin2026!")

# Resetear todos los docentes de prueba
con.execute("UPDATE Usuarios SET password=? WHERE correo='profesor@unah.edu.hn'",
            (generate_password_hash('Docente2026!'),))
print("  profesor@unah.edu.hn -> Docente2026!")

con.commit()
con.close()
print("\nListo. Credenciales actualizadas.")
