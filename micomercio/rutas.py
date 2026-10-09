"""Carpetas persistentes del usuario. Nada se guarda junto al ejecutable ni en temporales."""
from __future__ import annotations

import os
from pathlib import Path

from . import NOMBRE_APP


def carpeta_datos() -> Path:
    """%LOCALAPPDATA%\\MiComercio (se puede cambiar con la variable MICOMERCIO_DATOS)."""
    forzada = os.environ.get("MICOMERCIO_DATOS")
    if forzada:
        base = Path(forzada)
    else:
        local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        base = Path(local) / NOMBRE_APP
    base.mkdir(parents=True, exist_ok=True)
    return base


def ruta_base_datos() -> Path:
    return carpeta_datos() / "micomercio.db"


def carpeta_copias_predeterminada() -> Path:
    ruta = carpeta_datos() / "copias"
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


def carpeta_registros() -> Path:
    ruta = carpeta_datos() / "registros"
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta
