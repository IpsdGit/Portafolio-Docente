import os
import csv
import io
import sqlite3
from datetime import datetime
from flask import (Flask, render_template, request, session,
                   redirect, url_for, flash, jsonify, Response)
from werkzeug.security import generate_password_hash, check_password_hash
import firebase_admin
from firebase_admin import credentials, storage

# ─────────────────────────────────────────────
#  CONFIGURACIÓN DE LA APLICACIÓN
# ─────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__, 
            template_folder=os.path.join(BASE_DIR, 'templates'), 
            static_folder=os.path.join(BASE_DIR, 'static'))

app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'portafolio_unah_dev_2026_s3cr3t!')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024   # 16 MB máximo
DB_PATH  = os.path.join(BASE_DIR, 'portafolio.db')

# --- AUTO-PARCHES ACUMULADOS ---
columnas_perfil = [
    'cv_url', 'redes_sociales', 'grado_academico', 'grado_url', 
    'licenciatura', 'licenciatura_url', 'maestria', 'maestria_url', 'doctorado', 'doctorado_url', 'premios_url'
]
for col in columnas_perfil:
    try:
        _conn = sqlite3.connect(DB_PATH)
        _conn.execute(f"ALTER TABLE PerfilDocente ADD COLUMN {col} TEXT")
        _conn.commit()
        _conn.close()
    except: pass

try:
    _conn = sqlite3.connect(DB_PATH)
    _conn.execute("ALTER TABLE EvidenciasClase ADD COLUMN estado_evaluacion TEXT DEFAULT 'Sin Revisar'")
    _conn.execute("ALTER TABLE EvidenciasClase ADD COLUMN comentario_admin TEXT")
    _conn.execute("ALTER TABLE EvidenciasClase ADD COLUMN feedback_leido INTEGER DEFAULT 0")
    _conn.commit()
    _conn.close()
except: pass

try:
    _conn = sqlite3.connect(DB_PATH)
    _conn.execute("""
        CREATE TABLE IF NOT EXISTS TitulosDocente (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER,
            nivel TEXT,
            nombre_titulo TEXT,
            url_archivo TEXT
        )
    """)
    _conn.commit()
    
    _conn.row_factory = sqlite3.Row
    perfiles_viejos = _conn.execute("SELECT usuario_id, licenciatura, licenciatura_url, maestria, maestria_url, doctorado, doctorado_url FROM PerfilDocente").fetchall()
    for p in perfiles_viejos:
        uid = p['usuario_id']
        ya_migrado = _conn.execute("SELECT id FROM TitulosDocente WHERE usuario_id=?", (uid,)).fetchone()
        if not ya_migrado:
            if p['licenciatura']: _conn.execute("INSERT INTO TitulosDocente (usuario_id, nivel, nombre_titulo, url_archivo) VALUES (?, ?, ?, ?)", (uid, 'Licenciatura', p['licenciatura'], p['licenciatura_url']))
            if p['maestria']: _conn.execute("INSERT INTO TitulosDocente (usuario_id, nivel, nombre_titulo, url_archivo) VALUES (?, ?, ?, ?)", (uid, 'Maestría', p['maestria'], p['maestria_url']))
            if p['doctorado']: _conn.execute("INSERT INTO TitulosDocente (usuario_id, nivel, nombre_titulo, url_archivo) VALUES (?, ?, ?, ?)", (uid, 'Doctorado', p['doctorado'], p['doctorado_url']))
    _conn.commit()
    _conn.close()
except Exception as e: print("Error en parche V2.6:", e)

try:
    _conn = sqlite3.connect(DB_PATH)
    _conn.execute("""
        CREATE TABLE IF NOT EXISTS ReflexionesClase (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clase_id INTEGER,
            fecha_registro TEXT,
            contenido TEXT,
            url_instrumento TEXT
        )
    """)
    _conn.commit()
    _conn.close()
except Exception as e: print("Error en parche Reflexiones:", e)

# Parche: columna 'activo' en Usuarios (para gestión de cuentas)
try:
    _conn = sqlite3.connect(DB_PATH)
    _conn.execute("ALTER TABLE Usuarios ADD COLUMN activo INTEGER DEFAULT 1")
    _conn.commit()
    _conn.close()
except: pass

# Parche: columna 'filosofia_url' en PerfilDocente
try:
    _conn = sqlite3.connect(DB_PATH)
    _conn.execute("ALTER TABLE PerfilDocente ADD COLUMN filosofia_url TEXT")
    _conn.commit()
    _conn.close()
except: pass

# Parche V3: Carreras, cargos de autoridad, catálogo de evidencias y categorías por clase
try:
    _conn = sqlite3.connect(DB_PATH)
    _conn.execute("""
        CREATE TABLE IF NOT EXISTS Carreras (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE NOT NULL,
            facultad TEXT DEFAULT ''
        )
    """)
    _conn.execute("""
        CREATE TABLE IF NOT EXISTS CatalogoEvidencias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE NOT NULL,
            activo INTEGER DEFAULT 1
        )
    """)
    _conn.execute("""
        CREATE TABLE IF NOT EXISTS ClaseTiposEvidencia (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clase_id INTEGER NOT NULL,
            nombre TEXT NOT NULL,
            UNIQUE(clase_id, nombre)
        )
    """)
    _conn.commit()
    _conn.close()
except Exception as e: print("Error en parche V3 tablas:", e)

for _col_u in ['carrera_id INTEGER', 'cargo_admin TEXT']:
    try:
        _conn = sqlite3.connect(DB_PATH)
        _conn.execute(f"ALTER TABLE Usuarios ADD COLUMN {_col_u}")
        _conn.commit()
        _conn.close()
    except: pass
# ------------------------------------------------------------------------

TIPOS_FORMACION = ['Taller', 'Seminario', 'Diplomado', 'Posgrado', 'Congreso', 'Jornada Pedagógica', 'Curso en Línea (MOOC)', 'Práctica Docente', 'Otro']
TIPOS_EVIDENCIA = ['Planificación Didáctica', 'Material Didáctico', 'Instrumento de Evaluación (Rúbricas, Ejercicios, Proyectos)', 'Asignaciones para Estudiantes (Tareas, Ejercicios, Talleres)', 'Evidencias Fotográficas (Talleres, Trabajos de Campo)', 'Evaluación Docente', 'Bibliografía', 'Registro de Calificaciones', 'Actividades de Vinculación', 'Actividades de Investigación', 'Horas de Tutoría', 'Otras Actividades']
NATURALEZA_OPTS   = ['Teórica', 'Práctica', 'Mixta', 'Laboratorio']
MODALIDAD_OPTS    = ['Presencial', 'Virtual', 'B-learning', 'Teledocencia']
RESPONSABILIDAD_OPTS = ['Ninguna', 'Jefe de Departamento', 'Coordinador de Carrera', 'Ambas', 'Otros']
CARGOS_ADMIN_OPTS = ['Jefe de Departamento', 'Coordinador de Carrera']

# Sembrar CatalogoEvidencias con las 12 categorías base si está vacío
try:
    _conn = sqlite3.connect(DB_PATH)
    _cnt = _conn.execute("SELECT COUNT(*) FROM CatalogoEvidencias").fetchone()[0]
    if _cnt == 0:
        for _t in TIPOS_EVIDENCIA:
            _conn.execute("INSERT OR IGNORE INTO CatalogoEvidencias (nombre, activo) VALUES (?, 1)", (_t,))
        _conn.commit()
    _conn.close()
except Exception as e: print("Error sembrando CatalogoEvidencias:", e)

# SOLUCIÓN: Agregamos Word (.doc, .docx) y Excel (.xls, .xlsx) a los permisos
EXTENSIONES_PERMITIDAS = {'pdf', 'jpg', 'jpeg', 'png', 'doc', 'docx', 'xls', 'xlsx'}

cred_path = os.path.join(BASE_DIR, 'credenciales.json')
if not firebase_admin._apps:
    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred, {
        'storageBucket': 'portafoliodocente-2d7c6.firebasestorage.app'
    })
bucket = storage.bucket()

def obtener_conexion():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def extension_permitida(filename):
    return ('.' in filename and filename.rsplit('.', 1)[1].lower() in EXTENSIONES_PERMITIDAS)

def requiere_login(rol=None):
    if 'usuario_id' not in session: return False
    if rol and session.get('rol') != rol: return False
    return True

# Correos con acceso a Gestión de Usuarios (Super Admins)
SUPER_ADMIN_EMAILS = ['bayron@unah.edu.hn', 'admin@unah.edu.hn']

def es_superadmin():
    return session.get('correo') in SUPER_ADMIN_EMAILS

def obtener_catalogo_evidencias(con, solo_activos=True):
    if solo_activos:
        return con.execute("SELECT * FROM CatalogoEvidencias WHERE activo = 1 ORDER BY id ASC").fetchall()
    return con.execute("SELECT * FROM CatalogoEvidencias ORDER BY id ASC").fetchall()

def obtener_tipos_clase(con, clase_id):
    filas = con.execute("SELECT nombre FROM ClaseTiposEvidencia WHERE clase_id = ? ORDER BY id ASC", (clase_id,)).fetchall()
    if not filas:
        catalogo = obtener_catalogo_evidencias(con, solo_activos=True)
        nombres_base = [r['nombre'] for r in catalogo] if catalogo else list(TIPOS_EVIDENCIA)
        for nom in nombres_base:
            con.execute("INSERT OR IGNORE INTO ClaseTiposEvidencia (clase_id, nombre) VALUES (?, ?)", (clase_id, nom))
        con.commit()
        tipos = list(nombres_base)
    else:
        tipos = [r['nombre'] for r in filas]

    # Garantizar que si ya existen archivos con algún tipo histórico, no se oculten
    existentes = con.execute("SELECT DISTINCT tipo_evidencia FROM EvidenciasClase WHERE clase_id = ?", (clase_id,)).fetchall()
    for ex in existentes:
        t = ex['tipo_evidencia']
        if t and t not in tipos:
            tipos.append(t)
    return tipos

def obtener_scope_admin(con):
    if es_superadmin():
        return {
            'es_superadmin': True,
            'carrera_id': None,
            'carrera_nombre': 'Todas las Carreras',
            'cargo': 'Super Administrador',
            'sin_carrera': False
        }
    uid = session.get('usuario_id')
    row = con.execute("""
        SELECT u.carrera_id, u.cargo_admin, c.nombre AS carrera_nombre
        FROM Usuarios u
        LEFT JOIN Carreras c ON u.carrera_id = c.id
        WHERE u.id = ?
    """, (uid,)).fetchone()
    if not row or not row['carrera_id']:
        return {
            'es_superadmin': False,
            'carrera_id': None,
            'carrera_nombre': 'Sin carrera asignada',
            'cargo': (row['cargo_admin'] if row and row['cargo_admin'] else 'Administrador'),
            'sin_carrera': True
        }
    return {
        'es_superadmin': False,
        'carrera_id': row['carrera_id'],
        'carrera_nombre': row['carrera_nombre'] or 'Carrera Asignada',
        'cargo': row['cargo_admin'] or 'Administrador',
        'sin_carrera': False
    }

def admin_puede_ver_docente(con, scope, docente_id):
    if scope['es_superadmin']:
        return True
    if scope['sin_carrera']:
        return False
    row = con.execute("SELECT carrera_id FROM Usuarios WHERE id = ? AND rol = 'Docente'", (docente_id,)).fetchone()
    return bool(row and row['carrera_id'] == scope['carrera_id'])

# Inyectar variables globales en los templates
@app.context_processor
def inject_superadmin():
    return dict(es_superadmin=es_superadmin(), super_admin_emails=SUPER_ADMIN_EMAILS)

def subir_a_firebase(archivo, carpeta):
    from werkzeug.utils import secure_filename
    nombre_seguro = secure_filename(archivo.filename)
    timestamp     = datetime.now().strftime('%Y%m%d_%H%M%S')
    ruta_firebase = f"{carpeta}/{timestamp}_{nombre_seguro}"
    blob = bucket.blob(ruta_firebase)
    blob.upload_from_string(archivo.read(), content_type=archivo.content_type)
    blob.make_public()
    return blob.public_url

@app.context_processor
def inject_notificaciones():
    if session.get('rol') == 'Docente':
        try:
            con = obtener_conexion()
            notifs = con.execute("""
                SELECT e.id as ev_id, e.nombre, e.tipo_evidencia, e.comentario_admin,
                       c.id as clase_id, c.nombre_espacio
                FROM EvidenciasClase e
                JOIN MisClases c ON e.clase_id = c.id
                WHERE c.usuario_id = ? AND e.comentario_admin IS NOT NULL AND e.comentario_admin != '' AND IFNULL(e.feedback_leido, 0) = 0
                ORDER BY e.id DESC
            """, (session.get('usuario_id'),)).fetchall()
            con.close()
            lista_notifs = [dict(n) for n in notifs]
            return dict(total_notificaciones=len(lista_notifs), notificaciones_detalle=lista_notifs)
        except Exception: return dict(total_notificaciones=0, notificaciones_detalle=[])
    return dict(total_notificaciones=0, notificaciones_detalle=[])

# ─────────────────────────────────────────────
#  RUTAS DE AUTENTICACIÓN Y SEGURIDAD
# ─────────────────────────────────────────────
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'usuario_id' in session: return redirect(url_for('panel_admin') if session['rol'] == 'Administrador' else url_for('ver_perfil'))
    if request.method == 'POST':
        correo   = request.form.get('correo', '').strip().lower()
        password = request.form.get('password', '')
        try:
            con = obtener_conexion()
            usuario = con.execute("SELECT * FROM Usuarios WHERE correo = ?", (correo,)).fetchone()
            con.close()
        except Exception:
            flash('Error de conexión.', 'danger')
            return render_template('login.html')
        if usuario and check_password_hash(usuario['password'], password):
            if 'activo' in usuario.keys() and usuario['activo'] == 0:
                flash('Tu cuenta se encuentra desactivada. Contacta al administrador.', 'danger')
                return render_template('login.html')
            session['usuario_id'] = usuario['id']
            session['nombre']     = usuario['nombre']
            session['correo']     = usuario['correo']
            session['rol']        = usuario['rol']
            session.permanent     = True
            return redirect(url_for('panel_admin') if usuario['rol'] == 'Administrador' else url_for('ver_perfil'))
        else:
            flash('Correo o contraseña incorrectos.', 'danger')
    return render_template('login.html')

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    try:
        con = obtener_conexion()
        carreras = con.execute("SELECT id, nombre, facultad FROM Carreras ORDER BY nombre ASC").fetchall()
        con.close()
    except Exception:
        carreras = []

    if request.method == 'POST':
        nombre     = request.form.get('nombre', '').strip()
        correo     = request.form.get('correo', '').strip().lower()
        password   = request.form.get('password', '')
        password2  = request.form.get('password2', '')
        carrera_id = request.form.get('carrera_id', '').strip()
        carrera_val = int(carrera_id) if carrera_id.isdigit() else None

        if len(nombre) < 3 or not correo.endswith('.edu.hn') or len(password) < 8 or password != password2:
            flash('Revisa los requisitos del formulario.', 'warning')
            return render_template('registro.html', carreras=carreras)

        if carreras and not carrera_val:
            flash('Por favor selecciona la carrera a la que perteneces.', 'warning')
            return render_template('registro.html', carreras=carreras)

        try:
            con = obtener_conexion()
            if con.execute("SELECT id FROM Usuarios WHERE correo = ?", (correo,)).fetchone():
                con.close()
                flash('Este correo ya está registrado.', 'warning')
                return render_template('registro.html', carreras=carreras)
            hashed = generate_password_hash(password)
            con.execute(
                "INSERT INTO Usuarios (nombre, correo, password, rol, activo, carrera_id) VALUES (?, ?, ?, 'Docente', 1, ?)",
                (nombre, correo, hashed, carrera_val)
            )
            con.commit()
            con.close()
        except Exception:
            flash('Error al crear la cuenta.', 'danger')
            return render_template('registro.html', carreras=carreras)

        flash('¡Cuenta creada exitosamente!', 'success')
        return redirect(url_for('login'))
    return render_template('registro.html', carreras=carreras)

@app.route('/logout')
def logout():
    session.clear()
    flash('Sesión cerrada correctamente.', 'info')
    return redirect(url_for('login'))

@app.route('/cambiar_password', methods=['POST'])
def cambiar_password():
    if not requiere_login(): return redirect(url_for('login'))
    uid = session['usuario_id']
    actual = request.form.get('password_actual', '')
    nuevo = request.form.get('nuevo_password', '')
    confirmar = request.form.get('confirmar_password', '')

    if nuevo != confirmar or len(nuevo) < 8:
        flash('Verifica las contraseñas nuevas.', 'warning')
        return redirect(request.referrer or url_for('ver_perfil'))

    try:
        con = obtener_conexion()
        usuario = con.execute("SELECT password FROM Usuarios WHERE id = ?", (uid,)).fetchone()
        if not usuario or not check_password_hash(usuario['password'], actual):
            flash('La contraseña actual es incorrecta.', 'danger')
            con.close()
            return redirect(request.referrer or url_for('ver_perfil'))
        nuevo_hash = generate_password_hash(nuevo)
        con.execute("UPDATE Usuarios SET password = ? WHERE id = ?", (nuevo_hash, uid))
        con.commit()
        con.close()
        flash('¡Contraseña actualizada exitosamente!', 'success')
    except Exception:
        flash('Error al actualizar la contraseña.', 'danger')
    return redirect(request.referrer or url_for('ver_perfil'))

# ─────────────────────────────────────────────
#  MÓDULO: MI PERFIL Y TÍTULOS
# ─────────────────────────────────────────────
@app.route('/docente/perfil', methods=['GET', 'POST'])
def ver_perfil():
    if not requiere_login(rol='Docente'): return redirect(url_for('login'))
    uid = session['usuario_id']

    if request.method == 'POST':
        accion = request.form.get('accion', 'guardar_perfil')
        if accion == 'subir_foto':
            foto = request.files.get('foto_file')
            if foto and foto.filename != '' and extension_permitida(foto.filename):
                try:
                    url_foto = subir_a_firebase(foto, f'fotos_perfil/docente_{uid}')
                    con = obtener_conexion()
                    existe = con.execute("SELECT id FROM PerfilDocente WHERE usuario_id=?", (uid,)).fetchone()
                    if existe: con.execute("UPDATE PerfilDocente SET foto_url=? WHERE usuario_id=?", (url_foto, uid))
                    else: con.execute("INSERT INTO PerfilDocente (usuario_id, foto_url) VALUES (?,?)", (uid, url_foto))
                    con.commit()
                    con.close()
                    flash('¡Foto de perfil actualizada!', 'success')
                except Exception as e: flash(f'Error al subir foto: {str(e)}', 'danger')
            else: flash('Archivo de imagen inválido.', 'warning')
            return redirect(url_for('ver_perfil'))

        curriculum          = request.form.get('curriculum', '').strip()
        facultad            = request.form.get('facultad', '').strip()
        departamento        = request.form.get('departamento', '').strip()
        premios             = request.form.get('premios', '').strip()

        premios_url = None
        if 'premios_file' in request.files:
            file = request.files['premios_file']
            if file and file.filename != '' and extension_permitida(file.filename):
                ext = file.filename.rsplit('.', 1)[1].lower()
                blob = bucket.blob(f"premios/{uid}_{int(datetime.now().timestamp())}.{ext}")
                blob.upload_from_file(file, content_type=f"application/{'pdf' if ext=='pdf' else 'image/'+ext}")
                blob.make_public()
                premios_url = blob.public_url
        redes_sociales      = request.form.get('redes_sociales', '').strip()
        filosofia_ensenanza = request.form.get('filosofia_ensenanza', '').strip()
        responsabilidad     = request.form.get('responsabilidad', 'Ninguna')
        if responsabilidad == 'Otros':
            responsabilidad = request.form.get('otra_responsabilidad', '').strip() or 'Otros'

        try:
            con = obtener_conexion()
            perfil_existente = con.execute("SELECT * FROM PerfilDocente WHERE usuario_id=?", (uid,)).fetchone()
            
            cv_url = perfil_existente['cv_url'] if perfil_existente else None
            archivo_cv = request.files.get('cv_file')
            if archivo_cv and archivo_cv.filename != '':
                if extension_permitida(archivo_cv.filename):
                    ext = archivo_cv.filename.rsplit('.', 1)[1].lower()
                    blob = bucket.blob(f"cv_docentes/{uid}_{int(datetime.now().timestamp())}.{ext}")
                    blob.upload_from_file(archivo_cv, content_type=f"application/{'pdf' if ext=='pdf' else 'image/'+ext}")
                    blob.make_public()
                    cv_url = blob.public_url
                else:
                    flash('Formato de CV no permitido. Usa PDF o Imagen.', 'warning')
            
            if not premios_url:
                premios_url = perfil_existente['premios_url'] if perfil_existente else None

            # Procesar archivo de filosofía de enseñanza
            filosofia_url = perfil_existente['filosofia_url'] if perfil_existente and 'filosofia_url' in perfil_existente.keys() else None
            archivo_filo = request.files.get('filosofia_file')
            if archivo_filo and archivo_filo.filename != '':
                if extension_permitida(archivo_filo.filename):
                    try:
                        filosofia_url = subir_a_firebase(archivo_filo, f'filosofia_docentes/docente_{uid}')
                    except Exception as e:
                        flash(f'Error al subir el documento de filosofía: {str(e)}', 'warning')
                else:
                    flash('Formato no permitido para filosofía. Usa PDF o Word.', 'warning')

            if perfil_existente:
                con.execute("UPDATE PerfilDocente SET curriculum=?, facultad=?, departamento=?, filosofia_ensenanza=?, premios=?, premios_url=?, responsabilidad=?, redes_sociales=?, cv_url=?, filosofia_url=? WHERE usuario_id=?", (curriculum, facultad, departamento, filosofia_ensenanza, premios, premios_url, responsabilidad, redes_sociales, cv_url, filosofia_url, uid))
            else:
                con.execute("INSERT INTO PerfilDocente (usuario_id, curriculum, facultad, departamento, filosofia_ensenanza, premios, premios_url, responsabilidad, redes_sociales, cv_url, filosofia_url) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (uid, curriculum, facultad, departamento, filosofia_ensenanza, premios, premios_url, responsabilidad, redes_sociales, cv_url, filosofia_url))
            con.commit()
            con.close()
            flash('¡Perfil actualizado correctamente!', 'success')
        except Exception as e: flash(f'Error al guardar el perfil: {str(e)}', 'danger')
        return redirect(url_for('ver_perfil'))

    try:
        con = obtener_conexion()
        perfil = con.execute("SELECT * FROM PerfilDocente WHERE usuario_id=?", (uid,)).fetchone()
        titulos = con.execute("SELECT * FROM TitulosDocente WHERE usuario_id=? ORDER BY id ASC", (uid,)).fetchall()
        con.close()
    except Exception: perfil, titulos = None, []
    return render_template('perfil.html', nombre=session['nombre'], perfil=perfil, titulos=titulos, responsabilidad_opts=RESPONSABILIDAD_OPTS)

@app.route('/docente/perfil/titulo', methods=['POST'])
def agregar_titulo():
    if not requiere_login(rol='Docente'): return redirect(url_for('login'))
    uid = session['usuario_id']
    nivel = request.form.get('nivel')
    nombre_titulo = request.form.get('nombre_titulo', '').strip()
    archivo = request.files.get('titulo_file')
    if not nivel or not nombre_titulo:
        flash('Faltan datos del título.', 'warning')
        return redirect(url_for('ver_perfil'))
    url_archivo = None
    if archivo and archivo.filename != '':
        if extension_permitida(archivo.filename):
            try: url_archivo = subir_a_firebase(archivo, f'grados_academicos/docente_{uid}')
            except: pass
        else:
            flash('Archivo del título no permitido.', 'warning')
            return redirect(url_for('ver_perfil'))
    try:
        con = obtener_conexion()
        con.execute("INSERT INTO TitulosDocente (usuario_id, nivel, nombre_titulo, url_archivo) VALUES (?,?,?,?)", (uid, nivel, nombre_titulo, url_archivo))
        con.commit()
        con.close()
        flash('Grado académico agregado a tu expediente.', 'success')
    except: flash('Error al guardar el título.', 'danger')
    return redirect(url_for('ver_perfil'))

@app.route('/docente/perfil/titulo/<int:titulo_id>/editar', methods=['POST'])
def editar_titulo(titulo_id):
    if not requiere_login(rol='Docente'): return redirect(url_for('login'))
    uid = session['usuario_id']
    nivel = request.form.get('nivel')
    nombre_titulo = request.form.get('nombre_titulo', '').strip()
    archivo = request.files.get('titulo_file')
    if not nivel or not nombre_titulo:
        flash('Faltan datos del título.', 'warning')
        return redirect(url_for('ver_perfil'))
    try:
        con = obtener_conexion()
        if archivo and archivo.filename != '':
            if extension_permitida(archivo.filename):
                url_archivo = subir_a_firebase(archivo, f'grados_academicos/docente_{uid}')
                con.execute("UPDATE TitulosDocente SET nivel=?, nombre_titulo=?, url_archivo=? WHERE id=? AND usuario_id=?", (nivel, nombre_titulo, url_archivo, titulo_id, uid))
            else:
                flash('Archivo no permitido.', 'warning')
                return redirect(url_for('ver_perfil'))
        else: con.execute("UPDATE TitulosDocente SET nivel=?, nombre_titulo=? WHERE id=? AND usuario_id=?", (nivel, nombre_titulo, titulo_id, uid))
        con.commit()
        con.close()
        flash('Título actualizado correctamente.', 'success')
    except: flash('Error al actualizar el título.', 'danger')
    return redirect(url_for('ver_perfil'))

@app.route('/docente/perfil/titulo/<int:titulo_id>/eliminar', methods=['POST'])
def eliminar_titulo(titulo_id):
    if not requiere_login(rol='Docente'): return redirect(url_for('login'))
    try:
        con = obtener_conexion()
        con.execute("DELETE FROM TitulosDocente WHERE id=? AND usuario_id=?", (titulo_id, session['usuario_id']))
        con.commit()
        con.close()
        flash('Título eliminado.', 'info')
    except: flash('Error al eliminar.', 'danger')
    return redirect(url_for('ver_perfil'))

# ─────────────────────────────────────────────
#  MÓDULO: CERTIFICADOS
# ─────────────────────────────────────────────
@app.route('/docente')
def inicio_docente():
    if not requiere_login(rol='Docente'): return redirect(url_for('login'))
    uid = session['usuario_id']
    try:
        con = obtener_conexion()
        documentos = con.execute("SELECT * FROM Documentos WHERE usuario_id = ? ORDER BY id DESC", (uid,)).fetchall()
        stats = con.execute("SELECT COUNT(*) as total, COALESCE(SUM(CASE WHEN estado='Aprobado' THEN 1 ELSE 0 END), 0) as aprobados, COALESCE(SUM(CASE WHEN estado='Pendiente' THEN 1 ELSE 0 END), 0) as pendientes, COALESCE(SUM(CASE WHEN estado='Aprobado' THEN horas ELSE 0 END), 0) as horas_aprobadas FROM Documentos WHERE usuario_id = ?", (uid,)).fetchone()
        con.close()
    except Exception: documentos, stats = [], None
    return render_template('subir_documento.html', nombre=session['nombre'], documentos=documentos, stats=stats, tipos=TIPOS_FORMACION)

@app.route('/subir', methods=['POST'])
def procesar_subida():
    if not requiere_login(rol='Docente'): return redirect(url_for('login'))
    archivo = request.files.get('certificado_file')
    if not archivo or archivo.filename == '':
        flash('Debes adjuntar un archivo.', 'danger')
        return redirect(url_for('inicio_docente'))
    if not extension_permitida(archivo.filename):
        flash('Formato no permitido. Usa PDF, Imágenes, Word o Excel.', 'danger')
        return redirect(url_for('inicio_docente'))

    try:
        url_archivo = subir_a_firebase(archivo, f"portafolios/docente_{session['usuario_id']}")
        tipo_final = request.form.get('tipo_formacion', '')
        if tipo_final == 'Otro': tipo_final = request.form.get('otro_tipo_formacion', '').strip()
        con = obtener_conexion()
        con.execute("INSERT INTO Documentos (usuario_id, nombre_actividad, tipo_formacion, institucion, fecha_emision, horas, url_archivo, fecha_registro) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", 
                    (session['usuario_id'], request.form.get('nombre_actividad', '').strip(), tipo_final, request.form.get('institucion', '').strip(), request.form.get('fecha_emision'), request.form.get('horas', 0), url_archivo, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        con.commit()
        con.close()
        flash('¡Certificado registrado exitosamente!', 'success')
    except: flash('Error al procesar la subida.', 'danger')
    return redirect(url_for('inicio_docente'))

@app.route('/docente/certificado/<int:doc_id>/editar', methods=['POST'])
def editar_certificado(doc_id):
    if not requiere_login(rol='Docente'): return redirect(url_for('login'))
    uid = session['usuario_id']
    try:
        con = obtener_conexion()
        doc = con.execute("SELECT * FROM Documentos WHERE id=? AND usuario_id=?", (doc_id, uid)).fetchone()
        if not doc:
            con.close()
            flash('No tienes permiso para editar este certificado.', 'danger')
            return redirect(url_for('inicio_docente'))

        nombre_actividad = request.form.get('nombre_actividad', '').strip()
        tipo_final = request.form.get('tipo_formacion', '')
        if tipo_final == 'Otro': tipo_final = request.form.get('otro_tipo_formacion', '').strip()
        institucion = request.form.get('institucion', '').strip()
        fecha_emision = request.form.get('fecha_emision', '')
        horas = request.form.get('horas', 0)

        # Archivo nuevo (opcional)
        url_archivo = doc['url_archivo']
        archivo = request.files.get('certificado_file')
        if archivo and archivo.filename != '':
            if extension_permitida(archivo.filename):
                url_archivo = subir_a_firebase(archivo, f"portafolios/docente_{uid}")
            else:
                con.close()
                flash('Formato de archivo no permitido.', 'danger')
                return redirect(url_for('inicio_docente'))

        con.execute("""
            UPDATE Documentos
            SET nombre_actividad=?, tipo_formacion=?, institucion=?, fecha_emision=?, horas=?, url_archivo=?
            WHERE id=? AND usuario_id=?
        """, (nombre_actividad, tipo_final, institucion, fecha_emision, horas, url_archivo, doc_id, uid))
        con.commit()
        con.close()
        flash('¡Certificado actualizado correctamente!', 'success')
    except Exception as e:
        flash(f'Error al actualizar el certificado: {str(e)}', 'danger')
    return redirect(url_for('inicio_docente'))

# ─────────────────────────────────────────────
#  MÓDULO: MIS CLASES
# ─────────────────────────────────────────────
@app.route('/docente/clases')
def mis_clases():
    if not requiere_login(rol='Docente'): return redirect(url_for('login'))
    uid = session['usuario_id']
    clases = []
    try:
        con = obtener_conexion()
        filas = con.execute("""
            SELECT c.*, (SELECT COUNT(*) FROM EvidenciasClase e WHERE e.clase_id = c.id) AS total_evidencias,
                   (SELECT COUNT(DISTINCT tipo_evidencia) FROM EvidenciasClase e WHERE e.clase_id = c.id) AS tipos_completados,
                   (SELECT COUNT(*) FROM EvidenciasClase e WHERE e.clase_id = c.id AND e.comentario_admin IS NOT NULL AND e.comentario_admin != '' AND IFNULL(e.feedback_leido, 0) = 0) AS notificaciones_nuevas
            FROM MisClases c WHERE c.usuario_id = ? ORDER BY c.fecha_creacion DESC
        """, (uid,)).fetchall()
        for f in filas:
            cd = dict(f)
            tipos_clase = obtener_tipos_clase(con, f['id'])
            cd['total_tipos_clase'] = len(tipos_clase)
            clases.append(cd)
        con.close()
    except Exception: clases = []
    return render_template('mis_clases.html', nombre=session['nombre'], clases=clases, total_tipos=len(TIPOS_EVIDENCIA))

@app.route('/docente/clases/nueva', methods=['POST'])
def nueva_clase():
    if not requiere_login(rol='Docente'): return redirect(url_for('login'))
    uid = session['usuario_id']
    periodo_tipo = request.form.get('periodo_tipo', '').strip()
    periodo_anio = request.form.get('periodo_anio', '').strip()
    periodo = f"{periodo_tipo} {periodo_anio}".strip()
    nombre_espacio = request.form.get('nombre_espacio', '').strip()
    clase_origen_id = request.form.get('clase_origen_id', '').strip()
    duplicar_evidencias = request.form.get('duplicar_evidencias') == '1'

    if not periodo_tipo or not periodo_anio or not nombre_espacio:
        flash('El período, año y nombre del espacio son obligatorios.', 'warning')
        return redirect(url_for('mis_clases'))
    try:
        con = obtener_conexion()
        cur = con.execute("INSERT INTO MisClases (usuario_id, periodo, nombre_espacio, codigo, naturaleza, modalidad, uv_ca) VALUES (?,?,?,?,?,?,?)", 
                          (uid, periodo, nombre_espacio, request.form.get('codigo', '').strip(), request.form.get('naturaleza', ''), request.form.get('modalidad', ''), request.form.get('uv_ca', '').strip()))
        nueva_id = cur.lastrowid

        origen_valido = None
        if clase_origen_id.isdigit():
            origen_valido = con.execute("SELECT id FROM MisClases WHERE id=? AND usuario_id=?", (int(clase_origen_id), uid)).fetchone()

        if origen_valido:
            # Copiar las categorías configuradas de la clase origen
            tipos_origen = obtener_tipos_clase(con, origen_valido['id'])
            for t in tipos_origen:
                con.execute("INSERT OR IGNORE INTO ClaseTiposEvidencia (clase_id, nombre) VALUES (?, ?)", (nueva_id, t))
            # Si el docente eligió duplicar archivos de evidencias anteriores
            if duplicar_evidencias:
                evs_origen = con.execute("SELECT tipo_evidencia, nombre, url_archivo FROM EvidenciasClase WHERE clase_id=?", (origen_valido['id'],)).fetchall()
                for ev in evs_origen:
                    con.execute(
                        "INSERT INTO EvidenciasClase (clase_id, tipo_evidencia, nombre, url_archivo, estado_evaluacion, comentario_admin, feedback_leido) VALUES (?,?,?,?,'Sin Revisar',NULL,0)",
                        (nueva_id, ev['tipo_evidencia'], ev['nombre'], ev['url_archivo'])
                    )
        else:
            # Inicializar con el catálogo global activo
            catalogo = obtener_catalogo_evidencias(con, solo_activos=True)
            nombres_base = [r['nombre'] for r in catalogo] if catalogo else list(TIPOS_EVIDENCIA)
            for nom in nombres_base:
                con.execute("INSERT OR IGNORE INTO ClaseTiposEvidencia (clase_id, nombre) VALUES (?, ?)", (nueva_id, nom))

        con.commit()
        con.close()
        if origen_valido and duplicar_evidencias:
            flash('¡Carpeta de clase replicada con sus evidencias anteriores!', 'success')
        elif origen_valido:
            flash('¡Carpeta de clase replicada con éxito!', 'success')
        else:
            flash('¡Carpeta de clase creada!', 'success')
        return redirect(url_for('detalle_clase', clase_id=nueva_id))
    except Exception as e:
        flash(f'Error al crear la clase: {str(e)}', 'danger')
        return redirect(url_for('mis_clases'))

@app.route('/docente/clases/<int:clase_id>')
def detalle_clase(clase_id):
    if not requiere_login(rol='Docente'): return redirect(url_for('login'))
    uid = session['usuario_id']
    try:
        con = obtener_conexion()
        clase = con.execute("SELECT * FROM MisClases WHERE id=? AND usuario_id=?", (clase_id, uid)).fetchone()
        if not clase:
            con.close()
            return redirect(url_for('mis_clases'))
        tipos_clase = obtener_tipos_clase(con, clase_id)
        evidencias = con.execute("SELECT * FROM EvidenciasClase WHERE clase_id=? ORDER BY tipo_evidencia, fecha_registro DESC", (clase_id,)).fetchall()
        reflexiones = con.execute("SELECT * FROM ReflexionesClase WHERE clase_id=? ORDER BY fecha_registro DESC", (clase_id,)).fetchall()
        
        con.execute("UPDATE EvidenciasClase SET feedback_leido = 1 WHERE clase_id = ? AND comentario_admin IS NOT NULL AND comentario_admin != ''", (clase_id,))
        con.commit()
        con.close()
    except: return redirect(url_for('mis_clases'))

    evidencias_por_tipo = {}
    for ev in evidencias:
        t = ev['tipo_evidencia']
        if t not in evidencias_por_tipo: evidencias_por_tipo[t] = []
        evidencias_por_tipo[t].append(ev)
        
    return render_template('detalle_clase.html', nombre=session['nombre'], clase=clase, evidencias_por_tipo=evidencias_por_tipo, tipos_evidencia=tipos_clase, naturaleza_opts=NATURALEZA_OPTS, modalidad_opts=MODALIDAD_OPTS, reflexiones=reflexiones)

@app.route('/docente/clases/<int:clase_id>/editar', methods=['POST'])
def editar_clase(clase_id):
    if not requiere_login(rol='Docente'): return redirect(url_for('login'))
    uid = session['usuario_id']
    periodo_tipo = request.form.get('periodo_tipo', '').strip()
    periodo_anio = request.form.get('periodo_anio', '').strip()
    periodo = f"{periodo_tipo} {periodo_anio}".strip()
    try:
        con = obtener_conexion()
        con.execute("UPDATE MisClases SET periodo=?, nombre_espacio=?, codigo=?, naturaleza=?, modalidad=?, uv_ca=? WHERE id=? AND usuario_id=?", 
                    (periodo, request.form.get('nombre_espacio', '').strip(), request.form.get('codigo', '').strip(), request.form.get('naturaleza', ''), request.form.get('modalidad', ''), request.form.get('uv_ca', '').strip(), clase_id, uid))
        con.commit()
        con.close()
        flash('¡Clase actualizada!', 'success')
    except: flash('Error al actualizar.', 'danger')
    return redirect(url_for('detalle_clase', clase_id=clase_id))

@app.route('/docente/clases/<int:clase_id>/evidencia', methods=['POST'])
def subir_evidencia(clase_id):
    if not requiere_login(rol='Docente'): return redirect(url_for('login'))
    uid = session['usuario_id']
    archivo = request.files.get('evidencia_file')
    tipo_evidencia = request.form.get('tipo_evidencia', '').strip()
    nombre_evidencia = request.form.get('nombre_evidencia', '').strip()
    
    # SOLUCIÓN DE ALERTAS: Si el archivo no es válido, ya no falla en silencio
    if not archivo or archivo.filename == '':
        flash('Debes adjuntar un archivo obligatoriamente.', 'warning')
        return redirect(url_for('detalle_clase', clase_id=clase_id))
        
    if not extension_permitida(archivo.filename):
        flash('Formato no permitido para evidencias. Solo PDF, Word, Excel, JPG o PNG.', 'danger')
        return redirect(url_for('detalle_clase', clase_id=clase_id))

    try:
        con = obtener_conexion()
        prop = con.execute("SELECT id FROM MisClases WHERE id=? AND usuario_id=?", (clase_id, uid)).fetchone()
        if not prop:
            con.close()
            flash('No tienes permiso para subir evidencias en esta clase.', 'danger')
            return redirect(url_for('mis_clases'))
        url_archivo = subir_a_firebase(archivo, f"clases/clase_{clase_id}")
        con.execute("INSERT INTO EvidenciasClase (clase_id, tipo_evidencia, nombre, url_archivo) VALUES (?,?,?,?)", (clase_id, tipo_evidencia, nombre_evidencia, url_archivo))
        con.commit()
        con.close()
        flash('¡Evidencia subida correctamente!', 'success')
    except Exception as e: 
        flash(f'Error al subir evidencia a la nube: {str(e)}', 'danger')
    return redirect(url_for('detalle_clase', clase_id=clase_id))

@app.route('/docente/clases/<int:clase_id>/evidencia/<int:ev_id>/editar', methods=['POST'])
def editar_evidencia(clase_id, ev_id):
    if not requiere_login(rol='Docente'): return redirect(url_for('login'))
    uid = session['usuario_id']
    nombre_evidencia = request.form.get('nombre_evidencia', '').strip()
    tipo_evidencia = request.form.get('tipo_evidencia', '').strip()
    archivo = request.files.get('evidencia_file')

    if not nombre_evidencia or not tipo_evidencia:
        flash('El nombre y la categoría de la evidencia son obligatorios.', 'warning')
        return redirect(url_for('detalle_clase', clase_id=clase_id))

    try:
        con = obtener_conexion()
        ev = con.execute("""
            SELECT e.* FROM EvidenciasClase e
            JOIN MisClases c ON e.clase_id = c.id
            WHERE e.id = ? AND e.clase_id = ? AND c.usuario_id = ?
        """, (ev_id, clase_id, uid)).fetchone()
        if not ev:
            con.close()
            flash('No tienes permiso para editar esta evidencia.', 'danger')
            return redirect(url_for('detalle_clase', clase_id=clase_id))

        url_archivo = ev['url_archivo']
        if archivo and archivo.filename != '':
            if not extension_permitida(archivo.filename):
                con.close()
                flash('Formato no permitido para evidencias. Solo PDF, Word, Excel, JPG o PNG.', 'danger')
                return redirect(url_for('detalle_clase', clase_id=clase_id))
            url_archivo = subir_a_firebase(archivo, f"clases/clase_{clase_id}")

        con.execute(
            "UPDATE EvidenciasClase SET nombre=?, tipo_evidencia=?, url_archivo=? WHERE id=? AND clase_id=?",
            (nombre_evidencia, tipo_evidencia, url_archivo, ev_id, clase_id)
        )
        con.commit()
        con.close()
        flash('¡Evidencia actualizada correctamente!', 'success')
    except Exception as e:
        flash(f'Error al actualizar la evidencia: {str(e)}', 'danger')
    return redirect(url_for('detalle_clase', clase_id=clase_id))

@app.route('/docente/clases/<int:clase_id>/evidencia/<int:ev_id>/eliminar', methods=['POST'])
def eliminar_evidencia(clase_id, ev_id):
    if not requiere_login(rol='Docente'): return redirect(url_for('login'))
    uid = session['usuario_id']
    try:
        con = obtener_conexion()
        prop = con.execute("SELECT id FROM MisClases WHERE id=? AND usuario_id=?", (clase_id, uid)).fetchone()
        if prop:
            con.execute("DELETE FROM EvidenciasClase WHERE id=? AND clase_id=?", (ev_id, clase_id))
            con.commit()
            flash('Evidencia eliminada.', 'info')
        con.close()
    except: flash('Error al eliminar.', 'danger')
    return redirect(url_for('detalle_clase', clase_id=clase_id))

# --- RUTAS PARA EL DIARIO DE REFLEXIÓN ---
@app.route('/docente/clases/<int:clase_id>/reflexion', methods=['POST'])
def subir_reflexion(clase_id):
    if not requiere_login(rol='Docente'): return redirect(url_for('login'))
    contenido = request.form.get('contenido', '').strip()
    archivo = request.files.get('instrumento_file')
    
    if not contenido:
        flash('El diario de reflexión no puede estar vacío.', 'warning')
        return redirect(url_for('detalle_clase', clase_id=clase_id))

    url_instrumento = None
    if archivo and archivo.filename != '':
        # SOLUCIÓN: Verifica la extensión antes de intentar subir
        if extension_permitida(archivo.filename):
            try: 
                url_instrumento = subir_a_firebase(archivo, f"reflexiones/clase_{clase_id}")
            except Exception as e: 
                flash(f'Error de red al subir el instrumento: {str(e)}', 'danger')
                return redirect(url_for('detalle_clase', clase_id=clase_id))
        else:
            flash('El archivo adjunto no es válido. Usa PDF, Word, Excel o Imágenes.', 'warning')
            return redirect(url_for('detalle_clase', clase_id=clase_id))

    try:
        con = obtener_conexion()
        con.execute("INSERT INTO ReflexionesClase (clase_id, fecha_registro, contenido, url_instrumento) VALUES (?,?,?,?)",
                    (clase_id, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), contenido, url_instrumento))
        con.commit()
        con.close()
        flash('¡Reflexión guardada exitosamente en tu diario!', 'success')
    except Exception as e:
        flash('Error al guardar la reflexión en la base de datos.', 'danger')
    return redirect(url_for('detalle_clase', clase_id=clase_id))

@app.route('/docente/clases/<int:clase_id>/reflexion/<int:ref_id>/eliminar', methods=['POST'])
def eliminar_reflexion(clase_id, ref_id):
    if not requiere_login(rol='Docente'): return redirect(url_for('login'))
    try:
        con = obtener_conexion()
        con.execute("DELETE FROM ReflexionesClase WHERE id=? AND clase_id=?", (ref_id, clase_id))
        con.commit()
        con.close()
        flash('Reflexión eliminada de tu diario.', 'info')
    except: flash('Error al eliminar reflexión.', 'danger')
    return redirect(url_for('detalle_clase', clase_id=clase_id))

# ─────────────────────────────────────────────
#  PANEL ADMINISTRADOR
# ─────────────────────────────────────────────
@app.route('/admin')
def panel_admin():
    if not requiere_login(rol='Administrador'): return redirect(url_for('login'))
    filtro_estado = request.args.get('estado', 'Todos')
    filtro_docente = request.args.get('docente', '').strip().lower()
    filtro_carrera_raw = request.args.get('carrera', 'Todas').strip()
    scope = None
    carreras = []
    catalogo_evidencias = []
    try:
        con = obtener_conexion()
        scope = obtener_scope_admin(con)
        carreras = con.execute("SELECT id, nombre, facultad FROM Carreras ORDER BY nombre ASC").fetchall()
        catalogo_evidencias = obtener_catalogo_evidencias(con, solo_activos=True)

        # Determinar carrera efectiva de filtrado
        carrera_filtrada_id = None
        if not scope['es_superadmin']:
            if scope['sin_carrera']:
                con.close()
                kpis_vacio = {'total_docentes': 0, 'total_docs': 0, 'pendientes': 0, 'aprobados': 0, 'horas_aprobadas': 0}
                return render_template('panel_admin.html', nombre=session['nombre'], documentos=[], kpis=kpis_vacio,
                                       docentes_agrupados=[], filtro_estado=filtro_estado, filtro_docente=filtro_docente,
                                       filtro_carrera='Todas', carreras=carreras, scope_admin=scope,
                                       catalogo_evidencias=catalogo_evidencias)
            carrera_filtrada_id = scope['carrera_id']
        elif filtro_carrera_raw.isdigit():
            carrera_filtrada_id = int(filtro_carrera_raw)

        query = """
            SELECT d.*, u.nombre AS nombre_docente, u.id AS usuario_id, u.carrera_id,
                   c.nombre AS nombre_carrera, p.foto_url
            FROM Documentos d
            JOIN Usuarios u ON d.usuario_id = u.id
            LEFT JOIN Carreras c ON u.carrera_id = c.id
            LEFT JOIN PerfilDocente p ON u.id = p.usuario_id
        """
        params, conds = [], ["u.rol = 'Docente'"]
        if carrera_filtrada_id is not None:
            conds.append("u.carrera_id = ?")
            params.append(carrera_filtrada_id)
        if filtro_estado != 'Todos':
            conds.append("d.estado = ?")
            params.append(filtro_estado)
        if filtro_docente:
            conds.append("LOWER(u.nombre) LIKE ?")
            params.append(f'%{filtro_docente}%')
        if conds:
            query += " WHERE " + " AND ".join(conds)
        query += " ORDER BY d.id DESC"
        documentos = con.execute(query, params).fetchall()
        
        docentes_resumen = {}
        for doc in documentos:
            uid = doc['usuario_id']
            if uid not in docentes_resumen:
                docentes_resumen[uid] = {
                    'usuario_id': uid,
                    'nombre_docente': doc['nombre_docente'],
                    'nombre_carrera': doc['nombre_carrera'],
                    'foto_url': doc['foto_url'],
                    'total_docs': 0,
                    'pendientes': 0,
                    'aprobados': 0,
                    'documentos': [],
                    'clases': []
                }
            docentes_resumen[uid]['total_docs'] += 1
            if doc['estado'] == 'Pendiente':
                docentes_resumen[uid]['pendientes'] += 1
            elif doc['estado'] == 'Aprobado':
                docentes_resumen[uid]['aprobados'] += 1
            docentes_resumen[uid]['documentos'].append(doc)

        # Incluir docentes que no tienen documentos pero sí pueden tener clases (respetando la carrera)
        doc_query = """
            SELECT u.id, u.nombre, c.nombre AS nombre_carrera, p.foto_url
            FROM Usuarios u
            LEFT JOIN Carreras c ON u.carrera_id = c.id
            LEFT JOIN PerfilDocente p ON u.id = p.usuario_id
            WHERE u.rol = 'Docente'
        """
        doc_params = []
        if carrera_filtrada_id is not None:
            doc_query += " AND u.carrera_id = ?"
            doc_params.append(carrera_filtrada_id)
        doc_query += " ORDER BY u.nombre"
        todos_docentes = con.execute(doc_query, doc_params).fetchall()
        for td in todos_docentes:
            if td['id'] not in docentes_resumen:
                if not filtro_docente or filtro_docente in td['nombre'].lower():
                    docentes_resumen[td['id']] = {
                        'usuario_id': td['id'],
                        'nombre_docente': td['nombre'],
                        'nombre_carrera': td['nombre_carrera'],
                        'foto_url': td['foto_url'],
                        'total_docs': 0,
                        'pendientes': 0,
                        'aprobados': 0,
                        'documentos': [],
                        'clases': []
                    }

        # Cargar clases para cada docente
        for uid in docentes_resumen:
            clases_db = con.execute("SELECT * FROM MisClases WHERE usuario_id = ? ORDER BY fecha_creacion DESC", (uid,)).fetchall()
            clases_list = []
            for c in clases_db:
                cd = dict(c)
                cd['total_evidencias'] = con.execute("SELECT COUNT(*) as cnt FROM EvidenciasClase WHERE clase_id = ?", (c['id'],)).fetchone()['cnt']
                cd['total_reflexiones'] = con.execute("SELECT COUNT(*) as cnt FROM ReflexionesClase WHERE clase_id = ?", (c['id'],)).fetchone()['cnt']
                clases_list.append(cd)
            docentes_resumen[uid]['clases'] = clases_list

        docentes_agrupados = sorted(docentes_resumen.values(), key=lambda x: (-x['pendientes'], x['nombre_docente']))
        
        if carrera_filtrada_id is not None:
            kpis = con.execute("""
                SELECT
                    (SELECT COUNT(DISTINCT id) FROM Usuarios WHERE rol = 'Docente' AND carrera_id = ?) AS total_docentes,
                    COUNT(d.id) AS total_docs,
                    COALESCE(SUM(CASE WHEN d.estado='Pendiente' THEN 1 ELSE 0 END), 0) AS pendientes,
                    COALESCE(SUM(CASE WHEN d.estado='Aprobado' THEN 1 ELSE 0 END), 0) AS aprobados,
                    COALESCE(SUM(CASE WHEN d.estado='Aprobado' THEN d.horas ELSE 0 END), 0) AS horas_aprobadas
                FROM Documentos d
                JOIN Usuarios u ON d.usuario_id = u.id
                WHERE u.rol = 'Docente' AND u.carrera_id = ?
            """, (carrera_filtrada_id, carrera_filtrada_id)).fetchone()
        else:
            kpis = con.execute("SELECT (SELECT COUNT(DISTINCT id) FROM Usuarios WHERE rol = 'Docente') AS total_docentes, COUNT(*) AS total_docs, COALESCE(SUM(CASE WHEN estado='Pendiente' THEN 1 ELSE 0 END), 0) AS pendientes, COALESCE(SUM(CASE WHEN estado='Aprobado' THEN 1 ELSE 0 END), 0) AS aprobados, COALESCE(SUM(CASE WHEN estado='Aprobado' THEN horas ELSE 0 END), 0) AS horas_aprobadas FROM Documentos").fetchone()
        con.close()
    except Exception:
        documentos, kpis, docentes_agrupados = [], None, []
        if scope is None:
            scope = {'es_superadmin': es_superadmin(), 'carrera_id': None, 'carrera_nombre': '', 'cargo': 'Administrador', 'sin_carrera': False}
    return render_template('panel_admin.html', nombre=session['nombre'], documentos=documentos, kpis=kpis,
                           docentes_agrupados=docentes_agrupados, filtro_estado=filtro_estado,
                           filtro_docente=filtro_docente, filtro_carrera=filtro_carrera_raw,
                           carreras=carreras, scope_admin=scope, catalogo_evidencias=catalogo_evidencias)

@app.route('/actualizar_estado/<int:doc_id>', methods=['POST'])
def actualizar_estado(doc_id):
    if not requiere_login(rol='Administrador'): return redirect(url_for('login'))
    try:
        con = obtener_conexion()
        scope = obtener_scope_admin(con)
        doc = con.execute("SELECT usuario_id FROM Documentos WHERE id = ?", (doc_id,)).fetchone()
        if not doc or not admin_puede_ver_docente(con, scope, doc['usuario_id']):
            con.close()
            flash('No tienes permiso para evaluar documentos fuera de tu carrera.', 'danger')
            return redirect(url_for('panel_admin'))
        con.execute("UPDATE Documentos SET estado = ?, comentario_admin = ? WHERE id = ?", (request.form.get('estado'), request.form.get('comentario', '').strip(), doc_id))
        con.commit()
        con.close()
        flash('Estado actualizado.', 'success')
    except: flash('Error al actualizar.', 'danger')
    return redirect(url_for('panel_admin'))

@app.route('/admin/evidencia/<int:ev_id>/evaluar', methods=['POST'])
def evaluar_evidencia(ev_id):
    if not requiere_login(rol='Administrador'): return redirect(url_for('login'))
    try:
        con = obtener_conexion()
        scope = obtener_scope_admin(con)
        ev = con.execute("SELECT c.usuario_id FROM EvidenciasClase e JOIN MisClases c ON e.clase_id = c.id WHERE e.id = ?", (ev_id,)).fetchone()
        if ev:
            if not admin_puede_ver_docente(con, scope, ev['usuario_id']):
                con.close()
                flash('No tienes permiso para evaluar evidencias de docentes fuera de tu carrera.', 'danger')
                return redirect(url_for('panel_admin'))
            con.execute("UPDATE EvidenciasClase SET estado_evaluacion=?, comentario_admin=?, feedback_leido=0 WHERE id=?", (request.form.get('estado_evaluacion', 'Sin Revisar'), request.form.get('comentario_admin', '').strip(), ev_id))
            con.commit()
            flash('Feedback enviado.', 'success')
            uid = ev['usuario_id']
            con.close()
            return redirect(url_for('expediente_docente', docente_id=uid))
        con.close()
    except: flash('Error al guardar.', 'danger')
    return redirect(url_for('panel_admin'))

@app.route('/admin/catalogo_evidencias/agregar', methods=['POST'])
def agregar_catalogo_evidencia():
    if not requiere_login(rol='Administrador'): return redirect(url_for('login'))
    nombre_cat = request.form.get('nombre_categoria', '').strip()
    if not nombre_cat:
        flash('Debes ingresar un nombre para la categoría de evidencia.', 'warning')
        return redirect(request.referrer or url_for('panel_admin'))
    try:
        con = obtener_conexion()
        existente = con.execute("SELECT id, activo FROM CatalogoEvidencias WHERE LOWER(nombre) = LOWER(?)", (nombre_cat,)).fetchone()
        if existente:
            con.execute("UPDATE CatalogoEvidencias SET activo = 1 WHERE id = ?", (existente['id'],))
            flash(f'La categoría "{nombre_cat}" ya existía y fue activada en el catálogo.', 'info')
        else:
            con.execute("INSERT INTO CatalogoEvidencias (nombre, activo) VALUES (?, 1)", (nombre_cat,))
            flash(f'Categoría "{nombre_cat}" agregada al catálogo general de evidencias.', 'success')
        con.commit()
        con.close()
    except Exception as e:
        flash(f'Error al agregar categoría: {str(e)}', 'danger')
    return redirect(request.referrer or url_for('panel_admin'))

@app.route('/admin/catalogo_evidencias/<int:cat_id>/eliminar', methods=['POST'])
def eliminar_catalogo_evidencia(cat_id):
    if not requiere_login(rol='Administrador'): return redirect(url_for('login'))
    try:
        con = obtener_conexion()
        cat = con.execute("SELECT nombre FROM CatalogoEvidencias WHERE id = ?", (cat_id,)).fetchone()
        if cat:
            con.execute("DELETE FROM CatalogoEvidencias WHERE id = ?", (cat_id,))
            con.commit()
            flash(f'Categoría "{cat["nombre"]}" eliminada del catálogo base (las clases ya creadas conservan sus archivos).', 'info')
        con.close()
    except Exception as e:
        flash(f'Error al eliminar categoría: {str(e)}', 'danger')
    return redirect(request.referrer or url_for('panel_admin'))

@app.route('/admin/clase/<int:clase_id>/tipo_evidencia/agregar', methods=['POST'])
def agregar_tipo_evidencia_clase(clase_id):
    if not requiere_login(rol='Administrador'): return redirect(url_for('login'))
    nombre_tipo = request.form.get('nombre_tipo', '').strip()
    if not nombre_tipo:
        flash('Indica el nombre de la categoría de evidencia a agregar.', 'warning')
        return redirect(request.referrer or url_for('panel_admin'))
    try:
        con = obtener_conexion()
        scope = obtener_scope_admin(con)
        clase = con.execute("SELECT id, usuario_id FROM MisClases WHERE id = ?", (clase_id,)).fetchone()
        if not clase or not admin_puede_ver_docente(con, scope, clase['usuario_id']):
            con.close()
            flash('No tienes permiso para modificar esta clase.', 'danger')
            return redirect(url_for('panel_admin'))
        # Asegurar que los tipos actuales estén inicializados antes de agregar
        obtener_tipos_clase(con, clase_id)
        con.execute("INSERT OR IGNORE INTO ClaseTiposEvidencia (clase_id, nombre) VALUES (?, ?)", (clase_id, nombre_tipo))
        con.commit()
        uid = clase['usuario_id']
        con.close()
        flash(f'Categoría "{nombre_tipo}" agregada a esta clase.', 'success')
        return redirect(url_for('expediente_docente', docente_id=uid))
    except Exception as e:
        flash(f'Error al agregar categoría a la clase: {str(e)}', 'danger')
    return redirect(request.referrer or url_for('panel_admin'))

@app.route('/admin/clase/<int:clase_id>/tipo_evidencia/eliminar', methods=['POST'])
def eliminar_tipo_evidencia_clase(clase_id):
    if not requiere_login(rol='Administrador'): return redirect(url_for('login'))
    nombre_tipo = request.form.get('nombre_tipo', '').strip()
    try:
        con = obtener_conexion()
        scope = obtener_scope_admin(con)
        clase = con.execute("SELECT id, usuario_id FROM MisClases WHERE id = ?", (clase_id,)).fetchone()
        if not clase or not admin_puede_ver_docente(con, scope, clase['usuario_id']):
            con.close()
            flash('No tienes permiso para modificar esta clase.', 'danger')
            return redirect(url_for('panel_admin'))
        obtener_tipos_clase(con, clase_id)
        tiene_archivos = con.execute("SELECT COUNT(*) FROM EvidenciasClase WHERE clase_id = ? AND tipo_evidencia = ?", (clase_id, nombre_tipo)).fetchone()[0]
        uid = clase['usuario_id']
        if tiene_archivos > 0:
            con.close()
            flash(f'No se puede quitar "{nombre_tipo}" porque ya tiene {tiene_archivos} evidencia(s) subida(s) en esta clase.', 'warning')
            return redirect(url_for('expediente_docente', docente_id=uid))
        con.execute("DELETE FROM ClaseTiposEvidencia WHERE clase_id = ? AND nombre = ?", (clase_id, nombre_tipo))
        con.commit()
        con.close()
        flash(f'Categoría "{nombre_tipo}" retirada de esta clase.', 'info')
        return redirect(url_for('expediente_docente', docente_id=uid))
    except Exception as e:
        flash(f'Error al quitar categoría: {str(e)}', 'danger')
    return redirect(request.referrer or url_for('panel_admin'))

@app.route('/admin/exportar_csv')
def exportar_csv():
    if not requiere_login(rol='Administrador'): return redirect(url_for('login'))
    filtro_carrera_raw = request.args.get('carrera', 'Todas').strip()
    try:
        con = obtener_conexion()
        scope = obtener_scope_admin(con)
        carrera_filtrada_id = None
        if not scope['es_superadmin']:
            if scope['sin_carrera']:
                con.close()
                flash('No tienes una carrera asignada para exportar datos.', 'warning')
                return redirect(url_for('panel_admin'))
            carrera_filtrada_id = scope['carrera_id']
        elif filtro_carrera_raw.isdigit():
            carrera_filtrada_id = int(filtro_carrera_raw)

        sql = """
            SELECT u.nombre, u.correo, IFNULL(c.nombre, 'Sin carrera'), d.nombre_actividad, d.tipo_formacion,
                   d.institucion, d.fecha_emision, d.horas, d.estado,
                   d.comentario_admin, d.fecha_registro, d.url_archivo
            FROM Documentos d
            JOIN Usuarios u ON d.usuario_id = u.id
            LEFT JOIN Carreras c ON u.carrera_id = c.id
            WHERE u.rol = 'Docente'
        """
        params = []
        if carrera_filtrada_id is not None:
            sql += " AND u.carrera_id = ?"
            params.append(carrera_filtrada_id)
        sql += " ORDER BY u.nombre, d.fecha_registro DESC"
        filas = con.execute(sql, params).fetchall()
        con.close()
    except Exception:
        flash('Error al generar el reporte.', 'danger')
        return redirect(url_for('panel_admin'))
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Docente', 'Correo', 'Carrera', 'Actividad', 'Tipo de Formación', 'Institución', 'Fecha Emisión', 'Horas', 'Estado', 'Comentario Admin', 'Fecha Registro', 'URL Archivo'])
    for fila in filas: writer.writerow(list(fila))
    return Response(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': f'attachment; filename=portafolio_docente_{datetime.now().strftime("%Y%m%d")}.csv'})

@app.route('/admin/estadisticas')
def estadisticas_json():
    if not requiere_login(rol='Administrador'): return jsonify({'error': 'No autorizado'}), 401
    filtro_carrera_raw = request.args.get('carrera', 'Todas').strip()
    try:
        con = obtener_conexion()
        scope = obtener_scope_admin(con)
        carrera_filtrada_id = None
        if not scope['es_superadmin']:
            if scope['sin_carrera']:
                con.close()
                return jsonify({'por_tipo': [], 'por_docente': []})
            carrera_filtrada_id = scope['carrera_id']
        elif filtro_carrera_raw.isdigit():
            carrera_filtrada_id = int(filtro_carrera_raw)

        if carrera_filtrada_id is not None:
            por_tipo = con.execute("""
                SELECT d.tipo_formacion, COUNT(*) AS cantidad, SUM(d.horas) AS total_horas
                FROM Documentos d
                JOIN Usuarios u ON d.usuario_id = u.id
                WHERE d.estado='Aprobado' AND u.rol='Docente' AND u.carrera_id = ?
                GROUP BY d.tipo_formacion ORDER BY total_horas DESC
            """, (carrera_filtrada_id,)).fetchall()
            por_docente = con.execute("""
                SELECT u.nombre, COUNT(d.id) AS documentos,
                       COALESCE(SUM(CASE WHEN d.estado='Aprobado' THEN d.horas ELSE 0 END), 0) AS horas
                FROM Usuarios u
                LEFT JOIN Documentos d ON u.id = d.usuario_id
                WHERE u.rol = 'Docente' AND u.carrera_id = ?
                GROUP BY u.id ORDER BY horas DESC LIMIT 10
            """, (carrera_filtrada_id,)).fetchall()
        else:
            por_tipo = con.execute("SELECT tipo_formacion, COUNT(*) AS cantidad, SUM(horas) AS total_horas FROM Documentos WHERE estado='Aprobado' GROUP BY tipo_formacion ORDER BY total_horas DESC").fetchall()
            por_docente = con.execute("SELECT u.nombre, COUNT(d.id) AS documentos, COALESCE(SUM(CASE WHEN d.estado='Aprobado' THEN d.horas ELSE 0 END), 0) AS horas FROM Usuarios u LEFT JOIN Documentos d ON u.id = d.usuario_id WHERE u.rol = 'Docente' GROUP BY u.id ORDER BY horas DESC LIMIT 10").fetchall()
        con.close()
        return jsonify({'por_tipo': [dict(r) for r in por_tipo], 'por_docente': [dict(r) for r in por_docente]})
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/admin/expediente/<int:docente_id>')
def expediente_docente(docente_id):
    if not requiere_login(rol='Administrador'): return redirect(url_for('login'))
    try:
        con = obtener_conexion()
        scope = obtener_scope_admin(con)
        if not admin_puede_ver_docente(con, scope, docente_id):
            con.close()
            flash('No tienes permiso para ver expedientes de docentes de otra carrera.', 'danger')
            return redirect(url_for('panel_admin'))
        docente = con.execute("""
            SELECT u.id, u.nombre, u.correo, c.nombre AS nombre_carrera,
                   p.curriculum, p.facultad, p.departamento, p.filosofia_ensenanza,
                   p.foto_url, p.cv_url, p.redes_sociales, p.premios, p.premios_url,
                   p.responsabilidad, p.filosofia_url
            FROM Usuarios u
            LEFT JOIN Carreras c ON u.carrera_id = c.id
            LEFT JOIN PerfilDocente p ON u.id = p.usuario_id
            WHERE u.id = ? AND u.rol = 'Docente'
        """, (docente_id,)).fetchone()
        if not docente:
            con.close()
            return redirect(url_for('panel_admin'))
        titulos = con.execute("SELECT * FROM TitulosDocente WHERE usuario_id=? ORDER BY id ASC", (docente_id,)).fetchall()
        certificados = con.execute("SELECT * FROM Documentos WHERE usuario_id = ? ORDER BY id DESC", (docente_id,)).fetchall()
        clases_db = con.execute("SELECT * FROM MisClases WHERE usuario_id = ? ORDER BY fecha_creacion DESC", (docente_id,)).fetchall()
        catalogo_evidencias = obtener_catalogo_evidencias(con, solo_activos=True)
        clases = []
        for c in clases_db:
            cd = dict(c)
            cd['tipos_evidencia'] = obtener_tipos_clase(con, c['id'])
            cd['evidencias'] = con.execute("SELECT * FROM EvidenciasClase WHERE clase_id = ? ORDER BY id DESC", (c['id'],)).fetchall()
            cd['reflexiones'] = con.execute("SELECT * FROM ReflexionesClase WHERE clase_id = ? ORDER BY fecha_registro DESC", (c['id'],)).fetchall()
            clases.append(cd)
        con.close()
        horas_totales = sum(int(c['horas']) for c in certificados if c['estado'] == 'Aprobado')
        return render_template('expediente_admin.html', nombre=session['nombre'], docente=docente, titulos=titulos,
                               certificados=certificados, clases=clases, horas_totales=horas_totales,
                               catalogo_evidencias=catalogo_evidencias)
    except: return redirect(url_for('panel_admin'))

# ─────────────────────────────────────────────
#  MÓDULO: GESTIÓN DE USUARIOS Y CARRERAS (SUPER ADMIN)
# ─────────────────────────────────────────────
@app.route('/admin/usuarios')
def admin_usuarios():
    if not requiere_login(rol='Administrador'): return redirect(url_for('login'))
    if not es_superadmin(): 
        flash('No tienes permisos de Super Administrador para ver esta sección.', 'danger')
        return redirect(url_for('panel_admin'))
        
    try:
        con = obtener_conexion()
        carreras_raw = con.execute("SELECT id, nombre, facultad FROM Carreras ORDER BY nombre ASC").fetchall()
        carreras = []
        for c in carreras_raw:
            cd = dict(c)
            cd['total_docentes'] = con.execute("SELECT COUNT(*) FROM Usuarios WHERE rol='Docente' AND carrera_id=?", (c['id'],)).fetchone()[0]
            jefe = con.execute("SELECT nombre FROM Usuarios WHERE rol='Administrador' AND carrera_id=? AND cargo_admin='Jefe de Departamento' AND IFNULL(activo,1)=1", (c['id'],)).fetchone()
            coord = con.execute("SELECT nombre FROM Usuarios WHERE rol='Administrador' AND carrera_id=? AND cargo_admin='Coordinador de Carrera' AND IFNULL(activo,1)=1", (c['id'],)).fetchone()
            cd['jefe_nombre'] = jefe['nombre'] if jefe else None
            cd['coord_nombre'] = coord['nombre'] if coord else None
            carreras.append(cd)

        docentes = con.execute("""
            SELECT u.id, u.nombre, u.correo, u.activo, u.carrera_id,
                   c.nombre AS nombre_carrera,
                   (SELECT COUNT(*) FROM Documentos d WHERE d.usuario_id = u.id) AS total_certs,
                   (SELECT COUNT(*) FROM Documentos d WHERE d.usuario_id = u.id AND d.estado = 'Aprobado') AS certs_aprobados
            FROM Usuarios u
            LEFT JOIN Carreras c ON u.carrera_id = c.id
            WHERE u.rol = 'Docente'
            ORDER BY u.nombre ASC
        """).fetchall()
        admins = con.execute("""
            SELECT u.id, u.nombre, u.correo, u.activo, u.carrera_id, u.cargo_admin,
                   c.nombre AS nombre_carrera
            FROM Usuarios u
            LEFT JOIN Carreras c ON u.carrera_id = c.id
            WHERE u.rol = 'Administrador'
            ORDER BY u.nombre ASC
        """).fetchall()
        todos_docentes_para_promover = con.execute("""
            SELECT id, nombre, correo, carrera_id FROM Usuarios
            WHERE rol = 'Docente'
            ORDER BY nombre ASC
        """).fetchall()
        catalogo_evidencias = obtener_catalogo_evidencias(con, solo_activos=True)
        con.close()
    except Exception as e:
        flash(f'Error al cargar usuarios: {str(e)}', 'danger')
        docentes, admins, todos_docentes_para_promover, carreras, catalogo_evidencias = [], [], [], [], []
    return render_template('admin_usuarios.html',
                           nombre=session['nombre'],
                           docentes=docentes,
                           admins=admins,
                           todos_docentes=todos_docentes_para_promover,
                           carreras=carreras,
                           cargos_admin_opts=CARGOS_ADMIN_OPTS,
                           catalogo_evidencias=catalogo_evidencias)

@app.route('/admin/carreras/crear', methods=['POST'])
def crear_carrera():
    if not requiere_login(rol='Administrador') or not es_superadmin():
        return redirect(url_for('panel_admin'))
    nombre = request.form.get('nombre', '').strip()
    facultad = request.form.get('facultad', '').strip()
    if len(nombre) < 2:
        flash('El nombre de la carrera es obligatorio.', 'warning')
        return redirect(url_for('admin_usuarios') + '#carreras')
    try:
        con = obtener_conexion()
        con.execute("INSERT INTO Carreras (nombre, facultad) VALUES (?, ?)", (nombre, facultad))
        con.commit()
        con.close()
        flash(f'Carrera "{nombre}" creada correctamente.', 'success')
    except sqlite3.IntegrityError:
        flash(f'La carrera "{nombre}" ya existe.', 'warning')
    except Exception as e:
        flash(f'Error al crear la carrera: {str(e)}', 'danger')
    return redirect(url_for('admin_usuarios') + '#carreras')

@app.route('/admin/carreras/<int:cid>/editar', methods=['POST'])
def editar_carrera(cid):
    if not requiere_login(rol='Administrador') or not es_superadmin():
        return redirect(url_for('panel_admin'))
    nombre = request.form.get('nombre', '').strip()
    facultad = request.form.get('facultad', '').strip()
    if len(nombre) < 2:
        flash('El nombre de la carrera no puede estar vacío.', 'warning')
        return redirect(url_for('admin_usuarios') + '#carreras')
    try:
        con = obtener_conexion()
        con.execute("UPDATE Carreras SET nombre = ?, facultad = ? WHERE id = ?", (nombre, facultad, cid))
        con.commit()
        con.close()
        flash('Carrera actualizada.', 'success')
    except Exception as e:
        flash(f'Error al actualizar carrera: {str(e)}', 'danger')
    return redirect(url_for('admin_usuarios') + '#carreras')

@app.route('/admin/carreras/<int:cid>/eliminar', methods=['POST'])
def eliminar_carrera(cid):
    if not requiere_login(rol='Administrador') or not es_superadmin():
        return redirect(url_for('panel_admin'))
    try:
        con = obtener_conexion()
        con.execute("UPDATE Usuarios SET carrera_id = NULL WHERE carrera_id = ?", (cid,))
        con.execute("DELETE FROM Carreras WHERE id = ?", (cid,))
        con.commit()
        con.close()
        flash('Carrera eliminada. Los usuarios asociados quedaron sin carrera asignada.', 'info')
    except Exception as e:
        flash(f'Error al eliminar carrera: {str(e)}', 'danger')
    return redirect(url_for('admin_usuarios') + '#carreras')

@app.route('/admin/usuarios/<int:uid>/asignar_carrera', methods=['POST'])
def asignar_carrera_usuario(uid):
    if not requiere_login(rol='Administrador') or not es_superadmin():
        return redirect(url_for('panel_admin'))
    carrera_raw = request.form.get('carrera_id', '').strip()
    carrera_val = int(carrera_raw) if carrera_raw.isdigit() else None
    cargo_admin = request.form.get('cargo_admin', '').strip()
    try:
        con = obtener_conexion()
        u = con.execute("SELECT id, nombre, rol, correo FROM Usuarios WHERE id = ?", (uid,)).fetchone()
        if not u:
            con.close()
            flash('Usuario no encontrado.', 'danger')
            return redirect(url_for('admin_usuarios'))

        if u['rol'] == 'Administrador' and u['correo'] not in SUPER_ADMIN_EMAILS:
            if not carrera_val or cargo_admin not in CARGOS_ADMIN_OPTS:
                con.close()
                flash('Un administrador de carrera debe tener carrera y cargo (Jefe o Coordinador).', 'warning')
                return redirect(url_for('admin_usuarios') + '#admins')
            ocupado = con.execute("""
                SELECT nombre FROM Usuarios
                WHERE rol = 'Administrador' AND carrera_id = ? AND cargo_admin = ? AND id != ? AND IFNULL(activo, 1) = 1
            """, (carrera_val, cargo_admin, uid)).fetchone()
            if ocupado:
                con.close()
                flash(f'El cargo de {cargo_admin} en esa carrera ya está ocupado por {ocupado["nombre"]}. Pásalo primero a Docente.', 'warning')
                return redirect(url_for('admin_usuarios') + '#admins')
            con.execute("UPDATE Usuarios SET carrera_id = ?, cargo_admin = ? WHERE id = ?", (carrera_val, cargo_admin, uid))
            con.commit()
            con.close()
            flash(f'Asignación actualizada para {u["nombre"]}.', 'success')
            return redirect(url_for('admin_usuarios') + '#admins')
        else:
            con.execute("UPDATE Usuarios SET carrera_id = ? WHERE id = ?", (carrera_val, uid))
            con.commit()
            con.close()
            flash(f'Carrera actualizada para {u["nombre"]}.', 'success')
            return redirect(url_for('admin_usuarios'))
    except Exception as e:
        flash(f'Error al asignar carrera: {str(e)}', 'danger')
    return redirect(url_for('admin_usuarios'))

@app.route('/admin/usuarios/<int:uid>/cambiar_rol', methods=['POST'])
def cambiar_rol_usuario(uid):
    if not requiere_login(rol='Administrador'): return redirect(url_for('login'))
    if not es_superadmin(): return redirect(url_for('panel_admin'))
    # Protección: no puede quitarse el rol a sí mismo
    if uid == session['usuario_id']:
        flash('No puedes cambiar tu propio rol mientras tienes sesión activa.', 'warning')
        return redirect(url_for('admin_usuarios'))
    nuevo_rol = request.form.get('nuevo_rol', '')
    if nuevo_rol not in ('Administrador', 'Docente'):
        flash('Rol no válido.', 'danger')
        return redirect(url_for('admin_usuarios'))
    try:
        con = obtener_conexion()
        usuario = con.execute("SELECT nombre, rol, correo, carrera_id FROM Usuarios WHERE id=?", (uid,)).fetchone()
        if not usuario:
            con.close()
            flash('Usuario no encontrado.', 'danger')
            return redirect(url_for('admin_usuarios'))
        if usuario['correo'] in SUPER_ADMIN_EMAILS and nuevo_rol == 'Docente':
            con.close()
            flash('No se puede degradar a una cuenta de Super Administrador.', 'warning')
            return redirect(url_for('admin_usuarios') + '#admins')

        if nuevo_rol == 'Administrador':
            carrera_raw = request.form.get('carrera_id', '').strip()
            carrera_val = int(carrera_raw) if carrera_raw.isdigit() else usuario['carrera_id']
            cargo_admin = request.form.get('cargo_admin', '').strip()
            if not carrera_val or cargo_admin not in CARGOS_ADMIN_OPTS:
                con.close()
                flash('Debes seleccionar la Carrera y el Cargo (Jefe de Departamento o Coordinador de Carrera).', 'warning')
                return redirect(url_for('admin_usuarios'))
            ocupado = con.execute("""
                SELECT nombre FROM Usuarios
                WHERE rol = 'Administrador' AND carrera_id = ? AND cargo_admin = ? AND id != ? AND IFNULL(activo, 1) = 1
            """, (carrera_val, cargo_admin, uid)).fetchone()
            if ocupado:
                con.close()
                flash(f'El puesto de {cargo_admin} en esta carrera ya pertenece a {ocupado["nombre"]}. Cambia primero a esa persona al rol de Docente.', 'warning')
                return redirect(url_for('admin_usuarios'))
            con.execute("UPDATE Usuarios SET rol='Administrador', carrera_id=?, cargo_admin=? WHERE id=?", (carrera_val, cargo_admin, uid))
            con.commit()
            con.close()
            flash(f'¡{usuario["nombre"]} ha sido promovido a {cargo_admin} exitosamente!', 'success')
            return redirect(url_for('admin_usuarios') + '#admins')
        else:
            # Regresar a Docente conservando su carrera_id y liberando el cargo_admin
            con.execute("UPDATE Usuarios SET rol='Docente', cargo_admin=NULL WHERE id=?", (uid,))
            con.commit()
            con.close()
            flash(f'¡{usuario["nombre"]} ha vuelto al rol de Docente exitosamente!', 'success')
            return redirect(url_for('admin_usuarios') + '#admins')
    except Exception as e:
        flash(f'Error al cambiar el rol: {str(e)}', 'danger')
    return redirect(url_for('admin_usuarios'))

@app.route('/admin/usuarios/<int:uid>/restablecer_password', methods=['POST'])
def restablecer_password(uid):
    if not requiere_login(rol='Administrador'): return redirect(url_for('login'))
    if not es_superadmin(): return redirect(url_for('panel_admin'))
    
    nueva_password = request.form.get('nueva_password')
    if not nueva_password or len(nueva_password) < 8:
        flash('La nueva contraseña debe tener al menos 8 caracteres.', 'danger')
        return redirect(url_for('admin_usuarios'))
        
    try:
        con = obtener_conexion()
        usuario = con.execute("SELECT id, nombre, rol FROM Usuarios WHERE id=?", (uid,)).fetchone()
        
        if usuario:
            hash_pass = generate_password_hash(nueva_password)
            con.execute("UPDATE Usuarios SET password=? WHERE id=?", (hash_pass, uid))
            con.commit()
            flash(f'Contraseña actualizada exitosamente para {usuario["nombre"]}.', 'success')
        else:
            flash('Usuario no encontrado.', 'danger')
            
    except Exception as e:
        flash(f'Error al restablecer contraseña: {str(e)}', 'danger')
    finally:
        if 'con' in locals(): con.close()
        
    return redirect(url_for('admin_usuarios'))

@app.route('/admin/usuarios/<int:uid>/toggle_activo', methods=['POST'])
def toggle_activo_usuario(uid):
    if not requiere_login(rol='Administrador'): return redirect(url_for('login'))
    if not es_superadmin(): return redirect(url_for('panel_admin'))
    if uid == session['usuario_id']:
        flash('No puedes desactivar tu propia cuenta.', 'warning')
        return redirect(url_for('admin_usuarios'))
    try:
        con = obtener_conexion()
        usuario = con.execute("SELECT nombre, activo FROM Usuarios WHERE id=?", (uid,)).fetchone()
        if not usuario:
            con.close()
            flash('Usuario no encontrado.', 'danger')
            return redirect(url_for('admin_usuarios'))
        nuevo_activo = 0 if usuario['activo'] else 1
        con.execute("UPDATE Usuarios SET activo=? WHERE id=?", (nuevo_activo, uid))
        con.commit()
        con.close()
        estado = 'activado' if nuevo_activo else 'desactivado'
        flash(f'¡Cuenta de {usuario["nombre"]} {estado} correctamente!', 'success')
    except Exception as e:
        flash(f'Error al cambiar estado: {str(e)}', 'danger')
    return redirect(url_for('admin_usuarios'))

@app.route('/admin/usuarios/crear_admin', methods=['POST'])
def crear_admin():
    if not requiere_login(rol='Administrador'): return redirect(url_for('login'))
    if not es_superadmin(): return redirect(url_for('panel_admin'))
    nombre = request.form.get('nombre', '').strip()
    correo = request.form.get('correo', '').strip().lower()
    password = request.form.get('password', '')
    carrera_raw = request.form.get('carrera_id', '').strip()
    carrera_val = int(carrera_raw) if carrera_raw.isdigit() else None
    cargo_admin = request.form.get('cargo_admin', '').strip()

    if len(nombre) < 3 or not correo or len(password) < 8:
        flash('Datos insuficientes para crear el administrador.', 'warning')
        return redirect(url_for('admin_usuarios'))
    if not carrera_val or cargo_admin not in CARGOS_ADMIN_OPTS:
        flash('Debes asignar una Carrera y un Cargo (Jefe o Coordinador) al nuevo administrador.', 'warning')
        return redirect(url_for('admin_usuarios'))
    try:
        con = obtener_conexion()
        if con.execute("SELECT id FROM Usuarios WHERE correo=?", (correo,)).fetchone():
            con.close()
            flash('Este correo ya está registrado en el sistema.', 'warning')
            return redirect(url_for('admin_usuarios'))
        ocupado = con.execute("""
            SELECT nombre FROM Usuarios
            WHERE rol = 'Administrador' AND carrera_id = ? AND cargo_admin = ? AND IFNULL(activo, 1) = 1
        """, (carrera_val, cargo_admin)).fetchone()
        if ocupado:
            con.close()
            flash(f'El cargo de {cargo_admin} en esa carrera ya está ocupado por {ocupado["nombre"]}.', 'warning')
            return redirect(url_for('admin_usuarios'))
        hashed = generate_password_hash(password)
        con.execute(
            "INSERT INTO Usuarios (nombre, correo, password, rol, activo, carrera_id, cargo_admin) VALUES (?,?,?,'Administrador',1,?,?)",
            (nombre, correo, hashed, carrera_val, cargo_admin)
        )
        con.commit()
        con.close()
        flash(f'¡{cargo_admin} {nombre} creado exitosamente!', 'success')
    except Exception as e:
        flash(f'Error al crear administrador: {str(e)}', 'danger')
    return redirect(url_for('admin_usuarios') + '#admins')

# ─────────────────────────────────────────────
#  MANEJADORES DE ERROR
# ─────────────────────────────────────────────
@app.errorhandler(413)
def archivo_muy_grande(e):
    flash('El archivo excede el límite (16 MB).', 'danger')
    return redirect(request.referrer or url_for('inicio_docente'))


@app.route('/docente/clases/<int:clase_id>/eliminar', methods=['POST'])
def eliminar_clase(clase_id):
    if not requiere_login(rol='Docente'): return redirect(url_for('login'))
    uid = session['usuario_id']
    try:
        con = obtener_conexion()
        clase = con.execute('SELECT id FROM MisClases WHERE id=? AND usuario_id=?', (clase_id, uid)).fetchone()
        if not clase:
            con.close()
            flash('No tienes permiso para eliminar esta clase.', 'danger')
            return redirect(url_for('mis_clases'))
        con.execute('DELETE FROM EvidenciasClase WHERE clase_id=?', (clase_id,))
        con.execute('DELETE FROM ClaseTiposEvidencia WHERE clase_id=?', (clase_id,))
        con.execute('DELETE FROM ReflexionesClase WHERE clase_id=?', (clase_id,))
        con.execute('DELETE FROM MisClases WHERE id=? AND usuario_id=?', (clase_id, uid))
        con.commit()
        con.close()
        flash('Clase y sus evidencias eliminadas correctamente.', 'info')
    except Exception as e:
        flash(f'Error al eliminar la clase: {str(e)}', 'danger')
    return redirect(url_for('mis_clases'))

if __name__ == '__main__':
    app.run(debug=True)