"""EntreCOL+ - Sistema de Información (aplicación web)

Proyecto Final Bases de Datos 2026-2 - ColPlus-Solutions
Ejecutar:  python app.py   y abrir http://127.0.0.1:5000
"""
import datetime
import decimal
import json
import math
import os
import re
from collections import OrderedDict

import pymysql
from flask import (Flask, Response, abort, flash, redirect, render_template, request, session,
                   url_for)
from werkzeug.utils import secure_filename

import config
from cargadores import ErrorCarga, cargar_libros, cargar_nomina, cargar_peliculas
from db import conectar, consultar, consultar_uno, ejecutar
from entidades import ENTIDADES, TABLAS_CONSULTA
from informes_base import LIMITE_FILAS_HTML, Reporte, generar_pdf
from reportes import REPORTES, SECCIONES_ENTRETENIMIENTO
from seguridad import (auditar, captcha_correcto, cifrar_contrasena, login_requerido, nuevo_captcha,
                       puede_editar, revisar_csrf, rol_requerido, token_csrf, validar_politica,
                       verificar_contrasena)

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.permanent_session_lifetime = datetime.timedelta(minutes=config.MINUTOS_SESION)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # archivos de hasta 50 MB
os.makedirs(config.CARPETA_CARGAS, exist_ok=True)


@app.before_request
def antes_de_cada_peticion():
    session.permanent = True
    revisar_csrf()


@app.context_processor
def variables_globales():
    grupos = OrderedDict()
    for clave, e in ENTIDADES.items():
        grupos.setdefault(e["grupo"], []).append((clave, e["titulo"]))
    return {"csrf_token": token_csrf, "menu_entidades": grupos, "puede_editar": puede_editar(),
            "rol": session.get("rol"), "usuario_nombre": session.get("nombre"), "reportes": REPORTES}


@app.template_filter("valor")
def formato_valor(v):
    if v is None:
        return ""
    if isinstance(v, decimal.Decimal):
        return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if isinstance(v, datetime.datetime):
        return v.strftime("%d/%m/%Y %H:%M:%S")
    if isinstance(v, datetime.date):
        return v.strftime("%d/%m/%Y")
    return v


@app.errorhandler(403)
def prohibido(e):
    return render_template("error.html", codigo=403, mensaje="No tiene permiso para entrar a esta página."), 403


@app.errorhandler(404)
def no_encontrado(e):
    return render_template("error.html", codigo=404, mensaje="La página no existe."), 404


@app.errorhandler(400)
def peticion_mala(e):
    return render_template("error.html", codigo=400, mensaje=e.description), 400


@app.errorhandler(pymysql.err.OperationalError)
def error_bd(e):
    return render_template("error.html", codigo=500,
                           mensaje=f"No hay conexión con MySQL. Revise config.py. Detalle: {e}"), 500


# ==================================================================
# LOGIN / LOGOUT
# ==================================================================
@app.route("/captcha.png")
def captcha():
    return Response(nuevo_captcha(), mimetype="image/png",
                    headers={"Cache-Control": "no-store"})


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        usuario = (request.form.get("usuario") or "").strip()
        contrasena = request.form.get("contrasena") or ""
        # Paso 1: captcha (segundo factor)
        if not captcha_correcto(request.form.get("captcha")):
            auditar("LOGIN_FALLIDO", "Usuario", detalle=f"Captcha incorrecto para '{usuario}'", id_usuario=None)
            flash("El código de verificación (captcha) no es correcto.", "error")
            return render_template("login.html", usuario=usuario)
        # Paso 2: usuario y contraseña
        u = consultar_uno(
            """SELECT u.*, r.Nombre AS Rol FROM Usuario u JOIN Rol r ON r.ID_Rol = u.ID_Rol
               WHERE u.Username = %s""", (usuario,))
        if not u:
            auditar("LOGIN_FALLIDO", "Usuario", detalle=f"Usuario inexistente '{usuario}'", id_usuario=None)
            flash("Usuario o contraseña incorrectos.", "error")
            return render_template("login.html", usuario=usuario)
        if not u["Activo"]:
            auditar("LOGIN_FALLIDO", "Usuario", u["ID_Usuario"], "Usuario inactivo o bloqueado",
                    id_usuario=u["ID_Usuario"])
            flash("El usuario está bloqueado o inactivo. Contacte al administrador.", "error")
            return render_template("login.html", usuario=usuario)
        if not verificar_contrasena(contrasena, u["Contrasena_Cifrada"]):
            intentos = u["Intentos_Fallidos"] + 1
            bloquear = intentos >= config.MAX_INTENTOS_FALLIDOS
            ejecutar("UPDATE Usuario SET Intentos_Fallidos=%s, Activo=%s WHERE ID_Usuario=%s",
                     (intentos, 0 if bloquear else 1, u["ID_Usuario"]))
            auditar("BLOQUEO" if bloquear else "LOGIN_FALLIDO", "Usuario", u["ID_Usuario"],
                    f"Contraseña incorrecta (intento {intentos})", id_usuario=u["ID_Usuario"])
            if bloquear:
                flash("Usuario bloqueado por superar el número de intentos.", "error")
            else:
                flash(f"Usuario o contraseña incorrectos. Le quedan "
                      f"{config.MAX_INTENTOS_FALLIDOS - intentos} intento(s).", "error")
            return render_template("login.html", usuario=usuario)
        # Login correcto
        ejecutar("UPDATE Usuario SET Intentos_Fallidos=0 WHERE ID_Usuario=%s", (u["ID_Usuario"],))
        session.clear()
        session.update({"id_usuario": u["ID_Usuario"], "usuario": u["Username"], "nombre": u["Nombre"],
                        "rol": u["Rol"]})
        auditar("LOGIN", "Usuario", u["ID_Usuario"], "Inicio de sesión correcto")
        siguiente = request.args.get("siguiente") or ""
        return redirect(siguiente if siguiente.startswith("/") and not siguiente.startswith("//")
                        else url_for("inicio"))
    return render_template("login.html", usuario="")


@app.route("/logout")
def logout():
    if "id_usuario" in session:
        auditar("LOGOUT", "Usuario", session["id_usuario"], "Cierre de sesión")
    session.clear()
    flash("Sesión cerrada.", "ok")
    return redirect(url_for("login"))


@app.route("/contrasena", methods=["GET", "POST"])
@login_requerido
def cambiar_contrasena():
    if request.method == "POST":
        u = consultar_uno("SELECT Contrasena_Cifrada FROM Usuario WHERE ID_Usuario=%s", (session["id_usuario"],))
        actual, nueva, repetir = (request.form.get(k) or "" for k in ("actual", "nueva", "repetir"))
        errores = validar_politica(nueva)
        if not verificar_contrasena(actual, u["Contrasena_Cifrada"]):
            flash("La contraseña actual no es correcta.", "error")
        elif nueva != repetir:
            flash("La nueva contraseña y su confirmación no coinciden.", "error")
        elif errores:
            flash("La contraseña debe tener: " + ", ".join(errores) + ".", "error")
        else:
            ejecutar("UPDATE Usuario SET Contrasena_Cifrada=%s WHERE ID_Usuario=%s",
                     (cifrar_contrasena(nueva), session["id_usuario"]))
            auditar("UPDATE", "Usuario", session["id_usuario"], "Cambio de contraseña propia")
            flash("Contraseña actualizada.", "ok")
            return redirect(url_for("inicio"))
    return render_template("contrasena.html")


# ==================================================================
# INICIO
# ==================================================================
@app.route("/")
@login_requerido
def inicio():
    conteos = consultar_uno(
        """SELECT (SELECT COUNT(*) FROM Empleado) AS empleados,
                  (SELECT COUNT(*) FROM Dependencia) AS dependencias,
                  (SELECT COUNT(*) FROM Novedad) AS novedades,
                  (SELECT COUNT(*) FROM Pelicula) AS peliculas,
                  (SELECT COUNT(*) FROM Genero) AS generos,
                  (SELECT COUNT(*) FROM Libro) AS libros,
                  (SELECT COUNT(*) FROM Autor) AS autores,
                  (SELECT COUNT(*) FROM Usuario) AS usuarios""")
    cargas = consultar(
        """SELECT c.*, u.Username FROM Carga_Archivo c LEFT JOIN Usuario u ON u.ID_Usuario = c.ID_Usuario
           ORDER BY c.Fecha_Hora DESC LIMIT 5""")
    return render_template("inicio.html", c=conteos, cargas=cargas)


# ==================================================================
# CRUD GENÉRICO
# ==================================================================
def _entidad(clave):
    if clave not in ENTIDADES:
        abort(404)
    return ENTIDADES[clave]


@app.route("/datos/<clave>")
@login_requerido
def crud_lista(clave):
    e = _entidad(clave)
    q = (request.args.get("q") or "").strip()
    pagina = max(1, request.args.get("pagina", 1, type=int))
    por_pagina = 25
    where, params = "", []
    if q:
        where = " WHERE " + " OR ".join(f"{c} LIKE %s" for c in e["buscar"])
        params = [f"%{q}%"] * len(e["buscar"])
    total = consultar_uno(f"SELECT COUNT(*) AS n FROM ({e['lista_sql']}{where}) x", params)["n"]
    filas = consultar(f"{e['lista_sql']}{where} ORDER BY {e['orden']} LIMIT %s OFFSET %s",
                      params + [por_pagina, (pagina - 1) * por_pagina])
    return render_template("crud_lista.html", e=e, clave=clave, filas=filas, q=q, pagina=pagina,
                           paginas=max(1, math.ceil(total / por_pagina)), total=total)


def _opciones(campo):
    return consultar(campo["opciones"]) if campo["tipo"] == "fk" else []


def _leer_formulario(e):
    """Lee y valida los campos del formulario. Devuelve (valores, extras, errores)."""
    valores, extras, errores = {}, {}, []
    for c in e["campos"]:
        crudo = (request.form.get(c["nombre"]) or "").strip()
        if c["tipo"] == "multi_genero":
            extras["generos"] = [int(x) for x in request.form.getlist(c["nombre"]) if x.isdigit()]
            continue
        if c["tipo"] == "autores":
            autores = list(dict.fromkeys(a.strip() for a in crudo.split("/") if a.strip()))
            if c["requerido"] and not autores:
                errores.append(f"{c['etiqueta']}: es obligatorio.")
            extras["autores"] = autores
            continue
        if crudo == "":
            if c["requerido"]:
                errores.append(f"{c['etiqueta']}: es obligatorio.")
            valores[c["nombre"]] = None
            continue
        try:
            if c["tipo"] == "entero":
                v = int(crudo)
            elif c["tipo"] == "decimal":
                v = float(crudo.replace(",", "."))
            elif c["tipo"] == "fecha":
                v = datetime.date.fromisoformat(crudo)
            elif c["tipo"] == "fk":
                v = int(crudo)
            else:
                v = crudo
                if len(v) > c.get("max", 255):
                    raise ValueError(f"máximo {c.get('max')} caracteres")
            if c["tipo"] in ("entero", "decimal"):
                if "min" in c and v < c["min"]:
                    raise ValueError(f"debe ser mayor o igual a {c['min']}")
                if "max_valor" in c and v > c["max_valor"]:
                    raise ValueError(f"debe ser menor o igual a {c['max_valor']}")
            valores[c["nombre"]] = v
        except ValueError as ex:
            errores.append(f"{c['etiqueta']}: valor no válido ({ex}).")
    if e.get("validar") == "fechas_novedad" and not errores:
        if valores["Fecha_Fin"] < valores["Fecha_Inicio"]:
            errores.append("La fecha fin no puede ser menor que la fecha inicio.")
    return valores, extras, errores


def _guardar_relaciones(cur, clave, id_registro, extras):
    if clave == "peliculas":
        cur.execute("DELETE FROM Pelicula_Genero WHERE ID_Pelicula=%s", (id_registro,))
        for g in extras.get("generos", []):
            cur.execute("INSERT INTO Pelicula_Genero (ID_Pelicula, ID_Genero) VALUES (%s,%s)", (id_registro, g))
    if clave == "libros":
        cur.execute("DELETE FROM Libro_Autor WHERE ID_Libro=%s", (id_registro,))
        for orden, nombre in enumerate(extras.get("autores", []), 1):
            cur.execute("SELECT ID_Autor FROM Autor WHERE Nombre=%s", (nombre,))
            fila = cur.fetchone()
            if fila:
                id_autor = fila["ID_Autor"]
            else:
                cur.execute("INSERT INTO Autor (Nombre) VALUES (%s)", (nombre[:255],))
                id_autor = cur.lastrowid
            cur.execute("INSERT INTO Libro_Autor (ID_Libro, ID_Autor, Orden_Autor) VALUES (%s,%s,%s)",
                        (id_registro, id_autor, orden))


def _relaciones_actuales(clave, id_registro):
    if clave == "peliculas":
        return {"generos": [f["ID_Genero"] for f in consultar(
            "SELECT ID_Genero FROM Pelicula_Genero WHERE ID_Pelicula=%s", (id_registro,))]}
    if clave == "libros":
        return {"autores": " / ".join(f["Nombre"] for f in consultar(
            """SELECT a.Nombre FROM Libro_Autor la JOIN Autor a ON a.ID_Autor = la.ID_Autor
               WHERE la.ID_Libro=%s ORDER BY la.Orden_Autor""", (id_registro,)))}
    return {}


def _texto_error_bd(ex):
    codigo = ex.args[0] if ex.args else 0
    if codigo == 1062:
        return "Ya existe un registro con ese valor (llave o dato único repetido)."
    if codigo in (1451,):
        return "No se puede eliminar porque otros registros dependen de este."
    if codigo in (1452,):
        return "El valor escogido en una lista no existe."
    if codigo in (3819, 4025):
        return "Algún valor no cumple las reglas de la tabla (CHECK)."
    return f"Error de base de datos: {ex.args[-1] if ex.args else ex}"


@app.route("/datos/<clave>/nuevo", methods=["GET", "POST"])
@app.route("/datos/<clave>/<id_registro>/editar", methods=["GET", "POST"])
@rol_requerido("Administrador", "Operador")
def crud_form(clave, id_registro=None):
    e = _entidad(clave)
    editando = id_registro is not None
    registro, extras_actuales = {}, {}
    if editando:
        registro = consultar_uno(f"SELECT * FROM {e['tabla']} WHERE {e['llave']}=%s", (id_registro,))
        if not registro:
            abort(404)
        extras_actuales = _relaciones_actuales(clave, id_registro)

    if request.method == "POST":
        valores, extras, errores = _leer_formulario(e)
        if errores:
            for err in errores:
                flash(err, "error")
            registro = {**registro, **valores}
            extras_actuales = {"generos": extras.get("generos", []),
                               "autores": " / ".join(extras.get("autores", []))}
        else:
            con = conectar()
            try:
                cur = con.cursor()
                if editando:
                    columnas = [k for k in valores if not (k == e["llave"])]
                    cur.execute(
                        f"UPDATE {e['tabla']} SET {', '.join(f'{k}=%s' for k in columnas)} WHERE {e['llave']}=%s",
                        [valores[k] for k in columnas] + [id_registro])
                    nuevo_id = id_registro
                    accion = "UPDATE"
                else:
                    columnas = list(valores)
                    cur.execute(
                        f"INSERT INTO {e['tabla']} ({', '.join(columnas)}) VALUES ({', '.join(['%s'] * len(columnas))})",
                        [valores[k] for k in columnas])
                    nuevo_id = valores.get(e["llave"]) if e["llave_manual"] else cur.lastrowid
                    accion = "INSERT"
                _guardar_relaciones(cur, clave, nuevo_id, extras)
                con.commit()
                detalle = json.dumps({k: str(v) for k, v in {**valores, **extras}.items()}, ensure_ascii=False)
                auditar(accion, e["tabla"], nuevo_id, detalle)
                flash(f"Se guardó el {e['singular']} correctamente." if e["singular"][-1] != "a"
                      else f"Se guardó la {e['singular']} correctamente.", "ok")
                return redirect(url_for("crud_lista", clave=clave))
            except pymysql.err.MySQLError as ex:
                con.rollback()
                flash(_texto_error_bd(ex), "error")
                registro = {**registro, **valores}
            finally:
                con.close()

    opciones = {c["nombre"]: _opciones(c) for c in e["campos"]}
    if clave == "peliculas":
        opciones["_generos"] = consultar("SELECT ID_Genero AS id, Nombre AS texto FROM Genero ORDER BY Nombre")
    return render_template("crud_form.html", e=e, clave=clave, registro=registro, editando=editando,
                           opciones=opciones, extras=extras_actuales, id_registro=id_registro)


@app.route("/datos/<clave>/<id_registro>/eliminar", methods=["POST"])
@rol_requerido("Administrador", "Operador")
def crud_eliminar(clave, id_registro):
    e = _entidad(clave)
    registro = consultar_uno(f"SELECT * FROM {e['tabla']} WHERE {e['llave']}=%s", (id_registro,))
    if not registro:
        abort(404)
    try:
        ejecutar(f"DELETE FROM {e['tabla']} WHERE {e['llave']}=%s", (id_registro,))
        auditar("DELETE", e["tabla"], id_registro,
                json.dumps({k: str(v) for k, v in registro.items()}, ensure_ascii=False))
        flash("Registro eliminado.", "ok")
    except pymysql.err.MySQLError as ex:
        flash(_texto_error_bd(ex), "error")
    return redirect(url_for("crud_lista", clave=clave))


# ==================================================================
# CARGA DE ARCHIVOS
# ==================================================================
@app.route("/cargas", methods=["GET", "POST"])
@login_requerido
def cargas():
    resultado = None
    if request.method == "POST":
        if not puede_editar():
            abort(403)
        tipo = request.form.get("tipo")
        archivo = request.files.get("archivo")
        extensiones = {"NOMINA": (".xlsx",), "PELICULAS": (".dat", ".txt"), "LIBROS": (".json",)}
        if not archivo or not archivo.filename:
            flash("Seleccione un archivo.", "error")
        elif tipo not in extensiones:
            flash("Seleccione el tipo de archivo.", "error")
        elif not archivo.filename.lower().endswith(extensiones[tipo]):
            flash(f"Para {tipo.lower()} el archivo debe ser {' o '.join(extensiones[tipo])}.", "error")
        else:
            nombre = secure_filename(archivo.filename) or "archivo"
            ruta = os.path.join(config.CARPETA_CARGAS,
                                f"{datetime.datetime.now():%Y%m%d%H%M%S}_{nombre}")
            archivo.save(ruta)
            try:
                if tipo == "NOMINA":
                    periodo = request.form.get("periodo") or ""
                    if not re.fullmatch(r"\d{4}-\d{2}", periodo):
                        raise ErrorCarga("Indique el mes y año de la liquidación.")
                    anio, mes = periodo.split("-")
                    resultado = cargar_nomina(ruta, anio, mes, session["id_usuario"], archivo.filename)
                elif tipo == "PELICULAS":
                    resultado = cargar_peliculas(ruta, session["id_usuario"], archivo.filename)
                else:
                    resultado = cargar_libros(ruta, session["id_usuario"], archivo.filename)
                auditar("CARGA", "Carga_Archivo", resultado["id_carga"],
                        f"{tipo}: {archivo.filename} - cargados {resultado['cargados']}, "
                        f"rechazados {resultado['rechazados']}")
                flash(f"Carga terminada: {resultado['cargados']} registros cargados y "
                      f"{resultado['rechazados']} rechazados.", "ok")
            except ErrorCarga as ex:
                auditar("CARGA_FALLIDA", "Carga_Archivo", None, f"{tipo}: {archivo.filename} - {ex}")
                flash(f"No se pudo cargar el archivo: {ex}", "error")
            finally:
                try:
                    os.remove(ruta)
                except OSError:
                    pass
    historial = consultar(
        """SELECT c.*, u.Username FROM Carga_Archivo c LEFT JOIN Usuario u ON u.ID_Usuario = c.ID_Usuario
           ORDER BY c.Fecha_Hora DESC LIMIT 50""")
    return render_template("cargas.html", resultado=resultado, historial=historial,
                           mes_actual=datetime.date.today().strftime("%Y-%m"))


@app.route("/cargas/<int:id_carga>")
@login_requerido
def carga_detalle(id_carga):
    c = consultar_uno(
        """SELECT c.*, u.Username FROM Carga_Archivo c LEFT JOIN Usuario u ON u.ID_Usuario = c.ID_Usuario
           WHERE c.ID_Carga=%s""", (id_carga,))
    if not c:
        abort(404)
    return render_template("carga_detalle.html", c=c)


# ==================================================================
# CONSULTAS DINÁMICAS
# ==================================================================
OPERADORES = OrderedDict([("=", "igual a"), ("<>", "diferente de"), (">", "mayor que"), ("<", "menor que"),
                          (">=", "mayor o igual"), ("<=", "menor o igual"), ("LIKE", "contiene"),
                          ("IS NULL", "está vacío")])


def _columnas_de(tabla):
    return [f["COLUMN_NAME"] for f in consultar(
        """SELECT COLUMN_NAME FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s ORDER BY ORDINAL_POSITION""", (tabla,))]


@app.route("/consultas", methods=["GET", "POST"])
@login_requerido
def consultas():
    columnas_por_tabla = {t: _columnas_de(t) for t in TABLAS_CONSULTA}
    resultado, sql_mostrado, f = None, None, request.form
    if request.method == "POST":
        modo = f.get("modo", "constructor")
        try:
            if modo == "sql":
                if session.get("rol") != "Administrador":
                    abort(403)
                sql_mostrado = (f.get("sql") or "").strip().rstrip(";")
                if ";" in sql_mostrado or not re.match(r"(?is)^\s*(SELECT|WITH|SHOW|DESCRIBE|EXPLAIN)\b", sql_mostrado):
                    raise ValueError("Solo se permite una consulta de lectura (SELECT).")
                con = conectar(solo_lectura=True)
                try:
                    with con.cursor() as cur:
                        cur.execute("START TRANSACTION READ ONLY")
                        cur.execute(sql_mostrado)  # sin parámetros: el texto va tal cual
                        filas = cur.fetchmany(LIMITE_FILAS_HTML * 5)
                        columnas = [d[0] for d in cur.description] if cur.description else []
                    con.rollback()
                finally:
                    con.close()
            else:
                tabla = f.get("tabla")
                if tabla not in columnas_por_tabla:
                    raise ValueError("Tabla no válida.")
                validas = columnas_por_tabla[tabla]
                columnas = [c for c in f.getlist("columnas") if c in validas] or validas
                sql = f"SELECT {', '.join(columnas)} FROM {tabla}"
                params = []
                filtro_col, op, valor = f.get("filtro_col"), f.get("operador"), f.get("valor", "")
                if filtro_col in validas and op in OPERADORES:
                    if op == "IS NULL":
                        sql += f" WHERE {filtro_col} IS NULL"
                    elif op == "LIKE":
                        sql += f" WHERE {filtro_col} LIKE %s"
                        params.append(f"%{valor}%")
                    elif valor != "":
                        sql += f" WHERE {filtro_col} {op} %s"
                        params.append(valor)
                orden_col = f.get("orden_col")
                if orden_col in validas:
                    sql += f" ORDER BY {orden_col} {'DESC' if f.get('orden_dir') == 'DESC' else 'ASC'}"
                limite = min(max(f.get("limite", 100, type=int), 1), 5000)
                sql += " LIMIT %s"
                params.append(limite)
                filas = consultar(sql, params)
                sql_mostrado = sql.replace("%s", "?") + f"   -- parámetros: {params}"
            resultado = {"columnas": columnas, "filas": filas}
            auditar("CONSULTA", None, None, sql_mostrado[:1000])
            if f.get("accion") == "pdf":
                r = Reporte("Resultado de consulta dinámica", sql_mostrado[:500])
                r.texto(f"Filas: {len(filas)}")
                r.tabla(columnas, [[formato_valor(fl[c]) for c in columnas] for fl in filas])
                return _respuesta_pdf(r, "consulta.pdf")
        except (ValueError, pymysql.err.MySQLError) as ex:
            flash(f"Error en la consulta: {ex}", "error")
    return render_template("consultas.html", columnas_por_tabla=columnas_por_tabla, operadores=OPERADORES,
                           resultado=resultado, sql=sql_mostrado, f=f, limite_html=LIMITE_FILAS_HTML)


# ==================================================================
# REPORTES
# ==================================================================
def _respuesta_pdf(reporte, nombre):
    pdf = generar_pdf(reporte, session.get("usuario", ""))
    return Response(pdf, mimetype="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{nombre}"'})


@app.route("/reportes")
@login_requerido
def reportes_inicio():
    return render_template("reportes.html")


@app.route("/reportes/<clave>")
@login_requerido
def reporte_ver(clave):
    if clave not in REPORTES:
        abort(404)
    info = REPORTES[clave]
    reporte = info["funcion"](request.args) if request.args.get("generar") else None
    if reporte:
        auditar("REPORTE", None, None, f"{info['nombre']} {dict(request.args)}")
    empleados = consultar("SELECT Codigo, Nombre FROM Empleado ORDER BY Nombre") if clave == "personal" else []
    generos = consultar("SELECT ID_Genero, Nombre FROM Genero ORDER BY Nombre") if clave == "entretenimiento" else []
    return render_template("reporte.html", clave=clave, info=info, reporte=reporte, args=request.args,
                           empleados=empleados, generos=generos, secciones_ent=SECCIONES_ENTRETENIMIENTO,
                           limite_html=LIMITE_FILAS_HTML)


@app.route("/reportes/<clave>/pdf")
@login_requerido
def reporte_pdf(clave):
    if clave not in REPORTES:
        abort(404)
    reporte = REPORTES[clave]["funcion"](request.args)
    auditar("REPORTE_PDF", None, None, f"{REPORTES[clave]['nombre']} {dict(request.args)}")
    return _respuesta_pdf(reporte, f"reporte_{clave}.pdf")


# ==================================================================
# USUARIOS (solo Administrador)
# ==================================================================
@app.route("/usuarios")
@rol_requerido("Administrador")
def usuarios():
    filas = consultar("""SELECT u.*, r.Nombre AS Rol FROM Usuario u JOIN Rol r ON r.ID_Rol = u.ID_Rol
                         ORDER BY u.Username""")
    return render_template("usuarios.html", filas=filas, maximo=config.MAX_INTENTOS_FALLIDOS)


@app.route("/usuarios/nuevo", methods=["GET", "POST"])
@app.route("/usuarios/<int:id_usuario>/editar", methods=["GET", "POST"])
@rol_requerido("Administrador")
def usuario_form(id_usuario=None):
    roles = consultar("SELECT * FROM Rol ORDER BY ID_Rol")
    u = consultar_uno("SELECT * FROM Usuario WHERE ID_Usuario=%s", (id_usuario,)) if id_usuario else {}
    if id_usuario and not u:
        abort(404)
    if request.method == "POST":
        f = request.form
        datos = {"Username": f.get("username", "").strip(), "Nombre": f.get("nombre", "").strip(),
                 "Email": f.get("email", "").strip(), "ID_Rol": f.get("rol", type=int),
                 "Activo": 1 if f.get("activo") else 0}
        contrasena = f.get("contrasena") or ""
        errores = []
        if not re.fullmatch(r"[A-Za-z0-9_.]{3,50}", datos["Username"]):
            errores.append("El usuario debe tener de 3 a 50 caracteres (letras, números, punto o guion bajo).")
        if not datos["Nombre"]:
            errores.append("El nombre es obligatorio.")
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", datos["Email"]):
            errores.append("El correo no es válido.")
        if contrasena or not id_usuario:
            faltan = validar_politica(contrasena)
            if faltan:
                errores.append("La contraseña debe tener: " + ", ".join(faltan) + ".")
        if id_usuario == session["id_usuario"] and (not datos["Activo"] or datos["ID_Rol"] != u["ID_Rol"]):
            errores.append("No puede desactivarse ni cambiarse el rol a sí mismo.")
        if errores:
            for e in errores:
                flash(e, "error")
            u = {**u, **datos}
        else:
            try:
                if id_usuario:
                    sets = "Username=%s, Nombre=%s, Email=%s, ID_Rol=%s, Activo=%s"
                    params = [datos["Username"], datos["Nombre"], datos["Email"], datos["ID_Rol"], datos["Activo"]]
                    if datos["Activo"]:
                        sets += ", Intentos_Fallidos=0"
                    if contrasena:
                        sets += ", Contrasena_Cifrada=%s"
                        params.append(cifrar_contrasena(contrasena))
                    ejecutar(f"UPDATE Usuario SET {sets} WHERE ID_Usuario=%s", params + [id_usuario])
                    auditar("UPDATE", "Usuario", id_usuario,
                            f"Edición de usuario {datos['Username']}" + (" (cambio de contraseña)" if contrasena else ""))
                else:
                    nuevo = ejecutar(
                        """INSERT INTO Usuario (Username, Contrasena_Cifrada, Nombre, Email, ID_Rol, Activo)
                           VALUES (%s,%s,%s,%s,%s,%s)""",
                        (datos["Username"], cifrar_contrasena(contrasena), datos["Nombre"], datos["Email"],
                         datos["ID_Rol"], datos["Activo"]))
                    auditar("INSERT", "Usuario", nuevo, f"Creación de usuario {datos['Username']}")
                flash("Usuario guardado.", "ok")
                return redirect(url_for("usuarios"))
            except pymysql.err.MySQLError as ex:
                flash(_texto_error_bd(ex), "error")
                u = {**u, **datos}
    return render_template("usuario_form.html", u=u, roles=roles, id_usuario=id_usuario)


@app.route("/usuarios/<int:id_usuario>/eliminar", methods=["POST"])
@rol_requerido("Administrador")
def usuario_eliminar(id_usuario):
    if id_usuario == session["id_usuario"]:
        flash("No puede eliminar su propio usuario.", "error")
    else:
        u = consultar_uno("SELECT Username FROM Usuario WHERE ID_Usuario=%s", (id_usuario,))
        ejecutar("DELETE FROM Usuario WHERE ID_Usuario=%s", (id_usuario,))
        auditar("DELETE", "Usuario", id_usuario, f"Eliminación de usuario {u['Username'] if u else ''}")
        flash("Usuario eliminado.", "ok")
    return redirect(url_for("usuarios"))


# ==================================================================
# AUDITORÍA (solo Administrador)
# ==================================================================
def _filtrar_auditoria(args):
    where, params = [], []
    if args.get("usuario"):
        where.append("u.Username LIKE %s")
        params.append(f"%{args['usuario']}%")
    if args.get("accion"):
        where.append("a.Accion = %s")
        params.append(args["accion"])
    if args.get("desde"):
        where.append("a.Fecha_Hora >= %s")
        params.append(args["desde"])
    if args.get("hasta"):
        where.append("a.Fecha_Hora < DATE_ADD(%s, INTERVAL 1 DAY)")
        params.append(args["hasta"])
    sql = """SELECT a.*, u.Username FROM Auditoria a LEFT JOIN Usuario u ON u.ID_Usuario = a.ID_Usuario"""
    if where:
        sql += " WHERE " + " AND ".join(where)
    return sql, params


@app.route("/auditoria")
@rol_requerido("Administrador")
def auditoria():
    sql, params = _filtrar_auditoria(request.args)
    pagina = max(1, request.args.get("pagina", 1, type=int))
    total = consultar_uno(f"SELECT COUNT(*) AS n FROM ({sql}) x", params)["n"]
    filas = consultar(sql + " ORDER BY a.Fecha_Hora DESC, a.ID_Auditoria DESC LIMIT 50 OFFSET %s",
                      params + [(pagina - 1) * 50])
    acciones = [f["Accion"] for f in consultar("SELECT DISTINCT Accion FROM Auditoria ORDER BY Accion")]
    return render_template("auditoria.html", filas=filas, args=request.args, acciones=acciones,
                           pagina=pagina, paginas=max(1, math.ceil(total / 50)), total=total)


@app.route("/auditoria/pdf")
@rol_requerido("Administrador")
def auditoria_pdf():
    sql, params = _filtrar_auditoria(request.args)
    filas = consultar(sql + " ORDER BY a.Fecha_Hora DESC LIMIT 5000", params)
    filtros = ", ".join(f"{k}={v}" for k, v in request.args.items() if v) or "sin filtros"
    r = Reporte("Reporte de Auditoría de Usuarios", f"Filtros: {filtros}")
    r.texto(f"Registros: {len(filas)}")
    r.tabla(["Fecha y hora", "Usuario", "Acción", "Tabla", "ID registro", "IP", "Detalle"],
            [[formato_valor(f["Fecha_Hora"]), f["Username"] or "-", f["Accion"], f["Tabla_Afectada"] or "",
              f["ID_Registro"] or "", f["Direccion_IP"], (f["Detalle"] or "")[:200]] for f in filas])
    return _respuesta_pdf(r, "auditoria.pdf")


if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=5000)
