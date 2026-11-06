"""Motor de decisiones y cola de órdenes (secciones 6 y 11 de la especificación).

Regla del MVP:
    bloqueo manual            -> HIDDEN
    inventario inválido/None  -> mantener estado previo y marcar revisión (None)
    stock <= 0                -> HIDDEN
    stock > 0                 -> VISIBLE
"""
from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from core.models import (
    AlbumImage,
    AuditEvent,
    Command,
    InventoryItem,
    InventorySnapshot,
    ManualBlock,
    Product,
    Visibility,
)


def desired_visibility(stock, inventory_valid, manual_block):
    """Función pura con la regla de negocio. Devuelve None = no recalcular."""
    if manual_block:
        return Visibility.HIDDEN
    if not inventory_valid or stock is None:
        return None
    if stock <= 0:
        return Visibility.HIDDEN
    return Visibility.VISIBLE


@dataclass
class ProductState:
    product: Product
    stock: object
    inventory_valid: bool
    snapshot: InventorySnapshot | None
    block: ManualBlock | None
    desired: str | None
    reason: str
    album_images: list = field(default_factory=list)


def product_state(product, snapshot=None):
    snapshot = snapshot or InventorySnapshot.latest_valid()
    item = None
    if snapshot:
        item = InventoryItem.objects.filter(snapshot=snapshot, product=product).first()
    block = product.active_block
    stock = item.stock if item else None
    valid = bool(snapshot and item and not item.flagged)
    desired = desired_visibility(stock, valid, block is not None)

    if block:
        reason = "Bloqueo manual activo"
    elif not snapshot:
        reason = "Aún no hay un inventario válido importado"
    elif not item:
        reason = "SIN DATO: el SKU no aparece en el último Excel válido"
    elif item.flagged:
        reason = f"En revisión: {item.flagged}"
    elif stock <= 0:
        reason = "Stock en cero"
    else:
        reason = "Disponible"

    album_images = list(
        AlbumImage.objects.filter(drive_image__products__product=product)
        .select_related("album", "drive_image")
        .distinct()
    )
    return ProductState(product, stock, valid, snapshot, block, desired, reason, album_images)


def _cancel_obsolete(album_image, wanted_action):
    """Si el estado deseado cambió antes de ejecutar, la orden contraria pendiente queda obsoleta."""
    opposite = Command.Action.ADD if wanted_action == Command.Action.REMOVE else Command.Action.REMOVE
    album_image.commands.filter(
        action=opposite, status__in=[Command.Status.PENDING, Command.Status.RETRYABLE_ERROR]
    ).update(status=Command.Status.CANCELED, finished_at=timezone.now(), error_code="OBSOLETE")


def _enqueue(album_image, action, source, trigger, product, actor):
    """Crea una orden si no existe una equivalente abierta."""
    if album_image.commands.filter(action=action, status__in=Command.OPEN_STATUSES).exists():
        return None

    cmd, created = Command.objects.get_or_create(
        idempotency_key=f"ai{album_image.pk}:{action}:{trigger}",
        defaults=dict(
            action=action,
            source=source,
            album_image=album_image,
            product=product,
            requested_by=actor if getattr(actor, "pk", None) else None,
        ),
    )
    return cmd if created else None


def recalculate(product, source, trigger, actor=None, snapshot=None):
    """Recalcula la visibilidad deseada de cada foto+álbum del SKU y encola lo necesario."""
    created = []
    with transaction.atomic():
        state = product_state(product, snapshot)
        if state.desired is None:
            return state, created  # mantener estado previo; el tablero muestra el motivo
        for ai in AlbumImage.objects.select_for_update().filter(pk__in=[a.pk for a in state.album_images]):
            ai.desired_state = state.desired
            ai.save(update_fields=["desired_state"])
            action = Command.Action.ADD if state.desired == Visibility.VISIBLE else Command.Action.REMOVE
            _cancel_obsolete(ai, action)
            if ai.observed_state == state.desired:
                continue
            cmd = _enqueue(ai, action, source, trigger, product, actor)
            if cmd:
                created.append(cmd)
    return state, created


def block_product(product, actor, reason=""):
    with transaction.atomic():
        block = ManualBlock.objects.select_for_update().filter(product=product, active=True).first()
        if not block:
            block = ManualBlock.objects.create(product=product, reason=reason, created_by=actor)
            AuditEvent.log(actor, "MANUAL_BLOCK", product.sku, after={"reason": reason})
        state, cmds = recalculate(product, Command.Source.MANUAL, f"block{block.pk}", actor)
    return block, state, cmds


def release_block(product, actor):
    with transaction.atomic():
        block = ManualBlock.objects.select_for_update().filter(product=product, active=True).first()
        if not block:
            return None, product_state(product), []
        block.active = False
        block.cleared_by = actor
        block.cleared_at = timezone.now()
        block.save()
        AuditEvent.log(actor, "MANUAL_RELEASE", product.sku, before={"reason": block.reason})
        state, cmds = recalculate(product, Command.Source.MANUAL, f"release{block.pk}", actor)
    return block, state, cmds


def recalculate_all(snapshot, actor=None):
    """Tras una importación válida: recalcula todos los SKU que tienen fotos en álbumes."""
    created = []
    products = Product.objects.filter(images__drive_image__album_images__isnull=False).distinct()
    for product in products:
        _, cmds = recalculate(product, Command.Source.INVENTORY, f"snap{snapshot.pk}", actor, snapshot)
        created.extend(cmds)
    return created
