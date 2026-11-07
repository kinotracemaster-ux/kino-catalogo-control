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

La organización bloquea las claves de cuentas de servicio, así que el sistema entra a Drive
**con la propia cuenta de ventas, en modo solo lectura**:

1. En https://console.cloud.google.com (proyecto `gold-virtue-498220-r0`) ve a
   *APIs y servicios → Pantalla de consentimiento de OAuth*: tipo **Interno**, nombre `Kino Catálogo`.
2. *APIs y servicios → Credenciales → Crear credenciales → ID de cliente de OAuth* →
   tipo **App de escritorio** → descarga el JSON (`client_secret_....json`).
3. En la computadora, con el proyecto instalado:
   ```bash
   python manage.py drive_login --client-secrets client_secret_XXXX.json
   ```
   Se abre el navegador: entra con la cuenta de ventas y acepta. Se crea `drive-token.json`.
4. En el servidor, pon el contenido de `drive-token.json` en `GOOGLE_OAUTH_TOKEN_JSON`, y los IDs
   de las carpetas (lo que va después de `/folders/` en la URL) en `DRIVE_PHOTOS_FOLDER_ID` y
   `DRIVE_INVENTORY_FOLDER_ID`. **Ninguno de estos archivos se sube a GitHub.**
5. Prueba:
   ```bash
   python manage.py sync_drive_images      # registra fotos y propone SKU por nombre de archivo
   python manage.py import_inventory --drive
   ```

Alternativa: si un superadministrador quita la política `iam.disableServiceAccountKeyCreation`,
también funciona una cuenta de servicio (`GOOGLE_SERVICE_ACCOUNT_JSON`) con las carpetas compartidas como Lector.

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
