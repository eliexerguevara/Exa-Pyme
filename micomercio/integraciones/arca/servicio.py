"""Reglas de la facturación electrónica: qué comprobante corresponde, numeración, reintentos y notas de crédito."""
from __future__ import annotations

import json
import sqlite3
from datetime import date

from ...core.dinero import D, fmt_dinero
from ...core.errores import ErrorNegocio
from ...core.precios import desglosar_centavos
from ...core.util import ahora, rango_dias
from ...registro import log
from . import (
    ALICUOTAS_IVA, CONDICIONES_RECEPTOR, DOC_CONSUMIDOR_FINAL, DOCUMENTOS, NOMBRES_CLASE, TIPOS_COMPROBANTE,
    EstadoFiscal, credenciales, cuit_valido, letra_comprobante, solo_digitos, wsaa,
)
from .transporte import ErrorConexion, enviar
from .wsfe import Wsfe

SELECT = """
    SELECT c.*, v.fecha AS venta_fecha, v.estado AS venta_estado
    FROM comprobantes_fiscales c JOIN ventas v ON v.id = c.venta_id
"""


def numero_completo(c) -> str:
    """'B 00001-00000012'"""
    if c["numero"] is None:
        return ""
    return f"{c['letra']} {int(c['punto_venta']):05d}-{int(c['numero']):08d}"


class ServicioArca:
    def __init__(self, ctx, transporte=enviar):
        self.ctx, self.db, self.transporte = ctx, ctx.db, transporte

    # ---- configuración ---------------------------------------------------
    @property
    def entorno(self) -> str:
        return "produccion" if self.ctx.config.obtener("fiscal_entorno") == "produccion" else "homologacion"

    @property
    def cuit(self) -> str:
        return solo_digitos(self.ctx.config.obtener("fiscal_cuit"))

    def entorno_actual(self) -> str:
        return self.entorno

    # ---- certificado (vive en la computadora que tiene los datos) ----------
    def estado_certificado(self) -> dict:
        return credenciales.estado(self.entorno)

    def generar_pedido(self) -> bytes:
        self.ctx.requiere("facturacion")
        cfg = self.ctx.config
        return credenciales.generar_pedido(self.entorno, cfg.obtener("fiscal_cuit"), cfg.obtener("fiscal_razon_social"))

    def importar_certificado(self, contenido: bytes) -> dict:
        self.ctx.requiere("facturacion")
        return credenciales.importar_certificado(self.entorno, contenido, self.ctx.config.obtener("fiscal_cuit"))

    def importar_clave(self, contenido: bytes) -> None:
        self.ctx.requiere("facturacion")
        credenciales.importar_clave(self.entorno, contenido)

    def datos_completos(self) -> list[str]:
        """Datos fiscales que faltan para poder facturar."""
        cfg, faltan = self.ctx.config, []
        if not cfg.obtener("fiscal_razon_social"):
            faltan.append("Razón social")
        if not cuit_valido(cfg.obtener("fiscal_cuit")):
            faltan.append("CUIT válido")
        if not cfg.obtener("fiscal_condicion_iva"):
            faltan.append("Condición frente al IVA")
        if not cfg.obtener("fiscal_domicilio"):
            faltan.append("Domicilio comercial")
        if not cfg.obtener("fiscal_punto_venta").isdigit() or int(cfg.obtener("fiscal_punto_venta")) < 1:
            faltan.append("Punto de venta autorizado")
        return faltan

    def estado(self) -> EstadoFiscal:
        if not self.ctx.config.booleano("fiscal_habilitado"):
            return EstadoFiscal(False, "La facturación electrónica está desactivada. Las ventas se guardan con "
                                       "comprobante interno (ticket no válido como factura).")
        faltan = self.datos_completos()
        if faltan:
            return EstadoFiscal(False, "Faltan datos fiscales del comercio: " + ", ".join(faltan) + ".")
        cert = credenciales.estado(self.entorno)["certificado"]
        if cert is None or not credenciales.estado(self.entorno)["clave"]:
            return EstadoFiscal(False, "Falta cargar el certificado de ARCA para este entorno.")
        if cert["vencido"]:
            return EstadoFiscal(False, f"El certificado de ARCA venció el {cert['hasta']}. Hay que generar uno nuevo.")
        if self.entorno == "homologacion":
            return EstadoFiscal(True, "Facturación electrónica activa en HOMOLOGACIÓN: los comprobantes son de prueba "
                                      "y no tienen validez fiscal.")
        return EstadoFiscal(True, "Facturación electrónica activa en producción.")

    def _requerir_disponible(self) -> None:
        estado = self.estado()
        if not estado.disponible:
            raise ErrorNegocio(estado.mensaje)

    def _wsfe(self) -> Wsfe:
        return Wsfe(self.entorno, self.cuit, lambda forzar: wsaa.obtener_ticket(self.entorno, self.transporte, forzar),
                    self.transporte)

    def probar_conexion(self) -> list[str]:
        """Comprueba, paso a paso, que se puede facturar. Devuelve líneas para mostrar al usuario."""
        self.ctx.requiere("facturacion")
        lineas = []
        servidores = Wsfe(self.entorno, self.cuit, None, self.transporte).dummy()
        lineas.append("Servidores de ARCA: " + ", ".join(f"{k} {v}" for k, v in servidores.items()))
        faltan = self.datos_completos()
        if faltan:
            raise ErrorNegocio("\n".join(lineas) + "\n\nFaltan datos fiscales: " + ", ".join(faltan) + ".")
        ticket = wsaa.obtener_ticket(self.entorno, self.transporte)
        lineas.append(f"Acceso con el certificado: correcto (ticket válido hasta las {ticket.vence.astimezone():%H:%M}).")
        punto = int(self.ctx.config.obtener("fiscal_punto_venta"))
        for letra in sorted({l for (l, _) in TIPOS_COMPROBANTE if self._letra_posible(l)}):
            ultimo = self._wsfe().ultimo_autorizado(punto, TIPOS_COMPROBANTE[(letra, "factura")])
            lineas.append(f"Punto de venta {punto}, Factura {letra}: último número autorizado {ultimo}.")
        return lineas

    def _letra_posible(self, letra: str) -> bool:
        emisor = self.ctx.config.obtener("fiscal_condicion_iva")
        return letra == "C" if emisor in ("Monotributista", "Exento") else letra in ("A", "B")

    # ---- armado del comprobante -----------------------------------------
    def armar(self, venta_id: int) -> dict:
        """Calcula los datos fiscales de la factura de una venta. No guarda ni envía nada."""
        cfg = self.ctx.config
        v = self.ctx.ventas.obtener(venta_id)
        if v["total_cent"] <= 0:
            raise ErrorNegocio("No se puede facturar una venta con total cero.")
        cliente = self.ctx.clientes.obtener(v["cliente_id"]) if v["cliente_id"] else None
        condicion = cliente["condicion_iva"] if cliente else "Consumidor final"
        letra = letra_comprobante(cfg.obtener("fiscal_condicion_iva"), condicion)
        if letra is None:
            raise ErrorNegocio("Cargá la condición frente al IVA del comercio en los datos fiscales.")

        doc_tipo, doc_nro = DOC_CONSUMIDOR_FINAL, "0"
        if cliente and solo_digitos(cliente["documento"]):
            doc_tipo, doc_nro = DOCUMENTOS.get(cliente["tipo_documento"], 99), solo_digitos(cliente["documento"])
        if letra == "A" and (doc_tipo != DOCUMENTOS["CUIT"] or not cuit_valido(doc_nro)):
            raise ErrorNegocio(
                f"Para emitir una Factura A, el cliente «{cliente['nombre']}» debe tener cargado un CUIT válido "
                "(tipo de documento CUIT)."
            )

        por_alicuota: dict[str, int] = {}
        for item in self.ctx.ventas.items(venta_id):
            por_alicuota[item["impuesto_pct"]] = por_alicuota.get(item["impuesto_pct"], 0) + item["total_cent"]
        alicuotas, neto, iva = [], 0, 0
        if letra == "C":
            neto = v["total_cent"]  # en comprobantes C no se discrimina IVA
        else:
            for pct, total in sorted(por_alicuota.items(), key=lambda par: float(par[0])):
                if total == 0:
                    continue
                if pct not in ALICUOTAS_IVA:
                    raise ErrorNegocio(
                        f"La venta tiene productos con Impuestos {pct.replace('.', ',')} %, que no es una alícuota de IVA "
                        "válida para facturar (0, 2,5, 5, 10,5, 21 o 27 %). Corregí el producto."
                    )
                base, importe = desglosar_centavos(total, pct)
                alicuotas.append([ALICUOTAS_IVA[pct], base, importe])
                neto += base
                iva += importe
        return {
            "venta_id": venta_id, "letra": letra, "punto_venta": int(cfg.obtener("fiscal_punto_venta")),
            "doc_tipo": doc_tipo, "doc_nro": doc_nro, "condicion_receptor": CONDICIONES_RECEPTOR.get(condicion, 5),
            "total_cent": v["total_cent"], "neto_cent": neto, "iva_cent": iva, "alicuotas": alicuotas,
            "receptor": {
                "nombre": cliente["nombre"] if cliente else "Consumidor final", "condicion": condicion,
                "documento": f"{cliente['tipo_documento']} {cliente['documento']}" if cliente and cliente["documento"] else "",
                "domicilio": cliente["direccion"] if cliente else "",
            },
            "emisor": {
                "razon_social": cfg.obtener("fiscal_razon_social"), "domicilio": cfg.obtener("fiscal_domicilio"),
                "condicion": cfg.obtener("fiscal_condicion_iva"), "ingresos_brutos": cfg.obtener("fiscal_ingresos_brutos"),
                "inicio_actividades": cfg.obtener("fiscal_inicio_actividades"),
            },
        }

    def _insertar(self, d: dict, clase: str, asociado_id: int | None = None) -> int:
        return self.db.ejecutar(
            """INSERT INTO comprobantes_fiscales (venta_id, comprobante_asociado_id, entorno, tipo, punto_venta, estado,
               total_cent, solicitado_en, clase, letra, fecha, doc_tipo, doc_nro, condicion_receptor, neto_cent, iva_cent,
               alicuotas, cuit_emisor, receptor, emisor, usuario_id)
               VALUES (?,?,?,?,?, 'pendiente', ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                d["venta_id"], asociado_id, self.entorno, TIPOS_COMPROBANTE[(d["letra"], clase)], d["punto_venta"],
                d["total_cent"], ahora(), clase, d["letra"], date.today().strftime("%Y%m%d"), d["doc_tipo"], d["doc_nro"],
                d["condicion_receptor"], d["neto_cent"], d["iva_cent"], json.dumps(d["alicuotas"]), self.cuit,
                json.dumps(d["receptor"], ensure_ascii=False), json.dumps(d["emisor"], ensure_ascii=False),
                self.ctx.usuario_id,
            ),
        ).lastrowid

    def _marcar_venta(self, venta_id: int, estado: str) -> None:
        # El estado fiscal de la venta solo refleja comprobantes reales: los de homologación son pruebas.
        if self.entorno == "produccion":
            self.db.ejecutar("UPDATE ventas SET estado_fiscal = ? WHERE id = ?", (estado, venta_id))

    # ---- consultas -------------------------------------------------------
    def obtener(self, comprobante_id: int):
        fila = self.db.uno(SELECT + " WHERE c.id = ?", (comprobante_id,))
        if fila is None:
            raise ErrorNegocio("El comprobante no existe.")
        return fila

    def _vigente(self, venta_id: int, clase: str, estados=("autorizada", "pendiente")):
        marcas = ",".join("?" * len(estados))
        return self.db.uno(
            SELECT + f" WHERE c.venta_id = ? AND c.entorno = ? AND c.clase = ? AND c.parcial = 0 AND c.estado IN ({marcas}) ORDER BY c.id DESC",
            (venta_id, self.entorno, clase, *estados),
        )

    def comprobantes(self, venta_id: int):
        return self.db.consultar(SELECT + " WHERE c.venta_id = ? AND c.entorno = ? ORDER BY c.id", (venta_id, self.entorno))

    def pendientes(self):
        return self.db.consultar(SELECT + " WHERE c.entorno = ? AND c.estado = 'pendiente' ORDER BY c.id", (self.entorno,))

    def ventas(self, desde: str, hasta: str) -> list[dict]:
        """Ventas del período con su situación fiscal en el entorno actual."""
        inicio, fin = rango_dias(desde, hasta)
        filas = []
        for v in self.db.consultar(
            """SELECT v.id, v.fecha, v.total_cent, v.estado, COALESCE(c.nombre, 'Consumidor final') AS cliente
               FROM ventas v LEFT JOIN clientes c ON c.id = v.cliente_id
               WHERE v.fecha >= ? AND v.fecha < ? ORDER BY v.id DESC""",
            (inicio, fin),
        ):
            comprobantes = self.comprobantes(v["id"])
            factura = next((c for c in reversed(comprobantes) if c["clase"] == "factura" and c["estado"] != "rechazada"), None)
            nota = next((c for c in reversed(comprobantes)
                         if c["clase"] == "nota_credito" and c["estado"] != "rechazada" and not c["parcial"]), None)
            parciales = [c for c in comprobantes if c["parcial"] and c["estado"] == "autorizada"]
            rechazada = next((c for c in reversed(comprobantes) if c["estado"] == "rechazada"), None)
            if nota is not None and nota["estado"] == "autorizada":
                situacion, texto = "nota_credito", f"Anulada con nota de crédito {numero_completo(nota)}"
            elif nota is not None:
                situacion, texto = "pendiente", "Nota de crédito pendiente de autorización"
            elif factura is not None and factura["estado"] == "autorizada":
                situacion, texto = "autorizada", f"Factura {numero_completo(factura)}"
                if parciales:
                    texto += f" · {len(parciales)} nota(s) de crédito parcial(es)"
            elif factura is not None:
                situacion, texto = "pendiente", "Factura pendiente de autorización"
            elif rechazada is not None:
                situacion, texto = "rechazada", "Rechazada por ARCA"
            else:
                situacion, texto = "sin_comprobante", "Sin comprobante fiscal"
            filas.append({**dict(v), "situacion": situacion, "texto": texto, "factura": factura, "nota": nota,
                          "parciales": parciales,
                          "motivo": rechazada["respuesta"] if rechazada is not None and situacion == "rechazada" else ""})
        return filas

    # ---- emisión ---------------------------------------------------------
    def autorizar_venta(self, venta_id: int):
        """Emite la factura de una venta y devuelve el comprobante autorizado.

        Si la venta ya tiene factura, devuelve esa (no factura dos veces). Si no hay
        respuesta de ARCA, el comprobante queda pendiente y se lanza ErrorConexion.
        """
        self.ctx.requiere("vender")
        self._requerir_disponible()
        existente = self._vigente(venta_id, "factura")
        if existente is not None:
            return existente if existente["estado"] == "autorizada" else self._resolver(existente["id"])
        v = self.ctx.ventas.obtener(venta_id)
        if v["estado"] != "completada":
            raise ErrorNegocio("No se puede facturar una venta anulada.")
        datos = self.armar(venta_id)
        try:
            with self.db.transaccion():
                comprobante_id = self._insertar(datos, "factura")
                self._marcar_venta(venta_id, "pendiente")
        except sqlite3.IntegrityError:
            # Otra caja empezó a facturar esta misma venta en el mismo instante.
            raise ErrorNegocio("Esta venta ya se está facturando desde otra computadora. Actualizá la lista.") from None
        return self._resolver(comprobante_id)

    def reintentar(self, comprobante_id: int):
        self.ctx.requiere("vender")
        self._requerir_disponible()
        c = self.obtener(comprobante_id)
        if c["estado"] != "pendiente":
            return c
        c = self._resolver(comprobante_id)
        if c["parcial"] and c["devolucion_id"] is None:
            c = self._completar_parcial(c)  # la nota quedó autorizada: falta registrar la devolución
        return c

    def descartar_pendiente(self, comprobante_id: int) -> None:
        """Descarta un comprobante pendiente que nunca llegó a enviarse a ARCA (todavía no tiene número).

        Si ya se le asignó un número no se puede descartar: ARCA pudo haberlo autorizado y hay que reintentar
        para averiguarlo.
        """
        self.ctx.requiere("facturacion")
        c = self.obtener(comprobante_id)
        if c["estado"] != "pendiente":
            raise ErrorNegocio("Este comprobante ya no está pendiente.")
        if c["numero"] is not None:
            raise ErrorNegocio(
                "Este comprobante ya se envió a ARCA y no se sabe si quedó autorizado. Usá «Reintentar pendientes» "
                "cuando haya conexión: el programa lo averigua y lo resuelve."
            )
        with self.db.transaccion():
            self.db.ejecutar("UPDATE comprobantes_fiscales SET estado = 'rechazada', respuesta = ? WHERE id = ?",
                             ("Descartado antes de enviarse a ARCA.", comprobante_id))
            if c["clase"] == "factura":
                self._marcar_venta(c["venta_id"], "sin_comprobante")

    def reintentar_pendientes(self) -> dict:
        resultado = {"autorizados": 0, "fallidos": []}
        for c in self.pendientes():
            try:
                self.reintentar(c["id"])
                resultado["autorizados"] += 1
            except ErrorConexion as e:
                resultado["fallidos"].append(str(e))
                break  # sin conexión no tiene sentido seguir
            except ErrorNegocio as e:
                resultado["fallidos"].append(f"Venta N° {c['venta_id']}: {e}")
        return resultado

    def _resolver(self, comprobante_id: int):
        """Lleva un comprobante pendiente a autorizado o rechazado hablando con ARCA."""
        c = self.obtener(comprobante_id)
        tipo, punto = int(c["tipo"]), int(c["punto_venta"])
        try:
            wsfe = self._wsfe()
            # Un intento anterior pudo haber llegado a ARCA sin que llegara la respuesta:
            # antes de pedir otro número se consulta si aquel comprobante quedó autorizado.
            if c["numero"] is not None:
                previo = wsfe.consultar(punto, tipo, int(c["numero"]))
                if previo and self._es_el_mismo(previo, c):
                    return self._autorizado(c, previo["cae"], previo["cae_vencimiento"], "Recuperado de ARCA tras un corte.")
            numero = wsfe.ultimo_autorizado(punto, tipo) + 1
            fecha = date.today().strftime("%Y%m%d")
            with self.db.transaccion():
                self.db.ejecutar("UPDATE comprobantes_fiscales SET numero = ?, fecha = ?, respuesta = '' WHERE id = ?",
                                 (numero, fecha, comprobante_id))
            pedido = {
                "tipo": tipo, "punto_venta": punto, "numero": numero, "fecha": fecha, "doc_tipo": c["doc_tipo"],
                "doc_nro": c["doc_nro"], "condicion_receptor": c["condicion_receptor"], "total_cent": c["total_cent"],
                "neto_cent": c["neto_cent"], "iva_cent": c["iva_cent"], "alicuotas": json.loads(c["alicuotas"]),
            }
            if c["comprobante_asociado_id"]:
                a = self.obtener(c["comprobante_asociado_id"])
                pedido["asociado"] = {"tipo": int(a["tipo"]), "punto_venta": int(a["punto_venta"]), "numero": int(a["numero"]),
                                      "cuit": a["cuit_emisor"], "fecha": a["fecha"]}
            respuesta = wsfe.solicitar_cae(pedido)
        except ErrorConexion as e:
            with self.db.transaccion():
                self.db.ejecutar("UPDATE comprobantes_fiscales SET respuesta = ? WHERE id = ?", (str(e), comprobante_id))
            raise ErrorConexion(f"{e} El comprobante quedó PENDIENTE de autorización: reintentalo desde Facturación.") from None

        c = self.obtener(comprobante_id)
        if respuesta.aprobado:
            return self._autorizado(c, respuesta.cae, respuesta.cae_vencimiento, " ".join(respuesta.observaciones))
        log.warning("ARCA rechazó el comprobante %s: %s", comprobante_id, respuesta.motivo())
        with self.db.transaccion():
            self.db.ejecutar("UPDATE comprobantes_fiscales SET estado = 'rechazada', respuesta = ? WHERE id = ?",
                             (respuesta.motivo(), comprobante_id))
            if c["clase"] == "factura":
                self._marcar_venta(c["venta_id"], "sin_comprobante")
            self.ctx.auditar("comprobante_rechazado", "comprobantes_fiscales", comprobante_id, respuesta.motivo()[:300])
        raise ErrorNegocio("ARCA rechazó el comprobante:\n" + respuesta.motivo())

    @staticmethod
    def _es_el_mismo(previo: dict, c) -> bool:
        try:
            mismo_total = round(float(previo["total"]) * 100) == c["total_cent"]
        except ValueError:
            return False
        return mismo_total and previo["fecha"] == c["fecha"] and str(previo["doc_nro"]) == str(c["doc_nro"])

    def _autorizado(self, c, cae: str, vencimiento: str, observaciones: str):
        if not (len(cae) == 14 and cae.isdigit()):
            raise ErrorNegocio("ARCA no devolvió un CAE válido. El comprobante sigue pendiente.")
        with self.db.transaccion():
            self.db.ejecutar(
                """UPDATE comprobantes_fiscales SET estado = 'autorizada', cae = ?, cae_vencimiento = ?, autorizado_en = ?,
                   observaciones = ?, respuesta = '' WHERE id = ? AND estado = 'pendiente'""",
                (cae, vencimiento, ahora(), observaciones, c["id"]),
            )
            if c["clase"] == "factura":
                self._marcar_venta(c["venta_id"], "autorizada")
            self.ctx.auditar("comprobante_autorizado", "comprobantes_fiscales", c["id"],
                             f"{NOMBRES_CLASE[c['clase']]} {numero_completo(self.obtener(c['id']))} · {fmt_dinero(c['total_cent'])} · {self.entorno}")
        return self.obtener(c["id"])

    # ---- nota de crédito -------------------------------------------------
    def emitir_nota_credito(self, venta_id: int, motivo: str):
        """Emite la nota de crédito por el total de la factura y, en producción, anula la venta."""
        self.ctx.requiere("anular")
        self._requerir_disponible()
        motivo = (motivo or "").strip()
        if not motivo:
            raise ErrorNegocio("Escribí el motivo de la nota de crédito.")
        factura = self._vigente(venta_id, "factura", ("autorizada",))
        if factura is None:
            raise ErrorNegocio("Esta venta no tiene una factura autorizada en este entorno.")
        if self.db.uno("SELECT 1 FROM comprobantes_fiscales WHERE venta_id = ? AND entorno = ? AND parcial = 1 "
                       "AND estado IN ('autorizada', 'pendiente')", (venta_id, self.entorno)):
            raise ErrorNegocio(
                "Esta venta ya tiene notas de crédito parciales. Para devolver lo que queda, registrá otra devolución "
                "desde Historial de ventas con los productos restantes."
            )
        v = self.ctx.ventas.obtener(venta_id)
        real = self.entorno == "produccion"
        if real and v["estado"] == "completada" and v["cobrado_cent"] > 0:
            self.ctx.caja.requerir_abierta()  # la devolución del dinero se registra en la caja

        nota = self._vigente(venta_id, "nota_credito")
        if nota is None:
            datos = {
                "venta_id": venta_id, "letra": factura["letra"], "punto_venta": int(factura["punto_venta"]),
                "doc_tipo": factura["doc_tipo"], "doc_nro": factura["doc_nro"],
                "condicion_receptor": factura["condicion_receptor"], "total_cent": factura["total_cent"],
                "neto_cent": factura["neto_cent"], "iva_cent": factura["iva_cent"],
                "alicuotas": json.loads(factura["alicuotas"]), "receptor": json.loads(factura["receptor"]),
                "emisor": json.loads(factura["emisor"]),
            }
            with self.db.transaccion():
                nota_id = self._insertar(datos, "nota_credito", factura["id"])
            nota = self._resolver(nota_id)
        elif nota["estado"] == "pendiente":
            nota = self._resolver(nota["id"])
        if real:
            if self.ctx.ventas.obtener(venta_id)["estado"] == "completada":
                self.ctx.ventas.anular(venta_id, f"{motivo} (nota de crédito {numero_completo(nota)})", con_nota_credito=True)
            with self.db.transaccion():
                self._marcar_venta(venta_id, "nota_credito")
        return nota

    # ---- nota de crédito parcial (devolución de algunos productos) ---------
    def nota_credito_parcial(self, venta_id: int, cantidades: dict, motivo: str, medio: str = "efectivo"):
        """Emite una nota de crédito por los productos devueltos y, cuando ARCA la autoriza, registra la devolución.

        Solo corresponde en producción y con la venta facturada. Si un corte dejó una nota autorizada sin su
        devolución registrada, se completa esa en lugar de emitir otra.
        """
        self.ctx.requiere("anular")
        self._requerir_disponible()
        motivo = (motivo or "").strip()
        if not motivo:
            raise ErrorNegocio("Escribí el motivo de la devolución.")
        if self.entorno != "produccion":
            raise ErrorNegocio("En homologación las devoluciones se registran sin nota de crédito.")
        factura = self._vigente(venta_id, "factura", ("autorizada",))
        if factura is None:
            raise ErrorNegocio("Esta venta no tiene una factura autorizada.")
        colgada = self.db.uno(
            SELECT + """ WHERE c.venta_id = ? AND c.entorno = ? AND c.parcial = 1 AND c.devolucion_id IS NULL
                         AND c.estado IN ('autorizada', 'pendiente') ORDER BY c.id""",
            (venta_id, self.entorno),
        )
        if colgada is not None:
            if colgada["estado"] == "pendiente":
                colgada = self._resolver(colgada["id"])
            return self._completar_parcial(colgada)

        self.ctx.ventas.validar_devolucion(venta_id, medio, con_nota_credito=True)
        calculo = self.ctx.ventas.calcular_devolucion(venta_id, cantidades)
        if calculo["total_cent"] <= 0:
            raise ErrorNegocio("La devolución no tiene importe: no corresponde una nota de crédito.")
        alicuotas, neto, iva = [], 0, 0
        if factura["letra"] == "C":
            neto = calculo["total_cent"]
        else:
            por_alicuota: dict[str, int] = {}
            for l in calculo["lineas"]:
                por_alicuota[l["impuesto_pct"]] = por_alicuota.get(l["impuesto_pct"], 0) + l["total_cent"]
            for pct, total in sorted(por_alicuota.items(), key=lambda par: float(par[0])):
                if total == 0:
                    continue
                base, importe = desglosar_centavos(total, pct)
                alicuotas.append([ALICUOTAS_IVA[pct], base, importe])
                neto += base
                iva += importe
        datos = {
            "venta_id": venta_id, "letra": factura["letra"], "punto_venta": int(factura["punto_venta"]),
            "doc_tipo": factura["doc_tipo"], "doc_nro": factura["doc_nro"], "condicion_receptor": factura["condicion_receptor"],
            "total_cent": calculo["total_cent"], "neto_cent": neto, "iva_cent": iva, "alicuotas": alicuotas,
            "receptor": json.loads(factura["receptor"]), "emisor": json.loads(factura["emisor"]),
        }
        detalle = {"cantidades": {str(k): str(v) for k, v in cantidades.items()}, "motivo": motivo, "medio": medio,
                   "lineas": calculo["lineas"]}
        with self.db.transaccion():
            nota_id = self._insertar(datos, "nota_credito", factura["id"])
            self.db.ejecutar("UPDATE comprobantes_fiscales SET parcial = 1, devolucion_json = ? WHERE id = ?",
                             (json.dumps(detalle, ensure_ascii=False), nota_id))
        return self._completar_parcial(self._resolver(nota_id))

    def _completar_parcial(self, nota):
        """Registra la devolución que corresponde a una nota de crédito parcial ya autorizada."""
        if nota["estado"] != "autorizada":
            raise ErrorNegocio("La nota de crédito todavía no fue autorizada por ARCA.")
        detalle = json.loads(nota["devolucion_json"])
        devolucion_id = self.ctx.ventas.devolver(
            nota["venta_id"], {int(k): D(v) for k, v in detalle["cantidades"].items()},
            f"{detalle['motivo']} (nota de crédito {numero_completo(nota)})", detalle["medio"], con_nota_credito=True,
        )
        with self.db.transaccion():
            self.db.ejecutar("UPDATE comprobantes_fiscales SET devolucion_id = ? WHERE id = ?", (devolucion_id, nota["id"]))
        return self.obtener(nota["id"])
