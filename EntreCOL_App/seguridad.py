"""Seguridad: cifrado de contraseñas, captcha, control de sesión, roles y auditoría."""
import io
import os
import random
import re
import secrets
import string
from functools import wraps

import bcrypt
from flask import abort, flash, redirect, request, session, url_for
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from db import ejecutar

CARPETA_FUENTES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "fonts")


# ------------------------------------------------------------------
# Contraseñas
# ------------------------------------------------------------------
def cifrar_contrasena(texto):
    """Cifra la contraseña con bcrypt (incluye 'sal' aleatoria). Nunca se guarda el texto plano."""
    return bcrypt.hashpw(texto.encode("utf-8"), bcrypt.gensalt(12)).decode("utf-8")


def verificar_contrasena(texto, hash_guardado):
    try:
        return bcrypt.checkpw(texto.encode("utf-8"), hash_guardado.encode("utf-8"))
    except ValueError:
        return False


def validar_politica(contrasena):
    """Devuelve una lista con lo que le falta a la contraseña (vacía si cumple)."""
    errores = []
    if len(contrasena) < 8:
        errores.append("mínimo 8 caracteres")
    if not re.search(r"[A-Z]", contrasena):
        errores.append("una letra mayúscula")
    if not re.search(r"[a-z]", contrasena):
        errores.append("una letra minúscula")
    if not re.search(r"\d", contrasena):
        errores.append("un número")
    if not re.search(r"[^A-Za-z0-9]", contrasena):
        errores.append("un carácter especial (ej. * # $ !)")
    return errores


# ------------------------------------------------------------------
# Captcha (segundo factor del login)
# ------------------------------------------------------------------
_CARACTERES = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sin 0/O ni 1/I para que no se confundan


def _fuente(tamano):
    for nombre in (os.path.join(CARPETA_FUENTES, "DejaVuSans-Bold.ttf"), "arialbd.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(nombre, tamano)
        except OSError:
            continue
    return ImageFont.load_default(size=tamano)


def nuevo_captcha():
    """Genera un texto aleatorio, lo guarda en la sesión y devuelve la imagen PNG."""
    texto = "".join(random.choice(_CARACTERES) for _ in range(5))
    session["captcha"] = texto
    ancho, alto = 200, 70
    img = Image.new("RGB", (ancho, alto), (245, 247, 250))
    dibujo = ImageDraw.Draw(img)
    for _ in range(8):  # líneas de ruido
        dibujo.line(
            [(random.randint(0, ancho), random.randint(0, alto)),
             (random.randint(0, ancho), random.randint(0, alto))],
            fill=(random.randint(120, 200), random.randint(120, 200), random.randint(120, 200)),
            width=2,
        )
    x = 12
    for letra in texto:
        capa = Image.new("RGBA", (45, 60), (0, 0, 0, 0))
        ImageDraw.Draw(capa).text(
            (6, 4), letra, font=_fuente(38),
            fill=(random.randint(10, 90), random.randint(10, 90), random.randint(60, 140)),
        )
        capa = capa.rotate(random.randint(-30, 30), expand=False, resample=Image.BICUBIC)
        img.paste(capa, (x, random.randint(0, 10)), capa)
        x += 36
    for _ in range(250):  # puntos de ruido
        dibujo.point((random.randint(0, ancho - 1), random.randint(0, alto - 1)), fill=(100, 100, 100))
    img = img.filter(ImageFilter.SMOOTH)
    salida = io.BytesIO()
    img.save(salida, "PNG")
    return salida.getvalue()


def captcha_correcto(respuesta):
    esperado = session.pop("captcha", None)  # se usa una sola vez
    return bool(esperado) and (respuesta or "").strip().upper() == esperado


# ------------------------------------------------------------------
# Protección CSRF sencilla para formularios
# ------------------------------------------------------------------
def token_csrf():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


def revisar_csrf():
    if request.method == "POST":
        if request.form.get("csrf") != session.get("csrf"):
            abort(400, "Formulario vencido. Recargue la página e intente de nuevo.")


# ------------------------------------------------------------------
# Sesión y roles
# ------------------------------------------------------------------
def login_requerido(funcion):
    @wraps(funcion)
    def envoltura(*args, **kwargs):
        if "id_usuario" not in session:
            flash("Debe iniciar sesión.", "aviso")
            return redirect(url_for("login", siguiente=request.path))
        return funcion(*args, **kwargs)
    return envoltura


def rol_requerido(*roles):
    def decorador(funcion):
        @wraps(funcion)
        @login_requerido
        def envoltura(*args, **kwargs):
            if session.get("rol") not in roles:
                auditar("ACCESO_DENEGADO", detalle=f"Intentó entrar a {request.path}")
                abort(403)
            return funcion(*args, **kwargs)
        return envoltura
    return decorador


def puede_editar():
    return session.get("rol") in ("Administrador", "Operador")


# ------------------------------------------------------------------
# Auditoría
# ------------------------------------------------------------------
def ip_cliente():
    return (request.headers.get("X-Forwarded-For") or request.remote_addr or "")[:45]


def auditar(accion, tabla=None, id_registro=None, detalle=None, id_usuario="sesion"):
    """Guarda una acción en la tabla Auditoria. Si falla, no detiene la aplicación."""
    if id_usuario == "sesion":
        id_usuario = session.get("id_usuario")
    try:
        ejecutar(
            """INSERT INTO Auditoria (ID_Usuario, Accion, Tabla_Afectada, ID_Registro, Detalle, Direccion_IP)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (id_usuario, accion[:20], tabla, None if id_registro is None else str(id_registro)[:50],
             detalle, ip_cliente()),
        )
    except Exception as e:  # pragma: no cover
        print("No se pudo guardar la auditoría:", e)


def texto_aleatorio(n=10):
    return "".join(random.choice(string.ascii_letters + string.digits) for _ in range(n))
