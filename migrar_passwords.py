import sqlite3
import os
from werkzeug.security import generate_password_hash

db  = os.path.join(os.path.dirname(__file__), 'portafolio.db')
con = sqlite3.connect(db)
con.row_factory = sqlite3.Row

usuarios     = con.execute('SELECT id, correo, password FROM Usuarios').fetchall()
actualizados = 0

for u in usuarios:
    pwd = u['password']
    # Si la contraseña no tiene el prefijo de werkzeug es texto plano
    if not (pwd.startswith('pbkdf2:') or pwd.startswith('scrypt:') or pwd.startswith('bcrypt:')):
        nuevo_hash = generate_password_hash(pwd)
        con.execute('UPDATE Usuarios SET password = ? WHERE id = ?', (nuevo_hash, u['id']))
        print(f"  Hasheado: {u['correo']}  (pwd plano: {pwd})")
        actualizados += 1
    else:
        print(f"  Ya hasheado: {u['correo']}")

con.commit()
con.close()
print(f"Actualizados: {actualizados} usuario(s).")
