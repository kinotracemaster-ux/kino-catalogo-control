"""Pruebas de los criterios de aceptación B y C (sección 14)."""
import io

from django.contrib.auth.models import Group, User
from django.test import TestCase, override_settings
from openpyxl import Workbook

from core.executor import worker
from core.models import (
    Album,
    AlbumImage,
    Command,
    DriveImage,
    InventorySnapshot,
    Product,
    ProductImage,
    Visibility,
)
from core.services import decisions, importer


def excel(rows, headers=("Referencia", "Saldo")):
    wb = Workbook()
    ws = wb.active
    ws.append(list(headers))
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


class Base(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("operador", password="x" * 12)
        self.album = Album.objects.create(
            name="JOEFOX", share_url="https://photos.app.goo.gl/prueba", owner_account="ventas@ejemplo.com"
        )
        # catálogo base de 20 SKU para que los umbrales tengan sentido
        self.base = [(f"SKU-{i:02d}", 5) for i in range(20)]
        self.product = Product.objects.create(sku="JF-2359", brand="JOEFOX")
        img = DriveImage.objects.create(drive_file_id="d1", filename="JF-2359.jpg")
        ProductImage.objects.create(product=self.product, drive_image=img)
        self.ai = AlbumImage.objects.create(album=self.album, drive_image=img, observed_state=Visibility.VISIBLE)

    def load(self, extra, name="inv.xlsx"):
        return importer.import_inventory(excel(self.base + extra), name)


class DecisionRuleTests(TestCase):
    def test_matriz(self):
        f = decisions.desired_visibility
        self.assertEqual(f(10, True, False), "VISIBLE")
        self.assertEqual(f(0, True, False), "HIDDEN")
        self.assertEqual(f(10, True, True), "HIDDEN")
        self.assertIsNone(f(None, False, False))
        self.assertEqual(f(None, False, True), "HIDDEN")


class InventoryTests(Base):
    def test_stock_a_cero_genera_retiro(self):
        self.load([("JF-2359", 5)])
        snap, cmds = self.load([("JF-2359", 0)], "inv2.xlsx")
        self.assertEqual(snap.status, InventorySnapshot.Status.VALID)
        self.assertEqual([c.action for c in cmds], [Command.Action.REMOVE])

    def test_mismo_archivo_no_repite_ordenes(self):
        data = excel(self.base + [("JF-2359", 0)]).getvalue()
        _, c1 = importer.import_inventory(io.BytesIO(data), "a.xlsx")
        snap, c2 = importer.import_inventory(io.BytesIO(data), "a.xlsx")
        self.assertEqual(len(c1), 1)
        self.assertEqual(snap.status, InventorySnapshot.Status.DUPLICATE)
        self.assertEqual(c2, [])

    def test_ausencia_no_es_cero(self):
        self.load([("JF-2359", 5)])
        _, cmds = self.load([], "sin-jf.xlsx")
        self.assertEqual(cmds, [])
        self.assertIn("SIN DATO", decisions.product_state(self.product).reason)

    def test_cambio_masivo_queda_en_revision(self):
        self.load([("JF-2359", 5)])
        agotado = [(s, 0) for s, _ in self.base] + [("JF-2359", 0)]
        snap, cmds = importer.import_inventory(excel(agotado), "masivo.xlsx")
        self.assertEqual(snap.status, InventorySnapshot.Status.REVIEW)
        self.assertEqual(cmds, [])
        cmds = importer.approve_snapshot(snap, self.user)
        self.assertEqual(len(cmds), 1)

    def test_sku_conserva_ceros_y_guiones(self):
        self.load([("  0815b-1 ", 3), (9051, 2)])
        self.assertTrue(Product.objects.filter(sku="0815B-1").exists())
        self.assertTrue(Product.objects.filter(sku="9051").exists())

    def test_negativo_y_duplicado_quedan_en_revision(self):
        self.load([("JF-2359", -1), ("DUP", 1), ("DUP", 2)])
        snap = InventorySnapshot.latest_valid()
        flagged = set(snap.items.exclude(flagged="").values_list("product__sku", flat=True))
        self.assertEqual(flagged, {"JF-2359", "DUP"})

    def test_columna_faltante_rechaza(self):
        snap, _ = importer.import_inventory(excel([("A", 1)], headers=("Codigo", "Cantidad")), "malo.xlsx")
        self.assertEqual(snap.status, InventorySnapshot.Status.REJECTED)


class ManualControlTests(Base):
    def test_bloqueo_prevalece_sobre_excel(self):
        self.load([("JF-2359", 5)])
        _, _, cmds = decisions.block_product(self.product, self.user, "prueba")
        self.assertEqual(len(cmds), 1)
        worker.confirm_manually(cmds[0], self.user)
        _, again = self.load([("JF-2359", 50)], "nuevo.xlsx")
        self.assertEqual(again, [])
        self.ai.refresh_from_db()
        self.assertEqual(self.ai.desired_state, Visibility.HIDDEN)

    def test_liberar_con_stock_restaura(self):
        self.load([("JF-2359", 5)])
        _, _, cmds = decisions.block_product(self.product, self.user)
        worker.confirm_manually(cmds[0], self.user)
        _, state, cmds = decisions.release_block(self.product, self.user)
        self.assertEqual(state.desired, Visibility.VISIBLE)
        self.assertEqual([c.action for c in cmds], [Command.Action.ADD])

    def test_liberar_con_stock_cero_sigue_oculto(self):
        self.load([("JF-2359", 0)])
        cmd = Command.objects.get()
        worker.confirm_manually(cmd, self.user)
        decisions.block_product(self.product, self.user)
        _, state, cmds = decisions.release_block(self.product, self.user)
        self.assertEqual(state.desired, Visibility.HIDDEN)
        self.assertEqual(cmds, [])

    def test_orden_obsoleta_se_cancela(self):
        self.load([("JF-2359", 0)])
        remove = Command.objects.get()
        self.load([("JF-2359", 8)], "vuelve.xlsx")
        remove.refresh_from_db()
        self.assertEqual(remove.status, Command.Status.CANCELED)

    def test_un_solo_bloqueo_activo(self):
        decisions.block_product(self.product, self.user)
        decisions.block_product(self.product, self.user)
        self.assertEqual(self.product.manual_blocks.filter(active=True).count(), 1)


class PanelTests(Base):
    def setUp(self):
        super().setUp()
        Group.objects.create(name="Operador")
        self.user.groups.add(Group.objects.get(name="Operador"))
        self.client.force_login(self.user)

    def test_paginas_cargan(self):
        for url in ["/", "/buscar/?q=jf", "/ref/JF-2359/", "/ordenes/", "/albumes/"]:
            self.assertEqual(self.client.get(url, follow=True).status_code, 200, url)

    def test_retirar_desde_panel(self):
        r = self.client.post("/ref/JF-2359/retirar/", {"reason": "prueba"}, follow=True)
        self.assertContains(r, "bloqueado")
        self.assertTrue(self.product.manual_blocks.filter(active=True).exists())

    def test_operador_no_importa_excel(self):
        self.assertEqual(self.client.get("/inventario/").status_code, 403)


@override_settings(KINO={**__import__("django.conf").conf.settings.KINO, "PHOTOS_EXECUTOR": "assisted"})
class WorkerTests(Base):
    def test_modo_asistido_no_ejecuta(self):
        self.load([("JF-2359", 0)])
        self.assertEqual(worker.run_once(), 0)
        self.assertEqual(Command.objects.get().status, Command.Status.PENDING)
