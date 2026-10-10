"""Conversión de datos a JSON y de vuelta, sin perder tipos (importes exactos, tuplas, bytes)."""
from __future__ import annotations

import base64
import dataclasses
import json
import sqlite3
from decimal import Decimal
from pathlib import PurePath


class Objeto(dict):
    """Diccionario con acceso por atributo: así llegan al cliente los resultados que en el servidor son objetos."""

    def __getattr__(self, nombre):
        try:
            return self[nombre]
        except KeyError:
            raise AttributeError(nombre) from None


def _preparar(valor):
    if valor is None or isinstance(valor, (bool, int, float, str)):
        return valor
    if isinstance(valor, Decimal):
        return {"__d": str(valor)}
    if isinstance(valor, bytes):
        return {"__b": base64.b64encode(valor).decode("ascii")}
    if isinstance(valor, sqlite3.Row):
        return {clave: _preparar(valor[clave]) for clave in valor.keys()}
    if dataclasses.is_dataclass(valor) and not isinstance(valor, type):
        return {"__o": {c.name: _preparar(getattr(valor, c.name)) for c in dataclasses.fields(valor)}}
    if isinstance(valor, Objeto):
        return {"__o": {k: _preparar(v) for k, v in valor.items()}}
    if isinstance(valor, dict):
        if all(isinstance(k, str) and not k.startswith("__") for k in valor):
            return {k: _preparar(v) for k, v in valor.items()}
        return {"__m": [[_preparar(k), _preparar(v)] for k, v in valor.items()]}
    if isinstance(valor, tuple):
        return {"__t": [_preparar(v) for v in valor]}
    if isinstance(valor, (list, set)):
        return [_preparar(v) for v in valor]
    if isinstance(valor, PurePath):
        return str(valor)
    raise TypeError(f"No se puede enviar un dato de tipo {type(valor).__name__}")


def _restaurar(valor):
    if isinstance(valor, list):
        return [_restaurar(v) for v in valor]
    if isinstance(valor, dict):
        if len(valor) == 1:
            (marca, contenido), = valor.items()
            if marca == "__d":
                return Decimal(contenido)
            if marca == "__b":
                return base64.b64decode(contenido)
            if marca == "__t":
                return tuple(_restaurar(v) for v in contenido)
            if marca == "__m":
                return {_restaurar(k): _restaurar(v) for k, v in contenido}
            if marca == "__o":
                return Objeto({k: _restaurar(v) for k, v in contenido.items()})
        return {k: _restaurar(v) for k, v in valor.items()}
    return valor


def codificar(valor) -> bytes:
    return json.dumps(_preparar(valor), ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def decodificar(datos: bytes):
    return _restaurar(json.loads(datos.decode("utf-8")))
