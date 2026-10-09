from __future__ import annotations

import uuid
from decimal import Decimal

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QDialog, QGridLayout, QLineEdit, QListWidget, QListWidgetItem, QRadioButton, QVBoxLayout,
)

from ...core.dinero import D, a_centavos, a_milesimas, de_centavos, fmt_cantidad, fmt_dinero, fmt_pct, parse_decimal
from ...core.errores import ErrorNegocio
from ...integraciones import arca
from ...servicios import tickets
from ...servicios.caja import MEDIOS
from ...servicios.ventas import calcular_totales
from .. import tema
from ..comunes import (
    Buscador, CampoDecimal, Dialogo, Pagina, Tabla, boton, cd, confirmar, etiqueta, fila, panel,
)
from ..impresion import imprimir_directo, mostrar_comprobante
from .facturacion import con_espera, mostrar_factura


class DialogoCobro(Dialogo):
    """Confirma el cobro según el medio de pago. Devuelve el pago en .pago"""

    def __init__(self, padre, medio: str, total_cent: int):
        super().__init__(padre, f"Cobrar con {MEDIOS[medio].lower()}", "Confirmar venta", 440)
        self.medio, self.total_cent, self.pago, self.vuelto_cent = medio, total_cent, None, 0
        total = etiqueta(fmt_dinero(total_cent), "total")
        total.setAlignment(Qt.AlignCenter)
        self.cuerpo.insertWidget(0, total)
        self.cuerpo.insertWidget(0, etiqueta("Total a cobrar", "suave"))
        self.recibido = self.referencia = self.comision = self.verificado = None

        if medio == "efectivo":
            self.recibido = CampoDecimal("Paga con", dinero=True)
            self.recibido.poner(de_centavos(total_cent))
            self.vuelto = etiqueta("$ 0,00", "grande")
            self.formulario.addRow("Paga con ($):", self.recibido)
            self.formulario.addRow("Vuelto:", self.vuelto)
            self.recibido.textEdited.connect(lambda _: self.actualizar_vuelto())
        elif medio == "tarjeta":
            self.cuerpo.insertWidget(2, etiqueta(
                "Pasá la tarjeta por la terminal y confirmá la venta solo cuando el pago esté aprobado.", "nota", True))
            self.referencia = QLineEdit()
            self.referencia.setPlaceholderText("Opcional")
            self.formulario.addRow("N° de cupón:", self.referencia)
        else:
            self.cuerpo.insertWidget(2, etiqueta(
                "Verificá en tu cuenta que el dinero haya ingresado. Una captura de pantalla que muestre el "
                "cliente no alcanza para dar el pago por cobrado.", "aviso", True))
            self.verificado = QRadioButton("Ya verifiqué en mi cuenta que el dinero ingresó")
            self.pendiente = QRadioButton("Todavía no lo verifiqué: dejar el pago como pendiente")
            self.pendiente.setChecked(True)
            grupo = QButtonGroup(self)
            grupo.addButton(self.verificado)
            grupo.addButton(self.pendiente)
            self.cuerpo.insertWidget(3, self.verificado)
            self.cuerpo.insertWidget(4, self.pendiente)
            self.referencia = QLineEdit()
            self.referencia.setPlaceholderText("Opcional")
            self.formulario.addRow("N° de operación:", self.referencia)
            if medio == "mercadopago":
                self.comision = CampoDecimal("Comisión", dinero=True, opcional=True)
                self.comision.setPlaceholderText("Opcional")
                self.formulario.addRow("Comisión de Mercado Pago ($):", self.comision)
        self.terminar()
        if self.recibido:
            self.recibido.setFocus()
            self.recibido.selectAll()

    def actualizar_vuelto(self) -> None:
        recibido = self.recibido.valor_o()
        if recibido is None or a_centavos(recibido) < self.total_cent:
            self.vuelto.setText("Falta dinero")
            self.vuelto.setStyleSheet(f"color: {tema.ROJO};")
        else:
            self.vuelto.setText(fmt_dinero(a_centavos(recibido) - self.total_cent))
            self.vuelto.setStyleSheet(f"color: {tema.VERDE};")

    def guardar(self) -> None:
        pago = {"medio": self.medio, "monto_cent": self.total_cent, "estado": "confirmado"}
        if self.recibido:
            recibido = a_centavos(self.recibido.valor())
            if recibido < self.total_cent:
                raise ErrorNegocio("El importe recibido es menor al total de la venta.")
            self.vuelto_cent = recibido - self.total_cent
        if self.referencia:
            pago["referencia"] = self.referencia.text()
        if self.verificado is not None and not self.verificado.isChecked():
            pago["estado"] = "pendiente"
        if self.comision and self.comision.valor() is not None:
            pago["comision_cent"] = a_centavos(self.comision.valor())
        self.pago = pago
        self.accept()


class DialogoDescuento(Dialogo):
    def __init__(self, padre, bruto_cent: int, maximo_pct: Decimal, actual: tuple[str, Decimal] | None):
        super().__init__(padre, "Descuento", "Aplicar", 400)
        self.descuento: tuple[str, Decimal] | None = None
        self.bruto_cent = bruto_cent
        if maximo_pct < 100:
            self.cuerpo.insertWidget(0, etiqueta(
                f"Tu usuario puede aplicar descuentos de hasta {fmt_pct(maximo_pct)} %.", "nota", True))
        self.tipo = QComboBox()
        self.tipo.addItem("Porcentaje (%)", "pct")
        self.tipo.addItem("Importe ($)", "importe")
        self.valor = CampoDecimal("Descuento")
        if actual:
            self.tipo.setCurrentIndex(self.tipo.findData(actual[0]))
            self.valor.poner(actual[1])
        self.formulario.addRow("Tipo de descuento:", self.tipo)
        self.formulario.addRow("Descuento:", self.valor)
        self.terminar()
        self.botones.addButton(boton("Quitar descuento", self.quitar), self.botones.ButtonRole.ResetRole)
        self.valor.setFocus()

    def quitar(self) -> None:
        self.descuento = None
        self.accept()

    def guardar(self) -> None:
        valor = self.valor.valor()
        if valor == 0:
            return self.quitar()
        if self.tipo.currentData() == "pct" and valor > 100:
            raise ErrorNegocio("El descuento no puede ser mayor al 100 %.")
        self.descuento = (self.tipo.currentData(), valor)
        self.accept()


class DialogoVentaRegistrada(QDialog):
    def __init__(self, padre, ctx, venta_id: int, vuelto_cent: int, pendiente: bool, factura=None, error_fiscal: str = ""):
        super().__init__(padre)
        self.ctx, self.venta_id = ctx, venta_id
        self.servicio, self.factura = arca.crear_servicio(ctx), factura
        self.setWindowTitle("Venta registrada")
        self.setMinimumWidth(400)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 18)
        v.setSpacing(10)
        venta = ctx.ventas.obtener(venta_id)
        v.addWidget(etiqueta(f"Venta N° {venta_id} registrada", "subtitulo"))
        v.addWidget(etiqueta(f"Total: {fmt_dinero(venta['total_cent'])}", "grande"))
        if vuelto_cent:
            vuelto = etiqueta(f"Vuelto: {fmt_dinero(vuelto_cent)}", "total")
            v.addWidget(vuelto)
        if pendiente:
            v.addWidget(etiqueta("El pago quedó PENDIENTE: no se cuenta como cobrado. Cuando verifiques que el dinero "
                                 "ingresó, confirmalo desde «Historial de ventas».", "aviso", True))
        self.l_fiscal = etiqueta("", "nota", True)
        v.addWidget(self.l_fiscal)
        self.b_factura = boton("Emitir factura", self.facturar)
        seguir = boton("Nueva venta  (Enter)", self.accept, "primario")
        seguir.setDefault(True)
        seguir.setAutoDefault(True)
        v.addLayout(fila(boton("Imprimir ticket", self.imprimir), self.b_factura, None, seguir))
        self.mostrar_fiscal(error_fiscal)
        seguir.setFocus()

    def mostrar_fiscal(self, error: str = "") -> None:
        disponible = self.servicio.estado().disponible
        self.b_factura.setVisible(disponible or self.factura is not None)
        if self.factura is not None:
            c = self.factura
            prueba = "  (PRUEBA, sin validez fiscal)" if c["entorno"] != "produccion" else ""
            self.l_fiscal.setText(f"Factura {c['letra']} {int(c['punto_venta']):05d}-{int(c['numero']):08d} autorizada por ARCA. "
                                  f"CAE {c['cae']}{prueba}")
            self.b_factura.setText("Imprimir factura")
        elif error:
            self.l_fiscal.setText("No se emitió la factura: " + error)
        self.l_fiscal.setVisible(self.factura is not None or bool(error))

    def facturar(self) -> None:
        if self.factura is None:
            try:
                self.factura = con_espera(lambda: self.servicio.autorizar_venta(self.venta_id))
            except ErrorNegocio as e:
                self.mostrar_fiscal(str(e))
                return
            self.mostrar_fiscal()
        mostrar_factura(self, self.ctx, self.factura)

    def imprimir(self) -> None:
        mostrar_comprobante(self, self.ctx, tickets.html_ticket(self.ctx, self.venta_id), f"Ticket venta {self.venta_id}")


class PaginaVenta(Pagina):
    titulo = "Nueva venta"

    def armar(self) -> None:
        self.carrito: list[dict] = []
        self.descuento: tuple[str, Decimal] | None = None
        self.uuid = str(uuid.uuid4())
        self.cobrando = False

        self.aviso_caja = etiqueta("La caja está cerrada. Abrila para poder vender.", "aviso")
        self.boton_abrir = boton("Ir a Caja diaria", lambda: self.ventana.ir("caja"))
        self.barra_caja = fila(self.aviso_caja, self.boton_abrir, None)
        self.cuerpo.addLayout(self.barra_caja)

        # --- izquierda: búsqueda y carrito ---
        self.buscador = Buscador("Escaneá el código de barras o escribí el nombre del producto…", 180)
        self.buscador.setObjectName("buscador")
        self.buscador.setToolTip("Para cargar varias unidades escribí la cantidad, un asterisco y el código: 3*7791234567890")
        self.buscador.buscar.connect(self.sugerir)
        self.buscador.returnPressed.connect(self.enter)
        self.buscador.installEventFilter(self)
        self.sugerencias = QListWidget()
        self.sugerencias.setMaximumHeight(190)
        self.sugerencias.hide()
        self.sugerencias.itemActivated.connect(self.elegir_sugerencia)
        self.sugerencias.itemClicked.connect(self.elegir_sugerencia)
        self.mensaje = etiqueta("", "suave")

        self.tabla = Tabla(["Código", "Producto", "Cantidad", "Precio", "Importe"], ordenable=False)
        self.tabla.activada.connect(self.cambiar_cantidad)
        self.tabla.installEventFilter(self)
        izquierda = QVBoxLayout()
        izquierda.setSpacing(8)
        izquierda.addWidget(self.buscador)
        izquierda.addWidget(self.sugerencias)
        izquierda.addWidget(self.mensaje)
        izquierda.addWidget(self.tabla, 1)
        izquierda.addLayout(fila(
            boton("+ 1", lambda: self.sumar(1), ayuda="Tecla +"), boton("− 1", lambda: self.sumar(-1), ayuda="Tecla −"),
            boton("Cambiar cantidad", self.cambiar_cantidad), boton("Quitar producto", self.quitar, "peligro", ayuda="Tecla Supr"),
            None, boton("Vaciar venta", self.vaciar, "peligro"),
        ))

        # --- derecha: totales y cobro ---
        derecha, vd = panel()
        derecha.setFixedWidth(350)
        self.cliente = QComboBox()
        vd.addWidget(etiqueta("Cliente", "suave"))
        vd.addWidget(self.cliente)
        vd.addSpacing(6)
        rejilla = QGridLayout()
        rejilla.setVerticalSpacing(6)
        self.l_subtotal, self.l_impuestos, self.l_descuento = etiqueta("$ 0,00"), etiqueta("$ 0,00"), etiqueta("$ 0,00")
        for n, (nombre, valor) in enumerate([("Subtotal sin impuestos", self.l_subtotal), ("Impuestos", self.l_impuestos),
                                              ("Descuento", self.l_descuento)]):
            rejilla.addWidget(etiqueta(nombre, "suave"), n, 0)
            valor.setAlignment(Qt.AlignRight)
            rejilla.addWidget(valor, n, 1)
        vd.addLayout(rejilla)
        vd.addWidget(boton("Aplicar descuento", self.pedir_descuento))
        vd.addSpacing(4)
        vd.addWidget(etiqueta("TOTAL", "suave"))
        self.l_total = etiqueta("$ 0,00", "total")
        self.l_total.setAlignment(Qt.AlignRight)
        vd.addWidget(self.l_total)
        vd.addStretch(1)
        vd.addWidget(etiqueta("Cobrar con", "suave"))
        cobros = QGridLayout()
        cobros.setSpacing(8)
        self.botones_cobro = []
        for n, (medio, tecla) in enumerate([("efectivo", "F5"), ("tarjeta", "F6"), ("transferencia", "F7"), ("mercadopago", "F8")]):
            b = boton(f"{MEDIOS[medio]}\n{tecla}", lambda m=medio: self.cobrar(m), "cobro")
            b.setMinimumHeight(64)
            cobros.addWidget(b, n // 2, n % 2)
            self.botones_cobro.append(b)
            atajo = QShortcut(QKeySequence(tecla), self)
            atajo.activated.connect(lambda m=medio: self.cobrar(m))
        vd.addLayout(cobros)

        self.cuerpo.addLayout(fila(izquierda, derecha, espacio=16), 1)

    # ---- eventos de teclado ---------------------------------------------
    def eventFilter(self, objeto, evento):
        if evento.type() == QEvent.KeyPress:
            tecla = evento.key()
            if objeto is self.buscador and tecla == Qt.Key_Down and self.sugerencias.isVisible():
                self.sugerencias.setFocus()
                self.sugerencias.setCurrentRow(0)
                return True
            if objeto is self.tabla:
                if tecla == Qt.Key_Delete:
                    self.quitar()
                    return True
                if tecla in (Qt.Key_Plus, Qt.Key_Minus):
                    self.sumar(1 if tecla == Qt.Key_Plus else -1)
                    return True
        return super().eventFilter(objeto, evento)

    def enfocar(self) -> None:
        self.buscador.setFocus()

    # ---- búsqueda --------------------------------------------------------
    def _separar_cantidad(self, texto: str) -> tuple[Decimal, str]:
        """'3*779...' -> (3, '779...')"""
        if "*" in texto:
            cantidad, _, resto = texto.partition("*")
            try:
                valor = parse_decimal(cantidad)
                if valor > 0:
                    return valor, resto.strip()
            except ValueError:
                pass
        return Decimal(1), texto

    def enter(self) -> None:
        """Enter (o el lector de códigos): agrega el producto si el código coincide exactamente."""
        self.buscador.reloj.stop()
        cantidad, texto = self._separar_cantidad(self.buscador.text().strip())
        if not texto:
            return
        producto = self.ctx.productos.por_codigo(texto)
        if producto is None:
            encontrados = self.ctx.productos.buscar(texto, limite=30)
            if len(encontrados) == 1:
                producto = encontrados[0]
            elif encontrados:
                self.mostrar_sugerencias(encontrados)
                self.sugerencias.setFocus()
                self.sugerencias.setCurrentRow(0)
                return
            else:
                self.sugerencias.hide()
                self.avisar(f"No se encontró ningún producto con «{texto}».", error=True)
                self.buscador.selectAll()
                return
        self.agregar(producto, cantidad)

    def sugerir(self) -> None:
        _, texto = self._separar_cantidad(self.buscador.text().strip())
        if len(texto) < 2:
            self.sugerencias.hide()
            return
        self.mostrar_sugerencias(self.ctx.productos.buscar(texto, limite=30))

    def mostrar_sugerencias(self, productos) -> None:
        self.sugerencias.clear()
        for p in productos:
            item = QListWidgetItem(
                f"{p['nombre']}   ·   {fmt_dinero(p['precio_final_cent'])}   ·   disponible: {fmt_cantidad(p['stock_mil'])} {p['unidad']}"
            )
            item.setData(Qt.UserRole, p["id"])
            self.sugerencias.addItem(item)
        self.sugerencias.setVisible(bool(productos))

    def elegir_sugerencia(self, item) -> None:
        cantidad, _ = self._separar_cantidad(self.buscador.text().strip())
        self.agregar(self.ctx.productos.obtener(item.data(Qt.UserRole)), cantidad)

    def avisar(self, texto: str, error: bool = False) -> None:
        self.mensaje.setText(texto)
        self.mensaje.setStyleSheet(f"color: {tema.ROJO if error else tema.TEXTO_SUAVE};")

    # ---- carrito ---------------------------------------------------------
    def _verificar_stock(self, producto, cantidad: Decimal) -> None:
        if a_milesimas(cantidad) > producto["stock_mil"] and not self.ctx.inventario.permite_negativo():
            raise ErrorNegocio(
                f"No hay stock suficiente de «{producto['nombre']}»: hay {fmt_cantidad(producto['stock_mil'])} disponibles."
            )

    def agregar(self, producto, cantidad: Decimal = Decimal(1)) -> None:
        self.sugerencias.hide()
        self.buscador.clear()
        self.buscador.reloj.stop()
        self.buscador.setFocus()
        try:
            for linea in self.carrito:
                if linea["producto_id"] == producto["id"]:
                    self._verificar_stock(producto, linea["cantidad"] + cantidad)
                    linea["cantidad"] += cantidad
                    break
            else:
                self._verificar_stock(producto, cantidad)
                self.carrito.append({
                    "producto_id": producto["id"], "codigo": producto["codigo"], "nombre": producto["nombre"],
                    "unidad": producto["unidad"], "cantidad": cantidad, "precio_unit_cent": producto["precio_final_cent"],
                    "impuesto_pct": producto["impuesto_pct"],
                })
                linea = self.carrito[-1]
        except ErrorNegocio as e:
            self.avisar(str(e), error=True)
            return
        self.avisar(f"Agregado: {producto['nombre']}  ×  {fmt_cantidad(a_milesimas(linea['cantidad']))}")
        self.mostrar(self.carrito.index(linea))

    def _linea_actual(self) -> dict:
        n = self.tabla.currentRow()
        if not self.carrito:
            raise ErrorNegocio("Todavía no hay productos en la venta.")
        if n < 0 or n >= len(self.carrito):
            n = len(self.carrito) - 1
        return self.carrito[n]

    def _poner_cantidad(self, linea: dict, cantidad: Decimal) -> None:
        if cantidad <= 0:
            self.carrito.remove(linea)
            self.mostrar()
            return
        self._verificar_stock(self.ctx.productos.obtener(linea["producto_id"]), cantidad)
        linea["cantidad"] = cantidad
        self.mostrar(self.carrito.index(linea))

    def sumar(self, delta: int) -> None:
        linea = self._linea_actual()
        self._poner_cantidad(linea, linea["cantidad"] + delta)

    def cambiar_cantidad(self) -> None:
        linea = self._linea_actual()
        dialogo = Dialogo(self, "Cambiar cantidad", "Aceptar", 360)
        campo = CampoDecimal("Cantidad", 3)
        campo.poner(linea["cantidad"])
        dialogo.formulario.addRow(f"Cantidad de «{linea['nombre']}» ({linea['unidad']}):", campo)
        dialogo.terminar()
        campo.setFocus()
        campo.selectAll()
        if dialogo.exec():
            self._poner_cantidad(linea, campo.valor())
        self.enfocar()

    def quitar(self) -> None:
        self.carrito.remove(self._linea_actual())
        self.mostrar()
        self.enfocar()

    def vaciar(self) -> None:
        if self.carrito and not confirmar(self, "¿Vaciar la venta actual? Se quitan todos los productos.", "Vaciar"):
            return
        self.reiniciar()

    def reiniciar(self) -> None:
        self.carrito, self.descuento = [], None
        self.uuid = str(uuid.uuid4())
        self.cobrando = False
        self.cliente.setCurrentIndex(0)
        self.avisar("")
        self.mostrar()
        self.enfocar()

    # ---- totales ---------------------------------------------------------
    def totales(self) -> dict:
        lineas = [{"cantidad_mil": a_milesimas(l["cantidad"]), "precio_unit_cent": l["precio_unit_cent"],
                   "impuesto_pct": l["impuesto_pct"]} for l in self.carrito]
        bruto = calcular_totales(lineas)["bruto_cent"]
        descuento = 0
        if self.descuento:
            tipo, valor = self.descuento
            descuento = a_centavos(de_centavos(bruto) * valor / 100) if tipo == "pct" else a_centavos(valor)
            descuento = min(descuento, bruto)
        return calcular_totales(lineas, descuento)

    def mostrar(self, seleccionar: int | None = None) -> None:
        t = self.totales()
        self.tabla.cargar([[l["codigo"], l["nombre"], (f"{fmt_cantidad(a_milesimas(l['cantidad']))} {l['unidad']}", 0),
                            cd(l["precio_unit_cent"]), cd(tl["bruto_cent"])]
                           for l, tl in zip(self.carrito, t["lineas"])])
        if seleccionar is not None and self.carrito:
            self.tabla.selectRow(seleccionar)
            self.tabla.scrollToItem(self.tabla.item(seleccionar, 0))
        self.l_subtotal.setText(fmt_dinero(t["neto_cent"]))
        self.l_impuestos.setText(fmt_dinero(t["impuestos_cent"]))
        self.l_descuento.setText(("- " if t["descuento_cent"] else "") + fmt_dinero(t["descuento_cent"]))
        self.l_total.setText(fmt_dinero(t["total_cent"]))
        self.actualizar_botones()

    def actualizar_botones(self) -> None:
        habilitado = bool(self.carrito) and self.ctx.caja.abierta() is not None and not self.cobrando
        for b in self.botones_cobro:
            b.setEnabled(habilitado)

    def pedir_descuento(self) -> None:
        if not self.carrito:
            raise ErrorNegocio("Agregá productos antes de aplicar un descuento.")
        maximo = self.ctx.ventas.descuento_maximo_pct()
        dialogo = DialogoDescuento(self, self.totales()["bruto_cent"], maximo, self.descuento)
        if dialogo.exec():
            anterior, self.descuento = self.descuento, dialogo.descuento
            t = self.totales()
            if t["bruto_cent"] and D(t["descuento_cent"]) * 100 / t["bruto_cent"] > maximo:
                self.descuento = anterior
                raise ErrorNegocio(f"Tu usuario puede aplicar descuentos de hasta {fmt_pct(maximo)} %. "
                                   "Un descuento mayor debe hacerlo un administrador.")
            self.mostrar()
        self.enfocar()

    # ---- cobro -----------------------------------------------------------
    def cobrar(self, medio: str) -> None:
        # Evita registrar dos veces la venta por pulsaciones repetidas: mientras se
        # cobra se ignoran nuevos pedidos, y el uuid hace que la base no la duplique.
        if self.cobrando or not self.carrito or not self.isVisible():
            return
        self.ctx.caja.requerir_abierta()
        t = self.totales()
        self.cobrando = True
        self.actualizar_botones()
        try:
            pagos, vuelto, pendiente = [], 0, False
            if t["total_cent"] > 0:
                dialogo = DialogoCobro(self, medio, t["total_cent"])
                if not dialogo.exec():
                    return
                pagos, vuelto, pendiente = [dialogo.pago], dialogo.vuelto_cent, dialogo.pago["estado"] == "pendiente"
            venta_id = self.ctx.ventas.registrar(
                self.uuid,
                [{"producto_id": l["producto_id"], "cantidad": l["cantidad"], "precio_unit_cent": l["precio_unit_cent"]}
                 for l in self.carrito],
                pagos, t["descuento_cent"], self.cliente.currentData(),
            )
        finally:
            self.cobrando = False
            self.actualizar_botones()
        self.reiniciar()
        self.ventana.actualizar_estado()
        if self.ctx.config.booleano("ticket_imprimir_automatico"):
            try:
                imprimir_directo(self.ctx, tickets.html_ticket(self.ctx, venta_id))
            except Exception:
                self.avisar("La venta se registró, pero no se pudo imprimir el ticket.", error=True)
        # La venta ya está guardada: la factura se pide aparte y, si ARCA no responde, queda pendiente.
        factura, error_fiscal = None, ""
        if self.ctx.config.booleano("fiscal_automatico"):
            servicio = arca.crear_servicio(self.ctx)
            if servicio.estado().disponible:
                try:
                    factura = con_espera(lambda: servicio.autorizar_venta(venta_id))
                except ErrorNegocio as e:
                    error_fiscal = str(e)
        DialogoVentaRegistrada(self, self.ctx, venta_id, vuelto, pendiente, factura, error_fiscal).exec()
        self.enfocar()

    def refrescar(self) -> None:
        abierta = self.ctx.caja.abierta() is not None
        self.aviso_caja.setVisible(not abierta)
        self.boton_abrir.setVisible(not abierta)
        actual = self.cliente.currentData()
        self.cliente.clear()
        self.cliente.addItem("Consumidor final (sin registrar)", None)
        for c in self.ctx.clientes.buscar():
            self.cliente.addItem(c["nombre"] + (f" · {c['documento']}" if c["documento"] else ""), c["id"])
        self.cliente.setCurrentIndex(max(0, self.cliente.findData(actual)))
        self.mostrar()
        self.enfocar()
