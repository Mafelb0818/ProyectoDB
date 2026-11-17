"""Conexión a la base de datos MySQL y funciones de ayuda."""
import pymysql
import pymysql.cursors

import config


def conectar(solo_lectura=False):
    con = pymysql.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        database=config.DB_NAME,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )
    if solo_lectura:
        with con.cursor() as cur:
            cur.execute("SET SESSION TRANSACTION READ ONLY")
    return con


def consultar(sql, params=None):
    """Ejecuta un SELECT y devuelve una lista de diccionarios."""
    con = conectar()
    try:
        with con.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.fetchall()
    finally:
        con.close()


def consultar_uno(sql, params=None):
    filas = consultar(sql, params)
    return filas[0] if filas else None


def ejecutar(sql, params=None):
    """Ejecuta INSERT / UPDATE / DELETE. Devuelve el último id insertado."""
    con = conectar()
    try:
        with con.cursor() as cur:
            cur.execute(sql, params or ())
            nuevo_id = cur.lastrowid
        con.commit()
        return nuevo_id
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
