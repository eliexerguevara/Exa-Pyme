"""Arranque de la aplicación de escritorio."""
from __future__ import annotations

import sys

from PySide6.QtCore import QLocale, QLockFile, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMessageBox

from . import NOMBRE_APP, __version__, preferencias
from .core.errores import ErrorNegocio
from .db import BaseDatos
from .registro import configurar_registro, log
from .rutas import carpeta_datos, carpeta_registros, ruta_base_datos
from .servicios import Contexto, actualizador
from .ui import tema
from .ui.acceso import DialogoConexion, DialogoIngreso, DialogoModo, DialogoPrimerUso
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

    # Una sola copia del programa a la vez en esta computadora.
    candado = QLockFile(str(carpeta_datos() / "micomercio.lock"))
    candado.setStaleLockTime(0)
    # Tras una actualización, la versión anterior puede tardar unos segundos en cerrarse.
    espera = 20000 if actualizador.ARGUMENTO_REINICIO in sys.argv else 200
    if not candado.tryLock(espera):
        QMessageBox.information(None, NOMBRE_APP, "Exa Pyme ya está abierto en esta computadora.")
        return 0
    actualizador.limpiar_restos()

    db = servidor = None
    try:
        modo = _elegir_modo()
        while True:
            if not modo:
                return 0
            if modo == "cliente":
                dialogo = DialogoConexion()
                aceptado = dialogo.exec()
                if dialogo.cambiar_modo:
                    modo = _preguntar_modo()
                    continue
                if not aceptado:
                    return 0
                ctx = dialogo.ctx
            else:
                db = _abrir_base()
                if db is None:
                    return 1
                servidor = _iniciar_servidor(db)
                ctx = Contexto(db)
                ctx.puesto = _puesto_propio()
                dialogo = DialogoIngreso(ctx) if ctx.usuarios.hay_usuarios() else DialogoPrimerUso(ctx)
                if not dialogo.exec():
                    return 0
            break
        ventana = VentanaPrincipal(ctx, servidor)
        ventana.showMaximized()
        QTimer.singleShot(700, ventana.revisar_seguridad)
        codigo = app.exec()
        servidor = ventana.servidor
        del ventana  # las ventanas se destruyen antes que la aplicación
        return codigo
    finally:
        if servidor is not None and servidor.activo:
            servidor.detener()
        if db is not None:
            db.cerrar()
        candado.unlock()
        log.info("Cierre de %s", NOMBRE_APP)


def _preguntar_modo() -> str:
    dialogo = DialogoModo()
    if not dialogo.exec():
        return ""
    preferencias.guardar(**dialogo.valores())
    return dialogo.modo


def _elegir_modo() -> str:
    """Servidor (esta computadora guarda los datos) o cliente. Se pregunta una sola vez, al instalar."""
    modo = preferencias.leer()["modo"]
    if modo in ("servidor", "cliente"):
        return modo
    if ruta_base_datos().exists():
        # Instalación anterior a la versión con red: ya tiene datos, así que sigue siendo la computadora principal.
        preferencias.guardar(modo="servidor")
        return "servidor"
    return _preguntar_modo()


def _puesto_propio() -> str:
    from .servicios.contexto import PUESTO_PRINCIPAL

    return preferencias.leer()["puesto"] or PUESTO_PRINCIPAL


def _abrir_base():
    try:
        return BaseDatos(ruta_base_datos())
    except ErrorNegocio as e:
        QMessageBox.critical(None, NOMBRE_APP, str(e))
    except Exception:
        log.exception("No se pudo abrir la base de datos")
        QMessageBox.critical(
            None, NOMBRE_APP,
            "No se pudo abrir la base de datos.\n\nSi tenés una copia de seguridad, el soporte técnico puede "
            f"ayudarte a restaurarla. Los datos están en:\n{carpeta_datos()}",
        )
    return None


def _iniciar_servidor(db):
    """Empieza a atender a las otras computadoras, si esta fue configurada como servidor de red."""
    prefs = preferencias.leer()
    if not prefs["red_activa"]:
        return None
    from .red.servidor import Servidor

    servidor = Servidor(db, int(prefs["red_puerto"]), _puesto_propio())
    try:
        servidor.iniciar()
    except ErrorNegocio as e:
        QMessageBox.warning(None, NOMBRE_APP, f"{e}\n\nEsta computadora va a funcionar igual, pero las otras no van a poder conectarse.")
        return None
    return servidor
