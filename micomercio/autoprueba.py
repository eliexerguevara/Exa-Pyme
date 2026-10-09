"""Autoprueba del programa ya empaquetado:  MiComercio.exe --autoprueba [archivo_resultado]

Trabaja sobre una base de datos temporal (nunca sobre los datos reales), sin
mostrar ventanas: crea un producto, registra una venta, recorre todas las
pantallas y verifica una copia de seguridad. Devuelve 0 si todo funcionó.
Sirve para comprobar que el .exe generado contiene todo lo necesario.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import traceback
import uuid
from decimal import Decimal


def ejecutar(ruta_resultado: str | None = None) -> int:
    temporal = tempfile.mkdtemp(prefix="micomercio_autoprueba_")
    os.environ["MICOMERCIO_DATOS"] = temporal
    codigo, mensaje = 0, "OK"
    db = None
    try:
        from PySide6.QtWidgets import QApplication

        from .db import BaseDatos
        from .rutas import ruta_base_datos
        from .servicios import Contexto, tickets
        from .servicios.copias import validar_copia
        from .ui import tema
        from .ui.ventana import MENU, VentanaPrincipal

        app = QApplication.instance() or QApplication(sys.argv[:1])
        app.setStyleSheet(tema.HOJA_DE_ESTILO)
        db = BaseDatos(ruta_base_datos())
        ctx = Contexto(db)
        ctx.usuarios.crear("admin", "Autoprueba", uuid.uuid4().hex)
        ctx.usuario = dict(ctx.db.uno("SELECT id, usuario, nombre, rol FROM usuarios"))
        producto = ctx.productos.crear({
            "nombre": "Producto de prueba", "codigo_barras": "7790000000017", "costo": Decimal("10000"),
            "impuesto_pct": Decimal("21"), "ganancia_pct": Decimal("30"), "stock": Decimal("5"),
        })
        p = ctx.productos.obtener(producto)
        assert p["precio_final_cent"] == 1728571, "el cálculo de precios no dio el resultado esperado"
        ctx.caja.abrir(0)
        venta = ctx.ventas.registrar(
            str(uuid.uuid4()), [{"producto_id": producto, "cantidad": Decimal(1), "precio_unit_cent": p["precio_final_cent"]}],
            [{"medio": "efectivo", "monto_cent": p["precio_final_cent"]}],
        )
        assert ctx.productos.obtener(producto)["stock_mil"] == 4000, "la venta no descontó el stock"
        assert "DOCUMENTO NO VÁLIDO COMO FACTURA" in tickets.html_ticket(ctx, venta)

        ventana = VentanaPrincipal(ctx)  # no se muestra
        ventana.reloj_copias.stop()
        assert len(ventana.paginas) == len(MENU), "faltan pantallas del menú"
        for clave in ventana.paginas:
            ventana.ir(clave)
        assert validar_copia(ctx.copias.crear())["ventas"] == 1, "la copia de seguridad no es válida"
        ventana.close()
    except BaseException:
        codigo, mensaje = 1, traceback.format_exc()
    finally:
        if db is not None:
            db.cerrar()
        shutil.rmtree(temporal, ignore_errors=True)
    if ruta_resultado:
        with open(ruta_resultado, "w", encoding="utf-8") as archivo:
            archivo.write(mensaje)
    return codigo
