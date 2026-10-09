from __future__ import annotations

from decimal import Decimal

from ..core.dinero import D, a_milesimas, fmt_cantidad
from ..core.errores import ErrorNegocio
from ..core.util import ahora, rango_dias

TIPOS = {
    "inicial": "Stock inicial",
    "venta": "Venta",
    "compra": "Compra",
    "entrada": "Entrada manual",
    "salida": "Salida manual",
    "ajuste": "Ajuste de inventario",
    "devolucion": "Devolución",
    "anulacion": "Anulación de venta",
}


class Inventario:
    def __init__(self, ctx):
        self.ctx = ctx
        self.db = ctx.db

    def permite_negativo(self) -> bool:
        """El stock negativo solo se permite si el administrador lo habilitó en Configuración."""
        return self.ctx.config.booleano("permitir_stock_negativo")

    def mover(self, producto_id: int, cantidad_mil: int, tipo: str, motivo: str = "",
              ref_tipo: str | None = None, ref_id: int | None = None, costo_cent: int | None = None) -> int:
        """Cambia el stock y deja registrado el movimiento, siempre dentro de una misma transacción."""
        if cantidad_mil == 0:
            raise ErrorNegocio("La cantidad del movimiento no puede ser cero.")
        with self.db.transaccion():
            p = self.db.uno("SELECT nombre, stock_mil, costo_cent FROM productos WHERE id = ?", (producto_id,))
            if p is None:
                raise ErrorNegocio("El producto no existe.")
            nuevo = p["stock_mil"] + cantidad_mil
            if cantidad_mil < 0 and nuevo < 0 and not self.permite_negativo():
                raise ErrorNegocio(
                    f"No hay stock suficiente de «{p['nombre']}»: hay {fmt_cantidad(p['stock_mil'])} "
                    f"y se necesitan {fmt_cantidad(-cantidad_mil)}."
                )
            self.db.ejecutar("UPDATE productos SET stock_mil = ? WHERE id = ?", (nuevo, producto_id))
            self.db.ejecutar(
                """INSERT INTO movimientos_stock (producto_id, fecha, tipo, cantidad_mil, stock_resultante_mil,
                   motivo, ref_tipo, ref_id, costo_cent, usuario_id) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    producto_id, ahora(), tipo, cantidad_mil, nuevo, motivo, ref_tipo, ref_id,
                    p["costo_cent"] if costo_cent is None else costo_cent, self.ctx.usuario_id,
                ),
            )
        return nuevo

    def registrar_movimiento(self, producto_id: int, tipo: str, cantidad, motivo: str) -> int:
        """Movimiento manual. En 'ajuste' la cantidad es el stock real contado."""
        self.ctx.requiere("inventario")
        motivo = (motivo or "").strip()
        if not motivo:
            raise ErrorNegocio("Escribí el motivo del movimiento.")
        cantidad = D(cantidad)
        with self.db.transaccion():
            if tipo == "ajuste":
                actual = self.db.valor("SELECT stock_mil FROM productos WHERE id = ?", (producto_id,))
                if actual is None:
                    raise ErrorNegocio("El producto no existe.")
                if cantidad < 0 and not self.permite_negativo():
                    raise ErrorNegocio("El stock contado no puede ser negativo.")
                delta = a_milesimas(cantidad) - actual
                if delta == 0:
                    raise ErrorNegocio("El stock contado es igual al que ya figura en el sistema.")
            elif tipo in ("entrada", "devolucion"):
                if cantidad <= 0:
                    raise ErrorNegocio("La cantidad debe ser mayor a cero.")
                delta = a_milesimas(cantidad)
            elif tipo == "salida":
                if cantidad <= 0:
                    raise ErrorNegocio("La cantidad debe ser mayor a cero.")
                delta = -a_milesimas(cantidad)
            else:
                raise ErrorNegocio("El tipo de movimiento no es válido.")
            nuevo = self.mover(producto_id, delta, tipo, motivo, "manual", None)
            self.ctx.auditar("movimiento_stock", "productos", producto_id, f"{tipo} {fmt_cantidad(delta)}: {motivo}")
        return nuevo

    # ---- consultas -------------------------------------------------------
    def existencias(self, texto: str = "", estado: str = "todos"):
        """estado: todos | bajo | agotado"""
        filas = self.ctx.productos.buscar(texto, solo_activos=True, limite=1_000_000)
        if estado == "agotado":
            return [f for f in filas if f["stock_mil"] <= 0]
        if estado == "bajo":
            return [f for f in filas if 0 < f["stock_mil"] <= f["stock_minimo_mil"]]
        return filas

    def alertas(self) -> dict:
        fila = self.db.uno(
            """SELECT SUM(stock_mil <= 0) AS agotados,
                      SUM(stock_mil > 0 AND stock_mil <= stock_minimo_mil) AS bajos
               FROM productos WHERE activo = 1"""
        )
        return {"agotados": fila["agotados"] or 0, "bajos": fila["bajos"] or 0}

    def movimientos(self, producto_id: int | None = None, desde: str | None = None, hasta: str | None = None,
                    tipo: str | None = None, limite: int = 2000):
        donde, params = [], []
        if producto_id:
            donde.append("m.producto_id = ?")
            params.append(producto_id)
        if desde and hasta:
            inicio, fin = rango_dias(desde, hasta)
            donde.append("m.fecha >= ? AND m.fecha < ?")
            params += [inicio, fin]
        if tipo:
            donde.append("m.tipo = ?")
            params.append(tipo)
        return self.db.consultar(
            f"""SELECT m.*, p.codigo, p.nombre, p.unidad, COALESCE(u.nombre, '') AS usuario
                FROM movimientos_stock m
                JOIN productos p ON p.id = m.producto_id
                LEFT JOIN usuarios u ON u.id = m.usuario_id
                {"WHERE " + " AND ".join(donde) if donde else ""}
                ORDER BY m.id DESC LIMIT ?""",
            (*params, limite),
        )

    def valor_inventario(self) -> dict:
        """Valor estimado del stock actual (solo existencias positivas de productos activos), en centavos."""
        costo = venta = Decimal(0)
        for p in self.db.consultar(
            "SELECT stock_mil, costo_cent, precio_final_cent FROM productos WHERE activo = 1 AND stock_mil > 0"
        ):
            costo += Decimal(p["stock_mil"]) * p["costo_cent"] / 1000
            venta += Decimal(p["stock_mil"]) * p["precio_final_cent"] / 1000
        return {"costo_cent": int(round(costo)), "venta_cent": int(round(venta))}
