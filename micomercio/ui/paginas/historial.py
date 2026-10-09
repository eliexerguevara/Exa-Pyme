from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QDialog, QLineEdit, QVBoxLayout

from ...core.dinero import a_centavos, de_centavos, fmt_cantidad, fmt_dinero
from ...core.errores import ErrorNegocio
from ...servicios import tickets
from ...servicios.caja import MEDIOS
from ...servicios.ventas import ESTADOS_PAGO, MEDIOS_CON_PENDIENTE, estado_pago
from .. import tema
from ..comunes import (
    Buscador, CampoDecimal, Dialogo, DialogoImporte, Pagina, SelectorPeriodo, Tabla, boton, cd, cf, confirmar,
    etiqueta, fila,
)
from ..impresion import mostrar_comprobante

ESTADOS_DE_PAGO = {"pendiente": "Pendiente", "confirmado": "Confirmado", "rechazado": "Rechazado", "cancelado": "Cancelado"}
ESTADOS_FISCALES = {"sin_comprobante": "Sin comprobante fiscal", "pendiente": "Pendiente de autorización",
                    "autorizada": "Autorizada", "rechazada": "Rechazada"}
COLORES = {"pendiente": tema.NARANJA, "impaga": tema.ROJO, "anulada": "#9CA3AF"}


class DialogoConfirmarPago(Dialogo):
    def __init__(self, padre, pago):
        super().__init__(padre, "Confirmar cobro", "Confirmar cobro", 440)
        self.cuerpo.insertWidget(0, etiqueta(
            f"{MEDIOS[pago['medio']]} por {fmt_dinero(pago['monto_cent'])}", "subtitulo"))
        self.cuerpo.insertWidget(1, etiqueta(
            "Confirmá solo si ya verificaste en tu cuenta que el dinero ingresó. Una captura de pantalla del "
            "cliente no alcanza.", "aviso", True))
        self.referencia = QLineEdit(pago["referencia"])
        self.formulario.addRow("N° de operación:", self.referencia)
        self.comision = None
        if pago["medio"] == "mercadopago":
            self.comision = CampoDecimal("Comisión", dinero=True, opcional=True)
            self.formulario.addRow("Comisión de Mercado Pago ($):", self.comision)
        self.terminar()

    def comision_cent(self) -> int:
        return a_centavos(self.comision.valor() or 0) if self.comision else 0

    def guardar(self) -> None:
        self.comision_cent()
        self.accept()


class DialogoNuevoCobro(Dialogo):
    def __init__(self, padre, saldo_cent: int):
        super().__init__(padre, "Registrar cobro", "Registrar", 420)
        self.cuerpo.insertWidget(0, etiqueta(f"Falta cobrar: {fmt_dinero(saldo_cent)}", "subtitulo"))
        self.medio = QComboBox()
        for clave, nombre in MEDIOS.items():
            self.medio.addItem(nombre, clave)
        self.importe = CampoDecimal("Importe", dinero=True)
        self.importe.poner(de_centavos(saldo_cent))
        self.estado = QComboBox()
        self.estado.addItem("Cobrado y verificado", "confirmado")
        self.estado.addItem("Pendiente de verificar", "pendiente")
        self.referencia = QLineEdit()
        self.formulario.addRow("Medio de pago:", self.medio)
        self.formulario.addRow("Importe ($):", self.importe)
        self.formulario.addRow("Estado:", self.estado)
        self.formulario.addRow("N° de operación:", self.referencia)
        self.terminar()

    def pago(self) -> dict:
        return {"medio": self.medio.currentData(), "monto_cent": a_centavos(self.importe.valor()),
                "estado": self.estado.currentData(), "referencia": self.referencia.text()}

    def guardar(self) -> None:
        pago = self.pago()
        if pago["estado"] == "pendiente" and pago["medio"] not in MEDIOS_CON_PENDIENTE:
            raise ErrorNegocio("Solo las transferencias y los cobros con Mercado Pago pueden quedar pendientes.")
        self.accept()


class DialogoVenta(QDialog):
    """Detalle de una venta: productos, pagos y acciones sobre los pagos."""

    def __init__(self, padre, ctx, venta_id: int):
        super().__init__(padre)
        self.ctx, self.venta_id = ctx, venta_id
        self.setWindowTitle(f"Venta N° {venta_id}")
        self.resize(900, 640)
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 16)
        v.setSpacing(8)
        self.cabecera = etiqueta("", "subtitulo")
        self.datos = etiqueta("", "suave", True)
        v.addWidget(self.cabecera)
        v.addWidget(self.datos)
        self.items = Tabla(["Código", "Producto", "Cantidad", "Precio", "Descuento", "Importe"], ordenable=False)
        v.addWidget(self.items, 3)
        v.addWidget(etiqueta("Pagos", "subtitulo"))
        self.pagos = Tabla(["Medio", "Tipo", "Importe", "Estado", "Comisión", "N° de operación", "Fecha de cobro"],
                           estirar=5, ordenable=False)
        v.addWidget(self.pagos, 2)
        self.b_confirmar = boton("Confirmar cobro pendiente", self.confirmar_pago, "primario")
        self.b_rechazar = boton("Marcar rechazado", lambda: self.descartar("rechazado"))
        self.b_cancelar = boton("Marcar cancelado", lambda: self.descartar("cancelado"))
        self.b_comision = boton("Cargar comisión de Mercado Pago", self.comision)
        self.b_cobro = boton("Registrar cobro", self.nuevo_cobro)
        v.addLayout(fila(self.b_confirmar, self.b_rechazar, self.b_cancelar, self.b_comision, self.b_cobro, None))
        self.b_anular = boton("Anular venta", self.anular, "peligro")
        v.addLayout(fila(self.b_anular, None, boton("Ver / imprimir ticket", self.ticket), boton("Cerrar", self.accept)))
        self.pagos.itemSelectionChanged.connect(self.actualizar_botones)
        self.cargar()

    def cargar(self) -> None:
        ctx = self.ctx
        v = ctx.ventas.obtener(self.venta_id)
        self.venta = v
        estado = estado_pago(v)
        self.cabecera.setText(f"Venta N° {v['id']}  ·  {fmt_dinero(v['total_cent'])}  ·  {ESTADOS_PAGO[estado]}")
        texto = (f"{cf(v['fecha'])[0]}  ·  Cliente: {v['cliente']}  ·  Atendió: {v['usuario']}\n"
                 f"Subtotal sin impuestos {fmt_dinero(v['neto_cent'])}  ·  Impuestos {fmt_dinero(v['impuestos_cent'])}  ·  "
                 f"Descuento {fmt_dinero(v['descuento_cent'])}  ·  {ESTADOS_FISCALES.get(v['estado_fiscal'], '')}")
        if v["estado"] == "anulada":
            texto += f"\nAnulada el {cf(v['anulada_en'])[0]}. Motivo: {v['motivo_anulacion']}"
        self.datos.setText(texto)
        self.items.cargar([[i["codigo"], i["nombre"], (f"{fmt_cantidad(i['cantidad_mil'])} {i['unidad']}", 0),
                            cd(i["precio_unit_cent"]), cd(i["descuento_cent"]), cd(i["total_cent"])]
                           for i in ctx.ventas.items(self.venta_id)])
        self.lista_pagos = ctx.ventas.pagos(self.venta_id)
        self.pagos.cargar([[MEDIOS[p["medio"]], "Cobro" if p["tipo"] == "cobro" else "Devolución", cd(p["monto_cent"]),
                            ESTADOS_DE_PAGO[p["estado"]], cd(p["comision_cent"]) if p["comision_cent"] else "",
                            p["referencia"], cf(p["confirmado_en"])] for p in self.lista_pagos],
                          [p["id"] for p in self.lista_pagos])
        if self.lista_pagos:
            self.pagos.selectRow(0)
        self.actualizar_botones()

    def _pago(self):
        pago_id = self.pagos.id_actual()
        return next((p for p in self.lista_pagos if p["id"] == pago_id), None)

    def actualizar_botones(self) -> None:
        pago = self._pago()
        activa = self.venta["estado"] == "completada"
        pendiente = bool(pago) and pago["estado"] == "pendiente" and pago["tipo"] == "cobro" and activa
        puede_caja = self.ctx.puede("caja")
        for b in (self.b_confirmar, self.b_rechazar, self.b_cancelar):
            b.setEnabled(pendiente and puede_caja)
        self.b_comision.setEnabled(bool(pago) and pago["estado"] == "confirmado" and pago["medio"] == "mercadopago"
                                   and pago["tipo"] == "cobro" and puede_caja)
        self.b_cobro.setEnabled(activa and puede_caja and self.ctx.ventas.saldo(self.venta_id) > 0)
        self.b_anular.setVisible(self.ctx.puede("anular"))
        self.b_anular.setEnabled(activa)

    def confirmar_pago(self) -> None:
        pago = self._pago()
        dialogo = DialogoConfirmarPago(self, pago)
        if dialogo.exec():
            self.ctx.ventas.confirmar_pago(pago["id"], dialogo.referencia.text(), dialogo.comision_cent())
            self.cargar()

    def descartar(self, estado: str) -> None:
        pago = self._pago()
        if confirmar(self, f"¿Marcar este pago de {fmt_dinero(pago['monto_cent'])} como {estado}?\n\n"
                           "La venta va a quedar sin cobrar hasta que registres un nuevo cobro.", f"Marcar {estado}"):
            self.ctx.ventas.descartar_pago(pago["id"], estado)
            self.cargar()

    def comision(self) -> None:
        pago = self._pago()
        dialogo = DialogoImporte(self, "Comisión de Mercado Pago", "Comisión ($)",
                                 texto="Importe que Mercado Pago descontó de este cobro.",
                                 inicial=de_centavos(pago["comision_cent"]), aceptar="Guardar")
        if dialogo.exec():
            self.ctx.ventas.registrar_comision(pago["id"], a_centavos(dialogo.importe.valor()))
            self.cargar()

    def nuevo_cobro(self) -> None:
        dialogo = DialogoNuevoCobro(self, self.ctx.ventas.saldo(self.venta_id))
        if dialogo.exec():
            self.ctx.ventas.agregar_pago(self.venta_id, dialogo.pago())
            self.cargar()

    def anular(self) -> None:
        dialogo = Dialogo(self, "Anular venta", "Anular venta", 460)
        dialogo.cuerpo.insertWidget(0, etiqueta(
            f"Vas a anular la venta N° {self.venta_id} por {fmt_dinero(self.venta['total_cent'])}.\n\n"
            "Los productos vuelven al stock y el dinero cobrado se registra como devolución en la caja abierta. "
            "La venta no se borra: queda en el historial como anulada.", ajustar=True))
        motivo = QLineEdit()
        dialogo.formulario.addRow("Motivo:", motivo)
        dialogo.terminar()
        if dialogo.exec():
            self.ctx.ventas.anular(self.venta_id, motivo.text())
            self.cargar()

    def ticket(self) -> None:
        mostrar_comprobante(self, self.ctx, tickets.html_ticket(self.ctx, self.venta_id), f"Ticket venta {self.venta_id}")


class PaginaHistorial(Pagina):
    titulo = "Historial de ventas"

    def armar(self) -> None:
        self.periodo = SelectorPeriodo("Hoy")
        self.periodo.cambiado.connect(self.refrescar)
        self.estado = QComboBox()
        self.estado.addItem("Todas las ventas", "todas")
        for clave, nombre in ESTADOS_PAGO.items():
            self.estado.addItem(nombre, clave)
        self.estado.currentIndexChanged.connect(lambda _: self.refrescar())
        self.buscador = Buscador("N° de venta o cliente…")
        self.buscador.setMaximumWidth(240)
        self.buscador.buscar.connect(self.refrescar)
        self.cuerpo.addLayout(fila(self.periodo, self.estado, self.buscador, None,
                                   boton("Ver detalle y pagos", self.detalle, "primario"), boton("Ticket", self.ticket)))
        self.tabla = Tabla(["N°", "Fecha", "Cliente", "Total", "Medio de pago", "Estado", "Comprobante fiscal", "Usuario"], estirar=2)
        self.tabla.activada.connect(self.detalle)
        self.cuerpo.addWidget(self.tabla, 1)
        self.pie = etiqueta("", "suave")
        self.cuerpo.addWidget(self.pie)

    def refrescar(self) -> None:
        ventas = self.ctx.ventas.listar(*self.periodo.rango(), self.estado.currentData(), self.buscador.text())
        filas, colores, total = [], {}, 0
        for n, v in enumerate(ventas):
            estado = estado_pago(v)
            medios = ", ".join(MEDIOS[m] for m in (v["medios"] or "").split(",") if m)
            filas.append([(str(v["id"]), v["id"]), cf(v["fecha"]), v["cliente"], cd(v["total_cent"]), medios,
                          ESTADOS_PAGO[estado], ESTADOS_FISCALES.get(v["estado_fiscal"], ""), v["usuario"]])
            if estado in COLORES:
                colores[n] = COLORES[estado]
            if estado != "anulada":
                total += v["total_cent"]
        self.tabla.cargar(filas, [v["id"] for v in ventas], colores)
        self.pie.setText(f"{len(ventas)} ventas  ·  Total sin anuladas: {fmt_dinero(total)}")

    def detalle(self) -> None:
        DialogoVenta(self, self.ctx, self.tabla.id_requerido("Seleccioná una venta de la lista.")).exec()
        self.refrescar()
        self.ventana.actualizar_estado()

    def ticket(self) -> None:
        venta_id = self.tabla.id_requerido("Seleccioná una venta de la lista.")
        mostrar_comprobante(self, self.ctx, tickets.html_ticket(self.ctx, venta_id), f"Ticket venta {venta_id}")
