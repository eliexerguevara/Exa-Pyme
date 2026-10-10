"""Textos imprimibles (HTML simple): ticket de venta y cierre de caja.

El ticket es un comprobante interno. Mientras la venta no tenga un CAE otorgado
por ARCA, siempre lleva la leyenda «Documento no válido como factura».
"""
from __future__ import annotations

from html import escape

from ..core.dinero import fmt_cantidad, fmt_dinero
from ..core.util import fecha_legible
from .caja import MEDIOS

ESTADOS_PAGO_TICKET = {"confirmado": "", "pendiente": " (pendiente)", "rechazado": " (rechazado)", "cancelado": " (cancelado)"}

ESTILO = """
<style>
  body { font-family: 'Segoe UI', Arial, sans-serif; font-size: 9pt; color: #000; }
  h1 { font-size: 12pt; margin: 0; }
  table { width: 100%; border-collapse: collapse; }
  td, th { padding: 1px 0; vertical-align: top; }
  th { text-align: left; border-bottom: 1px solid #000; }
  .d { text-align: right; white-space: nowrap; }
  .c { text-align: center; }
  .total td { font-size: 12pt; font-weight: bold; border-top: 1px solid #000; padding-top: 3px; }
  .chico { font-size: 8pt; }
  hr { border: 0; border-top: 1px dashed #000; }
</style>
"""


def _fila(etiqueta: str, valor: str, clase: str = "") -> str:
    return f"<tr class='{clase}'><td>{escape(etiqueta)}</td><td class='d'>{escape(valor)}</td></tr>"


def html_ticket(ctx, venta_id: int) -> str:
    if getattr(ctx, "remoto", False):
        return ctx.sistema.html_ticket(venta_id)
    v = ctx.ventas.obtener(venta_id)
    cfg = ctx.config
    partes = [ESTILO, f"<div class='c'><h1>{escape(cfg.obtener('comercio_nombre'))}</h1>"]
    for clave in ("comercio_direccion", "comercio_telefono"):
        if cfg.obtener(clave):
            partes.append(f"{escape(cfg.obtener(clave))}<br>")
    partes.append("</div><hr>")
    partes.append(f"Venta N° {v['id']} &nbsp;·&nbsp; {fecha_legible(v['fecha'])}<br>")
    partes.append(f"Cliente: {escape(v['cliente'])}<br>")
    if v["usuario"]:
        partes.append(f"Atendido por: {escape(v['usuario'])}<br>")
    if v["estado"] == "anulada":
        partes.append("<div class='c'><b>*** VENTA ANULADA ***</b></div>")
    partes.append("<hr><table width='100%'>")
    for i in ctx.ventas.items(venta_id):
        partes.append(f"<tr><td colspan='2'>{escape(i['nombre'])}</td></tr>")
        detalle = f"{fmt_cantidad(i['cantidad_mil'])} {i['unidad']} x {fmt_dinero(i['precio_unit_cent'])}"
        partes.append(f"<tr><td class='chico'>&nbsp;&nbsp;{escape(detalle)}</td><td class='d'>{fmt_dinero(i['bruto_cent'])}</td></tr>")
    partes.append("</table><hr><table width='100%'>")
    if v["descuento_cent"]:
        partes.append(_fila("Importe", fmt_dinero(v["bruto_cent"])))
        partes.append(_fila("Descuento", "- " + fmt_dinero(v["descuento_cent"])))
    partes.append(_fila("Subtotal sin impuestos", fmt_dinero(v["neto_cent"])))
    partes.append(_fila("Impuestos", fmt_dinero(v["impuestos_cent"])))
    partes.append(_fila("TOTAL", fmt_dinero(v["total_cent"]), "total"))
    partes.append("</table><br><table width='100%'>")
    for p in ctx.ventas.pagos(venta_id):
        etiqueta = MEDIOS[p["medio"]] + ESTADOS_PAGO_TICKET[p["estado"]]
        if p["tipo"] == "devolucion":
            etiqueta = "Devolución " + MEDIOS[p["medio"]].lower()
        partes.append(_fila(etiqueta, fmt_dinero(p["monto_cent"])))
    partes.append("</table><hr>")
    partes.append("<div class='c chico'><b>DOCUMENTO NO VÁLIDO COMO FACTURA</b></div>")
    if cfg.obtener("ticket_pie"):
        partes.append(f"<div class='c'>{escape(cfg.obtener('ticket_pie'))}</div>")
    return "".join(partes)


def html_cierre_caja(ctx, caja_id: int) -> str:
    if getattr(ctx, "remoto", False):
        return ctx.sistema.html_cierre_caja(caja_id)
    r = ctx.caja.resumen(caja_id)
    d = fmt_dinero
    partes = [ESTILO, f"<div class='c'><h1>{escape(ctx.config.obtener('comercio_nombre'))}</h1>"]
    titulo = "Cierre de caja" if r["estado"] == "cerrada" else "Resumen de caja (abierta)"
    partes.append(f"<b>{titulo} N° {caja_id}</b><br>{escape(r['puesto'])}</div><hr>")
    partes.append(f"Apertura: {fecha_legible(r['abierta_en'])} {escape(r['abierta_por'])}<br>")
    if r["cerrada_en"]:
        partes.append(f"Cierre: {fecha_legible(r['cerrada_en'])} {escape(r['cerrada_por'])}<br>")
    partes.append("<hr><table width='100%'>")
    partes.append(_fila(f"Ventas del día ({r['ventas_cantidad']})", d(r["ventas_total_cent"])))
    partes.append(_fila("Total efectivamente cobrado", d(r["cobrado_total_cent"])))
    partes.append(_fila("Pagos pendientes", d(r["pendientes_cent"])))
    partes.append(_fila(f"Devoluciones y anulaciones ({r['anuladas_cantidad']})", d(r["devoluciones_cent"])))
    partes.append("</table><hr><b>Ingresos por medio de pago</b><table width='100%'>")
    for medio, nombre in MEDIOS.items():
        partes.append(_fila(nombre, d(r["cobrado_cent"][medio])))
    partes.append(_fila("Comisiones de Mercado Pago", "- " + d(r["mp_comisiones_cent"])))
    partes.append(_fila("Mercado Pago neto recibido", d(r["mp_neto_cent"])))
    partes.append("</table><hr><b>Efectivo en caja</b><table width='100%'>")
    partes.append(_fila("Saldo inicial", d(r["saldo_inicial_cent"])))
    partes.append(_fila("Ingresos en efectivo", d(r["cobrado_cent"]["efectivo"])))
    partes.append(_fila("Entradas manuales", d(r["entradas_cent"])))
    partes.append(_fila("Salidas manuales", "- " + d(r["salidas_cent"])))
    partes.append(_fila("Efectivo esperado", d(r["efectivo_esperado_cent"]), "total"))
    if r["estado"] == "cerrada":
        partes.append(_fila("Efectivo contado", d(r["efectivo_contado_cent"])))
        partes.append(_fila("Diferencia de caja", d(r["diferencia_cent"])))
    partes.append("</table>")
    movimientos = ctx.caja.movimientos(caja_id)
    if movimientos:
        partes.append("<hr><b>Entradas y salidas manuales</b><table width='100%'>")
        for m in movimientos:
            signo = "" if m["tipo"] == "entrada" else "- "
            partes.append(_fila(m["motivo"], signo + d(m["monto_cent"])))
        partes.append("</table>")
    if r["notas"]:
        partes.append(f"<hr>Notas: {escape(r['notas'])}")
    return "".join(partes)
