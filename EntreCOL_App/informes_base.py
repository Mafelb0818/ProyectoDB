"""Estructura común de los reportes y generación de gráficos y PDF.

Un reporte es una lista de secciones (títulos, textos, tablas y gráficos).
La misma estructura se usa para mostrarlo en la página (HTML) y para
generar el PDF, así los dos siempre muestran lo mismo.
"""
import base64
import datetime
import io
import os

import matplotlib

matplotlib.use("Agg")  # sin ventana, solo imágenes
import matplotlib.pyplot as plt  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4, landscape  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import cm  # noqa: E402
from reportlab.pdfbase import pdfmetrics  # noqa: E402
from reportlab.pdfbase.ttfonts import TTFont  # noqa: E402
from reportlab.platypus import (Image, LongTable, PageBreak, Paragraph,  # noqa: E402
                                SimpleDocTemplate, Spacer, TableStyle)

CARPETA_FUENTES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "fonts")
LIMITE_FILAS_HTML = 1000
LIMITE_FILAS_PDF = 5000

COLORES = ["#2563eb", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6", "#06b6d4", "#ec4899",
           "#84cc16", "#f97316", "#64748b", "#14b8a6", "#a855f7", "#eab308", "#0ea5e9",
           "#d946ef", "#22c55e", "#fb7185", "#78716c", "#4f46e5", "#0d9488"]


# ------------------------------------------------------------------
# Estructura del reporte
# ------------------------------------------------------------------
class Reporte:
    def __init__(self, titulo, parametros=""):
        self.titulo = titulo
        self.parametros = parametros
        self.secciones = []

    def titulo_seccion(self, texto):
        self.secciones.append({"tipo": "titulo", "texto": texto})

    def texto(self, texto):
        self.secciones.append({"tipo": "texto", "texto": texto})

    def tabla(self, columnas, filas, titulo=None):
        """filas: lista de listas (ya formateadas como texto o número)."""
        self.secciones.append({"tipo": "tabla", "titulo": titulo, "columnas": columnas, "filas": filas})

    def grafico(self, png, titulo=None):
        self.secciones.append({"tipo": "grafico", "titulo": titulo, "png": png,
                               "b64": base64.b64encode(png).decode("ascii")})

    def salto(self):
        self.secciones.append({"tipo": "salto"})


# ------------------------------------------------------------------
# Gráficos (matplotlib -> PNG)
# ------------------------------------------------------------------
def _png(fig):
    salida = io.BytesIO()
    fig.savefig(salida, format="png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    return salida.getvalue()


def grafico_torta(etiquetas, valores, titulo):
    fig, ax = plt.subplots(figsize=(7, 4.6))
    if not valores or sum(valores) == 0:
        ax.text(0.5, 0.5, "Sin datos", ha="center", va="center")
        ax.axis("off")
    else:
        ax.pie(valores, labels=[f"{e} ({v})" for e, v in zip(etiquetas, valores)],
               autopct="%1.1f%%", startangle=90, colors=COLORES[: len(valores)],
               wedgeprops={"edgecolor": "white", "linewidth": 1.5}, textprops={"fontsize": 9})
        ax.axis("equal")
    ax.set_title(titulo, fontsize=12, fontweight="bold")
    return _png(fig)


def grafico_barras(etiquetas, valores, titulo, eje_x="", eje_y="Cantidad", horizontal=False):
    alto = max(4.2, 0.32 * len(etiquetas)) if horizontal else 4.6
    fig, ax = plt.subplots(figsize=(9, alto))
    if not valores:
        ax.text(0.5, 0.5, "Sin datos", ha="center", va="center")
        ax.axis("off")
    elif horizontal:
        barras = ax.barh(etiquetas, valores, color=COLORES[0])
        ax.invert_yaxis()
        ax.set_xlabel(eje_y)
        ax.bar_label(barras, padding=3, fontsize=8)
    else:
        barras = ax.bar(etiquetas, valores, color=COLORES[0])
        ax.set_xlabel(eje_x)
        ax.set_ylabel(eje_y)
        ax.bar_label(barras, padding=2, fontsize=8)
        if len(etiquetas) > 6:
            plt.setp(ax.get_xticklabels(), rotation=45, ha="right", fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_title(titulo, fontsize=12, fontweight="bold")
    return _png(fig)


def grafico_barras_agrupadas(grupos, series, datos, titulo, eje_x="", eje_y="Cantidad"):
    """grupos: categorías del eje X; series: una barra por serie dentro de cada grupo;
    datos[(grupo, serie)] = cantidad."""
    fig, ax = plt.subplots(figsize=(10, 5))
    if not grupos or not series:
        ax.text(0.5, 0.5, "Sin datos", ha="center", va="center")
        ax.axis("off")
    else:
        n = len(series)
        ancho = 0.8 / n
        for i, s in enumerate(series):
            xs = [g + (i - (n - 1) / 2) * ancho for g in range(len(grupos))]
            ys = [datos.get((gr, s), 0) for gr in grupos]
            barras = ax.bar(xs, ys, width=ancho, label=s, color=COLORES[i % len(COLORES)])
            ax.bar_label(barras, labels=[str(y) if y else "" for y in ys], padding=1, fontsize=7)
        ax.set_xticks(range(len(grupos)))
        ax.set_xticklabels(grupos)
        ax.set_xlabel(eje_x)
        ax.set_ylabel(eje_y)
        ax.yaxis.get_major_locator().set_params(integer=True)
        ax.legend(fontsize=8, bbox_to_anchor=(1.01, 1), loc="upper left", frameon=False)
        ax.spines[["top", "right"]].set_visible(False)
    ax.set_title(titulo, fontsize=12, fontweight="bold")
    return _png(fig)


# ------------------------------------------------------------------
# PDF (ReportLab)
# ------------------------------------------------------------------
_FUENTES_LISTAS = False


def _registrar_fuentes():
    """Usa DejaVu Sans para que salgan bien tildes, ñ y otros caracteres."""
    global _FUENTES_LISTAS
    if _FUENTES_LISTAS:
        return "DejaVu", "DejaVu-Bold"
    try:
        pdfmetrics.registerFont(TTFont("DejaVu", os.path.join(CARPETA_FUENTES, "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("DejaVu-Bold", os.path.join(CARPETA_FUENTES, "DejaVuSans-Bold.ttf")))
        _FUENTES_LISTAS = True
        return "DejaVu", "DejaVu-Bold"
    except Exception:
        return "Helvetica", "Helvetica-Bold"


def _esc(valor):
    texto = "" if valor is None else str(valor)
    return texto.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def generar_pdf(reporte, usuario=""):
    normal, negrita = _registrar_fuentes()
    estilos = getSampleStyleSheet()
    est_titulo = ParagraphStyle("t", parent=estilos["Title"], fontName=negrita, fontSize=17,
                                textColor=colors.HexColor("#1e3a8a"))
    est_sub = ParagraphStyle("s", parent=estilos["Heading2"], fontName=negrita, fontSize=12.5,
                             textColor=colors.HexColor("#1e3a8a"), spaceBefore=10, keepWithNext=1)
    est_texto = ParagraphStyle("n", parent=estilos["Normal"], fontName=normal, fontSize=9.5, leading=13)
    est_celda = ParagraphStyle("c", parent=est_texto, fontSize=8, leading=10)
    est_cab = ParagraphStyle("h", parent=est_celda, fontName=negrita, textColor=colors.white)

    hay_tablas_anchas = any(s["tipo"] == "tabla" and len(s["columnas"]) > 7 for s in reporte.secciones)
    tam_pagina = landscape(A4) if hay_tablas_anchas else A4
    ancho_util = tam_pagina[0] - 3 * cm

    salida = io.BytesIO()
    fecha = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")

    def encabezado(canvas, doc):
        canvas.saveState()
        canvas.setFont(normal, 8)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawString(1.5 * cm, tam_pagina[1] - 1 * cm, "EntreCOL+  |  Sistema de Información - ColPlus-Solutions")
        canvas.drawRightString(tam_pagina[0] - 1.5 * cm, 1 * cm, f"Página {doc.page}")
        canvas.drawString(1.5 * cm, 1 * cm, f"Generado: {fecha}  por {usuario}")
        canvas.restoreState()

    doc = SimpleDocTemplate(salida, pagesize=tam_pagina, leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                            topMargin=1.6 * cm, bottomMargin=1.6 * cm, title=reporte.titulo,
                            author="EntreCOL+")
    elementos = [Paragraph(_esc(reporte.titulo), est_titulo)]
    if reporte.parametros:
        elementos.append(Paragraph(_esc(reporte.parametros), est_texto))
    elementos.append(Spacer(1, 8))

    for s in reporte.secciones:
        if s["tipo"] == "titulo":
            elementos.append(Paragraph(_esc(s["texto"]), est_sub))
        elif s["tipo"] == "texto":
            elementos.append(Paragraph(_esc(s["texto"]), est_texto))
            elementos.append(Spacer(1, 4))
        elif s["tipo"] == "salto":
            elementos.append(PageBreak())
        elif s["tipo"] == "grafico":
            if s.get("titulo"):
                elementos.append(Paragraph(_esc(s["titulo"]), ParagraphStyle("gt", parent=est_texto, keepWithNext=1)))
            img = Image(io.BytesIO(s["png"]))
            escala = min(ancho_util / img.imageWidth, (tam_pagina[1] * 0.55) / img.imageHeight)
            img.drawWidth, img.drawHeight = img.imageWidth * escala, img.imageHeight * escala
            elementos.append(img)
            elementos.append(Spacer(1, 6))
        elif s["tipo"] == "tabla":
            if s.get("titulo"):
                elementos.append(Paragraph(_esc(s["titulo"]), ParagraphStyle(
                    "tt", parent=est_texto, fontName=negrita, keepWithNext=1)))
            filas = s["filas"][:LIMITE_FILAS_PDF]
            if not filas:
                elementos.append(Paragraph("<i>Sin registros.</i>", est_texto))
                elementos.append(Spacer(1, 6))
                continue
            datos = [[Paragraph(_esc(c), est_cab) for c in s["columnas"]]]
            datos += [[Paragraph(_esc(v), est_celda) for v in fila] for fila in filas]
            # ancho de cada columna según el largo del texto que tiene (con mínimo y máximo)
            pesos = []
            for i, col in enumerate(s["columnas"]):
                largo = max([len(str(col))] + [len(str(f[i])) for f in filas[:300]])
                pesos.append(min(max(largo, 8), 45))
            anchos = [ancho_util * p / sum(pesos) for p in pesos]
            tabla = LongTable(datos, repeatRows=1, colWidths=anchos)
            tabla.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a8a")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#eef2ff")]),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            elementos.append(tabla)
            if len(s["filas"]) > LIMITE_FILAS_PDF:
                elementos.append(Paragraph(
                    f"Se muestran las primeras {LIMITE_FILAS_PDF} de {len(s['filas'])} filas. "
                    "Use filtros más específicos para ver el resto.", est_texto))
            elementos.append(Spacer(1, 8))

    doc.build(elementos, onFirstPage=encabezado, onLaterPages=encabezado)
    return salida.getvalue()
