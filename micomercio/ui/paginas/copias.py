from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QCheckBox, QFileDialog, QSpinBox

from ...servicios.copias import validar_copia
from ..comunes import Pagina, Tabla, boton, cf, confirmar, etiqueta, fila, informar


class PaginaCopias(Pagina):
    titulo = "Copias de seguridad"

    def armar(self) -> None:
        self.cuerpo.addWidget(etiqueta(
            "Una copia de seguridad guarda todos los datos del comercio en un solo archivo. Conviene guardar copias "
            "en un pendrive o en otra computadora, por si esta se rompe.", "nota", True))
        self.carpeta = etiqueta("", "suave", True)
        self.cuerpo.addLayout(fila(self.carpeta, None, boton("Cambiar carpeta", self.cambiar_carpeta),
                                   boton("Abrir carpeta", self.abrir_carpeta)))
        self.automaticas = QCheckBox("Hacer una copia automática por día, al abrir el programa")
        self.conservar = QSpinBox()
        self.conservar.setRange(1, 365)
        self.cuerpo.addLayout(fila(self.automaticas, 16, etiqueta("Copias automáticas que se conservan:"), self.conservar,
                                   boton("Guardar", self.guardar), None))
        self.cuerpo.addLayout(fila(
            boton("Crear copia de seguridad ahora", self.crear, "primario"), None,
            boton("Restaurar la copia seleccionada", self.restaurar_seleccionada),
            boton("Restaurar desde un archivo…", self.restaurar_archivo),
        ))
        self.tabla = Tabla(["Archivo", "Fecha", "Tipo", "Tamaño"], estirar=0)
        self.cuerpo.addWidget(self.tabla, 1)

    def refrescar(self) -> None:
        cfg = self.ctx.config
        self.carpeta.setText(f"Las copias se guardan en: {self.ctx.copias.carpeta()}")
        self.automaticas.setChecked(cfg.booleano("copias_automaticas"))
        self.conservar.setValue(cfg.entero("copias_conservar"))
        copias = self.ctx.copias.listar()
        self.rutas = {c["nombre"]: c["ruta"] for c in copias}
        self.tabla.cargar([[c["nombre"], cf(c["fecha"]), c["tipo"], (f"{c['tamano'] / 1024:,.0f} KB".replace(",", "."), c["tamano"])]
                           for c in copias], [c["nombre"] for c in copias])

    def guardar(self) -> None:
        self.ctx.config.guardar({"copias_automaticas": self.automaticas.isChecked(), "copias_conservar": str(self.conservar.value())})
        informar(self, "La configuración se guardó.")

    def cambiar_carpeta(self) -> None:
        carpeta = QFileDialog.getExistingDirectory(self, "Carpeta para las copias de seguridad", str(self.ctx.copias.carpeta()))
        if carpeta:
            self.ctx.config.guardar({"copias_carpeta": carpeta})
            self.refrescar()

    def abrir_carpeta(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.ctx.copias.carpeta())))

    def crear(self) -> None:
        self.ctx.requiere("copias")
        ruta = self.ctx.copias.crear("manual")
        self.refrescar()
        informar(self, f"La copia de seguridad se creó y se verificó correctamente:\n{ruta}")

    def restaurar_seleccionada(self) -> None:
        nombre = self.tabla.id_requerido("Seleccioná una copia de la lista.")
        self.restaurar(self.rutas[nombre])

    def restaurar_archivo(self) -> None:
        ruta, _ = QFileDialog.getOpenFileName(self, "Elegir copia de seguridad", str(self.ctx.copias.carpeta()),
                                              "Copias de MiComercio (*.db)")
        if ruta:
            self.restaurar(ruta)

    def restaurar(self, ruta) -> None:
        self.ctx.requiere("copias")
        info = validar_copia(ruta)
        if not confirmar(
            self,
            f"La copia es válida: contiene {info['productos']} productos y {info['ventas']} ventas.\n\n"
            "Al restaurarla, TODOS los datos actuales se reemplazan por los de la copia. Lo que se haya cargado "
            "después de esa copia se pierde.\n\nAntes de reemplazar, se guarda automáticamente una copia de los "
            "datos actuales.\n\n¿Restaurar esta copia?", "Restaurar"):
            return
        resultado = self.ctx.copias.restaurar(ruta)
        informar(self, "La copia se restauró correctamente.\n\nLos datos anteriores quedaron guardados en:\n"
                       f"{resultado['resguardo']}\n\nMiComercio se va a cerrar. Volvé a abrirlo para seguir trabajando.")
        self.ventana.cerrar_sin_copia()
