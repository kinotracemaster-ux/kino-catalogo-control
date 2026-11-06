from django.contrib import admin

from core import models


class ProductImageInline(admin.TabularInline):
    model = models.ProductImage
    extra = 0
    raw_id_fields = ["drive_image"]


@admin.register(models.Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ["sku", "brand", "name", "active"]
    search_fields = ["sku", "name"]
    list_filter = ["brand", "active"]
    inlines = [ProductImageInline]


@admin.register(models.ExcelMapping)
class ExcelMappingAdmin(admin.ModelAdmin):
    list_display = ["name", "active", "sheet_name", "sku_column", "stock_column", "warehouse_column"]


@admin.register(models.Album)
class AlbumAdmin(admin.ModelAdmin):
    list_display = ["name", "owner_account", "authorized", "paused", "last_verified_at"]
    list_filter = ["authorized", "paused"]

    def get_readonly_fields(self, request, obj=None):
        return ["share_url"] if obj else []  # el enlace original no se cambia una vez registrado


@admin.register(models.AlbumImage)
class AlbumImageAdmin(admin.ModelAdmin):
    list_display = ["album", "drive_image", "desired_state", "observed_state", "mapping_verified", "observed_at"]
    list_filter = ["album", "desired_state", "observed_state", "mapping_verified"]
    raw_id_fields = ["drive_image"]
    search_fields = ["drive_image__filename"]


@admin.register(models.DriveImage)
class DriveImageAdmin(admin.ModelAdmin):
    list_display = ["filename", "folder_path", "active", "last_seen_at"]
    search_fields = ["filename", "drive_file_id"]
    list_filter = ["active"]


@admin.register(models.InventorySnapshot)
class SnapshotAdmin(admin.ModelAdmin):
    list_display = ["filename", "status", "row_count", "imported_at", "source"]
    list_filter = ["status", "source"]
    readonly_fields = [f.name for f in models.InventorySnapshot._meta.fields]


@admin.register(models.ManualBlock)
class ManualBlockAdmin(admin.ModelAdmin):
    list_display = ["product", "active", "reason", "created_by", "created_at", "cleared_at"]
    list_filter = ["active"]


@admin.register(models.Command)
class CommandAdmin(admin.ModelAdmin):
    list_display = ["id", "action", "source", "product", "status", "attempts", "created_at", "error_code"]
    list_filter = ["status", "action", "source"]


@admin.register(models.AuditEvent)
class AuditAdmin(admin.ModelAdmin):
    list_display = ["created_at", "actor", "event_type", "target"]
    list_filter = ["event_type"]

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
