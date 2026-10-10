"""Comprobante fiscal imprimible, con CAE y código QR (RG 4892)."""
from __future__ import annotations

import base64
import json
from html import escape

import segno

from ...core.dinero import fmt_cantidad, fmt_dinero
from ...core.errores import ErrorNegocio
from ...servicios.tickets import ESTILO
from . import NOMBRES_CLASE, formatear_cuit

URL_QR = "https://www.afip.gob.ar/fe/qr/?p="
PORCENTAJES = {3: "0 %", 9: "2,5 %", 8: "5 %", 4: "10,5 %", 5: "21 %", 6: "27 %"}
LEYENDA_MONOTRIBUTO = ("El crédito fiscal discriminado en el presente comprobante, sólo podrá ser computado a efectos "
                       "del Régimen de Sostenimiento e Inclusión Fiscal para Pequeños Contribuyentes de la Ley Nº 27.618.")


def _fecha(aaaammdd: str) -> str:
    return f"{aaaammdd[6:8]}/{aaaammdd[4:6]}/{aaaammdd[0:4]}" if len(aaaammdd) == 8 else aaaammdd


def datos_qr(c) -> dict:
    """Contenido del código QR, con los campos y nombres que define ARCA."""
    return {
        "ver": 1, "fecha": f"{c['fecha'][0:4]}-{c['fecha'][4:6]}-{c['fecha'][6:8]}", "cuit": int(c["cuit_emisor"]),
        "ptoVta": int(c["punto_venta"]), "tipoCmp": int(c["tipo"]), "nroCmp": int(c["numero"]),
        "importe": c["total_cent"] / 100, "moneda": "PES", "ctz": 1, "tipoDocRec": int(c["doc_tipo"]),
        "nroDocRec": int(c["doc_nro"] or 0), "tipoCodAut": "E", "codAut": int(c["cae"]),
    }


def url_qr(c) -> str:
    return URL_QR + base64.b64encode(json.dumps(datos_qr(c), separators=(",", ":")).encode()).decode()


def _fila(nombre: str, valor: str, clase: str = "") -> str:
    return f"<tr class='{clase}'><td>{escape(nombre)}</td><td class='d'>{escape(valor)}</td></tr>"


def html_comprobante(ctx, comprobante_id: int) -> str:
    if getattr(ctx, "remoto", False):
        return ctx.sistema.html_comprobante(comprobante_id)
    from .servicio import ServicioArca

    c = ServicioArca(ctx).obtener(comprobante_id)
    if c["estado"] != "autorizada" or not c["cae"]:
        # Sin CAE no hay comprobante fiscal que imprimir.
        raise ErrorNegocio("Este comprobante todavía no fue autorizado por ARCA: no se puede imprimir como factura.")
    emisor, receptor = json.loads(c["emisor"]), json.loads(c["receptor"])
    letra, prueba = c["letra"], c["entorno"] != "produccion"
    p = [ESTILO]
    if prueba:
        p.append("<div class='c'><b>*** COMPROBANTE DE PRUEBA (HOMOLOGACIÓN) ***<br>SIN VALIDEZ FISCAL</b></div><hr>")
    p.append(f"<div class='c'><h1>{escape(emisor.get('razon_social', ''))}</h1>{escape(emisor.get('domicilio', ''))}<br>"
             f"{escape(emisor.get('condicion', ''))}</div>")
    p.append(f"CUIT: {formatear_cuit(c['cuit_emisor'])}<br>")
    if emisor.get("ingresos_brutos"):
        p.append(f"Ingresos Brutos: {escape(emisor['ingresos_brutos'])}<br>")
    if emisor.get("inicio_actividades"):
        p.append(f"Inicio de actividades: {escape(emisor['inicio_actividades'])}<br>")
    p.append("<hr>")
    p.append(f"<div class='c'><h1>{NOMBRES_CLASE[c['clase']].upper()} {letra}</h1>Cód. {int(c['tipo']):03d}</div>")
    p.append(f"N° {int(c['punto_venta']):05d}-{int(c['numero']):08d} &nbsp;·&nbsp; Fecha: {_fecha(c['fecha'])}<br>")
    if c["comprobante_asociado_id"]:
        a = ServicioArca(ctx).obtener(c["comprobante_asociado_id"])
        p.append(f"Anula: Factura {a['letra']} {int(a['punto_venta']):05d}-{int(a['numero']):08d}<br>")
    p.append("<hr>")
    p.append(f"Cliente: {escape(receptor.get('nombre', ''))}<br>")
    if receptor.get("documento"):
        p.append(f"{escape(receptor['documento'])}<br>")
    p.append(f"Condición frente al IVA: {escape(receptor.get('condicion', ''))}<br>")
    if receptor.get("domicilio"):
        p.append(f"Domicilio: {escape(receptor['domicilio'])}<br>")
    p.append("<hr><table width='100%'>")
    # Una nota de crédito parcial detalla solo lo devuelto.
    renglones = json.loads(c["devolucion_json"])["lineas"] if c["parcial"] else ctx.ventas.items(c["venta_id"])
    for i in renglones:
        # En A los precios van sin IVA (se discrimina abajo); en B y C van finales.
        precio, importe = i["precio_unit_cent"], i["total_cent"]
        if letra == "A":
            importe = i["neto_cent"]
            precio = round(i["neto_cent"] * 1000 / i["cantidad_mil"]) if i["cantidad_mil"] else 0
        p.append(f"<tr><td colspan='2'>{escape(i['nombre'])}</td></tr>")
        detalle = f"{fmt_cantidad(i['cantidad_mil'])} {i['unidad']} x {fmt_dinero(precio)}"
        if letra == "A":
            detalle += f"  (IVA {i['impuesto_pct'].replace('.', ',')} %)"
        p.append(f"<tr><td class='chico'>&nbsp;&nbsp;{escape(detalle)}</td><td class='d'>{fmt_dinero(importe)}</td></tr>")
    p.append("</table><hr><table width='100%'>")
    alicuotas = json.loads(c["alicuotas"])
    if letra == "A":
        p.append(_fila("Importe neto gravado", fmt_dinero(c["neto_cent"])))
        for identificador, _, importe in alicuotas:
            p.append(_fila(f"IVA {PORCENTAJES.get(identificador, '')}", fmt_dinero(importe)))
    p.append(_fila("TOTAL", fmt_dinero(c["total_cent"]), "total"))
    p.append("</table>")
    if letra == "B":
        p.append("<br><div class='chico'><b>Régimen de Transparencia Fiscal al Consumidor (Ley 27.743)</b><br>"
                 f"IVA contenido: {fmt_dinero(c['iva_cent'])}</div>")
    if letra == "A" and receptor.get("condicion") == "Monotributista":
        p.append(f"<br><div class='chico'>{LEYENDA_MONOTRIBUTO}</div>")
    p.append("<hr>")
    qr = segno.make(url_qr(c), error="m").png_data_uri(scale=3, border=2)
    p.append(f"<div class='c'><img src='{qr}'><br>CAE N°: <b>{c['cae']}</b><br>"
             f"Vencimiento del CAE: {_fecha(c['cae_vencimiento'])}<br><span class='chico'>Comprobante autorizado</span></div>")
    if prueba:
        p.append("<hr><div class='c'><b>*** SIN VALIDEZ FISCAL ***</b></div>")
    return "".join(p)
