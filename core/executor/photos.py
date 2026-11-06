"""Ejecutor de Google Fotos (sección 10).

La API oficial de Google Fotos ya no permite gestionar álbumes creados a mano
(desde el 31-mar-2025), así que los álbumes actuales solo se pueden operar por
la interfaz web. Este módulo tiene dos ejecutores:

- AssistedExecutor (por defecto): no toca Google Fotos. Las órdenes quedan en
  el panel para que una persona las haga y las confirme.
- PlaywrightExecutor: robot de navegador para el PILOTO (Fase 0). Arranca en
  modo simulación (KINO_PHOTOS_DRY_RUN=1): abre el álbum, comprueba la sesión y
  que el enlace siga funcionando, pero NO hace clic en nada. Las acciones reales
  (quitar/añadir) se completan solo después de observar la interfaz real en el
  álbum de prueba y obtener el GO.

Prohibiciones (nunca implementar): borrar álbumes, mover a la papelera, cambiar
o desactivar el uso compartido, operar álbumes no autorizados, resolver captchas
o eludir MFA, marcar éxito sin verificar.
"""
from dataclasses import dataclass

from django.conf import settings


@dataclass
class Result:
    status: str  # CONFIRMED | NEEDS_HUMAN | RETRYABLE_ERROR | FAILED
    error_code: str = ""
    detail: str = ""
    observed: str | None = None  # VISIBLE | HIDDEN si se verificó


class AssistedExecutor:
    name = "assisted"

    def run(self, command):
        return Result("NEEDS_HUMAN", "ASSISTED_MODE", "Modo asistido: hazlo a mano en el álbum y confírmalo en el panel.")


class PlaywrightExecutor:
    name = "playwright"
    LOGIN_HOSTS = ("accounts.google.com",)

    def __init__(self):
        self.profile_dir = settings.KINO["PHOTOS_PROFILE_DIR"]
        self.dry_run = settings.KINO["PHOTOS_DRY_RUN"]

    def _open(self, playwright):
        # Perfil persistente: la sesión de la cuenta de ventas se inicia UNA vez a mano
        # con `python manage.py photos_login`. No se guardan contraseñas.
        return playwright.chromium.launch_persistent_context(self.profile_dir, headless=False)

    def run(self, command):
        album = command.album_image.album
        if not album.authorized or album.paused:
            return Result("FAILED", "ALBUM_NOT_AUTHORIZED", "El álbum no está en la lista autorizada o está pausado.")
        if not command.album_image.mapping_verified or not command.album_image.photos_item_locator:
            return Result("NEEDS_HUMAN", "MAPPING_NOT_VERIFIED", "Falta identificar la foto exacta en Google Fotos.")

        from playwright.sync_api import TimeoutError as PWTimeout
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            ctx = self._open(p)
            try:
                page = ctx.new_page()
                page.goto(album.share_url, wait_until="domcontentloaded", timeout=45_000)
                if any(h in page.url for h in self.LOGIN_HOSTS):
                    return Result("NEEDS_HUMAN", "LOGIN_REQUIRED", "Google pide iniciar sesión. Ejecuta photos_login.")
                if self.dry_run:
                    return Result(
                        "NEEDS_HUMAN", "DRY_RUN",
                        f"Simulación: el álbum abrió en {page.url}. No se hizo ningún cambio.",
                    )
                # Pendiente del piloto: localizar la foto por photos_item_locator,
                # usar «Quitar del álbum» / «Añadir a álbum» y VERIFICAR el resultado.
                return Result("NEEDS_HUMAN", "NOT_IMPLEMENTED", "Acción real pendiente del piloto con el álbum de prueba.")
            except PWTimeout:
                return Result("RETRYABLE_ERROR", "TIMEOUT", "Google Fotos no respondió a tiempo.")
            finally:
                ctx.close()


def get_executor():
    if settings.KINO["PHOTOS_EXECUTOR"] == "playwright":
        return PlaywrightExecutor()
    return AssistedExecutor()
