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
    'licenciatura', 'licenciatura_url', 'maestria', 'maestria_url', 'doctorado', 'doctorado_url'
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

TIPOS_FORMACION = ['Taller', 'Seminario', 'Diplomado', 'Posgrado', 'Congreso', 'Jornada Pedagógica', 'Curso en Línea (MOOC)', 'Práctica Docente', 'Otro']
TIPOS_EVIDENCIA = ['Planificación Didáctica', 'Material Didáctico', 'Instrumento de Evaluación (Rúbricas, Ejercicios, Proyectos)', 'Asignaciones para Estudiantes (Tareas, Ejercicios, Talleres)', 'Evidencias Fotográficas (Talleres, Trabajos de Campo)', 'Evaluación Docente', 'Bibliografía', 'Registro de Calificaciones', 'Actividades de Vinculación', 'Actividades de Investigación', 'Horas de Tutoría', 'Otras Actividades']
NATURALEZA_OPTS   = ['Teórica', 'Práctica', 'Mixta', 'Laboratorio']
MODALIDAD_OPTS    = ['Presencial', 'Virtual', 'Semipresencial', 'En Línea']
RESPONSABILIDAD_OPTS = ['Ninguna', 'Jefe de Departamento', 'Coordinador de Carrera', 'Ambas', 'Otros']
EXTENSIONES_PERMITIDAS = {'pdf', 'jpg', 'jpeg', 'png'}

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
            session['usuario_id'] = usuario['id']
            session['nombre']     = usuario['nombre']
            session['rol']        = usuario['rol']
            session.permanent     = True
            return redirect(url_for('panel_admin') if usuario['rol'] == 'Administrador' else url_for('ver_perfil'))
        else:
            flash('Correo o contraseña incorrectos.', 'danger')
    return render_template('login.html')

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        nombre    = request.form.get('nombre', '').strip()
        correo    = request.form.get('correo', '').strip().lower()
        password  = request.form.get('password', '')
        password2 = request.form.get('password2', '')

        if len(nombre) < 3 or not correo.endswith('.edu.hn') or len(password) < 8 or password != password2:
            flash('Revisa los requisitos del formulario.', 'warning')
            return render_template('registro.html')

        try:
            con = obtener_conexion()
            if con.execute("SELECT id FROM Usuarios WHERE correo = ?", (correo,)).fetchone():
                con.close()
                flash('Este correo ya está registrado.', 'warning')
                return render_template('registro.html')
            hashed = generate_password_hash(password)
            con.execute("INSERT INTO Usuarios (nombre, correo, password, rol) VALUES (?, ?, ?, 'Docente')", (nombre, correo, hashed))
            con.commit()
            con.close()
        except Exception:
            flash('Error al crear la cuenta.', 'danger')
            return render_template('registro.html')

        flash('¡Cuenta creada exitosamente!', 'success')
        return redirect(url_for('login'))
    return render_template('registro.html')

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
            else: flash('Archivo inválido.', 'warning')
            return redirect(url_for('ver_perfil'))

        curriculum          = request.form.get('curriculum', '').strip()
        facultad            = request.form.get('facultad', '').strip()
        departamento        = request.form.get('departamento', '').strip()
        premios             = request.form.get('premios', '').strip()
        redes_sociales      = request.form.get('redes_sociales', '').strip()
        filosofia_ensenanza = request.form.get('filosofia_ensenanza', '').strip()
        responsabilidad     = request.form.get('responsabilidad', 'Ninguna')
        if responsabilidad == 'Otros':
            responsabilidad = request.form.get('otra_responsabilidad', '').strip() or 'Otros'

        try:
            con = obtener_conexion()
            existe = con.execute("SELECT * FROM PerfilDocente WHERE usuario_id=?", (uid,)).fetchone()
            cv_url = existe['cv_url'] if existe and 'cv_url' in existe.keys() else None
            archivo_cv = request.files.get('cv_file')
            if archivo_cv and archivo_cv.filename != '' and extension_permitida(archivo_cv.filename):
                cv_url = subir_a_firebase(archivo_cv, f'cv_docentes/docente_{uid}')

            if existe:
                con.execute("UPDATE PerfilDocente SET curriculum=?, facultad=?, departamento=?, filosofia_ensenanza=?, premios=?, responsabilidad=?, redes_sociales=?, cv_url=? WHERE usuario_id=?", (curriculum, facultad, departamento, filosofia_ensenanza, premios, responsabilidad, redes_sociales, cv_url, uid))
            else:
                con.execute("INSERT INTO PerfilDocente (usuario_id, curriculum, facultad, departamento, filosofia_ensenanza, premios, responsabilidad, redes_sociales, cv_url) VALUES (?,?,?,?,?,?,?,?,?)", (uid, curriculum, facultad, departamento, filosofia_ensenanza, premios, responsabilidad, redes_sociales, cv_url))
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
    if archivo and archivo.filename != '' and extension_permitida(archivo.filename):
        try: url_archivo = subir_a_firebase(archivo, f'grados_academicos/docente_{uid}')
        except: pass
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
        if archivo and archivo.filename != '' and extension_permitida(archivo.filename):
            url_archivo = subir_a_firebase(archivo, f'grados_academicos/docente_{uid}')
            con.execute("UPDATE TitulosDocente SET nivel=?, nombre_titulo=?, url_archivo=? WHERE id=? AND usuario_id=?", (nivel, nombre_titulo, url_archivo, titulo_id, uid))
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
        stats = con.execute("SELECT COUNT(*) as total, SUM(CASE WHEN estado='Aprobado' THEN 1 ELSE 0 END) as aprobados, SUM(CASE WHEN estado='Pendiente' THEN 1 ELSE 0 END) as pendientes, COALESCE(SUM(CASE WHEN estado='Aprobado' THEN horas ELSE 0 END), 0) as horas_aprobadas FROM Documentos WHERE usuario_id = ?", (uid,)).fetchone()
        con.close()
    except Exception: documentos, stats = [], None
    return render_template('subir_documento.html', nombre=session['nombre'], documentos=documentos, stats=stats, tipos=TIPOS_FORMACION)

@app.route('/subir', methods=['POST'])
def procesar_subida():
    if not requiere_login(rol='Docente'): return redirect(url_for('login'))
    archivo = request.files.get('certificado_file')
    if not archivo or archivo.filename == '' or not extension_permitida(archivo.filename):
        flash('Archivo inválido.', 'danger')
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

# ─────────────────────────────────────────────
#  MÓDULO: MIS CLASES (Normalizado)
# ─────────────────────────────────────────────
@app.route('/docente/clases')
def mis_clases():
    if not requiere_login(rol='Docente'): return redirect(url_for('login'))
    uid = session['usuario_id']
    try:
        con = obtener_conexion()
        clases = con.execute("""
            SELECT c.*, (SELECT COUNT(*) FROM EvidenciasClase e WHERE e.clase_id = c.id) AS total_evidencias,
                   (SELECT COUNT(DISTINCT tipo_evidencia) FROM EvidenciasClase e WHERE e.clase_id = c.id) AS tipos_completados,
                   (SELECT COUNT(*) FROM EvidenciasClase e WHERE e.clase_id = c.id AND e.comentario_admin IS NOT NULL AND e.comentario_admin != '' AND IFNULL(e.feedback_leido, 0) = 0) AS notificaciones_nuevas
            FROM MisClases c WHERE c.usuario_id = ? ORDER BY c.fecha_creacion DESC
        """, (uid,)).fetchall()
        con.close()
    except Exception: clases = []
    return render_template('mis_clases.html', nombre=session['nombre'], clases=clases, total_tipos=len(TIPOS_EVIDENCIA))

@app.route('/docente/clases/nueva', methods=['POST'])
def nueva_clase():
    if not requiere_login(rol='Docente'): return redirect(url_for('login'))
    uid = session['usuario_id']
    
    # LÓGICA DE CONCATENACIÓN PARA NORMALIZACIÓN
    periodo_tipo = request.form.get('periodo_tipo', '').strip()
    periodo_anio = request.form.get('periodo_anio', '').strip()
    periodo = f"{periodo_tipo} {periodo_anio}".strip()
    
    nombre_espacio = request.form.get('nombre_espacio', '').strip()
    
    if not periodo_tipo or not periodo_anio or not nombre_espacio:
        flash('El período, año y nombre del espacio son obligatorios.', 'warning')
        return redirect(url_for('mis_clases'))
    try:
        con = obtener_conexion()
        cur = con.execute("INSERT INTO MisClases (usuario_id, periodo, nombre_espacio, codigo, naturaleza, modalidad, uv_ca) VALUES (?,?,?,?,?,?,?)", 
                          (uid, periodo, nombre_espacio, request.form.get('codigo', '').strip(), request.form.get('naturaleza', ''), request.form.get('modalidad', ''), request.form.get('uv_ca', '').strip()))
        con.commit()
        con.close()
        flash('¡Carpeta de clase creada!', 'success')
        return redirect(url_for('detalle_clase', clase_id=cur.lastrowid))
    except: flash('Error al crear la clase.', 'danger'); return redirect(url_for('mis_clases'))

@app.route('/docente/clases/<int:clase_id>')
def detalle_clase(clase_id):
    if not requiere_login(rol='Docente'): return redirect(url_for('login'))
    uid = session['usuario_id']
    try:
        con = obtener_conexion()
        clase = con.execute("SELECT * FROM MisClases WHERE id=? AND usuario_id=?", (clase_id, uid)).fetchone()
        if not clase: return redirect(url_for('mis_clases'))
        evidencias = con.execute("SELECT * FROM EvidenciasClase WHERE clase_id=? ORDER BY tipo_evidencia, fecha_registro DESC", (clase_id,)).fetchall()
        con.execute("UPDATE EvidenciasClase SET feedback_leido = 1 WHERE clase_id = ? AND comentario_admin IS NOT NULL AND comentario_admin != ''", (clase_id,))
        con.commit()
        con.close()
    except: return redirect(url_for('mis_clases'))

    evidencias_por_tipo = {}
    for ev in evidencias:
        t = ev['tipo_evidencia']
        if t not in evidencias_por_tipo: evidencias_por_tipo[t] = []
        evidencias_por_tipo[t].append(ev)
    return render_template('detalle_clase.html', nombre=session['nombre'], clase=clase, evidencias_por_tipo=evidencias_por_tipo, tipos_evidencia=TIPOS_EVIDENCIA, naturaleza_opts=NATURALEZA_OPTS, modalidad_opts=MODALIDAD_OPTS)

@app.route('/docente/clases/<int:clase_id>/editar', methods=['POST'])
def editar_clase(clase_id):
    if not requiere_login(rol='Docente'): return redirect(url_for('login'))
    uid = session['usuario_id']
    
    # LÓGICA DE CONCATENACIÓN PARA NORMALIZACIÓN EN LA EDICIÓN
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
    if not archivo or archivo.filename == '' or not extension_permitida(archivo.filename): return redirect(url_for('detalle_clase', clase_id=clase_id))
    try:
        url_archivo = subir_a_firebase(archivo, f"clases/clase_{clase_id}")
        con = obtener_conexion()
        con.execute("INSERT INTO EvidenciasClase (clase_id, tipo_evidencia, nombre, url_archivo) VALUES (?,?,?,?)", (clase_id, tipo_evidencia, nombre_evidencia, url_archivo))
        con.commit()
        con.close()
        flash('¡Evidencia subida!', 'success')
    except Exception as e: flash(f'Error al subir evidencia: {str(e)}', 'danger')
    return redirect(url_for('detalle_clase', clase_id=clase_id))

@app.route('/docente/clases/<int:clase_id>/evidencia/<int:ev_id>/eliminar', methods=['POST'])
def eliminar_evidencia(clase_id, ev_id):
    if not requiere_login(rol='Docente'): return redirect(url_for('login'))
    try:
        con = obtener_conexion()
        con.execute("DELETE FROM EvidenciasClase WHERE id=? AND clase_id=?", (ev_id, clase_id))
        con.commit()
        con.close()
        flash('Evidencia eliminada.', 'info')
    except: flash('Error al eliminar.', 'danger')
    return redirect(url_for('detalle_clase', clase_id=clase_id))

# ─────────────────────────────────────────────
#  PANEL ADMINISTRADOR
# ─────────────────────────────────────────────
@app.route('/admin')
def panel_admin():
    if not requiere_login(rol='Administrador'): return redirect(url_for('login'))
    filtro_estado = request.args.get('estado', 'Todos')
    filtro_docente = request.args.get('docente', '').strip().lower()
    try:
        con = obtener_conexion()
        query = "SELECT d.*, u.nombre AS nombre_docente, u.id AS usuario_id FROM Documentos d JOIN Usuarios u ON d.usuario_id = u.id"
        params, conds = [], []
        if filtro_estado != 'Todos': conds.append("d.estado = ?"); params.append(filtro_estado)
        if filtro_docente: conds.append("LOWER(u.nombre) LIKE ?"); params.append(f'%{filtro_docente}%')
        if conds: query += " WHERE " + " AND ".join(conds)
        query += " ORDER BY d.id DESC"
        documentos = con.execute(query, params).fetchall()
        kpis = con.execute("SELECT (SELECT COUNT(DISTINCT id) FROM Usuarios WHERE rol = 'Docente') AS total_docentes, COUNT(*) AS total_docs, SUM(CASE WHEN estado='Pendiente' THEN 1 ELSE 0 END) AS pendientes, SUM(CASE WHEN estado='Aprobado' THEN 1 ELSE 0 END) AS aprobados, COALESCE(SUM(CASE WHEN estado='Aprobado' THEN horas ELSE 0 END), 0) AS horas_aprobadas FROM Documentos").fetchone()
        docentes = con.execute("SELECT DISTINCT nombre FROM Usuarios WHERE rol='Docente' ORDER BY nombre").fetchall()
        con.close()
    except: documentos, kpis, docentes = [], None, []
    return render_template('panel_admin.html', nombre=session['nombre'], documentos=documentos, kpis=kpis, docentes=docentes, filtro_estado=filtro_estado, filtro_docente=filtro_docente)

@app.route('/actualizar_estado/<int:doc_id>', methods=['POST'])
def actualizar_estado(doc_id):
    if not requiere_login(rol='Administrador'): return redirect(url_for('login'))
    try:
        con = obtener_conexion()
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
        ev = con.execute("SELECT c.usuario_id FROM EvidenciasClase e JOIN MisClases c ON e.clase_id = c.id WHERE e.id = ?", (ev_id,)).fetchone()
        if ev:
            con.execute("UPDATE EvidenciasClase SET estado_evaluacion=?, comentario_admin=?, feedback_leido=0 WHERE id=?", (request.form.get('estado_evaluacion', 'Sin Revisar'), request.form.get('comentario_admin', '').strip(), ev_id))
            con.commit()
            flash('Feedback enviado.', 'success')
            uid = ev['usuario_id']
            con.close()
            return redirect(url_for('expediente_docente', docente_id=uid))
        con.close()
    except: flash('Error al guardar.', 'danger')
    return redirect(url_for('panel_admin'))

@app.route('/admin/exportar_csv')
def exportar_csv():
    if not requiere_login(rol='Administrador'): return redirect(url_for('login'))
    try:
        con = obtener_conexion()
        filas = con.execute("""
            SELECT u.nombre, u.correo, d.nombre_actividad, d.tipo_formacion,
                   d.institucion, d.fecha_emision, d.horas, d.estado,
                   d.comentario_admin, d.fecha_registro, d.url_archivo
            FROM Documentos d
            JOIN Usuarios u ON d.usuario_id = u.id
            ORDER BY u.nombre, d.fecha_registro DESC
        """).fetchall()
        con.close()
    except Exception:
        flash('Error al generar el reporte.', 'danger')
        return redirect(url_for('panel_admin'))
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Docente', 'Correo', 'Actividad', 'Tipo de Formación', 'Institución', 'Fecha Emisión', 'Horas', 'Estado', 'Comentario Admin', 'Fecha Registro', 'URL Archivo'])
    for fila in filas: writer.writerow(list(fila))
    return Response(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': f'attachment; filename=portafolio_docente_{datetime.now().strftime("%Y%m%d")}.csv'})

@app.route('/admin/estadisticas')
def estadisticas_json():
    if not requiere_login(rol='Administrador'): return jsonify({'error': 'No autorizado'}), 401
    try:
        con = obtener_conexion()
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
        docente = con.execute("SELECT u.id, u.nombre, u.correo, p.curriculum, p.facultad, p.departamento, p.filosofia_ensenanza, p.foto_url, p.cv_url, p.redes_sociales, p.premios, p.responsabilidad FROM Usuarios u LEFT JOIN PerfilDocente p ON u.id = p.usuario_id WHERE u.id = ? AND u.rol = 'Docente'", (docente_id,)).fetchone()
        if not docente: return redirect(url_for('panel_admin'))
        titulos = con.execute("SELECT * FROM TitulosDocente WHERE usuario_id=? ORDER BY id ASC", (docente_id,)).fetchall()
        certificados = con.execute("SELECT * FROM Documentos WHERE usuario_id = ? ORDER BY id DESC", (docente_id,)).fetchall()
        clases_db = con.execute("SELECT * FROM MisClases WHERE usuario_id = ? ORDER BY fecha_creacion DESC", (docente_id,)).fetchall()
        clases = []
        for c in clases_db:
            cd = dict(c)
            cd['evidencias'] = con.execute("SELECT * FROM EvidenciasClase WHERE clase_id = ? ORDER BY id DESC", (c['id'],)).fetchall()
            clases.append(cd)
        con.close()
        horas_totales = sum(int(c['horas']) for c in certificados if c['estado'] == 'Aprobado')
        return render_template('expediente_admin.html', nombre=session['nombre'], docente=docente, titulos=titulos, certificados=certificados, clases=clases, horas_totales=horas_totales)
    except: return redirect(url_for('panel_admin'))

# ─────────────────────────────────────────────
#  MANEJADORES DE ERROR
# ─────────────────────────────────────────────
@app.errorhandler(413)
def archivo_muy_grande(e):
    flash('El archivo excede el límite (16 MB).', 'danger')
    return redirect(request.referrer or url_for('inicio_docente'))

if __name__ == '__main__':
    app.run(debug=True)