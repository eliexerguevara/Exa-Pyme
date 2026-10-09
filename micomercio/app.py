"""Arranque de la aplicación de escritorio."""
from __future__ import annotations

import sys

from PySide6.QtCore import QLocale, QLockFile
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMessageBox

from . import NOMBRE_APP, __version__
from .core.errores import ErrorNegocio
from .db import BaseDatos
from .registro import configurar_registro, log
from .rutas import carpeta_datos, carpeta_registros, ruta_base_datos
from .servicios import Contexto, actualizador
from .ui import tema
from .ui.acceso import DialogoIngreso, DialogoPrimerUso
from .ui.ventana import VentanaPrincipal


def _gancho_errores(tipo, valor, traza) -> None:
    """Todo error llega acá: los esperables se muestran tal cual; los demás se registran."""
    padre = QApplication.activeModalWidget() or QApplication.activeWindow()
    if issubclass(tipo, ErrorNegocio):
        QMessageBox.warning(padre, "Revisá este dato", str(valor))
        return
    if issubclass(tipo, KeyboardInterrupt):
        return
    log.error("Error no controlado", exc_info=(tipo, valor, traza))
    QMessageBox.critical(
        padre, "Ocurrió un problema",
        "Ocurrió un problema inesperado y la operación no se completó.\n\n"
        "Tus datos están a salvo. Si vuelve a pasar, enviá al soporte técnico el archivo de registro que está en:\n"
        f"{carpeta_registros()}",
    )


def main() -> int:
    configurar_registro()
    app = QApplication(sys.argv)
    app.setApplicationName(NOMBRE_APP)
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(tema.HOJA_DE_ESTILO)
    app.setWindowIcon(tema.icono_aplicacion())
    QLocale.setDefault(QLocale(QLocale.Spanish, QLocale.Argentina))
    sys.excepthook = _gancho_errores
    log.info("Inicio de %s %s", NOMBRE_APP, __version__)

    # Una sola copia del programa a la vez sobre la misma base de datos.
    candado = QLockFile(str(carpeta_datos() / "micomercio.lock"))
    candado.setStaleLockTime(0)
    # Tras una actualización, la versión anterior puede tardar unos segundos en cerrarse.
    espera = 20000 if actualizador.ARGUMENTO_REINICIO in sys.argv else 200
    if not candado.tryLock(espera):
        QMessageBox.information(None, NOMBRE_APP, "MiComercio ya está abierto en esta computadora.")
        return 0

    actualizador.limpiar_restos()
    try:
        db = BaseDatos(ruta_base_datos())
    except ErrorNegocio as e:
        QMessageBox.critical(None, NOMBRE_APP, str(e))
        return 1
    except Exception:
        log.exception("No se pudo abrir la base de datos")
        QMessageBox.critical(
            None, NOMBRE_APP,
            "No se pudo abrir la base de datos.\n\nSi tenés una copia de seguridad, el soporte técnico puede "
            f"ayudarte a restaurarla. Los datos están en:\n{carpeta_datos()}",
        )
        return 1

    ctx = Contexto(db)
    try:
        dialogo = DialogoIngreso(ctx) if ctx.usuarios.hay_usuarios() else DialogoPrimerUso(ctx)
        if not dialogo.exec():
            return 0
        ventana = VentanaPrincipal(ctx)
        ventana.showMaximized()
        codigo = app.exec()
        del ventana  # las ventanas se destruyen antes que la aplicación
        return codigo
    finally:
        db.cerrar()
        candado.unlock()
        log.info("Cierre de %s", NOMBRE_APP)
