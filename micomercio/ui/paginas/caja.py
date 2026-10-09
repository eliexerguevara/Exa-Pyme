from __future__ import annotations

from PySide6.QtWidgets import QLineEdit

from ...core.dinero import a_centavos, de_centavos, fmt_dinero
from ...core.util import fecha_legible
from ...servicios import tickets
from .. import tema
from ..comunes import (
    CampoDecimal, Dialogo, DialogoImporte, Pagina, Tabla, boton, cd, cf, confirmar, etiqueta, fila, informar,
)
from ..impresion import mostrar_comprobante
from ..resumen_caja import ResumenCaja


class DialogoCierre(Dialogo):
    def __init__(self, padre, esperado_cent: int):
        super().__init__(padre, "Cerrar caja", "Cerrar caja", 460)
        self.esperado = esperado_cent
        self.cuerpo.insertWidget(0, etiqueta(
            "Contá el efectivo que hay en la caja y escribí el importe. El sistema lo compara con el efectivo esperado.",
            ajustar=True))
        self.contado = CampoDecimal("Efectivo contado", dinero=True)
        self.diferencia = etiqueta("—", "grande")
        self.notas = QLineEdit()
        self.notas.setPlaceholderText("Opcional")
        self.formulario.addRow("Efectivo esperado:", etiqueta(fmt_dinero(esperado_cent), "grande"))
        self.formulario.addRow("Efectivo contado ($):", self.contado)
        self.formulario.addRow("Diferencia de caja:", self.diferencia)
        self.formulario.addRow("Notas:", self.notas)
        self.contado.textEdited.connect(lambda _: self.calcular())
        self.terminar()
        self.contado.setFocus()

    def calcular(self) -> None:
        contado = self.contado.valor_o()
        if contado is None:
            self.diferencia.setText("—")
            return
        diferencia = a_centavos(contado) - self.esperado
        texto = "Sin diferencia" if diferencia == 0 else fmt_dinero(diferencia) + (" (sobra)" if diferencia > 0 else " (falta)")
        self.diferencia.setText(texto)
        self.diferencia.setStyleSheet(f"color: {tema.VERDE if diferencia == 0 else tema.ROJO};")

    def guardar(self) -> None:
        self.contado.valor()
        self.accept()


class PaginaCaja(Pagina):
    titulo = "Caja diaria"

    def armar(self) -> None:
        self.estado = etiqueta("", "chip")
        self.encabezado.insertWidget(1, self.estado)
        self.b_abrir = boton("Abrir caja", self.abrir, "primario")
        self.b_entrada = boton("Entrada de efectivo", lambda: self.movimiento("entrada"))
        self.b_salida = boton("Salida de efectivo", lambda: self.movimiento("salida"))
        self.b_cerrar = boton("Cerrar caja", self.cerrar, "primario")
        self.cuerpo.addLayout(fila(self.b_abrir, self.b_entrada, self.b_salida, self.b_cerrar, None,
                                   boton("Imprimir resumen", self.imprimir)))
        self.titulo_resumen = etiqueta("", "subtitulo")
        self.cuerpo.addWidget(self.titulo_resumen)
        self.resumen = ResumenCaja()
        self.cuerpo.addWidget(self.resumen)

        self.cuerpo.addWidget(etiqueta("Jornadas de caja", "subtitulo"))
        self.cuerpo.addWidget(etiqueta("Seleccioná una jornada para ver su resumen. Las entradas y salidas manuales "
                                       "aparecen a la derecha.", "suave"))
        self.tabla = Tabla(["N°", "Apertura", "Cierre", "Abrió", "Efectivo esperado", "Efectivo contado", "Diferencia", "Estado"],
                           estirar=3, minimo=110)
        self.tabla.itemSelectionChanged.connect(self.mostrar_seleccion)
        self.movimientos = Tabla(["Hora", "Tipo", "Importe", "Motivo"], estirar=3, ordenable=False, minimo=120)
        self.movimientos.setMaximumWidth(400)
        self.cuerpo.addLayout(fila(self.tabla, self.movimientos, espacio=12), 1)

    def refrescar(self) -> None:
        abierta = self.ctx.caja.abierta()
        self.estado.setText("ABIERTA" if abierta else "CERRADA")
        self.estado.setStyleSheet(
            "background: #DCFCE7; color: #166534;" if abierta else "background: #FEE2E2; color: #991B1B;")
        self.b_abrir.setVisible(not abierta)
        for b in (self.b_entrada, self.b_salida, self.b_cerrar):
            b.setVisible(bool(abierta))
        cajas = self.ctx.caja.listar()
        filas = []
        for c in cajas:
            esperado = c["efectivo_esperado_cent"]
            filas.append([(str(c["id"]), c["id"]), cf(c["abierta_en"]), cf(c["cerrada_en"]), c["abierta_por_nombre"],
                          cd(esperado) if esperado is not None else "", cd(c["efectivo_contado_cent"]) if esperado is not None else "",
                          cd(c["diferencia_cent"]) if esperado is not None else "", "Abierta" if c["estado"] == "abierta" else "Cerrada"])
        self.tabla.blockSignals(True)
        self.tabla.cargar(filas, [c["id"] for c in cajas])
        self.tabla.blockSignals(False)
        if cajas and self.tabla.id_actual() is None:
            self.tabla.seleccionar_id(cajas[0]["id"])
        self.mostrar_seleccion()
        self.ventana.actualizar_estado()

    def mostrar_seleccion(self) -> None:
        caja_id = self.tabla.id_actual()
        if caja_id is None:
            self.resumen.mostrar(None)
            self.movimientos.cargar([])
            self.titulo_resumen.setText("Todavía no se abrió ninguna caja")
            return
        r = self.ctx.caja.resumen(caja_id)
        self.resumen.mostrar(r)
        if r["estado"] == "abierta":
            self.titulo_resumen.setText(f"Caja N° {caja_id} · abierta desde el {fecha_legible(r['abierta_en'])}")
        else:
            self.titulo_resumen.setText(f"Caja N° {caja_id} · del {fecha_legible(r['abierta_en'])} al {fecha_legible(r['cerrada_en'])}")
        self.movimientos.cargar([[cf(m["fecha"]), "Entrada" if m["tipo"] == "entrada" else "Salida",
                                  cd(m["monto_cent"]), m["motivo"]] for m in self.ctx.caja.movimientos(caja_id)])

    def abrir(self) -> None:
        ultima = self.ctx.caja.ultima()
        sugerido = de_centavos(ultima["efectivo_contado_cent"] or 0) if ultima else 0
        dialogo = DialogoImporte(self, "Abrir caja", "Saldo inicial ($)", inicial=sugerido, aceptar="Abrir caja",
                                 texto="Escribí cuánto efectivo hay en la caja al empezar la jornada.")
        if dialogo.exec():
            caja_id = self.ctx.caja.abrir(a_centavos(dialogo.importe.valor()))
            self.refrescar()
            self.tabla.seleccionar_id(caja_id)

    def movimiento(self, tipo: str) -> None:
        titulo = "Entrada de efectivo" if tipo == "entrada" else "Salida de efectivo"
        dialogo = DialogoImporte(self, titulo, "Importe ($)", con_motivo=True, aceptar="Registrar",
                                 texto="Usalo para dinero que entra o sale de la caja y no es una venta: "
                                       "cambio, retiros, pagos a proveedores, gastos.")
        if dialogo.exec():
            self.ctx.caja.registrar_movimiento(tipo, a_centavos(dialogo.importe.valor()), dialogo.motivo.text())
            self.refrescar()

    def cerrar(self) -> None:
        caja = self.ctx.caja.requerir_abierta()
        r = self.ctx.caja.resumen(caja["id"])
        if r["pendientes_cent"] and not confirmar(
            self, f"Hay pagos pendientes por {fmt_dinero(r['pendientes_cent'])} que todavía no se confirmaron.\n\n"
                  "Podés cerrar igual: cuando los confirmes, van a contar en la caja que esté abierta en ese momento.",
            "Cerrar igual"):
            return
        dialogo = DialogoCierre(self, r["efectivo_esperado_cent"])
        if not dialogo.exec():
            return
        self.ctx.caja.cerrar(a_centavos(dialogo.contado.valor()), dialogo.notas.text())
        self.refrescar()
        self.tabla.seleccionar_id(caja["id"])
        if confirmar(self, "La caja quedó cerrada.\n\n¿Querés ver el reporte del cierre para imprimirlo?", "Ver reporte", "No"):
            mostrar_comprobante(self, self.ctx, tickets.html_cierre_caja(self.ctx, caja["id"]), f"Cierre de caja {caja['id']}")

    def imprimir(self) -> None:
        caja_id = self.tabla.id_requerido("Seleccioná una jornada de caja de la lista.")
        mostrar_comprobante(self, self.ctx, tickets.html_cierre_caja(self.ctx, caja_id), f"Cierre de caja {caja_id}")
