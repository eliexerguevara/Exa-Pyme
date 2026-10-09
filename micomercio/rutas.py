"""Carpetas persistentes del usuario. Nada se guarda junto al ejecutable ni en temporales."""
from __future__ import annotations

import os
from pathlib import Path

CARPETA = "ExaPyme"
# El programa se llamaba MiComercio: si existen datos con ese nombre, se conservan.
CARPETA_ANTERIOR = "MiComercio"


def carpeta_datos() -> Path:
    """%LOCALAPPDATA%\\ExaPyme (se puede cambiar con la variable EXAPYME_DATOS)."""
    forzada = os.environ.get("EXAPYME_DATOS") or os.environ.get("MICOMERCIO_DATOS")
    if forzada:
        base = Path(forzada)
    else:
        local = Path(os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local"))
        base, anterior = local / CARPETA, local / CARPETA_ANTERIOR
        if not base.exists() and anterior.exists():
            try:
                anterior.rename(base)  # mismo disco: es un cambio de nombre, no una copia
            except OSError:
                base = anterior  # en uso en este momento: se sigue trabajando ahí y se renombra en otro arranque
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
