"""Configuración de la aplicación.

Cambie aquí los datos de conexión a MySQL si en su equipo son distintos.
También se pueden poner como variables de entorno (DB_HOST, DB_USER, etc.).
"""
import os

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "Danna123321.")
DB_NAME = os.getenv("DB_NAME", "entrecol")

# Llave para firmar la sesión de Flask (cámbiela en producción)
SECRET_KEY = os.getenv("SECRET_KEY", "entrecol-colplus-2026-2-clave-sesion")

# Seguridad del login
MAX_INTENTOS_FALLIDOS = 5          # después de esto el usuario queda bloqueado
MINUTOS_SESION = 30                # tiempo de inactividad antes de cerrar sesión

# Carpeta temporal para los archivos que suben los usuarios
CARPETA_CARGAS = os.path.join(os.path.dirname(__file__), "cargas_temp")
