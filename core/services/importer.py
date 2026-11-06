"""Importador y validador del Excel de inventario (sección 5 y 11).

Nunca interpreta la ausencia de un SKU como stock cero, nunca ejecuta macros
(openpyxl en modo solo lectura y solo valores) y no genera órdenes repetidas
si llega el mismo archivo dos veces.
"""
import hashlib
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from openpyxl import load_workbook

from core.models import (
    AuditEvent,
    ExcelMapping,
    InventoryItem,
    InventorySnapshot,
    Product,
    normalize_sku,
)
from core.services import decisions

ALLOWED_EXT = (".xlsx", ".xlsm")


class ExcelError(Exception):
    pass


@dataclass
class ParsedRow:
    sku: str
    stock: Decimal | None
    brand: str = ""
    name: str = ""
    warehouse: str = ""
    flag: str = ""


@dataclass
class ParseResult:
    rows: dict = field(default_factory=dict)  # sku -> ParsedRow
    errors: list = field(default_factory=list)
    total_rows: int = 0


def _header_index(headers, wanted, required=True):
    if not wanted:
        return None
    norm = {str(h).strip().lower(): i for i, h in enumerate(headers) if h is not None}
    idx = norm.get(wanted.strip().lower())
    if idx is None and required:
        raise ExcelError(f"No encuentro la columna «{wanted}». Encabezados: {', '.join(str(h) for h in headers if h)}")
    return idx


def _to_number(value):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        return Decimal(str(value).replace(",", ".").strip())
    except InvalidOperation:
        return "invalid"


def parse_workbook(path_or_file, mapping: ExcelMapping) -> ParseResult:
    try:
        wb = load_workbook(path_or_file, read_only=True, data_only=True, keep_vba=False)
    except Exception as exc:  # archivo corrupto o no es Excel
        raise ExcelError(f"No pude abrir el Excel: {exc}") from exc

    if mapping.sheet_name:
        if mapping.sheet_name not in wb.sheetnames:
            raise ExcelError(f"No existe la hoja «{mapping.sheet_name}». Hojas: {', '.join(wb.sheetnames)}")
        ws = wb[mapping.sheet_name]
    else:
        ws = wb[wb.sheetnames[0]]

    rows = ws.iter_rows(values_only=True)
    headers = None
    for _ in range(mapping.header_row):
        headers = next(rows, None)
    if not headers:
        raise ExcelError("El Excel está vacío o la fila de encabezados no existe.")

    i_sku = _header_index(headers, mapping.sku_column)
    i_stock = _header_index(headers, mapping.stock_column)
    i_brand = _header_index(headers, mapping.brand_column, required=False)
    i_name = _header_index(headers, mapping.name_column, required=False)
    i_wh = _header_index(headers, mapping.warehouse_column, required=bool(mapping.warehouse_column))
    counted = mapping.warehouse_list()

    result = ParseResult()
    for line_no, row in enumerate(rows, start=mapping.header_row + 1):
        if row is None or all(c is None for c in row):
            continue
        result.total_rows += 1
        sku = normalize_sku(row[i_sku] if i_sku < len(row) else None)
        if not sku:
            result.errors.append(f"Fila {line_no}: SKU vacío")
            continue
        wh = str(row[i_wh]).strip().upper() if i_wh is not None and row[i_wh] is not None else ""
        if counted and wh not in counted:
            continue
        stock = _to_number(row[i_stock] if i_stock < len(row) else None)
        flag = ""
        if stock == "invalid":
            flag, stock = f"cantidad no numérica en fila {line_no}", None
        elif stock is None:
            flag = f"cantidad vacía en fila {line_no}"
        elif stock < 0:
            flag = f"cantidad negativa ({stock}) en fila {line_no}"

        new = ParsedRow(
            sku=sku,
            stock=stock,
            brand=str(row[i_brand]).strip() if i_brand is not None and row[i_brand] else "",
            name=str(row[i_name]).strip() if i_name is not None and row[i_name] else "",
            warehouse=wh,
            flag=flag,
        )
        prev = result.rows.get(sku)
        if prev is None:
            result.rows[sku] = new
        elif mapping.sum_warehouses and not prev.flag and not new.flag:
            prev.stock += new.stock
            prev.warehouse = ",".join(filter(None, [prev.warehouse, wh]))
        else:
            prev.flag = prev.flag or new.flag or f"SKU duplicado sin regla de suma (fila {line_no})"
    return result


def file_sha256(fileobj):
    h = hashlib.sha256()
    fileobj.seek(0)
    for chunk in iter(lambda: fileobj.read(1024 * 1024), b""):
        h.update(chunk)
    fileobj.seek(0)
    return h.hexdigest()


def import_inventory(fileobj, filename, actor=None, source="upload", drive_file_id="", cutoff_at=None):
    """Importa un Excel. Devuelve (snapshot, órdenes_creadas)."""
    cfg = settings.KINO
    if not filename.lower().endswith(ALLOWED_EXT):
        raise ExcelError("Solo se aceptan archivos .xlsx")
    fileobj.seek(0, 2)
    size_mb = fileobj.tell() / (1024 * 1024)
    fileobj.seek(0)
    if size_mb > cfg["MAX_EXCEL_MB"]:
        raise ExcelError(f"El archivo pesa {size_mb:.1f} MB; el límite es {cfg['MAX_EXCEL_MB']} MB")

    digest = file_sha256(fileobj)
    if InventorySnapshot.objects.filter(file_hash=digest).exclude(status=InventorySnapshot.Status.REJECTED).exists():
        snap = InventorySnapshot.objects.create(
            source=source, filename=filename, drive_file_id=drive_file_id, file_hash=digest,
            imported_by=actor if getattr(actor, "pk", None) else None,
            status=InventorySnapshot.Status.DUPLICATE, error_summary="Mismo archivo ya importado; sin cambios.",
        )
        return snap, []

    mapping = ExcelMapping.objects.filter(active=True).first() or ExcelMapping.objects.create()
    previous = InventorySnapshot.latest_valid()
    if previous and cutoff_at and previous.source_cutoff_at and cutoff_at <= previous.source_cutoff_at:
        raise ExcelError("Este Excel es más viejo que el último inventario aceptado.")

    try:
        parsed = parse_workbook(fileobj, mapping)
    except ExcelError as exc:
        snap = InventorySnapshot.objects.create(
            source=source, filename=filename, drive_file_id=drive_file_id, file_hash=digest,
            imported_by=actor if getattr(actor, "pk", None) else None,
            status=InventorySnapshot.Status.REJECTED, error_summary=str(exc),
        )
        AuditEvent.log(actor, "IMPORT_REJECTED", filename, after={"error": str(exc)})
        return snap, []

    if not parsed.rows:
        status, notes = InventorySnapshot.Status.REJECTED, ["El Excel no tiene filas con SKU."]
    else:
        status, notes = InventorySnapshot.Status.VALID, []

    # Umbrales de seguridad frente al último inventario válido.
    if previous and status == InventorySnapshot.Status.VALID:
        prev_items = {i.product.sku: i.stock for i in previous.items.select_related("product")}
        if prev_items:
            missing = [s for s in prev_items if s not in parsed.rows]
            missing_pct = 100 * len(missing) / len(prev_items)
            sold_out = [
                s for s, st in prev_items.items()
                if st and st > 0 and s in parsed.rows and parsed.rows[s].stock is not None and parsed.rows[s].stock <= 0
            ]
            sold_out_pct = 100 * len(sold_out) / len(prev_items)
            if missing_pct > cfg["MAX_MISSING_SKU_PCT"]:
                status = InventorySnapshot.Status.REVIEW
                notes.append(f"Faltan {len(missing)} SKU ({missing_pct:.1f} %) frente al último inventario.")
            if sold_out_pct > cfg["MAX_SOLD_OUT_PCT"]:
                status = InventorySnapshot.Status.REVIEW
                notes.append(f"{len(sold_out)} SKU ({sold_out_pct:.1f} %) pasan a agotado en un solo archivo.")

    notes.extend(parsed.errors[:50])
    flagged = [r for r in parsed.rows.values() if r.flag]
    if flagged:
        notes.append(f"{len(flagged)} SKU quedaron en revisión (no se tocan sus fotos).")

    with transaction.atomic():
        snap = InventorySnapshot.objects.create(
            source=source, filename=filename, drive_file_id=drive_file_id, file_hash=digest,
            source_cutoff_at=cutoff_at, imported_by=actor if getattr(actor, "pk", None) else None,
            status=status, row_count=parsed.total_rows, error_summary="\n".join(notes),
        )
        for row in parsed.rows.values():
            product, _ = Product.objects.get_or_create(sku=row.sku, defaults={"brand": row.brand, "name": row.name})
            InventoryItem.objects.create(
                snapshot=snap, product=product, stock=row.stock, warehouse_scope=row.warehouse, flagged=row.flag
            )
        AuditEvent.log(actor, "IMPORT", filename, after={"status": status, "rows": parsed.total_rows})

    commands = []
    if status == InventorySnapshot.Status.VALID:
        commands = decisions.recalculate_all(snap, actor)
    return snap, commands


def approve_snapshot(snapshot, actor):
    """Un supervisor aprueba una importación que quedó en revisión por cambios masivos."""
    if snapshot.status != InventorySnapshot.Status.REVIEW:
        return []
    snapshot.status = InventorySnapshot.Status.VALID
    snapshot.approved_by = actor
    snapshot.save(update_fields=["status", "approved_by"])
    AuditEvent.log(actor, "IMPORT_APPROVED", snapshot.filename)
    return decisions.recalculate_all(snapshot, actor)
