# KINO CATÁLOGO CONTROL

Panel privado para **retirar o restaurar fotos de productos por referencia (SKU)** en los álbumes
**actuales** de Google Fotos de Kino, sincronizado con el Excel del programa de inventario.
Las fotos maestras viven en Google Drive (cuenta de **ventas**).

> Regla de oro: nunca se cambian los enlaces de los álbumes, nunca se desactiva el uso compartido,
> nunca se borra nada de Drive ni de Google Fotos.

## Qué hay hoy

| Parte | Estado |
|---|---|
| Base de datos (SKU, fotos, álbumes, bloqueos, órdenes, auditoría) | Listo |
| Importador de Excel con mapeo de columnas y validaciones de seguridad | Listo |
| Motor de decisiones (bloqueo manual > inventario) y cola sin duplicados | Listo |
| Panel: inicio, buscar SKU, Retirar / Liberar, órdenes, álbumes, subir Excel | Listo |
| Modo asistido (el equipo hace el cambio a mano y lo confirma) | Listo |
| Conector de Google Drive (lectura de fotos y Excel) | Listo, falta la cuenta de servicio |
| Robot de Google Fotos (Playwright) | Solo simulación; las acciones reales se completan en el piloto |

## Arrancar en local

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py setup_roles
python manage.py createsuperuser
python manage.py runserver
```

Abre http://127.0.0.1:8000, entra y en **Administración** configura:
1. **Mapeos de Excel**: hoja y nombres de columnas (SKU, saldo, bodega).
2. **Álbumes**: nombre, enlace compartido original y cuenta propietaria.
3. **Usuarios**: asígnales un grupo (Operador, Supervisor, Administrador, Auditor).

Pruebas: `python manage.py test core`

## Conectar Google Drive (cuenta de ventas)

1. En https://console.cloud.google.com crea un proyecto (p. ej. `kino-catalogo`).
2. Activa **Google Drive API**.
3. *IAM y administración → Cuentas de servicio → Crear*. Luego *Claves → Agregar clave → JSON*. Guarda el archivo; **no lo subas a GitHub**.
4. Desde el **correo de ventas**, comparte la carpeta de fotos y la carpeta de inventario con el correo de la cuenta de servicio (`...@...iam.gserviceaccount.com`) como **Lector**.
5. Copia los IDs de las carpetas (lo que va después de `/folders/` en la URL) a `DRIVE_PHOTOS_FOLDER_ID` y `DRIVE_INVENTORY_FOLDER_ID`, y el contenido del JSON a `GOOGLE_SERVICE_ACCOUNT_JSON`.
6. Prueba:
   ```bash
   python manage.py sync_drive_images      # registra fotos y propone SKU por nombre de archivo
   python manage.py import_inventory --drive
   ```

## Google Fotos

Desde marzo de 2025 la API oficial no permite manejar álbumes creados a mano, así que los álbumes
actuales solo se pueden operar desde la interfaz web. Por eso:

- **Por defecto (`KINO_PHOTOS_EXECUTOR=assisted`)** el sistema calcula qué foto quitar o poner en
  qué álbum, y el equipo lo hace a mano y pulsa **Hecho** en *Órdenes*.
- **Piloto del robot**: en la computadora de la oficina, `pip install playwright && playwright install chromium`,
  luego `python manage.py photos_login` (inicias sesión con el correo de ventas una vez) y
  `KINO_PHOTOS_EXECUTOR=playwright KINO_PHOTOS_DRY_RUN=1 python manage.py run_worker --once`.
  En simulación abre el álbum y verifica la sesión, sin hacer clics. Las acciones reales se
  programan después de observar la interfaz en **un álbum de prueba**.

## Despliegue (Railway)

El `Procfile` define `web` (panel) y `worker` (cola + revisión de Drive cada 15 min).
Agrega una base PostgreSQL y las variables de `.env.example`. El robot de Google Fotos
**no** corre en Railway: necesita un navegador con la sesión de ventas, en una computadora de Kino.

## Especificación

Ver `docs/ESPECIFICACION.md`.
