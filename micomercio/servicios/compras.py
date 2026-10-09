from __future__ import annotations

from ..core.dinero import D, a_milesimas, fmt_dinero, importe_linea
from ..core.errores import ErrorNegocio
from ..core.util import ahora, rango_dias

CAMPOS_PROVEEDOR = ("nombre", "cuit", "telefono", "email", "direccion", "notas")


class Compras:
    def __init__(self, ctx):
        self.ctx = ctx
        self.db = ctx.db

    # ---- proveedores -----------------------------------------------------
    def proveedores(self, texto: str = "", solo_activos: bool = True):
        donde, params = [], []
        if texto.strip():
            donde.append("(nombre LIKE ? OR cuit LIKE ?)")
            params += [f"%{texto.strip()}%"] * 2
        if solo_activos:
            donde.append("activo = 1")
        return self.db.consultar(
            f"SELECT * FROM proveedores {'WHERE ' + ' AND '.join(donde) if donde else ''} ORDER BY nombre COLLATE NOCASE",
            params,
        )

    def proveedor(self, proveedor_id: int):
        fila = self.db.uno("SELECT * FROM proveedores WHERE id = ?", (proveedor_id,))
        if fila is None:
            raise ErrorNegocio("El proveedor no existe.")
        return fila

    def guardar_proveedor(self, datos: dict, proveedor_id: int | None = None) -> int:
        self.ctx.requiere("compras")
        valores = {c: (datos.get(c) or "").strip() for c in CAMPOS_PROVEEDOR}
        if not valores["nombre"]:
            raise ErrorNegocio("Escribí el nombre del proveedor.")
        with self.db.transaccion():
            if proveedor_id is None:
                cur = self.db.ejecutar(
                    f"INSERT INTO proveedores ({', '.join(CAMPOS_PROVEEDOR)}, creado_en) "
                    f"VALUES ({', '.join('?' * len(CAMPOS_PROVEEDOR))}, ?)",
                    (*valores.values(), ahora()),
                )
                return cur.lastrowid
            self.db.ejecutar(
                f"UPDATE proveedores SET {', '.join(c + ' = ?' for c in CAMPOS_PROVEEDOR)} WHERE id = ?",
                (*valores.values(), proveedor_id),
            )
            return proveedor_id

    def cambiar_estado_proveedor(self, proveedor_id: int, activo: bool) -> None:
        self.ctx.requiere("compras")
        with self.db.transaccion():
            self.db.ejecutar("UPDATE proveedores SET activo = ? WHERE id = ?", (1 if activo else 0, proveedor_id))

    # ---- compras ---------------------------------------------------------
    def registrar(self, proveedor_id: int | None, items: list[dict], comprobante: str = "", notas: str = "",
                  actualizar_precios: bool = True) -> int:
        """Confirma una compra: suma el stock y registra el nuevo Precio Costo de cada producto.

        items: [{producto_id, cantidad (Decimal), costo_cent}]
        actualizar_precios: si es verdadero, el Precio de venta final se recalcula
        con el Porcentaje de ganancia de cada producto. Si no, el precio de venta
        no cambia y se recalcula la ganancia resultante.
        Las ventas ya registradas no se modifican: guardan su propio costo.
        """
        self.ctx.requiere("compras")
        if not items:
            raise ErrorNegocio("Agregá al menos un producto a la compra.")
        with self.db.transaccion():
            lineas, total = [], 0
            for item in items:
                cantidad_mil = a_milesimas(D(item["cantidad"]))
                costo = int(item["costo_cent"])
                if cantidad_mil <= 0:
                    raise ErrorNegocio("Las cantidades compradas deben ser mayores a cero.")
                if costo < 0:
                    raise ErrorNegocio("El costo no puede ser negativo.")
                subtotal = importe_linea(costo, cantidad_mil)
                lineas.append((item["producto_id"], cantidad_mil, costo, subtotal))
                total += subtotal
            compra_id = self.db.ejecutar(
                "INSERT INTO compras (fecha, proveedor_id, comprobante, total_cent, notas, usuario_id) VALUES (?,?,?,?,?,?)",
                (ahora(), proveedor_id, (comprobante or "").strip(), total, (notas or "").strip(), self.ctx.usuario_id),
            ).lastrowid
            for producto_id, cantidad_mil, costo, subtotal in lineas:
                self.db.ejecutar(
                    "INSERT INTO compra_items (compra_id, producto_id, cantidad_mil, costo_unit_cent, subtotal_cent) VALUES (?,?,?,?,?)",
                    (compra_id, producto_id, cantidad_mil, costo, subtotal),
                )
                self.ctx.productos.actualizar_costo(producto_id, costo, actualizar_precios, "compra")
                self.ctx.inventario.mover(producto_id, cantidad_mil, "compra", f"Compra N° {compra_id}", "compra", compra_id, costo)
            self.ctx.auditar("compra", "compras", compra_id, f"Total {fmt_dinero(total)}")
        return compra_id

    def listar(self, desde: str, hasta: str):
        inicio, fin = rango_dias(desde, hasta)
        return self.db.consultar(
            """SELECT c.*, COALESCE(p.nombre, 'Sin proveedor') AS proveedor, COALESCE(u.nombre, '') AS usuario,
                      (SELECT COUNT(*) FROM compra_items WHERE compra_id = c.id) AS renglones
               FROM compras c LEFT JOIN proveedores p ON p.id = c.proveedor_id LEFT JOIN usuarios u ON u.id = c.usuario_id
               WHERE c.fecha >= ? AND c.fecha < ? ORDER BY c.id DESC""",
            (inicio, fin),
        )

    def items(self, compra_id: int):
        return self.db.consultar(
            """SELECT i.*, p.codigo, p.nombre, p.unidad FROM compra_items i
               JOIN productos p ON p.id = i.producto_id WHERE i.compra_id = ? ORDER BY i.id""",
            (compra_id,),
        )
