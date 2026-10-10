"""Catálogo de imágenes de productos: una imagen por código de barras (7790001000012.jpg).

El catálogo es una carpeta de la computadora principal (ver Productos.imagen_de_catalogo). Este módulo define
con qué nombres puede estar guardada una imagen y, además, sabe buscar en un catálogo publicado en Internet.
Esa búsqueda en línea está desactivada (configuración «catalogo_en_linea»): las imágenes no están publicadas.
"""
from __future__ import annotations

import re
import urllib.error
import urllib.request

from .. import __version__
from ..core.errores import ErrorNegocio

URL_BASE = "https://raw.githubusercontent.com/eliexerguevara/Exa-Pyme/main/imagenes-productos/"
TAMANO_MAXIMO = 2 * 1024 * 1024


class SinConexion(ErrorNegocio):
    """No se pudo consultar el catálogo (sin Internet)."""


def candidatos(codigo_barras: str) -> list[str]:
    """Nombres con los que puede estar guardada la imagen de un código de barras.

    Un mismo producto puede estar escrito con o sin ceros adelante (EAN-13, UPC de 12 dígitos, EAN-8).
    """
    codigo = (codigo_barras or "").strip()
    if not re.fullmatch(r"[0-9A-Za-z_-]{4,32}", codigo):
        return []
    variantes = [codigo]
    if codigo.isdigit():
        sin_ceros = codigo.lstrip("0")
        variantes += [sin_ceros, sin_ceros.zfill(13), sin_ceros.zfill(12), sin_ceros.zfill(8), sin_ceros.zfill(14)]
    vistos, resultado = set(), []
    for v in variantes:
        if len(v) >= 4 and v not in vistos:
            vistos.add(v)
            resultado.append(v)
    return resultado


def _obtener(url: str) -> bytes | None:
    """Contenido de la dirección, o None si no existe."""
    try:
        pedido = urllib.request.Request(url, headers={"User-Agent": f"ExaPyme/{__version__}"})
        with urllib.request.urlopen(pedido, timeout=8) as respuesta:
            datos = respuesta.read(TAMANO_MAXIMO + 1)
            return datos if len(datos) <= TAMANO_MAXIMO else None
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise SinConexion("El catálogo de imágenes no está disponible en este momento.") from None
    except OSError:
        raise SinConexion("No se pudo consultar el catálogo de imágenes. Revisá la conexión a Internet.") from None


def buscar(codigo_barras: str, obtener=_obtener) -> bytes | None:
    """Imagen del catálogo para ese código de barras, o None si no hay ninguna."""
    for nombre in candidatos(codigo_barras):
        datos = obtener(f"{URL_BASE}{nombre}.jpg")
        if datos and datos[:3] == b"\xff\xd8\xff":  # es un JPEG de verdad
            return datos
    return None
