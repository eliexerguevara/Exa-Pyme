"""WSAA: obtención del ticket de acceso (token y sign) para usar WSFEv1."""
from __future__ import annotations

import base64
import json
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ...core.errores import ErrorNegocio
from ...registro import log
from . import credenciales
from .transporte import analizar, buscar, texto

URLS = {
    "homologacion": "https://wsaahomo.afip.gov.ar/ws/services/LoginCms",
    "produccion": "https://wsaa.afip.gov.ar/ws/services/LoginCms",
}
SERVICIO = "wsfe"

# Explicación en lenguaje llano de los rechazos más comunes de WSAA
ERRORES = {
    "cms.cert.untrusted": "ARCA no reconoce el certificado. Revisá que sea el certificado del entorno elegido "
                          "(homologación y producción usan certificados distintos).",
    "cms.cert.expired": "El certificado de ARCA está vencido. Hay que generar uno nuevo.",
    "cms.cert.invalid": "El certificado de ARCA no es válido.",
    "cms.sign.invalid": "ARCA no aceptó la firma. El certificado no coincide con la clave privada.",
    "coe.notAuthorized": "El certificado no está autorizado a usar la facturación electrónica. En el sitio de ARCA "
                         "hay que asociar el servicio «Facturación Electrónica» (wsfe) al certificado.",
    "coe.alreadyAuthenticated": "ARCA ya entregó un ticket de acceso hace instantes. Esperá unos minutos y volvé a intentar.",
    "xml.generationTime.invalid": "La fecha y hora de esta computadora no son correctas. Ajustá el reloj de Windows.",
    "xml.expirationTime.invalid": "La fecha y hora de esta computadora no son correctas. Ajustá el reloj de Windows.",
}


@dataclass
class Ticket:
    token: str
    sign: str
    vence: datetime

    def vigente(self) -> bool:
        return self.vence - datetime.now(timezone.utc) > timedelta(minutes=5)


def crear_pedido(ahora: datetime | None = None) -> bytes:
    """Ticket de requerimiento de acceso (TRA)."""
    ahora = (ahora or datetime.now()).astimezone().replace(microsecond=0)
    return (
        '<?xml version="1.0" encoding="UTF-8"?><loginTicketRequest version="1.0"><header>'
        f"<uniqueId>{random.randint(1, 2_000_000_000)}</uniqueId>"
        f"<generationTime>{(ahora - timedelta(minutes=10)).isoformat()}</generationTime>"
        f"<expirationTime>{(ahora + timedelta(minutes=10)).isoformat()}</expirationTime>"
        f"</header><service>{SERVICIO}</service></loginTicketRequest>"
    ).encode("utf-8")


def interpretar(respuesta: bytes) -> Ticket:
    raiz = analizar(respuesta)
    falla = buscar(raiz, "Fault")
    if falla is not None:
        codigo, detalle = texto(falla, "faultcode").split(":")[-1], texto(falla, "faultstring")
        log.warning("WSAA rechazó el acceso: %s %s", codigo, detalle)
        raise ErrorNegocio(ERRORES.get(codigo, f"ARCA rechazó el acceso: {detalle or codigo}"))
    contenido = texto(raiz, "loginCmsReturn")
    if not contenido:
        raise ErrorNegocio("ARCA no devolvió el ticket de acceso.")
    ticket = analizar(contenido.encode("utf-8"))
    token, sign, vence = texto(ticket, "token"), texto(ticket, "sign"), texto(ticket, "expirationTime")
    if not token or not sign or not vence:
        raise ErrorNegocio("ARCA devolvió un ticket de acceso incompleto.")
    return Ticket(token, sign, datetime.fromisoformat(vence).astimezone(timezone.utc))


def _leer_guardado(entorno: str) -> Ticket | None:
    ruta = credenciales.carpeta(entorno) / "ticket.dpapi"
    if not ruta.exists():
        return None
    try:
        d = json.loads(credenciales.desproteger(ruta.read_bytes()))
        return Ticket(d["token"], d["sign"], datetime.fromisoformat(d["vence"]))
    except (ErrorNegocio, ValueError, KeyError):
        return None


def obtener_ticket(entorno: str, transporte, forzar: bool = False) -> Ticket:
    """Devuelve un ticket vigente. Se reutiliza el guardado: ARCA no entrega otro mientras haya uno válido."""
    if not forzar:
        guardado = _leer_guardado(entorno)
        if guardado and guardado.vigente():
            return guardado
    certificado, clave = credenciales.cargar(entorno)
    cms = base64.b64encode(credenciales.firmar_cms(crear_pedido(), certificado, clave)).decode("ascii")
    cuerpo = (f'<wsaa:loginCms xmlns:wsaa="http://wsaa.view.sua.dvadac.desein.afip.gov"><wsaa:in0>{cms}</wsaa:in0>'
              "</wsaa:loginCms>")
    ticket = interpretar(transporte(URLS[entorno], "", cuerpo))
    datos = json.dumps({"token": ticket.token, "sign": ticket.sign, "vence": ticket.vence.isoformat()}).encode()
    (credenciales.carpeta(entorno) / "ticket.dpapi").write_bytes(credenciales.proteger(datos))
    return ticket
