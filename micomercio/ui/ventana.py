from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QMainWindow, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from .. import NOMBRE_APP, __version__, preferencias
from ..core.errores import ErrorNegocio
from ..registro import log
from ..servicios.contexto import ROLES
from . import tema
from .actualizacion import GestorActualizaciones
from .comunes import etiqueta
from .paginas.caja import PaginaCaja
from .paginas.clientes import PaginaClientes
from .paginas.compras import PaginaCompras
from .paginas.configuracion import PaginaConfiguracion
from .paginas.copias import PaginaCopias
from .paginas.facturacion import PaginaFacturacion
from .paginas.guia import PaginaGuia
from .paginas.historial import PaginaHistorial
from .paginas.inicio import PaginaInicio
from .paginas.inventario import PaginaInventario
from .paginas.productos import PaginaProductos
from .paginas.reportes import PaginaReportes
from .paginas.venta import PaginaVenta

# (clave, texto del menú, pantalla, permiso necesario)
MENU = [
    ("inicio", "Inicio", PaginaInicio, None),
    ("venta", "Nueva venta", PaginaVenta, "vender"),
    ("productos", "Productos", PaginaProductos, "productos_ver"),
    ("inventario", "Inventario", PaginaInventario, "inventario"),
    ("compras", "Compras y proveedores", PaginaCompras, "compras"),
    ("clientes", "Clientes", PaginaClientes, "clientes"),
    ("historial", "Historial de ventas", PaginaHistorial, "historial"),
    ("caja", "Caja diaria", PaginaCaja, "caja"),
    ("facturacion", "Facturación", PaginaFacturacion, "facturacion"),
    ("reportes", "Reportes", PaginaReportes, "reportes"),
    ("configuracion", "Configuración", PaginaConfiguracion, "configuracion"),
    ("copias", "Copias de seguridad", PaginaCopias, "copias"),
    ("guia", "Guía de uso", PaginaGuia, None),
]


class VentanaPrincipal(QMainWindow):
    def __init__(self, ctx, servidor=None):
        super().__init__()
        self.ctx = ctx
        self.servidor = servidor                       # servidor de red de esta computadora, si lo hay
        self.remoto = getattr(ctx, "remoto", False)    # esta computadora es un cliente
        self.copia_al_cerrar = True
        self.setWindowIcon(tema.icono_aplicacion())
        self.setMinimumSize(1120, 700)
        self.resize(1360, 820)

        central = QWidget()
        self.setCentralWidget(central)
        h = QHBoxLayout(central)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        lateral = QFrame()
        lateral.setObjectName("lateral")
        lateral.setFixedWidth(236)
        vl = QVBoxLayout(lateral)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)
        vl.addWidget(etiqueta(NOMBRE_APP, "marca"))
        self.comercio = etiqueta("", "submarca")
        vl.addWidget(self.comercio)

        self.pila = QStackedWidget()
        self.pila.setObjectName("contenido")
        self.paginas: dict[str, QWidget] = {}
        self.botones: dict[str, QPushButton] = {}
        grupo = QButtonGroup(self)
        for clave, texto, clase, permiso in MENU:
            if permiso and not ctx.puede(permiso):
                continue
            if clave == "copias" and self.remoto:
                continue  # las copias se hacen en la computadora que tiene los datos
            b = QPushButton("  " + texto)
            b.setCheckable(True)
            b.setIcon(tema.icono_menu(clave))
            b.setIconSize(QSize(20, 20))
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, c=clave: self.ir(c))
            grupo.addButton(b)
            vl.addWidget(b)
            self.botones[clave] = b
            pagina = clase(ctx, self)
            self.paginas[clave] = pagina
            self.pila.addWidget(pagina)
        vl.addStretch(1)
        # Aparece solo cuando hay una versión nueva publicada.
        self.boton_update = QPushButton("Update")
        self.boton_update.setObjectName("actualizar")
        self.boton_update.setCursor(Qt.PointingHandCursor)
        self.boton_update.hide()
        vl.addWidget(self.boton_update)
        self.estado_red = etiqueta("", "submarca", True)
        vl.addWidget(self.estado_red)
        self.estado_caja = etiqueta("", "chip")
        self.estado_caja.setAlignment(Qt.AlignCenter)
        contenedor = QHBoxLayout()
        contenedor.setContentsMargins(18, 0, 18, 10)
        contenedor.addWidget(self.estado_caja)
        vl.addLayout(contenedor)
        usuario = ctx.usuario
        vl.addWidget(etiqueta(f"{usuario['nombre']}\n{ROLES[usuario['rol']]}  ·  v{__version__}", "usuario"))

        h.addWidget(lateral)
        h.addWidget(self.pila, 1)

        if "venta" in self.paginas:
            QShortcut(QKeySequence("F2"), self).activated.connect(lambda: self.ir("venta"))
        self.actualizaciones = GestorActualizaciones(self, self.mostrar_actualizacion)
        self.boton_update.clicked.connect(lambda _=False: self.actualizaciones.actualizar())
        self.actualizar_estado()
        self.ir("inicio")

        # Copia automática diaria: al abrir y, si el programa queda abierto varios días, cada hora se revisa.
        # Los relojes pertenecen a la ventana: al cerrarla se detienen y no disparan nada después.
        self.reloj_inicio = QTimer(self)
        self.reloj_inicio.setSingleShot(True)
        self.reloj_inicio.timeout.connect(self.copia_automatica)
        self.reloj_copias = QTimer(self)
        self.reloj_copias.timeout.connect(self.copia_automatica)
        if not self.remoto:
            self.reloj_inicio.start(1500)
            self.reloj_copias.start(60 * 60 * 1000)
        # Con varias computadoras, el estado de la caja puede cambiar desde otra: se refresca cada tanto.
        self.reloj_estado = QTimer(self)
        self.reloj_estado.timeout.connect(self.refrescar_estado)
        self.reloj_estado.start(20000)

        # Actualizaciones: se consulta al abrir y cada seis horas. Sin Internet no pasa nada.
        self.reloj_actualizaciones = QTimer(self)
        self.reloj_actualizaciones.timeout.connect(lambda: self.actualizaciones.buscar())
        self.reloj_primera_consulta = QTimer(self)
        self.reloj_primera_consulta.setSingleShot(True)
        self.reloj_primera_consulta.timeout.connect(lambda: self.actualizaciones.buscar())
        # EXAPYME_SIN_ACTUALIZACIONES=1 evita la consulta automática (pruebas, equipos sin Internet).
        if ctx.puede("configuracion") and not os.environ.get("EXAPYME_SIN_ACTUALIZACIONES"):
            self.reloj_primera_consulta.start(4000)
            self.reloj_actualizaciones.start(6 * 60 * 60 * 1000)

    def ir(self, clave: str) -> None:
        if clave not in self.paginas:
            return
        self.botones[clave].setChecked(True)
        pagina = self.paginas[clave]
        self.pila.setCurrentWidget(pagina)
        pagina.refrescar()

    def actualizar_estado(self) -> None:
        nombre = self.ctx.config.obtener("comercio_nombre")
        self.comercio.setText(nombre)
        self.setWindowTitle(f"{NOMBRE_APP} — {nombre}")
        if self.remoto:
            self.estado_red.setText(f"Conectado a {self.ctx.cliente.host}")
        elif self.servidor is not None and self.servidor.activo:
            from ..red.servidor import direcciones_locales

            self.estado_red.setText(f"Servidor: {direcciones_locales()[0]} : {self.servidor.puerto}")
        else:
            self.estado_red.setText("")
        self.estado_red.setVisible(bool(self.estado_red.text()))
        abierta = self.ctx.caja.abierta() is not None
        self.estado_caja.setText(f"{self.ctx.puesto}: " + ("abierta" if abierta else "cerrada"))
        self.estado_caja.setStyleSheet(
            "background: #DCFCE7; color: #166534;" if abierta else "background: #FEE2E2; color: #991B1B;")

    def revisar_seguridad(self) -> None:
        """Al ingresar un administrador: avisa si su contraseña fue restablecida y ofrece crear el código de recuperación."""
        if not self.ctx.es_admin:
            return
        from .acceso import DialogoCodigo
        from .comunes import advertir, confirmar

        aviso = self.ctx.usuarios.aviso_de_seguridad()
        if aviso:
            advertir(self, aviso, "Aviso de seguridad")
        if not self.ctx.usuarios.tiene_codigo() and confirmar(
                self, "Todavía no tenés un código de recuperación.\n\nSi algún día olvidás la contraseña del administrador, "
                      "ese código es la forma de recuperarla. Lleva un minuto.\n\n¿Generarlo ahora?",
                "Generar ahora", "Más tarde", "Código de recuperación"):
            DialogoCodigo(self, self.ctx.usuarios.generar_codigo_recuperacion(), self.ctx).exec()

    def refrescar_estado(self) -> None:
        if self.remoto or (self.servidor is not None and self.servidor.activo):
            try:
                self.actualizar_estado()
            except ErrorNegocio:
                self.estado_red.setText("Sin conexión con el servidor")

    def aplicar_red(self) -> None:
        """Enciende, apaga o reinicia el servidor de red según las preferencias de esta computadora."""
        if self.remoto:
            return
        from ..red.servidor import Servidor

        prefs = preferencias.leer()
        if self.servidor is not None and self.servidor.activo:
            self.servidor.detener()
        self.servidor = None
        if prefs["red_activa"]:
            servidor = Servidor(self.ctx.db, int(prefs["red_puerto"]), self.ctx.puesto)
            servidor.iniciar()
            self.servidor = servidor
        self.actualizar_estado()

    def mostrar_actualizacion(self, actualizacion) -> None:
        visible = actualizacion is not None and self.ctx.puede("configuracion")
        if visible:
            self.boton_update.setText(f"Update  ·  versión {actualizacion.version}")
            self.boton_update.setToolTip("Hay una versión nueva de Exa Pyme. Hacé clic para actualizar.")
        self.boton_update.setVisible(visible)

    def copia_automatica(self) -> None:
        try:
            self.ctx.productos.asociar_catalogo()  # imágenes de productos, por código de barras
        except Exception:
            log.exception("No se pudieron asociar las imágenes del catálogo")
        try:
            self.ctx.copias.automatica_si_corresponde()
        except Exception:
            log.exception("Falló la copia de seguridad automática")

    def cerrar_sin_copia(self) -> None:
        self.copia_al_cerrar = False
        self.close()

    def closeEvent(self, evento) -> None:
        if self.servidor is not None and self.servidor.activo and self.servidor.conectados():
            from .comunes import confirmar

            if not confirmar(self, "Hay otras computadoras conectadas a esta. Si cerrás Exa Pyme acá, van a dejar de "
                                   "funcionar hasta que lo vuelvas a abrir.\n\n¿Cerrar igual?", "Cerrar"):
                evento.ignore()
                return
        for reloj in (self.reloj_copias, self.reloj_actualizaciones, self.reloj_inicio, self.reloj_primera_consulta, self.reloj_estado):
            reloj.stop()
        self.actualizaciones.detener()
        if self.remoto:
            self.ctx.cliente.salir()
        elif self.servidor is not None and self.servidor.activo:
            self.servidor.detener()
        evento.accept()
