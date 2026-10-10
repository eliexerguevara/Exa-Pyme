"""Importación y exportación en CSV compatible con Excel en español
(separador punto y coma, coma decimal, UTF-8 con BOM)."""
from __future__ import annotations

import csv
from pathlib import Path

from ..core.dinero import D, decimal_csv, de_centavos, de_milesimas, parse_decimal
from ..core.errores import ErrorNegocio
from ..core.precios import METODOS
from .reportes import Reporte, formatear

COLUMNAS_PRODUCTO = [
    "Código interno", "Código de barras", "Nombre del producto", "Descripción", "Categoría", "Marca", "Proveedor",
    "Precio Costo", "Impuestos", "Porcentaje de ganancia", "Método de cálculo", "Precio de venta sin impuestos",
    "Precio de venta final", "Precio manual", "Cantidad disponible", "Stock mínimo", "Unidad de medida",
    "Fecha de alta", "Estado",
]


def escribir_csv(ruta: str | Path, encabezados: list[str], filas: list[list]) -> None:
    try:
        with open(ruta, "w", newline="", encoding="utf-8-sig") as archivo:
            escritor = csv.writer(archivo, delimiter=";")
            escritor.writerow(encabezados)
            escritor.writerows(filas)
    except PermissionError:
        raise ErrorNegocio(
            "No se pudo guardar el archivo. Si está abierto en Excel, cerralo y volvé a intentar."
        ) from None
    except OSError as e:
        raise ErrorNegocio(f"No se pudo guardar el archivo.\n{e}") from None


def exportar_reporte(reporte: Reporte, ruta: str | Path) -> None:
    filas = [[formatear(v, tipo, para_csv=True) for v, (_, tipo) in zip(fila, reporte.columnas)] for fila in reporte.filas]
    escribir_csv(ruta, [titulo for titulo, _ in reporte.columnas], filas)


def exportar_productos(ctx, ruta: str | Path) -> int:
    filas = []
    for p in ctx.productos.buscar(solo_activos=False, limite=1_000_000):
        filas.append([
            p["codigo"], p["codigo_barras"], p["nombre"], p["descripcion"], p["categoria"], p["marca"], p["proveedor"],
            decimal_csv(de_centavos(p["costo_cent"])), decimal_csv(D(p["impuesto_pct"])), decimal_csv(D(p["ganancia_pct"])),
            p["metodo_precio"], decimal_csv(de_centavos(p["precio_neto_cent"])),
            decimal_csv(de_centavos(p["precio_final_cent"])), "Sí" if p["precio_manual"] else "No",
            decimal_csv(de_milesimas(p["stock_mil"]), 3), decimal_csv(de_milesimas(p["stock_minimo_mil"]), 3),
            p["unidad"], p["fecha_alta"], "Activo" if p["activo"] else "Inactivo",
        ])
    escribir_csv(ruta, COLUMNAS_PRODUCTO, filas)
    return len(filas)


def leer_archivo(ruta: str | Path) -> str:
    try:
        datos = Path(ruta).read_bytes()
    except OSError:
        raise ErrorNegocio("No se pudo abrir el archivo.") from None
    for codificacion in ("utf-8-sig", "cp1252"):
        try:
            texto = datos.decode(codificacion)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ErrorNegocio("No se pudo leer el archivo: guardalo desde Excel como «CSV UTF-8».")
    return texto


def _filas(texto: str) -> list[dict]:
    primera = texto.split("\n", 1)[0]
    delimitador = max(";,\t", key=primera.count)
    lector = csv.DictReader(texto.splitlines(), delimiter=delimitador)
    if not lector.fieldnames:
        raise ErrorNegocio("El archivo está vacío.")
    return [{(k or "").strip().lower(): (v or "").strip() for k, v in fila.items()} for fila in lector]


def importar_productos(ctx, ruta: str | Path) -> dict:
    """Importa desde un archivo de esta computadora. En un cliente, el contenido se envía al servidor."""
    texto = leer_archivo(ruta)
    if getattr(ctx, "remoto", False):
        return ctx.sistema.importar_productos(texto)
    return importar_productos_texto(ctx, texto)


def importar_productos_texto(ctx, texto: str) -> dict:
    """Crea o actualiza productos desde un CSV con las mismas columnas que la exportación.

    Un producto existente se reconoce por su código interno o su código de barras.
    Solo «Nombre del producto» es obligatoria. Si el archivo trae «Cantidad
    disponible», la diferencia con el stock actual se registra como ajuste de
    inventario, para no perder la trazabilidad.
    Las filas con errores se informan y no se importan; el resto sí.
    """
    ctx.requiere("productos_editar")
    filas = _filas(texto)
    if filas and "nombre del producto" not in filas[0] and "nombre" not in filas[0]:
        raise ErrorNegocio(
            "El archivo no tiene la columna «Nombre del producto». Exportá primero los productos "
            "para usar ese archivo como modelo."
        )
    proveedores = {p["nombre"].lower(): p["id"] for p in ctx.compras.proveedores(solo_activos=False)}
    resultado = {"creados": 0, "actualizados": 0, "errores": []}

    def numero(fila, columna, defecto, dinero=False):
        texto = fila.get(columna, "")
        if texto == "":
            return defecto
        try:
            return parse_decimal(texto, punto_miles=dinero)
        except ValueError:
            raise ErrorNegocio(f"el valor «{texto}» de la columna «{columna}» no es un número") from None

    for n, fila in enumerate(filas, start=2):
        if not any(fila.values()):
            continue
        try:
            with ctx.db.transaccion():
                codigo, barras = fila.get("código interno", ""), fila.get("código de barras", "")
                existente = None
                if codigo:
                    existente = ctx.db.uno("SELECT * FROM productos WHERE codigo = ?", (codigo,))
                if existente is None and barras:
                    existente = ctx.db.uno("SELECT * FROM productos WHERE codigo_barras = ?", (barras,))
                base = ctx.productos.obtener(existente["id"]) if existente else None

                metodo = fila.get("método de cálculo", "").lower() or (base["metodo_precio"] if base else "")
                if metodo and metodo not in METODOS:
                    raise ErrorNegocio("el «Método de cálculo» debe ser «margen» o «recargo»")
                proveedor_id = base["proveedor_id"] if base else None
                nombre_proveedor = fila.get("proveedor", "")
                if nombre_proveedor:
                    proveedor_id = proveedores.get(nombre_proveedor.lower())
                    if proveedor_id is None:
                        proveedor_id = ctx.compras.guardar_proveedor({"nombre": nombre_proveedor})
                        proveedores[nombre_proveedor.lower()] = proveedor_id

                final = numero(fila, "precio de venta final", None, dinero=True)
                manual = fila.get("precio manual", "").lower() in ("sí", "si", "1", "x")
                tiene_ganancia = fila.get("porcentaje de ganancia", "") != ""
                if final is None and base is not None and base["precio_manual"] and not tiene_ganancia:
                    final = de_centavos(base["precio_final_cent"])
                datos = {
                    "codigo": codigo or (base["codigo"] if base else ""),
                    "codigo_barras": barras or (base["codigo_barras"] if base else ""),
                    "nombre": fila.get("nombre del producto") or fila.get("nombre", ""),
                    "descripcion": fila.get("descripción", base["descripcion"] if base else ""),
                    "categoria": fila.get("categoría", base["categoria"] if base else ""),
                    "marca": fila.get("marca", base["marca"] if base else ""),
                    "proveedor_id": proveedor_id,
                    "costo": numero(fila, "precio costo", de_centavos(base["costo_cent"]) if base else 0, dinero=True),
                    "impuesto_pct": numero(fila, "impuestos", D(base["impuesto_pct"]) if base
                                           else ctx.config.decimal("impuesto_predeterminado")),
                    "ganancia_pct": numero(fila, "porcentaje de ganancia", D(base["ganancia_pct"]) if base else 0),
                    "metodo_precio": metodo,
                    # Si no viene la ganancia pero sí el precio final, se respeta el precio.
                    "precio_manual": final is not None and (manual or not tiene_ganancia),
                    "precio_final": final,
                    "stock_minimo": numero(fila, "stock mínimo", de_milesimas(base["stock_minimo_mil"]) if base else 0),
                    "unidad": fila.get("unidad de medida") or (base["unidad"] if base else "unidad"),
                    "activo": fila.get("estado", "activo").lower() != "inactivo",
                }
                stock = numero(fila, "cantidad disponible", None)
                if base is None:
                    datos["stock"] = stock or 0
                    ctx.productos.crear(datos, origen="importacion")
                    resultado["creados"] += 1
                else:
                    ctx.productos.actualizar(base["id"], datos, origen="importacion")
                    if stock is not None and stock != de_milesimas(base["stock_mil"]):
                        ctx.inventario.registrar_movimiento(base["id"], "ajuste", stock, "Importación desde CSV")
                    resultado["actualizados"] += 1
        except ErrorNegocio as e:
            resultado["errores"].append(f"Fila {n}: {e}")
    with ctx.db.transaccion():
        ctx.auditar("importacion_productos", "productos", None,
                    f"{resultado['creados']} creados, {resultado['actualizados']} actualizados, {len(resultado['errores'])} con error")
    return resultado
