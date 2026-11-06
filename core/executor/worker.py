"""Trabajador de la cola: toma órdenes pendientes y las pasa al ejecutor."""
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.models import AlbumImage, AuditEvent, Command
from core.executor.photos import get_executor

STALE_RUNNING = timedelta(minutes=30)


def recover_stale():
    """Órdenes RUNNING viejas (p. ej. tras un reinicio) no se repiten a ciegas: van a revisión."""
    return Command.objects.filter(
        status=Command.Status.RUNNING, started_at__lt=timezone.now() - STALE_RUNNING
    ).update(status=Command.Status.NEEDS_HUMAN, error_code="STALE_RUNNING")


def claim_next():
    with transaction.atomic():
        cmd = (
            Command.objects.select_for_update(skip_locked=True)
            .filter(
                status__in=[Command.Status.PENDING, Command.Status.RETRYABLE_ERROR],
                album_image__album__paused=False,
                album_image__album__authorized=True,
            )
            .order_by("created_at")
            .first()
        )
        if not cmd:
            return None
        cmd.status = Command.Status.RUNNING
        cmd.attempts += 1
        cmd.started_at = timezone.now()
        cmd.save(update_fields=["status", "attempts", "started_at"])
        return cmd


def apply_result(cmd, result, actor="robot"):
    cmd.status = result.status
    cmd.error_code = result.error_code
    cmd.error_detail = result.detail
    if result.status == Command.Status.RETRYABLE_ERROR and cmd.attempts >= settings.KINO["MAX_COMMAND_ATTEMPTS"]:
        cmd.status = Command.Status.FAILED
    if cmd.status in (Command.Status.CONFIRMED, Command.Status.FAILED):
        cmd.finished_at = timezone.now()
    cmd.save()
    if result.observed:
        AlbumImage.objects.filter(pk=cmd.album_image_id).update(
            observed_state=result.observed, observed_at=timezone.now()
        )
    AuditEvent.log(actor, f"COMMAND_{cmd.status}", f"cmd{cmd.pk}", after={"error": result.error_code})


def confirm_manually(cmd, user, evidence=""):
    """Modo asistido: una persona hizo el cambio en el álbum y lo confirma."""
    from core.models import Visibility

    observed = Visibility.VISIBLE if cmd.action == Command.Action.ADD else Visibility.HIDDEN
    cmd.status = Command.Status.CONFIRMED
    cmd.finished_at = timezone.now()
    cmd.confirmed_by = user
    cmd.evidence = evidence
    cmd.save()
    AlbumImage.objects.filter(pk=cmd.album_image_id).update(observed_state=observed, observed_at=timezone.now())
    AuditEvent.log(user, "COMMAND_CONFIRMED_MANUAL", f"cmd{cmd.pk}", after={"evidence": evidence})


def run_once():
    executor = get_executor()
    if executor.name == "assisted":
        return 0  # en modo asistido las órdenes esperan a una persona en el panel
    processed = 0
    while (cmd := claim_next()) is not None:
        apply_result(cmd, executor.run(cmd))
        processed += 1
        if cmd.status == Command.Status.NEEDS_HUMAN and cmd.error_code == "LOGIN_REQUIRED":
            break  # sin sesión no tiene sentido seguir
    return processed
