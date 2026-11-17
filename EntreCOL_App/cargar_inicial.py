"""Carga inicial de la información entregada por EntreCOL+.

Uso (desde la carpeta EntreCOL_App):
    python cargar_inicial.py

Lee los archivos de la carpeta datos/ y los carga en la base de datos.
Antes de correrlo hay que ejecutar sql/01_esquema.sql en MySQL.
"""
import os
import sys

from cargadores import cargar_libros, cargar_nomina, cargar_peliculas
from db import consultar_uno

CARPETA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "datos")

# La hoja de novedades no trae el mes. Se toma como periodo de liquidación
# mayo de 2022, que es el mes de la novedad más reciente del archivo.
ANIO_NOMINA, MES_NOMINA = 2022, 5


def mostrar(nombre, r):
    print(f"\n== {nombre} ==")
    print(f"   Cargados:   {r['cargados']}")
    print(f"   Rechazados: {r['rechazados']}")
    for o in r["observaciones"][:15]:
        print("   -", o)
    if len(r["observaciones"]) > 15:
        print(f"   ... ({len(r['observaciones']) - 15} observaciones más, ver tabla Carga_Archivo)")


def main():
    admin = consultar_uno("SELECT ID_Usuario FROM Usuario WHERE Username='admin'")
    id_admin = admin["ID_Usuario"] if admin else None
    archivos = {
        "nomina": os.path.join(CARPETA, "Nomina.xlsx"),
        "peliculas": os.path.join(CARPETA, "movies.dat"),
        "libros": os.path.join(CARPETA, "Books.json"),
    }
    for nombre, ruta in archivos.items():
        if not os.path.exists(ruta):
            sys.exit(f"No se encontró el archivo {ruta}")

    mostrar("NÓMINA", cargar_nomina(archivos["nomina"], ANIO_NOMINA, MES_NOMINA, id_admin))
    mostrar("PELÍCULAS", cargar_peliculas(archivos["peliculas"], id_admin))
    mostrar("LIBROS", cargar_libros(archivos["libros"], id_admin))
    print("\nCarga inicial terminada.")


if __name__ == "__main__":
    main()
