"""WSFEv1: último comprobante autorizado, solicitud de CAE y consulta de comprobantes."""
from __future__ import annotations

from dataclasses import dataclass, field
from html import escape

from ...core.dinero import de_centavos
from ...core.errores import ErrorNegocio
from .transporte import analizar, buscar, texto, todos

URLS = {
    "homologacion": "https://wswhomo.afip.gov.ar/wsfev1/service.asmx",
    "produccion": "https://servicios1.afip.gov.ar/wsfev1/service.asmx",
}
NS = "http://ar.gov.afip.dif.FEV1/"
CODIGO_TICKET_INVALIDO = "600"
CODIGO_SIN_DATOS = "602"


def importe(centavos: int) -> str:
    return f"{de_centavos(centavos):.2f}"


@dataclass
class Respuesta:
    resultado: str = ""          # A aprobado | R rechazado | P parcial
    cae: str = ""
    cae_vencimiento: str = ""    # AAAAMMDD
    observaciones: list[str] = field(default_factory=list)
    errores: list[str] = field(default_factory=list)
    cruda: str = ""

    @property
    def aprobado(self) -> bool:
        # Solo vale un CAE real: aprobado por ARCA y con sus 14 dígitos.
        return self.resultado == "A" and len(self.cae) == 14 and self.cae.isdigit()

    def motivo(self) -> str:
        return " ".join(self.errores + self.observaciones) or "ARCA no informó el motivo."


def _mensajes(raiz, contenedor: str, item: str) -> tuple[list[str], list[str]]:
    codigos, textos = [], []
    for e in todos(buscar(raiz, contenedor), item):
        codigos.append(texto(e, "Code"))
        textos.append(f"({texto(e, 'Code')}) {texto(e, 'Msg')}")
    return codigos, textos


class Wsfe:
    def __init__(self, entorno: str, cuit: str, obtener_ticket, transporte):
        """obtener_ticket(forzar: bool) -> Ticket ;  transporte(url, accion, cuerpo) -> bytes"""
        self.url, self.cuit = URLS[entorno], cuit
        self.obtener_ticket, self.transporte = obtener_ticket, transporte

    def _llamar(self, operacion: str, contenido: str, con_acceso: bool = True):
        for intento in (1, 2):
            acceso = ""
            if con_acceso:
                t = self.obtener_ticket(intento == 2)
                acceso = f"<Auth><Token>{escape(t.token)}</Token><Sign>{escape(t.sign)}</Sign><Cuit>{self.cuit}</Cuit></Auth>"
            cuerpo = f'<{operacion} xmlns="{NS}">{acceso}{contenido}</{operacion}>'
            cruda = self.transporte(self.url, NS + operacion, cuerpo)
            raiz = analizar(cruda)
            falla = buscar(raiz, "Fault")
            if falla is not None:
                raise ErrorNegocio(f"ARCA devolvió un error: {texto(falla, 'faultstring')}")
            resultado = buscar(raiz, operacion + "Result")
            if resultado is None:
                raise ErrorNegocio("ARCA devolvió una respuesta inesperada.")
            codigos, _ = _mensajes(resultado, "Errors", "Err")
            if con_acceso and intento == 1 and CODIGO_TICKET_INVALIDO in codigos:
                continue  # el ticket guardado ya no sirve: se pide otro y se reintenta una vez
            return resultado, cruda.decode("utf-8", "replace")

    def dummy(self) -> dict:
        """Estado de los servidores de ARCA. No necesita certificado."""
        r, _ = self._llamar("FEDummy", "", con_acceso=False)
        return {n: texto(r, n) for n in ("AppServer", "DbServer", "AuthServer")}

    def ultimo_autorizado(self, punto_venta: int, tipo: int) -> int:
        r, _ = self._llamar("FECompUltimoAutorizado", f"<PtoVta>{punto_venta}</PtoVta><CbteTipo>{tipo}</CbteTipo>")
        _, errores = _mensajes(r, "Errors", "Err")
        if errores:
            raise ErrorNegocio("ARCA no informó el último comprobante: " + " ".join(errores))
        return int(texto(r, "CbteNro", "0") or 0)

    def consultar(self, punto_venta: int, tipo: int, numero: int) -> dict | None:
        """Datos de un comprobante ya autorizado, o None si ARCA no lo tiene."""
        r, _ = self._llamar(
            "FECompConsultar",
            f"<FeCompConsReq><CbteTipo>{tipo}</CbteTipo><CbteNro>{numero}</CbteNro><PtoVta>{punto_venta}</PtoVta></FeCompConsReq>",
        )
        codigos, errores = _mensajes(r, "Errors", "Err")
        datos = buscar(r, "ResultGet")
        if datos is None or not texto(datos, "CodAutorizacion"):
            if errores and CODIGO_SIN_DATOS not in codigos:
                raise ErrorNegocio("ARCA no pudo consultar el comprobante: " + " ".join(errores))
            return None
        return {
            "resultado": texto(datos, "Resultado"), "cae": texto(datos, "CodAutorizacion"),
            "cae_vencimiento": texto(datos, "FchVto"), "fecha": texto(datos, "CbteFch"),
            "total": texto(datos, "ImpTotal"), "doc_nro": texto(datos, "DocNro"), "tipo_emision": texto(datos, "EmisionTipo"),
        }

    @staticmethod
    def armar_detalle(c: dict) -> str:
        """Detalle de FECAESolicitar. El orden de los campos es el del WSDL oficial y no puede cambiarse.

        c: tipo, punto_venta, numero, fecha (AAAAMMDD), doc_tipo, doc_nro, condicion_receptor,
           total_cent, neto_cent, iva_cent, alicuotas [(id, base_cent, importe_cent)],
           asociado {tipo, punto_venta, numero, cuit, fecha} (solo notas de crédito)
        """
        partes = [
            "<Concepto>1</Concepto>",  # productos
            f"<DocTipo>{c['doc_tipo']}</DocTipo><DocNro>{c['doc_nro']}</DocNro>",
            f"<CbteDesde>{c['numero']}</CbteDesde><CbteHasta>{c['numero']}</CbteHasta><CbteFch>{c['fecha']}</CbteFch>",
            f"<ImpTotal>{importe(c['total_cent'])}</ImpTotal><ImpTotConc>0.00</ImpTotConc>",
            f"<ImpNeto>{importe(c['neto_cent'])}</ImpNeto><ImpOpEx>0.00</ImpOpEx><ImpTrib>0.00</ImpTrib>",
            f"<ImpIVA>{importe(c['iva_cent'])}</ImpIVA>",
            "<MonId>PES</MonId><MonCotiz>1</MonCotiz>",
            f"<CondicionIVAReceptorId>{c['condicion_receptor']}</CondicionIVAReceptorId>",
        ]
        a = c.get("asociado")
        if a:
            partes.append(
                f"<CbtesAsoc><CbteAsoc><Tipo>{a['tipo']}</Tipo><PtoVta>{a['punto_venta']}</PtoVta><Nro>{a['numero']}</Nro>"
                f"<Cuit>{a['cuit']}</Cuit><CbteFch>{a['fecha']}</CbteFch></CbteAsoc></CbtesAsoc>")
        if c.get("alicuotas"):
            partes.append("<Iva>" + "".join(
                f"<AlicIva><Id>{i}</Id><BaseImp>{importe(base)}</BaseImp><Importe>{importe(imp)}</Importe></AlicIva>"
                for i, base, imp in c["alicuotas"]) + "</Iva>")
        return "<FECAEDetRequest>" + "".join(partes) + "</FECAEDetRequest>"

    def solicitar_cae(self, c: dict) -> Respuesta:
        contenido = (
            "<FeCAEReq>"
            f"<FeCabReq><CantReg>1</CantReg><PtoVta>{c['punto_venta']}</PtoVta><CbteTipo>{c['tipo']}</CbteTipo></FeCabReq>"
            f"<FeDetReq>{self.armar_detalle(c)}</FeDetReq></FeCAEReq>"
        )
        r, cruda = self._llamar("FECAESolicitar", contenido)
        detalle = buscar(r, "FECAEDetResponse")
        _, errores = _mensajes(r, "Errors", "Err")
        _, observaciones = _mensajes(detalle, "Observaciones", "Obs") if detalle is not None else ([], [])
        return Respuesta(
            resultado=texto(detalle, "Resultado") or texto(buscar(r, "FeCabResp"), "Resultado"),
            cae=texto(detalle, "CAE"), cae_vencimiento=texto(detalle, "CAEFchVto"),
            observaciones=observaciones, errores=errores, cruda=cruda,
        )
