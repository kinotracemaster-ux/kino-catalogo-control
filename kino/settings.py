"""Configuración de KINO CATÁLOGO CONTROL.

Todo lo sensible se lee de variables de entorno (ver .env.example).
Nunca escribir credenciales, cookies ni tokens en el código.
"""
import os
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).lower() in ("1", "true", "yes", "si", "sí")


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "solo-para-desarrollo-cambiar-en-produccion")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = [h for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h]
CSRF_TRUSTED_ORIGINS = [o for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "kino.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "kino.wsgi.application"

# PostgreSQL en producción (DATABASE_URL); SQLite solo para desarrollo local.
DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "es-co"
TIME_ZONE = "America/Bogota"  # se guarda en UTC, se muestra en hora de Colombia
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login/"

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# --- Integraciones (cuenta de Google de VENTAS de Kino) ---
KINO = {
    # Opción 1 (recomendada): sesión de la cuenta de ventas, creada con `manage.py drive_login`.
    "GOOGLE_OAUTH_TOKEN_JSON": os.environ.get("GOOGLE_OAUTH_TOKEN_JSON", ""),
    "GOOGLE_OAUTH_TOKEN_FILE": os.environ.get("GOOGLE_OAUTH_TOKEN_FILE", ""),
    # Opción 2: cuenta de servicio de Google Cloud: ruta a JSON o el JSON completo en la variable.
    "GOOGLE_SERVICE_ACCOUNT_FILE": os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", ""),
    "GOOGLE_SERVICE_ACCOUNT_JSON": os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", ""),
    # Carpetas de Drive (IDs) compartidas con la cuenta de servicio.
    "DRIVE_INVENTORY_FOLDER_ID": os.environ.get("DRIVE_INVENTORY_FOLDER_ID", ""),
    "DRIVE_PHOTOS_FOLDER_ID": os.environ.get("DRIVE_PHOTOS_FOLDER_ID", ""),
    # Umbrales de seguridad del importador (propuestas iniciales, ajustar con datos reales).
    "MAX_MISSING_SKU_PCT": float(os.environ.get("KINO_MAX_MISSING_SKU_PCT", "5")),
    "MAX_SOLD_OUT_PCT": float(os.environ.get("KINO_MAX_SOLD_OUT_PCT", "15")),
    "STALE_INVENTORY_HOURS": int(os.environ.get("KINO_STALE_INVENTORY_HOURS", "24")),
    "MAX_EXCEL_MB": int(os.environ.get("KINO_MAX_EXCEL_MB", "20")),
    # Ejecutor de Google Fotos. Por defecto: modo asistido (nadie toca Google Fotos automáticamente).
    "PHOTOS_EXECUTOR": os.environ.get("KINO_PHOTOS_EXECUTOR", "assisted"),  # assisted | playwright
    "PHOTOS_PROFILE_DIR": os.environ.get("KINO_PHOTOS_PROFILE_DIR", str(BASE_DIR / ".photos-profile")),
    "PHOTOS_DRY_RUN": env_bool("KINO_PHOTOS_DRY_RUN", True),
    "MAX_COMMAND_ATTEMPTS": int(os.environ.get("KINO_MAX_COMMAND_ATTEMPTS", "3")),
}
