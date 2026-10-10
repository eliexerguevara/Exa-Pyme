"""Ventana de cobro con QR de Mercado Pago: muestra el código y espera la confirmación de Mercado Pago."""
from __future__ import annotations

import io

import segno
from PySide6.QtCore import Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QVBoxLayout

from ..core.dinero import fmt_dinero
from ..core.errores import ErrorNegocio
from ..integraciones import mercadopago
from ..registro import log
from . import tema
from .comunes import boton, etiqueta, fila

INTERVALO_MS = 3000
MOTIVOS = {"cancelado": "El código QR venció o el cobro fue cancelado", "rechazado": "Mercado Pago rechazó el pago"}


class _Consulta(QThread):
    """Pregunta en segundo plano si el cliente ya pagó, para no congelar la ventana."""

    terminada = Signal(str, str)  # (estado del pago, error)

    def __init__(self, servicio, pago_id: int):
        super().__init__()
        self.servicio, self.pago_id = servicio, pago_id

    def run(self) -> None:
        try:
            self.terminada.emit(self.servicio.verificar(self.pago_id), "")
        except mercadopago.ErrorConexionMP:
            self.terminada.emit("", "conexion")
        except ErrorNegocio as e:
            self.terminada.emit("", "conexion" if type(e).__name__ == "ErrorServidor" else str(e))
        except Exception:
            log.exception("Error al consultar el cobro en Mercado Pago")
            self.terminada.emit("", "conexion")


class DialogoCobroQR(QDialog):
    """resultado: 'confirmado' (pagó), 'otra_forma' (se canceló el cobro) o 'pendiente' (se deja para verificar después)."""

    def __init__(self, padre, ctx, venta_id: int, pago_id: int, servicio=None):
        super().__init__(padre)
        self.ctx, self.venta_id, self.pago_id = ctx, venta_id, pago_id
        self.servicio = servicio or mercadopago.crear_servicio(ctx)
        self.resultado, self.creado, self.hilo = "pendiente", False, None
        self.setWindowTitle("Cobrar con Mercado Pago")
        self.setMinimumWidth(430)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 18)
        v.setSpacing(10)
        v.addWidget(etiqueta("Total a cobrar", "suave"), alignment=Qt.AlignCenter)
        self.total = etiqueta("", "total")
        v.addWidget(self.total, alignment=Qt.AlignCenter)
        self.imagen = QLabel()
        self.imagen.setAlignment(Qt.AlignCenter)
        self.imagen.setMinimumHeight(40)
        v.addWidget(self.imagen)
        self.instruccion = etiqueta("", ajustar=True)
        self.instruccion.setAlignment(Qt.AlignCenter)
        v.addWidget(self.instruccion)
        self.estado = etiqueta("", "grande", True)
        self.estado.setAlignment(Qt.AlignCenter)
        v.addWidget(self.estado)
        self.b_otro = boton("Generar otro QR", self.nuevo_qr, "primario")
        self.b_otra_forma = boton("Cobrar de otra forma", self.otra_forma)
        self.b_pendiente = boton("Dejar pendiente", self.reject,
                                 ayuda="La venta queda con el pago pendiente. Se puede verificar después desde Historial de ventas.")
        v.addLayout(fila(self.b_otro, None, self.b_otra_forma, self.b_pendiente))
        self.reloj = QTimer(self)
        self.reloj.setInterval(INTERVALO_MS)
        self.reloj.timeout.connect(self.consultar)
        self.iniciar()

    # ---- creación del cobro ---------------------------------------------
    def iniciar(self) -> None:
        self.b_otro.hide()
        self.creado = False
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            cobro = self.servicio.crear_cobro(self.pago_id)
        except ErrorNegocio as e:
            self.mostrar_estado(f"No se pudo generar el cobro.\n{e}", tema.ROJO)
            self.imagen.clear()
            self.instruccion.setText("")
            self.b_otro.setText("Reintentar")
            self.b_otro.show()
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.creado = True
        self.total.setText(fmt_dinero(cobro["monto_cent"]))
        if cobro["qr"]:
            memoria = io.BytesIO()
            segno.make(cobro["qr"], error="m").save(memoria, kind="png", scale=6, border=3)
            pixmap = QPixmap()
            pixmap.loadFromData(memoria.getvalue())
            self.imagen.setPixmap(pixmap.scaled(300, 300, Qt.KeepAspectRatio, Qt.FastTransformation))
            texto = "Pedile al cliente que escanee este código con la app de Mercado Pago o de su banco."
            if cobro["modo"] == "hybrid":
                texto += " También puede escanear el QR impreso de la caja."
        else:
            self.imagen.clear()
            texto = "Pedile al cliente que escanee el QR impreso de la caja. El importe le aparece solo en el celular."
        self.instruccion.setText(texto)
        self.mostrar_estado("Esperando el pago…", tema.TEXTO_SUAVE)
        self.reloj.start()

    def mostrar_estado(self, texto: str, color: str) -> None:
        self.estado.setText(texto)
        self.estado.setStyleSheet(f"color: {color};")

    # ---- seguimiento -----------------------------------------------------
    def consultar(self) -> None:
        if not self.creado or (self.hilo is not None and self.hilo.isRunning()):
            return
        self.hilo = _Consulta(self.servicio, self.pago_id)
        self.hilo.terminada.connect(self.recibir)
        self.hilo.start()

    @Slot(str, str)
    def recibir(self, estado: str, error: str) -> None:
        """estado: cómo quedó el pago después de preguntarle a Mercado Pago (pendiente, confirmado, cancelado, rechazado)."""
        if not self.reloj.isActive():
            return  # llegó tarde: el diálogo ya resolvió otra cosa
        if error == "conexion":
            self.mostrar_estado("Sin conexión con Mercado Pago. Reintentando…", tema.NARANJA)
            return
        if error:
            self.reloj.stop()
            self.mostrar_estado(error, tema.ROJO)
            return
        if estado == "pendiente":
            self.mostrar_estado("Esperando el pago…", tema.TEXTO_SUAVE)
            return
        self.reloj.stop()
        self.resolver(estado)

    def resolver(self, estado: str) -> None:
        if estado == "confirmado":
            self.resultado = "confirmado"
            self.imagen.clear()
            self.instruccion.setText("")
            self.mostrar_estado("✔  Pago acreditado", tema.VERDE)
            for b in (self.b_otro, self.b_otra_forma, self.b_pendiente):
                b.setEnabled(False)
            QTimer.singleShot(1400, self.accept)
        elif estado == "pendiente":
            self.reloj.start()
        else:
            # Venció, se canceló o fue rechazado: ese cobro ya no sirve.
            self.resultado = "otra_forma"
            self.creado = False
            self.imagen.clear()
            self.instruccion.setText("")
            self.mostrar_estado(MOTIVOS.get(estado, "El cobro no se completó") + ".", tema.ROJO)
            self.b_otro.setText("Generar otro QR")
            self.b_otro.show()
            self.b_pendiente.hide()

    def nuevo_qr(self) -> None:
        if self.ctx.ventas.pago(self.pago_id)["estado"] != "pendiente":
            # El cobro anterior quedó cancelado: se registra uno nuevo por lo que falta cobrar.
            self.pago_id = self.ctx.ventas.agregar_pago(
                self.venta_id, {"medio": "mercadopago", "monto_cent": self.ctx.ventas.saldo(self.venta_id), "estado": "pendiente"})
        self.resultado = "pendiente"
        self.b_pendiente.show()
        self.iniciar()

    def otra_forma(self) -> None:
        self.reloj.stop()
        if self.creado:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                estado = self.servicio.cancelar(self.pago_id)
            except ErrorNegocio as e:
                self.mostrar_estado(str(e), tema.NARANJA)
                self.reloj.start()
                return
            finally:
                QApplication.restoreOverrideCursor()
            if estado == "confirmado":  # el cliente pagó justo antes
                self.resolver("confirmado")
                return
        elif self.ctx.ventas.pago(self.pago_id)["estado"] == "pendiente":
            self.ctx.ventas.descartar_pago(self.pago_id, "cancelado")  # nunca llegó a crearse en Mercado Pago
        self.resultado = "otra_forma"
        self.accept()

    def done(self, codigo: int) -> None:
        self.reloj.stop()
        if self.hilo is not None and self.hilo.isRunning():
            self.hilo.wait(3000)
        super().done(codigo)
