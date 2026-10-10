"""Piezas de interfaz compartidas por todas las pantallas."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from PySide6.QtCore import QDate, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..core.dinero import fmt_cantidad, fmt_dinero, fmt_numero, parse_decimal
from ..core.errores import ErrorNegocio
from ..core.util import fecha_legible
from . import tema


# ---- mensajes ------------------------------------------------------------
def _mensaje(padre, icono, titulo: str, texto: str) -> QMessageBox:
    caja = QMessageBox(icono, titulo, texto, parent=padre)
    caja.setTextFormat(Qt.PlainText)
    return caja


def informar(padre, texto: str, titulo: str = "Exa Pyme") -> None:
    _mensaje(padre, QMessageBox.Information, titulo, texto).exec()


def advertir(padre, texto: str, titulo: str = "Revisá este dato") -> None:
    _mensaje(padre, QMessageBox.Warning, titulo, texto).exec()


def confirmar(padre, texto: str, si: str = "Sí", no: str = "Cancelar", titulo: str = "Confirmar") -> bool:
    caja = _mensaje(padre, QMessageBox.Question, titulo, texto)
    boton_si = caja.addButton(si, QMessageBox.AcceptRole)
    caja.setDefaultButton(caja.addButton(no, QMessageBox.RejectRole))
    caja.exec()
    return caja.clickedButton() is boton_si


# ---- controles -----------------------------------------------------------
def boton(texto: str, al_pulsar=None, tipo: str = "", icono: str | None = None, ayuda: str = "") -> QPushButton:
    b = QPushButton(texto)
    if tipo:
        b.setProperty("tipo", tipo)
    if icono:
        b.setIcon(tema.icono(icono, "white" if tipo in ("primario", "cobro") else "#4B5563"))
    if ayuda:
        b.setToolTip(ayuda)
    b.setCursor(Qt.PointingHandCursor)
    b.setAutoDefault(False)
    if al_pulsar:
        b.clicked.connect(lambda _=False: al_pulsar())
    return b


def etiqueta(texto: str = "", nombre: str = "", ajustar: bool = False) -> QLabel:
    e = QLabel(texto)
    if nombre:
        e.setObjectName(nombre)
    e.setWordWrap(ajustar)
    return e


def fila(*elementos, margen: int = 0, espacio: int = 8) -> QHBoxLayout:
    """Disposición horizontal. Un número es un espacio elástico; None también."""
    h = QHBoxLayout()
    h.setContentsMargins(margen, margen, margen, margen)
    h.setSpacing(espacio)
    for e in elementos:
        if e is None:
            h.addStretch(1)
        elif isinstance(e, int):
            h.addSpacing(e)
        elif isinstance(e, QWidget):
            h.addWidget(e)
        else:
            h.addLayout(e)
    return h


class CampoDecimal(QLineEdit):
    """Campo para importes, cantidades o porcentajes. Acepta coma o punto decimal."""

    def __init__(self, nombre: str, decimales: int = 2, dinero: bool = False, opcional: bool = False,
                 negativo: bool = False):
        super().__init__()
        self.nombre, self.decimales, self.dinero, self.opcional, self.negativo = nombre, decimales, dinero, opcional, negativo
        self.setAlignment(Qt.AlignRight)
        self.setMaximumWidth(170)
        self.editingFinished.connect(self._normalizar)

    def focusInEvent(self, evento) -> None:
        # Al entrar al campo se selecciona todo: lo que se escribe reemplaza el valor anterior.
        super().focusInEvent(evento)
        if not self.isReadOnly():
            QTimer.singleShot(0, self.selectAll)

    def valor(self) -> Decimal | None:
        texto = self.text().strip()
        if not texto:
            if self.opcional:
                return None
            raise ErrorNegocio(f"Completá el campo «{self.nombre}».")
        try:
            v = parse_decimal(texto, punto_miles=self.dinero)
        except ValueError:
            raise ErrorNegocio(f"El valor de «{self.nombre}» no es un número válido.") from None
        if v < 0 and not self.negativo:
            raise ErrorNegocio(f"«{self.nombre}» no puede ser negativo.")
        return v

    def valor_o(self, defecto=None) -> Decimal | None:
        try:
            return self.valor()
        except ErrorNegocio:
            return defecto

    def poner(self, v) -> None:
        if v is None:
            self.clear()
            return
        texto = fmt_numero(v, self.decimales)
        if not self.dinero and "," in texto:
            texto = texto.rstrip("0").rstrip(",")
        self.setText(texto)

    def _normalizar(self) -> None:
        v = self.valor_o()
        if v is not None:
            self.poner(v)


def cd(centavos):
    """Celda de dinero: texto para mostrar y valor para ordenar."""
    return (fmt_dinero(centavos), centavos if centavos is not None else -1)


def cq(milesimas):
    return (fmt_cantidad(milesimas), milesimas)


def cf(fecha):
    return (fecha_legible(fecha), fecha or "")


class _Celda(QTableWidgetItem):
    def __lt__(self, otra):
        a, b = self.data(Qt.UserRole + 1), otra.data(Qt.UserRole + 1)
        try:
            return a < b
        except TypeError:
            return str(a) < str(b)


class Tabla(QTableWidget):
    """Tabla de solo lectura. Las celdas son texto o (texto, valor para ordenar)."""

    activada = Signal()

    def __init__(self, columnas: list[str], estirar: int = 1, ordenable: bool = True, minimo: int = 220):
        super().__init__(0, len(columnas))
        self.estirar, self.minimo = estirar, minimo
        self.setHorizontalHeaderLabels(columnas)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(34)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setWordWrap(False)
        cabecera = self.horizontalHeader()
        cabecera.setHighlightSections(False)
        cabecera.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        cabecera.setSectionResizeMode(QHeaderView.ResizeToContents)
        cabecera.setSectionResizeMode(estirar, QHeaderView.Stretch)
        cabecera.setMinimumSectionSize(70)
        self.setSortingEnabled(ordenable)
        self.doubleClicked.connect(lambda _: self.activada.emit())

    def cargar(self, filas: list[list], ids: list | None = None, colores: dict[int, str] | None = None,
               iconos: dict[int, object] | None = None, columna_icono: int = 1) -> None:
        """colores: {número de fila: color del texto} · iconos: {número de fila: imagen para mostrar en esa fila}"""
        seleccion = self.id_actual()
        ordenable = self.isSortingEnabled()
        self.setSortingEnabled(False)
        self.setRowCount(len(filas))
        for r, datos in enumerate(filas):
            for c, valor in enumerate(datos):
                texto, clave = valor if isinstance(valor, tuple) else (str(valor), str(valor).lower())
                celda = _Celda(texto)
                celda.setData(Qt.UserRole + 1, clave)
                if not isinstance(clave, str):
                    celda.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    if r == 0:
                        self.horizontalHeaderItem(c).setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if c == 0 and ids is not None:
                    celda.setData(Qt.UserRole, ids[r])
                if colores and r in colores:
                    celda.setForeground(QColor(colores[r]))
                if iconos and c == columna_icono and r in iconos:
                    celda.setIcon(QIcon(iconos[r]))
                self.setItem(r, c, celda)
        self.setSortingEnabled(ordenable)
        if seleccion is not None:
            self.seleccionar_id(seleccion)
        self._ajustar()

    def resizeEvent(self, evento) -> None:
        super().resizeEvent(evento)
        self._ajustar()

    def _ajustar(self) -> None:
        """La columna principal ocupa el espacio libre, pero nunca queda más angosta que su mínimo."""
        cabecera = self.horizontalHeader()
        otras = sum(cabecera.sectionSize(c) for c in range(self.columnCount()) if c != self.estirar)
        if self.viewport().width() - otras >= self.minimo:
            cabecera.setSectionResizeMode(self.estirar, QHeaderView.Stretch)
        else:
            cabecera.setSectionResizeMode(self.estirar, QHeaderView.Interactive)
            cabecera.resizeSection(self.estirar, self.minimo)

    def id_actual(self):
        fila_actual = self.currentRow()
        if fila_actual < 0 or self.item(fila_actual, 0) is None or not self.selectedItems():
            return None
        return self.item(fila_actual, 0).data(Qt.UserRole)

    def id_requerido(self, mensaje: str = "Primero seleccioná una fila de la lista."):
        actual = self.id_actual()
        if actual is None:
            raise ErrorNegocio(mensaje)
        return actual

    def seleccionar_id(self, identificador) -> None:
        for r in range(self.rowCount()):
            if self.item(r, 0).data(Qt.UserRole) == identificador:
                self.selectRow(r)
                return


class Tarjeta(QFrame):
    """Recuadro con un título chico y un valor destacado."""

    def __init__(self, titulo: str, valor: str = "—"):
        super().__init__()
        self.setObjectName("tarjeta")
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(2)
        v.addWidget(etiqueta(titulo, "tarjetaTitulo"))
        self.valor = etiqueta(valor, "tarjetaValor")
        v.addWidget(self.valor)

    def poner(self, texto: str, color: str = tema.TEXTO) -> None:
        self.valor.setText(texto)
        self.valor.setStyleSheet(f"color: {color};")


def panel(titulo: str = "") -> tuple[QFrame, QVBoxLayout]:
    marco = QFrame()
    marco.setObjectName("tarjeta")
    v = QVBoxLayout(marco)
    v.setContentsMargins(16, 14, 16, 14)
    v.setSpacing(8)
    if titulo:
        v.addWidget(etiqueta(titulo, "subtitulo"))
    return marco, v


class Pagina(QWidget):
    """Base de las pantallas del menú. refrescar() se llama cada vez que se muestra."""

    titulo = ""

    def __init__(self, ctx, ventana):
        super().__init__()
        self.ctx, self.ventana = ctx, ventana
        self.cuerpo = QVBoxLayout(self)
        self.cuerpo.setContentsMargins(24, 18, 24, 18)
        self.cuerpo.setSpacing(12)
        self.encabezado = fila(etiqueta(self.titulo, "titulo"), None)
        self.cuerpo.addLayout(self.encabezado)
        self.armar()

    def armar(self) -> None: ...

    def refrescar(self) -> None: ...


class Dialogo(QDialog):
    """Diálogo con formulario y botones Guardar / Cancelar. guardar() valida y cierra."""

    def __init__(self, padre, titulo: str, texto_aceptar: str = "Guardar", ancho: int = 460):
        super().__init__(padre)
        self.setWindowTitle(titulo)
        self.setMinimumWidth(ancho)
        self.cuerpo = QVBoxLayout(self)
        self.cuerpo.setContentsMargins(20, 18, 20, 16)
        self.cuerpo.setSpacing(12)
        self.formulario = QFormLayout()
        self.formulario.setSpacing(9)
        self.formulario.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.cuerpo.addLayout(self.formulario)
        self.botones = QDialogButtonBox()
        self.boton_aceptar = boton(texto_aceptar, self.guardar, "primario")
        self.boton_aceptar.setDefault(True)
        self.boton_aceptar.setAutoDefault(True)
        self.botones.addButton(self.boton_aceptar, QDialogButtonBox.AcceptRole)
        self.botones.addButton(boton("Cancelar", self.reject), QDialogButtonBox.RejectRole)

    def terminar(self) -> None:
        """Agrega la botonera al final (llamar al terminar de armar el diálogo)."""
        self.cuerpo.addWidget(self.botones)

    def guardar(self) -> None:
        self.accept()


class DialogoImporte(Dialogo):
    """Pide un importe y, si hace falta, un motivo."""

    def __init__(self, padre, titulo: str, nombre_importe: str, con_motivo: bool = False, texto: str = "",
                 inicial=None, aceptar: str = "Aceptar"):
        super().__init__(padre, titulo, aceptar, 400)
        if texto:
            self.cuerpo.insertWidget(0, etiqueta(texto, ajustar=True))
        self.importe = CampoDecimal(nombre_importe, dinero=True)
        self.importe.poner(inicial)
        self.formulario.addRow(nombre_importe + ":", self.importe)
        self.motivo = QLineEdit()
        if con_motivo:
            self.formulario.addRow("Motivo:", self.motivo)
        self.terminar()
        self.importe.setFocus()
        self.importe.selectAll()

    def guardar(self) -> None:
        self.importe.valor()
        self.accept()


class SelectorPeriodo(QWidget):
    cambiado = Signal()

    OPCIONES = ["Hoy", "Ayer", "Esta semana", "Este mes", "Mes pasado", "Período personalizado"]

    def __init__(self, inicial: str = "Hoy"):
        super().__init__()
        self.combo = QComboBox()
        self.combo.addItems(self.OPCIONES)
        self.desde, self.hasta = QDateEdit(), QDateEdit()
        for d in (self.desde, self.hasta):
            d.setCalendarPopup(True)
            d.setDisplayFormat("dd/MM/yyyy")
            d.setDate(QDate.currentDate())
            d.dateChanged.connect(lambda _: self._fecha_cambiada())
        self.lay = fila(self.combo, etiqueta("desde"), self.desde, etiqueta("hasta"), self.hasta)
        self.setLayout(self.lay)
        self.combo.setCurrentText(inicial)
        self.combo.currentIndexChanged.connect(lambda _: self._aplicar())
        self._aplicar(emitir=False)

    def _aplicar(self, emitir: bool = True) -> None:
        hoy = date.today()
        opcion = self.combo.currentText()
        if opcion == "Hoy":
            desde = hasta = hoy
        elif opcion == "Ayer":
            desde = hasta = hoy - timedelta(days=1)
        elif opcion == "Esta semana":
            desde, hasta = hoy - timedelta(days=hoy.weekday()), hoy
        elif opcion == "Este mes":
            desde, hasta = hoy.replace(day=1), hoy
        elif opcion == "Mes pasado":
            hasta = hoy.replace(day=1) - timedelta(days=1)
            desde = hasta.replace(day=1)
        else:
            desde = hasta = None
        if desde:
            for campo, valor in ((self.desde, desde), (self.hasta, hasta)):
                campo.blockSignals(True)
                campo.setDate(QDate(valor.year, valor.month, valor.day))
                campo.blockSignals(False)
        if emitir:
            self.cambiado.emit()

    def _fecha_cambiada(self) -> None:
        self.combo.blockSignals(True)
        self.combo.setCurrentText("Período personalizado")
        self.combo.blockSignals(False)
        self.cambiado.emit()

    def rango(self) -> tuple[str, str]:
        desde, hasta = self.desde.date().toString("yyyy-MM-dd"), self.hasta.date().toString("yyyy-MM-dd")
        if desde > hasta:
            raise ErrorNegocio("La fecha «desde» no puede ser posterior a la fecha «hasta».")
        return desde, hasta


class Buscador(QLineEdit):
    """Campo de búsqueda que avisa cuando el usuario deja de escribir."""

    buscar = Signal()

    def __init__(self, sugerencia: str = "Buscar…", demora_ms: int = 220):
        super().__init__()
        self.setPlaceholderText(sugerencia)
        self.setClearButtonEnabled(True)
        self.reloj = QTimer(self)
        self.reloj.setSingleShot(True)
        self.reloj.setInterval(demora_ms)
        self.reloj.timeout.connect(self.buscar.emit)
        self.textChanged.connect(lambda _: self.reloj.start())


class DialogoElegirProducto(QDialog):
    """Busca un producto por nombre o código y devuelve su id en .producto_id"""

    def __init__(self, padre, ctx):
        super().__init__(padre)
        self.ctx, self.producto_id = ctx, None
        self.setWindowTitle("Elegir producto")
        self.resize(720, 480)
        v = QVBoxLayout(self)
        self.buscador = Buscador("Escribí el nombre o escaneá el código de barras…")
        self.buscador.buscar.connect(self.cargar)
        self.buscador.returnPressed.connect(self._enter)
        self.tabla = Tabla(["Código", "Producto", "Disponible", "Precio Costo", "Precio final"])
        self.tabla.activada.connect(self.elegir)
        v.addWidget(self.buscador)
        v.addWidget(self.tabla)
        v.addLayout(fila(None, boton("Cancelar", self.reject), boton("Elegir", self.elegir, "primario")))
        self.cargar()

    def cargar(self) -> None:
        productos = self.ctx.productos.buscar(self.buscador.text(), limite=200)
        self.tabla.cargar(
            [[p["codigo"], p["nombre"], cq(p["stock_mil"]), cd(p["costo_cent"]), cd(p["precio_final_cent"])] for p in productos],
            [p["id"] for p in productos],
        )
        if productos:
            self.tabla.selectRow(0)

    def _enter(self) -> None:
        exacto = self.ctx.productos.por_codigo(self.buscador.text())
        if exacto:
            self.producto_id = exacto["id"]
            self.accept()
            return
        self.cargar()
        if self.tabla.rowCount() == 1:
            self.elegir()

    def elegir(self) -> None:
        self.producto_id = self.tabla.id_requerido("Seleccioná un producto de la lista.")
        self.accept()
