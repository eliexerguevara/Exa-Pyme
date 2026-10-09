"""Cobros con QR contra un Mercado Pago simulado (mismas rutas y respuestas que la API de Orders)."""
import json

import pytest

from conftest import vender
from micomercio.core.errores import ErrorNegocio, PermisoDenegado
from micomercio.integraciones import mercadopago as mp
from micomercio.servicios.ventas import estado_pago

TOKEN = "APP_USR-1234567890-prueba-no-es-real"


class MPSimulado:
    def __init__(self):
        self.ordenes: dict[str, dict] = {}
        self.llamadas: list[tuple[str, str]] = []
        self.cabeceras: list[dict] = []
        self.cajas = [{"id": 1, "name": "Caja mostrador", "external_id": "CAJA01", "status": "active",
                       "qr_response": {"image": "https://www.mercadopago.com/instore/merchant/qr/1/imagen.png"}},
                      {"id": 2, "name": "Caja creada en la app", "status": "active"}]
        self.caido = False
        self.comision = "250.50"

    def __call__(self, metodo, url, cabeceras, cuerpo):
        ruta = url.replace(mp.API, "").split("?")[0]
        self.llamadas.append((metodo, ruta))
        self.cabeceras.append(cabeceras)
        if self.caido:
            raise mp.ErrorConexionMP("No se pudo conectar con Mercado Pago. Revisá la conexión a Internet.")
        if cabeceras["Authorization"] != f"Bearer {TOKEN}":
            return 401, b'{"message": "invalid access token", "status": 401}'
        datos = json.loads(cuerpo) if cuerpo else {}
        if (metodo, ruta) == ("GET", "/users/me"):
            return 200, json.dumps({"id": 987654, "nickname": "ALMACENDONPEPE", "site_id": "MLA"}).encode()
        if (metodo, ruta) == ("GET", "/v2/pos"):
            return 200, json.dumps({"paging": {"total": len(self.cajas)}, "data": self.cajas}).encode()
        if metodo == "POST" and ruta == "/users/987654/stores":
            assert datos["location"]["latitude"] == -32.9468
            return 200, json.dumps({"id": 555, "name": datos["name"], "external_id": datos["external_id"]}).encode()
        if (metodo, ruta) == ("POST", "/v2/pos"):
            assert cabeceras.get("X-Idempotency-Key") and datos["store_id"] == "555"
            return 201, json.dumps({"id": 3, "name": datos["name"], "external_id": datos["external_id"], "status": "active",
                                    "qr_response": {"image": "https://www.mercadopago.com/qr/3.png"}}).encode()
        if (metodo, ruta) == ("POST", "/v1/orders"):
            assert cabeceras.get("X-Idempotency-Key")
            if datos["config"]["qr"]["external_pos_id"] != "CAJA01":
                return 404, json.dumps({"errors": [{"code": "pos_not_found", "message": "pos not found"}]}).encode()
            assert datos["type"] == "qr" and datos["transactions"]["payments"][0]["amount"] == datos["total_amount"]
            identificador = f"ORD{len(self.ordenes) + 1:026d}"
            orden = {"id": identificador, "type": "qr", "status": "created", "status_detail": "created",
                     "external_reference": datos["external_reference"], "total_amount": datos["total_amount"],
                     "config": datos["config"],
                     "transactions": {"payments": [{"id": "PAY01", "amount": datos["total_amount"], "status": "created",
                                                    "status_detail": "ready_to_process"}]}}
            self.ordenes[identificador] = orden
            respuesta = dict(orden)
            if datos["config"]["qr"]["mode"] != "static":
                respuesta["type_response"] = {"qr_data": "00020101021243650016com.mercadolibre" + identificador}
            return 201, json.dumps(respuesta).encode()
        if metodo == "GET" and ruta.startswith("/v1/orders/"):
            orden = self.ordenes.get(ruta.rsplit("/", 1)[1])
            return (200, json.dumps(orden).encode()) if orden else (404, b'{"errors":[{"code":"order_not_found"}]}')
        if metodo == "POST" and ruta.endswith("/cancel"):
            orden = self.ordenes[ruta.split("/")[3]]
            if orden["status"] != "created":
                return 409, json.dumps({"errors": [{"code": "order_already_canceled", "message": "x"}]}).encode()
            orden.update(status="canceled", status_detail="canceled")
            return 200, json.dumps(orden).encode()
        if metodo == "GET" and ruta.startswith("/v1/payments/"):
            return 200, json.dumps({"id": 92937960454, "status": "approved",
                                    "fee_details": [{"type": "mercadopago_fee", "amount": float(self.comision), "fee_payer": "collector"}]}).encode()
        return 404, b"{}"

    def pagar(self, orden: str, importe: str | None = None):
        o = self.ordenes[orden]
        o.update(status="processed", status_detail="accredited", total_paid_amount=importe or o["total_amount"])
        if importe:
            o["total_amount"] = importe
        o["transactions"]["payments"][0].update(status="processed", status_detail="accredited", reference={"id": "92937960454"})


@pytest.fixture
def cobro(ctx, producto):
    """Integración activa con la caja CAJA01, caja diaria abierta y una venta con pago de Mercado Pago pendiente."""
    simulado = MPSimulado()
    servicio = mp.ServicioMercadoPago(ctx, simulado)
    servicio.guardar_credencial(TOKEN)
    servicio.elegir_caja(servicio.cajas()[0], "dynamic")
    ctx.config.guardar({"mp_habilitado": True})
    ctx.caja.abrir(0)
    venta = vender(ctx, producto, medio="mercadopago", estado="pendiente")
    return servicio, simulado, venta, ctx.ventas.pagos(venta)[0]["id"]


def test_credencial_cifrada_y_fuera_de_la_base(ctx):
    simulado = MPSimulado()
    servicio = mp.ServicioMercadoPago(ctx, simulado)
    assert not servicio.estado().disponible
    with pytest.raises(ErrorNegocio, match="APP_USR"):
        servicio.guardar_credencial("mi-clave-del-banco")
    with pytest.raises(ErrorNegocio, match="rechazó la credencial"):
        servicio.guardar_credencial("APP_USR-otra-credencial")
    assert not servicio.tiene_credencial()

    assert servicio.guardar_credencial(TOKEN) == {"id": 987654, "nombre": "ALMACENDONPEPE"}
    guardado = mp._ruta_credencial().read_bytes()
    assert TOKEN.encode() not in guardado                               # cifrada en disco
    assert TOKEN not in " ".join(f["valor"] for f in ctx.db.consultar("SELECT valor FROM configuracion"))
    assert TOKEN not in " ".join(str(f["detalle"]) for f in ctx.db.consultar("SELECT detalle FROM auditoria"))
    assert "mercadopago" not in str(ctx.copias.crear())                 # la copia de seguridad es solo la base

    ctx.config.guardar({"mp_habilitado": True})
    assert "Falta elegir la caja" in servicio.estado().mensaje
    cajas = servicio.cajas()
    with pytest.raises(ErrorNegocio, match="identificador externo"):
        servicio.elegir_caja(cajas[1], "dynamic")
    servicio.elegir_caja(cajas[0], "hybrid")
    assert servicio.estado().disponible and ctx.config.obtener("mp_caja") == "CAJA01"

    nueva = servicio.crear_sucursal_y_caja({"nombre": "Almacén Don Pepe", "calle": "San Martín", "numero": "123",
                                            "ciudad": "Rosario", "provincia": "Santa Fe", "latitud": "-32,9468", "longitud": "-60,6393"})
    assert nueva["externo"].startswith("MCCAJA") and nueva["qr"]
    with pytest.raises(ErrorNegocio, match="latitud"):
        servicio.crear_sucursal_y_caja({"nombre": "X", "calle": "Y", "numero": "1", "ciudad": "Z", "provincia": "W", "latitud": "", "longitud": ""})
    servicio.borrar_credencial()
    assert not servicio.tiene_credencial() and not servicio.estado().disponible


def test_cobro_se_confirma_solo_cuando_mercado_pago_lo_acredita(cobro, ctx):
    servicio, simulado, venta, pago = cobro
    creado = servicio.crear_cobro(pago)
    assert creado["qr"].startswith("000201") and creado["orden"].startswith("ORD") and creado["monto_cent"] == 1728571
    orden = simulado.ordenes[creado["orden"]]
    assert orden["total_amount"] == "17285.71" and orden["external_reference"].startswith(f"MC-{venta}-{pago}-")
    assert ctx.ventas.pagos(venta)[0]["id_externo"] == creado["orden"]

    assert servicio.verificar(pago) == "pendiente"                      # el cliente todavía no pagó
    assert estado_pago(ctx.ventas.obtener(venta)) == "pendiente"
    assert ctx.caja.resumen(ctx.caja.abierta()["id"])["cobrado_total_cent"] == 0

    simulado.pagar(creado["orden"])
    assert servicio.verificar(pago) == "confirmado"
    p = ctx.ventas.pagos(venta)[0]
    assert (p["estado"], p["referencia"], p["comision_cent"]) == ("confirmado", "MP 92937960454", 25050)
    r = ctx.caja.resumen(ctx.caja.abierta()["id"])
    assert r["cobrado_cent"]["mercadopago"] == 1728571 and r["mp_neto_cent"] == 1728571 - 25050
    assert servicio.verificar(pago) == "confirmado"                     # consultar de nuevo no lo cobra dos veces
    assert ctx.db.valor("SELECT COUNT(*) FROM pagos WHERE estado = 'confirmado'") == 1


def test_un_pago_que_no_coincide_no_confirma(cobro, ctx):
    servicio, simulado, venta, pago = cobro
    creado = servicio.crear_cobro(pago)
    simulado.pagar(creado["orden"], importe="100.00")                   # pagaron otro importe
    with pytest.raises(ErrorNegocio, match="no coincide"):
        servicio.verificar(pago)
    assert ctx.ventas.pagos(venta)[0]["estado"] == "pendiente"
    orden = simulado.ordenes[creado["orden"]]
    orden.update(total_amount="17285.71", external_reference="MC-999-999-otra")   # orden de otra venta
    with pytest.raises(ErrorNegocio, match="no coincide"):
        servicio.verificar(pago)
    assert ctx.ventas.pagos(venta)[0]["estado"] == "pendiente"


@pytest.mark.parametrize("estado_mp,esperado", [("expired", "cancelado"), ("canceled", "cancelado"), ("failed", "rechazado"),
                                                ("refunded", "cancelado"), ("action_required", "pendiente"), ("algo_nuevo", "pendiente")])
def test_estados_que_no_son_un_cobro(cobro, ctx, estado_mp, esperado):
    servicio, simulado, venta, pago = cobro
    creado = servicio.crear_cobro(pago)
    simulado.ordenes[creado["orden"]]["status"] = estado_mp
    assert servicio.verificar(pago) == esperado
    assert ctx.ventas.pagos(venta)[0]["estado"] == esperado
    assert ctx.caja.resumen(ctx.caja.abierta()["id"])["cobrado_total_cent"] == 0


def test_cancelar_y_cobrar_de_otra_forma(cobro, ctx):
    servicio, simulado, venta, pago = cobro
    creado = servicio.crear_cobro(pago)
    assert servicio.cancelar(pago) == "cancelado"
    assert simulado.ordenes[creado["orden"]]["status"] == "canceled"
    assert estado_pago(ctx.ventas.obtener(venta)) == "impaga" and ctx.ventas.saldo(venta) == 1728571
    ctx.ventas.agregar_pago(venta, {"medio": "efectivo", "monto_cent": 1728571})
    assert estado_pago(ctx.ventas.obtener(venta)) == "pagada"


def test_si_pagaron_justo_antes_de_cancelar_se_confirma(cobro, ctx):
    servicio, simulado, venta, pago = cobro
    creado = servicio.crear_cobro(pago)
    simulado.pagar(creado["orden"])
    assert servicio.cancelar(pago) == "confirmado"
    assert ("POST", f"/v1/orders/{creado['orden']}/cancel") not in simulado.llamadas


def test_sin_conexion_no_cambia_nada(cobro, ctx):
    servicio, simulado, venta, pago = cobro
    simulado.caido = True
    with pytest.raises(mp.ErrorConexionMP):
        servicio.crear_cobro(pago)
    assert ctx.ventas.pagos(venta)[0]["id_externo"] is None
    simulado.caido = False
    servicio.crear_cobro(pago)
    simulado.caido = True
    for operacion in (servicio.verificar, servicio.cancelar):
        with pytest.raises(mp.ErrorConexionMP):
            operacion(pago)
    assert ctx.ventas.pagos(venta)[0]["estado"] == "pendiente"
    assert servicio.verificar_pendientes()["errores"]
    simulado.caido = False
    assert servicio.verificar_pendientes()["pendiente"] == 1


def test_modo_estatico_caja_incorrecta_y_permisos(cobro, ctx):
    servicio, simulado, venta, pago = cobro
    ctx.config.guardar({"mp_modo": "static"})
    assert servicio.crear_cobro(pago)["qr"] == ""                       # se paga con el QR impreso de la caja
    ctx.config.guardar({"mp_caja": "NO-EXISTE"})
    with pytest.raises(ErrorNegocio, match="no encuentra la caja"):
        servicio.crear_cobro(pago)
    efectivo = vender(ctx, ctx.ventas.items(venta)[0]["producto_id"])
    with pytest.raises(ErrorNegocio):
        servicio.crear_cobro(ctx.ventas.pagos(efectivo)[0]["id"])       # no es un cobro de Mercado Pago
    manual = vender(ctx, ctx.ventas.items(venta)[0]["producto_id"], medio="mercadopago", estado="pendiente")
    with pytest.raises(ErrorNegocio, match="a mano"):
        servicio.verificar(ctx.ventas.pagos(manual)[0]["id"])           # sin orden asociada no hay nada que consultar
    ctx.usuarios.crear("caja1", "Cajera", "clave-de-prueba", "cajero")
    ctx.usuarios.iniciar_sesion("caja1", "clave-de-prueba")
    with pytest.raises(PermisoDenegado):
        servicio.guardar_credencial(TOKEN)
    ctx.config_mp = None
    assert all("Bearer " in c["Authorization"] for c in simulado.cabeceras)


def test_la_api_real_rechaza_una_credencial_inventada(ctx):
    """Contra el servidor real: confirma la dirección, el formato del pedido y la lectura del error."""
    try:
        with pytest.raises(ErrorNegocio, match="rechazó la credencial"):
            mp.ServicioMercadoPago(ctx).guardar_credencial("APP_USR-0000000000000000-000000-credencialinventada-000000000")
    except mp.ErrorConexionMP:
        pytest.skip("sin conexión a Internet")
    assert not mp.ServicioMercadoPago(ctx).tiene_credencial()


# ---- pantallas ----------------------------------------------------------------
def test_ventana_de_cobro_con_qr(app, cobro, ctx):
    from micomercio.ui.cobro_qr import DialogoCobroQR

    servicio, simulado, venta, pago = cobro
    d = DialogoCobroQR(None, ctx, venta, pago, servicio)
    assert d.total.text() == "$ 17.285,71" and not d.imagen.pixmap().isNull() and d.reloj.isActive()
    d.recibir(servicio.consultar_orden(d.datos), "")
    assert "Esperando" in d.estado.text() and d.reloj.isActive()
    d.recibir(None, "conexion")
    assert "Sin conexión" in d.estado.text() and ctx.ventas.pagos(venta)[0]["estado"] == "pendiente"

    simulado.pagar(d.datos["orden"])
    d.consultar()                                   # consulta real en segundo plano
    d.hilo.wait(5000)
    app.processEvents()
    assert d.resultado == "confirmado" and not d.reloj.isActive() and "acreditado" in d.estado.text()
    assert ctx.ventas.pagos(venta)[0]["estado"] == "confirmado"
    d.done(0)


def test_qr_vencido_se_puede_generar_otro_o_cobrar_de_otra_forma(app, cobro, ctx):
    from micomercio.ui.cobro_qr import DialogoCobroQR

    servicio, simulado, venta, pago = cobro
    d = DialogoCobroQR(None, ctx, venta, pago, servicio)
    simulado.ordenes[d.datos["orden"]]["status"] = "expired"
    d.recibir(servicio.consultar_orden(d.datos), "")
    assert d.resultado == "otra_forma" and not d.b_otro.isHidden() and "venció" in d.estado.text()
    assert ctx.ventas.pagos(venta)[0]["estado"] == "cancelado"

    d.nuevo_qr()
    pagos = ctx.ventas.pagos(venta)
    assert len(pagos) == 2 and d.pago_id == pagos[1]["id"] and pagos[1]["id_externo"] and d.reloj.isActive()
    d.otra_forma()
    assert d.resultado == "otra_forma" and ctx.ventas.pagos(venta)[1]["estado"] == "cancelado"
    assert ctx.ventas.saldo(venta) == 1728571 and len(simulado.ordenes) == 2

    simulado.caido = True                            # si no se puede crear el cobro, no queda nada colgado
    otra = vender(ctx, ctx.ventas.items(venta)[0]["producto_id"], medio="mercadopago", estado="pendiente")
    d2 = DialogoCobroQR(None, ctx, otra, ctx.ventas.pagos(otra)[0]["id"], servicio)
    assert "No se pudo generar" in d2.estado.text() and not d2.reloj.isActive()
    d2.otra_forma()
    assert ctx.ventas.pagos(otra)[0]["estado"] == "cancelado"


def test_venta_completa_con_qr(app, cobro, ctx, producto, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from micomercio.ui.paginas import venta as modulo
    from micomercio.ui.ventana import VentanaPrincipal

    servicio, simulado, _, _ = cobro
    monkeypatch.setattr(modulo.mercadopago, "crear_servicio", lambda c: servicio)
    ventana = VentanaPrincipal(ctx)
    ventana.reloj_copias.stop()
    ventana.show()
    ventana.ir("venta")
    pagina = ventana.paginas["venta"]

    d = modulo.DialogoCobro(pagina, "mercadopago", 1000, con_qr=True)   # con la integración activa, el QR es la opción elegida
    d.guardar()
    assert d.usar_qr and d.pago["estado"] == "pendiente"
    assert modulo.DialogoCobro(pagina, "mercadopago", 1000).qr is None

    registradas = []

    class Cobro:
        def __init__(self, padre, medio, total, con_qr=False):
            assert con_qr
            self.pago, self.vuelto_cent, self.usar_qr = {"medio": medio, "monto_cent": total, "estado": "pendiente"}, 0, True

        def exec(self):
            return QDialog.Accepted

    class VentanaQR:
        pagar = True

        def __init__(self, padre, ctx_, venta_id, pago_id):
            self.resultado = "pendiente"
            if self.pagar:
                creado = servicio.crear_cobro(pago_id)
                simulado.pagar(creado["orden"])
                servicio.verificar(pago_id)
                self.resultado = "confirmado"

        def exec(self):
            return QDialog.Accepted

    class Registrada:
        def __init__(self, padre, ctx_, venta_id, vuelto, pendiente, factura, error):
            registradas.append((venta_id, pendiente))

        def exec(self):
            return QDialog.Accepted

    monkeypatch.setattr(modulo, "DialogoCobro", Cobro)
    monkeypatch.setattr(modulo, "DialogoCobroQR", VentanaQR)
    monkeypatch.setattr(modulo, "DialogoVentaRegistrada", Registrada)
    pagina.agregar(ctx.productos.obtener(producto))
    pagina.cobrar("mercadopago")
    venta_id, pendiente = registradas[0]
    assert not pendiente and estado_pago(ctx.ventas.obtener(venta_id)) == "pagada"

    VentanaQR.pagar = False                          # el cliente no paga: la venta queda guardada y pendiente
    pagina.agregar(ctx.productos.obtener(producto))
    pagina.cobrar("mercadopago")
    assert registradas[1][1] and estado_pago(ctx.ventas.obtener(registradas[1][0])) == "pendiente"
    ventana.ir("configuracion")
    assert "Cobro con QR activo" in ventana.paginas["configuracion"].mercado_pago.estado.text()
    ventana.close()
