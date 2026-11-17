"""Definición de las tablas que se pueden administrar (CRUD) desde la aplicación.

Cada entidad dice qué tabla usa, cuál es su llave, qué campos tiene el formulario
y qué consulta se usa para el listado. Con esto una sola parte del código
(crud en app.py) sirve para crear, leer, actualizar y eliminar en todas las tablas.

Tipos de campo: texto, entero, decimal, fecha, fk (lista desplegable a otra tabla),
multi_genero (varios géneros de una película), autores (autores de un libro separados por '/').
"""
from collections import OrderedDict


def _catalogo(tabla, llave, titulo, singular, col="Nombre", largo=80, uso=None):
    return {
        "tabla": tabla, "llave": llave, "llave_manual": False, "titulo": titulo, "singular": singular,
        "grupo": "Catálogos",
        "campos": [{"nombre": col, "etiqueta": col.replace("_", " "), "tipo": "texto", "requerido": True,
                    "max": largo}],
        "lista_sql": (f"SELECT t.{llave} AS id, t.{col}" +
                      (f", (SELECT COUNT(*) FROM {uso[0]} u WHERE u.{uso[1]} = t.{llave}) AS Usos" if uso else "") +
                      f" FROM {tabla} t"),
        "columnas": [(col, col.replace("_", " "))] + ([("Usos", "Registros que lo usan")] if uso else []),
        "buscar": [f"t.{col}"], "orden": f"t.{col}",
    }


ENTIDADES = OrderedDict()

# ---------------- Nómina ----------------
ENTIDADES["empleados"] = {
    "tabla": "Empleado", "llave": "Codigo", "llave_manual": True, "titulo": "Empleados",
    "singular": "empleado", "grupo": "Nómina",
    "campos": [
        {"nombre": "Codigo", "etiqueta": "Código", "tipo": "entero", "requerido": True},
        {"nombre": "Nombre", "etiqueta": "Nombre completo", "tipo": "texto", "requerido": True, "max": 100},
        {"nombre": "Fecha_Ingreso", "etiqueta": "Fecha de ingreso", "tipo": "fecha", "requerido": True},
        {"nombre": "Sueldo", "etiqueta": "Sueldo", "tipo": "decimal", "requerido": True, "min": 0},
        {"nombre": "ID_Dependencia", "etiqueta": "Dependencia", "tipo": "fk",
         "opciones": "SELECT ID_Dependencia AS id, Nombre AS texto FROM Dependencia ORDER BY Nombre", "requerido": True},
        {"nombre": "ID_Cargo", "etiqueta": "Cargo", "tipo": "fk",
         "opciones": "SELECT ID_Cargo AS id, Nombre AS texto FROM Cargo ORDER BY Nombre", "requerido": True},
        {"nombre": "ID_EPS", "etiqueta": "EPS", "tipo": "fk",
         "opciones": "SELECT ID_EPS AS id, Nombre AS texto FROM EPS ORDER BY Nombre", "requerido": True},
        {"nombre": "ID_ARL", "etiqueta": "ARL", "tipo": "fk",
         "opciones": "SELECT ID_ARL AS id, Nombre AS texto FROM ARL ORDER BY Nombre", "requerido": True},
        {"nombre": "ID_Pension", "etiqueta": "Fondo de pensión", "tipo": "fk",
         "opciones": "SELECT ID_Pension AS id, Nombre AS texto FROM Fondo_Pension ORDER BY Nombre", "requerido": True},
    ],
    "lista_sql": """SELECT e.Codigo AS id, e.Codigo, e.Nombre, d.Nombre AS Dependencia, c.Nombre AS Cargo,
                           DATE_FORMAT(e.Fecha_Ingreso, '%%d/%%m/%%Y') AS Ingreso, eps.Nombre AS EPS,
                           p.Nombre AS Pension, e.Sueldo
                    FROM Empleado e
                    JOIN Dependencia d ON d.ID_Dependencia = e.ID_Dependencia
                    JOIN Cargo c ON c.ID_Cargo = e.ID_Cargo
                    JOIN EPS eps ON eps.ID_EPS = e.ID_EPS
                    JOIN Fondo_Pension p ON p.ID_Pension = e.ID_Pension""",
    "columnas": [("Codigo", "Código"), ("Nombre", "Nombre"), ("Dependencia", "Dependencia"), ("Cargo", "Cargo"),
                 ("Ingreso", "Ingreso"), ("EPS", "EPS"), ("Pension", "Pensión"), ("Sueldo", "Sueldo")],
    "buscar": ["e.Nombre", "CAST(e.Codigo AS CHAR)", "d.Nombre", "c.Nombre"], "orden": "e.Nombre",
}

ENTIDADES["liquidaciones"] = {
    "tabla": "Liquidacion_Mes", "llave": "ID_Liquidacion", "llave_manual": False,
    "titulo": "Liquidaciones mensuales", "singular": "liquidación", "grupo": "Nómina",
    "campos": [
        {"nombre": "Codigo_Empleado", "etiqueta": "Empleado", "tipo": "fk", "requerido": True,
         "opciones": "SELECT Codigo AS id, CONCAT(Codigo, ' - ', Nombre) AS texto FROM Empleado ORDER BY Nombre"},
        {"nombre": "Anio", "etiqueta": "Año", "tipo": "entero", "requerido": True, "min": 1900, "max_valor": 2100},
        {"nombre": "Mes", "etiqueta": "Mes", "tipo": "entero", "requerido": True, "min": 1, "max_valor": 12},
        {"nombre": "Dias_Trabajados", "etiqueta": "Días trabajados", "tipo": "entero", "requerido": True,
         "min": 0, "max_valor": 31},
        {"nombre": "Bonificacion", "etiqueta": "Bonificación", "tipo": "decimal", "requerido": True, "min": 0},
        {"nombre": "Transporte", "etiqueta": "Transporte", "tipo": "decimal", "requerido": True, "min": 0},
    ],
    "lista_sql": """SELECT l.ID_Liquidacion AS id, l.ID_Liquidacion, e.Nombre AS Empleado,
                           CONCAT(LPAD(l.Mes, 2, '0'), '/', l.Anio) AS Periodo, l.Dias_Trabajados,
                           l.Bonificacion, l.Transporte,
                           (SELECT COUNT(*) FROM Novedad n WHERE n.ID_Liquidacion = l.ID_Liquidacion) AS Novedades
                    FROM Liquidacion_Mes l JOIN Empleado e ON e.Codigo = l.Codigo_Empleado""",
    "columnas": [("ID_Liquidacion", "ID"), ("Empleado", "Empleado"), ("Periodo", "Periodo"),
                 ("Dias_Trabajados", "Días trab."), ("Bonificacion", "Bonificación"),
                 ("Transporte", "Transporte"), ("Novedades", "Novedades")],
    "buscar": ["e.Nombre", "CAST(e.Codigo AS CHAR)"], "orden": "l.Anio DESC, l.Mes DESC, e.Nombre",
}

ENTIDADES["novedades"] = {
    "tabla": "Novedad", "llave": "ID_Novedad", "llave_manual": False, "titulo": "Novedades",
    "singular": "novedad", "grupo": "Nómina",
    "campos": [
        {"nombre": "ID_Liquidacion", "etiqueta": "Liquidación (empleado y periodo)", "tipo": "fk", "requerido": True,
         "opciones": """SELECT l.ID_Liquidacion AS id,
                               CONCAT(e.Nombre, ' - ', LPAD(l.Mes, 2, '0'), '/', l.Anio) AS texto
                        FROM Liquidacion_Mes l JOIN Empleado e ON e.Codigo = l.Codigo_Empleado
                        ORDER BY e.Nombre, l.Anio, l.Mes"""},
        {"nombre": "ID_Tipo", "etiqueta": "Tipo de novedad", "tipo": "fk", "requerido": True,
         "opciones": "SELECT ID_Tipo AS id, Nombre AS texto FROM Tipo_Novedad ORDER BY Nombre"},
        {"nombre": "Fecha_Inicio", "etiqueta": "Fecha inicio", "tipo": "fecha", "requerido": True},
        {"nombre": "Fecha_Fin", "etiqueta": "Fecha fin", "tipo": "fecha", "requerido": True},
        {"nombre": "Numero_De_Dias", "etiqueta": "Número de días", "tipo": "entero", "requerido": True, "min": 0},
    ],
    "lista_sql": """SELECT n.ID_Novedad AS id, n.ID_Novedad, e.Nombre AS Empleado, t.Nombre AS Tipo,
                           DATE_FORMAT(n.Fecha_Inicio, '%%d/%%m/%%Y') AS Inicio,
                           DATE_FORMAT(n.Fecha_Fin, '%%d/%%m/%%Y') AS Fin, n.Numero_De_Dias
                    FROM Novedad n
                    JOIN Tipo_Novedad t ON t.ID_Tipo = n.ID_Tipo
                    JOIN Liquidacion_Mes l ON l.ID_Liquidacion = n.ID_Liquidacion
                    JOIN Empleado e ON e.Codigo = l.Codigo_Empleado""",
    "columnas": [("ID_Novedad", "ID"), ("Empleado", "Empleado"), ("Tipo", "Tipo"), ("Inicio", "Inicio"),
                 ("Fin", "Fin"), ("Numero_De_Dias", "Días")],
    "buscar": ["e.Nombre", "t.Nombre"], "orden": "n.Fecha_Inicio DESC",
    "validar": "fechas_novedad",
}

ENTIDADES["dependencias"] = _catalogo("Dependencia", "ID_Dependencia", "Dependencias", "dependencia",
                                      uso=("Empleado", "ID_Dependencia"))
ENTIDADES["dependencias"]["grupo"] = "Nómina"
ENTIDADES["cargos"] = _catalogo("Cargo", "ID_Cargo", "Cargos", "cargo", uso=("Empleado", "ID_Cargo"))
ENTIDADES["cargos"]["grupo"] = "Nómina"
ENTIDADES["eps"] = _catalogo("EPS", "ID_EPS", "EPS", "EPS", uso=("Empleado", "ID_EPS"))
ENTIDADES["arl"] = _catalogo("ARL", "ID_ARL", "ARL", "ARL", uso=("Empleado", "ID_ARL"))
ENTIDADES["pensiones"] = _catalogo("Fondo_Pension", "ID_Pension", "Fondos de pensión", "fondo de pensión",
                                   uso=("Empleado", "ID_Pension"))
ENTIDADES["tipos_novedad"] = _catalogo("Tipo_Novedad", "ID_Tipo", "Tipos de novedad", "tipo de novedad",
                                       largo=60, uso=("Novedad", "ID_Tipo"))

# ---------------- Películas ----------------
ENTIDADES["peliculas"] = {
    "tabla": "Pelicula", "llave": "ID_Pelicula", "llave_manual": True, "titulo": "Películas",
    "singular": "película", "grupo": "Entretenimiento",
    "campos": [
        {"nombre": "ID_Pelicula", "etiqueta": "ID", "tipo": "entero", "requerido": True},
        {"nombre": "Titulo", "etiqueta": "Título", "tipo": "texto", "requerido": True, "max": 255},
        {"nombre": "Anio", "etiqueta": "Año", "tipo": "entero", "requerido": False, "min": 1800, "max_valor": 2100},
        {"nombre": "_generos", "etiqueta": "Géneros", "tipo": "multi_genero", "requerido": False},
    ],
    "lista_sql": """SELECT p.ID_Pelicula AS id, p.ID_Pelicula, p.Titulo, p.Anio,
                           (SELECT GROUP_CONCAT(g.Nombre ORDER BY g.Nombre SEPARATOR ', ')
                            FROM Pelicula_Genero pg JOIN Genero g ON g.ID_Genero = pg.ID_Genero
                            WHERE pg.ID_Pelicula = p.ID_Pelicula) AS Generos
                    FROM Pelicula p""",
    "columnas": [("ID_Pelicula", "ID"), ("Titulo", "Título"), ("Anio", "Año"), ("Generos", "Géneros")],
    "buscar": ["p.Titulo", "CAST(p.ID_Pelicula AS CHAR)", "CAST(p.Anio AS CHAR)"], "orden": "p.Titulo",
}
ENTIDADES["generos"] = _catalogo("Genero", "ID_Genero", "Géneros", "género", largo=50,
                                 uso=("Pelicula_Genero", "ID_Genero"))
ENTIDADES["generos"]["grupo"] = "Entretenimiento"

# ---------------- Libros ----------------
ENTIDADES["libros"] = {
    "tabla": "Libro", "llave": "ID_Libro", "llave_manual": True, "titulo": "Libros", "singular": "libro",
    "grupo": "Entretenimiento",
    "campos": [
        {"nombre": "ID_Libro", "etiqueta": "ID", "tipo": "entero", "requerido": True},
        {"nombre": "Titulo", "etiqueta": "Título", "tipo": "texto", "requerido": True, "max": 500},
        {"nombre": "_autores", "etiqueta": "Autores (separados por /)", "tipo": "autores", "requerido": True},
        {"nombre": "ISBN", "etiqueta": "ISBN", "tipo": "texto", "requerido": False, "max": 10},
        {"nombre": "ISBN13", "etiqueta": "ISBN13", "tipo": "texto", "requerido": False, "max": 13},
        {"nombre": "Numero_Paginas", "etiqueta": "Número de páginas", "tipo": "entero", "requerido": False, "min": 0},
        {"nombre": "Fecha_Publicacion", "etiqueta": "Fecha de publicación", "tipo": "fecha", "requerido": False},
        {"nombre": "Rating_Promedio", "etiqueta": "Rating promedio (0 a 5)", "tipo": "decimal", "requerido": False,
         "min": 0, "max_valor": 5},
        {"nombre": "Cantidad_Ratings", "etiqueta": "Cantidad de ratings", "tipo": "entero", "requerido": True, "min": 0},
        {"nombre": "Cantidad_Resenas", "etiqueta": "Cantidad de reseñas", "tipo": "entero", "requerido": True, "min": 0},
        {"nombre": "ID_Editorial", "etiqueta": "Editorial", "tipo": "fk", "requerido": False,
         "opciones": "SELECT ID_Editorial AS id, Nombre AS texto FROM Editorial ORDER BY Nombre"},
        {"nombre": "ID_Idioma", "etiqueta": "Idioma", "tipo": "fk", "requerido": False,
         "opciones": "SELECT ID_Idioma AS id, Codigo AS texto FROM Idioma ORDER BY Codigo"},
    ],
    "lista_sql": """SELECT l.ID_Libro AS id, l.ID_Libro, l.Titulo,
                           (SELECT GROUP_CONCAT(a.Nombre ORDER BY la.Orden_Autor SEPARATOR ' / ')
                            FROM Libro_Autor la JOIN Autor a ON a.ID_Autor = la.ID_Autor
                            WHERE la.ID_Libro = l.ID_Libro) AS Autores,
                           l.Rating_Promedio, DATE_FORMAT(l.Fecha_Publicacion, '%%d/%%m/%%Y') AS Publicacion,
                           ed.Nombre AS Editorial, i.Codigo AS Idioma
                    FROM Libro l
                    LEFT JOIN Editorial ed ON ed.ID_Editorial = l.ID_Editorial
                    LEFT JOIN Idioma i ON i.ID_Idioma = l.ID_Idioma""",
    "columnas": [("ID_Libro", "ID"), ("Titulo", "Título"), ("Autores", "Autores"), ("Rating_Promedio", "Rating"),
                 ("Publicacion", "Publicación"), ("Editorial", "Editorial"), ("Idioma", "Idioma")],
    "buscar": ["l.Titulo", "CAST(l.ID_Libro AS CHAR)", "l.ISBN", "l.ISBN13"], "orden": "l.Titulo",
}
ENTIDADES["autores"] = _catalogo("Autor", "ID_Autor", "Autores", "autor", largo=255, uso=("Libro_Autor", "ID_Autor"))
ENTIDADES["autores"]["grupo"] = "Entretenimiento"
ENTIDADES["editoriales"] = _catalogo("Editorial", "ID_Editorial", "Editoriales", "editorial", largo=255,
                                     uso=("Libro", "ID_Editorial"))
ENTIDADES["editoriales"]["grupo"] = "Entretenimiento"
ENTIDADES["idiomas"] = _catalogo("Idioma", "ID_Idioma", "Idiomas", "idioma", col="Codigo", largo=10,
                                 uso=("Libro", "ID_Idioma"))
ENTIDADES["idiomas"]["grupo"] = "Entretenimiento"

# Tablas que se pueden usar en el constructor de consultas dinámicas
TABLAS_CONSULTA = ["Empleado", "Dependencia", "Cargo", "EPS", "ARL", "Fondo_Pension", "Liquidacion_Mes",
                   "Novedad", "Tipo_Novedad", "Pelicula", "Genero", "Pelicula_Genero", "Libro", "Autor",
                   "Libro_Autor", "Editorial", "Idioma", "Carga_Archivo", "Auditoria"]
