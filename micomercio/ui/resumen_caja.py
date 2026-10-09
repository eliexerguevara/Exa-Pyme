from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QWidget

from ..core.dinero import fmt_dinero
from . import tema
from .comunes import etiqueta, panel


class ResumenCaja(QWidget):
    """Resumen de una jornada de caja: lo vendido, lo realmente cobrado y el efectivo esperado."""

    GRUPOS = [
        ("Ventas y cobros", [
            ("ventas", "Total de ventas del día"),
            ("cobrado", "Total efectivamente cobrado"),
            ("pendientes", "Pagos pendientes"),
            ("devoluciones", "Devoluciones y anulaciones"),
        ]),
        ("Ingresos por medio de pago", [
            ("efectivo", "Ingresos en efectivo"),
            ("transferencia", "Ingresos mediante transferencias"),
            ("tarjeta", "Ingresos mediante tarjetas"),
            ("mercadopago", "Ingresos mediante Mercado Pago"),
            ("mp_comisiones", "Comisiones de Mercado Pago"),
            ("mp_neto", "Mercado Pago neto recibido"),
        ]),
        ("Efectivo en caja", [
            ("inicial", "Saldo inicial de caja"),
            ("entradas", "Entradas manuales"),
            ("salidas", "Salidas manuales"),
            ("esperado", "Efectivo esperado al cierre"),
            ("contado", "Efectivo contado"),
            ("diferencia", "Diferencia de caja"),
        ]),
    ]

    def __init__(self):
        super().__init__()
        self.valores: dict[str, QLabel] = {}
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(12)
        for titulo, campos in self.GRUPOS:
            marco, v = panel(titulo)
            rejilla = QGridLayout()
            rejilla.setVerticalSpacing(7)
            for n, (clave, nombre) in enumerate(campos):
                rejilla.addWidget(etiqueta(nombre, "suave"), n, 0)
                valor = etiqueta("—")
                valor.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                valor.setStyleSheet("font-weight: 600;")
                rejilla.addWidget(valor, n, 1)
                self.valores[clave] = valor
            v.addLayout(rejilla)
            v.addStretch(1)
            h.addWidget(marco, 1)

    def mostrar(self, r: dict | None) -> None:
        if r is None:
            for valor in self.valores.values():
                valor.setText("—")
                valor.setStyleSheet("font-weight: 600;")
            return
        d = fmt_dinero
        textos = {
            "ventas": f"{d(r['ventas_total_cent'])}  ({r['ventas_cantidad']})",
            "cobrado": d(r["cobrado_total_cent"]),
            "pendientes": d(r["pendientes_cent"]),
            "devoluciones": f"{d(r['devoluciones_cent'])}  ({r['anuladas_cantidad']})",
            "efectivo": d(r["cobrado_cent"]["efectivo"]),
            "transferencia": d(r["cobrado_cent"]["transferencia"]),
            "tarjeta": d(r["cobrado_cent"]["tarjeta"]),
            "mercadopago": d(r["cobrado_cent"]["mercadopago"]),
            "mp_comisiones": d(r["mp_comisiones_cent"]),
            "mp_neto": d(r["mp_neto_cent"]),
            "inicial": d(r["saldo_inicial_cent"]),
            "entradas": d(r["entradas_cent"]),
            "salidas": d(r["salidas_cent"]),
            "esperado": d(r["efectivo_esperado_cent"]),
            "contado": d(r["efectivo_contado_cent"]) if r["estado"] == "cerrada" else "Se carga al cerrar",
            "diferencia": d(r["diferencia_cent"]) if r["estado"] == "cerrada" else "—",
        }
        colores = {"cobrado": tema.VERDE, "esperado": tema.AZUL}
        if r["pendientes_cent"]:
            colores["pendientes"] = tema.NARANJA
        if r["estado"] == "cerrada" and r["diferencia_cent"]:
            colores["diferencia"] = tema.ROJO
        for clave, valor in self.valores.items():
            valor.setText(textos[clave])
            valor.setStyleSheet(f"font-weight: 600; color: {colores.get(clave, tema.TEXTO)};")
