import sqlite3
import uuid
from decimal import Decimal as D

import pytest

from conftest import vender
from micomercio.core.errores import ErrorNegocio, PermisoDenegado
from micomercio.db import BaseDatos
from micomercio.servicios import Contexto, csv_io, tickets
from micomercio.servicios.copias import validar_copia
from micomercio.servicios.ventas import calcular_totales, estado_pago, repartir_descuento


# ---- productos y precios -------------------------------------------------
def test_producto_calcula_precios(ctx, producto):
    p = ctx.productos.obtener(producto)
    assert (p["costo_cent"], p["precio_neto_cent"], p["precio_final_cent"]) == (1000000, 1428571, 1728571)
    assert p["stock_mil"] == 10000 and p["categoria"] == "Almacén"
    assert len(ctx.productos.historial_precios(producto)) == 1
    assert ctx.inventario.movimientos(producto)[0]["tipo"] == "inicial"


def test_codigos_unicos_y_busqueda(ctx, producto):
    with pytest.raises(ErrorNegocio):
        ctx.productos.crear({"codigo": "a1", "nombre": "Otro"})
    with pytest.raises(ErrorNegocio):
        ctx.productos.crear({"codigo_barras": "7790001000012", "nombre": "Otro"})
    otro = ctx.productos.crear({"nombre": "Azúcar", "categoria": "Almacén"})
    assert ctx.productos.obtener(otro)["codigo"]  # código generado
    assert ctx.productos.por_codigo("7790001000012")["id"] == producto
    assert ctx.productos.por_codigo("A1")["id"] == producto
    assert [p["id"] for p in ctx.productos.buscar("yerba")] == [producto]
    assert len(ctx.productos.buscar("almacén")) == 2
    assert len(ctx.productos.buscar("7790001")) == 1
    ctx.productos.cambiar_estado(producto, False)
    assert ctx.productos.por_codigo("A1") is None
    assert len(ctx.productos.buscar("", solo_activos=False)) == 2


def test_precio_manual_recalcula_ganancia(ctx, producto):
    datos = ctx.productos.datos_para_duplicar(producto)
    datos.update(codigo="A1", codigo_barras="7790001000012", nombre="Yerba 1 kg", precio_manual=True, precio_final=D("20000"))
    ctx.productos.actualizar(producto, datos)
    p = ctx.productos.obtener(producto)
    assert p["precio_final_cent"] == 2000000 and p["precio_manual"] == 1
    assert D(p["ganancia_pct"]) == D("39.5")  # 1 - 10000 / (20000 / 1.21)
    historial = ctx.productos.historial_precios(producto)
    assert len(historial) == 2 and historial[0]["final_ant_cent"] == 1728571


def test_duplicar(ctx, producto):
    nuevo = ctx.productos.crear(ctx.productos.datos_para_duplicar(producto))
    p = ctx.productos.obtener(nuevo)
    assert p["precio_final_cent"] == 1728571 and p["stock_mil"] == 0 and p["codigo"] != "A1"


def test_cambio_masivo_con_vista_previa(ctx, producto):
    vista = ctx.productos.previsualizar_cambio_masivo("costo", "porcentaje", D("10"))
    assert ctx.productos.obtener(producto)["costo_cent"] == 1000000  # la vista previa no guarda
    assert vista[0]["campos"]["costo_cent"] == 1100000
    assert vista[0]["campos"]["precio_final_cent"] == 1901429  # 11000 / 0,7 x 1,21
    assert ctx.productos.aplicar_cambio_masivo(vista) == 1
    assert ctx.productos.obtener(producto)["precio_final_cent"] == 1901429
    assert ctx.productos.historial_precios(producto)[0]["origen"] == "masivo"

    vista = ctx.productos.previsualizar_cambio_masivo("final", "importe", D("-1000"), redondeo=100)
    assert vista[0]["campos"]["precio_final_cent"] == 1800000
    ctx.productos.aplicar_cambio_masivo(vista)
    with pytest.raises(ErrorNegocio):  # vista previa vencida
        ctx.productos.aplicar_cambio_masivo(vista)
    vista = ctx.productos.previsualizar_cambio_masivo("final", "importe", D("-99999999"))
    assert vista[0]["error"] and vista[0]["campos"] is None
    assert ctx.productos.aplicar_cambio_masivo(vista) == 0


# ---- ventas, stock y caja -------------------------------------------------
def test_reparto_de_descuento():
    assert repartir_descuento([1000, 2000, 3000], 601) == [100, 200, 301]
    assert sum(repartir_descuento([333, 333, 334], 100)) == 100
    t = calcular_totales([{"cantidad_mil": 1500, "precio_unit_cent": 1000, "impuesto_pct": "21"}], 100)
    assert t["bruto_cent"] == 1500 and t["total_cent"] == 1400 and t["neto_cent"] + t["impuestos_cent"] == 1400


def test_no_se_vende_con_la_caja_cerrada(ctx, producto):
    with pytest.raises(ErrorNegocio):
        vender(ctx, producto)
    assert ctx.productos.obtener(producto)["stock_mil"] == 10000


def test_venta_descuenta_stock_y_no_se_duplica(ctx, producto):
    ctx.caja.abrir(500000)
    identificador = str(uuid.uuid4())
    venta = vender(ctx, producto, "2", uuid=identificador)
    assert vender(ctx, producto, "2", uuid=identificador) == venta  # doble clic
    assert ctx.db.valor("SELECT COUNT(*) FROM ventas") == 1
    assert ctx.productos.obtener(producto)["stock_mil"] == 8000
    v = ctx.ventas.obtener(venta)
    assert v["total_cent"] == 3457142 and v["neto_cent"] + v["impuestos_cent"] == v["total_cent"]
    assert estado_pago(v) == "pagada"
    item = ctx.ventas.items(venta)[0]
    assert item["costo_unit_cent"] == 1000000 and item["nombre"] == "Yerba 1 kg"


def test_venta_fallida_no_deja_nada_a_medias(ctx, producto):
    ctx.caja.abrir(0)
    with pytest.raises(ErrorNegocio):  # stock insuficiente
        vender(ctx, producto, "11")
    p = ctx.productos.obtener(producto)
    with pytest.raises(ErrorNegocio):  # pago que no coincide con el total
        ctx.ventas.registrar(str(uuid.uuid4()), [{"producto_id": producto, "cantidad": D(1), "precio_unit_cent": p["precio_final_cent"]}],
                             [{"medio": "efectivo", "monto_cent": 100}])
    # Falla inesperada en medio de la transacción: todo vuelve atrás.
    original = ctx.ventas._insertar_pago
    ctx.ventas._insertar_pago = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("corte"))
    with pytest.raises(RuntimeError):
        vender(ctx, producto)
    ctx.ventas._insertar_pago = original
    assert ctx.db.valor("SELECT COUNT(*) FROM ventas") == 0
    assert ctx.db.valor("SELECT COUNT(*) FROM venta_items") == 0
    assert ctx.productos.obtener(producto)["stock_mil"] == 10000
    assert len(ctx.inventario.movimientos(producto)) == 1


def test_stock_negativo_solo_con_autorizacion(ctx, producto):
    ctx.caja.abrir(0)
    ctx.config.guardar({"permitir_stock_negativo": True})
    vender(ctx, producto, "12")
    assert ctx.productos.obtener(producto)["stock_mil"] == -2000


def test_ventas_historicas_no_cambian_al_editar_el_producto(ctx, producto):
    ctx.caja.abrir(0)
    venta = vender(ctx, producto)
    datos = ctx.productos.datos_para_duplicar(producto)
    datos.update(codigo="A1", nombre="Yerba premium", costo=D("20000"), precio_manual=False)
    ctx.productos.actualizar(producto, datos)
    item = ctx.ventas.items(venta)[0]
    assert (item["nombre"], item["costo_unit_cent"], item["precio_unit_cent"]) == ("Yerba 1 kg", 1000000, 1728571)


def test_caja_distingue_vendido_de_cobrado(ctx, producto):
    caja = ctx.caja.abrir(1000000)
    vender(ctx, producto)                                              # efectivo 17.285,71
    vender(ctx, producto, medio="tarjeta")
    mp = vender(ctx, producto, medio="mercadopago", estado="pendiente")
    transferencia = vender(ctx, producto, medio="transferencia", estado="pendiente")
    ctx.caja.registrar_movimiento("entrada", 200000, "Cambio")
    ctx.caja.registrar_movimiento("salida", 50000, "Pago de flete")

    r = ctx.caja.resumen(caja)
    assert r["ventas_cantidad"] == 4 and r["ventas_total_cent"] == 4 * 1728571
    assert r["cobrado_total_cent"] == 2 * 1728571          # los pendientes no son ingresos
    assert r["pendientes_cent"] == 2 * 1728571
    assert r["cobrado_cent"] == {"efectivo": 1728571, "tarjeta": 1728571, "transferencia": 0, "mercadopago": 0}
    assert r["efectivo_esperado_cent"] == 1000000 + 1728571 + 200000 - 50000
    assert estado_pago(ctx.ventas.obtener(mp)) == "pendiente"

    pago_mp = ctx.ventas.pagos(mp)[0]["id"]
    ctx.ventas.confirmar_pago(pago_mp, "OP-123", comision_cent=100000)
    with pytest.raises(ErrorNegocio):                      # no se cobra dos veces
        ctx.ventas.confirmar_pago(pago_mp)
    ctx.ventas.descartar_pago(ctx.ventas.pagos(transferencia)[0]["id"], "rechazado")
    with pytest.raises(ErrorNegocio):
        ctx.ventas.confirmar_pago(ctx.ventas.pagos(transferencia)[0]["id"])

    r = ctx.caja.resumen(caja)
    assert r["cobrado_total_cent"] == 3 * 1728571 and r["pendientes_cent"] == 0
    assert r["mp_comisiones_cent"] == 100000 and r["mp_neto_cent"] == 1628571
    assert estado_pago(ctx.ventas.obtener(transferencia)) == "impaga"
    assert ctx.ventas.saldo(transferencia) == 1728571
    ctx.ventas.agregar_pago(transferencia, {"medio": "efectivo", "monto_cent": 1728571})
    with pytest.raises(ErrorNegocio):                      # ya está cobrada
        ctx.ventas.agregar_pago(transferencia, {"medio": "efectivo", "monto_cent": 1})

    esperado = 1000000 + 2 * 1728571 + 200000 - 50000
    cierre = ctx.caja.cerrar(esperado - 5000, "Faltó cambio")
    assert cierre["estado"] == "cerrada" and cierre["diferencia_cent"] == -5000
    assert cierre["efectivo_esperado_cent"] == esperado
    assert ctx.caja.abierta() is None
    with pytest.raises(ErrorNegocio):
        ctx.caja.cerrar(0)
    assert "Diferencia de caja" in tickets.html_cierre_caja(ctx, caja)


def test_pago_pendiente_cuenta_en_la_caja_en_que_se_confirma(ctx, producto):
    primera = ctx.caja.abrir(0)
    venta = vender(ctx, producto, medio="transferencia", estado="pendiente")
    ctx.caja.cerrar(0)
    segunda = ctx.caja.abrir(0)
    ctx.ventas.confirmar_pago(ctx.ventas.pagos(venta)[0]["id"])
    assert ctx.caja.resumen(primera)["cobrado_total_cent"] == 0
    assert ctx.caja.resumen(primera)["ventas_total_cent"] == 1728571
    assert ctx.caja.resumen(segunda)["cobrado_cent"]["transferencia"] == 1728571
    assert ctx.caja.resumen(segunda)["ventas_total_cent"] == 0


def test_una_sola_caja_abierta(ctx):
    ctx.caja.abrir(0)
    with pytest.raises(ErrorNegocio):
        ctx.caja.abrir(0)
    with pytest.raises(sqlite3.IntegrityError):
        ctx.db.ejecutar("INSERT INTO cajas (abierta_en, saldo_inicial_cent) VALUES ('x', 0)")


def test_anulacion_devuelve_stock_y_dinero(ctx, producto):
    caja = ctx.caja.abrir(0)
    venta = vender(ctx, producto, "3")
    ctx.ventas.anular(venta, "Error de carga")
    with pytest.raises(ErrorNegocio):
        ctx.ventas.anular(venta, "otra vez")
    assert ctx.productos.obtener(producto)["stock_mil"] == 10000
    r = ctx.caja.resumen(caja)
    assert r["ventas_total_cent"] == 0 and r["cobrado_total_cent"] == 0
    assert r["devoluciones_cent"] == 3 * 1728571 and r["anuladas_cantidad"] == 1
    assert r["efectivo_esperado_cent"] == 0
    assert ctx.db.valor("SELECT COUNT(*) FROM ventas") == 1  # la venta no se borra
    assert "VENTA ANULADA" in tickets.html_ticket(ctx, venta)
    assert [m["tipo"] for m in ctx.inventario.movimientos(producto)] == ["anulacion", "venta", "inicial"]


def test_descuentos_autorizados_y_permisos(ctx, producto):
    ctx.caja.abrir(0)
    ctx.usuarios.crear("caja1", "Cajera", "clave-de-prueba", "cajero")
    ctx.usuarios.iniciar_sesion("caja1", "clave-de-prueba")
    vender(ctx, producto, descuento_cent=172857)            # 10 %: permitido
    with pytest.raises(ErrorNegocio):
        vender(ctx, producto, descuento_cent=500000)        # 29 %: no
    venta = vender(ctx, producto)
    with pytest.raises(PermisoDenegado):
        ctx.ventas.anular(venta, "x")
    with pytest.raises(PermisoDenegado):
        ctx.productos.crear({"nombre": "X"})
    with pytest.raises(PermisoDenegado):
        ctx.config.guardar({"permitir_stock_negativo": True})
    ctx.usuarios.iniciar_sesion("admin", "clave-de-prueba")
    vender(ctx, producto, descuento_cent=500000)
    with pytest.raises(ErrorNegocio):
        ctx.usuarios.iniciar_sesion("admin", "incorrecta")
    with pytest.raises(ErrorNegocio):                       # no se puede quedar sin administrador
        ctx.usuarios.actualizar(ctx.usuario_id, "Administrador", "cajero", True)


def test_ticket(ctx, producto):
    ctx.caja.abrir(0)
    html = tickets.html_ticket(ctx, vender(ctx, producto, "2"))
    assert "Yerba 1 kg" in html and "$ 34.571,42" in html and "DOCUMENTO NO VÁLIDO COMO FACTURA" in html


# ---- inventario y compras -------------------------------------------------
def test_movimientos_manuales(ctx, producto):
    assert ctx.inventario.registrar_movimiento(producto, "entrada", D("5"), "Reposición") == 15000
    assert ctx.inventario.registrar_movimiento(producto, "salida", D("1.5"), "Rotura") == 13500
    assert ctx.inventario.registrar_movimiento(producto, "ajuste", D("2"), "Conteo") == 2000
    with pytest.raises(ErrorNegocio):
        ctx.inventario.registrar_movimiento(producto, "salida", D("3"), "Rotura")
    with pytest.raises(ErrorNegocio):
        ctx.inventario.registrar_movimiento(producto, "entrada", D("3"), "")
    movimientos = ctx.inventario.movimientos(producto)
    assert [m["cantidad_mil"] for m in movimientos] == [-11500, -1500, 5000, 10000]
    assert ctx.inventario.alertas() == {"agotados": 0, "bajos": 1}
    assert ctx.inventario.valor_inventario() == {"costo_cent": 2000000, "venta_cent": 3457142}
    ctx.inventario.registrar_movimiento(producto, "ajuste", D("0"), "Conteo")
    assert ctx.inventario.alertas() == {"agotados": 1, "bajos": 0}


def test_compra_actualiza_stock_y_costo(ctx, producto):
    ctx.caja.abrir(0)
    venta = vender(ctx, producto)
    proveedor = ctx.compras.guardar_proveedor({"nombre": "Distribuidora Sur", "cuit": "30-12345678-9"})
    ctx.compras.registrar(proveedor, [{"producto_id": producto, "cantidad": D("20"), "costo_cent": 1200000}], "FC A 0001-00001234")
    p = ctx.productos.obtener(producto)
    assert p["stock_mil"] == 29000 and p["costo_cent"] == 1200000
    assert p["precio_final_cent"] == 2074286                       # 12000 / 0,7 x 1,21
    assert ctx.ventas.items(venta)[0]["costo_unit_cent"] == 1000000  # la venta histórica no cambia
    assert ctx.productos.historial_precios(producto)[0]["origen"] == "compra"

    ctx.compras.registrar(proveedor, [{"producto_id": producto, "cantidad": D("1"), "costo_cent": 1500000}], actualizar_precios=False)
    p = ctx.productos.obtener(producto)
    assert p["precio_final_cent"] == 2074286 and D(p["ganancia_pct"]) == D("12.5")
    assert len(ctx.compras.listar("2000-01-01", "2999-01-01")) == 2


# ---- reportes ------------------------------------------------------------
def test_reportes(ctx, producto, tmp_path):
    ctx.caja.abrir(0)
    vender(ctx, producto, "2")
    vender(ctx, producto, medio="mercadopago", estado="pendiente")
    anulada = vender(ctx, producto, medio="tarjeta")
    ctx.ventas.anular(anulada, "Prueba")
    c = ctx.reportes.cifras("2000-01-01", "2999-01-01")
    assert c["ventas_cantidad"] == 2 and c["facturacion_cent"] == 3 * 1728571
    assert c["cobrado_cent"] == 2 * 1728571 and c["pendientes_cent"] == 1728571
    assert c["costo_cent"] == 3000000
    assert c["ganancia_bruta_cent"] == c["neto_cent"] - 3000000
    assert c["margen_pct"] == D("30.00")
    assert c["anuladas_cantidad"] == 1 and c["devoluciones_cent"] == 1728571
    for clave, _ in ctx.reportes.LISTA:
        reporte = ctx.reportes.generar(clave, "2000-01-01", "2999-01-01")
        csv_io.exportar_reporte(reporte, tmp_path / f"{clave}.csv")
    texto = (tmp_path / "mas_vendidos.csv").read_text(encoding="utf-8-sig")
    assert "Yerba 1 kg;3,000;51857,13" in texto
    assert ctx.reportes.cifras("1990-01-01", "1990-01-02")["ventas_cantidad"] == 0


# ---- CSV -----------------------------------------------------------------
def test_csv_ida_y_vuelta(ctx, producto, tmp_path):
    archivo = tmp_path / "productos.csv"
    assert csv_io.exportar_productos(ctx, archivo) == 1
    texto = archivo.read_text(encoding="utf-8-sig")
    assert "Precio Costo;Impuestos;Porcentaje de ganancia" in texto and "10000,00;21,00;30,00" in texto

    archivo.write_text(
        texto + "B2;;Fideos;;Almacén;Marca;Molinos SA;1.000,00;10,5;50;recargo;;;;7;1;unidad;;\n"
        ";;;;;;;abc;;;;;;;;;;;\n;;Sin precio;;;;;x;;;;;;;;;;;\n",
        encoding="utf-8-sig",
    )
    ctx.inventario.registrar_movimiento(producto, "entrada", D("1"), "Reposición")
    r = csv_io.importar_productos(ctx, archivo)
    assert (r["creados"], r["actualizados"], len(r["errores"])) == (1, 1, 2)
    fideos = ctx.productos.por_codigo("B2")
    assert fideos["precio_final_cent"] == 165750 and fideos["stock_mil"] == 7000 and fideos["proveedor"] == "Molinos SA"
    assert ctx.productos.obtener(producto)["stock_mil"] == 10000   # ajustado al valor del archivo
    assert ctx.inventario.movimientos(producto)[0]["tipo"] == "ajuste"
    assert ctx.productos.obtener(producto)["precio_final_cent"] == 1728571


# ---- copias de seguridad ---------------------------------------------------
def test_copia_y_restauracion(ctx, producto, tmp_path):
    copia = ctx.copias.crear()
    assert validar_copia(copia)["productos"] == 1
    ctx.productos.crear({"nombre": "Creado después de la copia"})
    assert ctx.db.valor("SELECT COUNT(*) FROM productos") == 2

    basura = tmp_path / "basura.db"
    basura.write_bytes(b"esto no es una base de datos" * 100)
    with pytest.raises(ErrorNegocio):
        ctx.copias.restaurar(basura)
    otra = tmp_path / "otra.db"
    sqlite3.connect(otra).executescript("CREATE TABLE x (a); INSERT INTO x VALUES (1);")
    with pytest.raises(ErrorNegocio):
        ctx.copias.restaurar(otra)
    danada = tmp_path / "danada.db"
    datos = bytearray(copia.read_bytes())
    datos[5000:9000] = b"\xff" * 4000
    danada.write_bytes(datos)
    with pytest.raises(ErrorNegocio):
        ctx.copias.restaurar(danada)
    assert ctx.db.valor("SELECT COUNT(*) FROM productos") == 2      # nada cambió

    info = ctx.copias.restaurar(copia)
    assert info["resguardo"].exists()
    assert ctx.db.valor("SELECT COUNT(*) FROM productos") == 1
    assert ctx.usuario is None
    ctx.usuarios.iniciar_sesion("admin", "clave-de-prueba")
    assert ctx.db.valor("PRAGMA foreign_keys") == 1


def test_copia_automatica_diaria(ctx):
    assert ctx.copias.automatica_si_corresponde() is not None
    assert ctx.copias.automatica_si_corresponde() is None
    assert [c["tipo"] for c in ctx.copias.listar()] == ["Automática"]


def test_los_datos_persisten_al_reabrir(ctx, producto, tmp_path):
    ruta = ctx.db.ruta
    ctx.db.cerrar()
    otro = Contexto(BaseDatos(ruta))
    assert otro.productos.por_codigo("A1")["precio_final_cent"] == 1728571
    assert not otro.puede("vender")  # sin sesión no hay permisos
    otro.db.cerrar()
    ctx.db.abrir()


def test_los_datos_del_nombre_anterior_se_conservan(tmp_path, monkeypatch):
    from micomercio import rutas

    monkeypatch.delenv("EXAPYME_DATOS", raising=False)
    monkeypatch.delenv("MICOMERCIO_DATOS", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    vieja = tmp_path / "MiComercio"
    (vieja / "copias").mkdir(parents=True)
    (vieja / "micomercio.db").write_bytes(b"datos del comercio")
    assert rutas.carpeta_datos() == tmp_path / "ExaPyme" and not vieja.exists()
    assert rutas.ruta_base_datos().read_bytes() == b"datos del comercio"
    assert rutas.carpeta_datos() == tmp_path / "ExaPyme"            # la segunda vez no cambia nada

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "nueva_pc"))
    assert rutas.carpeta_datos() == tmp_path / "nueva_pc" / "ExaPyme"   # instalación nueva
