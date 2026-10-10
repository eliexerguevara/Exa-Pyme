"""Preferencias de esta computadora (no del comercio): se guardan en un archivo local, fuera de la base.

    modo               "servidor" (esta PC guarda los datos) o "cliente" (se conecta a otra PC)
    red_activa         el servidor acepta conexiones de otras computadoras
    red_puerto         puerto en el que escucha el servidor
    servidor_host      dirección IP del servidor (solo en clientes, si se marcó «Recordar»)
    servidor_puerto    puerto del servidor
    servidor_huella    huella del certificado del servidor en el que se confía
    puesto             nombre de esta computadora como caja (cada una tiene su propia caja diaria)
    impresora, ticket_ancho, ticket_imprimir_automatico   impresión propia de un cliente
"""
from __future__ import annotations

import json
import socket

from .rutas import carpeta_datos

PUERTO_PREDETERMINADO = 8765
PREDETERMINADAS = {
    "modo": "", "red_activa": False, "red_puerto": PUERTO_PREDETERMINADO, "servidor_host": "",
    "servidor_puerto": PUERTO_PREDETERMINADO, "servidor_huella": "", "impresora": "", "ticket_ancho": "80",
    "ticket_imprimir_automatico": "0", "puesto": "",
}


def nombre_equipo() -> str:
    """Nombre que se propone para la caja de una computadora cliente."""
    try:
        return (socket.gethostname() or "Caja")[:40]
    except OSError:
        return "Caja"


def _ruta():
    return carpeta_datos() / "preferencias.json"


def leer() -> dict:
    datos = dict(PREDETERMINADAS)
    try:
        guardadas = json.loads(_ruta().read_text(encoding="utf-8"))
        if isinstance(guardadas, dict):
            datos.update(guardadas)
    except (OSError, ValueError):
        pass
    return datos


def guardar(**valores) -> dict:
    datos = leer()
    datos.update(valores)
    _ruta().write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    return datos
