"""Conversión, redondeo y formato de importes, cantidades y porcentajes.

Los importes se guardan como enteros en centavos y las cantidades como enteros
en milésimas, para que las sumas de la base de datos sean exactas. Todos los
cálculos intermedios usan Decimal y redondeo comercial (mitad hacia arriba).
"""
from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENTAVO = Decimal("0.01")
UNO = Decimal(1)


def D(valor) -> Decimal:
    if isinstance(valor, Decimal):
        return valor
    return Decimal(str(valor))


def redondear(valor, decimales: int = 2) -> Decimal:
    return D(valor).quantize(Decimal(1).scaleb(-decimales), rounding=ROUND_HALF_UP)


def a_centavos(valor) -> int:
    return int((D(valor) * 100).quantize(UNO, rounding=ROUND_HALF_UP))


def de_centavos(centavos: int) -> Decimal:
    return Decimal(int(centavos)) / 100


def a_milesimas(cantidad) -> int:
    return int((D(cantidad) * 1000).quantize(UNO, rounding=ROUND_HALF_UP))


def de_milesimas(milesimas: int) -> Decimal:
    return Decimal(int(milesimas)) / 1000


def importe_linea(precio_unit_cent: int, cantidad_mil: int) -> int:
    """Importe en centavos de una línea: precio unitario × cantidad."""
    return int((Decimal(precio_unit_cent) * Decimal(cantidad_mil) / 1000).quantize(UNO, rounding=ROUND_HALF_UP))


def parse_decimal(texto, punto_miles: bool = False) -> Decimal:
    """Interpreta un número escrito por el usuario ("1.250,50", "1250.5", "$ 300").

    Con punto_miles=True, un único punto seguido de exactamente tres dígitos se
    toma como separador de miles ("1.500" = mil quinientos), que es la forma
    habitual de escribir importes en Argentina.
    """
    if isinstance(texto, (int, Decimal)):
        return D(texto)
    s = str(texto).strip().replace("$", "").replace("%", "").replace(" ", "").replace(" ", "")
    if not s:
        raise ValueError("vacío")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    elif punto_miles and re.fullmatch(r"-?\d{1,3}\.\d{3}", s):
        s = s.replace(".", "")
    try:
        valor = Decimal(s)
    except InvalidOperation:
        raise ValueError(f"número inválido: {texto!r}") from None
    if not valor.is_finite():
        raise ValueError(f"número inválido: {texto!r}")
    return valor


def _miles(entero: int) -> str:
    return f"{entero:,}".replace(",", ".")


def fmt_numero(valor, decimales: int = 2) -> str:
    v = redondear(valor, decimales)
    signo = "-" if v < 0 else ""
    v = abs(v)
    entero = int(v)
    if decimales == 0:
        return f"{signo}{_miles(entero)}"
    frac = str(v).split(".")[1]
    return f"{signo}{_miles(entero)},{frac}"


def fmt_dinero(centavos: int | None) -> str:
    if centavos is None:
        return ""
    return "$ " + fmt_numero(de_centavos(centavos), 2)


def fmt_cantidad(milesimas: int | None) -> str:
    """Cantidad sin ceros sobrantes: 2 · 1,5 · 0,25"""
    if milesimas is None:
        return ""
    v = de_milesimas(milesimas)
    texto = fmt_numero(v, 3)
    return texto.rstrip("0").rstrip(",") if "," in texto else texto


def fmt_pct(valor) -> str:
    texto = fmt_numero(D(valor), 2)
    return texto.rstrip("0").rstrip(",") if "," in texto else texto


def decimal_csv(valor, decimales: int = 2) -> str:
    """Número para CSV de Excel en español: coma decimal y sin separador de miles."""
    return str(redondear(valor, decimales)).replace(".", ",")
