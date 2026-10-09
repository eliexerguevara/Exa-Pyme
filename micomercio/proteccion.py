"""Cifrado de secretos con DPAPI de Windows.

Lo que se cifra acá (clave privada de ARCA, credencial de Mercado Pago) solo puede
descifrarlo el mismo usuario de Windows en la misma computadora. Nunca se guarda en
el código, en la base de datos ni en las copias de seguridad.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt

from .core.errores import ErrorNegocio


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(funcion, datos: bytes) -> bytes:
    entrada = _Blob(len(datos), ctypes.cast(ctypes.create_string_buffer(datos, len(datos)), ctypes.POINTER(ctypes.c_char)))
    salida = _Blob()
    if not funcion(ctypes.byref(entrada), None, None, None, None, 0, ctypes.byref(salida)):
        raise ErrorNegocio(
            "No se pudo acceder a un dato protegido. Solo puede usarlo el mismo usuario de Windows "
            "que lo guardó, en esta misma computadora."
        )
    try:
        return ctypes.string_at(salida.pbData, salida.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(salida.pbData)


def proteger(datos: bytes) -> bytes:
    return _dpapi(ctypes.windll.crypt32.CryptProtectData, datos)


def desproteger(datos: bytes) -> bytes:
    return _dpapi(ctypes.windll.crypt32.CryptUnprotectData, datos)
