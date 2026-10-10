"""Una caja diaria por computadora, cada una con su propio arqueo."""
import sqlite3

import pytest

from conftest import vender
from micomercio import __version__
from micomercio.core.errores import ErrorNegocio, PermisoDenegado
from micomercio.db import BaseDatos
from micomercio.db.esquema import MIGRACIONES
from micomercio.red.servidor import Servidor
from micomercio.servicios import Contexto, tickets

PRECIO = 1728571


def otra_computadora(ctx, puesto: str, usuario: str | None = None) -> Contexto:
    """Otra computadora trabajando sobre los mismos datos."""
    otra = Contexto(ctx.db)
    otra.puesto = puesto
    if usuario:
        otra.usuarios.iniciar_sesion(usuario, "clave-de-prueba")
    else:
        otra.usuario = dict(ctx.usuario)
    return otra


def test_cada_computadora_tiene_su_caja_y_su_arqueo(ctx, producto):
    caja2 = otra_computadora(ctx, "Caja 2")
    principal = ctx.caja.abrir(100000)
    with pytest.raises(ErrorNegocio, match="caja está cerrada"):       # la caja de la principal no sirve para la otra
        vender(caja2, producto)
    segunda = caja2.caja.abrir(50000)
    assert segunda != principal and ctx.caja.abierta()["id"] == principal and caja2.caja.abierta()["id"] == segunda
    with pytest.raises(ErrorNegocio, match="ya tiene la caja abierta"):
        caja2.caja.abrir(0)

    vender(ctx, producto, "2")                                          # efectivo en la principal
    vender(caja2, producto)                                             # efectivo en la caja 2
    vender(caja2, producto, medio="tarjeta")
    caja2.caja.registrar_movimiento("salida", 20000, "Cambio para la principal")
    ctx.caja.registrar_movimiento("entrada", 20000, "Cambio de la caja 2")

    r1, r2 = ctx.caja.resumen(principal), caja2.caja.resumen(segunda)
    assert (r1["puesto"], r1["ventas_cantidad"], r1["efectivo_esperado_cent"]) == ("Caja principal", 1, 100000 + 2 * PRECIO + 20000)
    assert (r2["puesto"], r2["ventas_cantidad"], r2["efectivo_esperado_cent"]) == ("Caja 2", 2, 50000 + PRECIO - 20000)
    assert r2["cobrado_cent"]["tarjeta"] == PRECIO and r1["cobrado_cent"]["tarjeta"] == 0
    assert ctx.productos.obtener(producto)["stock_mil"] == 6000         # el stock es uno solo para todas

    cierre2 = caja2.caja.cerrar(50000 + PRECIO - 20000 - 1500, "Faltó cambio")     # arqueo propio
    assert cierre2["diferencia_cent"] == -1500 and caja2.caja.abierta() is None
    assert ctx.caja.abierta()["id"] == principal                        # la principal sigue abierta
    vender(ctx, producto)
    assert ctx.caja.cerrar(100000 + 3 * PRECIO + 20000)["diferencia_cent"] == 0
    assert "Caja 2" in tickets.html_cierre_caja(ctx, segunda) and "Caja principal" in tickets.html_cierre_caja(ctx, principal)
    assert [c["puesto"] for c in ctx.caja.abiertas()] == []
    assert caja2.caja.ultima()["id"] == segunda and ctx.caja.ultima()["id"] == principal

    reporte = ctx.reportes.generar("cajas", "2000-01-01", "2999-01-01")
    assert [(f[1], f[5], f[11]) for f in reporte.filas] == [("Caja 2", 2, -1500), ("Caja principal", 2, 0)]
    assert ctx.reportes.cifras("2000-01-01", "2999-01-01")["ventas_cantidad"] == 4     # los reportes suman todas


def test_el_dinero_entra_y_sale_por_la_caja_de_quien_opera(ctx, producto):
    caja2 = otra_computadora(ctx, "Caja 2")
    principal, segunda = ctx.caja.abrir(0), caja2.caja.abrir(0)
    pendiente = vender(caja2, producto, medio="transferencia", estado="pendiente")
    ctx.ventas.confirmar_pago(ctx.ventas.pagos(pendiente)[0]["id"])     # lo confirma la principal
    assert ctx.caja.resumen(principal)["cobrado_cent"]["transferencia"] == PRECIO
    assert caja2.caja.resumen(segunda)["cobrado_total_cent"] == 0 and caja2.caja.resumen(segunda)["ventas_cantidad"] == 1

    venta = vender(caja2, producto, "2")
    ctx.ventas.devolver(venta, {ctx.ventas.items(venta)[0]["id"]: 1}, "Devuelve en la otra caja")   # devuelve la principal
    assert ctx.caja.resumen(principal)["devoluciones_cent"] == PRECIO
    assert ctx.caja.resumen(principal)["efectivo_esperado_cent"] == -PRECIO
    assert caja2.caja.resumen(segunda)["efectivo_esperado_cent"] == 2 * PRECIO

    caja2.caja.cerrar(2 * PRECIO)
    with pytest.raises(ErrorNegocio, match="caja está cerrada"):       # con su caja cerrada, la caja 2 no anula
        caja2.ventas.anular(venta, "x")
    ctx.ventas.anular(venta, "Anula la principal")
    assert ctx.caja.resumen(principal)["devoluciones_cent"] == 2 * PRECIO


def test_solo_el_administrador_cierra_la_caja_de_otra_computadora(ctx, producto):
    ctx.usuarios.crear("caja1", "Cajera", "clave-de-prueba", "cajero")
    ctx.usuarios.crear("caja2", "Cajero Dos", "clave-de-prueba", "cajero")
    uno, dos = otra_computadora(ctx, "Caja 1", "caja1"), otra_computadora(ctx, "Caja 2", "caja2")
    primera, segunda = uno.caja.abrir(1000), dos.caja.abrir(2000)
    vender(dos, producto)
    assert [c["id"] for c in uno.caja.listar()] == [primera]            # un cajero ve solo las jornadas de su caja
    assert [c["puesto"] for c in ctx.caja.listar()] == ["Caja 2", "Caja 1"]
    assert [c["puesto"] for c in ctx.caja.abiertas()] == ["Caja 1", "Caja 2"]
    with pytest.raises(PermisoDenegado):
        uno.caja.cerrar(0, "", segunda)
    assert dos.caja.abierta() is not None

    cierre = ctx.caja.cerrar(2000 + PRECIO, "Quedó abierta al apagarse", segunda)   # el administrador sí puede
    assert cierre["estado"] == "cerrada" and cierre["puesto"] == "Caja 2" and dos.caja.abierta() is None
    with pytest.raises(ErrorNegocio, match="ya está cerrada"):
        ctx.caja.cerrar(0, "", segunda)
    assert uno.caja.cerrar(1000, "", primera)["diferencia_cent"] == 0   # la propia se puede cerrar por número
    assert ctx.caja.abierta() is None                                   # el administrador nunca abrió la suya


def test_el_nombre_de_la_caja_no_distingue_mayusculas(ctx):
    ctx.caja.abrir(0)
    otra = otra_computadora(ctx, "CAJA PRINCIPAL")
    assert otra.caja.abierta() is not None
    with pytest.raises(sqlite3.IntegrityError):
        ctx.db.ejecutar("INSERT INTO cajas (abierta_en, saldo_inicial_cent, puesto) VALUES ('x', 0, 'caja principal')")


def test_migracion_conserva_la_caja_abierta(tmp_path):
    ruta = tmp_path / "anterior.db"
    conn = sqlite3.connect(ruta)
    for n, migracion in enumerate(MIGRACIONES[:4], start=1):
        conn.executescript(f"BEGIN;{migracion}PRAGMA user_version = {n};COMMIT;")
    conn.execute("INSERT INTO cajas (abierta_en, saldo_inicial_cent) VALUES ('2026-10-09 09:00:00', 150000)")
    conn.commit()
    conn.close()
    db = BaseDatos(ruta)
    ctx = Contexto(db)
    assert db.valor("PRAGMA user_version") == len(MIGRACIONES)
    abierta = ctx.caja.abierta()
    assert abierta["puesto"] == "Caja principal" and abierta["saldo_inicial_cent"] == 150000
    db.cerrar()


def test_dos_computadoras_no_pueden_usar_el_mismo_nombre(ctx):
    servidor = Servidor(ctx.db, 0, "Caja principal")
    ingresar = lambda ip, puesto: servidor.atender(  # noqa: E731
        {"accion": "ingresar", "usuario": "admin", "clave": "clave-de-prueba", "version": __version__, "puesto": puesto}, ip)
    primera = ingresar("10.0.0.2", "  Caja   2 ")
    assert primera["ok"] and primera["resultado"]["puesto"] == "Caja 2"
    assert "nombre de caja «caja 2»" in ingresar("10.0.0.3", "caja 2")["mensaje"]      # otra computadora, mismo nombre
    assert "nombre de caja" in ingresar("10.0.0.3", "Caja Principal")["mensaje"]       # el de la computadora principal
    assert ingresar("10.0.0.2", "Caja 2")["ok"]                                        # la misma computadora, otro usuario
    assert ingresar("10.0.0.3", "Caja 3")["ok"]
    sesion = primera["resultado"]["sesion"]
    abrir = servidor.atender({"accion": "llamar", "sesion": sesion, "servicio": "caja", "metodo": "abrir", "args": [0]}, "10.0.0.2")
    assert abrir["ok"] and ctx.db.uno("SELECT puesto FROM cajas WHERE id = ?", (abrir["resultado"],))["puesto"] == "Caja 2"
    assert ctx.caja.abierta() is None


def test_pantalla_de_caja_con_varias_computadoras(app, ctx, producto, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from micomercio.ui.paginas import caja as modulo
    from micomercio.ui.ventana import VentanaPrincipal

    caja2 = otra_computadora(ctx, "Caja 2")
    ajena = caja2.caja.abrir(0)
    vender(caja2, producto)
    ventana = VentanaPrincipal(ctx)
    ventana.ir("caja")
    pagina = ventana.paginas["caja"]
    assert pagina.estado.text() == "Caja principal: CERRADA" and not pagina.b_abrir.isHidden()
    assert "Caja 2 (Administrador)" in pagina.otras.text() and pagina.tabla.item(0, 1).text() == "Caja 2"
    assert ventana.estado_caja.text() == "Caja principal: cerrada"
    pagina.tabla.seleccionar_id(ajena)
    assert "Caja 2 · jornada" in pagina.titulo_resumen.text() and not pagina.b_cerrar_otra.isHidden()

    class Cierre:
        def __init__(self, padre, esperado):
            self.contado = type("C", (), {"valor": lambda s: PRECIO / 100})()
            self.notas = type("N", (), {"text": lambda s: "Cerrada desde la principal"})()

        def exec(self):
            return QDialog.Accepted

    monkeypatch.setattr(modulo, "DialogoCierre", Cierre)
    monkeypatch.setattr(modulo, "confirmar", lambda *a, **k: True)
    pagina.cerrar_otra()
    assert caja2.caja.abierta() is None and ctx.caja.resumen(ajena)["diferencia_cent"] == 0
    assert pagina.otras.isHidden() and pagina.b_cerrar_otra.isHidden()

    red = ventana.paginas["configuracion"].red
    ventana.ir("configuracion")
    assert red.puesto.text() == "Caja principal"
    ctx.caja.abrir(0)
    red.puesto.setText("Mostrador")
    with pytest.raises(ErrorNegocio, match="Cerrá la caja"):            # no se renombra con la caja abierta
        red.guardar()
    ctx.caja.cerrar(0)
    monkeypatch.setattr("micomercio.ui.paginas.config_red.informar", lambda *a, **k: None)
    red.guardar()
    assert ctx.puesto == "Mostrador" and ctx.caja.abierta() is None
    ventana.close()
