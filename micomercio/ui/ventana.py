from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QMainWindow, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from .. import NOMBRE_APP, __version__
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
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
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
        self.reloj_inicio.start(1500)
        self.reloj_copias = QTimer(self)
        self.reloj_copias.timeout.connect(self.copia_automatica)
        self.reloj_copias.start(60 * 60 * 1000)

        # Actualizaciones: se consulta al abrir y cada seis horas. Sin Internet no pasa nada.
        self.reloj_actualizaciones = QTimer(self)
        self.reloj_actualizaciones.timeout.connect(lambda: self.actualizaciones.buscar())
        self.reloj_primera_consulta = QTimer(self)
        self.reloj_primera_consulta.setSingleShot(True)
        self.reloj_primera_consulta.timeout.connect(lambda: self.actualizaciones.buscar())
        # MICOMERCIO_SIN_ACTUALIZACIONES=1 evita la consulta automática (pruebas, equipos sin Internet).
        if ctx.puede("configuracion") and not os.environ.get("MICOMERCIO_SIN_ACTUALIZACIONES"):
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
        abierta = self.ctx.caja.abierta() is not None
        self.estado_caja.setText("Caja abierta" if abierta else "Caja cerrada")
        self.estado_caja.setStyleSheet(
            "background: #DCFCE7; color: #166534;" if abierta else "background: #FEE2E2; color: #991B1B;")

    def mostrar_actualizacion(self, actualizacion) -> None:
        visible = actualizacion is not None and self.ctx.puede("configuracion")
        if visible:
            self.boton_update.setText(f"Update  ·  versión {actualizacion.version}")
            self.boton_update.setToolTip("Hay una versión nueva de MiComercio. Hacé clic para actualizar.")
        self.boton_update.setVisible(visible)

    def copia_automatica(self) -> None:
        try:
            self.ctx.copias.automatica_si_corresponde()
        except Exception:
            log.exception("Falló la copia de seguridad automática")

    def cerrar_sin_copia(self) -> None:
        self.copia_al_cerrar = False
        self.close()

    def closeEvent(self, evento) -> None:
        for reloj in (self.reloj_copias, self.reloj_actualizaciones, self.reloj_inicio, self.reloj_primera_consulta):
            reloj.stop()
        self.actualizaciones.detener()
        evento.accept()
