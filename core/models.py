"""Modelo de datos mínimo (sección 8 de la especificación).

Conceptos que NO se mezclan:
- stock: existencia del último Excel válido (InventoryItem).
- manual block: bloqueo manual persistente (ManualBlock).
- desired_state: lo que debería verse (AlbumImage.desired_state).
- observed_state: lo que se verificó en el álbum (AlbumImage.observed_state).
"""
from django.conf import settings
from django.db import models
from django.db.models import Q


def normalize_sku(raw):
    """Normalización NO destructiva: mayúsculas y espacios marginales.

    Conserva guiones y ceros a la izquierda. Los números que Excel guarda como
    float entero (p. ej. 9051.0) se devuelven sin el ".0".
    """
    if raw is None:
        return ""
    if isinstance(raw, float) and raw.is_integer():
        raw = int(raw)
    return str(raw).strip().upper()


class Visibility(models.TextChoices):
    VISIBLE = "VISIBLE", "Visible"
    HIDDEN = "HIDDEN", "Oculto"
    UNKNOWN = "UNKNOWN", "Sin verificar"


class Product(models.Model):
    sku = models.CharField(max_length=80, unique=True)
    brand = models.CharField(max_length=80, blank=True)
    name = models.CharField(max_length=200, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sku"]
        verbose_name = "producto"

    def save(self, *args, **kwargs):
        self.sku = normalize_sku(self.sku)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.sku

    @property
    def active_block(self):
        return self.manual_blocks.filter(active=True).first()


class ExcelMapping(models.Model):
    """Mapeo configurable de columnas del Excel del programa de inventario."""

    name = models.CharField(max_length=80, default="Principal")
    active = models.BooleanField(default=True)
    sheet_name = models.CharField(max_length=80, blank=True, help_text="Vacío = primera hoja")
    header_row = models.PositiveIntegerField(default=1)
    sku_column = models.CharField(max_length=80, default="Referencia")
    stock_column = models.CharField(max_length=80, default="Saldo")
    brand_column = models.CharField(max_length=80, blank=True)
    name_column = models.CharField(max_length=80, blank=True)
    warehouse_column = models.CharField(max_length=80, blank=True)
    counted_warehouses = models.CharField(
        max_length=300, blank=True, help_text="Bodegas que cuentan, separadas por coma. Vacío = todas"
    )
    sum_warehouses = models.BooleanField(
        default=False,
        help_text="Si un SKU aparece en varias filas por bodega, sumar. Si no, se marca como duplicado y se bloquea.",
    )

    class Meta:
        verbose_name = "mapeo de Excel"
        verbose_name_plural = "mapeos de Excel"

    def __str__(self):
        return self.name

    def warehouse_list(self):
        return [w.strip().upper() for w in self.counted_warehouses.split(",") if w.strip()]


class InventorySnapshot(models.Model):
    class Status(models.TextChoices):
        VALID = "VALID", "Válido"
        REVIEW = "REVIEW", "En revisión"
        REJECTED = "REJECTED", "Rechazado"
        DUPLICATE = "DUPLICATE", "Repetido (ignorado)"

    source = models.CharField(max_length=20, default="upload")  # upload | drive
    filename = models.CharField(max_length=255)
    drive_file_id = models.CharField(max_length=120, blank=True)
    file_hash = models.CharField(max_length=64, db_index=True)
    source_cutoff_at = models.DateTimeField(null=True, blank=True)
    imported_at = models.DateTimeField(auto_now_add=True)
    imported_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=12, choices=Status.choices)
    row_count = models.PositiveIntegerField(default=0)
    error_summary = models.TextField(blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-imported_at"]
        verbose_name = "importación de inventario"
        verbose_name_plural = "importaciones de inventario"

    def __str__(self):
        return f"{self.filename} ({self.get_status_display()})"

    @classmethod
    def latest_valid(cls):
        return cls.objects.filter(status=cls.Status.VALID).order_by("-imported_at").first()


class InventoryItem(models.Model):
    snapshot = models.ForeignKey(InventorySnapshot, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="inventory_items")
    stock = models.DecimalField(max_digits=12, decimal_places=2, null=True)
    warehouse_scope = models.CharField(max_length=200, blank=True)
    flagged = models.CharField(max_length=200, blank=True, help_text="Motivo si el SKU quedó en revisión")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["snapshot", "product"], name="uniq_item_per_snapshot")]


class DriveImage(models.Model):
    drive_file_id = models.CharField(max_length=120, unique=True)
    filename = models.CharField(max_length=255)
    folder_path = models.CharField(max_length=500, blank=True)
    mime_type = models.CharField(max_length=80, blank=True)
    checksum = models.CharField(max_length=64, blank=True)  # md5 que entrega Drive
    active = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["filename"]
        verbose_name = "imagen de Drive"
        verbose_name_plural = "imágenes de Drive"

    def __str__(self):
        return self.filename


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    drive_image = models.ForeignKey(DriveImage, on_delete=models.CASCADE, related_name="products")
    sort_order = models.PositiveIntegerField(default=0)
    verified = models.BooleanField(default=False, help_text="Vinculación revisada por una persona")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["product", "drive_image"], name="uniq_product_image")]
        ordering = ["sort_order"]


class Album(models.Model):
    name = models.CharField(max_length=120)
    share_url = models.URLField(max_length=500, unique=True, help_text="Enlace compartido ORIGINAL. Inmutable.")
    owner_account = models.CharField(max_length=200, help_text="Cuenta de Google propietaria (correo de ventas)")
    authorized = models.BooleanField(default=False, help_text="Incluido en la lista autorizada para el ejecutor")
    paused = models.BooleanField(default=False)
    last_verified_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "álbum"

    def __str__(self):
        return self.name


class AlbumImage(models.Model):
    album = models.ForeignKey(Album, on_delete=models.CASCADE, related_name="album_images")
    drive_image = models.ForeignKey(DriveImage, on_delete=models.CASCADE, related_name="album_images")
    photos_item_locator = models.CharField(
        max_length=500, blank=True, help_text="Cómo encontrar el elemento en Google Fotos (enlace o identificador comprobado)"
    )
    desired_state = models.CharField(max_length=10, choices=Visibility.choices, default=Visibility.UNKNOWN)
    observed_state = models.CharField(max_length=10, choices=Visibility.choices, default=Visibility.UNKNOWN)
    observed_at = models.DateTimeField(null=True, blank=True)
    mapping_verified = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["album", "drive_image"], name="uniq_album_image")]


class ManualBlock(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="manual_blocks")
    active = models.BooleanField(default=True)
    reason = models.CharField(max_length=300, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    cleared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    cleared_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["product"], condition=Q(active=True), name="one_active_block_per_sku")
        ]
        verbose_name = "bloqueo manual"
        verbose_name_plural = "bloqueos manuales"


class Command(models.Model):
    class Action(models.TextChoices):
        REMOVE = "REMOVE", "Retirar del álbum"
        ADD = "ADD", "Añadir / restaurar en el álbum"
        VERIFY = "VERIFY", "Verificar"

    class Source(models.TextChoices):
        MANUAL = "MANUAL", "Manual"
        INVENTORY = "INVENTARIO", "Inventario"
        RECONCILIATION = "RECONCILIACION", "Conciliación"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pendiente"
        RUNNING = "RUNNING", "En ejecución"
        CONFIRMED = "CONFIRMED", "Confirmada"
        NEEDS_HUMAN = "NEEDS_HUMAN", "Necesita intervención"
        RETRYABLE_ERROR = "RETRYABLE_ERROR", "Error, se reintentará"
        FAILED = "FAILED", "Falló"
        CANCELED = "CANCELED", "Cancelada (obsoleta)"

    OPEN_STATUSES = (Status.PENDING, Status.RUNNING, Status.RETRYABLE_ERROR, Status.NEEDS_HUMAN)

    action = models.CharField(max_length=10, choices=Action.choices)
    source = models.CharField(max_length=16, choices=Source.choices)
    album_image = models.ForeignKey(AlbumImage, on_delete=models.CASCADE, related_name="commands")
    product = models.ForeignKey(Product, null=True, on_delete=models.SET_NULL, related_name="commands")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
    idempotency_key = models.CharField(max_length=200, unique=True)
    attempts = models.PositiveIntegerField(default=0)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(max_length=60, blank=True)
    error_detail = models.TextField(blank=True)
    evidence = models.TextField(blank=True, help_text="Nota o ruta de captura; nunca credenciales")
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "orden"
        verbose_name_plural = "órdenes"

    def __str__(self):
        return f"{self.get_action_display()} {self.product} en {self.album_image.album}"


class AuditEvent(models.Model):
    actor = models.CharField(max_length=150)
    event_type = models.CharField(max_length=60)
    target = models.CharField(max_length=200)
    before_json = models.JSONField(null=True, blank=True)
    after_json = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "evento de auditoría"
        verbose_name_plural = "auditoría"

    @classmethod
    def log(cls, actor, event_type, target, before=None, after=None):
        name = getattr(actor, "username", None) or str(actor or "sistema")
        return cls.objects.create(
            actor=name, event_type=event_type, target=str(target), before_json=before, after_json=after
        )
