"""Cálculo automático de precios.

Nombres de los campos, tal como los ve el usuario:
    Precio Costo                    lo que le cuesta al comercio el producto
    Impuestos                       porcentaje de impuesto del producto
    Porcentaje de ganancia          margen o recargo, según el método
    Precio de venta sin impuestos   precio antes de impuestos
    Precio de venta final           lo que paga el cliente

Método "margen" (predeterminado): la ganancia es un porcentaje del precio de
venta sin impuestos.
    Precio de venta sin impuestos = Precio Costo / (1 - ganancia / 100)

Método "recargo": la ganancia es un porcentaje que se suma al costo.
    Precio de venta sin impuestos = Precio Costo × (1 + ganancia / 100)

En ambos casos:
    Precio de venta final = Precio de venta sin impuestos × (1 + Impuestos / 100)
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .dinero import D, redondear
from .errores import ErrorNegocio

METODO_MARGEN = "margen"
METODO_RECARGO = "recargo"
METODOS = {
    METODO_MARGEN: "Margen sobre el precio de venta",
    METODO_RECARGO: "Recargo sobre el costo",
}
IMPUESTOS_HABITUALES = ["0", "10.5", "21", "27"]

CIEN = Decimal(100)


@dataclass(frozen=True)
class Precio:
    sin_impuestos: Decimal
    final: Decimal

    @property
    def impuestos(self) -> Decimal:
        return self.final - self.sin_impuestos


def validar(costo: Decimal, impuesto_pct: Decimal, ganancia_pct: Decimal | None, metodo: str) -> None:
    if metodo not in METODOS:
        raise ErrorNegocio("El método de cálculo de precio no es válido.")
    if costo < 0:
        raise ErrorNegocio("El Precio Costo no puede ser negativo.")
    if impuesto_pct < 0:
        raise ErrorNegocio("Los Impuestos no pueden ser negativos.")
    if ganancia_pct is None:
        return
    if metodo == METODO_MARGEN and ganancia_pct >= 100:
        raise ErrorNegocio(
            "El Porcentaje de ganancia debe ser menor a 100 cuando se calcula como margen "
            "sobre el precio de venta. Si querés sumar un porcentaje al costo, elegí el "
            "método «Recargo sobre el costo»."
        )
    if metodo == METODO_RECARGO and ganancia_pct <= -100:
        raise ErrorNegocio("El Porcentaje de ganancia no puede ser -100 % o menos.")


def calcular_precio(costo, impuesto_pct, ganancia_pct, metodo: str = METODO_MARGEN) -> Precio:
    costo, impuesto_pct, ganancia_pct = D(costo), D(impuesto_pct), D(ganancia_pct)
    validar(costo, impuesto_pct, ganancia_pct, metodo)
    if metodo == METODO_MARGEN:
        neto = costo / (1 - ganancia_pct / CIEN)
    else:
        neto = costo * (1 + ganancia_pct / CIEN)
    final = neto * (1 + impuesto_pct / CIEN)
    return Precio(redondear(neto), redondear(final))


def sin_impuestos_desde_final(final, impuesto_pct) -> Decimal:
    return redondear(D(final) / (1 + D(impuesto_pct) / CIEN))


def ganancia_desde_final(costo, impuesto_pct, final, metodo: str = METODO_MARGEN) -> Decimal:
    """Porcentaje de ganancia que resulta de un Precio de venta final dado."""
    costo, impuesto_pct, final = D(costo), D(impuesto_pct), D(final)
    validar(costo, impuesto_pct, None, metodo)
    if final < 0:
        raise ErrorNegocio("El Precio de venta final no puede ser negativo.")
    neto = final / (1 + impuesto_pct / CIEN)
    base = neto if metodo == METODO_MARGEN else costo
    if base == 0:
        return Decimal("0.00")
    return redondear((neto - costo) / base * CIEN)


def desglosar_centavos(total_cent: int, impuesto_pct) -> tuple[int, int]:
    """Separa un importe final (con impuestos) en (sin impuestos, impuestos), en centavos."""
    neto = int(redondear(Decimal(total_cent) / (1 + D(impuesto_pct) / CIEN), 0))
    return neto, total_cent - neto


def redondear_a_multiplo(valor, multiplo) -> Decimal:
    """Redondea un precio al múltiplo indicado (por ejemplo $ 10 o $ 100)."""
    valor, multiplo = D(valor), D(multiplo)
    if multiplo <= 0:
        return redondear(valor)
    return redondear(redondear(valor / multiplo, 0) * multiplo)
