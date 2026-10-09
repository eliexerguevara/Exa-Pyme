from decimal import Decimal as D

import pytest

from micomercio.core import precios
from micomercio.core.dinero import fmt_cantidad, fmt_dinero, parse_decimal
from micomercio.core.errores import ErrorNegocio


def test_ejemplo_del_enunciado():
    p = precios.calcular_precio(D("10000"), D("21"), D("30"))
    assert p.sin_impuestos == D("14285.71")
    assert p.final == D("17285.71")


def test_margen_no_es_recargo():
    margen = precios.calcular_precio(D("10000"), D("21"), D("30"), precios.METODO_MARGEN)
    recargo = precios.calcular_precio(D("10000"), D("21"), D("30"), precios.METODO_RECARGO)
    assert recargo.sin_impuestos == D("13000.00")
    assert recargo.final == D("15730.00")
    assert margen.final > recargo.final


@pytest.mark.parametrize("impuesto,final", [("0", "14285.71"), ("10.5", "15785.71"), ("21", "17285.71"), ("27", "18142.86"), ("3.5", "14785.71")])
def test_impuestos(impuesto, final):
    assert precios.calcular_precio(D("10000"), D(impuesto), D("30")).final == D(final)


def test_margen_100_es_invalido():
    with pytest.raises(ErrorNegocio):
        precios.calcular_precio(D("100"), D("21"), D("100"))
    assert precios.calcular_precio(D("100"), D("21"), D("100"), precios.METODO_RECARGO).sin_impuestos == D("200.00")


def test_valores_negativos():
    with pytest.raises(ErrorNegocio):
        precios.calcular_precio(D("-1"), D("21"), D("30"))
    with pytest.raises(ErrorNegocio):
        precios.calcular_precio(D("1"), D("-21"), D("30"))


def test_ganancia_resultante_de_un_precio_manual():
    assert precios.ganancia_desde_final(D("10000"), D("21"), D("17285.71")) == D("30.00")
    assert precios.ganancia_desde_final(D("10000"), D("21"), D("15730"), precios.METODO_RECARGO) == D("30.00")
    # vender por debajo del costo da ganancia negativa
    assert precios.ganancia_desde_final(D("10000"), D("21"), D("9680")) == D("-25.00")
    assert precios.ganancia_desde_final(D("0"), D("21"), D("0")) == D("0.00")


def test_redondeo_mitad_hacia_arriba():
    assert precios.calcular_precio(D("0.335"), D("0"), D("0")).final == D("0.34")
    assert precios.redondear_a_multiplo(D("17285.71"), 100) == D("17300.00")
    assert precios.redondear_a_multiplo(D("17250"), 100) == D("17300.00")
    assert precios.redondear_a_multiplo(D("17249.99"), 100) == D("17200.00")


def test_desglose_suma_exacta():
    for total in (1728571, 100, 1, 999, 12345):
        neto, imp = precios.desglosar_centavos(total, "21")
        assert neto + imp == total
    assert precios.desglosar_centavos(12100, "21") == (10000, 2100)


def test_parse_y_formato():
    assert parse_decimal("1.250,50") == D("1250.50")
    assert parse_decimal("$ 17.285,71") == D("17285.71")
    assert parse_decimal("1250.5") == D("1250.5")
    assert parse_decimal("1.500", punto_miles=True) == D("1500")
    assert parse_decimal("1.500") == D("1.500")
    assert parse_decimal("10,5 %") == D("10.5")
    with pytest.raises(ValueError):
        parse_decimal("abc")
    assert fmt_dinero(1728571) == "$ 17.285,71"
    assert fmt_dinero(-50) == "$ -0,50"
    assert fmt_cantidad(1500) == "1,5"
    assert fmt_cantidad(2000) == "2"
    assert fmt_cantidad(1000000) == "1.000"
