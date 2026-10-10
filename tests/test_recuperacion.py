"""Recuperación de la contraseña del administrador."""
import re

import pytest

from micomercio import __version__
from micomercio.core.errores import ErrorNegocio, PermisoDenegado
from micomercio.red.cliente import Cliente, ContextoRemoto
from micomercio.red.servidor import Servidor
from micomercio.servicios import Contexto

CLAVE = "clave-de-prueba"


def test_codigo_de_recuperacion(ctx):
    assert not ctx.usuarios.tiene_codigo()
    codigo = ctx.usuarios.generar_codigo_recuperacion()
    assert re.fullmatch(r"([A-HJ-NP-Z2-9]{4}-){4}[A-HJ-NP-Z2-9]{4}", codigo) and ctx.usuarios.tiene_codigo()
    guardado = " ".join(str(v) for fila in ctx.db.consultar("SELECT * FROM usuarios") for v in tuple(fila))
    assert codigo not in guardado and codigo.replace("-", "") not in guardado       # en la base queda solo la huella
    assert codigo not in " ".join(str(f["detalle"]) for f in ctx.db.consultar("SELECT detalle FROM auditoria"))
    assert "recuperacion_hash" not in ctx.usuarios.listar()[0].keys()

    nuevo = Contexto(ctx.db)                                                       # otra persona, sin sesión iniciada
    for usuario, intento in [("admin", "AAAA-BBBB-CCCC-DDDD-EEEE"), ("admin", ""), ("nadie", codigo), ("", "")]:
        with pytest.raises(ErrorNegocio, match="no son correctos"):
            nuevo.usuarios.recuperar(usuario, intento, "otra-clave")
    with pytest.raises(ErrorNegocio, match="al menos"):
        nuevo.usuarios.recuperar("admin", codigo, "x")
    assert nuevo.usuarios.iniciar_sesion("admin", CLAVE)                            # nada cambió todavía

    otro = Contexto(ctx.db)
    codigo2 = otro.usuarios.recuperar("ADMIN", codigo.lower().replace("-", " "), "clave-nueva")   # tolera cómo se escribe
    assert codigo2 != codigo and re.fullmatch(r"([A-HJ-NP-Z2-9]{4}-){4}[A-HJ-NP-Z2-9]{4}", codigo2)
    with pytest.raises(ErrorNegocio):
        otro.usuarios.iniciar_sesion("admin", CLAVE)                                # la anterior ya no sirve
    assert otro.usuarios.iniciar_sesion("admin", "clave-nueva")["rol"] == "admin"
    with pytest.raises(ErrorNegocio, match="no son correctos"):                     # el código sirve una sola vez
        otro.usuarios.recuperar("admin", codigo, "tercera-clave")
    assert otro.usuarios.recuperar("admin", codigo2, "tercera-clave")
    assert "clave_recuperada" in [a["accion"] for a in otro.auditoria()]


def test_el_codigo_es_solo_para_administradores(ctx):
    ctx.usuarios.crear("caja1", "Cajera", CLAVE, "cajero")
    cajera = Contexto(ctx.db)
    cajera.usuarios.iniciar_sesion("caja1", CLAVE)
    with pytest.raises(ErrorNegocio, match="solo para administradores"):
        cajera.usuarios.generar_codigo_recuperacion()
    codigo = ctx.usuarios.generar_codigo_recuperacion()
    with pytest.raises(ErrorNegocio, match="no son correctos"):                     # el código del admin no sirve para otro usuario
        cajera.usuarios.recuperar("caja1", codigo, "otra-clave")
    assert not cajera.usuarios.tiene_codigo() and cajera.usuarios.aviso_de_seguridad() == ""
    ctx.usuarios.crear("jefa", "Otra administradora", CLAVE, "admin")
    ctx.usuarios.actualizar(ctx.usuario_id, "Administrador", "admin", False)        # un administrador desactivado no se recupera
    with pytest.raises(ErrorNegocio, match="no son correctos"):
        Contexto(ctx.db).usuarios.recuperar("admin", codigo, "otra-clave")


def test_recuperar_desde_una_computadora_cliente(ctx):
    codigo = ctx.usuarios.generar_codigo_recuperacion()
    servidor = Servidor(ctx.db, 0)
    servidor.iniciar("127.0.0.1")
    try:
        cliente = Cliente("127.0.0.1", servidor.puerto)
        with pytest.raises(ErrorNegocio, match="no son correctos"):
            cliente.recuperar("admin", "AAAA-AAAA-AAAA-AAAA-AAAA", "clave-nueva")
        nuevo = cliente.recuperar("admin", codigo, "clave-nueva")
        remoto = ContextoRemoto(cliente)
        assert remoto.ingresar("admin", "clave-nueva", "Caja 2")["rol"] == "admin" and remoto.usuarios.tiene_codigo() is True
        otro_codigo = remoto.usuarios.generar_codigo_recuperacion()                 # desde el cliente también se puede renovar
        assert otro_codigo != nuevo
        with pytest.raises(ErrorNegocio, match="no está disponible"):               # pero no las operaciones internas
            remoto.usuarios.restablecer_sin_codigo(1, "x")
        with pytest.raises(ErrorNegocio, match="no está disponible"):
            remoto.usuarios.recuperar("admin", otro_codigo, "x")
    finally:
        servidor.detener()
    pedir = lambda **p: servidor.atender({"accion": "recuperar", "usuario": "admin", "clave": "otra-clave", **p}, "10.0.0.7")  # noqa: E731
    for _ in range(5):
        assert "no son correctos" in pedir(codigo="MALO")["mensaje"]
    assert "Demasiados intentos" in pedir(codigo=otro_codigo)["mensaje"]            # adivinar por la red se frena
    assert "Demasiados intentos" in servidor.atender({"accion": "ingresar", "usuario": "admin", "clave": "clave-nueva",
                                                      "version": __version__}, "10.0.0.7")["mensaje"]


def test_herramienta_de_emergencia_deja_rastro(ctx):
    ctx.usuarios.generar_codigo_recuperacion()
    emergencia = Contexto(ctx.db)                                                   # sin sesión: nadie recuerda la contraseña
    assert [u["usuario"] for u in emergencia.usuarios.administradores()] == ["admin"]
    with pytest.raises(ErrorNegocio):
        emergencia.usuarios.restablecer_sin_codigo(999, "clave-nueva")
    emergencia.usuarios.restablecer_sin_codigo(ctx.usuario_id, "clave-nueva")
    assert "clave_restablecida" in [a["accion"] for a in emergencia.auditoria()]
    with pytest.raises(ErrorNegocio):
        emergencia.usuarios.iniciar_sesion("admin", CLAVE)
    emergencia.usuarios.iniciar_sesion("admin", "clave-nueva")
    assert not emergencia.usuarios.tiene_codigo()                                   # el código anterior quedó anulado
    aviso = emergencia.usuarios.aviso_de_seguridad()
    assert "fue restablecida" in aviso and "admin" in aviso
    assert emergencia.usuarios.aviso_de_seguridad() == ""                           # se avisa una sola vez
    ctx.usuarios.crear("caja1", "Cajera", CLAVE, "cajero")
    with pytest.raises(ErrorNegocio):                                               # solo administradores
        emergencia.usuarios.restablecer_sin_codigo(ctx.db.valor("SELECT id FROM usuarios WHERE usuario = 'caja1'"), "x-clave")


def test_pantallas_de_recuperacion(app, ctx, monkeypatch):
    from micomercio.ui import acceso
    from micomercio.ui.ventana import VentanaPrincipal

    codigo = ctx.usuarios.generar_codigo_recuperacion()
    monkeypatch.setattr(acceso, "informar", lambda *a, **k: None)
    d = acceso.DialogoRecuperar(None, Contexto(ctx.db).usuarios.recuperar, "admin")
    d.codigo.setText(codigo)
    d.clave.setText("clave-nueva")
    d.clave2.setText("distinta")
    with pytest.raises(ErrorNegocio, match="no coinciden"):
        d.guardar()
    d.clave2.setText("clave-nueva")
    d.guardar()
    assert d.codigo_nuevo and d.codigo_nuevo != codigo

    c = acceso.DialogoCodigo(None, d.codigo_nuevo, ctx)
    assert not c.boton_aceptar.isEnabled()                                          # hay que confirmar que se guardó
    c.reject()
    assert not c.result()
    c.copiar()
    assert app.clipboard().text() == d.codigo_nuevo
    c.guardado.setChecked(True)
    assert c.boton_aceptar.isEnabled()

    ctx.usuarios.restablecer_sin_codigo(ctx.usuario_id, CLAVE)                      # deja el aviso y borra el código
    mensajes, mostrados = [], []
    monkeypatch.setattr("micomercio.ui.comunes.advertir", lambda padre, texto, titulo="": mensajes.append(texto))
    monkeypatch.setattr("micomercio.ui.comunes.confirmar", lambda *a, **k: True)
    monkeypatch.setattr(acceso.DialogoCodigo, "exec", lambda self: mostrados.append(self.codigo))
    ventana = VentanaPrincipal(ctx)
    ventana.revisar_seguridad()
    assert "fue restablecida" in mensajes[0] and len(mostrados) == 1 and ctx.usuarios.tiene_codigo()
    ventana.revisar_seguridad()                                                     # la segunda vez no molesta
    assert len(mensajes) == 1 and len(mostrados) == 1
    ventana.ir("configuracion")
    ventana.paginas["configuracion"].codigo_recuperacion()
    assert len(mostrados) == 2 and mostrados[1] != mostrados[0]
    ventana.close()

    ctx.usuarios.crear("caja1", "Cajera", CLAVE, "cajero")
    ctx.usuarios.iniciar_sesion("caja1", CLAVE)
    cajera = VentanaPrincipal(ctx)
    cajera.revisar_seguridad()                                                      # a un cajero no se le ofrece nada
    assert len(mostrados) == 2
    cajera.close()
    with pytest.raises(PermisoDenegado):
        ctx.requiere("configuracion")
