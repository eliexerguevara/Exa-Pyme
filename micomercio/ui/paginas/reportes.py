from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QFileDialog

from ...servicios import csv_io
from ...servicios.reportes import formatear
from ..comunes import Pagina, SelectorPeriodo, Tabla, boton, etiqueta, fila, informar

NUMERICOS = ("dinero", "cantidad", "pct", "entero")


class PaginaReportes(Pagina):
    titulo = "Reportes"

    def armar(self) -> None:
        self.reporte = None
        self.tipo = QComboBox()
        for clave, nombre in self.ctx.reportes.LISTA:
            self.tipo.addItem(nombre, clave)
        self.tipo.currentIndexChanged.connect(lambda _: self.refrescar())
        self.periodo = SelectorPeriodo("Hoy")
        self.periodo.cambiado.connect(self.refrescar)
        self.cuerpo.addLayout(fila(self.tipo, self.periodo, None, boton("Exportar a CSV (Excel)", self.exportar, "primario")))
        self.notas = etiqueta("", "nota", True)
        self.cuerpo.addWidget(self.notas)
        self.tabla = None
        self.pie = etiqueta("", "suave")

    def refrescar(self) -> None:
        desde, hasta = self.periodo.rango()
        r = self.ctx.reportes.generar(self.tipo.currentData(), desde, hasta)
        self.reporte = r
        if self.tabla is not None:
            self.cuerpo.removeWidget(self.tabla)
            self.tabla.deleteLater()
            self.cuerpo.removeWidget(self.pie)
        estirar = next((n for n, (_, tipo) in enumerate(r.columnas) if tipo == "texto" and n > 0), 0)
        if r.columnas[0][0] == "Concepto":
            estirar = 0
        self.tabla = Tabla([titulo for titulo, _ in r.columnas], estirar=estirar)
        filas = []
        for datos in r.filas:
            celdas = []
            for valor, (_, tipo) in zip(datos, r.columnas):
                crudo = valor[1] if isinstance(valor, tuple) else valor
                tipo_real = valor[0] if isinstance(valor, tuple) else tipo
                texto = formatear(valor, tipo)
                if tipo_real in NUMERICOS and crudo is not None:
                    celdas.append((texto, float(crudo)))
                elif tipo_real == "fecha":
                    celdas.append((texto, str(crudo or "")))
                else:
                    celdas.append(texto)
            filas.append(celdas)
        self.tabla.setSortingEnabled(r.columnas[0][0] != "Concepto")
        self.tabla.cargar(filas)
        self.cuerpo.addWidget(self.tabla, 1)
        self.cuerpo.addWidget(self.pie)
        self.notas.setText(r.notas)
        self.notas.setVisible(bool(r.notas))
        self.periodo.setEnabled(r.usa_periodo)
        self.pie.setText(f"{len(r.filas)} filas")

    def exportar(self) -> None:
        if self.reporte is None:
            return
        desde, hasta = self.periodo.rango()
        nombre = f"{self.reporte.titulo} {desde} a {hasta}.csv" if self.reporte.usa_periodo else f"{self.reporte.titulo}.csv"
        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar reporte", nombre, "CSV para Excel (*.csv)")
        if ruta:
            csv_io.exportar_reporte(self.reporte, ruta)
            informar(self, f"El reporte se guardó en:\n{ruta}")
