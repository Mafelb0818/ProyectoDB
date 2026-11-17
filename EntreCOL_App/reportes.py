"""Los 5 reportes que pidió el cliente.

Cada reporte recibe los parámetros que escoge el usuario (orden, fechas, N...)
y devuelve un objeto Reporte con tablas y gráficos.
Todas las consultas usan parámetros (%s) para evitar inyección SQL.
"""
import calendar
import datetime
from collections import OrderedDict, defaultdict

from db import consultar
from informes_base import (Reporte, grafico_barras, grafico_barras_agrupadas,
                           grafico_torta)


# ------------------------------------------------------------------
# Ayudas para leer parámetros
# ------------------------------------------------------------------
def _orden(args, nombre="orden"):
    return "DESC" if (args.get(nombre) or "").lower() == "desc" else "ASC"


def _texto_orden(o):
    return "descendente (Z-A)" if o == "DESC" else "ascendente (A-Z)"


def _entero(args, nombre, defecto, minimo=None, maximo=None):
    try:
        valor = int(args.get(nombre, defecto))
    except (TypeError, ValueError):
        valor = defecto
    if minimo is not None:
        valor = max(minimo, valor)
    if maximo is not None:
        valor = min(maximo, valor)
    return valor


def _mes_anio(texto, defecto):
    """Convierte 'MM/AAAA' o 'AAAA-MM' (input type=month) en (año, mes)."""
    texto = (texto or "").strip()
    try:
        if "/" in texto:
            m, a = texto.split("/")
        else:
            a, m = texto.split("-")
        a, m = int(a), int(m)
        if 1 <= m <= 12:
            return a, m
    except ValueError:
        pass
    return defecto


def _fecha(d):
    return d.strftime("%d/%m/%Y") if d else ""


def _pesos(v):
    return "$ {:,.0f}".format(float(v or 0)).replace(",", ".")


# ==================================================================
# 1. REPORTE DE NÓMINA
# ==================================================================
def reporte_nomina(args):
    o = _orden(args)
    r = Reporte("Reporte de Nómina", f"Orden de nombres: {_texto_orden(o)}")

    base = """SELECT e.Codigo, e.Nombre, d.Nombre AS Dependencia, c.Nombre AS Cargo
              FROM Empleado e
              JOIN Dependencia d ON d.ID_Dependencia = e.ID_Dependencia
              JOIN Cargo c ON c.ID_Cargo = e.ID_Cargo"""

    # a. Cantidad y lista de empleados
    filas = consultar(f"{base} ORDER BY e.Nombre {o}")
    r.titulo_seccion(f"a. Empleados de la empresa  (cantidad: {len(filas)})")
    r.tabla(["Código", "Nombre", "Dependencia", "Cargo"],
            [[f["Codigo"], f["Nombre"], f["Dependencia"], f["Cargo"]] for f in filas])

    # b. Por dependencia
    filas = consultar(f"{base} ORDER BY d.Nombre ASC, e.Nombre {o}")
    grupos = OrderedDict()
    for f in filas:
        grupos.setdefault(f["Dependencia"], []).append(f)
    r.titulo_seccion("b. Empleados por dependencia")
    r.tabla(["Dependencia", "Cantidad"], [[d, len(l)] for d, l in grupos.items()], "Resumen")
    for dep, lista in grupos.items():
        r.tabla(["Código", "Nombre", "Cargo"], [[f["Codigo"], f["Nombre"], f["Cargo"]] for f in lista],
                f"{dep}  —  {len(lista)} empleado(s)")

    # c. Por cargo por dependencia
    filas = consultar(f"{base} ORDER BY d.Nombre ASC, c.Nombre ASC, e.Nombre {o}")
    grupos_c = OrderedDict()
    for f in filas:
        grupos_c.setdefault((f["Dependencia"], f["Cargo"]), []).append(f)
    r.titulo_seccion("c. Empleados por cargo por dependencia")
    r.tabla(["Dependencia", "Cargo", "Cantidad"], [[d, c, len(l)] for (d, c), l in grupos_c.items()], "Resumen")
    for (dep, cargo), lista in grupos_c.items():
        r.tabla(["Código", "Nombre"], [[f["Codigo"], f["Nombre"]] for f in lista],
                f"{dep} / {cargo}  —  {len(lista)} empleado(s)")

    # d. Torta por dependencia
    r.titulo_seccion("d. Gráfico de torta: empleados por dependencia")
    r.grafico(grafico_torta(list(grupos.keys()), [len(l) for l in grupos.values()],
                            "Empleados por dependencia"))

    # e. Barras comparativas por dependencia por cargo
    r.titulo_seccion("e. Gráfico de barras: empleados por dependencia por cargo")
    cargos = sorted({c for (_, c) in grupos_c})
    r.grafico(grafico_barras_agrupadas(list(grupos.keys()), cargos,
                                       {k: len(v) for k, v in grupos_c.items()},
                                       "Empleados por dependencia y cargo", "Dependencia"))
    return r


# ==================================================================
# 2. REPORTE DE INFORMACIÓN PERSONAL
# ==================================================================
def reporte_informacion_personal(args):
    o = _orden(args)
    codigo = (args.get("empleado") or "").strip()
    filtro, params = "", []
    if codigo and codigo != "todos":
        filtro, params = "WHERE e.Codigo = %s", [codigo]
    empleados = consultar(
        f"""SELECT e.Codigo, e.Nombre, d.Nombre AS Dependencia, c.Nombre AS Cargo, e.Fecha_Ingreso,
                   eps.Nombre AS EPS, arl.Nombre AS ARL, p.Nombre AS Pension, e.Sueldo
            FROM Empleado e
            JOIN Dependencia d ON d.ID_Dependencia = e.ID_Dependencia
            JOIN Cargo c ON c.ID_Cargo = e.ID_Cargo
            JOIN EPS eps ON eps.ID_EPS = e.ID_EPS
            JOIN ARL arl ON arl.ID_ARL = e.ID_ARL
            JOIN Fondo_Pension p ON p.ID_Pension = e.ID_Pension
            {filtro} ORDER BY e.Nombre {o}""", params)
    r = Reporte("Reporte de Información Personal",
                ("Empleado: " + (empleados[0]["Nombre"] if filtro and empleados else "todos")) +
                f"  |  Orden: {_texto_orden(o)}")
    r.texto("Aporte a pensión: en Colombia la cotización es el 16% del salario; el empleado aporta el 4% "
            "y la empresa el 12%.")
    liquidaciones = defaultdict(list)
    for l in consultar(
            """SELECT l.Codigo_Empleado, l.Anio, l.Mes, l.Dias_Trabajados, l.Bonificacion, l.Transporte,
                      t.Nombre AS Tipo, n.Fecha_Inicio, n.Fecha_Fin, n.Numero_De_Dias
               FROM Liquidacion_Mes l
               LEFT JOIN Novedad n ON n.ID_Liquidacion = l.ID_Liquidacion
               LEFT JOIN Tipo_Novedad t ON t.ID_Tipo = n.ID_Tipo
               ORDER BY l.Anio, l.Mes, n.Fecha_Inicio"""):
        liquidaciones[l["Codigo_Empleado"]].append(l)

    for e in empleados:
        r.titulo_seccion(f"{e['Nombre']}  —  Código {e['Codigo']}")
        sueldo = float(e["Sueldo"])
        r.tabla(["Dato", "Valor"], [
            ["a. Nombre completo + Código personal", f"{e['Nombre']} ({e['Codigo']})"],
            ["b. Dependencia", e["Dependencia"]],
            ["c. Cargo", e["Cargo"]],
            ["d. Fecha de ingreso", _fecha(e["Fecha_Ingreso"])],
            ["e. EPS", e["EPS"]],
            ["   ARL", e["ARL"]],
            ["f. Fondo de pensión", e["Pension"]],
            ["   Aporte pensión empleado (4%)", _pesos(sueldo * 0.04)],
            ["   Aporte pensión empresa (12%)", _pesos(sueldo * 0.12)],
            ["g. Salario", _pesos(sueldo)],
        ])
        filas_nov, filas_liq, vistos = [], [], set()
        for l in liquidaciones.get(e["Codigo"], []):
            periodo = f"{l['Mes']:02d}/{l['Anio']}"
            if periodo not in vistos:
                vistos.add(periodo)
                filas_liq.append([periodo, l["Dias_Trabajados"], _pesos(l["Bonificacion"]),
                                  _pesos(l["Transporte"])])
            if l["Tipo"]:
                filas_nov.append([periodo, l["Tipo"], _fecha(l["Fecha_Inicio"]), _fecha(l["Fecha_Fin"]),
                                  l["Numero_De_Dias"]])
        r.tabla(["Periodo", "Días trabajados", "Bonificación", "Transporte"], filas_liq,
                "h. Liquidación del mes")
        if filas_nov:
            r.tabla(["Periodo", "Tipo de novedad", "Fecha inicio", "Fecha fin", "Días"], filas_nov,
                    "h. Discriminación de novedades")
        else:
            r.texto("h. Discriminación de novedades: el empleado no tiene novedades registradas.")
    if not empleados:
        r.texto("No se encontró el empleado.")
    return r


# ==================================================================
# 3. REPORTE DE SALUD Y PENSIÓN
# ==================================================================
def reporte_salud_pension(args):
    o = _orden(args)
    r = Reporte("Reporte de Salud y Pensión", f"Orden de nombres: {_texto_orden(o)}")
    filas = consultar(
        f"""SELECT e.Codigo, e.Nombre, d.Nombre AS Dependencia, c.Nombre AS Cargo,
                   eps.Nombre AS EPS, p.Nombre AS Pension
            FROM Empleado e
            JOIN Dependencia d ON d.ID_Dependencia = e.ID_Dependencia
            JOIN Cargo c ON c.ID_Cargo = e.ID_Cargo
            JOIN EPS eps ON eps.ID_EPS = e.ID_EPS
            JOIN Fondo_Pension p ON p.ID_Pension = e.ID_Pension
            ORDER BY e.Nombre {o}""")
    dependencias = sorted({f["Dependencia"] for f in filas})

    for letra, campo, nombre in (("a", "EPS", "EPS"), ("b", "Pension", "fondo de pensión")):
        conteo = defaultdict(int)
        for f in filas:
            conteo[f[campo]] += 1
        etiquetas = sorted(conteo)
        r.titulo_seccion(f"{letra}. Frecuencia por {nombre} (toda la empresa)")
        r.tabla([nombre.capitalize(), "Cantidad"], [[e, conteo[e]] for e in etiquetas])
        r.grafico(grafico_barras(etiquetas, [conteo[e] for e in etiquetas],
                                 f"Empleados por {nombre}", nombre.capitalize()))

    for letra, campo, nombre in (("c", "EPS", "EPS"), ("d", "Pension", "fondo de pensión")):
        conteo = defaultdict(int)
        for f in filas:
            conteo[(f["Dependencia"], f[campo])] += 1
        series = sorted({f[campo] for f in filas})
        r.titulo_seccion(f"{letra}. Barras comparativas por {nombre} por dependencia")
        r.grafico(grafico_barras_agrupadas(dependencias, series, conteo,
                                           f"Empleados por {nombre} y dependencia", "Dependencia"))
        r.tabla(["Dependencia"] + series, [[d] + [conteo.get((d, s), 0) for s in series] for d in dependencias])

    for letra, campo, nombre in (("e", "EPS", "EPS"), ("f", "Pension", "pensión")):
        grupos = OrderedDict()
        # orden: cargo ASC, EPS/pensión ASC, nombre según el usuario (ya viene ordenado por nombre)
        for f in sorted(filas, key=lambda x: (x["Cargo"], x[campo])):
            grupos.setdefault((f["Cargo"], f[campo]), []).append(f)
        r.titulo_seccion(f"{letra}. Empleados por cargo y por {nombre}")
        r.tabla(["Cargo", nombre.capitalize(), "Cantidad"], [[c, e, len(l)] for (c, e), l in grupos.items()],
                "Resumen")
        for (cargo, valor), lista in grupos.items():
            r.tabla(["Código", "Nombre", "Dependencia"],
                    [[f["Codigo"], f["Nombre"], f["Dependencia"]] for f in lista],
                    f"{cargo} / {valor}  —  {len(lista)} empleado(s)")
    return r


# ==================================================================
# 4. REPORTE DE NOVEDADES
# ==================================================================
def reporte_novedades(args):
    o = _orden(args)
    a1, m1 = _mes_anio(args.get("f1"), (2022, 1))
    a2, m2 = _mes_anio(args.get("f2"), (2022, 12))
    if (a2, m2) < (a1, m1):
        a1, m1, a2, m2 = a2, m2, a1, m1
    desde = datetime.date(a1, m1, 1)
    hasta = datetime.date(a2, m2, calendar.monthrange(a2, m2)[1])
    r = Reporte("Reporte de Novedades",
                f"Rango: {m1:02d}/{a1} a {m2:02d}/{a2}  |  Orden de nombres: {_texto_orden(o)}")
    # Una novedad entra al rango si se cruza con él (empieza antes del fin y termina después del inicio)
    filas = consultar(
        f"""SELECT e.Codigo, e.Nombre, d.Nombre AS Dependencia, c.Nombre AS Cargo,
                   t.Nombre AS Tipo, n.Fecha_Inicio, n.Fecha_Fin, n.Numero_De_Dias
            FROM Novedad n
            JOIN Tipo_Novedad t ON t.ID_Tipo = n.ID_Tipo
            JOIN Liquidacion_Mes l ON l.ID_Liquidacion = n.ID_Liquidacion
            JOIN Empleado e ON e.Codigo = l.Codigo_Empleado
            JOIN Dependencia d ON d.ID_Dependencia = e.ID_Dependencia
            JOIN Cargo c ON c.ID_Cargo = e.ID_Cargo
            WHERE n.Fecha_Inicio <= %s AND n.Fecha_Fin >= %s
            ORDER BY e.Nombre {o}, n.Fecha_Inicio""", (hasta, desde))
    empleados = OrderedDict()
    for f in filas:
        empleados.setdefault(f["Codigo"], f)

    r.titulo_seccion(f"a. Empleados con novedades en el rango  (cantidad: {len(empleados)})")
    r.tabla(["Código", "Nombre", "Dependencia", "Cargo", "Novedad", "Inicio", "Fin", "Días"],
            [[f["Codigo"], f["Nombre"], f["Dependencia"], f["Cargo"], f["Tipo"],
              _fecha(f["Fecha_Inicio"]), _fecha(f["Fecha_Fin"]), f["Numero_De_Dias"]] for f in filas])

    r.titulo_seccion("b. Cantidad de empleados con novedades por dependencia y por cargo")
    por_dep, por_dep_cargo = defaultdict(int), defaultdict(int)
    for e in empleados.values():
        por_dep[e["Dependencia"]] += 1
        por_dep_cargo[(e["Dependencia"], e["Cargo"])] += 1
    r.tabla(["Dependencia", "Cantidad de empleados"], [[d, por_dep[d]] for d in sorted(por_dep)],
            "Por dependencia")
    r.tabla(["Dependencia", "Cargo", "Cantidad de empleados"],
            [[d, c, n] for (d, c), n in sorted(por_dep_cargo.items())], "Por dependencia y cargo")
    if por_dep:
        r.grafico(grafico_barras(sorted(por_dep), [por_dep[d] for d in sorted(por_dep)],
                                 "Empleados con novedades por dependencia", "Dependencia"))
    return r


# ==================================================================
# 5. REPORTE BASE-ENTRETENIMIENTO
# ==================================================================
SECCIONES_ENTRETENIMIENTO = OrderedDict([
    ("a", "a. Películas por género entre dos años"),
    ("b", "b. Top N libros con mejor rating"),
    ("c", "c. Top 5 mejores y peores libros por año"),
    ("d", "d. Películas con N géneros"),
    ("e", "e. Gráfico de películas por género"),
    ("f", "f. Gráfico de libros por año de publicación"),
])


def reporte_entretenimiento(args):
    o = _orden(args)
    elegidas = [s for s in SECCIONES_ENTRETENIMIENTO if args.get("sec_" + s)] or list(SECCIONES_ENTRETENIMIENTO)
    r = Reporte("Reporte Base-Entretenimiento", f"Orden de nombres: {_texto_orden(o)}")

    if "a" in elegidas:
        y1 = _entero(args, "peli_desde", 1995, 1800, 2100)
        y2 = _entero(args, "peli_hasta", 1995, 1800, 2100)
        y1, y2 = min(y1, y2), max(y1, y2)
        genero = (args.get("genero") or "todos").strip()
        filtro, params = "", [y1, y2]
        if genero != "todos":
            filtro, params = "AND g.ID_Genero = %s", [y1, y2, genero]
        filas = consultar(
            f"""SELECT g.Nombre AS Genero, p.ID_Pelicula, p.Titulo, p.Anio
                FROM Pelicula p
                JOIN Pelicula_Genero pg ON pg.ID_Pelicula = p.ID_Pelicula
                JOIN Genero g ON g.ID_Genero = pg.ID_Genero
                WHERE p.Anio BETWEEN %s AND %s {filtro}
                ORDER BY g.Nombre ASC, p.Titulo {o}""", params)
        r.titulo_seccion(f"a. Películas por género entre {y1} y {y2}")
        grupos = OrderedDict()
        for f in filas:
            grupos.setdefault(f["Genero"], []).append(f)
        r.tabla(["Género", "Cantidad"], [[g, len(l)] for g, l in grupos.items()], "Resumen por género")
        for g, lista in grupos.items():
            r.tabla(["ID", "Título", "Año"], [[f["ID_Pelicula"], f["Titulo"], f["Anio"]] for f in lista],
                    f"{g}  —  {len(lista)} película(s)")
        if not filas:
            r.texto("No hay películas en ese rango.")

    if "b" in elegidas:
        n = _entero(args, "top_n", 10, 1, 1000)
        min_ratings = _entero(args, "min_ratings", 0, 0)
        filas = consultar(
            f"""SELECT * FROM (
                    SELECT l.ID_Libro, l.Titulo, l.Rating_Promedio, l.Cantidad_Ratings,
                           YEAR(l.Fecha_Publicacion) AS Anio
                    FROM Libro l
                    WHERE l.Cantidad_Ratings >= %s
                    ORDER BY l.Rating_Promedio DESC, l.Cantidad_Ratings DESC
                    LIMIT %s) top
                ORDER BY top.Titulo {o}""", (min_ratings, n))
        r.titulo_seccion(f"b. Top {n} libros con mejor rating")
        if min_ratings:
            r.texto(f"Solo se tienen en cuenta libros con al menos {min_ratings} calificaciones.")
        r.texto("Se escogen los N libros con mayor rating (en empate gana el que tenga más calificaciones) "
                "y luego se muestran ordenados por título.")
        r.tabla(["ID", "Título", "Rating", "N° ratings", "Año"],
                [[f["ID_Libro"], f["Titulo"], f["Rating_Promedio"], f["Cantidad_Ratings"], f["Anio"]]
                 for f in filas])

    if "c" in elegidas:
        y1 = _entero(args, "top5_desde", 2000, 1800, 2100)
        y2 = _entero(args, "top5_hasta", 2005, 1800, 2100)
        y1, y2 = min(y1, y2), max(y1, y2)
        r.titulo_seccion(f"c. Top 5 mejores y peores libros por año ({y1} - {y2})")
        r.texto("Para los peores se excluyen libros sin calificaciones (rating 0 con 0 ratings).")
        for tipo, orden_rating, cond in (("Mejor", "DESC", ""), ("Peor", "ASC", "AND Cantidad_Ratings > 0")):
            filas = consultar(
                f"""SELECT Anio, Titulo, Rating_Promedio, Puesto FROM (
                        SELECT YEAR(Fecha_Publicacion) AS Anio, Titulo, Rating_Promedio,
                               ROW_NUMBER() OVER (PARTITION BY YEAR(Fecha_Publicacion)
                                                  ORDER BY Rating_Promedio {orden_rating}, Cantidad_Ratings DESC) AS Puesto
                        FROM Libro
                        WHERE YEAR(Fecha_Publicacion) BETWEEN %s AND %s {cond}) x
                    WHERE Puesto <= 5
                    ORDER BY Anio ASC, Titulo {o}""", (y1, y2))
            r.tabla(["Año", "Título", "Rating", "Puesto"],
                    [[f["Anio"], f["Titulo"], f["Rating_Promedio"], f["Puesto"]] for f in filas],
                    f"Top 5 {tipo.lower()} rating por año")

    if "d" in elegidas:
        n = _entero(args, "n_generos", 3, 0, 20)
        filas = consultar(
            f"""SELECT p.ID_Pelicula, p.Titulo, p.Anio, COUNT(pg.ID_Genero) AS Cantidad,
                       GROUP_CONCAT(g.Nombre ORDER BY g.Nombre SEPARATOR ', ') AS Generos
                FROM Pelicula p
                LEFT JOIN Pelicula_Genero pg ON pg.ID_Pelicula = p.ID_Pelicula
                LEFT JOIN Genero g ON g.ID_Genero = pg.ID_Genero
                GROUP BY p.ID_Pelicula, p.Titulo, p.Anio
                HAVING COUNT(pg.ID_Genero) = %s
                ORDER BY p.Titulo {o}""", (n,))
        r.titulo_seccion(f"d. Películas con exactamente {n} género(s)  (cantidad: {len(filas)})")
        r.tabla(["ID", "Título", "Año", "Géneros"],
                [[f["ID_Pelicula"], f["Titulo"], f["Anio"], f["Generos"] or "(sin género)"] for f in filas])

    if "e" in elegidas:
        filas = consultar(
            """SELECT g.Nombre, COUNT(*) AS Cantidad
               FROM Genero g JOIN Pelicula_Genero pg ON pg.ID_Genero = g.ID_Genero
               GROUP BY g.Nombre ORDER BY Cantidad DESC""")
        r.titulo_seccion("e. Frecuencia de películas por género")
        r.grafico(grafico_barras([f["Nombre"] for f in filas], [f["Cantidad"] for f in filas],
                                 "Películas por género", horizontal=True, eje_y="Cantidad de películas"))
        r.tabla(["Género", "Cantidad"], [[f["Nombre"], f["Cantidad"]] for f in filas])

    if "f" in elegidas:
        y1 = _entero(args, "libros_desde", 1990, 1800, 2100)
        y2 = _entero(args, "libros_hasta", 2010, 1800, 2100)
        y1, y2 = min(y1, y2), max(y1, y2)
        filas = consultar(
            """SELECT YEAR(Fecha_Publicacion) AS Anio, COUNT(*) AS Cantidad
               FROM Libro WHERE YEAR(Fecha_Publicacion) BETWEEN %s AND %s
               GROUP BY YEAR(Fecha_Publicacion) ORDER BY Anio""", (y1, y2))
        r.titulo_seccion(f"f. Frecuencia de libros por año de publicación ({y1} - {y2})")
        r.grafico(grafico_barras([str(f["Anio"]) for f in filas], [f["Cantidad"] for f in filas],
                                 f"Libros publicados por año ({y1}-{y2})", "Año"))
        r.tabla(["Año", "Cantidad"], [[f["Anio"], f["Cantidad"]] for f in filas])
    return r


# ------------------------------------------------------------------
REPORTES = OrderedDict([
    ("nomina", {"nombre": "1. Nómina", "funcion": reporte_nomina,
                "descripcion": "Empleados en total, por dependencia y por cargo, con gráficos."}),
    ("personal", {"nombre": "2. Información personal", "funcion": reporte_informacion_personal,
                  "descripcion": "Datos de cada empleado con salario, EPS, pensión y novedades."}),
    ("salud", {"nombre": "3. Salud y pensión", "funcion": reporte_salud_pension,
               "descripcion": "Frecuencias por EPS y fondo de pensión, por dependencia y por cargo."}),
    ("novedades", {"nombre": "4. Novedades", "funcion": reporte_novedades,
                   "descripcion": "Empleados con incapacidades o vacaciones entre dos meses."}),
    ("entretenimiento", {"nombre": "5. Base-Entretenimiento", "funcion": reporte_entretenimiento,
                         "descripcion": "Consultas de películas y libros con gráficos."}),
])
