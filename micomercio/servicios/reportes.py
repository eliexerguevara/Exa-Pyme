from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from ..core.dinero import D, decimal_csv, de_centavos, de_milesimas, fmt_cantidad, fmt_dinero, fmt_pct, redondear
from ..core.util import fecha_legible, rango_dias
from .caja import MEDIOS
from .inventario import TIPOS as TIPOS_MOVIMIENTO


@dataclass
class Reporte:
    titulo: str
    columnas: list[tuple[str, str]]  # (título, tipo): texto | dinero | cantidad | pct | entero | fecha
    filas: list[list] = field(default_factory=list)
    notas: str = ""
    usa_periodo: bool = True


def formatear(valor, tipo: str, para_csv: bool = False) -> str:
    """Una celda puede traer su propio tipo como tupla (tipo, valor)."""
    if isinstance(valor, tuple):
        tipo, valor = valor
    if valor is None:
        return ""
    if tipo == "dinero":
        return decimal_csv(de_centavos(valor)) if para_csv else fmt_dinero(valor)
    if tipo == "cantidad":
        return decimal_csv(de_milesimas(valor), 3) if para_csv else fmt_cantidad(valor)
    if tipo == "pct":
        return decimal_csv(valor) if para_csv else fmt_pct(valor) + " %"
    if tipo == "fecha":
        return fecha_legible(valor)
    return str(valor)


def _pct(parte: int, total: int) -> Decimal:
    return redondear(Decimal(parte) * 100 / total) if total else Decimal("0.00")


class Reportes:
    def __init__(self, ctx):
        self.ctx = ctx
        self.db = ctx.db

    LISTA = [
        ("resumen", "Resumen del período"),
        ("medios_pago", "Ventas por medio de pago"),
        ("mas_vendidos", "Productos más vendidos"),
        ("stock_bajo", "Productos con stock bajo"),
        ("compras", "Compras"),
        ("movimientos", "Movimientos de inventario"),
        ("valor_stock", "Precio Costo y valor del stock"),
        ("descuentos", "Devoluciones y descuentos"),
        ("cajas", "Cierres de caja por computadora"),
    ]

    def generar(self, clave: str, desde: str, hasta: str) -> Reporte:
        self.ctx.requiere("reportes")
        return getattr(self, clave)(desde, hasta)

    # ---- cifras base -----------------------------------------------------
    def cifras(self, desde: str, hasta: str) -> dict:
        """Cifras del período, en centavos.

        Facturación: total de las ventas no anuladas, con impuestos.
        Ingresos cobrados: pagos confirmados en el período, menos devoluciones.
        Ganancia bruta: ventas sin impuestos menos el costo de lo vendido
        (el costo es el que tenía cada producto en el momento de la venta).
        """
        inicio, fin = rango_dias(desde, hasta)
        v = self.db.uno(
            """SELECT COUNT(*) AS cantidad, COALESCE(SUM(total_cent), 0) AS total, COALESCE(SUM(neto_cent), 0) AS neto,
                      COALESCE(SUM(impuestos_cent), 0) AS impuestos, COALESCE(SUM(descuento_cent), 0) AS descuentos
               FROM ventas WHERE estado = 'completada' AND fecha >= ? AND fecha < ?""",
            (inicio, fin),
        )
        costo_mil = self.db.valor(
            """SELECT SUM(i.costo_unit_cent * i.cantidad_mil) FROM venta_items i JOIN ventas v ON v.id = i.venta_id
               WHERE v.estado = 'completada' AND v.fecha >= ? AND v.fecha < ?""",
            (inicio, fin), 0,
        )
        costo = int(redondear(Decimal(costo_mil) / 1000, 0))
        p = self.db.uno(
            """SELECT COALESCE(SUM(CASE WHEN tipo = 'cobro' THEN monto_cent END), 0) AS cobros,
                      COALESCE(SUM(CASE WHEN tipo = 'devolucion' THEN monto_cent END), 0) AS devoluciones,
                      COALESCE(SUM(CASE WHEN tipo = 'cobro' THEN comision_cent END), 0) AS comisiones
               FROM pagos WHERE estado = 'confirmado' AND confirmado_en >= ? AND confirmado_en < ?""",
            (inicio, fin),
        )
        pendientes = self.db.valor(
            """SELECT SUM(p.monto_cent) FROM pagos p JOIN ventas v ON v.id = p.venta_id
               WHERE p.tipo = 'cobro' AND p.estado = 'pendiente' AND v.estado = 'completada'
                 AND v.fecha >= ? AND v.fecha < ?""",
            (inicio, fin), 0,
        )
        anuladas = self.db.uno(
            """SELECT COUNT(*) AS cantidad, COALESCE(SUM(total_cent), 0) AS total FROM ventas
               WHERE estado = 'anulada' AND fecha >= ? AND fecha < ?""",
            (inicio, fin),
        )
        # Devoluciones parciales del período (de ventas vigentes): restan de lo vendido y de su costo.
        dev = self.db.uno(
            """SELECT COUNT(*) AS cantidad, COALESCE(SUM(d.total_cent), 0) AS total, COALESCE(SUM(d.neto_cent), 0) AS neto,
                      COALESCE(SUM(d.impuestos_cent), 0) AS impuestos, COALESCE(SUM(d.costo_cent), 0) AS costo
               FROM devoluciones d JOIN ventas v ON v.id = d.venta_id
               WHERE v.estado = 'completada' AND d.fecha >= ? AND d.fecha < ?""",
            (inicio, fin),
        )
        neto, costo = v["neto"] - dev["neto"], costo - dev["costo"]
        ganancia = neto - costo
        return {
            "ventas_cantidad": v["cantidad"], "facturacion_cent": v["total"] - dev["total"], "neto_cent": neto,
            "impuestos_cent": v["impuestos"] - dev["impuestos"], "descuentos_cent": v["descuentos"], "costo_cent": costo,
            "ganancia_bruta_cent": ganancia, "margen_pct": _pct(ganancia, neto),
            "parciales_cantidad": dev["cantidad"], "parciales_cent": dev["total"],
            "cobrado_cent": p["cobros"] - p["devoluciones"], "devoluciones_cent": p["devoluciones"],
            "comisiones_cent": p["comisiones"], "pendientes_cent": pendientes,
            "anuladas_cantidad": anuladas["cantidad"], "anuladas_cent": anuladas["total"],
        }

    # ---- reportes --------------------------------------------------------
    def resumen(self, desde: str, hasta: str) -> Reporte:
        c = self.cifras(desde, hasta)
        d = lambda cent: ("dinero", cent)  # noqa: E731
        filas = [
            ["Cantidad de ventas", ("entero", c["ventas_cantidad"])],
            ["Ventas totales (facturación, con impuestos)", d(c["facturacion_cent"])],
            ["Impuestos incluidos en las ventas", d(c["impuestos_cent"])],
            ["Ventas sin impuestos", d(c["neto_cent"])],
            ["Descuentos otorgados", d(c["descuentos_cent"])],
            ["Ingresos cobrados (pagos confirmados menos devoluciones)", d(c["cobrado_cent"])],
            ["Pagos pendientes de confirmar", d(c["pendientes_cent"])],
            ["Devoluciones de dinero", d(c["devoluciones_cent"])],
            ["Devoluciones parciales de productos (ya descontadas de las ventas)", d(c["parciales_cent"])],
            ["Ventas anuladas (cantidad)", ("entero", c["anuladas_cantidad"])],
            ["Ventas anuladas (importe)", d(c["anuladas_cent"])],
            ["Costo de la mercadería vendida", d(c["costo_cent"])],
            ["Ganancia bruta estimada", d(c["ganancia_bruta_cent"])],
            ["Margen de ganancia estimado sobre ventas sin impuestos", ("pct", c["margen_pct"])],
            ["Comisiones de Mercado Pago registradas", d(c["comisiones_cent"])],
            ["Ganancia bruta menos comisiones registradas", d(c["ganancia_bruta_cent"] - c["comisiones_cent"])],
        ]
        notas = (
            "Facturación es lo vendido; ingresos cobrados es el dinero que realmente entró. "
            "La ganancia bruta es una estimación: ventas sin impuestos menos el Precio Costo de lo vendido. "
            "La ganancia neta no se calcula porque el sistema no registra gastos como alquiler, sueldos, "
            "servicios u otros impuestos: hay que restarlos de la ganancia bruta."
        )
        return Reporte("Resumen del período", [("Concepto", "texto"), ("Valor", "texto")], filas, notas)

    def medios_pago(self, desde: str, hasta: str) -> Reporte:
        inicio, fin = rango_dias(desde, hasta)
        datos = {m: {"ops": 0, "cobros": 0, "dev": 0, "com": 0} for m in MEDIOS}
        for f in self.db.consultar(
            """SELECT medio, tipo, COUNT(*) AS ops, SUM(monto_cent) AS monto, SUM(comision_cent) AS comision
               FROM pagos WHERE estado = 'confirmado' AND confirmado_en >= ? AND confirmado_en < ? GROUP BY medio, tipo""",
            (inicio, fin),
        ):
            d = datos[f["medio"]]
            if f["tipo"] == "cobro":
                d["ops"], d["cobros"], d["com"] = f["ops"], f["monto"], f["comision"] or 0
            else:
                d["dev"] = f["monto"]
        filas = [
            [MEDIOS[m], d["ops"], d["cobros"], d["dev"], d["cobros"] - d["dev"], d["com"], d["cobros"] - d["dev"] - d["com"]]
            for m, d in datos.items()
        ]
        columnas = [("Medio de pago", "texto"), ("Cobros", "entero"), ("Cobrado", "dinero"), ("Devoluciones", "dinero"),
                    ("Ingreso", "dinero"), ("Comisiones", "dinero"), ("Neto recibido", "dinero")]
        return Reporte("Ventas por medio de pago", columnas, filas, "Solo incluye pagos confirmados en el período.")

    def mas_vendidos(self, desde: str, hasta: str) -> Reporte:
        inicio, fin = rango_dias(desde, hasta)
        filas = []
        for f in self.db.consultar(
            """SELECT p.codigo, p.nombre, SUM(i.cantidad_mil - COALESCE(r.cantidad, 0)) AS cantidad,
                      SUM(i.total_cent - COALESCE(r.total, 0)) AS total, SUM(i.neto_cent - COALESCE(r.neto, 0)) AS neto,
                      SUM(i.costo_unit_cent * (i.cantidad_mil - COALESCE(r.cantidad, 0))) AS costo_mil
               FROM venta_items i JOIN ventas v ON v.id = i.venta_id JOIN productos p ON p.id = i.producto_id
               LEFT JOIN (SELECT venta_item_id, SUM(cantidad_mil) AS cantidad, SUM(total_cent) AS total, SUM(neto_cent) AS neto
                          FROM devolucion_items GROUP BY venta_item_id) r ON r.venta_item_id = i.id
               WHERE v.estado = 'completada' AND v.fecha >= ? AND v.fecha < ?
               GROUP BY i.producto_id HAVING SUM(i.cantidad_mil - COALESCE(r.cantidad, 0)) > 0
               ORDER BY 3 DESC, 4 DESC LIMIT 200""",
            (inicio, fin),
        ):
            costo = int(redondear(Decimal(f["costo_mil"]) / 1000, 0))
            ganancia = f["neto"] - costo
            filas.append([f["codigo"], f["nombre"], f["cantidad"], f["total"], f["neto"], costo, ganancia, _pct(ganancia, f["neto"])])
        columnas = [("Código", "texto"), ("Producto", "texto"), ("Cantidad vendida", "cantidad"),
                    ("Ventas con impuestos", "dinero"), ("Ventas sin impuestos", "dinero"), ("Costo", "dinero"),
                    ("Ganancia bruta estimada", "dinero"), ("Margen", "pct")]
        return Reporte("Productos más vendidos", columnas, filas)

    def stock_bajo(self, desde: str, hasta: str) -> Reporte:
        filas = []
        for p in self.ctx.inventario.existencias():
            if p["stock_mil"] <= 0:
                estado = "Agotado"
            elif p["stock_mil"] <= p["stock_minimo_mil"]:
                estado = "Stock bajo"
            else:
                continue
            filas.append([p["codigo"], p["nombre"], p["categoria"], p["proveedor"], p["stock_mil"], p["stock_minimo_mil"], estado])
        filas.sort(key=lambda f: (f[6] != "Agotado", f[1].lower()))
        columnas = [("Código", "texto"), ("Producto", "texto"), ("Categoría", "texto"), ("Proveedor", "texto"),
                    ("Cantidad disponible", "cantidad"), ("Stock mínimo", "cantidad"), ("Estado", "texto")]
        return Reporte("Productos con stock bajo", columnas, filas, "Muestra el estado actual del inventario.", usa_periodo=False)

    def compras(self, desde: str, hasta: str) -> Reporte:
        filas = [[c["id"], c["fecha"], c["proveedor"], c["comprobante"], c["renglones"], c["total_cent"], c["usuario"]]
                 for c in self.ctx.compras.listar(desde, hasta)]
        columnas = [("N°", "entero"), ("Fecha", "fecha"), ("Proveedor", "texto"), ("Comprobante", "texto"),
                    ("Productos", "entero"), ("Total", "dinero"), ("Usuario", "texto")]
        total = sum(f[5] for f in filas)
        return Reporte("Compras", columnas, filas, f"Total comprado en el período: {fmt_dinero(total)}")

    def movimientos(self, desde: str, hasta: str) -> Reporte:
        filas = [[m["fecha"], m["codigo"], m["nombre"], TIPOS_MOVIMIENTO.get(m["tipo"], m["tipo"]), m["cantidad_mil"],
                  m["stock_resultante_mil"], m["motivo"], m["usuario"]]
                 for m in self.ctx.inventario.movimientos(desde=desde, hasta=hasta, limite=100_000)]
        columnas = [("Fecha", "fecha"), ("Código", "texto"), ("Producto", "texto"), ("Movimiento", "texto"),
                    ("Cantidad", "cantidad"), ("Stock resultante", "cantidad"), ("Motivo", "texto"), ("Usuario", "texto")]
        return Reporte("Movimientos de inventario", columnas, filas)

    def valor_stock(self, desde: str, hasta: str) -> Reporte:
        filas = []
        for p in self.ctx.inventario.existencias():
            stock = max(p["stock_mil"], 0)
            valor_costo = int(redondear(Decimal(stock) * p["costo_cent"] / 1000, 0))
            valor_venta = int(redondear(Decimal(stock) * p["precio_final_cent"] / 1000, 0))
            filas.append([p["codigo"], p["nombre"], p["categoria"], p["stock_mil"], p["costo_cent"], valor_costo,
                          D(p["ganancia_pct"]), p["precio_final_cent"], valor_venta])
        columnas = [("Código", "texto"), ("Producto", "texto"), ("Categoría", "texto"), ("Cantidad disponible", "cantidad"),
                    ("Precio Costo", "dinero"), ("Valor del stock al costo", "dinero"), ("Porcentaje de ganancia", "pct"),
                    ("Precio de venta final", "dinero"), ("Valor del stock a precio de venta", "dinero")]
        v = self.ctx.inventario.valor_inventario()
        notas = (f"Valor total del stock al costo: {fmt_dinero(v['costo_cent'])} · "
                 f"a precio de venta: {fmt_dinero(v['venta_cent'])}. Muestra el estado actual del inventario.")
        return Reporte("Precio Costo y valor del stock", columnas, filas, notas, usa_periodo=False)

    def descuentos(self, desde: str, hasta: str) -> Reporte:
        inicio, fin = rango_dias(desde, hasta)
        filas = []
        for v in self.db.consultar(
            """SELECT v.*, COALESCE(u.nombre, '') AS usuario FROM ventas v LEFT JOIN usuarios u ON u.id = v.usuario_id
               WHERE v.fecha >= ? AND v.fecha < ? AND (v.descuento_cent > 0 OR v.estado = 'anulada') ORDER BY v.id DESC""",
            (inicio, fin),
        ):
            if v["descuento_cent"] > 0:
                filas.append([v["id"], v["fecha"], "Descuento", v["descuento_cent"], v["total_cent"], "", v["usuario"]])
            if v["estado"] == "anulada":
                filas.append([v["id"], v["anulada_en"], "Anulación", v["total_cent"], v["total_cent"], v["motivo_anulacion"], v["usuario"]])
        for dv in self.db.consultar(
            """SELECT d.*, v.total_cent AS venta_total, COALESCE(u.nombre, '') AS usuario FROM devoluciones d
               JOIN ventas v ON v.id = d.venta_id LEFT JOIN usuarios u ON u.id = d.usuario_id
               WHERE d.fecha >= ? AND d.fecha < ? ORDER BY d.id DESC""",
            (inicio, fin),
        ):
            filas.append([dv["venta_id"], dv["fecha"], "Devolución parcial", dv["total_cent"], dv["venta_total"], dv["motivo"], dv["usuario"]])
        columnas = [("Venta N°", "entero"), ("Fecha", "fecha"), ("Tipo", "texto"), ("Importe", "dinero"),
                    ("Total de la venta", "dinero"), ("Motivo", "texto"), ("Usuario", "texto")]
        return Reporte("Devoluciones y descuentos", columnas, filas)

    def cajas(self, desde: str, hasta: str) -> Reporte:
        inicio, fin = rango_dias(desde, hasta)
        filas = []
        for c in self.db.consultar("SELECT id FROM cajas WHERE abierta_en >= ? AND abierta_en < ? ORDER BY id DESC", (inicio, fin)):
            r = self.ctx.caja.resumen(c["id"])
            filas.append([r["caja_id"], r["puesto"], r["abierta_en"], r["cerrada_en"], r["abierta_por"], r["ventas_cantidad"],
                          r["ventas_total_cent"], r["cobrado_total_cent"], r["cobrado_cent"]["efectivo"], r["efectivo_esperado_cent"],
                          r["efectivo_contado_cent"], r["diferencia_cent"]])
        columnas = [("N°", "entero"), ("Caja", "texto"), ("Apertura", "fecha"), ("Cierre", "fecha"), ("Abrió", "texto"),
                    ("Ventas", "entero"), ("Total vendido", "dinero"), ("Total cobrado", "dinero"), ("Efectivo", "dinero"),
                    ("Efectivo esperado", "dinero"), ("Efectivo contado", "dinero"), ("Diferencia", "dinero")]
        return Reporte("Cierres de caja por computadora", columnas, filas,
                       "Cada computadora tiene su propia caja. Las que siguen abiertas no tienen cierre ni diferencia.")
