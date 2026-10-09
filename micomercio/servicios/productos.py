from __future__ import annotations

from decimal import Decimal

from ..core import precios
from ..core.dinero import D, a_centavos, a_milesimas, de_centavos, redondear
from ..core.errores import ErrorNegocio
from ..core.util import ahora

UNIDADES = ["unidad", "kg", "g", "litro", "ml", "metro", "caja", "pack", "docena"]

SELECT_PRODUCTO = """
    SELECT p.*, COALESCE(c.nombre, '') AS categoria, COALESCE(pr.nombre, '') AS proveedor
    FROM productos p
    LEFT JOIN categorias c ON c.id = p.categoria_id
    LEFT JOIN proveedores pr ON pr.id = p.proveedor_id
"""


def pct_txt(valor) -> str:
    """Porcentaje como texto sin ceros sobrantes: 21 · 10.5"""
    texto = format(redondear(valor, 4).normalize(), "f")
    return "0" if texto in ("-0", "") else texto


class Productos:
    def __init__(self, ctx):
        self.ctx = ctx
        self.db = ctx.db

    # ---- consultas -------------------------------------------------------
    def obtener(self, producto_id: int):
        fila = self.db.uno(SELECT_PRODUCTO + " WHERE p.id = ?", (producto_id,))
        if fila is None:
            raise ErrorNegocio("El producto no existe.")
        return fila

    def por_codigo(self, codigo: str, solo_activos: bool = True):
        """Busca por coincidencia exacta de código de barras o código interno (lo que envía el lector)."""
        codigo = codigo.strip()
        if not codigo:
            return None
        activo = " AND p.activo = 1" if solo_activos else ""
        return self.db.uno(
            SELECT_PRODUCTO + f" WHERE (p.codigo_barras = ? OR p.codigo = ?){activo} ORDER BY p.codigo_barras = ? DESC",
            (codigo, codigo, codigo),
        )

    def buscar(self, texto: str = "", categoria_id: int | None = None, proveedor_id: int | None = None,
               solo_activos: bool = True, limite: int = 2000):
        """Busca por nombre, código, código de barras, categoría o marca. Cada palabra debe aparecer."""
        donde, params = [], []
        for palabra in texto.split():
            patron = f"%{palabra}%"
            donde.append("(p.nombre LIKE ? OR p.codigo LIKE ? OR p.codigo_barras LIKE ? OR c.nombre LIKE ? OR p.marca LIKE ?)")
            params += [patron] * 5
        if categoria_id:
            donde.append("p.categoria_id = ?")
            params.append(categoria_id)
        if proveedor_id:
            donde.append("p.proveedor_id = ?")
            params.append(proveedor_id)
        if solo_activos:
            donde.append("p.activo = 1")
        sql = SELECT_PRODUCTO + (" WHERE " + " AND ".join(donde) if donde else "")
        return self.db.consultar(sql + " ORDER BY p.nombre COLLATE NOCASE LIMIT ?", (*params, limite))

    def categorias(self):
        return self.db.consultar("SELECT id, nombre FROM categorias ORDER BY nombre COLLATE NOCASE")

    def historial_precios(self, producto_id: int | None = None, limite: int = 1000):
        donde = "WHERE h.producto_id = ?" if producto_id else ""
        params = (producto_id, limite) if producto_id else (limite,)
        return self.db.consultar(
            f"""SELECT h.*, p.codigo, p.nombre, COALESCE(u.nombre, '') AS usuario
                FROM historial_precios h
                JOIN productos p ON p.id = h.producto_id
                LEFT JOIN usuarios u ON u.id = h.usuario_id
                {donde} ORDER BY h.id DESC LIMIT ?""",
            params,
        )

    # ---- cálculo de precio ----------------------------------------------
    @staticmethod
    def campos_precio(costo, impuesto_pct, ganancia_pct, metodo, precio_manual=False, precio_final=None) -> dict:
        """Devuelve los campos de precio listos para guardar.

        Si el Precio de venta final fue escrito a mano, se respeta y se recalcula
        el Porcentaje de ganancia resultante.
        """
        costo, impuesto_pct, ganancia_pct = D(costo), D(impuesto_pct), D(ganancia_pct)
        if precio_manual and precio_final is not None:
            final = redondear(precio_final)
            if final < 0:
                raise ErrorNegocio("El Precio de venta final no puede ser negativo.")
            ganancia_pct = precios.ganancia_desde_final(costo, impuesto_pct, final, metodo)
            neto = precios.sin_impuestos_desde_final(final, impuesto_pct)
        else:
            precio = precios.calcular_precio(costo, impuesto_pct, ganancia_pct, metodo)
            neto, final = precio.sin_impuestos, precio.final
            precio_manual = False
        return {
            "costo_cent": a_centavos(costo),
            "impuesto_pct": pct_txt(impuesto_pct),
            "ganancia_pct": pct_txt(ganancia_pct),
            "metodo_precio": metodo,
            "precio_neto_cent": a_centavos(neto),
            "precio_final_cent": a_centavos(final),
            "precio_manual": 1 if precio_manual else 0,
        }

    def _registrar_precio(self, producto_id: int, anterior, nuevo: dict, origen: str) -> None:
        if anterior is not None and all(
            anterior[k] == nuevo[k] for k in ("costo_cent", "impuesto_pct", "ganancia_pct", "precio_final_cent")
        ):
            return
        self.db.ejecutar(
            """INSERT INTO historial_precios
               (producto_id, fecha, usuario_id, origen, costo_ant_cent, costo_cent, impuesto_ant, impuesto_pct,
                ganancia_ant, ganancia_pct, final_ant_cent, final_cent)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                producto_id, ahora(), self.ctx.usuario_id, origen,
                anterior["costo_cent"] if anterior else None, nuevo["costo_cent"],
                anterior["impuesto_pct"] if anterior else None, nuevo["impuesto_pct"],
                anterior["ganancia_pct"] if anterior else None, nuevo["ganancia_pct"],
                anterior["precio_final_cent"] if anterior else None, nuevo["precio_final_cent"],
            ),
        )

    def _aplicar_precio(self, producto_id: int, anterior, campos: dict, origen: str) -> None:
        self.db.ejecutar(
            """UPDATE productos SET costo_cent = :costo_cent, impuesto_pct = :impuesto_pct,
               ganancia_pct = :ganancia_pct, metodo_precio = :metodo_precio, precio_neto_cent = :precio_neto_cent,
               precio_final_cent = :precio_final_cent, precio_manual = :precio_manual WHERE id = :id""",
            {**campos, "id": producto_id},
        )
        self._registrar_precio(producto_id, anterior, campos, origen)

    # ---- altas y cambios -------------------------------------------------
    def _categoria_id(self, nombre: str | None) -> int | None:
        nombre = (nombre or "").strip()
        if not nombre:
            return None
        fila = self.db.uno("SELECT id FROM categorias WHERE nombre = ?", (nombre,))
        if fila:
            return fila["id"]
        return self.db.ejecutar("INSERT INTO categorias (nombre) VALUES (?)", (nombre,)).lastrowid

    def siguiente_codigo(self) -> str:
        n = self.db.valor("SELECT COALESCE(MAX(id), 0) FROM productos") + 1
        while self.db.uno("SELECT 1 FROM productos WHERE codigo = ?", (str(n),)):
            n += 1
        return str(n)

    def _validar(self, datos: dict, producto_id: int | None) -> dict:
        d = dict(datos)
        d["nombre"] = (d.get("nombre") or "").strip()
        d["codigo"] = (d.get("codigo") or "").strip()
        d["codigo_barras"] = (d.get("codigo_barras") or "").strip()
        if not d["nombre"]:
            raise ErrorNegocio("Escribí el nombre del producto.")
        if not d["codigo"]:
            d["codigo"] = self.siguiente_codigo()
        otro = self.db.uno("SELECT id FROM productos WHERE codigo = ? AND id IS NOT ?", (d["codigo"], producto_id))
        if otro:
            raise ErrorNegocio(f"Ya existe otro producto con el código interno «{d['codigo']}».")
        if d["codigo_barras"]:
            otro = self.db.uno(
                "SELECT nombre FROM productos WHERE codigo_barras = ? AND id IS NOT ?", (d["codigo_barras"], producto_id)
            )
            if otro:
                raise ErrorNegocio(f"El código de barras ya está asignado al producto «{otro['nombre']}».")
        d["unidad"] = (d.get("unidad") or "unidad").strip() or "unidad"
        d["stock_minimo"] = D(d.get("stock_minimo") or 0)
        if d["stock_minimo"] < 0:
            raise ErrorNegocio("El stock mínimo no puede ser negativo.")
        d["metodo_precio"] = d.get("metodo_precio") or self.ctx.config.obtener("metodo_precio_predeterminado")
        return d

    def crear(self, datos: dict, origen: str = "alta") -> int:
        self.ctx.requiere("productos_editar")
        with self.db.transaccion():
            d = self._validar(datos, None)
            campos = self.campos_precio(
                d.get("costo") or 0, d.get("impuesto_pct") or 0, d.get("ganancia_pct") or 0,
                d["metodo_precio"], d.get("precio_manual", False), d.get("precio_final"),
            )
            stock = D(d.get("stock") or 0)
            if stock < 0:
                raise ErrorNegocio("La cantidad disponible no puede ser negativa.")
            cur = self.db.ejecutar(
                """INSERT INTO productos (codigo, codigo_barras, nombre, descripcion, categoria_id, marca,
                   proveedor_id, stock_minimo_mil, unidad, fecha_alta, activo)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    d["codigo"], d["codigo_barras"], d["nombre"], (d.get("descripcion") or "").strip(),
                    self._categoria_id(d.get("categoria")), (d.get("marca") or "").strip(), d.get("proveedor_id"),
                    a_milesimas(d["stock_minimo"]), d["unidad"], ahora(), 1 if d.get("activo", True) else 0,
                ),
            )
            producto_id = cur.lastrowid
            self._aplicar_precio(producto_id, None, campos, origen)
            if stock > 0:
                self.ctx.inventario.mover(producto_id, a_milesimas(stock), "inicial", "Stock inicial", "producto", producto_id)
        return producto_id

    def actualizar(self, producto_id: int, datos: dict, origen: str = "edicion") -> None:
        """Modifica el producto. El stock no se toca acá: se cambia con movimientos de inventario."""
        self.ctx.requiere("productos_editar")
        with self.db.transaccion():
            anterior = self.obtener(producto_id)
            d = self._validar(datos, producto_id)
            campos = self.campos_precio(
                d.get("costo") or 0, d.get("impuesto_pct") or 0, d.get("ganancia_pct") or 0,
                d["metodo_precio"], d.get("precio_manual", False), d.get("precio_final"),
            )
            self.db.ejecutar(
                """UPDATE productos SET codigo = ?, codigo_barras = ?, nombre = ?, descripcion = ?, categoria_id = ?,
                   marca = ?, proveedor_id = ?, stock_minimo_mil = ?, unidad = ?, activo = ? WHERE id = ?""",
                (
                    d["codigo"], d["codigo_barras"], d["nombre"], (d.get("descripcion") or "").strip(),
                    self._categoria_id(d.get("categoria")), (d.get("marca") or "").strip(), d.get("proveedor_id"),
                    a_milesimas(d["stock_minimo"]), d["unidad"], 1 if d.get("activo", True) else 0, producto_id,
                ),
            )
            self._aplicar_precio(producto_id, anterior, campos, origen)
            if anterior["precio_final_cent"] != campos["precio_final_cent"] or anterior["costo_cent"] != campos["costo_cent"]:
                self.ctx.auditar(
                    "cambio_precio", "productos", producto_id,
                    f"{d['nombre']}: costo {de_centavos(anterior['costo_cent'])} -> {de_centavos(campos['costo_cent'])}, "
                    f"final {de_centavos(anterior['precio_final_cent'])} -> {de_centavos(campos['precio_final_cent'])}",
                )

    def cambiar_estado(self, producto_id: int, activo: bool) -> None:
        """Desactivar no borra nada: el producto deja de ofrecerse pero su historial se conserva."""
        self.ctx.requiere("productos_editar")
        with self.db.transaccion():
            self.db.ejecutar("UPDATE productos SET activo = ? WHERE id = ?", (1 if activo else 0, producto_id))
            self.ctx.auditar("producto_activado" if activo else "producto_desactivado", "productos", producto_id)

    def datos_para_duplicar(self, producto_id: int) -> dict:
        p = self.obtener(producto_id)
        return {
            "codigo": "", "codigo_barras": "", "nombre": f"{p['nombre']} (copia)", "descripcion": p["descripcion"],
            "categoria": p["categoria"], "marca": p["marca"], "proveedor_id": p["proveedor_id"],
            "costo": de_centavos(p["costo_cent"]), "impuesto_pct": D(p["impuesto_pct"]),
            "ganancia_pct": D(p["ganancia_pct"]), "metodo_precio": p["metodo_precio"],
            "precio_final": de_centavos(p["precio_final_cent"]), "precio_manual": bool(p["precio_manual"]),
            "stock": Decimal(0), "stock_minimo": Decimal(p["stock_minimo_mil"]) / 1000, "unidad": p["unidad"],
            "activo": True,
        }

    def actualizar_costo(self, producto_id: int, costo_cent: int, recalcular_precio: bool, origen: str) -> None:
        """Registra un nuevo Precio Costo (por ejemplo, al confirmar una compra).

        Con recalcular_precio se mantiene el Porcentaje de ganancia y cambia el
        Precio de venta final. Sin él, el precio final queda igual y se recalcula
        la ganancia resultante. Las ventas ya registradas conservan su propio costo.
        """
        with self.db.transaccion():
            p = self.obtener(producto_id)
            if p["costo_cent"] == costo_cent:
                return
            campos = self.campos_precio(
                de_centavos(costo_cent), p["impuesto_pct"], p["ganancia_pct"], p["metodo_precio"],
                precio_manual=not recalcular_precio, precio_final=de_centavos(p["precio_final_cent"]),
            )
            if not recalcular_precio:
                campos["precio_manual"] = p["precio_manual"]
            self._aplicar_precio(producto_id, p, campos, origen)

    # ---- cambio masivo de precios ---------------------------------------
    def previsualizar_cambio_masivo(self, campo: str, tipo: str, valor, redondeo=0, texto: str = "",
                                    categoria_id: int | None = None, proveedor_id: int | None = None) -> list[dict]:
        """Calcula, sin guardar, cómo quedaría cada producto.

        campo:  'costo' cambia el Precio Costo y recalcula el precio manteniendo la ganancia.
                'final' cambia el Precio de venta final y recalcula la ganancia resultante.
        tipo:   'porcentaje' o 'importe' (positivo aumenta, negativo disminuye).
        redondeo: múltiplo en pesos para el Precio de venta final (0 = sin redondeo).
        """
        if campo not in ("costo", "final") or tipo not in ("porcentaje", "importe"):
            raise ErrorNegocio("La operación de cambio de precios no es válida.")
        valor, redondeo = D(valor), D(redondeo or 0)
        if valor == 0 and redondeo == 0:
            raise ErrorNegocio("Indicá un porcentaje o un importe distinto de cero.")

        def ajustar(base: Decimal) -> Decimal:
            return base * (1 + valor / 100) if tipo == "porcentaje" else base + valor

        resultado = []
        for p in self.buscar(texto, categoria_id, proveedor_id, solo_activos=True, limite=1_000_000):
            costo, final = de_centavos(p["costo_cent"]), de_centavos(p["precio_final_cent"])
            fila = {
                "id": p["id"], "codigo": p["codigo"], "nombre": p["nombre"],
                "costo_ant_cent": p["costo_cent"], "final_ant_cent": p["precio_final_cent"],
                "ganancia_ant": p["ganancia_pct"], "error": "", "campos": None,
            }
            try:
                if campo == "costo":
                    nuevo_costo = redondear(ajustar(costo))
                    if nuevo_costo < 0:
                        raise ErrorNegocio("El Precio Costo quedaría negativo.")
                    campos = self.campos_precio(nuevo_costo, p["impuesto_pct"], p["ganancia_pct"], p["metodo_precio"])
                    nuevo_final = de_centavos(campos["precio_final_cent"])
                    if redondeo > 0:
                        nuevo_final = precios.redondear_a_multiplo(nuevo_final, redondeo)
                        campos = self.campos_precio(nuevo_costo, p["impuesto_pct"], 0, p["metodo_precio"], True, nuevo_final)
                else:
                    nuevo_final = redondear(ajustar(final))
                    if redondeo > 0:
                        nuevo_final = precios.redondear_a_multiplo(nuevo_final, redondeo)
                    if nuevo_final < 0:
                        raise ErrorNegocio("El Precio de venta final quedaría negativo.")
                    campos = self.campos_precio(costo, p["impuesto_pct"], 0, p["metodo_precio"], True, nuevo_final)
                fila["campos"] = campos
            except ErrorNegocio as e:
                fila["error"] = str(e)
            resultado.append(fila)
        return resultado

    def aplicar_cambio_masivo(self, vista_previa: list[dict]) -> int:
        """Guarda una vista previa ya revisada por el usuario. Devuelve cuántos productos cambiaron."""
        self.ctx.requiere("precios")
        cambiados = 0
        with self.db.transaccion():
            for fila in vista_previa:
                if fila["campos"] is None:
                    continue
                anterior = self.obtener(fila["id"])
                if (anterior["costo_cent"], anterior["precio_final_cent"]) != (fila["costo_ant_cent"], fila["final_ant_cent"]):
                    raise ErrorNegocio(
                        f"El producto «{anterior['nombre']}» cambió después de generar la vista previa. "
                        "Volvé a generarla antes de guardar."
                    )
                if (anterior["costo_cent"], anterior["precio_final_cent"]) == (
                    fila["campos"]["costo_cent"], fila["campos"]["precio_final_cent"]
                ):
                    continue
                self._aplicar_precio(fila["id"], anterior, fila["campos"], "masivo")
                cambiados += 1
            self.ctx.auditar("cambio_masivo_precios", "productos", None, f"{cambiados} productos modificados")
        return cambiados
