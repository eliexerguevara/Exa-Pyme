"""Facturación electrónica de ARCA (ex AFIP) — módulo preparado para la etapa 7.

Estado actual: NO emite comprobantes. Solo contiene lo que no depende de los
servicios de ARCA (validación de CUIT, tipo de comprobante que corresponde) y
la interfaz que la etapa 7 debe implementar.

Regla innegociable: un CAE solo puede provenir de una respuesta real de ARCA.
Este módulo nunca inventa un CAE ni marca una venta como autorizada por su cuenta.

Qué debe implementar la etapa 7 (siguiendo la documentación oficial vigente):
  1. WSAA: generar el ticket de requerimiento de acceso, firmarlo (CMS) con el
     certificado y la clave privada del comercio y obtener token y sign.
     El token dura unas horas: se guarda y se reutiliza hasta que venza.
  2. WSFEv1: FECompUltimoAutorizado para conocer el último número, y
     FECAESolicitar para pedir el CAE de cada comprobante (facturas A, B, C y
     notas de crédito asociadas al comprobante original).
  3. Guardar cada pedido en la tabla comprobantes_fiscales (entorno, tipo,
     punto de venta, número, CAE y su vencimiento, respuesta completa) y
     actualizar ventas.estado_fiscal: sin_comprobante -> pendiente -> autorizada | rechazada.
     Sin Internet, la venta queda guardada con estado_fiscal 'pendiente' y se reintenta después.
  4. Imprimir el comprobante con el código QR fiscal exigido por ARCA.
  5. Entornos separados de homologación y producción (configuracion.fiscal_entorno),
     cada uno con su propio certificado.

Credenciales: el certificado y la clave privada se guardan como archivos en la
carpeta de datos del usuario, fuera de la base y de las copias de seguridad, con
la clave privada cifrada para el usuario de Windows (DPAPI). Nunca en el código.
"""
from __future__ import annotations

from dataclasses import dataclass

CONDICIONES_EMISOR = ["", "Responsable inscripto", "Monotributista", "Exento"]
ENTORNOS = {"homologacion": "Homologación (pruebas)", "produccion": "Producción"}


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


def formatear_cuit(cuit: str) -> str:
    d = "".join(c for c in cuit if c.isdigit())
    return f"{d[:2]}-{d[2:10]}-{d[10:]}" if len(d) == 11 else cuit.strip()


def letra_comprobante(condicion_emisor: str, condicion_cliente: str) -> str | None:
    """Letra de factura que corresponde según la condición frente al IVA de quien vende y de quien compra.

    Es una ayuda orientativa: la etapa 7 debe confirmarla contra la normativa vigente.
    """
    if condicion_emisor in ("Monotributista", "Exento"):
        return "C"
    if condicion_emisor == "Responsable inscripto":
        return "A" if condicion_cliente in ("Responsable inscripto", "Monotributista") else "B"
    return None


@dataclass
class EstadoFiscal:
    disponible: bool
    mensaje: str


class ServicioFiscal:
    """Interfaz que usa la aplicación. La etapa 7 la implementa en una subclase."""

    def __init__(self, ctx):
        self.ctx = ctx

    def estado(self) -> EstadoFiscal:
        return EstadoFiscal(
            False,
            "La facturación electrónica todavía no está habilitada en esta versión. "
            "Las ventas se guardan con comprobante interno (ticket no válido como factura).",
        )

    def datos_completos(self) -> list[str]:
        """Devuelve la lista de datos fiscales que faltan para poder facturar."""
        cfg = self.ctx.config
        faltan = []
        if not cfg.obtener("fiscal_razon_social"):
            faltan.append("Razón social")
        if not cuit_valido(cfg.obtener("fiscal_cuit")):
            faltan.append("CUIT válido")
        if not cfg.obtener("fiscal_condicion_iva"):
            faltan.append("Condición frente al IVA")
        if not cfg.obtener("fiscal_domicilio"):
            faltan.append("Domicilio comercial")
        if not cfg.obtener("fiscal_punto_venta").isdigit():
            faltan.append("Punto de venta autorizado")
        return faltan

    def autorizar_venta(self, venta_id: int):
        raise NotImplementedError("La emisión de comprobantes fiscales corresponde a la etapa 7.")

    def emitir_nota_credito(self, venta_id: int):
        raise NotImplementedError("La emisión de notas de crédito corresponde a la etapa 7.")


def crear_servicio(ctx) -> ServicioFiscal:
    return ServicioFiscal(ctx)
