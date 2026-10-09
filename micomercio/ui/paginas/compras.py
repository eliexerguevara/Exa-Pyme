from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QLineEdit, QTabWidget, QVBoxLayout, QWidget

from ...core.dinero import a_centavos, a_milesimas, de_centavos, fmt_cantidad, fmt_dinero, importe_linea
from ...core.errores import ErrorNegocio
from ..comunes import (
    Buscador, CampoDecimal, Dialogo, DialogoElegirProducto, Pagina, SelectorPeriodo, Tabla, boton, cd, cf, confirmar,
    cq, etiqueta, fila,
)


class DialogoFicha(Dialogo):
    """Formulario simple de campos de texto (proveedores y clientes)."""

    def __init__(self, padre, titulo: str, campos: list[tuple[str, str, object]], datos=None):
        super().__init__(padre, titulo, ancho=480)
        self.controles = {}
        for clave, rotulo, opciones in campos:
            if opciones:
                control = QComboBox()
                control.addItems(opciones)
                if datos:
                    control.setCurrentText(datos[clave])
            else:
                control = QLineEdit(datos[clave] if datos else "")
            self.controles[clave] = control
            self.formulario.addRow(rotulo + ":", control)
        self.terminar()

    def datos(self) -> dict:
        return {c: (w.currentText() if isinstance(w, QComboBox) else w.text()) for c, w in self.controles.items()}

    def guardar(self) -> None:
        if not self.datos()["nombre"].strip():
            raise ErrorNegocio("Escribí el nombre.")
        self.accept()


CAMPOS_PROVEEDOR = [("nombre", "Nombre", None), ("cuit", "CUIT", None), ("telefono", "Teléfono", None),
                    ("email", "Correo electrónico", None), ("direccion", "Dirección", None), ("notas", "Notas", None)]


class DialogoLineaCompra(Dialogo):
    def __init__(self, padre, producto):
        super().__init__(padre, "Agregar a la compra", "Agregar", 420)
        self.cuerpo.insertWidget(0, etiqueta(producto["nombre"], "subtitulo"))
        self.cantidad = CampoDecimal("Cantidad comprada", 3)
        self.costo = CampoDecimal("Precio Costo unitario", dinero=True)
        self.costo.poner(de_centavos(producto["costo_cent"]))
        self.formulario.addRow(f"Cantidad comprada ({producto['unidad']}):", self.cantidad)
        self.formulario.addRow("Precio Costo unitario ($):", self.costo)
        self.terminar()
        self.cantidad.setFocus()

    def guardar(self) -> None:
        if self.cantidad.valor() <= 0:
            raise ErrorNegocio("La cantidad debe ser mayor a cero.")
        self.costo.valor()
        self.accept()


class DialogoCompra(QDialog):
    def __init__(self, padre, ctx):
        super().__init__(padre)
        self.ctx, self.items = ctx, []
        self.setWindowTitle("Nueva compra")
        self.resize(860, 600)
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 16)
        v.setSpacing(10)
        self.proveedor = QComboBox()
        self.proveedor.addItem("(Sin proveedor)", None)
        for p in ctx.compras.proveedores():
            self.proveedor.addItem(p["nombre"], p["id"])
        self.comprobante = QLineEdit()
        self.comprobante.setPlaceholderText("N° de factura o remito (opcional)")
        v.addLayout(fila(etiqueta("Proveedor:"), self.proveedor, etiqueta("Comprobante:"), self.comprobante))
        v.addLayout(fila(boton("Agregar producto", self.agregar, "primario"), boton("Quitar", self.quitar, "peligro"), None))
        self.tabla = Tabla(["Código", "Producto", "Cantidad", "Costo anterior", "Precio Costo nuevo", "Subtotal"], ordenable=False)
        v.addWidget(self.tabla, 1)
        self.actualizar_precios = QCheckBox(
            "Actualizar el Precio de venta final según el nuevo costo (mantiene el Porcentaje de ganancia de cada producto)")
        self.actualizar_precios.setChecked(True)
        v.addWidget(self.actualizar_precios)
        v.addWidget(etiqueta("Al confirmar se suma el stock y se registra el nuevo Precio Costo. "
                             "Las ventas ya realizadas no se modifican.", "nota", True))
        self.total = etiqueta("Total: $ 0,00", "grande")
        self.b_confirmar = boton("Confirmar compra", self.confirmar, "primario")
        v.addLayout(fila(self.total, None, boton("Cancelar", self.reject), self.b_confirmar))

    def agregar(self) -> None:
        elegir = DialogoElegirProducto(self, self.ctx)
        if not elegir.exec():
            return
        producto = self.ctx.productos.obtener(elegir.producto_id)
        linea = DialogoLineaCompra(self, producto)
        if not linea.exec():
            return
        self.items = [i for i in self.items if i["producto_id"] != producto["id"]]
        self.items.append({"producto_id": producto["id"], "codigo": producto["codigo"], "nombre": producto["nombre"],
                           "costo_anterior": producto["costo_cent"], "cantidad": linea.cantidad.valor(),
                           "costo_cent": a_centavos(linea.costo.valor())})
        self.mostrar()

    def quitar(self) -> None:
        n = self.tabla.currentRow()
        if 0 <= n < len(self.items):
            del self.items[n]
            self.mostrar()

    def mostrar(self) -> None:
        total, filas = 0, []
        for i in self.items:
            subtotal = importe_linea(i["costo_cent"], a_milesimas(i["cantidad"]))
            total += subtotal
            filas.append([i["codigo"], i["nombre"], cq(a_milesimas(i["cantidad"])), cd(i["costo_anterior"]),
                          cd(i["costo_cent"]), cd(subtotal)])
        self.tabla.cargar(filas)
        self.total.setText(f"Total: {fmt_dinero(total)}")

    def confirmar(self) -> None:
        if not self.items:
            raise ErrorNegocio("Agregá al menos un producto a la compra.")
        self.b_confirmar.setEnabled(False)
        try:
            self.ctx.compras.registrar(self.proveedor.currentData(), self.items, self.comprobante.text(),
                                       actualizar_precios=self.actualizar_precios.isChecked())
        finally:
            self.b_confirmar.setEnabled(True)
        self.accept()


class PaginaCompras(Pagina):
    titulo = "Compras y proveedores"

    def armar(self) -> None:
        pestanas = QTabWidget()
        compras = QWidget()
        vc = QVBoxLayout(compras)
        vc.setContentsMargins(0, 12, 0, 0)
        self.periodo = SelectorPeriodo("Este mes")
        self.periodo.cambiado.connect(self.cargar_compras)
        vc.addLayout(fila(boton("Nueva compra", self.nueva_compra, "primario"), self.periodo, None))
        self.tabla = Tabla(["N°", "Fecha", "Proveedor", "Comprobante", "Productos", "Total", "Usuario"], estirar=2)
        self.tabla.itemSelectionChanged.connect(self.cargar_detalle)
        vc.addWidget(self.tabla, 3)
        vc.addWidget(etiqueta("Detalle de la compra seleccionada", "subtitulo"))
        self.detalle = Tabla(["Código", "Producto", "Cantidad", "Precio Costo", "Subtotal"], ordenable=False)
        vc.addWidget(self.detalle, 2)
        pestanas.addTab(compras, "Compras")

        proveedores = QWidget()
        vp = QVBoxLayout(proveedores)
        vp.setContentsMargins(0, 12, 0, 0)
        self.buscador = Buscador("Buscar proveedor…")
        self.buscador.buscar.connect(self.cargar_proveedores)
        self.inactivos = QCheckBox("Mostrar inactivos")
        self.inactivos.toggled.connect(lambda _: self.cargar_proveedores())
        vp.addLayout(fila(self.buscador, self.inactivos, boton("Nuevo proveedor", self.nuevo_proveedor, "primario"),
                          boton("Editar", self.editar_proveedor), boton("Desactivar / activar", self.estado_proveedor)))
        self.tabla_prov = Tabla(["Nombre", "CUIT", "Teléfono", "Correo electrónico", "Dirección", "Estado"], estirar=0)
        self.tabla_prov.activada.connect(self.editar_proveedor)
        vp.addWidget(self.tabla_prov)
        pestanas.addTab(proveedores, "Proveedores")
        self.cuerpo.addWidget(pestanas, 1)

    def refrescar(self) -> None:
        self.cargar_compras()
        self.cargar_proveedores()

    def cargar_compras(self) -> None:
        compras = self.ctx.compras.listar(*self.periodo.rango())
        self.tabla.cargar([[(str(c["id"]), c["id"]), cf(c["fecha"]), c["proveedor"], c["comprobante"],
                            (str(c["renglones"]), c["renglones"]), cd(c["total_cent"]), c["usuario"]] for c in compras],
                          [c["id"] for c in compras])
        self.cargar_detalle()

    def cargar_detalle(self) -> None:
        compra_id = self.tabla.id_actual()
        items = self.ctx.compras.items(compra_id) if compra_id else []
        self.detalle.cargar([[i["codigo"], i["nombre"], (f"{fmt_cantidad(i['cantidad_mil'])} {i['unidad']}", 0),
                              cd(i["costo_unit_cent"]), cd(i["subtotal_cent"])] for i in items])

    def nueva_compra(self) -> None:
        if DialogoCompra(self, self.ctx).exec():
            self.refrescar()

    def cargar_proveedores(self) -> None:
        proveedores = self.ctx.compras.proveedores(self.buscador.text(), not self.inactivos.isChecked())
        self.tabla_prov.cargar([[p["nombre"], p["cuit"], p["telefono"], p["email"], p["direccion"],
                                 "Activo" if p["activo"] else "Inactivo"] for p in proveedores], [p["id"] for p in proveedores])

    def nuevo_proveedor(self) -> None:
        dialogo = DialogoFicha(self, "Nuevo proveedor", CAMPOS_PROVEEDOR)
        if dialogo.exec():
            self.ctx.compras.guardar_proveedor(dialogo.datos())
            self.cargar_proveedores()

    def editar_proveedor(self) -> None:
        proveedor_id = self.tabla_prov.id_requerido("Seleccioná un proveedor de la lista.")
        dialogo = DialogoFicha(self, "Editar proveedor", CAMPOS_PROVEEDOR, self.ctx.compras.proveedor(proveedor_id))
        if dialogo.exec():
            self.ctx.compras.guardar_proveedor(dialogo.datos(), proveedor_id)
            self.cargar_proveedores()

    def estado_proveedor(self) -> None:
        p = self.ctx.compras.proveedor(self.tabla_prov.id_requerido("Seleccioná un proveedor de la lista."))
        if p["activo"] and not confirmar(self, f"¿Desactivar al proveedor «{p['nombre']}»? Sus compras se conservan.", "Desactivar"):
            return
        self.ctx.compras.cambiar_estado_proveedor(p["id"], not p["activo"])
        self.cargar_proveedores()
