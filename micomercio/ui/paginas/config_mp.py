from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QLineEdit, QVBoxLayout, QWidget

from ...core.errores import ErrorNegocio
from ...integraciones import mercadopago
from ..comunes import Dialogo, boton, confirmar, etiqueta, fila, informar, panel

AYUDA = """<b>Cómo obtener el Access Token</b>
<ol>
<li>Entrá a <b>mercadopago.com.ar/developers</b> con la cuenta de Mercado Pago del comercio y abrí <b>Tus integraciones</b>.</li>
<li>Creá una aplicación para <b>pagos presenciales con Código QR</b> (el nombre puede ser «Exa Pyme»).</li>
<li>En <b>Credenciales de producción</b> copiá el <b>Access Token</b> (empieza con APP_USR-) y pegalo acá.</li>
</ol>
El Access Token es como una contraseña: no lo compartas ni lo envíes por mensaje. Acá se guarda cifrado para tu
usuario de Windows, fuera de la base de datos y de las copias de seguridad."""


def _esperar(funcion):
    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        return funcion()
    finally:
        QApplication.restoreOverrideCursor()


class DialogoSucursal(Dialogo):
    def __init__(self, padre, nombre: str):
        super().__init__(padre, "Crear sucursal y caja en Mercado Pago", "Crear", 520)
        self.cuerpo.insertWidget(0, etiqueta(
            "Mercado Pago exige la dirección real del local. La ciudad y la provincia deben escribirse sin abreviar, y "
            "la latitud y la longitud tienen que caer dentro de esa ciudad: en Google Maps, hacé clic derecho sobre tu "
            "local y copiá los dos números que aparecen arriba.", "suave", True))
        self.campos = {}
        for clave, rotulo, valor in [("nombre", "Nombre del local", nombre), ("calle", "Calle", ""), ("numero", "Número", ""),
                                     ("ciudad", "Ciudad", ""), ("provincia", "Provincia", ""),
                                     ("latitud", "Latitud (ej. -32,9468)", ""), ("longitud", "Longitud (ej. -60,6393)", "")]:
            self.campos[clave] = QLineEdit(valor)
            self.formulario.addRow(rotulo + ":", self.campos[clave])
        self.terminar()

    def datos(self) -> dict:
        return {clave: campo.text() for clave, campo in self.campos.items()}


class PanelMercadoPago(QWidget):
    """Pestaña de Configuración para conectar la cuenta de Mercado Pago y elegir la caja."""

    def __init__(self, ctx):
        super().__init__()
        self.ctx, self.servicio, self.lista = ctx, mercadopago.crear_servicio(ctx), []
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 12, 0, 0)
        self.estado = etiqueta("", "nota", True)
        v.addWidget(self.estado)

        marco1, v1 = panel("1. Cuenta de Mercado Pago")
        self.cuenta = etiqueta("", ajustar=True)
        self.token = QLineEdit()
        self.token.setEchoMode(QLineEdit.Password)
        self.token.setPlaceholderText("Pegá acá el Access Token (APP_USR-…)")
        v1.addWidget(self.cuenta)
        v1.addLayout(fila(self.token, boton("Guardar credencial", self.guardar_credencial, "primario"),
                          boton("Quitar", self.quitar, "peligro")))
        ayuda = etiqueta(AYUDA, "suave", True)
        ayuda.setTextFormat(Qt.RichText)
        v1.addWidget(ayuda)
        v.addWidget(marco1)

        marco2, v2 = panel("2. Caja que recibe los cobros")
        self.cajas = QComboBox()
        self.cajas.setMinimumWidth(320)
        self.modo = QComboBox()
        for clave, nombre in mercadopago.MODOS.items():
            self.modo.addItem(nombre, clave)
        v2.addLayout(fila(self.cajas, boton("Actualizar lista", self.cargar_cajas), boton("Crear sucursal y caja…", self.crear_caja), None))
        v2.addLayout(fila(etiqueta("El cliente paga con:"), self.modo, None))
        self.b_qr = boton("Ver el QR de la caja para imprimir", self.ver_qr)
        v2.addLayout(fila(boton("Guardar caja", self.guardar_caja, "primario"), self.b_qr, None))
        v.addWidget(marco2)

        marco3, v3 = panel("3. Activar")
        self.habilitado = QCheckBox("Cobrar con QR de Mercado Pago y confirmar el pago automáticamente")
        v3.addLayout(fila(self.habilitado, boton("Guardar", self.guardar_activacion, "primario"), None))
        v.addWidget(marco3)
        v.addStretch(1)

    def refrescar(self) -> None:
        cfg = self.ctx.config
        estado = self.servicio.estado()
        self.estado.setText(estado.mensaje)
        conectada = self.servicio.tiene_credencial()
        self.cuenta.setText(f"Cuenta conectada: {cfg.obtener('mp_cuenta')} (N° {cfg.obtener('mp_usuario_id')})."
                            if conectada else "Todavía no hay ninguna cuenta conectada.")
        self.habilitado.setChecked(cfg.booleano("mp_habilitado"))
        self.modo.setCurrentIndex(max(0, self.modo.findData(cfg.obtener("mp_modo"))))
        if not self.lista:
            self.cajas.clear()
            if cfg.obtener("mp_caja"):
                self.cajas.addItem(f"{cfg.obtener('mp_caja_nombre')} (configurada)", None)
            else:
                self.cajas.addItem("Pulsá «Actualizar lista» para ver tus cajas", None)
        self.b_qr.setEnabled(bool(cfg.obtener("mp_caja_qr")))

    def guardar_credencial(self) -> None:
        cuenta = _esperar(lambda: self.servicio.guardar_credencial(self.token.text()))
        self.token.clear()
        self.lista = []
        self.refrescar()
        informar(self, f"Credencial guardada. Cuenta conectada: {cuenta['nombre']}.\n\nAhora elegí la caja que va a recibir los cobros.")
        self.cargar_cajas()

    def quitar(self) -> None:
        if confirmar(self, "¿Quitar la credencial de Mercado Pago de esta computadora?\n\nEl cobro automático con QR "
                           "se desactiva. Los cobros ya registrados no cambian.", "Quitar"):
            self.servicio.borrar_credencial()
            self.lista = []
            self.refrescar()

    def cargar_cajas(self) -> None:
        self.lista = _esperar(self.servicio.cajas)
        self.cajas.clear()
        actual = self.ctx.config.obtener("mp_caja")
        for n, caja in enumerate(self.lista):
            nota = "" if caja["externo"] else "  (no se puede usar: sin identificador)"
            self.cajas.addItem(caja["nombre"] + nota, n)
            if caja["externo"] and caja["externo"] == actual:
                self.cajas.setCurrentIndex(n)
        if not self.lista:
            self.cajas.addItem("La cuenta no tiene cajas: creá una", None)

    def crear_caja(self) -> None:
        dialogo = DialogoSucursal(self, self.ctx.config.obtener("comercio_nombre"))
        if not dialogo.exec():
            return
        caja = _esperar(lambda: self.servicio.crear_sucursal_y_caja(dialogo.datos()))
        self.servicio.elegir_caja(caja, self.modo.currentData())
        self.lista = []
        self.refrescar()
        informar(self, "La sucursal y la caja se crearon en Mercado Pago y quedaron elegidas para cobrar.")

    def guardar_caja(self) -> None:
        indice = self.cajas.currentData()
        if indice is None:
            if not self.ctx.config.obtener("mp_caja"):
                raise ErrorNegocio("Pulsá «Actualizar lista» y elegí una caja.")
            self.ctx.config.guardar({"mp_modo": self.modo.currentData()})  # solo cambia el modo
        else:
            self.servicio.elegir_caja(self.lista[indice], self.modo.currentData())
        self.refrescar()
        informar(self, "La caja de Mercado Pago quedó configurada.")

    def ver_qr(self) -> None:
        QDesktopServices.openUrl(QUrl(self.ctx.config.obtener("mp_caja_qr")))

    def guardar_activacion(self) -> None:
        self.ctx.config.guardar({"mp_habilitado": self.habilitado.isChecked()})
        self.refrescar()
        estado = self.servicio.estado()
        if self.habilitado.isChecked() and not estado.disponible:
            informar(self, "Quedó activado, pero todavía falta un paso:\n\n" + estado.mensaje)
        else:
            informar(self, "La configuración se guardó.")
