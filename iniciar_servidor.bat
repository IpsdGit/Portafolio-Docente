@echo off
echo ==============================================================
echo Iniciando el Sistema Portafolio Docente (Servidor Waitress)
echo ==============================================================
echo El servidor estara disponible en: http://localhost:5000
echo.
echo Presiona Ctrl+C para detener el servidor.
echo.

python -m waitress --port=5000 flask_app:app

pause
