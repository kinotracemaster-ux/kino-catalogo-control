"""Registra las fotos de la carpeta de Drive y propone la vinculación SKU-foto."""
from django.core.management.base import BaseCommand

from core.connectors import drive


class Command(BaseCommand):
    help = "Sincroniza las imágenes maestras de Google Drive"

    def handle(self, *args, **opts):
        stats = drive.sync_images()
        self.stdout.write(
            f"Imágenes: {stats['images']} (nuevas {stats['new']}), vinculadas a SKU: {stats['linked']}, "
            f"sin SKU reconocido: {len(stats['unmatched'])}"
        )
        for name in stats["unmatched"][:30]:
            self.stdout.write(f"  sin SKU: {name}")
