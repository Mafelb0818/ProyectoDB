"""Programas de carga de información a la base de datos.

Hay un cargador por cada tipo de archivo que entregó el cliente:
  - cargar_nomina()    -> archivo Excel de nómina (empleados + novedades)
  - cargar_peliculas() -> archivo .dat de películas (id::titulo (año)::generos)
  - cargar_libros()    -> archivo .json de libros

Cada cargador valida registro por registro. Los registros con errores se
rechazan y se guarda el motivo. Al final se deja un registro en la tabla
Carga_Archivo con cuántos se cargaron y cuántos se rechazaron.

Si se vuelve a cargar un archivo con registros que ya existen (mismo código
de empleado, mismo id de película o de libro) el registro se ACTUALIZA, no
se duplica.
"""
import calendar
import datetime
import json
import os
import re
import unicodedata

import openpyxl
import pymysql

from db import conectar


class ErrorCarga(Exception):
    """Error que impide cargar el archivo completo (formato incorrecto)."""


# ------------------------------------------------------------------
# Funciones de ayuda
# ------------------------------------------------------------------
def _normalizar(texto):
    """Quita tildes, espacios de más y pasa a mayúsculas (para comparar encabezados)."""
    texto = unicodedata.normalize("NFKD", str(texto or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return " ".join(texto.upper().split())


def _texto(valor):
    if valor is None:
        return None
    valor = " ".join(str(valor).split())
    return valor or None


def _fecha_excel(valor):
    """Convierte la fecha del Excel a date. Acepta 20210311, '2021-03-11' o datetime."""
    if valor is None or valor == "":
        return None
    if isinstance(valor, datetime.datetime):
        return valor.date()
    if isinstance(valor, datetime.date):
        return valor
    texto = str(valor).strip().split(".")[0]
    for formato in ("%Y%m%d", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.datetime.strptime(texto, formato).date()
        except ValueError:
            pass
    raise ValueError(f"fecha no válida: {valor}")


def _numero(valor, entero=False, defecto=None):
    if valor is None or str(valor).strip() == "":
        if defecto is not None:
            return defecto
        raise ValueError("valor numérico vacío")
    numero = float(str(valor).replace(",", "").strip())
    return int(numero) if entero else numero


class _Catalogo:
    """Busca el id de un valor en una tabla catálogo; si no existe, lo crea.
    Guarda los ids en memoria para no consultar la BD a cada rato."""

    def __init__(self, cur, tabla, col_id, col_nombre="Nombre"):
        self.cur, self.tabla, self.col_id, self.col_nombre = cur, tabla, col_id, col_nombre
        cur.execute(f"SELECT {col_id} AS id, {col_nombre} AS nombre FROM {tabla}")
        self.cache = {_normalizar(f["nombre"]): f["id"] for f in cur.fetchall()}

    def id_de(self, nombre):
        clave = _normalizar(nombre)
        if clave not in self.cache:
            try:
                self.cur.execute("SAVEPOINT sp_catalogo")
                self.cur.execute(
                    f"INSERT INTO {self.tabla} ({self.col_nombre}) VALUES (%s)", (nombre,)
                )
                self.cache[clave] = self.cur.lastrowid
            except pymysql.err.IntegrityError:
                # MySQL lo considera igual a uno existente (mayúsculas/tildes): se usa ese
                self.cur.execute("ROLLBACK TO SAVEPOINT sp_catalogo")
                self.cur.execute(
                    f"SELECT {self.col_id} AS id FROM {self.tabla} WHERE {self.col_nombre}=%s", (nombre,)
                )
                self.cache[clave] = self.cur.fetchone()["id"]
        return self.cache[clave]


def registrar_carga(cur, nombre_archivo, tipo, cargados, rechazados, observaciones, id_usuario):
    texto = "\n".join(observaciones[:300])
    if len(observaciones) > 300:
        texto += f"\n... y {len(observaciones) - 300} observaciones más"
    cur.execute(
        """INSERT INTO Carga_Archivo
           (Nombre_Archivo, Tipo_Archivo, Registros_Cargados, Registros_Rechazados,
            Observaciones, ID_Usuario)
           VALUES (%s,%s,%s,%s,%s,%s)""",
        (nombre_archivo[:150], tipo, cargados, rechazados, texto or None, id_usuario),
    )
    return cur.lastrowid


# ------------------------------------------------------------------
# NÓMINA (Excel)
# ------------------------------------------------------------------
COLUMNAS_EMPLEADOS = {
    "CODIGO": "codigo", "NOMBRE DEL EMPLEADO": "nombre", "DEPENDENCIA": "dependencia",
    "CARGO": "cargo", "FECHA INGRESO": "fecha_ingreso", "EPS": "eps", "ARL": "arl",
    "PENSION": "pension", "SUELDO": "sueldo",
}
COLUMNAS_NOVEDADES = {
    "CODIGO": "codigo",
    "NOVEDAD INCAPACIDAD": "nov_incapacidad",
    "NOVEDAD VACACIONES": "nov_vacaciones",
    "NUMERO DIAS TRABAJADOS EN EL MES": "dias_trabajados",
    "NUMERO DIAS INCAPACIDADES EN EL MES": "dias_incapacidad",
    "NUMERO DE DIAS VACACIONES": "dias_vacaciones",
    "FECHA DE INICIO DE VACACIONES": "ini_vacaciones",
    "FECHA TERMINACION DE VACACIONES": "fin_vacaciones",
    "FECHA INICIO INCAPACIDAD": "ini_incapacidad",
    "FECHA TERMINACION INCAPACIDAD": "fin_incapacidad",
    "BONIFICACION": "bonificacion",
    "TRANSPORTE": "transporte",
}


def _leer_hoja(hoja, columnas_esperadas):
    filas = list(hoja.iter_rows(values_only=True))
    if not filas:
        return None
    encabezado = [_normalizar(c) for c in filas[0]]
    if not all(c in encabezado for c in columnas_esperadas):
        return None
    pos = {columnas_esperadas[c]: encabezado.index(c) for c in columnas_esperadas}
    datos = []
    for numero, fila in enumerate(filas[1:], start=2):
        if all(v is None or str(v).strip() == "" for v in fila):
            continue
        datos.append((numero, {k: fila[i] if i < len(fila) else None for k, i in pos.items()}))
    return datos


def cargar_nomina(ruta, anio, mes, id_usuario=None, nombre_archivo=None):
    """Carga el Excel de nómina. anio/mes = periodo de liquidación de la hoja de novedades."""
    anio, mes = int(anio), int(mes)
    if not (1 <= mes <= 12) or not (1900 <= anio <= 2100):
        raise ErrorCarga("El periodo (año/mes) de la liquidación no es válido.")
    try:
        libro = openpyxl.load_workbook(ruta, data_only=True, read_only=True)
    except Exception as e:
        raise ErrorCarga(f"No se pudo abrir el Excel: {e}")

    empleados = novedades = None
    for hoja in libro.worksheets:
        if empleados is None:
            empleados = _leer_hoja(hoja, COLUMNAS_EMPLEADOS)
            if empleados is not None:
                continue
        if novedades is None:
            novedades = _leer_hoja(hoja, COLUMNAS_NOVEDADES)
    if empleados is None:
        raise ErrorCarga("No se encontró la hoja de empleados (columnas CÓDIGO, NOMBRE DEL EMPLEADO, ...).")

    cargados, rechazados, obs = 0, 0, []
    con = conectar()
    try:
        cur = con.cursor()
        dep = _Catalogo(cur, "Dependencia", "ID_Dependencia")
        cargo = _Catalogo(cur, "Cargo", "ID_Cargo")
        eps = _Catalogo(cur, "EPS", "ID_EPS")
        arl = _Catalogo(cur, "ARL", "ID_ARL")
        pension = _Catalogo(cur, "Fondo_Pension", "ID_Pension")
        cur.execute("SELECT ID_Tipo, Nombre FROM Tipo_Novedad")
        tipos = {f["Nombre"]: f["ID_Tipo"] for f in cur.fetchall()}

        # 1. Empleados
        for fila_n, f in empleados:
            try:
                codigo = _numero(f["codigo"], entero=True)
                nombre = _texto(f["nombre"])
                if not nombre:
                    raise ValueError("nombre vacío")
                fecha = _fecha_excel(f["fecha_ingreso"])
                if fecha is None:
                    raise ValueError("fecha de ingreso vacía")
                sueldo = _numero(f["sueldo"])
                if sueldo < 0:
                    raise ValueError("sueldo negativo")
                campos = {k: _texto(f[k]) for k in ("dependencia", "cargo", "eps", "arl", "pension")}
                for k, v in campos.items():
                    if not v:
                        raise ValueError(f"{k} vacío")
                cur.execute(
                    """INSERT INTO Empleado (Codigo, Nombre, Fecha_Ingreso, Sueldo, ID_Dependencia,
                                             ID_Cargo, ID_EPS, ID_ARL, ID_Pension)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON DUPLICATE KEY UPDATE Nombre=VALUES(Nombre), Fecha_Ingreso=VALUES(Fecha_Ingreso),
                         Sueldo=VALUES(Sueldo), ID_Dependencia=VALUES(ID_Dependencia),
                         ID_Cargo=VALUES(ID_Cargo), ID_EPS=VALUES(ID_EPS), ID_ARL=VALUES(ID_ARL),
                         ID_Pension=VALUES(ID_Pension)""",
                    (codigo, nombre, fecha, sueldo, dep.id_de(campos["dependencia"]),
                     cargo.id_de(campos["cargo"]), eps.id_de(campos["eps"]),
                     arl.id_de(campos["arl"]), pension.id_de(campos["pension"])),
                )
                cargados += 1
            except Exception as e:
                rechazados += 1
                obs.append(f"Empleados fila {fila_n}: rechazada ({e})")

        # 2. Novedades / liquidación del mes
        if novedades is None:
            obs.append("No se encontró la hoja de novedades; solo se cargaron empleados.")
        else:
            for fila_n, f in novedades:
                try:
                    codigo = _numero(f["codigo"], entero=True)
                    cur.execute("SELECT 1 FROM Empleado WHERE Codigo=%s", (codigo,))
                    if not cur.fetchone():
                        raise ValueError(f"el empleado {codigo} no existe")
                    dias = _numero(f["dias_trabajados"], entero=True, defecto=30)
                    if not 0 <= dias <= 31:
                        raise ValueError("días trabajados fuera de rango")
                    bonif = _numero(f["bonificacion"], defecto=0)
                    transp = _numero(f["transporte"], defecto=0)
                    cur.execute(
                        """INSERT INTO Liquidacion_Mes (Codigo_Empleado, Anio, Mes, Dias_Trabajados,
                                                        Bonificacion, Transporte)
                           VALUES (%s,%s,%s,%s,%s,%s)
                           ON DUPLICATE KEY UPDATE Dias_Trabajados=VALUES(Dias_Trabajados),
                             Bonificacion=VALUES(Bonificacion), Transporte=VALUES(Transporte)""",
                        (codigo, anio, mes, dias, bonif, transp),
                    )
                    cur.execute(
                        "SELECT ID_Liquidacion FROM Liquidacion_Mes WHERE Codigo_Empleado=%s AND Anio=%s AND Mes=%s",
                        (codigo, anio, mes),
                    )
                    id_liq = cur.fetchone()["ID_Liquidacion"]
                    # Se reemplazan las novedades de ese mes (por si el archivo se carga otra vez)
                    cur.execute("DELETE FROM Novedad WHERE ID_Liquidacion=%s", (id_liq,))
                    for tipo, marca, ini, fin, ndias in (
                        ("Incapacidad", "nov_incapacidad", "ini_incapacidad", "fin_incapacidad", "dias_incapacidad"),
                        ("Vacaciones", "nov_vacaciones", "ini_vacaciones", "fin_vacaciones", "dias_vacaciones"),
                    ):
                        if _texto(f[marca]):
                            fi, ff = _fecha_excel(f[ini]), _fecha_excel(f[fin])
                            if not fi or not ff:
                                raise ValueError(f"novedad de {tipo.lower()} sin fechas")
                            if ff < fi:
                                raise ValueError(f"la fecha final de {tipo.lower()} es menor que la inicial")
                            n = _numero(f[ndias], entero=True, defecto=(ff - fi).days + 1)
                            cur.execute(
                                """INSERT INTO Novedad (ID_Liquidacion, ID_Tipo, Fecha_Inicio, Fecha_Fin, Numero_De_Dias)
                                   VALUES (%s,%s,%s,%s,%s)""",
                                (id_liq, tipos[tipo], fi, ff, n),
                            )
                    cargados += 1
                except Exception as e:
                    rechazados += 1
                    obs.append(f"Novedades fila {fila_n}: rechazada ({e})")

        id_carga = registrar_carga(cur, nombre_archivo or os.path.basename(ruta), "NOMINA",
                                   cargados, rechazados, obs, id_usuario)
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    return {"id_carga": id_carga, "cargados": cargados, "rechazados": rechazados, "observaciones": obs}


# ------------------------------------------------------------------
# PELÍCULAS (.dat)
# ------------------------------------------------------------------
PATRON_TITULO = re.compile(r"^(.*?)\s*\((\d{4})\)\s*$")


def _leer_texto(ruta):
    with open(ruta, "rb") as fh:
        crudo = fh.read()
    for codificacion in ("utf-8-sig", "latin-1"):
        try:
            return crudo.decode(codificacion)
        except UnicodeDecodeError:
            pass
    raise ErrorCarga("No se pudo leer la codificación del archivo.")


def cargar_peliculas(ruta, id_usuario=None, nombre_archivo=None):
    lineas = _leer_texto(ruta).splitlines()
    validos, obs, rechazados = [], [], 0
    vistos = set()
    for n, linea in enumerate(lineas, start=1):
        if not linea.strip():
            continue
        partes = linea.split("::")
        try:
            if len(partes) != 3:
                raise ValueError("no tiene el formato id::titulo::generos")
            id_peli = int(partes[0])
            if id_peli in vistos:
                raise ValueError(f"id {id_peli} repetido en el archivo")
            titulo_completo = partes[1].strip()
            m = PATRON_TITULO.match(titulo_completo)
            if m:
                titulo, anio = m.group(1).strip(), int(m.group(2))
            else:
                titulo, anio = titulo_completo, None
                obs.append(f"Línea {n}: película {id_peli} sin año en el título (se carga con año vacío)")
            if not titulo:
                raise ValueError("título vacío")
            generos = [g.strip() for g in partes[2].split("|") if g.strip()]
            generos = [g for g in generos if g.lower() != "(no genres listed)"]
            vistos.add(id_peli)
            validos.append((id_peli, titulo[:255], anio, list(dict.fromkeys(generos))))
        except Exception as e:
            rechazados += 1
            obs.append(f"Línea {n}: rechazada ({e})")

    if not validos and rechazados:
        raise ErrorCarga("Ninguna línea tiene el formato de películas (id::titulo (año)::genero1|genero2).")

    con = conectar()
    try:
        cur = con.cursor()
        genero = _Catalogo(cur, "Genero", "ID_Genero")
        for i in range(0, len(validos), 1000):
            bloque = validos[i:i + 1000]
            cur.executemany(
                """INSERT INTO Pelicula (ID_Pelicula, Titulo, Anio) VALUES (%s,%s,%s)
                   ON DUPLICATE KEY UPDATE Titulo=VALUES(Titulo), Anio=VALUES(Anio)""",
                [(p[0], p[1], p[2]) for p in bloque],
            )
            ids = [p[0] for p in bloque]
            cur.execute(
                f"DELETE FROM Pelicula_Genero WHERE ID_Pelicula IN ({','.join(['%s'] * len(ids))})", ids
            )
            pares = [(p[0], genero.id_de(g)) for p in bloque for g in p[3]]
            if pares:
                cur.executemany("INSERT INTO Pelicula_Genero (ID_Pelicula, ID_Genero) VALUES (%s,%s)", pares)
        id_carga = registrar_carga(cur, nombre_archivo or os.path.basename(ruta), "PELICULAS",
                                   len(validos), rechazados, obs, id_usuario)
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    return {"id_carga": id_carga, "cargados": len(validos), "rechazados": rechazados, "observaciones": obs}


# ------------------------------------------------------------------
# LIBROS (.json)
# ------------------------------------------------------------------
def _fecha_libro(texto):
    """Convierte 'M/D/AAAA'. Si el día no existe en ese mes (ej. 11/31/2000) se usa el último día del mes.
    Devuelve (fecha, corregida)."""
    m = re.fullmatch(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*", str(texto or ""))
    if not m:
        raise ValueError(f"fecha de publicación no válida: {texto!r}")
    mes, dia, anio = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not 1 <= mes <= 12:
        raise ValueError(f"mes no válido en la fecha {texto!r}")
    ultimo = calendar.monthrange(anio, mes)[1]
    if dia < 1:
        raise ValueError(f"día no válido en la fecha {texto!r}")
    if dia > ultimo:
        return datetime.date(anio, mes, ultimo), True
    return datetime.date(anio, mes, dia), False


def cargar_libros(ruta, id_usuario=None, nombre_archivo=None):
    try:
        datos = json.loads(_leer_texto(ruta))
    except json.JSONDecodeError as e:
        raise ErrorCarga(f"El archivo no es un JSON válido: {e}")
    if isinstance(datos, dict):
        datos = [datos]
    if not isinstance(datos, list):
        raise ErrorCarga("El JSON debe ser una lista de libros.")

    validos, obs, rechazados, vistos = [], [], 0, set()
    for n, lib in enumerate(datos, start=1):
        try:
            if not isinstance(lib, dict):
                raise ValueError("no es un objeto")
            id_libro = int(lib["bookID"])
            if id_libro in vistos:
                raise ValueError(f"bookID {id_libro} repetido")
            titulo = _texto(lib.get("title"))
            if not titulo:
                raise ValueError("título vacío")
            try:
                rating = float(str(lib.get("average_rating")).strip())
            except ValueError:
                raise ValueError("average_rating no es numérico (registro con columnas corridas)")
            if not 0 <= rating <= 5:
                raise ValueError("rating fuera de 0-5")
            isbn = _texto(lib.get("isbn"))
            isbn13 = _texto(lib.get("isbn13"))
            if isbn and len(isbn) > 10 or isbn13 and len(isbn13) > 13:
                raise ValueError("ISBN con longitud incorrecta")
            paginas = _numero(lib.get("num_pages"), entero=True, defecto=0)
            fecha, corregida = _fecha_libro(lib.get("publication_date"))
            if corregida:
                obs.append(f"Registro {n} (bookID {id_libro}): fecha {lib.get('publication_date')} no existe, "
                           f"se ajustó a {fecha.isoformat()}")
            autores = [a.strip() for a in str(lib.get("authors") or "").split("/") if a.strip()]
            autores = list(dict.fromkeys(a[:255] for a in autores))
            if not autores:
                raise ValueError("sin autores")
            vistos.add(id_libro)
            validos.append({
                "id": id_libro, "titulo": titulo[:500], "isbn": isbn, "isbn13": isbn13,
                "paginas": paginas, "fecha": fecha, "rating": rating,
                "n_ratings": _numero(lib.get("ratings_count"), entero=True, defecto=0),
                "n_resenas": _numero(lib.get("text_reviews_count"), entero=True, defecto=0),
                "editorial": _texto(lib.get("publisher")), "idioma": _texto(lib.get("language_code")),
                "autores": autores,
            })
        except Exception as e:
            rechazados += 1
            obs.append(f"Registro {n}: rechazado ({e})")

    con = conectar()
    try:
        cur = con.cursor()
        editorial = _Catalogo(cur, "Editorial", "ID_Editorial")
        idioma = _Catalogo(cur, "Idioma", "ID_Idioma", "Codigo")
        autor = _Catalogo(cur, "Autor", "ID_Autor")
        for i in range(0, len(validos), 1000):
            bloque = validos[i:i + 1000]
            cur.executemany(
                """INSERT INTO Libro (ID_Libro, Titulo, ISBN, ISBN13, Numero_Paginas, Fecha_Publicacion,
                                      Rating_Promedio, Cantidad_Ratings, Cantidad_Resenas, ID_Editorial, ID_Idioma)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON DUPLICATE KEY UPDATE Titulo=VALUES(Titulo), ISBN=VALUES(ISBN), ISBN13=VALUES(ISBN13),
                     Numero_Paginas=VALUES(Numero_Paginas), Fecha_Publicacion=VALUES(Fecha_Publicacion),
                     Rating_Promedio=VALUES(Rating_Promedio), Cantidad_Ratings=VALUES(Cantidad_Ratings),
                     Cantidad_Resenas=VALUES(Cantidad_Resenas), ID_Editorial=VALUES(ID_Editorial),
                     ID_Idioma=VALUES(ID_Idioma)""",
                [(b["id"], b["titulo"], b["isbn"], b["isbn13"], b["paginas"], b["fecha"], b["rating"],
                  b["n_ratings"], b["n_resenas"],
                  editorial.id_de(b["editorial"]) if b["editorial"] else None,
                  idioma.id_de(b["idioma"]) if b["idioma"] else None) for b in bloque],
            )
            ids = [b["id"] for b in bloque]
            cur.execute(f"DELETE FROM Libro_Autor WHERE ID_Libro IN ({','.join(['%s'] * len(ids))})", ids)
            cur.executemany(
                "INSERT INTO Libro_Autor (ID_Libro, ID_Autor, Orden_Autor) VALUES (%s,%s,%s)",
                [(b["id"], autor.id_de(a), orden) for b in bloque for orden, a in enumerate(b["autores"], 1)],
            )
        id_carga = registrar_carga(cur, nombre_archivo or os.path.basename(ruta), "LIBROS",
                                   len(validos), rechazados, obs, id_usuario)
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    return {"id_carga": id_carga, "cargados": len(validos), "rechazados": rechazados, "observaciones": obs}
