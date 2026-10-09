from __future__ import annotations

from decimal import Decimal

from ..core.dinero import D, a_milesimas, fmt_dinero, fmt_pct, importe_linea
from ..core.errores import ErrorNegocio
from ..core.precios import desglosar_centavos
from ..core.util import ahora, rango_dias
from .caja import MEDIOS

# Medios que pueden quedar pendientes hasta verificar que el dinero ingresó.
MEDIOS_CON_PENDIENTE = ("transferencia", "mercadopago")

SELECT_VENTA = """
    SELECT v.*, COALESCE(c.nombre, 'Consumidor final') AS cliente, COALESCE(u.nombre, '') AS usuario,
        (SELECT COALESCE(SUM(monto_cent), 0) FROM pagos WHERE venta_id = v.id AND tipo = 'cobro' AND estado = 'confirmado') AS cobrado_cent,
        (SELECT COALESCE(SUM(monto_cent), 0) FROM pagos WHERE venta_id = v.id AND tipo = 'cobro' AND estado = 'pendiente') AS pendiente_cent,
        (SELECT GROUP_CONCAT(DISTINCT medio) FROM pagos WHERE venta_id = v.id AND tipo = 'cobro' AND estado IN ('confirmado', 'pendiente')) AS medios
    FROM ventas v
    LEFT JOIN clientes c ON c.id = v.cliente_id
    LEFT JOIN usuarios u ON u.id = v.usuario_id
"""

ESTADOS_PAGO = {"pagada": "Pagada", "pendiente": "Pago pendiente", "impaga": "Sin cobrar", "anulada": "Anulada"}


def estado_pago(venta) -> str:
    if venta["estado"] == "anulada":
        return "anulada"
    if venta["cobrado_cent"] >= venta["total_cent"]:
        return "pagada"
    if venta["pendiente_cent"] > 0:
        return "pendiente"
    return "impaga"


def repartir_descuento(brutos: list[int], descuento_cent: int) -> list[int]:
    """Reparte un descuento entre las líneas en proporción a su importe, sin perder centavos."""
    total = sum(brutos)
    if descuento_cent <= 0 or total <= 0:
        return [0] * len(brutos)
    partes = [b * descuento_cent // total for b in brutos]
    resto = descuento_cent - sum(partes)
    for i in sorted(range(len(brutos)), key=lambda i: -brutos[i]):
        if resto <= 0:
            break
        if partes[i] < brutos[i]:
            partes[i] += 1
            resto -= 1
    return partes


def calcular_totales(items: list[dict], descuento_cent: int = 0) -> dict:
    """Totales de un carrito. Cada ítem: cantidad_mil, precio_unit_cent, impuesto_pct."""
    brutos = [importe_linea(i["precio_unit_cent"], i["cantidad_mil"]) for i in items]
    descuentos = repartir_descuento(brutos, descuento_cent)
    lineas, neto, impuestos = [], 0, 0
    for item, bruto, desc in zip(items, brutos, descuentos):
        total = bruto - desc
        n, imp = desglosar_centavos(total, item["impuesto_pct"])
        lineas.append({"bruto_cent": bruto, "descuento_cent": desc, "total_cent": total, "neto_cent": n, "impuesto_cent": imp})
        neto += n
        impuestos += imp
    bruto_total = sum(brutos)
    return {
        "lineas": lineas, "bruto_cent": bruto_total, "descuento_cent": sum(descuentos),
        "neto_cent": neto, "impuestos_cent": impuestos, "total_cent": bruto_total - sum(descuentos),
    }


class Ventas:
    def __init__(self, ctx):
        self.ctx = ctx
        self.db = ctx.db

    def descuento_maximo_pct(self) -> Decimal:
        """Descuento máximo que puede aplicar el usuario actual (el administrador no tiene tope)."""
        if self.ctx.puede("descuento_libre"):
            return Decimal(100)
        return self.ctx.config.decimal("descuento_maximo_cajero_pct")

    # ---- registrar -------------------------------------------------------
    def registrar(self, uuid: str, items: list[dict], pagos: list[dict], descuento_cent: int = 0,
                  cliente_id: int | None = None, notas: str = "") -> int:
        """Registra la venta completa en una sola transacción: venta, ítems, pagos y descuento de stock.

        Si algo falla no queda nada guardado. El uuid identifica el intento de
        venta: si llega dos veces (doble clic), la segunda devuelve la venta ya
        registrada en lugar de crear otra.

        items: [{producto_id, cantidad (Decimal), precio_unit_cent}]
        pagos: [{medio, monto_cent, estado ('confirmado' | 'pendiente'), referencia, comision_cent}]
        """
        self.ctx.requiere("vender")
        if not uuid:
            raise ErrorNegocio("Falta el identificador de la venta.")
        with self.db.transaccion():
            existente = self.db.uno("SELECT id FROM ventas WHERE uuid = ?", (uuid,))
            if existente:
                return existente["id"]
            caja = self.ctx.caja.requerir_abierta()
            if not items:
                raise ErrorNegocio("Agregá al menos un producto a la venta.")

            lineas = []
            for item in items:
                p = self.db.uno("SELECT * FROM productos WHERE id = ?", (item["producto_id"],))
                if p is None:
                    raise ErrorNegocio("Uno de los productos de la venta ya no existe.")
                if not p["activo"]:
                    raise ErrorNegocio(f"El producto «{p['nombre']}» está desactivado y no se puede vender.")
                cantidad_mil = a_milesimas(D(item["cantidad"]))
                if cantidad_mil <= 0:
                    raise ErrorNegocio(f"La cantidad de «{p['nombre']}» debe ser mayor a cero.")
                precio = int(item.get("precio_unit_cent", p["precio_final_cent"]))
                if precio < 0:
                    raise ErrorNegocio(f"El precio de «{p['nombre']}» no es válido.")
                lineas.append({"producto": p, "cantidad_mil": cantidad_mil, "precio_unit_cent": precio,
                               "impuesto_pct": p["impuesto_pct"]})

            bruto = sum(importe_linea(l["precio_unit_cent"], l["cantidad_mil"]) for l in lineas)
            descuento_cent = int(descuento_cent or 0)
            if descuento_cent < 0 or descuento_cent > bruto:
                raise ErrorNegocio("El descuento no puede ser mayor al importe de la venta.")
            if descuento_cent and bruto:
                maximo = self.descuento_maximo_pct()
                if Decimal(descuento_cent) * 100 / bruto > maximo:
                    raise ErrorNegocio(
                        f"Tu usuario puede aplicar descuentos de hasta {fmt_pct(maximo)} %. "
                        "Un descuento mayor debe hacerlo un administrador."
                    )
            totales = calcular_totales(lineas, descuento_cent)

            pagos = [dict(p) for p in pagos]
            for pago in pagos:
                self._validar_pago(pago)
            if sum(p["monto_cent"] for p in pagos) != totales["total_cent"]:
                raise ErrorNegocio("El importe de los pagos no coincide con el total de la venta.")

            fecha = ahora()
            venta_id = self.db.ejecutar(
                """INSERT INTO ventas (uuid, fecha, caja_id, cliente_id, usuario_id, bruto_cent, descuento_cent,
                   neto_cent, impuestos_cent, total_cent, notas) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    uuid, fecha, caja["id"], cliente_id, self.ctx.usuario_id, totales["bruto_cent"],
                    totales["descuento_cent"], totales["neto_cent"], totales["impuestos_cent"],
                    totales["total_cent"], (notas or "").strip(),
                ),
            ).lastrowid
            for linea, t in zip(lineas, totales["lineas"]):
                p = linea["producto"]
                self.db.ejecutar(
                    """INSERT INTO venta_items (venta_id, producto_id, codigo, nombre, unidad, cantidad_mil,
                       precio_unit_cent, impuesto_pct, costo_unit_cent, bruto_cent, descuento_cent, total_cent,
                       neto_cent, impuesto_cent) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        venta_id, p["id"], p["codigo"], p["nombre"], p["unidad"], linea["cantidad_mil"],
                        linea["precio_unit_cent"], p["impuesto_pct"], p["costo_cent"], t["bruto_cent"],
                        t["descuento_cent"], t["total_cent"], t["neto_cent"], t["impuesto_cent"],
                    ),
                )
                self.ctx.inventario.mover(p["id"], -linea["cantidad_mil"], "venta", f"Venta N° {venta_id}", "venta", venta_id)
            for pago in pagos:
                self._insertar_pago(venta_id, pago, caja["id"], fecha)
            if totales["descuento_cent"]:
                self.ctx.auditar("descuento", "ventas", venta_id, f"Descuento de {fmt_dinero(totales['descuento_cent'])}")
        return venta_id

    def _validar_pago(self, pago: dict) -> None:
        if pago.get("medio") not in MEDIOS:
            raise ErrorNegocio("El medio de pago no es válido.")
        pago.setdefault("estado", "confirmado")
        if pago["estado"] not in ("confirmado", "pendiente"):
            raise ErrorNegocio("El estado del pago no es válido.")
        if pago["estado"] == "pendiente" and pago["medio"] not in MEDIOS_CON_PENDIENTE:
            raise ErrorNegocio("Solo las transferencias y los cobros con Mercado Pago pueden quedar pendientes.")
        if int(pago.get("monto_cent", 0)) <= 0:
            raise ErrorNegocio("El importe del pago debe ser mayor a cero.")
        comision = int(pago.get("comision_cent") or 0)
        if comision < 0 or comision > pago["monto_cent"]:
            raise ErrorNegocio("La comisión no puede ser negativa ni mayor al importe cobrado.")
        pago["comision_cent"] = comision

    def _insertar_pago(self, venta_id: int, pago: dict, caja_id: int, fecha: str) -> int:
        confirmado = pago["estado"] == "confirmado"
        return self.db.ejecutar(
            """INSERT INTO pagos (venta_id, tipo, medio, monto_cent, estado, comision_cent, referencia, creado_en,
               confirmado_en, caja_id, usuario_id) VALUES (?, 'cobro', ?,?,?,?,?,?,?,?,?)""",
            (
                venta_id, pago["medio"], pago["monto_cent"], pago["estado"], pago["comision_cent"],
                (pago.get("referencia") or "").strip(), fecha, fecha if confirmado else None,
                caja_id if confirmado else None, self.ctx.usuario_id,
            ),
        ).lastrowid

    # ---- pagos -----------------------------------------------------------
    def _pago(self, pago_id: int):
        pago = self.db.uno("SELECT * FROM pagos WHERE id = ?", (pago_id,))
        if pago is None:
            raise ErrorNegocio("El pago no existe.")
        return pago

    def confirmar_pago(self, pago_id: int, referencia: str = "", comision_cent: int = 0) -> None:
        """Marca un pago pendiente como cobrado. El ingreso cuenta en la caja abierta en este momento."""
        self.ctx.requiere("caja")
        with self.db.transaccion():
            pago = self._pago(pago_id)
            caja = self.ctx.caja.requerir_abierta()
            if comision_cent < 0 or comision_cent > pago["monto_cent"]:
                raise ErrorNegocio("La comisión no puede ser negativa ni mayor al importe cobrado.")
            cur = self.db.ejecutar(
                """UPDATE pagos SET estado = 'confirmado', confirmado_en = ?, caja_id = ?, comision_cent = ?,
                   referencia = CASE WHEN ? <> '' THEN ? ELSE referencia END
                   WHERE id = ? AND estado = 'pendiente' AND tipo = 'cobro'""",
                (ahora(), caja["id"], comision_cent, referencia.strip(), referencia.strip(), pago_id),
            )
            if cur.rowcount != 1:
                raise ErrorNegocio("Este pago ya no está pendiente: no se puede confirmar otra vez.")
            self.ctx.auditar("pago_confirmado", "pagos", pago_id, f"Venta N° {pago['venta_id']}, {fmt_dinero(pago['monto_cent'])}")

    def descartar_pago(self, pago_id: int, estado: str) -> None:
        """Marca un pago pendiente como rechazado o cancelado. No genera ningún ingreso."""
        self.ctx.requiere("caja")
        if estado not in ("rechazado", "cancelado"):
            raise ErrorNegocio("El estado del pago no es válido.")
        with self.db.transaccion():
            pago = self._pago(pago_id)
            cur = self.db.ejecutar(
                "UPDATE pagos SET estado = ? WHERE id = ? AND estado = 'pendiente' AND tipo = 'cobro'", (estado, pago_id)
            )
            if cur.rowcount != 1:
                raise ErrorNegocio("Este pago ya no está pendiente.")
            self.ctx.auditar(f"pago_{estado}", "pagos", pago_id, f"Venta N° {pago['venta_id']}, {fmt_dinero(pago['monto_cent'])}")

    def registrar_comision(self, pago_id: int, comision_cent: int) -> None:
        """Guarda la comisión que cobró Mercado Pago, para conocer el importe neto recibido."""
        self.ctx.requiere("caja")
        with self.db.transaccion():
            pago = self._pago(pago_id)
            if pago["tipo"] != "cobro" or pago["estado"] != "confirmado" or pago["medio"] != "mercadopago":
                raise ErrorNegocio("Solo se puede cargar la comisión de un cobro confirmado de Mercado Pago.")
            if comision_cent < 0 or comision_cent > pago["monto_cent"]:
                raise ErrorNegocio("La comisión no puede ser negativa ni mayor al importe cobrado.")
            self.db.ejecutar("UPDATE pagos SET comision_cent = ? WHERE id = ?", (comision_cent, pago_id))
            self.ctx.auditar("pago_comision", "pagos", pago_id, fmt_dinero(comision_cent))

    def saldo(self, venta_id: int) -> int:
        """Importe de la venta que todavía no tiene un pago confirmado ni pendiente."""
        v = self.obtener(venta_id)
        if v["estado"] == "anulada":
            return 0
        return max(0, v["total_cent"] - v["cobrado_cent"] - v["pendiente_cent"])

    def agregar_pago(self, venta_id: int, pago: dict) -> int:
        """Registra un nuevo cobro para una venta que quedó sin cobrar (por ejemplo, tras un pago rechazado)."""
        self.ctx.requiere("caja")
        with self.db.transaccion():
            caja = self.ctx.caja.requerir_abierta()
            pago = dict(pago)
            self._validar_pago(pago)
            if pago["monto_cent"] > self.saldo(venta_id):
                raise ErrorNegocio("El importe supera lo que falta cobrar de esta venta.")
            pago_id = self._insertar_pago(venta_id, pago, caja["id"], ahora())
            self.ctx.auditar("pago_agregado", "pagos", pago_id, f"Venta N° {venta_id}, {fmt_dinero(pago['monto_cent'])}")
        return pago_id

    # ---- anulación -------------------------------------------------------
    def anular(self, venta_id: int, motivo: str, con_nota_credito: bool = False) -> None:
        """Anula la venta: devuelve el stock, cancela los pagos pendientes y registra la
        devolución de lo ya cobrado. La venta no se borra: queda marcada como anulada."""
        self.ctx.requiere("anular")
        motivo = (motivo or "").strip()
        if not motivo:
            raise ErrorNegocio("Escribí el motivo de la anulación.")
        with self.db.transaccion():
            v = self.obtener(venta_id)
            if v["estado"] != "completada":
                raise ErrorNegocio("Esta venta ya está anulada.")
            if v["estado_fiscal"] == "pendiente":
                raise ErrorNegocio(
                    "Esta venta tiene una factura pendiente de autorización. Resolvela primero desde Facturación."
                )
            if v["estado_fiscal"] == "autorizada" and not con_nota_credito:
                raise ErrorNegocio(
                    "Esta venta tiene una factura autorizada por ARCA. Para anularla hay que emitir una nota de "
                    "crédito desde Facturación."
                )
            fecha = ahora()
            confirmados = self.db.consultar(
                "SELECT * FROM pagos WHERE venta_id = ? AND tipo = 'cobro' AND estado = 'confirmado'", (venta_id,)
            )
            if confirmados:
                caja = self.ctx.caja.requerir_abierta()
                for pago in confirmados:
                    self.db.ejecutar(
                        """INSERT INTO pagos (venta_id, tipo, medio, monto_cent, estado, referencia, creado_en,
                           confirmado_en, caja_id, usuario_id) VALUES (?, 'devolucion', ?, ?, 'confirmado', ?, ?, ?, ?, ?)""",
                        (venta_id, pago["medio"], pago["monto_cent"], f"Anulación de venta N° {venta_id}",
                         fecha, fecha, caja["id"], self.ctx.usuario_id),
                    )
            self.db.ejecutar(
                "UPDATE pagos SET estado = 'cancelado' WHERE venta_id = ? AND tipo = 'cobro' AND estado = 'pendiente'",
                (venta_id,),
            )
            for item in self.items(venta_id):
                self.ctx.inventario.mover(
                    item["producto_id"], item["cantidad_mil"], "anulacion", f"Anulación de venta N° {venta_id}",
                    "venta", venta_id, item["costo_unit_cent"],
                )
            self.db.ejecutar(
                "UPDATE ventas SET estado = 'anulada', anulada_en = ?, anulada_por = ?, motivo_anulacion = ? WHERE id = ?",
                (fecha, self.ctx.usuario_id, motivo, venta_id),
            )
            self.ctx.auditar("venta_anulada", "ventas", venta_id, f"{fmt_dinero(v['total_cent'])}: {motivo}")

    # ---- consultas -------------------------------------------------------
    def obtener(self, venta_id: int):
        fila = self.db.uno(SELECT_VENTA + " WHERE v.id = ?", (venta_id,))
        if fila is None:
            raise ErrorNegocio("La venta no existe.")
        return fila

    def items(self, venta_id: int):
        return self.db.consultar("SELECT * FROM venta_items WHERE venta_id = ? ORDER BY id", (venta_id,))

    def pagos(self, venta_id: int):
        return self.db.consultar("SELECT * FROM pagos WHERE venta_id = ? ORDER BY id", (venta_id,))

    def listar(self, desde: str, hasta: str, estado: str = "todas", texto: str = "", limite: int = 5000):
        """estado: todas | pagada | pendiente | impaga | anulada"""
        inicio, fin = rango_dias(desde, hasta)
        donde, params = ["v.fecha >= ? AND v.fecha < ?"], [inicio, fin]
        texto = texto.strip()
        if texto:
            donde.append("(CAST(v.id AS TEXT) = ? OR c.nombre LIKE ?)")
            params += [texto.lstrip("#"), f"%{texto}%"]
        filas = self.db.consultar(
            SELECT_VENTA + " WHERE " + " AND ".join(donde) + " ORDER BY v.id DESC LIMIT ?", (*params, limite)
        )
        if estado != "todas":
            filas = [f for f in filas if estado_pago(f) == estado]
        return filas

    def pagos_pendientes(self):
        return self.db.consultar(
            """SELECT p.*, v.fecha AS venta_fecha, v.total_cent FROM pagos p JOIN ventas v ON v.id = p.venta_id
               WHERE p.tipo = 'cobro' AND p.estado = 'pendiente' AND v.estado = 'completada' ORDER BY p.id"""
        )
