from __future__ import annotations

from datetime import date, datetime, timedelta

FORMATO_FECHA_HORA = "%Y-%m-%d %H:%M:%S"


def ahora() -> str:
    return datetime.now().strftime(FORMATO_FECHA_HORA)


def hoy() -> str:
    return date.today().isoformat()


def rango_dias(desde: str, hasta: str) -> tuple[str, str]:
    """Convierte dos fechas (inclusive) en límites [inicio, fin) de fecha y hora."""
    fin = date.fromisoformat(hasta) + timedelta(days=1)
    return f"{desde} 00:00:00", f"{fin.isoformat()} 00:00:00"


def fecha_legible(texto: str | None) -> str:
    """'2026-10-09 14:05:33' -> '09/10/2026 14:05'"""
    if not texto:
        return ""
    try:
        if len(texto) <= 10:
            return date.fromisoformat(texto).strftime("%d/%m/%Y")
        return datetime.strptime(texto[:19], FORMATO_FECHA_HORA).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return texto
