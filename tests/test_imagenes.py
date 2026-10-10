"""Imágenes de productos y catálogo por código de barras."""
import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QColor, QImage

from micomercio.core.errores import ErrorNegocio, PermisoDenegado
from micomercio.red.cliente import Cliente, ContextoRemoto
from micomercio.red.servidor import Servidor
from micomercio.servicios import catalogo_imagenes as catalogo
from micomercio.ui import imagenes


def imagen_de_prueba(ancho=1200, alto=800, formato="PNG", color="#2563EB") -> bytes:
    imagen = QImage(ancho, alto, QImage.Format_ARGB32)
    imagen.fill(QColor(color))
    salida = QByteArray()
    memoria = QBuffer(salida)
    memoria.open(QIODevice.WriteOnly)
    imagen.save(memoria, formato)
    return bytes(salida)


def test_la_imagen_se_guarda_chica_y_en_jpeg(app):
    datos = imagenes.normalizar(imagen_de_prueba())
    resultado = QImage()
    assert resultado.loadFromData(QByteArray(datos)) and datos[:3] == b"\xff\xd8\xff"
    assert (resultado.width(), resultado.height()) == (500, 333) and len(datos) < 60_000
    chica = QImage()
    chica.loadFromData(QByteArray(imagenes.normalizar(imagen_de_prueba(200, 100))))
    assert (chica.width(), chica.height()) == (200, 100)                 # las chicas no se agrandan
    for basura in (b"", b"esto no es una imagen", b"\xff\xd8\xff corrupto"):
        with pytest.raises(ErrorNegocio, match="no es una imagen"):
            imagenes.normalizar(basura)
    assert imagenes.pixmap(datos, 150).width() == 150 and imagenes.pixmap(None, 150) is None


def test_nombres_posibles_de_un_codigo_de_barras():
    assert catalogo.candidatos("7790001000012")[0] == "7790001000012"
    # El mismo producto puede estar cargado con o sin ceros adelante.
    assert "0076625211992" in catalogo.candidatos("76625211992") and "76625211992" in catalogo.candidatos("0076625211992")
    assert "00014271" in catalogo.candidatos("14271")
    for malo in ("", "12", "../secreto", "779 000", "a/b", "x" * 40, None):
        assert catalogo.candidatos(malo) == []                           # nada que pueda armar otra dirección


def test_busqueda_en_el_catalogo():
    jpeg = b"\xff\xd8\xff" + b"0" * 100
    pedidos = []

    def obtener(url):
        pedidos.append(url)
        return jpeg if url.endswith("/0076625211992.jpg") else None

    assert catalogo.buscar("76625211992", obtener) == jpeg
    assert all(u.startswith(catalogo.URL_BASE) and u.endswith(".jpg") for u in pedidos)
    assert catalogo.buscar("7790001000012", obtener) is None
    assert catalogo.buscar("", obtener) is None
    assert catalogo.buscar("7790001000012", lambda url: b"<html>no encontrado</html>") is None   # no es una imagen

    def sin_red(url):
        raise catalogo.SinConexion("sin Internet")

    with pytest.raises(catalogo.SinConexion):
        catalogo.buscar("7790001000012", sin_red)


def test_imagen_del_producto(app, ctx, producto):
    foto = imagenes.normalizar(imagen_de_prueba())
    assert ctx.productos.imagen(producto) is None and ctx.productos.obtener(producto)["tiene_imagen"] == 0
    assert [p["id"] for p in ctx.productos.sin_imagen()] == [producto]
    ctx.productos.guardar_imagen(producto, foto, "catalogo")
    assert ctx.productos.imagen(producto) == foto and ctx.productos.obtener(producto)["tiene_imagen"] == 1
    assert ctx.productos.buscar("yerba")[0]["tiene_imagen"] == 1 and ctx.productos.sin_imagen() == []
    assert "datos" not in ctx.productos.obtener(producto).keys()         # la lista de productos no carga las imágenes

    otra = imagenes.normalizar(imagen_de_prueba(color="#DC2626"))
    ctx.productos.guardar_imagen(producto, otra)                         # se reemplaza
    assert ctx.productos.imagen(producto) == otra and ctx.db.valor("SELECT origen FROM producto_imagenes") == "manual"
    for invalida in (b"no es jpeg", imagen_de_prueba(), b"\xff\xd8\xff" + b"0" * 500_000, "texto"):
        with pytest.raises(ErrorNegocio):
            ctx.productos.guardar_imagen(producto, invalida)
    with pytest.raises(ErrorNegocio):
        ctx.productos.guardar_imagen(9999, foto)
    ctx.productos.quitar_imagen(producto)
    assert ctx.productos.imagen(producto) is None

    nuevo = ctx.productos.crear({"nombre": "Con foto", "codigo_barras": "7790001000999", "imagen": foto, "imagen_origen": "catalogo"})
    assert ctx.productos.imagen(nuevo) == foto
    datos = ctx.productos.datos_para_duplicar(nuevo)
    datos.update(codigo="X9", codigo_barras="7790001000999", nombre="Con foto")
    ctx.productos.actualizar(nuevo, datos)                               # editar sin tocar la imagen la conserva
    assert ctx.productos.imagen(nuevo) == foto
    ctx.productos.actualizar(nuevo, {**datos, "quitar_imagen": True})
    assert ctx.productos.imagen(nuevo) is None
    ctx.productos.cambiar_estado(nuevo, False)
    assert nuevo not in [p["id"] for p in ctx.productos.sin_imagen()]    # los inactivos no se cuentan

    ctx.usuarios.crear("caja1", "Cajera", "clave-de-prueba", "cajero")
    ctx.usuarios.iniciar_sesion("caja1", "clave-de-prueba")
    with pytest.raises(PermisoDenegado):
        ctx.productos.guardar_imagen(producto, foto)
    assert ctx.productos.imagen(producto) is None                        # pero ver, puede


def test_la_imagen_viaja_entre_computadoras(app, ctx, producto):
    foto = imagenes.normalizar(imagen_de_prueba())
    servidor = Servidor(ctx.db, 0)
    servidor.iniciar("127.0.0.1")
    try:
        remoto = ContextoRemoto(Cliente("127.0.0.1", servidor.puerto))
        remoto.ingresar("admin", "clave-de-prueba", "Caja 2")
        remoto.productos.guardar_imagen(producto, foto, "catalogo")
        assert ctx.productos.imagen(producto) == foto and remoto.productos.imagen(producto) == foto
        nuevo = remoto.productos.crear({"nombre": "Desde la caja 2", "imagen": foto})
        assert ctx.productos.imagen(nuevo) == foto
    finally:
        servidor.detener()


def test_al_cargar_un_producto_la_imagen_aparece_por_el_codigo_de_barras(app, ctx, monkeypatch, tmp_path):
    from micomercio.ui.paginas import productos as modulo

    foto_catalogo = imagen_de_prueba(800, 800, "JPG")
    d = modulo.DialogoProducto(None, ctx)
    assert d.foto.text() == "Sin imagen" and not d.b_quitar_foto.isEnabled()
    d.nombre.setText("Galletitas")
    d.barras.setText("7790001000555")
    d.imagen_encontrada("7790001000555", foto_catalogo)                  # lo que devuelve la búsqueda en el catálogo
    assert d.imagen is not None and d.imagen_origen == "catalogo" and "catálogo" in d.estado_foto.text()
    assert not d.foto.pixmap().isNull() and d.b_quitar_foto.isEnabled()
    d.guardar()
    assert ctx.productos.imagen(d.producto_id) == d.imagen
    assert ctx.db.valor("SELECT origen FROM producto_imagenes WHERE producto_id = ?", (d.producto_id,)) == "catalogo"

    e = modulo.DialogoProducto(None, ctx, d.producto_id)                 # al editar, la imagen ya está
    assert e.imagen == d.imagen and not e.imagen_cambiada
    e.imagen_encontrada("7790001000555", imagen_de_prueba(100, 100, "JPG"))   # no pisa la que ya tiene
    assert e.imagen == d.imagen
    e.quitar_imagen()
    e.guardar()
    assert ctx.productos.imagen(d.producto_id) is None

    f = modulo.DialogoProducto(None, ctx)
    f.barras.setText("111122223333")
    f.imagen_encontrada("999", foto_catalogo)                            # respuesta de un código que ya se cambió: se ignora
    assert f.imagen is None
    f.imagen_encontrada("111122223333", None)
    assert f.imagen is None and "no tiene imagen" in f.estado_foto.text()
    f.imagen_encontrada("111122223333", b"no es una imagen")             # una respuesta rara no rompe nada
    assert f.imagen is None

    # Búsqueda real en segundo plano, en la carpeta del catálogo.
    monkeypatch.delenv("EXAPYME_SIN_CATALOGO")
    carpeta = tmp_path / "catalogo"
    carpeta.mkdir()
    (carpeta / "111122223333.jpg").write_bytes(foto_catalogo)
    ctx.config.guardar({"catalogo_carpeta": str(carpeta)})
    f.buscar_en_catalogo()
    f.busqueda.wait(5000)
    app.processEvents()
    assert f.imagen is not None and f.imagen_origen == "catalogo"


def test_buscar_imagenes_para_los_productos_que_no_tienen(app, ctx, producto, monkeypatch, tmp_path):
    from micomercio.ui.paginas import productos as modulo, venta
    from micomercio.ui.ventana import VentanaPrincipal

    foto = imagen_de_prueba(600, 600, "JPG")
    sin_catalogo = ctx.productos.crear({"nombre": "Artesanal", "codigo_barras": "2000000000017", "stock": 3})
    ctx.productos.crear({"nombre": "Sin código de barras"})
    avisos = []
    monkeypatch.setattr(modulo, "confirmar", lambda *a, **k: True)
    monkeypatch.setattr(modulo, "informar", lambda padre, texto, titulo="": avisos.append(texto))
    ventana0 = VentanaPrincipal(ctx)
    ventana0.ir("productos")
    with pytest.raises(ErrorNegocio, match="no hay un catálogo"):       # sin catálogo configurado no hay dónde buscar
        ventana0.paginas["productos"].completar_imagenes()
    ventana0.close()
    carpeta = tmp_path / "catalogo"
    carpeta.mkdir()
    (carpeta / "7790001000012.jpg").write_bytes(foto)
    ctx.config.guardar({"catalogo_carpeta": str(carpeta)})
    ventana = VentanaPrincipal(ctx)
    ventana.show()
    ventana.ir("productos")
    ventana.paginas["productos"].completar_imagenes()
    assert ctx.productos.imagen(producto) is not None and ctx.productos.imagen(sin_catalogo) is None
    assert "Se cargaron 1 imágenes" in avisos[0]

    ctx.caja.abrir(0)
    ventana.ir("venta")
    pagina = ventana.paginas["venta"]
    pagina.agregar(ctx.productos.obtener(producto))
    assert not pagina.foto.pixmap().isNull()                             # el cajero ve la foto de lo que escaneó
    pagina.agregar(ctx.productos.obtener(sin_catalogo))
    assert pagina.foto.pixmap().isNull()
    pagina.reiniciar()
    assert pagina.foto.pixmap().isNull() and venta is not None
    ventana.close()


def test_catalogo_en_una_carpeta_del_comercio(app, ctx, producto, tmp_path):
    carpeta = tmp_path / "fotos"
    carpeta.mkdir()
    original = imagen_de_prueba(900, 900, "PNG")
    (carpeta / "0076625211992.png").write_bytes(original)               # nombre con cero adelante, en PNG
    (carpeta / "7790001000012.jpg").write_bytes(imagen_de_prueba(300, 300, "JPG"))
    (carpeta / "notas.txt").write_text("no es una imagen")
    assert ctx.productos.estado_catalogo()["existe"] is False and ctx.productos.imagen_de_catalogo("7790001000012") is None
    ctx.config.guardar({"catalogo_carpeta": str(carpeta)})
    assert ctx.productos.estado_catalogo() == {"carpeta": str(carpeta), "existe": True, "imagenes": 2}
    assert ctx.productos.imagen_de_catalogo("76625211992") == original   # el lector lo lee sin el cero
    assert ctx.productos.imagen_de_catalogo("7790001000012")[:3] == b"\xff\xd8\xff"
    for codigo in ("123456789", "", "..\\..\\secreto", "../notas", "notas.txt"):
        assert ctx.productos.imagen_de_catalogo(codigo) is None          # nunca lee fuera del catálogo
    assert imagenes.normalizar(ctx.productos.imagen_de_catalogo("76625211992"))[:3] == b"\xff\xd8\xff"

    servidor = Servidor(ctx.db, 0)                                       # una caja cliente usa el catálogo del servidor
    servidor.iniciar("127.0.0.1")
    try:
        remoto = ContextoRemoto(Cliente("127.0.0.1", servidor.puerto))
        remoto.ingresar("admin", "clave-de-prueba", "Caja 2")
        assert remoto.productos.imagen_de_catalogo("76625211992") == original
        assert remoto.productos.estado_catalogo()["imagenes"] == 2
    finally:
        servidor.detener()
