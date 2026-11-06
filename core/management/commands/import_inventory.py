"""Importa el Excel de inventario desde un archivo local o desde la carpeta de Drive.

    python manage.py import_inventory ruta/al/archivo.xlsx
    python manage.py import_inventory --drive
"""
from django.core.management.base import BaseCommand, CommandError

from core.models import InventorySnapshot
from core.services.importer import ExcelError, import_inventory


class Command(BaseCommand):
    help = "Importa el Excel de inventario"

    def add_arguments(self, parser):
        parser.add_argument("path", nargs="?")
        parser.add_argument("--drive", action="store_true", help="Tomar el Excel más reciente de Drive")

    def handle(self, *args, **opts):
        try:
            if opts["drive"]:
                from core.connectors import drive

                f = drive.latest_inventory_file()
                if not f:
                    self.stdout.write("No hay archivos .xlsx en la carpeta de inventario.")
                    return
                if InventorySnapshot.objects.filter(
                    drive_file_id=f["id"], imported_at__gte=drive.modified_time(f)
                ).exists():
                    self.stdout.write(f"{f['name']} ya fue procesado.")
                    return
                snap, cmds = import_inventory(
                    drive.download(f["id"]), f["name"], source="drive",
                    drive_file_id=f["id"], cutoff_at=drive.modified_time(f),
                )
            else:
                if not opts["path"]:
                    raise CommandError("Indica la ruta del Excel o usa --drive")
                with open(opts["path"], "rb") as fh:
                    snap, cmds = import_inventory(fh, opts["path"].rsplit("/", 1)[-1])
        except ExcelError as exc:
            raise CommandError(str(exc))
        self.stdout.write(f"{snap.get_status_display()}: {snap.row_count} filas, {len(cmds)} órdenes nuevas")
        if snap.error_summary:
            self.stdout.write(snap.error_summary)
