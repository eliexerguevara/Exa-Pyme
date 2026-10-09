"""Registros técnicos para diagnóstico (archivo rotativo en la carpeta de datos)."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from .rutas import carpeta_registros

log = logging.getLogger("micomercio")


def configurar_registro() -> None:
    if log.handlers:
        return
    log.setLevel(logging.INFO)
    archivo = RotatingFileHandler(
        carpeta_registros() / "micomercio.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    archivo.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    log.addHandler(archivo)
