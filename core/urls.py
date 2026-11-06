from django.urls import path

from core import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("buscar/", views.product_search, name="product_search"),
    path("ref/<str:sku>/", views.product_detail, name="product_detail"),
    path("ref/<str:sku>/retirar/", views.product_block, name="product_block"),
    path("ref/<str:sku>/liberar/", views.product_release, name="product_release"),
    path("inventario/", views.inventory_imports, name="inventory_imports"),
    path("inventario/<int:pk>/aprobar/", views.inventory_approve, name="inventory_approve"),
    path("ordenes/", views.command_list, name="command_list"),
    path("ordenes/<int:pk>/confirmar/", views.command_confirm, name="command_confirm"),
    path("ordenes/<int:pk>/reintentar/", views.command_retry, name="command_retry"),
    path("albumes/", views.album_list, name="album_list"),
]
