from __future__ import annotations

from PySide6.QtWidgets import QCheckBox

from ...servicios.clientes import CONDICIONES_IVA, TIPOS_DOCUMENTO
from ..comunes import Buscador, Pagina, Tabla, boton, confirmar, etiqueta, fila
from .compras import DialogoFicha

CAMPOS_CLIENTE = [
    ("nombre", "Nombre o razón social", None), ("tipo_documento", "Tipo de documento", TIPOS_DOCUMENTO),
    ("documento", "N° de documento", None), ("condicion_iva", "Condición frente al IVA", CONDICIONES_IVA),
    ("telefono", "Teléfono", None), ("email", "Correo electrónico", None), ("direccion", "Dirección", None),
    ("notas", "Notas", None),
]


class PaginaClientes(Pagina):
    titulo = "Clientes"

    def armar(self) -> None:
        self.cuerpo.addWidget(etiqueta(
            "Registrar clientes es opcional: se puede vender siempre como «Consumidor final».", "suave"))
        self.buscador = Buscador("Buscar por nombre, documento o teléfono…")
        self.buscador.buscar.connect(self.refrescar)
        self.inactivos = QCheckBox("Mostrar inactivos")
        self.inactivos.toggled.connect(lambda _: self.refrescar())
        self.cuerpo.addLayout(fila(self.buscador, self.inactivos, boton("Nuevo cliente", self.nuevo, "primario"),
                                   boton("Editar", self.editar), boton("Desactivar / activar", self.estado)))
        self.tabla = Tabla(["Nombre", "Documento", "Condición IVA", "Teléfono", "Correo electrónico", "Dirección", "Estado"], estirar=0)
        self.tabla.activada.connect(self.editar)
        self.cuerpo.addWidget(self.tabla, 1)

    def refrescar(self) -> None:
        clientes = self.ctx.clientes.buscar(self.buscador.text(), not self.inactivos.isChecked())
        self.tabla.cargar([[c["nombre"], f"{c['tipo_documento']} {c['documento']}" if c["documento"] else "",
                            c["condicion_iva"], c["telefono"], c["email"], c["direccion"],
                            "Activo" if c["activo"] else "Inactivo"] for c in clientes], [c["id"] for c in clientes])

    def nuevo(self) -> None:
        dialogo = DialogoFicha(self, "Nuevo cliente", CAMPOS_CLIENTE)
        if dialogo.exec():
            self.ctx.clientes.guardar(dialogo.datos())
            self.refrescar()

    def editar(self) -> None:
        cliente_id = self.tabla.id_requerido("Seleccioná un cliente de la lista.")
        dialogo = DialogoFicha(self, "Editar cliente", CAMPOS_CLIENTE, self.ctx.clientes.obtener(cliente_id))
        if dialogo.exec():
            self.ctx.clientes.guardar(dialogo.datos(), cliente_id)
            self.refrescar()

    def estado(self) -> None:
        c = self.ctx.clientes.obtener(self.tabla.id_requerido("Seleccioná un cliente de la lista."))
        if c["activo"] and not confirmar(self, f"¿Desactivar al cliente «{c['nombre']}»? Sus ventas se conservan.", "Desactivar"):
            return
        self.ctx.clientes.cambiar_estado(c["id"], not c["activo"])
        self.refrescar()
