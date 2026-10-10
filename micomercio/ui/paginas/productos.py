from __future__ import annotations

import os
from decimal import Decimal

from PySide6.QtCore import QSize, Qt, QThread, QTimer, Signal, Slot

from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
    QProgressDialog, QVBoxLayout,
)

from ...core import precios
from ...core.dinero import D, de_milesimas, fmt_numero, fmt_pct, parse_decimal
from ...core.errores import ErrorNegocio
from ...core.util import fecha_legible
from ...servicios import catalogo_imagenes, csv_io
from ...servicios.productos import UNIDADES
from .. import imagenes, tema
from ..comunes import (
    Buscador, CampoDecimal, Dialogo, Pagina, Tabla, advertir, boton, cd, cf, confirmar, cq, etiqueta, fila, informar,
    panel,
)

ORIGENES = {"alta": "Alta", "edicion": "Edición", "masivo": "Cambio masivo", "compra": "Compra", "importacion": "Importación"}


def buscar_imagen(ctx, codigo_barras: str):
    """Imagen de un código de barras: primero en el catálogo del comercio y, si está habilitado, en el de Internet."""
    datos = ctx.productos.imagen_de_catalogo(codigo_barras)
    if not datos and ctx.config.booleano("catalogo_en_linea"):
        datos = catalogo_imagenes.buscar(codigo_barras)
    return datos


class _BusquedaImagen(QThread):
    """Busca en segundo plano la imagen del catálogo para un código de barras."""

    terminada = Signal(str, object)  # (código de barras, imagen o None)

    def __init__(self, ctx, codigo: str):
        super().__init__()
        self.ctx, self.codigo = ctx, codigo

    def run(self) -> None:
        try:
            self.terminada.emit(self.codigo, buscar_imagen(self.ctx, self.codigo))
        except Exception:  # sin conexión o cualquier otro problema: el producto se carga igual, sin imagen
            self.terminada.emit(self.codigo, None)


class DialogoProducto(Dialogo):
    """Alta y edición de productos, con cálculo automático de precios mientras se escribe."""

    def __init__(self, padre, ctx, producto_id: int | None = None, datos: dict | None = None):
        super().__init__(padre, "Editar producto" if producto_id else "Nuevo producto", ancho=960)
        self.ctx, self.producto_id = ctx, producto_id
        self.manual = False
        self.cuerpo.removeItem(self.formulario)

        # --- datos generales ---
        self.nombre, self.codigo, self.barras, self.marca = QLineEdit(), QLineEdit(), QLineEdit(), QLineEdit()
        self.codigo.setPlaceholderText("Se genera solo si lo dejás vacío")
        self.barras.setPlaceholderText("Escaneá o escribí el código")
        self.descripcion = QPlainTextEdit()
        self.descripcion.setFixedHeight(58)
        self.categoria = QComboBox()
        self.categoria.setEditable(True)
        self.categoria.addItems([""] + [c["nombre"] for c in ctx.productos.categorias()])
        self.proveedor = QComboBox()
        self.proveedor.addItem("(Sin proveedor)", None)
        for p in ctx.compras.proveedores():
            self.proveedor.addItem(p["nombre"], p["id"])
        self.unidad = QComboBox()
        self.unidad.setEditable(True)
        self.unidad.addItems(UNIDADES)
        self.stock = CampoDecimal("Cantidad disponible", 3)
        self.stock_minimo = CampoDecimal("Stock mínimo", 3)
        self.activo = QCheckBox("Producto activo (se puede vender)")
        self.activo.setChecked(True)

        izquierda, vi = panel("Datos del producto")
        f1 = QFormLayout()
        f1.setSpacing(9)
        f1.addRow("Nombre del producto:", self.nombre)
        f1.addRow("Código interno:", self.codigo)
        f1.addRow("Código de barras:", self.barras)
        f1.addRow("Descripción:", self.descripcion)
        f1.addRow("Categoría:", self.categoria)
        f1.addRow("Marca:", self.marca)
        f1.addRow("Proveedor:", self.proveedor)
        f1.addRow("Unidad de medida:", self.unidad)
        f1.addRow("Cantidad disponible:", self.stock)
        f1.addRow("Stock mínimo:", self.stock_minimo)
        f1.addRow("", self.activo)
        vi.addLayout(f1)
        vi.addStretch(1)

        # --- precio ---
        self.costo = CampoDecimal("Precio Costo", dinero=True)
        self.impuestos = QComboBox()
        self.impuestos.setEditable(True)
        self.impuestos.addItems([fmt_pct(D(i)) for i in precios.IMPUESTOS_HABITUALES])
        self.impuestos.setMaximumWidth(170)
        self.impuestos.setToolTip("Elegí 0, 10,5, 21 o 27, o escribí otro porcentaje.")
        self.ganancia = CampoDecimal("Porcentaje de ganancia", negativo=True)
        self.metodo = QComboBox()
        for clave, nombre in precios.METODOS.items():
            self.metodo.addItem(nombre, clave)
        self.metodo.setMinimumWidth(250)
        self.neto = QLineEdit()
        self.neto.setReadOnly(True)
        self.neto.setMaximumWidth(170)
        self.neto.setAlignment(self.costo.alignment())
        self.final = CampoDecimal("Precio de venta final", dinero=True)
        self.final.setStyleSheet(f"font-size: 13pt; font-weight: 600; color: {tema.AZUL};")
        self.aviso = etiqueta("", "aviso", ajustar=True)
        self.boton_margen = boton("Recalcular margen", self.recalcular_margen,
                                  ayuda="Escribe en «Porcentaje de ganancia» la ganancia que resulta del precio final.")
        self.boton_auto = boton("Volver al cálculo automático", self.volver_automatico)
        self.error_precio = etiqueta("", ajustar=True)
        self.error_precio.setStyleSheet(f"color: {tema.ROJO};")

        derecha, vd = panel("Precio")
        f2 = QFormLayout()
        f2.setSpacing(9)
        f2.addRow("Precio Costo ($):", self.costo)
        f2.addRow("Impuestos (%):", self.impuestos)
        f2.addRow("Porcentaje de ganancia (%):", self.ganancia)
        f2.addRow("La ganancia se calcula como:", self.metodo)
        f2.addRow("Precio de venta sin impuestos ($):", self.neto)
        f2.addRow("Precio de venta final ($):", self.final)
        vd.addLayout(f2)
        vd.addWidget(self.error_precio)
        vd.addWidget(self.aviso)
        vd.addLayout(fila(self.boton_margen, self.boton_auto, None))
        # --- imagen ---
        self.imagen, self.imagen_origen, self.imagen_cambiada, self.busqueda = None, "manual", False, None
        self.foto = QLabel()
        self.foto.setFixedSize(150, 150)
        self.foto.setAlignment(Qt.AlignCenter)
        self.foto.setStyleSheet(f"background: white; border: 1px solid {tema.BORDE}; border-radius: 8px; color: {tema.TEXTO_SUAVE};")
        self.estado_foto = etiqueta("", "suave", True)
        self.b_quitar_foto = boton("Quitar", self.quitar_imagen)
        botones_foto = QVBoxLayout()
        botones_foto.addWidget(etiqueta("Imagen del producto", "subtitulo"))
        botones_foto.addWidget(self.estado_foto)
        botones_foto.addLayout(fila(boton("Elegir imagen…", self.elegir_imagen), self.b_quitar_foto, None))
        botones_foto.addStretch(1)
        vd.addSpacing(6)
        vd.addLayout(fila(self.foto, botones_foto, espacio=14))
        vd.addStretch(1)

        columnas = QHBoxLayout()
        columnas.addWidget(izquierda, 1)
        columnas.addWidget(derecha, 1)
        self.cuerpo.addLayout(columnas)
        self.terminar()
        # El lector de códigos envía Enter: no debe guardar el formulario por accidente.
        self.boton_aceptar.setDefault(False)
        self.boton_aceptar.setAutoDefault(False)

        if producto_id:
            p = ctx.productos.obtener(producto_id)
            datos = ctx.productos.datos_para_duplicar(producto_id)
            datos.update(codigo=p["codigo"], codigo_barras=p["codigo_barras"], nombre=p["nombre"],
                         stock=de_milesimas(p["stock_mil"]), activo=bool(p["activo"]))
            self.stock.setReadOnly(True)
            self.imagen = ctx.productos.imagen(producto_id)
            self.stock.setToolTip("El stock se modifica desde Inventario, para que quede registrado el movimiento.")
        self.cargar(datos or {
            "impuesto_pct": ctx.config.decimal("impuesto_predeterminado"), "ganancia_pct": Decimal(0),
            "metodo_precio": ctx.config.obtener("metodo_precio_predeterminado"), "costo": Decimal(0),
            "stock": Decimal(0), "stock_minimo": Decimal(0),
        })

        self.costo.textEdited.connect(lambda _: self.calcular())
        self.ganancia.textEdited.connect(lambda _: self.calcular())
        self.impuestos.editTextChanged.connect(lambda _: self.calcular())
        self.metodo.currentIndexChanged.connect(lambda _: self.calcular())
        self.final.textEdited.connect(lambda _: self.final_editado())
        self.barras.editingFinished.connect(self.buscar_en_catalogo)
        self.mostrar_imagen("")
        # Un producto que ya tiene código de barras pero no imagen: se busca apenas se abre la ficha.
        QTimer.singleShot(0, self.buscar_en_catalogo)
        self.nombre.setFocus()

    # ---- imagen ----------------------------------------------------------
    def mostrar_imagen(self, estado: str) -> None:
        vista = imagenes.pixmap(self.imagen, 146)
        if vista is not None:
            self.foto.setPixmap(vista)
        else:
            self.foto.clear()
            self.foto.setText("Sin imagen")
        self.b_quitar_foto.setEnabled(self.imagen is not None)
        self.estado_foto.setText(estado or (
            "" if self.imagen is not None else "Si el código de barras está en el catálogo, la imagen se carga sola."))

    def buscar_en_catalogo(self) -> None:
        """Si el producto no tiene imagen, busca una en el catálogo con su código de barras."""
        codigo = self.barras.text().strip()
        if self.imagen is not None or not catalogo_imagenes.candidatos(codigo) or os.environ.get("EXAPYME_SIN_CATALOGO"):
            return
        if self.busqueda is not None and self.busqueda.isRunning():
            return
        self.estado_foto.setText("Buscando la imagen en el catálogo…")
        self.busqueda = _BusquedaImagen(self.ctx, codigo)
        self.busqueda.terminada.connect(self.imagen_encontrada)
        self.busqueda.start()

    @Slot(str, object)
    def imagen_encontrada(self, codigo: str, datos) -> None:
        if self.imagen is not None or codigo != self.barras.text().strip():
            return  # mientras tanto se eligió otra imagen o se cambió el código
        if not datos:
            if self.ctx.productos.estado_catalogo()["imagenes"]:
                self.mostrar_imagen("El catálogo no tiene imagen para este código. Podés elegir una.")
            else:
                self.mostrar_imagen("Todavía no se eligió la carpeta del catálogo de imágenes: se hace en "
                                    "Configuración → Ventas y precios, en la computadora principal.")
            return
        try:
            self.imagen = imagenes.normalizar(datos)
        except ErrorNegocio:
            self.mostrar_imagen("")
            return
        self.imagen_origen, self.imagen_cambiada = "catalogo", True
        self.mostrar_imagen("Imagen del catálogo, encontrada por el código de barras.")

    def elegir_imagen(self) -> None:
        ruta, _ = QFileDialog.getOpenFileName(self, "Elegir la imagen del producto", "", "Imágenes (*.jpg *.jpeg *.png *.webp *.bmp)")
        if not ruta:
            return
        try:
            with open(ruta, "rb") as archivo:
                contenido = archivo.read()
        except OSError:
            raise ErrorNegocio("No se pudo abrir el archivo.") from None
        self.imagen = imagenes.normalizar(contenido)
        self.imagen_origen, self.imagen_cambiada = "manual", True
        self.mostrar_imagen("Imagen elegida a mano.")

    def quitar_imagen(self) -> None:
        self.imagen, self.imagen_cambiada = None, True
        self.mostrar_imagen("Sin imagen.")

    def done(self, codigo: int) -> None:
        if self.busqueda is not None and self.busqueda.isRunning():
            self.busqueda.wait(9000)
        super().done(codigo)

    # ---- carga -----------------------------------------------------------
    def cargar(self, d: dict) -> None:
        self.nombre.setText(d.get("nombre", ""))
        self.codigo.setText(d.get("codigo", ""))
        self.barras.setText(d.get("codigo_barras", ""))
        self.descripcion.setPlainText(d.get("descripcion", ""))
        self.categoria.setCurrentText(d.get("categoria", ""))
        self.marca.setText(d.get("marca", ""))
        self.proveedor.setCurrentIndex(max(0, self.proveedor.findData(d.get("proveedor_id"))))
        self.unidad.setCurrentText(d.get("unidad", "unidad"))
        self.stock.poner(d.get("stock", 0))
        self.stock_minimo.poner(d.get("stock_minimo", 0))
        self.activo.setChecked(d.get("activo", True))
        self.costo.poner(d.get("costo", 0))
        self.impuestos.setCurrentText(fmt_pct(d.get("impuesto_pct", 21)))
        self.ganancia.poner(d.get("ganancia_pct", 0))
        self.metodo.setCurrentIndex(max(0, self.metodo.findData(d.get("metodo_precio", "margen"))))
        self.manual = bool(d.get("precio_manual"))
        if self.manual:
            self.final.poner(d.get("precio_final"))
            self.mostrar_manual()
        else:
            self.calcular()

    # ---- cálculo ---------------------------------------------------------
    def _impuesto(self) -> Decimal:
        try:
            valor = parse_decimal(self.impuestos.currentText())
        except ValueError:
            raise ErrorNegocio("El valor de «Impuestos» no es un número válido.") from None
        if valor < 0:
            raise ErrorNegocio("Los Impuestos no pueden ser negativos.")
        return valor

    def calcular(self) -> None:
        """Cambió el costo, los impuestos o la ganancia: el precio vuelve a calcularse solo."""
        self.manual = False
        self.aviso.hide()
        self.boton_margen.hide()
        self.boton_auto.hide()
        try:
            precio = precios.calcular_precio(self.costo.valor(), self._impuesto(), self.ganancia.valor(), self.metodo.currentData())
        except ErrorNegocio as e:
            self.error_precio.setText(str(e))
            self.neto.clear()
            self.final.clear()
            return
        self.error_precio.clear()
        self.neto.setText(fmt_numero(precio.sin_impuestos))
        self.final.poner(precio.final)

    def final_editado(self) -> None:
        self.manual = True
        self.mostrar_manual()

    def _ganancia_resultante(self) -> Decimal:
        return precios.ganancia_desde_final(self.costo.valor(), self._impuesto(), self.final.valor(), self.metodo.currentData())

    def mostrar_manual(self) -> None:
        try:
            resultante = self._ganancia_resultante()
            self.neto.setText(fmt_numero(precios.sin_impuestos_desde_final(self.final.valor(), self._impuesto())))
        except ErrorNegocio as e:
            self.error_precio.setText(str(e))
            return
        self.error_precio.clear()
        texto = (f"Modificaste a mano el Precio de venta final. Con este precio, la ganancia resultante es "
                 f"{fmt_pct(resultante)} %.")
        if resultante < 0:
            texto += " ¡Atención! Estás vendiendo por debajo del costo."
        self.aviso.setText(texto)
        self.aviso.show()
        self.boton_margen.show()
        self.boton_auto.show()

    def recalcular_margen(self) -> None:
        self.ganancia.poner(self._ganancia_resultante())

    def volver_automatico(self) -> None:
        self.calcular()

    # ---- guardar ---------------------------------------------------------
    def guardar(self) -> None:
        datos = {
            "nombre": self.nombre.text(), "codigo": self.codigo.text(), "codigo_barras": self.barras.text(),
            "descripcion": self.descripcion.toPlainText(), "categoria": self.categoria.currentText(),
            "marca": self.marca.text(), "proveedor_id": self.proveedor.currentData(),
            "unidad": self.unidad.currentText(), "stock": self.stock.valor(), "stock_minimo": self.stock_minimo.valor(),
            "activo": self.activo.isChecked(), "costo": self.costo.valor(), "impuesto_pct": self._impuesto(),
            "ganancia_pct": self.ganancia.valor(), "metodo_precio": self.metodo.currentData(),
            "precio_manual": self.manual, "precio_final": self.final.valor() if self.manual else None,
        }
        if self.manual and self._ganancia_resultante() < 0 and not confirmar(
            self, "El Precio de venta final es menor al costo: vas a perder plata en cada venta.\n\n¿Guardar igual?",
            "Guardar igual",
        ):
            return
        if self.imagen_cambiada:
            datos.update(imagen=self.imagen, imagen_origen=self.imagen_origen, quitar_imagen=self.imagen is None,
                         miniatura=imagenes.miniatura(self.imagen) if self.imagen else None)
        if self.producto_id:
            self.ctx.productos.actualizar(self.producto_id, datos)
        else:
            self.producto_id = self.ctx.productos.crear(datos)
        self.accept()


class DialogoCambioMasivo(QDialog):
    """Aumenta o disminuye precios en lote, siempre con vista previa antes de guardar."""

    def __init__(self, padre, ctx):
        super().__init__(padre)
        self.ctx, self.vista = ctx, []
        self.setWindowTitle("Cambio masivo de precios")
        self.resize(980, 620)
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 16)
        v.setSpacing(10)

        self.campo = QComboBox()
        self.campo.addItem("Precio Costo (recalcula el precio de venta manteniendo la ganancia)", "costo")
        self.campo.addItem("Precio de venta final (el costo no cambia)", "final")
        self.sentido = QComboBox()
        self.sentido.addItems(["Aumentar", "Disminuir"])
        self.valor = CampoDecimal("Valor")
        self.tipo = QComboBox()
        self.tipo.addItem("% (porcentaje)", "porcentaje")
        self.tipo.addItem("$ (importe fijo)", "importe")
        self.redondeo = QComboBox()
        for texto, multiplo in [("Sin redondeo", 0), ("$ 1", 1), ("$ 10", 10), ("$ 50", 50), ("$ 100", 100)]:
            self.redondeo.addItem(texto, multiplo)
        self.categoria = QComboBox()
        self.categoria.addItem("Todas las categorías", None)
        for c in ctx.productos.categorias():
            self.categoria.addItem(c["nombre"], c["id"])
        self.proveedor = QComboBox()
        self.proveedor.addItem("Todos los proveedores", None)
        for p in ctx.compras.proveedores():
            self.proveedor.addItem(p["nombre"], p["id"])
        self.texto = QLineEdit()
        self.texto.setPlaceholderText("Nombre, marca o código (opcional)")

        v.addLayout(fila(etiqueta("Modificar:"), self.campo, None))
        v.addLayout(fila(self.sentido, self.valor, self.tipo, 12, etiqueta("Redondear el precio final a:"), self.redondeo, None))
        v.addLayout(fila(etiqueta("Productos:"), self.categoria, self.proveedor, self.texto))
        v.addLayout(fila(boton("Ver vista previa", self.previsualizar, "primario"), None))
        self.tabla = Tabla(["Código", "Producto", "Costo actual", "Costo nuevo", "Precio final actual",
                            "Precio final nuevo", "Ganancia nueva", "Observación"], minimo=170)
        v.addWidget(self.tabla, 1)
        self.resumen = etiqueta("Completá los datos y pulsá «Ver vista previa». Todavía no se guardó ningún cambio.", "nota", True)
        v.addWidget(self.resumen)
        self.boton_guardar = boton("Guardar cambios", self.aplicar, "primario")
        self.boton_guardar.setEnabled(False)
        v.addLayout(fila(None, boton("Cerrar", self.reject), self.boton_guardar))
        for control in (self.campo, self.sentido, self.tipo, self.redondeo, self.categoria, self.proveedor):
            control.currentIndexChanged.connect(lambda _: self.invalidar())
        self.valor.textEdited.connect(lambda _: self.invalidar())
        self.texto.textEdited.connect(lambda _: self.invalidar())

    def invalidar(self) -> None:
        self.boton_guardar.setEnabled(False)

    def previsualizar(self) -> None:
        valor = self.valor.valor_o(Decimal(0)) or Decimal(0)
        if self.sentido.currentText() == "Disminuir":
            valor = -valor
        self.vista = self.ctx.productos.previsualizar_cambio_masivo(
            self.campo.currentData(), self.tipo.currentData(), valor, self.redondeo.currentData(),
            self.texto.text(), self.categoria.currentData(), self.proveedor.currentData(),
        )
        filas, colores = [], {}
        for n, f in enumerate(self.vista):
            c = f["campos"]
            if c is None:
                filas.append([f["codigo"], f["nombre"], cd(f["costo_ant_cent"]), "", cd(f["final_ant_cent"]), "", "", f["error"]])
                colores[n] = tema.ROJO
            else:
                filas.append([f["codigo"], f["nombre"], cd(f["costo_ant_cent"]), cd(c["costo_cent"]), cd(f["final_ant_cent"]),
                              cd(c["precio_final_cent"]), fmt_pct(D(c["ganancia_pct"])) + " %", ""])
        self.tabla.cargar(filas, colores=colores)
        validos = sum(1 for f in self.vista if f["campos"] is not None)
        errores = len(self.vista) - validos
        texto = f"Vista previa: se modificarán {validos} productos."
        if errores:
            texto += f" {errores} no se pueden modificar (en rojo) y quedarán como están."
        self.resumen.setText(texto + " Todavía no se guardó nada.")
        self.boton_guardar.setEnabled(validos > 0)

    def aplicar(self) -> None:
        validos = sum(1 for f in self.vista if f["campos"] is not None)
        if not confirmar(self, f"Se van a modificar los precios de {validos} productos.\n\n¿Guardar los cambios?", "Guardar cambios"):
            return
        self.boton_guardar.setEnabled(False)
        cambiados = self.ctx.productos.aplicar_cambio_masivo(self.vista)
        informar(self, f"Listo: se actualizaron {cambiados} productos. Los cambios quedaron en el historial de precios.")
        self.accept()


class DialogoHistorialPrecios(QDialog):
    def __init__(self, padre, ctx, producto_id: int | None):
        super().__init__(padre)
        self.setWindowTitle("Historial de precios")
        self.resize(980, 520)
        v = QVBoxLayout(self)
        tabla = Tabla(["Fecha", "Producto", "Origen", "Costo anterior", "Precio Costo", "Impuestos", "Ganancia",
                       "Final anterior", "Precio de venta final", "Usuario"])
        tabla.cargar([[
            cf(h["fecha"]), h["nombre"], ORIGENES.get(h["origen"], h["origen"]), cd(h["costo_ant_cent"]), cd(h["costo_cent"]),
            fmt_pct(D(h["impuesto_pct"])) + " %", fmt_pct(D(h["ganancia_pct"])) + " %", cd(h["final_ant_cent"]),
            cd(h["final_cent"]), h["usuario"],
        ] for h in ctx.productos.historial_precios(producto_id)])
        v.addWidget(tabla)
        v.addLayout(fila(None, boton("Cerrar", self.accept)))


class PaginaProductos(Pagina):
    titulo = "Productos"

    def armar(self) -> None:
        self.buscador = Buscador("Buscar por nombre, código de barras, código interno o categoría…")
        self.buscador.buscar.connect(self.refrescar)
        self.categoria = QComboBox()
        self.categoria.currentIndexChanged.connect(lambda _: self.cargar())
        self.inactivos = QCheckBox("Mostrar inactivos")
        self.inactivos.toggled.connect(lambda _: self.cargar())
        self.cuerpo.addLayout(fila(self.buscador, self.categoria, self.inactivos))

        self.b_nuevo = boton("Nuevo producto", self.nuevo, "primario")
        self.b_editar = boton("Editar", self.editar)
        self.b_duplicar = boton("Duplicar", self.duplicar)
        self.b_estado = boton("Desactivar / activar", self.cambiar_estado)
        self.b_masivo = boton("Cambio masivo de precios", self.masivo)
        self.b_importar = boton("Importar CSV", self.importar)
        self.b_imagenes = boton("Buscar imágenes", self.completar_imagenes,
                                ayuda="Busca en el catálogo la imagen de cada producto que todavía no tiene, por su código de barras.")
        self.solo_edicion = [self.b_nuevo, self.b_editar, self.b_duplicar, self.b_estado, self.b_masivo, self.b_importar, self.b_imagenes]
        # Dos renglones: en pantallas angostas una sola fila cortaba los textos de los botones.
        self.cuerpo.addLayout(fila(self.b_nuevo, self.b_editar, self.b_duplicar, self.b_estado, self.b_imagenes, None))
        self.cuerpo.addLayout(fila(
            self.b_masivo, boton("Historial de precios", self.historial), None, self.b_importar, boton("Exportar CSV", self.exportar),
        ))
        self.tabla = Tabla(["Código", "Producto", "Categoría", "Precio Costo", "Impuestos",
                            "Ganancia", "Precio de venta final", "Disponible", "Estado"])
        self.tabla.activada.connect(self.editar)
        # Filas más altas para que se vea la foto de cada producto.
        self.tabla.setIconSize(QSize(44, 44))
        self.tabla.verticalHeader().setDefaultSectionSize(52)
        self.miniaturas = imagenes.Miniaturas(self.ctx, 44)
        self.cuerpo.addWidget(self.tabla, 1)
        self.pie = etiqueta("", "suave")
        self.cuerpo.addWidget(self.pie)

    def refrescar(self) -> None:
        actual = self.categoria.currentData()
        self.categoria.blockSignals(True)
        self.categoria.clear()
        self.categoria.addItem("Todas las categorías", None)
        for c in self.ctx.productos.categorias():
            self.categoria.addItem(c["nombre"], c["id"])
        self.categoria.setCurrentIndex(max(0, self.categoria.findData(actual)))
        self.categoria.blockSignals(False)
        puede = self.ctx.puede("productos_editar")
        for b in self.solo_edicion:
            b.setVisible(puede)
        self.miniaturas.olvidar()  # pudo cambiar alguna imagen
        self.cargar()

    def cargar(self) -> None:
        productos = self.ctx.productos.buscar(self.buscador.text(), self.categoria.currentData(),
                                               solo_activos=not self.inactivos.isChecked())
        filas, colores = [], {}
        for n, p in enumerate(productos):
            filas.append([
                p["codigo"], p["nombre"], p["categoria"], cd(p["costo_cent"]),
                fmt_pct(D(p["impuesto_pct"])) + " %", fmt_pct(D(p["ganancia_pct"])) + " %",
                cd(p["precio_final_cent"]), cq(p["stock_mil"]), "Activo" if p["activo"] else "Inactivo",
            ])
            if not p["activo"]:
                colores[n] = "#9CA3AF"
        fotos = self.miniaturas.de(productos)
        iconos = {n: fotos[p["id"]] for n, p in enumerate(productos) if p["id"] in fotos}
        self.tabla.cargar(filas, [p["id"] for p in productos], colores, iconos)
        self.pie.setText(f"{len(productos)} productos  ·  {len(iconos)} con imagen")

    def nuevo(self) -> None:
        if DialogoProducto(self, self.ctx).exec():
            self.refrescar()

    def editar(self) -> None:
        if not self.ctx.puede("productos_editar"):
            return
        if DialogoProducto(self, self.ctx, self.tabla.id_requerido("Seleccioná un producto de la lista.")).exec():
            self.refrescar()

    def duplicar(self) -> None:
        datos = self.ctx.productos.datos_para_duplicar(self.tabla.id_requerido("Seleccioná el producto que querés duplicar."))
        if DialogoProducto(self, self.ctx, datos=datos).exec():
            self.refrescar()

    def cambiar_estado(self) -> None:
        p = self.ctx.productos.obtener(self.tabla.id_requerido("Seleccioná un producto de la lista."))
        if p["activo"]:
            if not confirmar(self, f"¿Desactivar «{p['nombre']}»?\n\nDeja de ofrecerse en las ventas, pero su historial "
                                   "de ventas y movimientos se conserva. Podés volver a activarlo cuando quieras.", "Desactivar"):
                return
            self.inactivos.setChecked(True)
        self.ctx.productos.cambiar_estado(p["id"], not p["activo"])
        self.refrescar()

    def completar_imagenes(self) -> None:
        catalogo = self.ctx.productos.estado_catalogo()
        if not catalogo["imagenes"] and not self.ctx.config.booleano("catalogo_en_linea"):
            raise ErrorNegocio("Todavía no hay un catálogo de imágenes. Elegí la carpeta donde están las imágenes en "
                               "Configuración → Ventas y precios (en la computadora principal).")
        pendientes = self.ctx.productos.sin_imagen()
        if not pendientes:
            informar(self, "Todos los productos con código de barras ya tienen imagen.")
            return
        if not confirmar(self, f"Hay {len(pendientes)} productos con código de barras y sin imagen.\n\nSe va a buscar la imagen "
                               "de cada uno en el catálogo de imágenes.", "Buscar imágenes"):
            return
        progreso = QProgressDialog("Buscando imágenes en el catálogo…", "Detener", 0, len(pendientes), self)
        progreso.setWindowTitle("Imágenes de productos")
        progreso.setWindowModality(Qt.WindowModal)
        progreso.setMinimumDuration(0)
        encontradas, problema = 0, ""
        for n, producto in enumerate(pendientes):
            progreso.setValue(n)
            QApplication.processEvents()
            if progreso.wasCanceled():
                break
            try:
                datos = buscar_imagen(self.ctx, producto["codigo_barras"])
                if datos:
                    lista = imagenes.normalizar(datos)
                    self.ctx.productos.guardar_imagen(producto["id"], lista, "catalogo", imagenes.miniatura(lista))
                    encontradas += 1
            except catalogo_imagenes.SinConexion as e:
                problema = str(e)
                break
            except ErrorNegocio:
                continue  # esa imagen no sirve: se sigue con las demás
        progreso.setValue(len(pendientes))
        self.refrescar()
        texto = f"Se cargaron {encontradas} imágenes. Los demás productos no figuran en el catálogo: se les puede poner una imagen a mano."
        if problema:
            advertir(self, f"{problema}\n\nHasta ese momento se cargaron {encontradas} imágenes.", "Imágenes de productos")
        else:
            informar(self, texto, "Imágenes de productos")

    def masivo(self) -> None:
        DialogoCambioMasivo(self, self.ctx).exec()
        self.refrescar()

    def historial(self) -> None:
        DialogoHistorialPrecios(self, self.ctx, self.tabla.id_actual()).exec()

    def exportar(self) -> None:
        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar productos", "productos.csv", "CSV para Excel (*.csv)")
        if ruta:
            cantidad = csv_io.exportar_productos(self.ctx, ruta)
            informar(self, f"Se exportaron {cantidad} productos a:\n{ruta}")

    def importar(self) -> None:
        if not confirmar(
            self, "Vas a importar productos desde un archivo CSV.\n\nLos productos que ya existen (mismo código interno "
                  "o código de barras) se actualizan, y los demás se crean. El archivo debe tener las mismas columnas "
                  "que «Exportar CSV»: lo más fácil es exportar primero y usar ese archivo como modelo.", "Elegir archivo"):
            return
        ruta, _ = QFileDialog.getOpenFileName(self, "Importar productos", "", "CSV (*.csv *.txt)")
        if not ruta:
            return
        r = csv_io.importar_productos(self.ctx, ruta)
        texto = f"Productos creados: {r['creados']}\nProductos actualizados: {r['actualizados']}"
        if r["errores"]:
            texto += f"\n\nFilas con errores (no se importaron): {len(r['errores'])}\n" + "\n".join(r["errores"][:15])
            if len(r["errores"]) > 15:
                texto += "\n…"
            advertir(self, texto, "Importación terminada con errores")
        else:
            informar(self, texto, "Importación terminada")
        self.refrescar()
