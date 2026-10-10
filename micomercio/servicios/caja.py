from __future__ import annotations

from ..core.dinero import fmt_dinero
from ..core.errores import ErrorNegocio
from ..core.util import ahora

MEDIOS = {
    "efectivo": "Efectivo",
    "tarjeta": "Tarjeta",
    "transferencia": "Transferencia",
    "mercadopago": "Mercado Pago",
}


class Caja:
    def __init__(self, ctx):
        self.ctx = ctx
        self.db = ctx.db

    @property
    def puesto(self) -> str:
        return self.ctx.puesto

    def abierta(self):
        """La caja abierta de esta computadora (cada una tiene la suya)."""
        return self.db.uno("SELECT * FROM cajas WHERE estado = 'abierta' AND puesto = ? COLLATE NOCASE", (self.puesto,))

    def abiertas(self):
        """Todas las cajas abiertas en este momento, de todas las computadoras."""
        return self.db.consultar(
            """SELECT c.*, COALESCE(u.nombre, '') AS abierta_por_nombre FROM cajas c
               LEFT JOIN usuarios u ON u.id = c.abierta_por WHERE c.estado = 'abierta' ORDER BY c.puesto""")

    def requerir_abierta(self):
        caja = self.abierta()
        if caja is None:
            raise ErrorNegocio("La caja está cerrada. Abrí la caja para poder registrar esta operación.")
        return caja

    def obtener(self, caja_id: int):
        fila = self.db.uno(
            """SELECT c.*, COALESCE(ua.nombre, '') AS abierta_por_nombre, COALESCE(uc.nombre, '') AS cerrada_por_nombre
               FROM cajas c LEFT JOIN usuarios ua ON ua.id = c.abierta_por LEFT JOIN usuarios uc ON uc.id = c.cerrada_por
               WHERE c.id = ?""",
            (caja_id,),
        )
        if fila is None:
            raise ErrorNegocio("La jornada de caja no existe.")
        return fila

    def listar(self, limite: int = 400):
        """Jornadas de caja. El administrador ve las de todas las computadoras; un cajero, las de la suya."""
        filtro, params = ("", ()) if self.ctx.puede("cajas_todas") else ("WHERE c.puesto = ? COLLATE NOCASE", (self.puesto,))
        return self.db.consultar(
            f"""SELECT c.*, COALESCE(ua.nombre, '') AS abierta_por_nombre
               FROM cajas c LEFT JOIN usuarios ua ON ua.id = c.abierta_por {filtro} ORDER BY c.id DESC LIMIT ?""",
            (*params, limite),
        )

    def ultima(self):
        return self.db.uno("SELECT * FROM cajas WHERE puesto = ? COLLATE NOCASE ORDER BY id DESC LIMIT 1", (self.puesto,))

    # ---- operaciones -----------------------------------------------------
    def abrir(self, saldo_inicial_cent: int) -> int:
        self.ctx.requiere("caja")
        if saldo_inicial_cent < 0:
            raise ErrorNegocio("El saldo inicial no puede ser negativo.")
        with self.db.transaccion():
            if self.abierta() is not None:
                raise ErrorNegocio("Esta computadora ya tiene la caja abierta. Cerrala antes de abrir otra.")
            cur = self.db.ejecutar(
                "INSERT INTO cajas (abierta_en, abierta_por, saldo_inicial_cent, puesto) VALUES (?,?,?,?)",
                (ahora(), self.ctx.usuario_id, saldo_inicial_cent, self.puesto),
            )
            self.ctx.auditar("caja_abierta", "cajas", cur.lastrowid, f"{self.puesto}: saldo inicial {fmt_dinero(saldo_inicial_cent)}")
        return cur.lastrowid

    def registrar_movimiento(self, tipo: str, monto_cent: int, motivo: str) -> int:
        """Entrada o salida manual de efectivo (por ejemplo, pago a un proveedor o retiro)."""
        self.ctx.requiere("caja")
        if tipo not in ("entrada", "salida"):
            raise ErrorNegocio("El tipo de movimiento no es válido.")
        if monto_cent <= 0:
            raise ErrorNegocio("El importe debe ser mayor a cero.")
        if not (motivo or "").strip():
            raise ErrorNegocio("Escribí el motivo del movimiento.")
        with self.db.transaccion():
            caja = self.requerir_abierta()
            cur = self.db.ejecutar(
                "INSERT INTO movimientos_caja (caja_id, fecha, tipo, monto_cent, motivo, usuario_id) VALUES (?,?,?,?,?,?)",
                (caja["id"], ahora(), tipo, monto_cent, motivo.strip(), self.ctx.usuario_id),
            )
            self.ctx.auditar(f"caja_{tipo}", "cajas", caja["id"], f"{fmt_dinero(monto_cent)}: {motivo.strip()}")
        return cur.lastrowid

    def cerrar(self, efectivo_contado_cent: int, notas: str = "", caja_id: int | None = None) -> dict:
        """Cierra la caja de esta computadora. Con caja_id, un administrador puede cerrar la de otra
        (por ejemplo, si quedó abierta en una computadora que se apagó)."""
        self.ctx.requiere("caja")
        if efectivo_contado_cent < 0:
            raise ErrorNegocio("El efectivo contado no puede ser negativo.")
        with self.db.transaccion():
            if caja_id is None:
                caja = self.requerir_abierta()
            else:
                caja = self.obtener(caja_id)
                if caja["estado"] != "abierta":
                    raise ErrorNegocio("Esa caja ya está cerrada.")
                if caja["puesto"].lower() != self.puesto.lower():
                    self.ctx.requiere("cajas_todas")
            esperado = self.resumen(caja["id"])["efectivo_esperado_cent"]
            diferencia = efectivo_contado_cent - esperado
            self.db.ejecutar(
                """UPDATE cajas SET estado = 'cerrada', cerrada_en = ?, cerrada_por = ?, efectivo_esperado_cent = ?,
                   efectivo_contado_cent = ?, diferencia_cent = ?, notas = ? WHERE id = ? AND estado = 'abierta'""",
                (ahora(), self.ctx.usuario_id, esperado, efectivo_contado_cent, diferencia, (notas or "").strip(), caja["id"]),
            )
            self.ctx.auditar(
                "caja_cerrada", "cajas", caja["id"],
                f"{caja['puesto']}: esperado {fmt_dinero(esperado)}, contado {fmt_dinero(efectivo_contado_cent)}, diferencia {fmt_dinero(diferencia)}",
            )
        return self.resumen(caja["id"])

    def movimientos(self, caja_id: int):
        return self.db.consultar(
            """SELECT m.*, COALESCE(u.nombre, '') AS usuario FROM movimientos_caja m
               LEFT JOIN usuarios u ON u.id = m.usuario_id WHERE m.caja_id = ? ORDER BY m.id""",
            (caja_id,),
        )

    # ---- resumen ---------------------------------------------------------
    def resumen(self, caja_id: int) -> dict:
        """Resumen de una jornada de caja.

        Distingue lo vendido de lo realmente cobrado: un pago solo cuenta como
        ingreso si está confirmado, y cuenta en la caja en la que se confirmó.
        Cada pago es una única fila, por lo que no puede sumarse dos veces.
        """
        caja = self.obtener(caja_id)
        v = self.db.uno(
            """SELECT COUNT(*) AS cantidad, COALESCE(SUM(total_cent), 0) AS total,
                      COALESCE(SUM(descuento_cent), 0) AS descuentos
               FROM ventas WHERE caja_id = ? AND estado = 'completada'""",
            (caja_id,),
        )
        anuladas = self.db.uno(
            "SELECT COUNT(*) AS cantidad, COALESCE(SUM(total_cent), 0) AS total FROM ventas WHERE caja_id = ? AND estado = 'anulada'",
            (caja_id,),
        )
        cobrado = {m: 0 for m in MEDIOS}
        devuelto = {m: 0 for m in MEDIOS}
        comisiones = 0
        for f in self.db.consultar(
            """SELECT medio, tipo, SUM(monto_cent) AS monto, SUM(comision_cent) AS comision
               FROM pagos WHERE caja_id = ? AND estado = 'confirmado' GROUP BY medio, tipo""",
            (caja_id,),
        ):
            if f["tipo"] == "cobro":
                cobrado[f["medio"]] += f["monto"]
                if f["medio"] == "mercadopago":
                    comisiones += f["comision"] or 0
            else:
                devuelto[f["medio"]] += f["monto"]
        neto = {m: cobrado[m] - devuelto[m] for m in MEDIOS}
        pendientes = self.db.valor(
            """SELECT SUM(p.monto_cent) FROM pagos p JOIN ventas v ON v.id = p.venta_id
               WHERE v.caja_id = ? AND v.estado = 'completada' AND p.tipo = 'cobro' AND p.estado = 'pendiente'""",
            (caja_id,), 0,
        )
        mov = {"entrada": 0, "salida": 0}
        for f in self.db.consultar(
            "SELECT tipo, SUM(monto_cent) AS monto FROM movimientos_caja WHERE caja_id = ? GROUP BY tipo", (caja_id,)
        ):
            mov[f["tipo"]] = f["monto"]
        esperado = caja["saldo_inicial_cent"] + neto["efectivo"] + mov["entrada"] - mov["salida"]
        cerrada = caja["estado"] == "cerrada"
        return {
            "caja_id": caja_id,
            "puesto": caja["puesto"],
            "estado": caja["estado"],
            "abierta_en": caja["abierta_en"],
            "cerrada_en": caja["cerrada_en"],
            "abierta_por": caja["abierta_por_nombre"],
            "cerrada_por": caja["cerrada_por_nombre"],
            "notas": caja["notas"],
            "ventas_cantidad": v["cantidad"],
            "ventas_total_cent": v["total"],
            "descuentos_cent": v["descuentos"],
            "cobrado_total_cent": sum(neto.values()),
            "cobrado_cent": neto,
            "cobros_brutos_cent": cobrado,
            "pendientes_cent": pendientes,
            "devoluciones_cent": sum(devuelto.values()),
            "devoluciones_por_medio_cent": devuelto,
            "anuladas_cantidad": anuladas["cantidad"],
            "anuladas_total_cent": anuladas["total"],
            "mp_comisiones_cent": comisiones,
            "mp_neto_cent": neto["mercadopago"] - comisiones,
            "saldo_inicial_cent": caja["saldo_inicial_cent"],
            "entradas_cent": mov["entrada"],
            "salidas_cent": mov["salida"],
            "efectivo_esperado_cent": caja["efectivo_esperado_cent"] if cerrada else esperado,
            "efectivo_contado_cent": caja["efectivo_contado_cent"],
            "diferencia_cent": caja["diferencia_cent"],
        }
