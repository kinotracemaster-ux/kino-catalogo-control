"""Conector de Google Drive (solo lectura).

Dos formas de autenticarse (se usa la primera que esté configurada):

1. GOOGLE_OAUTH_TOKEN_JSON / GOOGLE_OAUTH_TOKEN_FILE (recomendada para Kino):
   la cuenta de VENTAS inicia sesión una vez con `python manage.py drive_login`
   y se guarda un permiso de solo lectura. No requiere claves de cuenta de
   servicio (bloqueadas por la política de la organización).
2. GOOGLE_SERVICE_ACCOUNT_JSON / GOOGLE_SERVICE_ACCOUNT_FILE: cuenta de servicio
   con las carpetas compartidas como «Lector».

Nunca modifica ni borra archivos de Drive.
"""
import io
import json
import re

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from core.models import DriveImage, Product, ProductImage, normalize_sku

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
FOLDER_MIME = "application/vnd.google-apps.folder"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
FIELDS = "nextPageToken, files(id, name, mimeType, md5Checksum, modifiedTime, size)"


class DriveNotConfigured(Exception):
    pass


def get_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    cfg = settings.KINO
    if cfg["GOOGLE_OAUTH_TOKEN_JSON"] or cfg["GOOGLE_OAUTH_TOKEN_FILE"]:
        from google.oauth2.credentials import Credentials

        if cfg["GOOGLE_OAUTH_TOKEN_JSON"]:
            creds = Credentials.from_authorized_user_info(json.loads(cfg["GOOGLE_OAUTH_TOKEN_JSON"]), SCOPES)
        else:
            creds = Credentials.from_authorized_user_file(cfg["GOOGLE_OAUTH_TOKEN_FILE"], SCOPES)
    elif cfg["GOOGLE_SERVICE_ACCOUNT_JSON"]:
        info = json.loads(cfg["GOOGLE_SERVICE_ACCOUNT_JSON"])
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    elif cfg["GOOGLE_SERVICE_ACCOUNT_FILE"]:
        creds = service_account.Credentials.from_service_account_file(cfg["GOOGLE_SERVICE_ACCOUNT_FILE"], scopes=SCOPES)
    else:
        raise DriveNotConfigured("Falta GOOGLE_OAUTH_TOKEN_JSON (ejecuta drive_login) o una cuenta de servicio")
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def list_children(service, folder_id):
    token = None
    while True:
        resp = (
            service.files()
            .list(
                q=f"'{folder_id}' in parents and trashed = false",
                fields=FIELDS,
                pageToken=token,
                pageSize=1000,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        yield from resp.get("files", [])
        token = resp.get("nextPageToken")
        if not token:
            break


def walk_images(service, folder_id, path=""):
    for f in list_children(service, folder_id):
        if f["mimeType"] == FOLDER_MIME:
            yield from walk_images(service, f["id"], f"{path}/{f['name']}".strip("/"))
        elif f["mimeType"].startswith("image/"):
            yield path, f


# "815B-1.jpg" -> candidatos ["815B-1", "815B"]; nunca inventa SKU nuevos.
SUFFIX = re.compile(r"^(?P<base>.+?)[ _\-\(]+(?P<n>\d{1,2})\)?$")


def sku_candidates(filename):
    stem = filename.rsplit(".", 1)[0]
    cands = [normalize_sku(stem)]
    m = SUFFIX.match(stem)
    if m:
        cands.append(normalize_sku(m.group("base")))
    return cands


def sync_images(folder_id=None):
    """Registra las imágenes de Drive y propone la vinculación SKU-foto (sin verificar)."""
    service = get_service()
    folder_id = folder_id or settings.KINO["DRIVE_PHOTOS_FOLDER_ID"]
    if not folder_id:
        raise DriveNotConfigured("Falta DRIVE_PHOTOS_FOLDER_ID")
    stats = {"images": 0, "new": 0, "linked": 0, "unmatched": []}
    now = timezone.now()
    for path, f in walk_images(service, folder_id):
        stats["images"] += 1
        img, created = DriveImage.objects.update_or_create(
            drive_file_id=f["id"],
            defaults=dict(
                filename=f["name"], folder_path=path, mime_type=f["mimeType"],
                checksum=f.get("md5Checksum", ""), active=True, last_seen_at=now,
            ),
        )
        stats["new"] += int(created)
        if img.products.exists():
            continue
        product = Product.objects.filter(sku__in=sku_candidates(f["name"])).first()
        if product:
            ProductImage.objects.get_or_create(product=product, drive_image=img)
            stats["linked"] += 1
        else:
            stats["unmatched"].append(f"{path}/{f['name']}")
    return stats


def latest_inventory_file(folder_id=None):
    service = get_service()
    folder_id = folder_id or settings.KINO["DRIVE_INVENTORY_FOLDER_ID"]
    if not folder_id:
        raise DriveNotConfigured("Falta DRIVE_INVENTORY_FOLDER_ID")
    files = [f for f in list_children(service, folder_id) if f["mimeType"] == XLSX_MIME]
    if not files:
        return None
    return max(files, key=lambda f: f["modifiedTime"])


def download(file_id):
    from googleapiclient.http import MediaIoBaseDownload

    service = get_service()
    buf = io.BytesIO()
    req = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    downloader = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    buf.seek(0)
    return buf


def modified_time(f):
    return parse_datetime(f["modifiedTime"])
