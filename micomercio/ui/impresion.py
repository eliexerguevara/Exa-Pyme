"""Impresión de tickets y reportes con las impresoras instaladas en Windows."""
from __future__ import annotations

from PySide6.QtCore import QMarginsF, QSizeF
from PySide6.QtGui import QPageLayout, QPageSize, QTextDocument
from PySide6.QtPrintSupport import QPrintDialog, QPrinter, QPrinterInfo
from PySide6.QtWidgets import QDialog, QFileDialog, QTextBrowser, QVBoxLayout

from ..registro import log
from .comunes import advertir, boton, fila


def impresoras() -> list[str]:
    return QPrinterInfo.availablePrinterNames()


def impresora_configurada(ctx) -> str:
    """Nombre de la impresora elegida en Configuración, si sigue instalada."""
    nombre = ctx.config.obtener("impresora")
    return nombre if nombre and nombre in impresoras() else ""


def _preparar(printer: QPrinter, ancho: str) -> None:
    if ancho in ("80", "58"):
        # Papel continuo: el alto es solo un máximo; la impresora corta al terminar.
        tamano = QPageSize(QSizeF(float(ancho), 297.0), QPageSize.Millimeter, f"Ticket {ancho} mm")
        printer.setPageLayout(QPageLayout(tamano, QPageLayout.Portrait, QMarginsF(3, 3, 3, 3), QPageLayout.Millimeter))
    else:
        printer.setPageLayout(QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait, QMarginsF(15, 15, 15, 15), QPageLayout.Millimeter))


def _imprimir(html: str, printer: QPrinter) -> None:
    documento = QTextDocument()
    documento.setHtml(html)
    documento.print_(printer)


def imprimir_directo(ctx, html: str) -> bool:
    """Imprime sin preguntar en la impresora configurada. Devuelve False si no hay ninguna."""
    nombre = impresora_configurada(ctx)
    if not nombre:
        return False
    printer = QPrinter(QPrinterInfo.printerInfo(nombre), QPrinter.HighResolution)
    _preparar(printer, ctx.config.obtener("ticket_ancho"))
    _imprimir(html, printer)
    return True


class VistaImpresion(QDialog):
    """Muestra el comprobante y permite imprimirlo o guardarlo como PDF."""

    def __init__(self, padre, ctx, html: str, titulo: str):
        super().__init__(padre)
        self.ctx, self.html, self.titulo = ctx, html, titulo
        self.setWindowTitle(titulo)
        self.resize(430, 640)
        v = QVBoxLayout(self)
        vista = QTextBrowser()
        vista.setHtml(html)
        v.addWidget(vista)
        v.addLayout(fila(
            boton("Guardar como PDF", self.guardar_pdf), None, boton("Cerrar", self.reject),
            boton("Imprimir", self.imprimir, "primario"),
        ))

    def imprimir(self) -> None:
        try:
            if imprimir_directo(self.ctx, self.html):
                self.accept()
                return
            if not impresoras():
                advertir(self, "No hay ninguna impresora instalada en Windows. Podés guardar el comprobante como PDF.")
                return
            printer = QPrinter(QPrinter.HighResolution)
            _preparar(printer, self.ctx.config.obtener("ticket_ancho"))
            if QPrintDialog(printer, self).exec() == QDialog.Accepted:
                _imprimir(self.html, printer)
                self.accept()
        except Exception:
            log.exception("Error al imprimir")
            advertir(self, "No se pudo imprimir. Revisá que la impresora esté encendida y conectada.")

    def guardar_pdf(self) -> None:
        ruta, _ = QFileDialog.getSaveFileName(self, "Guardar como PDF", f"{self.titulo}.pdf", "PDF (*.pdf)")
        if not ruta:
            return
        printer = QPrinter(QPrinter.HighResolution)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(ruta)
        _preparar(printer, self.ctx.config.obtener("ticket_ancho"))
        _imprimir(self.html, printer)


def mostrar_comprobante(padre, ctx, html: str, titulo: str) -> None:
    VistaImpresion(padre, ctx, html, titulo).exec()
