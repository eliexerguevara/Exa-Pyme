from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QLineEdit, QTabWidget, QVBoxLayout, QWidget

from ...core.dinero import de_milesimas, fmt_cantidad, fmt_dinero
from ...servicios.inventario import TIPOS
from .. import tema
from ..comunes import (
    Buscador, CampoDecimal, Dialogo, DialogoElegirProducto, Pagina, SelectorPeriodo, Tabla, Tarjeta, boton, cd, cf,
    cq, etiqueta, fila,
)


class DialogoMovimiento(Dialogo):
    OPCIONES = [
        ("entrada", "Entrada (suma al stock)"),
        ("salida", "Salida (resta del stock)"),
        ("devolucion", "Devolución de un cliente (suma al stock)"),
        ("ajuste", "Ajuste: corregir el stock con la cantidad real contada"),
    ]

    def __init__(self, padre, ctx, producto_id: int):
        super().__init__(padre, "Registrar movimiento de inventario", "Registrar", 520)
        self.ctx, self.producto = ctx, ctx.productos.obtener(producto_id)
        p = self.producto
        self.cuerpo.insertWidget(0, etiqueta(
            f"{p['nombre']}\nStock actual: {fmt_cantidad(p['stock_mil'])} {p['unidad']}", "subtitulo"))
        self.tipo = QComboBox()
        for clave, nombre in self.OPCIONES:
            self.tipo.addItem(nombre, clave)
        self.cantidad = CampoDecimal("Cantidad", 3)
        self.rotulo = etiqueta("Cantidad:")
        self.motivo = QLineEdit()
        self.motivo.setPlaceholderText("Por ejemplo: rotura, vencimiento, conteo de inventario…")
        self.formulario.addRow("Tipo de movimiento:", self.tipo)
        self.formulario.addRow(self.rotulo, self.cantidad)
        self.formulario.addRow("Motivo:", self.motivo)
        self.tipo.currentIndexChanged.connect(lambda _: self.cambio_tipo())
        self.terminar()
        self.cantidad.setFocus()

    def cambio_tipo(self) -> None:
        ajuste = self.tipo.currentData() == "ajuste"
        self.rotulo.setText("Cantidad real contada:" if ajuste else "Cantidad:")
        self.cantidad.negativo = ajuste and self.ctx.inventario.permite_negativo()
        if ajuste:
            self.cantidad.poner(de_milesimas(self.producto["stock_mil"]))
            self.cantidad.selectAll()

    def guardar(self) -> None:
        self.ctx.inventario.registrar_movimiento(
            self.producto["id"], self.tipo.currentData(), self.cantidad.valor(), self.motivo.text())
        self.accept()


class PaginaInventario(Pagina):
    titulo = "Inventario"

    def armar(self) -> None:
        self.t_costo = Tarjeta("Valor estimado del inventario (al Precio Costo)")
        self.t_venta = Tarjeta("Valor a precio de venta final")
        self.t_bajo = Tarjeta("Productos con stock bajo")
        self.t_agotados = Tarjeta("Productos agotados")
        self.cuerpo.addLayout(fila(self.t_costo, self.t_venta, self.t_bajo, self.t_agotados, espacio=12))

        pestanas = QTabWidget()
        # --- existencias ---
        existencias = QWidget()
        ve = QVBoxLayout(existencias)
        ve.setContentsMargins(0, 12, 0, 0)
        self.buscador = Buscador("Buscar producto…")
        self.buscador.buscar.connect(self.cargar_existencias)
        self.estado = QComboBox()
        for clave, nombre in [("todos", "Todos los productos"), ("bajo", "Solo stock bajo"), ("agotado", "Solo agotados")]:
            self.estado.addItem(nombre, clave)
        self.estado.currentIndexChanged.connect(lambda _: self.cargar_existencias())
        ve.addLayout(fila(self.buscador, self.estado, boton("Registrar movimiento", self.movimiento, "primario"),
                          boton("Ver movimientos del producto", self.ver_producto)))
        self.tabla = Tabla(["Código", "Producto", "Categoría", "Disponible", "Unidad", "Stock mínimo", "Precio Costo",
                            "Valor al costo", "Estado"])
        self.tabla.activada.connect(self.movimiento)
        ve.addWidget(self.tabla)
        pestanas.addTab(existencias, "Existencias")

        # --- movimientos ---
        movimientos = QWidget()
        vm = QVBoxLayout(movimientos)
        vm.setContentsMargins(0, 12, 0, 0)
        self.periodo = SelectorPeriodo("Este mes")
        self.periodo.cambiado.connect(self.cargar_movimientos)
        self.tipo = QComboBox()
        self.tipo.addItem("Todos los movimientos", None)
        for clave, nombre in TIPOS.items():
            self.tipo.addItem(nombre, clave)
        self.tipo.currentIndexChanged.connect(lambda _: self.cargar_movimientos())
        self.filtro_producto: int | None = None
        self.l_producto = etiqueta("", "suave")
        self.b_todos = boton("Ver todos los productos", self.quitar_filtro)
        vm.addLayout(fila(self.periodo, self.tipo, self.l_producto, self.b_todos, None))
        self.tabla_mov = Tabla(["Fecha", "Producto", "Movimiento", "Cantidad", "Stock resultante", "Motivo", "Usuario"])
        vm.addWidget(self.tabla_mov)
        pestanas.addTab(movimientos, "Historial de movimientos")
        self.pestanas = pestanas
        self.cuerpo.addWidget(pestanas, 1)

    def refrescar(self) -> None:
        valor = self.ctx.inventario.valor_inventario()
        alertas = self.ctx.inventario.alertas()
        self.t_costo.poner(fmt_dinero(valor["costo_cent"]))
        self.t_venta.poner(fmt_dinero(valor["venta_cent"]))
        self.t_bajo.poner(str(alertas["bajos"]), tema.NARANJA if alertas["bajos"] else tema.TEXTO)
        self.t_agotados.poner(str(alertas["agotados"]), tema.ROJO if alertas["agotados"] else tema.TEXTO)
        self.cargar_existencias()
        self.cargar_movimientos()

    def cargar_existencias(self) -> None:
        productos = self.ctx.inventario.existencias(self.buscador.text(), self.estado.currentData())
        filas, colores = [], {}
        for n, p in enumerate(productos):
            if p["stock_mil"] <= 0:
                estado, colores[n] = "Agotado", tema.ROJO
            elif p["stock_mil"] <= p["stock_minimo_mil"]:
                estado, colores[n] = "Stock bajo", tema.NARANJA
            else:
                estado = "Normal"
            valor = max(p["stock_mil"], 0) * p["costo_cent"] // 1000
            filas.append([p["codigo"], p["nombre"], p["categoria"], cq(p["stock_mil"]), p["unidad"],
                          cq(p["stock_minimo_mil"]), cd(p["costo_cent"]), cd(valor), estado])
        self.tabla.cargar(filas, [p["id"] for p in productos], colores)

    def cargar_movimientos(self) -> None:
        desde, hasta = self.periodo.rango()
        movimientos = self.ctx.inventario.movimientos(self.filtro_producto, desde, hasta, self.tipo.currentData())
        self.tabla_mov.cargar([[
            cf(m["fecha"]), m["nombre"], TIPOS.get(m["tipo"], m["tipo"]),
            (("+" if m["cantidad_mil"] > 0 else "") + fmt_cantidad(m["cantidad_mil"]), m["cantidad_mil"]),
            cq(m["stock_resultante_mil"]), m["motivo"], m["usuario"],
        ] for m in movimientos])
        self.b_todos.setVisible(self.filtro_producto is not None)

    def movimiento(self) -> None:
        self.ctx.requiere("inventario")
        producto_id = self.tabla.id_actual()
        if producto_id is None:
            elegir = DialogoElegirProducto(self, self.ctx)
            if not elegir.exec():
                return
            producto_id = elegir.producto_id
        if DialogoMovimiento(self, self.ctx, producto_id).exec():
            self.refrescar()

    def ver_producto(self) -> None:
        self.filtro_producto = self.tabla.id_requerido("Seleccioná un producto de la lista.")
        self.l_producto.setText("Producto: " + self.ctx.productos.obtener(self.filtro_producto)["nombre"])
        self.periodo.combo.setCurrentText("Este mes")
        self.cargar_movimientos()
        self.pestanas.setCurrentIndex(1)

    def quitar_filtro(self) -> None:
        self.filtro_producto = None
        self.l_producto.setText("")
        self.cargar_movimientos()
