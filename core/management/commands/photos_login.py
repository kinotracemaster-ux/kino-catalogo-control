"""Abre un navegador con el perfil del robot para iniciar sesión UNA vez con la cuenta de ventas.

Se ejecuta en la computadora donde corre el robot. La contraseña la escribe
una persona; el sistema no la guarda. Cierra la ventana al terminar.
"""
from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Inicia sesión en Google Fotos con el perfil del robot"

    def handle(self, *args, **opts):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(settings.KINO["PHOTOS_PROFILE_DIR"], headless=False)
            page = ctx.new_page()
            page.goto("https://photos.google.com/albums")
            self.stdout.write("Inicia sesión con el correo de ventas y luego cierra el navegador.")
            page.wait_for_event("close", timeout=0)
            ctx.close()
