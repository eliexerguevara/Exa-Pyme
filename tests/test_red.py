"""Modo servidor / cliente: varias computadoras trabajando sobre los datos de una."""
import sqlite3
import threading
import uuid
from decimal import Decimal as D

import pytest

from conftest import vender
from micomercio import __version__, preferencias
from micomercio.core.errores import ErrorNegocio, PermisoDenegado
from micomercio.integraciones import arca, mercadopago
from micomercio.red import codec
from micomercio.red.cliente import Cliente, ContextoRemoto, ErrorServidor, HuellaDistinta
from micomercio.red.servidor import Servidor, SesionVencida
from micomercio.servicios import csv_io, tickets
from micomercio.servicios.reportes import Reporte, formatear

CLAVE = "clave-de-prueba"


@pytest.fixture
def servidor(ctx, producto):
    """La computadora principal: base con un producto y la caja abierta, atendiendo en un puerto libre."""
    ctx.usuarios.crear("caja1", "Cajera Uno", CLAVE, "cajero")
    ctx.caja.abrir(0)
    s = Servidor(ctx.db, 0)
    s.iniciar("127.0.0.1")
    yield s
    s.detener()


def conectar(servidor, usuario="admin", puesto="Caja 2"):
    """Una computadora cliente, con su propia caja abierta."""
    remoto = ContextoRemoto(Cliente("127.0.0.1", servidor.puerto))
    remoto.ingresar(usuario, CLAVE, puesto)
    if remoto.caja.abierta() is None:
        remoto.caja.abrir(0)
    return remoto


# ---- datos que viajan ---------------------------------------------------------
def test_los_datos_viajan_sin_perder_precision(ctx, producto):
    fila = ctx.productos.obtener(producto)
    reporte = Reporte("R", [("Concepto", "texto"), ("Valor", "texto")], [["Total", ("dinero", 1728571)]], "nota")
    original = {"decimal": D("14285.71"), "tupla": ("dinero", 5), "bytes": b"\x00\xffcertificado", "fila": fila,
                "por_id": {7: {"cantidad_mil": 1000}}, "reporte": reporte, "lista": [1, "dos", None, True], "__rara": 1}
    recibido = codec.decodificar(codec.codificar(original))
    assert recibido["decimal"] == D("14285.71") and isinstance(recibido["decimal"], D)
    assert recibido["tupla"] == ("dinero", 5) and recibido["bytes"] == b"\x00\xffcertificado"
    assert recibido["fila"]["nombre"] == "Yerba 1 kg" and recibido["fila"]["precio_final_cent"] == 1728571
    assert recibido["por_id"] == {7: {"cantidad_mil": 1000}} and recibido["__rara"] == 1
    r = recibido["reporte"]
    assert r.titulo == "R" and r.columnas[0] == ("Concepto", "texto") and formatear(r.filas[0][1], "texto") == "$ 17.285,71"
    with pytest.raises(TypeError):
        codec.codificar({"conexion": ctx.db})


# ---- servidor: acceso y permisos -------------------------------------------------
def test_ingreso_y_permisos_se_comprueban_en_el_servidor(servidor, ctx, producto):
    pedir = lambda **p: servidor.atender(p, "10.0.0.9")  # noqa: E731
    assert pedir(accion="hola")["resultado"]["version"] == __version__
    assert pedir(accion="llamar", sesion="inventada", servicio="productos", metodo="buscar")["error"] == "SesionVencida"
    assert "misma versión" in pedir(accion="ingresar", usuario="admin", clave=CLAVE, version="0.0.1")["mensaje"]

    sesion = pedir(accion="ingresar", usuario="caja1", clave=CLAVE, version=__version__)["resultado"]
    assert sesion["usuario"]["rol"] == "cajero" and "vender" in sesion["permisos"] and "*" not in sesion["permisos"]
    llamar = lambda servicio, metodo, *args, **kw: pedir(  # noqa: E731
        accion="llamar", sesion=sesion["sesion"], servicio=servicio, metodo=metodo, args=list(args), kwargs=kw)
    assert llamar("productos", "buscar", "yerba")["resultado"][0]["nombre"] == "Yerba 1 kg"
    # Un cajero no puede hacer por la red lo que no puede hacer en la pantalla.
    assert llamar("productos", "crear", {"nombre": "Trampa"})["error"] == "PermisoDenegado"
    assert llamar("config", "guardar", {"permitir_stock_negativo": "1"}, auditar=False)["error"] == "PermisoDenegado"
    assert llamar("reportes", "generar", "resumen", "2000-01-01", "2999-01-01")["error"] == "PermisoDenegado"
    assert llamar("sistema", "auditoria")["error"] == "PermisoDenegado"
    # Operaciones internas, privadas o inexistentes: no se pueden pedir desde otra computadora.
    for servicio, metodo in [("inventario", "mover"), ("productos", "actualizar_costo"), ("ventas", "asociar_externo"),
                             ("ventas", "_insertar_pago"), ("reportes", "cifras"), ("mp", "aplicar"), ("mp", "datos_consulta"),
                             ("mp", "_token"), ("copias", "restaurar"), ("db", "ejecutar"), ("usuarios", "iniciar_sesion"),
                             ("config", "ctx"), ("productos", "no_existe")]:
        respuesta = llamar(servicio, metodo, 1, 1)
        assert not respuesta["ok"] and "no está disponible" in respuesta["mensaje"] or "no existe" in respuesta["mensaje"], (servicio, metodo)
    assert ctx.productos.obtener(producto)["stock_mil"] == 10000 and len(ctx.productos.buscar()) == 1

    assert servidor.conectados()[0]["usuario"] == "Cajera Uno" and servidor.conectados()[0]["puesto"] == "Equipo 10.0.0.9"
    pedir(accion="salir", sesion=sesion["sesion"])
    assert servidor.conectados() == [] and llamar("productos", "buscar")["error"] == "SesionVencida"


def test_bloqueo_por_intentos_fallidos(servidor):
    for _ in range(5):
        assert "no son correctos" in servidor.atender({"accion": "ingresar", "usuario": "admin", "clave": "x", "version": __version__}, "10.0.0.5")["mensaje"]
    bloqueado = servidor.atender({"accion": "ingresar", "usuario": "admin", "clave": CLAVE, "version": __version__}, "10.0.0.5")
    assert "Demasiados intentos" in bloqueado["mensaje"]
    assert servidor.atender({"accion": "ingresar", "usuario": "admin", "clave": CLAVE, "version": __version__}, "10.0.0.6")["ok"]


# ---- cliente real por la red (TLS) -------------------------------------------------
def test_un_cliente_trabaja_contra_el_servidor(servidor, ctx, producto, tmp_path):
    remoto = conectar(servidor)
    assert remoto.remoto and remoto.db is None and remoto.es_admin and remoto.puede("anular")
    assert remoto.config.obtener("comercio_nombre") == ctx.config.obtener("comercio_nombre")

    nuevo = remoto.productos.crear({"nombre": "Azúcar", "costo": D("900"), "impuesto_pct": D("21"), "ganancia_pct": D("28"), "stock": D("5")})
    assert ctx.productos.obtener(nuevo)["precio_final_cent"] == 151250      # se guardó en la base del servidor
    venta = vender(remoto, producto, "2", medio="tarjeta")
    assert ctx.productos.obtener(producto)["stock_mil"] == 8000
    assert ctx.ventas.obtener(venta)["usuario"] == "Administrador"
    assert "Yerba 1 kg" in tickets.html_ticket(remoto, venta) and "Efectivo esperado" in tickets.html_cierre_caja(remoto, remoto.caja.abierta()["id"])
    assert remoto.ventas.devuelto(venta) == {}
    remoto.ventas.devolver(venta, {remoto.ventas.items(venta)[0]["id"]: D(1)}, "Roto", "tarjeta")
    assert list(remoto.ventas.devuelto(venta).values()) == [{"cantidad_mil": 1000, "total_cent": 1728571}]

    reporte = remoto.reportes.generar("resumen", "2000-01-01", "2999-01-01")
    csv_io.exportar_reporte(reporte, tmp_path / "resumen.csv")
    assert "Ventas totales (facturación, con impuestos);17285,71" in (tmp_path / "resumen.csv").read_text(encoding="utf-8-sig")
    archivo = tmp_path / "productos.csv"
    assert csv_io.exportar_productos(remoto, archivo) == 2
    archivo.write_text(archivo.read_text(encoding="utf-8-sig") + "N9;;Fideos;;;;;500;21;30;margen;;;;3;0;unidad;;\n", encoding="utf-8-sig")
    assert csv_io.importar_productos(remoto, archivo)["creados"] == 1 and ctx.productos.por_codigo("N9")["stock_mil"] == 3000

    with pytest.raises(ErrorNegocio, match="No hay stock suficiente"):          # los errores llegan con su mensaje
        vender(remoto, producto, "50")
    cajero = conectar(servidor, "caja1")
    with pytest.raises(PermisoDenegado):
        cajero.ventas.anular(venta, "x")
    with pytest.raises(PermisoDenegado):
        cajero.requiere("anular")
    assert vender(cajero, producto) and ctx.db.valor("SELECT COUNT(*) FROM ventas") == 2
    assert len(servidor.conectados()) == 2
    remoto.cliente.salir()
    with pytest.raises(SesionVencida):
        remoto.productos.buscar()


def test_la_impresion_es_de_cada_computadora(servidor, ctx):
    remoto = conectar(servidor)
    remoto.config.guardar({"impresora": "Térmica de la caja 2", "ticket_imprimir_automatico": True, "ticket_pie": "¡Vuelva pronto!"})
    assert remoto.config.obtener("impresora") == "Térmica de la caja 2" and remoto.config.booleano("ticket_imprimir_automatico")
    assert preferencias.leer()["impresora"] == "Térmica de la caja 2"
    assert ctx.config.obtener("impresora") == "" and ctx.config.obtener("ticket_pie") == "¡Vuelva pronto!"


def test_conexion_cifrada_y_huella_del_servidor(servidor):
    cliente = Cliente("127.0.0.1", servidor.puerto)
    assert cliente.hola()["version"] == __version__ and cliente.huella == servidor.huella and len(cliente.huella) == 64
    with pytest.raises(HuellaDistinta) as otro:                                 # otro servidor en la misma dirección
        Cliente("127.0.0.1", servidor.puerto, "0" * 64).hola()
    assert otro.value.huella == servidor.huella
    carpeta = preferencias._ruta().parent / "red"
    assert b"PRIVATE KEY" not in (carpeta / "servidor.clave.dpapi").read_bytes() and not list(carpeta.glob("*.tmp"))
    with pytest.raises(ErrorServidor, match="No se pudo conectar"):
        Cliente("127.0.0.1", 1, tiempo=2).hola()
    import urllib.request
    with pytest.raises(Exception):                                              # sin cifrado no se atiende
        urllib.request.urlopen(f"http://127.0.0.1:{servidor.puerto}/rpc", data=b"{}", timeout=3)


def test_varias_cajas_venden_a_la_vez_sin_romper_el_stock(servidor, ctx, producto):
    """Diez unidades en stock y cuatro cajas intentando vender cinco cada una: solo se venden diez."""
    resultados, errores = [], []

    def caja(n):
        try:
            remoto = conectar(servidor, "caja1" if n % 2 else "admin", f"Caja {n + 2}")
            for _ in range(5):
                try:
                    resultados.append(vender(remoto, producto))
                except ErrorNegocio as e:
                    errores.append(str(e))
        except Exception as e:  # pragma: no cover
            errores.append(f"inesperado: {e!r}")

    hilos = [threading.Thread(target=caja, args=(n,)) for n in range(4)]
    for h in hilos:
        h.start()
    local = [vender(ctx, producto) for _ in range(2) if ctx.productos.obtener(producto)["stock_mil"] > 0]  # la principal también vende
    for h in hilos:
        h.join(60)
    vendidas = len(resultados) + len(local)
    assert not [e for e in errores if "stock suficiente" not in e], errores
    assert ctx.productos.obtener(producto)["stock_mil"] == 10000 - vendidas * 1000 >= 0
    assert vendidas == ctx.db.valor("SELECT COUNT(*) FROM ventas") == len(set(resultados + local))
    assert vendidas == 10 or ctx.productos.obtener(producto)["stock_mil"] == 0
    assert ctx.db.valor("SELECT SUM(cantidad_mil) FROM movimientos_stock WHERE tipo = 'venta'") == -vendidas * 1000
    resumenes = [ctx.caja.resumen(c["id"]) for c in ctx.caja.listar()]
    assert len(resumenes) == 5 and {r["puesto"] for r in resumenes} == {"Caja principal", "Caja 2", "Caja 3", "Caja 4", "Caja 5"}
    assert sum(r["ventas_cantidad"] for r in resumenes) == vendidas                 # cada venta cae en la caja de su computadora
    assert all(r["cobrado_total_cent"] == r["ventas_cantidad"] * 1728571 == r["efectivo_esperado_cent"] for r in resumenes)
    assert next(r for r in resumenes if r["puesto"] == "Caja principal")["ventas_cantidad"] == len(local)


def test_una_venta_no_se_duplica_aunque_se_envie_dos_veces(servidor, ctx, producto):
    remoto = conectar(servidor)
    identificador = uuid.uuid4().hex
    assert vender(remoto, producto, uuid=identificador) == vender(remoto, producto, uuid=identificador)
    assert ctx.db.valor("SELECT COUNT(*) FROM ventas") == 1


# ---- facturación y Mercado Pago corren en el servidor ---------------------------------
def test_facturacion_y_mercado_pago_desde_un_cliente(servidor, ctx, producto):
    remoto = conectar(servidor)
    servicio = arca.crear_servicio(remoto)
    assert servicio.entorno == "homologacion" and not servicio.estado().disponible
    remoto.config.guardar({"fiscal_razon_social": "Almacén SRL", "fiscal_cuit": "20-12345678-6"})
    pedido = servicio.generar_pedido()                                          # la clave se crea y queda en el servidor
    assert isinstance(pedido, bytes) and b"CERTIFICATE REQUEST" in pedido
    assert servicio.estado_certificado()["pedido_pendiente"] is True
    with pytest.raises(ErrorNegocio, match="no es un certificado"):
        servicio.importar_certificado(b"basura")
    assert servicio.ventas("2000-01-01", "2999-01-01") == []

    mp = mercadopago.crear_servicio(remoto)
    assert mp.estado().disponible is False and mp.tiene_credencial() is False
    with pytest.raises(ErrorNegocio, match="APP_USR"):
        mp.guardar_credencial("no-es-un-token")
    cajero = conectar(servidor, "caja1")
    with pytest.raises(PermisoDenegado):
        arca.crear_servicio(cajero).generar_pedido()
    with pytest.raises(PermisoDenegado):
        mercadopago.crear_servicio(cajero).guardar_credencial("APP_USR-x")


def test_dos_cajas_no_facturan_la_misma_venta(ctx, producto):
    ctx.caja.abrir(0)
    venta = vender(ctx, producto)
    insertar = lambda: ctx.db.ejecutar(  # noqa: E731
        "INSERT INTO comprobantes_fiscales (venta_id, entorno, tipo, punto_venta, estado, total_cent, solicitado_en) "
        "VALUES (?, 'produccion', '6', 1, 'pendiente', 100, 'x')", (venta,))
    insertar()
    with pytest.raises(sqlite3.IntegrityError):
        insertar()


def test_la_base_se_puede_usar_desde_varios_hilos(ctx, producto):
    errores = []

    def trabajar():
        try:
            for _ in range(25):
                with ctx.db.transaccion():
                    actual = ctx.db.valor("SELECT stock_mil FROM productos WHERE id = ?", (producto,))
                    ctx.db.ejecutar("UPDATE productos SET stock_mil = ? WHERE id = ?", (actual + 1, producto))
        except Exception as e:  # pragma: no cover
            errores.append(repr(e))

    hilos = [threading.Thread(target=trabajar) for _ in range(6)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(30)
    assert not errores and ctx.productos.obtener(producto)["stock_mil"] == 10000 + 150


# ---- pantallas ------------------------------------------------------------------
def test_todas_las_pantallas_funcionan_en_un_cliente(app, servidor, ctx, producto, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from micomercio.ui.paginas import venta as modulo
    from micomercio.ui.ventana import MENU, VentanaPrincipal

    remoto = conectar(servidor)
    ventana = VentanaPrincipal(remoto)
    assert ventana.remoto and list(ventana.paginas) == [clave for clave, *_ in MENU if clave != "copias"]
    for clave in ventana.paginas:
        ventana.ir(clave)
    reportes = ventana.paginas["reportes"]
    for n in range(reportes.tipo.count()):
        reportes.tipo.setCurrentIndex(n)
    assert "Conectado a 127.0.0.1" in ventana.estado_red.text()
    assert "CLIENTE" in ventana.paginas["configuracion"].red.estado.text()

    class Cobro:
        def __init__(self, padre, medio, total):
            self.pago, self.vuelto_cent = {"medio": medio, "monto_cent": total, "estado": "confirmado"}, 0

        def exec(self):
            return QDialog.Accepted

    monkeypatch.setattr(modulo, "DialogoCobro", Cobro)
    monkeypatch.setattr(modulo.DialogoVentaRegistrada, "exec", lambda self: QDialog.Accepted)
    ventana.show()
    ventana.ir("venta")
    pagina = ventana.paginas["venta"]
    pagina.buscador.setText("7790001000012")
    pagina.enter()
    pagina.cobrar("efectivo")
    assert ctx.db.valor("SELECT COUNT(*) FROM ventas") == 1 and ctx.productos.obtener(producto)["stock_mil"] == 9000
    ventana.ir("historial")
    historial = ventana.paginas["historial"]
    assert historial.tabla.rowCount() == 1
    from micomercio.ui.paginas.historial import DialogoVenta

    detalle = DialogoVenta(historial, remoto, ctx.db.valor("SELECT id FROM ventas"))
    assert detalle.items.rowCount() == 1 and detalle.pagos.rowCount() == 1
    ventana.close()
    assert servidor.conectados() == []                                          # al cerrar, la sesión termina


def test_la_principal_enciende_y_apaga_la_red_desde_configuracion(app, ctx):
    from micomercio.ui.ventana import VentanaPrincipal

    ventana = VentanaPrincipal(ctx)
    ventana.ir("configuracion")
    panel = ventana.paginas["configuracion"].red
    assert "trabaja sola" in panel.estado.text() and ventana.servidor is None
    libre = Servidor(ctx.db, 0)
    libre.iniciar("127.0.0.1")
    puerto = libre.puerto
    libre.detener()
    preferencias.guardar(red_activa=True, red_puerto=puerto)
    ventana.aplicar_red()
    panel.refrescar()
    assert ventana.servidor.activo and "está activo" in panel.estado.text() and str(puerto) in panel.direcciones.text()
    assert Cliente("127.0.0.1", puerto).hola()["version"] == __version__
    assert f": {puerto}" in ventana.estado_red.text()
    preferencias.guardar(red_activa=False)
    ventana.aplicar_red()
    assert ventana.servidor is None
    ventana.close()


def test_eleccion_de_modo_e_ingreso_del_cliente(app, servidor, tmp_path, monkeypatch):
    from micomercio import app as arranque
    from micomercio.ui import acceso

    assert preferencias.leer()["modo"] == ""
    d = acceso.DialogoModo()
    assert d.servidor.isChecked() and d.red.isEnabled()
    d.cliente.setChecked(True)
    assert not d.red.isEnabled()
    d.guardar()
    assert d.valores() == {"modo": "cliente"}
    d = acceso.DialogoModo()
    d.red.setChecked(True)
    d.guardar()
    assert d.valores() == {"modo": "servidor", "red_activa": True, "red_puerto": 8765}

    # Una instalación anterior, que ya tiene datos, sigue siendo la principal sin preguntar nada.
    assert arranque._elegir_modo() == "servidor" and preferencias.leer()["modo"] == "servidor"

    preferencias.guardar(modo="cliente")
    c = acceso.DialogoConexion()
    assert c.host.text() == "" and not c.recordar.isChecked()
    with pytest.raises(ErrorNegocio, match="IP del servidor"):
        c.guardar()
    c.host.setText("127.0.0.1")
    c.puerto.setValue(servidor.puerto)
    c.usuario.setText("caja1")
    c.clave.setText("incorrecta")
    with pytest.raises(ErrorNegocio, match="no son correctos"):
        c.guardar()
    assert c.clave.text() == ""
    c.clave.setText(CLAVE)
    c.recordar.setChecked(True)
    c.guardar()
    assert c.ctx.usuario["usuario"] == "caja1" and c.ctx.remoto
    prefs = preferencias.leer()
    assert (prefs["servidor_host"], prefs["servidor_puerto"], prefs["servidor_huella"]) == ("127.0.0.1", servidor.puerto, servidor.huella)
    assert "clave" not in str(prefs).lower().replace("servidor.clave", "")       # nunca se guarda la contraseña

    c2 = acceso.DialogoConexion()                                               # la próxima vez ya vienen cargados
    assert c2.host.text() == "127.0.0.1" and c2.puerto.value() == servidor.puerto and c2.recordar.isChecked()
    assert c2.usuario.text() == "" and c2.clave.text() == ""
    c2.usuario.setText("admin")
    c2.clave.setText(CLAVE)
    c2.recordar.setChecked(False)
    c2.guardar()
    assert preferencias.leer()["servidor_host"] == ""
