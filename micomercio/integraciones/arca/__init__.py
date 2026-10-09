"""Facturación electrónica de ARCA (ex AFIP).

Usa los servicios web oficiales:
    WSAA    autenticación: se firma un pedido con el certificado del comercio y ARCA
            devuelve un ticket de acceso (token y sign) válido por unas horas.
    WSFEv1  facturación: último número autorizado, solicitud de CAE y consulta
            de comprobantes.

Módulos:
    credenciales  clave privada, pedido de certificado (CSR), certificado y firma CMS
    transporte    envío de mensajes SOAP por HTTPS
    wsaa          ticket de acceso
    wsfe          operaciones de WSFEv1
    servicio      reglas: qué comprobante corresponde, numeración, reintentos, notas de crédito
    impreso       comprobante imprimible con CAE y código QR

Regla innegociable: un CAE solo se guarda si vino en una respuesta aprobada de
ARCA. Ningún módulo inventa un CAE ni marca una venta como autorizada por su cuenta.
"""
from __future__ import annotations

from dataclasses import dataclass

CONDICIONES_EMISOR = ["", "Responsable inscripto", "Monotributista", "Exento"]
ENTORNOS = {"homologacion": "Homologación (pruebas, sin validez fiscal)", "produccion": "Producción (facturas reales)"}

# Códigos de comprobante de ARCA
TIPOS_COMPROBANTE = {
    ("A", "factura"): 1, ("A", "nota_credito"): 3,
    ("B", "factura"): 6, ("B", "nota_credito"): 8,
    ("C", "factura"): 11, ("C", "nota_credito"): 13,
}
NOMBRES_CLASE = {"factura": "Factura", "nota_credito": "Nota de crédito"}
# Tipos de documento del receptor
DOCUMENTOS = {"CUIT": 80, "CUIL": 86, "DNI": 96, "Pasaporte": 94, "Otro": 99}
DOC_CONSUMIDOR_FINAL = 99
# Condición frente al IVA del receptor (campo CondicionIVAReceptorId)
CONDICIONES_RECEPTOR = {
    "Responsable inscripto": 1, "Exento": 4, "Consumidor final": 5, "Monotributista": 6, "No categorizado": 7,
}
# Alícuotas de IVA: porcentaje -> Id de ARCA
ALICUOTAS_IVA = {"0": 3, "2.5": 9, "5": 8, "10.5": 4, "21": 5, "27": 6}


def cuit_valido(cuit: str) -> bool:
    """Verifica el largo y el dígito verificador de un CUIT/CUIL."""
    digitos = [int(c) for c in cuit if c.isdigit()]
    if len(digitos) != 11:
        return False
    suma = sum(d * p for d, p in zip(digitos[:10], (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)))
    verificador = 11 - suma % 11
    if verificador == 11:
        verificador = 0
    return verificador == digitos[10]


def solo_digitos(texto: str) -> str:
    return "".join(c for c in (texto or "") if c.isdigit())


def formatear_cuit(cuit: str) -> str:
    d = solo_digitos(cuit)
    return f"{d[:2]}-{d[2:10]}-{d[10:]}" if len(d) == 11 else (cuit or "").strip()


def letra_comprobante(condicion_emisor: str, condicion_cliente: str) -> str | None:
    """Letra que corresponde según la condición frente al IVA de quien vende y de quien compra."""
    if condicion_emisor in ("Monotributista", "Exento"):
        return "C"
    if condicion_emisor == "Responsable inscripto":
        return "A" if condicion_cliente in ("Responsable inscripto", "Monotributista") else "B"
    return None


@dataclass
class EstadoFiscal:
    disponible: bool
    mensaje: str


def crear_servicio(ctx):
    from .servicio import ServicioArca

    return ServicioArca(ctx)
