# EntreCOL+ – Sistema de Información

Proyecto Final Bases de Datos 2026-2 – ColPlus-Solutions.
Aplicación web en Python (Flask) con MySQL.

## Pasos rápidos

1. Ejecute `../sql/EntreCOL_BD_completa.sql` en MySQL 8 (Workbench: File > Open SQL Script > ejecutar todo).
2. Instale las librerías: `pip install -r requirements.txt`
3. Ponga su usuario y contraseña de MySQL en `config.py`.
4. Inicie: `python app.py` (o doble clic en `iniciar.bat`).
5. Abra http://127.0.0.1:5000 e ingrese con **admin / Admin123***

Si prefiere empezar con la base vacía: ejecute `../sql/01_esquema.sql` y luego `python cargar_inicial.py`.

## Archivos

| Archivo | Para qué sirve |
|---|---|
| app.py | Rutas de la aplicación (login, CRUD, cargas, consultas, reportes, usuarios, auditoría) |
| config.py | Conexión a MySQL y parámetros de seguridad |
| db.py | Conexión y funciones de consulta |
| seguridad.py | bcrypt, captcha, roles, CSRF y auditoría |
| entidades.py | Definición de las tablas del CRUD |
| cargadores.py | Carga del Excel, el .dat y el .json |
| cargar_inicial.py | Carga inicial desde la carpeta datos/ |
| reportes.py | Los 5 reportes del cliente |
| informes_base.py | Gráficos (matplotlib) y PDF (ReportLab) |
| templates/, static/ | Pantallas HTML, CSS y fuentes |
| datos/ | Archivos originales del cliente |

Más detalle en el Manual de Usuario.
