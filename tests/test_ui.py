"""Pruebas de la interfaz sin pantalla: recorre todas las pantallas y hace una venta completa."""
import os
from decimal import Decimal as D

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from micomercio.core.errores import ErrorNegocio
from micomercio.ui import tema
from micomercio.ui.paginas import venta as modulo_venta
from micomercio.ui.paginas.productos import DialogoCambioMasivo, DialogoProducto
from micomercio.ui.ventana import MENU, VentanaPrincipal


@pytest.fixture
def ventana(app, ctx, producto):
    v = VentanaPrincipal(ctx)
    v.reloj_copias.stop()
    v.show()
    yield v
    v.close()


def test_todas_las_pantallas_abren(ventana, ctx):
    ctx.caja.abrir(100000)
    assert list(ventana.paginas) == [clave for clave, *_ in MENU]
    for clave in ventana.paginas:
        ventana.ir(clave)
        assert ventana.pila.currentWidget() is ventana.paginas[clave]
    reportes = ventana.paginas["reportes"]
    for n in range(reportes.tipo.count()):
        reportes.tipo.setCurrentIndex(n)
    assert ventana.paginas["productos"].tabla.rowCount() == 1
    assert ventana.paginas["caja"].tabla.rowCount() == 1


def test_el_cajero_ve_un_menu_reducido(app, ctx):
    ctx.usuarios.crear("caja1", "Cajera", "clave-de-prueba", "cajero")
    ctx.usuarios.iniciar_sesion("caja1", "clave-de-prueba")
    v = VentanaPrincipal(ctx)
    v.reloj_copias.stop()
    assert list(v.paginas) == ["inicio", "venta", "productos", "clientes", "historial", "caja", "guia"]
    v.ir("productos")
    assert not v.paginas["productos"].b_nuevo.isVisibleTo(v.paginas["productos"])
    v.close()


def test_dialogo_de_producto_calcula_mientras_se_escribe(app, ctx):
    d = DialogoProducto(None, ctx)
    d.nombre.setText("Aceite 900 ml")
    d.costo.clear()
    QTest.keyClicks(d.costo, "10000")
    d.ganancia.clear()
    QTest.keyClicks(d.ganancia, "30")
    assert d.neto.text() == "14.285,71" and d.final.text() == "17.285,71"
    d.impuestos.setCurrentText("10,5")
    assert d.final.text() == "15.785,71"
    d.metodo.setCurrentIndex(d.metodo.findData("recargo"))
    assert d.neto.text() == "13.000,00"
    d.metodo.setCurrentIndex(d.metodo.findData("margen"))
    d.impuestos.setCurrentText("21")

    d.final.clear()
    QTest.keyClicks(d.final, "20000")          # precio escrito a mano
    assert d.manual and not d.aviso.isHidden() and "39,5 %" in d.aviso.text()
    d.recalcular_margen()
    assert d.ganancia.text() == "39,5"
    d.volver_automatico()
    assert not d.manual and d.aviso.isHidden() and d.final.text() == "20.000,00"

    d.ganancia.clear()
    QTest.keyClicks(d.ganancia, "100")         # margen imposible: avisa y no calcula
    assert d.final.text() == "" and "menor a 100" in d.error_precio.text()
    with pytest.raises(ErrorNegocio):
        d.guardar()
    d.ganancia.clear()
    QTest.keyClicks(d.ganancia, "30")
    d.guardar()
    assert ctx.productos.obtener(d.producto_id)["precio_final_cent"] == 1728571


def test_cambio_masivo_exige_vista_previa(app, ctx, producto, monkeypatch):
    d = DialogoCambioMasivo(None, ctx)
    assert not d.boton_guardar.isEnabled()
    QTest.keyClicks(d.valor, "10")
    d.previsualizar()
    assert d.boton_guardar.isEnabled() and d.tabla.rowCount() == 1
    QTest.keyClicks(d.valor, "0")              # cambió el dato: la vista previa ya no vale
    assert not d.boton_guardar.isEnabled()
    assert ctx.productos.obtener(producto)["costo_cent"] == 1000000


def test_venta_completa_con_lector(ventana, ctx, producto, monkeypatch):
    ctx.caja.abrir(0)
    ventana.ir("venta")
    pagina = ventana.paginas["venta"]

    # El lector de códigos escribe el código y envía Enter.
    for _ in range(2):
        QTest.keyClicks(pagina.buscador, "7790001000012")
        QTest.keyClick(pagina.buscador, Qt.Key_Return)
    assert len(pagina.carrito) == 1 and pagina.carrito[0]["cantidad"] == D(2)
    QTest.keyClicks(pagina.buscador, "3*A1")
    QTest.keyClick(pagina.buscador, Qt.Key_Return)
    assert pagina.carrito[0]["cantidad"] == D(5)
    assert pagina.l_total.text() == "$ 86.428,55"
    QTest.keyClicks(pagina.buscador, "no-existe")
    QTest.keyClick(pagina.buscador, Qt.Key_Return)
    assert "No se encontró" in pagina.mensaje.text()
    pagina.buscador.clear()
    QTest.keyClicks(pagina.buscador, "20*A1")   # más que el stock: no se agrega
    QTest.keyClick(pagina.buscador, Qt.Key_Return)
    assert pagina.carrito[0]["cantidad"] == D(5) and "No hay stock" in pagina.mensaje.text()
    pagina.sumar(-1)
    assert pagina.carrito[0]["cantidad"] == D(4)

    cobros = []

    class CobroFalso:
        def __init__(self, padre, medio, total):
            self.pago = {"medio": medio, "monto_cent": total, "estado": "confirmado"}
            self.vuelto_cent = 0

        def exec(self):
            cobros.append(self.pago)
            pagina.cobrar("efectivo")           # segunda pulsación mientras se cobra: se ignora
            return QDialog.Accepted

    monkeypatch.setattr(modulo_venta, "DialogoCobro", CobroFalso)
    monkeypatch.setattr(modulo_venta.DialogoVentaRegistrada, "exec", lambda self: QDialog.Accepted)
    pagina.cobrar("efectivo")
    assert len(cobros) == 1
    assert ctx.db.valor("SELECT COUNT(*) FROM ventas") == 1
    assert ctx.productos.obtener(producto)["stock_mil"] == 6000
    assert pagina.carrito == [] and pagina.l_total.text() == "$ 0,00"
    assert ventana.estado_caja.text() == "Caja principal: abierta"

    ventana.ir("historial")
    assert ventana.paginas["historial"].tabla.rowCount() == 1
    ventana.ir("inicio")
    assert ventana.paginas["inicio"].t_cobrado.valor.text() == "$ 69.142,84"
