"""Inicia sesión UNA vez con la cuenta de ventas para leer Drive (solo lectura).

    python manage.py drive_login --client-secrets client_secret.json

Abre el navegador, la persona entra con la cuenta de ventas y acepta.
Se guarda drive-token.json (NO subirlo a GitHub). Su contenido va en la
variable GOOGLE_OAUTH_TOKEN_JSON del servidor.
"""
from django.core.management.base import BaseCommand

from core.connectors.drive import SCOPES


class Command(BaseCommand):
    help = "Autoriza el acceso de solo lectura a Google Drive con la cuenta de ventas"

    def add_arguments(self, parser):
        parser.add_argument("--client-secrets", required=True, help="JSON del cliente OAuth de escritorio")
        parser.add_argument("--out", default="drive-token.json")

    def handle(self, *args, **opts):
        from google_auth_oauthlib.flow import InstalledAppFlow

        flow = InstalledAppFlow.from_client_secrets_file(opts["client_secrets"], SCOPES)
        creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
        with open(opts["out"], "w") as fh:
            fh.write(creds.to_json())
        self.stdout.write(f"Listo. Permiso guardado en {opts['out']}. No lo compartas ni lo subas a GitHub.")
