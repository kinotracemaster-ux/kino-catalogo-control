"""Proceso trabajador: ejecuta la cola y revisa Drive cada N minutos.

    python manage.py run_worker            # bucle
    python manage.py run_worker --once     # una pasada
"""
import time

from django.core.management import call_command
from django.core.management.base import BaseCommand

from core.executor import worker


class Command(BaseCommand):
    help = "Ejecuta la cola de órdenes y la importación programada"

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--drive-every", type=int, default=15, help="Minutos entre revisiones de Drive (0 = no)")
        parser.add_argument("--sleep", type=int, default=30)

    def handle(self, *args, **opts):
        last_drive = 0.0
        while True:
            worker.recover_stale()
            if opts["drive_every"] and time.time() - last_drive >= opts["drive_every"] * 60:
                last_drive = time.time()
                try:
                    call_command("import_inventory", drive=True)
                except Exception as exc:  # Drive no configurado o caído: no detener la cola
                    self.stderr.write(f"Drive: {exc}")
            n = worker.run_once()
            if n:
                self.stdout.write(f"{n} órdenes procesadas")
            if opts["once"]:
                break
            time.sleep(opts["sleep"])
