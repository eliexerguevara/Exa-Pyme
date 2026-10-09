"""Envío de mensajes SOAP a los servidores de ARCA."""
from __future__ import annotations

import ssl
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

from ...core.errores import ErrorNegocio


class ErrorConexion(ErrorNegocio):
    """No hubo respuesta de ARCA (sin Internet, servidor caído o tiempo agotado).
    No se sabe si el pedido llegó: el comprobante queda pendiente y se verifica al reintentar."""


def _contexto_compatible() -> ssl.SSLContext:
    # Algunos servidores de ARCA negocian parámetros que OpenSSL 3 rechaza por defecto
    # («DH key too small»). Se baja solo ese nivel; el certificado del servidor se sigue verificando.
    contexto = ssl.create_default_context()
    contexto.set_ciphers("DEFAULT@SECLEVEL=1")
    return contexto


def enviar(url: str, accion: str, cuerpo: str, tiempo: int = 25) -> bytes:
    """Envía el contenido dentro de un sobre SOAP 1.1 y devuelve la respuesta (también si es un fault)."""
    sobre = ('<?xml version="1.0" encoding="UTF-8"?>'
             '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/">'
             f"<soapenv:Header/><soapenv:Body>{cuerpo}</soapenv:Body></soapenv:Envelope>").encode("utf-8")
    cabeceras = {"Content-Type": "text/xml; charset=utf-8", "SOAPAction": f'"{accion}"', "User-Agent": "MiComercio"}
    for contexto in (None, _contexto_compatible()):
        try:
            pedido = urllib.request.Request(url, data=sobre, headers=cabeceras)
            with urllib.request.urlopen(pedido, timeout=tiempo, context=contexto) as respuesta:
                return respuesta.read()
        except urllib.error.HTTPError as e:  # los errores SOAP llegan con código 500 y un cuerpo útil
            contenido = e.read()
            if contenido.lstrip().startswith(b"<"):
                return contenido
            raise ErrorConexion(f"ARCA respondió con un error ({e.code}). Probá de nuevo en unos minutos.") from None
        except urllib.error.URLError as e:
            if contexto is None and "DH_KEY_TOO_SMALL" in str(e.reason):
                continue
            raise ErrorConexion("No se pudo conectar con ARCA. Revisá la conexión a Internet.") from None
        except OSError:
            raise ErrorConexion("ARCA no respondió a tiempo.") from None
    raise ErrorConexion("No se pudo establecer una conexión segura con ARCA.")


def analizar(contenido: bytes) -> ET.Element:
    try:
        return ET.fromstring(contenido)
    except ET.ParseError:
        raise ErrorConexion("ARCA devolvió una respuesta que no se pudo interpretar.") from None


def local(elemento: ET.Element) -> str:
    return elemento.tag.rsplit("}", 1)[-1]


def buscar(raiz: ET.Element, nombre: str) -> ET.Element | None:
    """Primer elemento con ese nombre, sin importar el espacio de nombres."""
    for e in raiz.iter():
        if local(e) == nombre:
            return e
    return None


def texto(raiz: ET.Element | None, nombre: str, defecto: str = "") -> str:
    if raiz is None:
        return defecto
    e = buscar(raiz, nombre)
    return (e.text or "").strip() if e is not None else defecto


def todos(raiz: ET.Element | None, nombre: str) -> list[ET.Element]:
    return [e for e in raiz.iter() if local(e) == nombre] if raiz is not None else []
