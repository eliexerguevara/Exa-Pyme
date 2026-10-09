"""Devoluciones parciales y pago combinado."""
import uuid
from decimal import Decimal as D

import pytest

from conftest import vender
from micomercio.core.errores import ErrorNegocio, PermisoDenegado
from micomercio.integraciones.arca import impreso
from micomercio.servicios import tickets
from micomercio.servicios.ventas import estado_pago
from test_arca import fiscal  # noqa: F401  (fixture: comercio con facturación activa)

PRECIO = 1728571


def item(ctx, venta):
    return ctx.ventas.items(venta)[0]["id"]


# ---- devoluciones parciales ---------------------------------------------------
def test_devolucion_parcial_devuelve_stock_y_dinero(ctx, producto):
    caja = ctx.caja.abrir(0)
    venta = vender(ctx, producto, "3", descuento_cent=100000)          # total 50.857,13
    calculo = ctx.ventas.calcular_devolucion(venta, {item(ctx, venta): D(1)})
    assert calculo["total_cent"] == 1695238 and calculo["neto_cent"] + calculo["impuestos_cent"] == 1695238
    assert ctx.productos.obtener(producto)["stock_mil"] == 7000        # calcular no guarda nada

    devolucion = ctx.ventas.devolver(venta, {item(ctx, venta): D(1)}, "No le gustó")
    assert ctx.productos.obtener(producto)["stock_mil"] == 8000
    assert ctx.inventario.movimientos(producto)[0]["tipo"] == "devolucion"
    v = ctx.ventas.obtener(venta)
    assert v["estado"] == "completada" and estado_pago(v) == "pagada"   # la venta sigue vigente
    r = ctx.caja.resumen(caja)
    assert r["devoluciones_cent"] == 1695238 and r["cobrado_cent"]["efectivo"] == 5085713 - 1695238
    assert r["efectivo_esperado_cent"] == 5085713 - 1695238
    assert ctx.ventas.devuelto(venta) == {item(ctx, venta): {"cantidad_mil": 1000, "total_cent": 1695238}}
    assert ctx.ventas.devoluciones(venta)[0]["id"] == devolucion
    assert "Devolución efectivo" in tickets.html_ticket(ctx, venta)

    c = ctx.reportes.cifras("2000-01-01", "2999-01-01")
    assert c["facturacion_cent"] == 5085713 - 1695238 and c["parciales_cent"] == 1695238
    assert c["costo_cent"] == 2000000 and c["cobrado_cent"] == 5085713 - 1695238
    assert ctx.reportes.generar("mas_vendidos", "2000-01-01", "2999-01-01").filas[0][2] == 2000
    assert any(f[2] == "Devolución parcial" for f in ctx.reportes.generar("descuentos", "2000-01-01", "2999-01-01").filas)

    with pytest.raises(ErrorNegocio, match="quedan 2"):                # no se puede devolver más de lo que queda
        ctx.ventas.devolver(venta, {item(ctx, venta): D(3)}, "x")
    ctx.ventas.devolver(venta, {item(ctx, venta): D(2)}, "Devuelve el resto", "tarjeta")
    assert sum(d["total_cent"] for d in ctx.ventas.devoluciones(venta)) == 5085713   # ni un centavo de más ni de menos
    assert ctx.productos.obtener(producto)["stock_mil"] == 10000
    with pytest.raises(ErrorNegocio):
        ctx.ventas.devolver(venta, {item(ctx, venta): D(1)}, "x")


def test_anular_despues_de_una_devolucion_parcial(ctx, producto):
    caja = ctx.caja.abrir(0)
    venta = vender(ctx, producto, "4", medio="tarjeta")
    ctx.ventas.devolver(venta, {item(ctx, venta): D(1)}, "Roto", "efectivo")     # se devolvió en efectivo
    ctx.ventas.anular(venta, "Se arrepintió")
    assert ctx.productos.obtener(producto)["stock_mil"] == 10000       # solo vuelve lo que faltaba
    r = ctx.caja.resumen(caja)
    assert r["devoluciones_cent"] == 4 * PRECIO and r["cobrado_total_cent"] == 0
    assert r["devoluciones_por_medio_cent"] == {"efectivo": PRECIO, "tarjeta": 3 * PRECIO, "transferencia": 0, "mercadopago": 0}
    assert ctx.reportes.cifras("2000-01-01", "2999-01-01")["facturacion_cent"] == 0


def test_validaciones_de_la_devolucion(ctx, producto):
    ctx.caja.abrir(0)
    pendiente = vender(ctx, producto, medio="transferencia", estado="pendiente")
    with pytest.raises(ErrorNegocio, match="tiene que estar cobrada"):
        ctx.ventas.devolver(pendiente, {item(ctx, pendiente): D(1)}, "x")
    venta = vender(ctx, producto, "2")
    for cantidades, motivo in [({}, "x"), ({item(ctx, venta): D(0)}, "x"), ({item(ctx, venta): D(1)}, " "),
                               ({item(ctx, venta): D(-1)}, "x"), ({item(ctx, pendiente): D(1)}, "x")]:
        with pytest.raises(ErrorNegocio):
            ctx.ventas.devolver(venta, cantidades, motivo)
    with pytest.raises(ErrorNegocio):
        ctx.ventas.devolver(venta, {item(ctx, venta): D(1)}, "x", "cheque")
    ctx.usuarios.crear("caja1", "Cajera", "clave-de-prueba", "cajero")
    ctx.usuarios.iniciar_sesion("caja1", "clave-de-prueba")
    with pytest.raises(PermisoDenegado):
        ctx.ventas.devolver(venta, {item(ctx, venta): D(1)}, "x")
    ctx.usuarios.iniciar_sesion("admin", "clave-de-prueba")
    ctx.caja.cerrar(ctx.caja.resumen(ctx.caja.abierta()["id"])["efectivo_esperado_cent"])
    with pytest.raises(ErrorNegocio, match="caja está cerrada"):
        ctx.ventas.devolver(venta, {item(ctx, venta): D(1)}, "x")
    assert ctx.db.valor("SELECT COUNT(*) FROM devoluciones") == 0 and ctx.productos.obtener(producto)["stock_mil"] == 7000


def test_devolucion_de_producto_por_peso(ctx):
    ctx.caja.abrir(0)
    queso = ctx.productos.crear({"nombre": "Queso", "unidad": "kg", "costo": D(5000), "impuesto_pct": D(21),
                                 "ganancia_pct": D(30), "stock": D(10)})
    venta = vender(ctx, queso, "1.5")
    total = ctx.ventas.obtener(venta)["total_cent"]
    ctx.ventas.devolver(venta, {item(ctx, venta): D("0.5")}, "Pesaba de más")
    ctx.ventas.devolver(venta, {item(ctx, venta): D("1")}, "El resto")
    assert sum(d["total_cent"] for d in ctx.ventas.devoluciones(venta)) == total
    assert ctx.productos.obtener(queso)["stock_mil"] == 10000


# ---- devolución de una venta facturada ---------------------------------------
def test_venta_facturada_se_devuelve_con_nota_de_credito_parcial(fiscal, ctx, producto):  # noqa: F811
    servicio, simulado = fiscal
    venta = vender(ctx, producto, "3")
    factura = servicio.autorizar_venta(venta)
    with pytest.raises(ErrorNegocio, match="nota de crédito"):         # sin nota de crédito no se puede
        ctx.ventas.devolver(venta, {item(ctx, venta): D(1)}, "x")

    nota = servicio.nota_credito_parcial(venta, {item(ctx, venta): D(1)}, "Falla de fábrica", "efectivo")
    assert (nota["estado"], int(nota["tipo"]), nota["parcial"], nota["total_cent"]) == ("autorizada", 8, 1, PRECIO)
    assert nota["neto_cent"] + nota["iva_cent"] == PRECIO and nota["devolucion_id"] is not None
    assert "<ImpTotal>17285.71</ImpTotal>" in simulado.pedidos[1] and "<CbtesAsoc><CbteAsoc><Tipo>6</Tipo>" in simulado.pedidos[1]
    v = ctx.ventas.obtener(venta)
    assert (v["estado"], v["estado_fiscal"]) == ("completada", "autorizada")
    assert ctx.productos.obtener(producto)["stock_mil"] == 8000
    assert "nota de crédito B 00003-00000001" in ctx.ventas.devoluciones(venta)[0]["motivo"]
    html = impreso.html_comprobante(ctx, nota["id"])
    assert "NOTA DE CRÉDITO B" in html and "1 unidad x" in html and "3 unidad x" not in html
    assert "1 nota(s) de crédito parcial(es)" in servicio.ventas("2000-01-01", "2999-01-01")[0]["texto"]
    assert impreso.html_comprobante(ctx, factura["id"])                # la factura original sigue imprimible

    with pytest.raises(ErrorNegocio, match="parciales"):               # ya no corresponde una nota por el total
        servicio.emitir_nota_credito(venta, "todo")
    servicio.nota_credito_parcial(venta, {item(ctx, venta): D(2)}, "Devuelve el resto")
    assert ctx.productos.obtener(producto)["stock_mil"] == 10000
    assert sum(n["total_cent"] for n in servicio.ventas("2000-01-01", "2999-01-01")[0]["parciales"]) == 3 * PRECIO


def test_corte_entre_la_nota_y_la_devolucion_no_duplica(fiscal, ctx, producto, monkeypatch):  # noqa: F811
    servicio, simulado = fiscal
    venta = vender(ctx, producto, "2")
    servicio.autorizar_venta(venta)
    original = ctx.ventas.devolver
    monkeypatch.setattr(ctx.ventas, "devolver", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("corte de luz")))
    with pytest.raises(RuntimeError):                                  # ARCA autorizó la nota, pero no se llegó a registrar
        servicio.nota_credito_parcial(venta, {item(ctx, venta): D(1)}, "Roto")
    assert ctx.db.valor("SELECT COUNT(*) FROM devoluciones") == 0
    monkeypatch.setattr(ctx.ventas, "devolver", original)

    nota = servicio.nota_credito_parcial(venta, {item(ctx, venta): D(2)}, "otro intento")   # completa la que quedó colgada
    assert nota["total_cent"] == PRECIO and nota["devolucion_id"] is not None
    assert simulado.llamadas.count("FECAESolicitar") == 2              # factura + una sola nota de crédito
    assert ctx.ventas.devuelto(venta)[item(ctx, venta)]["cantidad_mil"] == 1000


# ---- pago combinado -----------------------------------------------------------
def test_pago_combinado(ctx, producto):
    caja = ctx.caja.abrir(0)
    p = ctx.productos.obtener(producto)
    registrar = lambda pagos: ctx.ventas.registrar(  # noqa: E731
        uuid.uuid4().hex, [{"producto_id": producto, "cantidad": D(1), "precio_unit_cent": p["precio_final_cent"]}], pagos)
    venta = registrar([{"medio": "efectivo", "monto_cent": 1000000}, {"medio": "tarjeta", "monto_cent": 500000},
                       {"medio": "transferencia", "monto_cent": 228571, "estado": "pendiente"}])
    r = ctx.caja.resumen(caja)
    assert r["cobrado_cent"] == {"efectivo": 1000000, "tarjeta": 500000, "transferencia": 0, "mercadopago": 0}
    assert r["pendientes_cent"] == 228571 and r["efectivo_esperado_cent"] == 1000000
    assert estado_pago(ctx.ventas.obtener(venta)) == "pendiente"
    ctx.ventas.confirmar_pago(ctx.ventas.pagos(venta)[2]["id"])
    assert estado_pago(ctx.ventas.obtener(venta)) == "pagada"
    html = tickets.html_ticket(ctx, venta)
    assert "Efectivo" in html and "Tarjeta" in html and "Transferencia" in html
    with pytest.raises(ErrorNegocio, match="no coincide"):             # los importes tienen que sumar el total
        registrar([{"medio": "efectivo", "monto_cent": 1000000}, {"medio": "tarjeta", "monto_cent": 500000}])
    ctx.ventas.anular(venta, "Prueba")
    assert ctx.caja.resumen(caja)["devoluciones_por_medio_cent"] == {"efectivo": 1000000, "tarjeta": 500000,
                                                                      "transferencia": 228571, "mercadopago": 0}


# ---- pantallas ----------------------------------------------------------------
def test_dialogo_de_pago_combinado(app, ctx):
    from micomercio.ui.paginas.venta import DialogoPagoCombinado

    d = DialogoPagoCombinado(None, 1728571, con_qr=True)
    assert "17.285,71" in d.falta.text()
    d.campos["efectivo"].setText("10000")
    d.actualizar()
    assert d.falta.text() == "$ 7.285,71"
    with pytest.raises(ErrorNegocio):
        d.guardar()
    d.resto("mercadopago")
    assert d.campos["mercadopago"].text() == "7.285,71" and "completo" in d.falta.text()
    d.guardar()
    assert d.usar_qr and d.pagos == [{"medio": "efectivo", "monto_cent": 1000000, "estado": "confirmado"},
                                     {"medio": "mercadopago", "monto_cent": 728571, "estado": "pendiente"}]
    d.campos["tarjeta"].setText("1")
    d.actualizar()
    assert "Sobran" in d.falta.text()
    assert DialogoPagoCombinado(None, 100).estados["mercadopago"].itemData(0) == "pendiente"   # sin integración no hay QR


def test_dialogo_de_devolucion(app, ctx, producto, monkeypatch):
    from micomercio.ui.paginas import historial

    ctx.caja.abrir(0)
    venta = vender(ctx, producto, "3")
    monkeypatch.setattr(historial, "confirmar", lambda *a, **k: True)
    d = historial.DialogoDevolucion(None, ctx, venta)
    campo = d.campos[item(ctx, venta)]
    campo.setText("5")
    d.calcular()
    assert "quedan 3" in d.importe.text()
    d.todo(campo, 2000)
    assert d.importe.text() == "$ 34.571,42" and d.medio.currentData() == "efectivo"
    with pytest.raises(ErrorNegocio, match="motivo"):
        d.guardar()
    d.motivo.setText("Cambio de opinión")
    d.guardar()
    assert ctx.productos.obtener(producto)["stock_mil"] == 9000 and d.nota is None
    detalle = historial.DialogoVenta(None, ctx, venta)
    assert detalle.items.item(0, 3).text() == "2" and detalle.b_devolver.isEnabled()
    assert list(historial.DialogoDevolucion(None, ctx, venta).campos) == [item(ctx, venta)]
    ctx.ventas.devolver(venta, {item(ctx, venta): D(1)}, "Resto")
    assert historial.DialogoDevolucion(None, ctx, venta).campos == {}
