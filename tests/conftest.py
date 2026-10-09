import os
import sys
from decimal import Decimal
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["EXAPYME_SIN_ACTUALIZACIONES"] = "1"  # las pruebas no consultan GitHub

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from micomercio.db import BaseDatos  # noqa: E402
from micomercio.servicios import Contexto  # noqa: E402


@pytest.fixture(scope="session")
def app():
    from PySide6.QtWidgets import QApplication

    from micomercio.ui import tema

    aplicacion = QApplication.instance() or QApplication([])
    aplicacion.setStyleSheet(tema.HOJA_DE_ESTILO)
    yield aplicacion
    # Cierre ordenado: las ventanas, imágenes e hilos de Qt deben destruirse antes que la aplicación,
    # y no durante el apagado del intérprete.
    import gc

    gc.collect()
    for ventana in aplicacion.topLevelWidgets():
        ventana.close()
        ventana.deleteLater()
    for _ in range(3):
        aplicacion.sendPostedEvents(None, 0)
        aplicacion.processEvents()
    gc.collect()


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("EXAPYME_DATOS", str(tmp_path / "datos"))
    db = BaseDatos(tmp_path / "datos" / "micomercio.db")
    contexto = Contexto(db)
    contexto.usuarios.crear("admin", "Administrador", "clave-de-prueba")
    contexto.usuarios.iniciar_sesion("admin", "clave-de-prueba")
    yield contexto
    db.cerrar()


@pytest.fixture
def producto(ctx):
    """Producto del ejemplo: costo 10.000, impuestos 21 %, ganancia 30 % -> final 17.285,71. Stock 10."""
    return ctx.productos.crear({
        "codigo": "A1", "codigo_barras": "7790001000012", "nombre": "Yerba 1 kg", "categoria": "Almacén",
        "costo": Decimal("10000"), "impuesto_pct": Decimal("21"), "ganancia_pct": Decimal("30"),
        "stock": Decimal("10"), "stock_minimo": Decimal("2"),
    })


def vender(ctx, producto_id, cantidad="1", medio="efectivo", estado="confirmado", descuento_cent=0, uuid=None):
    import uuid as _uuid

    from micomercio.servicios.ventas import calcular_totales
    from micomercio.core.dinero import a_milesimas

    p = ctx.productos.obtener(producto_id)
    total = calcular_totales(
        [{"cantidad_mil": a_milesimas(cantidad), "precio_unit_cent": p["precio_final_cent"], "impuesto_pct": p["impuesto_pct"]}],
        descuento_cent,
    )["total_cent"]
    return ctx.ventas.registrar(
        uuid or str(_uuid.uuid4()),
        [{"producto_id": producto_id, "cantidad": Decimal(cantidad), "precio_unit_cent": p["precio_final_cent"]}],
        [{"medio": medio, "monto_cent": total, "estado": estado}],
        descuento_cent=descuento_cent,
    )
