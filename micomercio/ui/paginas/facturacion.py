from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QFormLayout, QLineEdit

from ...core.errores import ErrorNegocio
from ...integraciones import arca
from ..comunes import Pagina, boton, etiqueta, fila, informar, panel


class PaginaFacturacion(Pagina):
    titulo = "Facturación"

    def armar(self) -> None:
        self.servicio = arca.crear_servicio(self.ctx)
        self.estado = etiqueta("", "aviso", True)
        self.cuerpo.addWidget(self.estado)

        marco, v = panel("Datos fiscales del comercio")
        v.addWidget(etiqueta("Estos datos se guardan ahora y se usarán para emitir facturas electrónicas "
                             "cuando se habilite la conexión con ARCA.", "suave", True))
        formulario = QFormLayout()
        formulario.setSpacing(9)
        self.razon, self.cuit, self.domicilio = QLineEdit(), QLineEdit(), QLineEdit()
        self.iibb, self.inicio, self.punto = QLineEdit(), QLineEdit(), QLineEdit()
        self.cuit.setPlaceholderText("30-12345678-9")
        self.inicio.setPlaceholderText("dd/mm/aaaa")
        self.punto.setPlaceholderText("Número del punto de venta habilitado para factura electrónica")
        self.condicion = QComboBox()
        self.condicion.addItems(arca.CONDICIONES_EMISOR)
        self.entorno = QComboBox()
        for clave, nombre in arca.ENTORNOS.items():
            self.entorno.addItem(nombre, clave)
        self.comprobantes = etiqueta("", "suave", True)
        self.condicion.currentTextChanged.connect(self.mostrar_comprobantes)
        formulario.addRow("Razón social:", self.razon)
        formulario.addRow("CUIT:", self.cuit)
        formulario.addRow("Condición frente al IVA:", self.condicion)
        formulario.addRow("Comprobantes que corresponden:", self.comprobantes)
        formulario.addRow("Domicilio comercial:", self.domicilio)
        formulario.addRow("Ingresos Brutos:", self.iibb)
        formulario.addRow("Inicio de actividades:", self.inicio)
        formulario.addRow("Punto de venta autorizado:", self.punto)
        formulario.addRow("Entorno:", self.entorno)
        v.addLayout(formulario)
        v.addLayout(fila(boton("Guardar datos fiscales", self.guardar, "primario"), None))
        marco.setMaximumWidth(820)
        self.cuerpo.addWidget(marco)

        self.pendientes = etiqueta("", "nota", True)
        self.cuerpo.addWidget(self.pendientes)
        self.cuerpo.addStretch(1)

    def mostrar_comprobantes(self, condicion: str) -> None:
        textos = {
            "Responsable inscripto": "Factura A a responsables inscriptos y monotributistas; Factura B a consumidores "
                                     "finales y exentos; notas de crédito A y B.",
            "Monotributista": "Factura C y nota de crédito C.",
            "Exento": "Factura C y nota de crédito C.",
        }
        self.comprobantes.setText(textos.get(condicion, "Elegí la condición frente al IVA."))

    def refrescar(self) -> None:
        cfg = self.ctx.config
        self.razon.setText(cfg.obtener("fiscal_razon_social"))
        self.cuit.setText(cfg.obtener("fiscal_cuit"))
        self.condicion.setCurrentText(cfg.obtener("fiscal_condicion_iva"))
        self.mostrar_comprobantes(self.condicion.currentText())
        self.domicilio.setText(cfg.obtener("fiscal_domicilio"))
        self.iibb.setText(cfg.obtener("fiscal_ingresos_brutos"))
        self.inicio.setText(cfg.obtener("fiscal_inicio_actividades"))
        self.punto.setText(cfg.obtener("fiscal_punto_venta"))
        self.entorno.setCurrentIndex(max(0, self.entorno.findData(cfg.obtener("fiscal_entorno"))))
        self.estado.setText(self.servicio.estado().mensaje)
        sin_comprobante = self.ctx.db.valor(
            "SELECT COUNT(*) FROM ventas WHERE estado = 'completada' AND estado_fiscal = 'sin_comprobante'", defecto=0)
        faltan = self.servicio.datos_completos()
        texto = f"Ventas registradas sin comprobante fiscal: {sin_comprobante}."
        if faltan:
            texto += "  Datos fiscales que faltan completar: " + ", ".join(faltan) + "."
        else:
            texto += "  Los datos fiscales del comercio están completos."
        self.pendientes.setText(texto)

    def guardar(self) -> None:
        cuit, punto = self.cuit.text().strip(), self.punto.text().strip()
        if cuit and not arca.cuit_valido(cuit):
            raise ErrorNegocio("El CUIT no es válido. Revisá que tenga 11 números y que estén bien escritos.")
        if punto and not punto.isdigit():
            raise ErrorNegocio("El punto de venta debe ser un número.")
        self.ctx.config.guardar({
            "fiscal_razon_social": self.razon.text().strip(), "fiscal_cuit": arca.formatear_cuit(cuit),
            "fiscal_condicion_iva": self.condicion.currentText(), "fiscal_domicilio": self.domicilio.text().strip(),
            "fiscal_ingresos_brutos": self.iibb.text().strip(), "fiscal_inicio_actividades": self.inicio.text().strip(),
            "fiscal_punto_venta": punto, "fiscal_entorno": self.entorno.currentData(),
        })
        self.refrescar()
        informar(self, "Los datos fiscales se guardaron.")
