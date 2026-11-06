from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.executor import worker
from core.models import Album, Command, InventorySnapshot, ManualBlock, Product, normalize_sku
from core.permissions import has_role, role_required
from core.services import decisions, importer


def _ctx(request, **extra):
    extra.update(
        can_operate=has_role(request.user, "Operador"),
        can_supervise=has_role(request.user, "Supervisor"),
        executor_mode=settings.KINO["PHOTOS_EXECUTOR"],
    )
    return extra


@login_required
def dashboard(request):
    snap = InventorySnapshot.latest_valid()
    counts = {}
    stale = False
    if snap:
        items = snap.items.all()
        counts = {
            "total": items.count(),
            "available": items.filter(stock__gt=0, flagged="").count(),
            "sold_out": items.filter(stock__lte=0, flagged="").count(),
            "review": items.exclude(flagged="").count(),
        }
        stale = timezone.now() - snap.imported_at > timedelta(hours=settings.KINO["STALE_INVENTORY_HOURS"])
    cmd_counts = dict(Command.objects.values_list("status").annotate(n=Count("id")))
    return render(
        request,
        "core/dashboard.html",
        _ctx(
            request,
            snap=snap,
            counts=counts,
            stale=stale,
            blocks=ManualBlock.objects.filter(active=True).count(),
            cmd_counts={label: cmd_counts.get(value, 0) for value, label in Command.Status.choices},
            pending_review=InventorySnapshot.objects.filter(status=InventorySnapshot.Status.REVIEW).count(),
            albums=Album.objects.all(),
        ),
    )


@login_required
def product_search(request):
    q = normalize_sku(request.GET.get("q", ""))
    if q:
        exact = Product.objects.filter(sku=q).first()
        if exact:
            return redirect("product_detail", sku=exact.sku)
    results = Product.objects.filter(sku__icontains=q)[:30] if q else []
    return render(request, "core/search.html", _ctx(request, q=q, results=results))


@login_required
def product_detail(request, sku):
    product = get_object_or_404(Product, sku=normalize_sku(sku))
    state = decisions.product_state(product)
    return render(
        request,
        "core/product.html",
        _ctx(
            request,
            product=product,
            state=state,
            images=product.images.select_related("drive_image"),
            commands=product.commands.select_related("album_image__album")[:20],
            history=product.manual_blocks.order_by("-created_at")[:10],
        ),
    )


@login_required
@role_required("Operador")
@require_POST
def product_block(request, sku):
    product = get_object_or_404(Product, sku=normalize_sku(sku))
    _, state, cmds = decisions.block_product(product, request.user, request.POST.get("reason", "")[:300])
    messages.success(request, f"{product.sku} bloqueado. Órdenes de retiro creadas: {len(cmds)}. Estado: pendiente hasta confirmar.")
    return redirect("product_detail", sku=product.sku)


@login_required
@role_required("Operador")
@require_POST
def product_release(request, sku):
    product = get_object_or_404(Product, sku=normalize_sku(sku))
    block, state, cmds = decisions.release_block(product, request.user)
    if not block:
        messages.info(request, "Este SKU no tenía bloqueo manual.")
    elif state.desired != "VISIBLE":
        messages.warning(request, f"Bloqueo liberado, pero la foto sigue oculta: {state.reason}.")
    else:
        messages.success(request, f"Bloqueo liberado. Órdenes de restauración creadas: {len(cmds)}.")
    return redirect("product_detail", sku=product.sku)


@login_required
@role_required("Supervisor")
def inventory_imports(request):
    if request.method == "POST" and request.FILES.get("excel"):
        f = request.FILES["excel"]
        try:
            snap, cmds = importer.import_inventory(f.file, f.name, actor=request.user)
            level = messages.SUCCESS if snap.status == InventorySnapshot.Status.VALID else messages.WARNING
            messages.add_message(request, level, f"{snap.get_status_display()}: {snap.row_count} filas, {len(cmds)} órdenes nuevas.")
        except importer.ExcelError as exc:
            messages.error(request, str(exc))
        return redirect("inventory_imports")
    return render(request, "core/imports.html", _ctx(request, snapshots=InventorySnapshot.objects.all()[:50]))


@login_required
@role_required("Supervisor")
@require_POST
def inventory_approve(request, pk):
    snap = get_object_or_404(InventorySnapshot, pk=pk)
    cmds = importer.approve_snapshot(snap, request.user)
    messages.success(request, f"Importación aprobada. Órdenes nuevas: {len(cmds)}.")
    return redirect("inventory_imports")


@login_required
def command_list(request):
    qs = Command.objects.select_related("product", "album_image__album", "album_image__drive_image", "requested_by")
    status = request.GET.get("status", "")
    if status:
        qs = qs.filter(status=status)
    sku = normalize_sku(request.GET.get("sku", ""))
    if sku:
        qs = qs.filter(product__sku__icontains=sku)
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    return render(
        request,
        "core/commands.html",
        _ctx(request, page=page, status=status, sku=sku, statuses=Command.Status.choices),
    )


@login_required
@role_required("Operador")
@require_POST
def command_confirm(request, pk):
    cmd = get_object_or_404(Command, pk=pk, status__in=Command.OPEN_STATUSES)
    worker.confirm_manually(cmd, request.user, request.POST.get("evidence", "")[:500])
    messages.success(request, "Orden confirmada.")
    return redirect(request.POST.get("next") or "command_list")


@login_required
@role_required("Supervisor")
@require_POST
def command_retry(request, pk):
    cmd = get_object_or_404(Command, pk=pk, status__in=[Command.Status.FAILED, Command.Status.NEEDS_HUMAN])
    cmd.status = Command.Status.PENDING
    cmd.save(update_fields=["status"])
    messages.success(request, "Orden puesta de nuevo en la cola.")
    return redirect("command_list")


@login_required
def album_list(request):
    albums = Album.objects.annotate(
        n_images=Count("album_images"),
        n_visible=Count("album_images", filter=Q(album_images__observed_state="VISIBLE")),
        n_pending=Count("album_images__commands", filter=Q(album_images__commands__status__in=Command.OPEN_STATUSES)),
    )
    return render(request, "core/albums.html", _ctx(request, albums=albums))
