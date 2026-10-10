"""Herramienta de emergencia:  ExaPyme.exe --restablecer-clave

Para quien perdió la contraseña del administrador y también su código de recuperación. Solo funciona en la
computadora que tiene los datos (el servidor), con el programa cerrado. No se ofrece desde las pantallas del
programa: hay que ejecutarla a propósito. Lo que hace queda en el registro de operaciones y el programa lo
avisa la próxima vez que ingrese un administrador.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import QLockFile
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QLineEdit, QMessageBox

from . import NOMBRE_APP, preferencias
from .core.errores import ErrorNegocio
from .db import BaseDatos
from .registro import configurar_registro, log
from .rutas import carpeta_datos, ruta_base_datos
from .servicios import Contexto
from .ui import tema
from .ui.comunes import Dialogo, etiqueta


class DialogoRestablecer(Dialogo):
    def __init__(self, ctx):
        super().__init__(None, "Exa Pyme - Restablecer la contraseña del administrador", "Restablecer contraseña", 540)
        self.ctx = ctx
        self.cuerpo.insertWidget(0, etiqueta("Restablecer la contraseña del administrador", "titulo"))
        self.cuerpo.insertWidget(1, etiqueta(
            "Usá esta herramienta solo si perdiste la contraseña y también el código de recuperación. El cambio queda "
            "anotado en el registro de operaciones y el programa lo va a avisar cuando ingrese un administrador.",
            "aviso", True))
        self.usuario = QComboBox()
        for u in ctx.usuarios.administradores():
            self.usuario.addItem(f"{u['nombre']} ({u['usuario']})", u["id"])
        self.clave, self.clave2 = QLineEdit(), QLineEdit()
        for campo in (self.clave, self.clave2):
            campo.setEchoMode(QLineEdit.Password)
        self.entiendo = QCheckBox("Soy el responsable del comercio y entiendo que este cambio queda registrado")
        self.formulario.addRow("Administrador:", self.usuario)
        self.formulario.addRow("Contraseña nueva:", self.clave)
        self.formulario.addRow("Repetir contraseña:", self.clave2)
        self.formulario.addRow("", self.entiendo)
        self.terminar()

    def guardar(self) -> None:
        if self.usuario.currentData() is None:
            raise ErrorNegocio("No hay ningún administrador activo en esta base de datos.")
        if self.clave.text() != self.clave2.text():
            raise ErrorNegocio("Las dos contraseñas no coinciden.")
        if not self.entiendo.isChecked():
            raise ErrorNegocio("Tildá la casilla para confirmar.")
        self.ctx.usuarios.restablecer_sin_codigo(self.usuario.currentData(), self.clave.text())
        self.accept()


def ejecutar() -> int:
    configurar_registro()
    app = QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(tema.HOJA_DE_ESTILO)
    app.setWindowIcon(tema.icono_aplicacion())

    def gancho(tipo, valor, traza):
        if issubclass(tipo, ErrorNegocio):
            QMessageBox.warning(QApplication.activeWindow(), "Revisá este dato", str(valor))
        else:
            log.error("Error en la herramienta de contraseña", exc_info=(tipo, valor, traza))
            QMessageBox.critical(QApplication.activeWindow(), NOMBRE_APP, "Ocurrió un problema inesperado. No se cambió nada.")

    sys.excepthook = gancho
    if preferencias.leer()["modo"] == "cliente" or not ruta_base_datos().exists():
        QMessageBox.information(None, NOMBRE_APP, "Esta herramienta se usa en la computadora principal, que es la que "
                                                  "guarda los datos del comercio.")
        return 1
    candado = QLockFile(str(carpeta_datos() / "micomercio.lock"))
    candado.setStaleLockTime(0)
    if not candado.tryLock(200):
        QMessageBox.information(None, NOMBRE_APP, "Cerrá Exa Pyme en esta computadora antes de usar esta herramienta.")
        return 1
    db = BaseDatos(ruta_base_datos())
    try:
        if not DialogoRestablecer(Contexto(db)).exec():
            return 0
        log.warning("Contraseña de administrador restablecida con la herramienta de emergencia")
        QMessageBox.information(None, NOMBRE_APP, "La contraseña se cambió.\n\nAbrí Exa Pyme, ingresá con la contraseña nueva "
                                                  "y generá un código de recuperación cuando el programa te lo ofrezca.")
        return 0
    finally:
        db.cerrar()
        candado.unlock()
