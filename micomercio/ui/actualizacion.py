"""Parte visual de la actualización: consulta en segundo plano, descarga con progreso y reinicio."""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtWidgets import QProgressDialog

from .. import __version__
from ..core.errores import ErrorNegocio
from ..registro import log
from ..servicios import actualizador
from .comunes import advertir, confirmar, informar


class _Consulta(QThread):
    terminada = Signal(object, str)  # (Actualizacion | None, mensaje de error)

    def run(self) -> None:
        try:
            self.terminada.emit(actualizador.buscar(), "")
        except ErrorNegocio as e:
            self.terminada.emit(None, str(e))
        except Exception:
            log.exception("Error al buscar actualizaciones")
            self.terminada.emit(None, "No se pudo consultar si hay actualizaciones.")


class _Descarga(QThread):
    avance = Signal(int, int)
    terminada = Signal(str)  # mensaje de error, vacío si salió bien

    def __init__(self, actualizacion, exe):
        super().__init__()
        self.actualizacion, self.exe = actualizacion, exe

    def run(self) -> None:
        try:
            nuevo = actualizador.descargar(
                self.actualizacion, self.exe.with_name(self.exe.name + actualizador.SUFIJO_NUEVO), self.avance.emit)
            actualizador.instalar(nuevo, self.exe)
            self.terminada.emit("")
        except ErrorNegocio as e:
            self.terminada.emit(str(e))
        except Exception:
            log.exception("Error al actualizar")
            self.terminada.emit("No se pudo instalar la actualización. El programa no se modificó.")


class GestorActualizaciones(QObject):
    """Lo usa la ventana principal. Avisa con al_encontrar(Actualizacion | None) cada vez que consulta."""

    def __init__(self, ventana, al_encontrar):
        super().__init__(ventana)
        self._manual, self._exe = False, None
        self.ventana, self.ctx, self.al_encontrar = ventana, ventana.ctx, al_encontrar
        self.disponible = None
        self._consulta = self._descarga = self._dialogo = None

    def detener(self) -> None:
        """Espera a que termine una consulta en curso, para no cerrar el programa con un hilo activo."""
        for hilo in (self._consulta, self._descarga):
            if hilo is not None and hilo.isRunning():
                hilo.wait(5000)

    def buscar(self, manual: bool = False) -> None:
        """manual=True muestra el resultado aunque no haya novedades o no haya Internet."""
        if self._consulta is not None and self._consulta.isRunning():
            return
        self._manual = manual
        self._consulta = _Consulta()
        self._consulta.terminada.connect(self._consultado)
        self._consulta.start()

    @Slot(object, str)
    def _consultado(self, actualizacion, error: str) -> None:
        manual = self._manual
        if not error:
            self.disponible = actualizacion
            self.al_encontrar(actualizacion)
        if not manual:
            return
        if error:
            advertir(self.ventana, error, "Actualizaciones")
        elif actualizacion is None:
            informar(self.ventana, f"Ya tenés la última versión de MiComercio ({__version__}).", "Actualizaciones")
        else:
            self.actualizar()

    def actualizar(self) -> None:
        a = self.disponible
        if a is None:
            return
        exe = actualizador.ruta_ejecutable()
        if exe is None:
            informar(self.ventana, f"Hay una versión nueva ({a.version}), pero la actualización automática solo funciona "
                                   "en el programa instalado (MiComercio.exe).", "Actualizaciones")
            return
        notas = f"\n\nNovedades:\n{a.notas[:900]}" if a.notas else ""
        if not confirmar(
            self.ventana,
            f"Hay una versión nueva de MiComercio: {a.version} (tenés la {__version__}).{notas}\n\n"
            "Antes de actualizar se hace una copia de seguridad de tus datos. Al terminar, el programa se cierra "
            "y se vuelve a abrir solo. Si hay una venta a medio cargar, terminala antes.\n\n¿Actualizar ahora?",
            "Actualizar ahora", "Más tarde", "Actualización disponible",
        ):
            return
        self.ctx.copias.crear("manual")
        self._dialogo = QProgressDialog("Descargando la actualización…", "", 0, 100, self.ventana)
        self._dialogo.setWindowTitle("Actualizando MiComercio")
        self._dialogo.setCancelButton(None)
        self._dialogo.setWindowModality(Qt.WindowModal)
        self._dialogo.setMinimumDuration(0)
        self._dialogo.setAutoClose(False)
        self._dialogo.setAutoReset(False)
        self._dialogo.setValue(0)
        self._descarga = _Descarga(a, exe)
        self._exe = exe
        self._descarga.avance.connect(self._avance)
        self._descarga.terminada.connect(self._instalado)
        self._descarga.start()

    @Slot(int, int)
    def _avance(self, hecho: int, total: int) -> None:
        self._dialogo.setValue(int(hecho * 100 / total) if total else 0)

    @Slot(str)
    def _instalado(self, error: str) -> None:
        exe, version = self._exe, self.disponible.version
        self._dialogo.close()
        if error:
            advertir(self.ventana, error, "Actualizaciones")
            return
        informar(self.ventana, f"MiComercio se actualizó a la versión {version}.\n\nEl programa se va a reiniciar.",
                 "Actualización instalada")
        actualizador.reiniciar(exe)
        self.ventana.close()
