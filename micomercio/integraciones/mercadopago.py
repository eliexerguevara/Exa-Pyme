"""Cobros con código QR de Mercado Pago, mediante su API oficial de Orders.

Cómo funciona:
    1. Al cobrar una venta se crea una orden (POST /v1/orders, tipo «qr») por el importe exacto.
    2. El cliente paga escaneando el QR que se muestra en pantalla (modo dinámico) o el QR
       impreso de la caja (modo estático).
    3. El programa consulta el estado de la orden (GET /v1/orders/{id}). El pago se da por
       cobrado únicamente cuando Mercado Pago informa que la orden está procesada y acreditada,
       por el mismo importe y con la misma referencia. Nunca por una captura de pantalla.

No se usan notificaciones (webhooks) porque un programa de escritorio no tiene una dirección
pública donde recibirlas: se consulta la API, que es el otro mecanismo oficial.

Credencial: el Access Token se guarda cifrado con DPAPI en
%LOCALAPPDATA%\\ExaPyme\\mercadopago\\credencial.dpapi. No está en el código fuente, en la
base de datos, en las copias de seguridad ni en los registros.

Referencia: https://www.mercadopago.com.ar/developers/es/reference/in-person-payments/qr-code/overview
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from ..core.dinero import a_centavos, de_centavos, fmt_dinero
from ..core.errores import ErrorNegocio
from ..proteccion import desproteger, proteger
from ..registro import log
from ..rutas import carpeta_datos

API = "https://api.mercadopago.com"
VENCIMIENTO = "PT10M"  # la orden vence a los 10 minutos si nadie la paga
MODOS = {
    "dynamic": "QR en la pantalla, distinto para cada venta",
    "static": "QR impreso de la caja (el del mostrador)",
    "hybrid": "Los dos: QR en pantalla y QR impreso",
}
MENSAJES = {
    "pos_not_found": "Mercado Pago no encuentra la caja configurada. Elegila de nuevo en Configuración → Mercado Pago.",
    "unauthorized": "Mercado Pago rechazó la credencial. Volvé a cargar el Access Token en Configuración → Mercado Pago.",
    "instore_order_locked_error": "El cliente está pagando en este momento: esperá unos segundos.",
    "order_already_canceled": "La orden ya no se puede cancelar porque cambió de estado.",
    "unsupported_site": "La cuenta de Mercado Pago no admite cobros con QR desde este país.",
}


class ErrorConexionMP(ErrorNegocio):
    """No hubo respuesta de Mercado Pago. No cambia el estado de ningún pago."""


@dataclass
class EstadoIntegracion:
    disponible: bool
    mensaje: str


@dataclass
class EstadoCobro:
    estado: str          # pendiente | confirmado | cancelado | vencido | rechazado | devuelto
    detalle: str = ""
    referencia: str = ""  # número de operación en Mercado Pago


def _enviar(metodo: str, url: str, cabeceras: dict, cuerpo: bytes | None) -> tuple[int, bytes]:
    try:
        pedido = urllib.request.Request(url, data=cuerpo, headers=cabeceras, method=metodo)
        with urllib.request.urlopen(pedido, timeout=20) as respuesta:
            return respuesta.status, respuesta.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except OSError:
        raise ErrorConexionMP("No se pudo conectar con Mercado Pago. Revisá la conexión a Internet.") from None


def _ruta_credencial():
    carpeta = carpeta_datos() / "mercadopago"
    carpeta.mkdir(parents=True, exist_ok=True)
    return carpeta / "credencial.dpapi"


def interpretar_orden(orden: dict, monto_cent: int, referencia_esperada: str) -> EstadoCobro:
    """Traduce el estado de una orden de Mercado Pago. Solo «confirmado» significa dinero acreditado."""
    estado = str(orden.get("status", ""))
    pagos = (orden.get("transactions") or {}).get("payments") or []
    pago = pagos[0] if pagos else {}
    referencia = str((pago.get("reference") or {}).get("id") or pago.get("reference_id") or "")
    if estado == "processed":
        try:
            total = a_centavos(Decimal(str(orden.get("total_amount"))))
        except (InvalidOperation, TypeError):
            total = -1
        if (total != monto_cent or str(orden.get("external_reference", "")) != referencia_esperada
                or pago.get("status") != "processed"):
            # Una orden paga que no coincide con la venta no confirma nada.
            log.warning("Orden de Mercado Pago procesada que no coincide con el pago esperado: %s", orden.get("id"))
            raise ErrorNegocio(
                "Mercado Pago informa un pago que no coincide con esta venta (importe o referencia distintos). "
                "No se confirmó. Revisalo en tu cuenta de Mercado Pago."
            )
        return EstadoCobro("confirmado", "Pago acreditado", referencia)
    if estado == "refunded":
        return EstadoCobro("devuelto", "El pago fue devuelto al cliente", referencia)
    if estado == "expired":
        return EstadoCobro("vencido", "El código QR venció sin que se pagara")
    if estado == "canceled":
        return EstadoCobro("cancelado", "El cobro fue cancelado")
    if estado == "failed":
        return EstadoCobro("rechazado", "Mercado Pago rechazó el pago")
    return EstadoCobro("pendiente", "Esperando el pago")


class ServicioMercadoPago:
    def __init__(self, ctx, transporte=_enviar):
        self.ctx, self.transporte = ctx, transporte

    # ---- credencial y llamadas ------------------------------------------
    def tiene_credencial(self) -> bool:
        return _ruta_credencial().exists()

    def _token(self) -> str:
        ruta = _ruta_credencial()
        if not ruta.exists():
            raise ErrorNegocio("Falta cargar la credencial de Mercado Pago en Configuración → Mercado Pago.")
        return desproteger(ruta.read_bytes()).decode("utf-8")

    def _pedir(self, metodo: str, ruta: str, cuerpo: dict | None = None, idempotencia: str | None = None,
               token: str | None = None) -> dict:
        cabeceras = {"Authorization": f"Bearer {token or self._token()}", "Content-Type": "application/json",
                     "User-Agent": "ExaPyme"}
        if idempotencia:
            cabeceras["X-Idempotency-Key"] = idempotencia
        datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
        codigo, contenido = self.transporte(metodo, API + ruta, cabeceras, datos)
        try:
            respuesta = json.loads(contenido) if contenido else {}
        except ValueError:
            respuesta = {}
        if 200 <= codigo < 300:
            return respuesta
        errores = respuesta.get("errors") if isinstance(respuesta, dict) else None
        clave = str((errores[0].get("code") if errores else None) or respuesta.get("error") or respuesta.get("code") or "")
        detalle = str((errores[0].get("message") if errores else None) or respuesta.get("message") or "")
        if codigo == 401:
            clave = "unauthorized"
        log.warning("Mercado Pago respondió %s a %s %s: %s %s", codigo, metodo, ruta.split("?")[0], clave, detalle)
        if codigo >= 500:
            raise ErrorConexionMP("Mercado Pago tiene un problema en este momento. Probá de nuevo en unos segundos.")
        error = ErrorNegocio(MENSAJES.get(clave) or f"Mercado Pago no aceptó la operación: {detalle or clave or codigo}")
        error.codigo = clave
        raise error

    def guardar_credencial(self, token: str) -> dict:
        """Comprueba el Access Token contra Mercado Pago y, si es válido, lo guarda cifrado."""
        self.ctx.requiere("configuracion")
        token = (token or "").strip()
        if not token.startswith(("APP_USR-", "TEST-")):
            raise ErrorNegocio("Eso no parece un Access Token de Mercado Pago: empieza con «APP_USR-».")
        cuenta = self._pedir("GET", "/users/me", token=token)
        if not cuenta.get("id"):
            raise ErrorNegocio("Mercado Pago no devolvió los datos de la cuenta.")
        _ruta_credencial().write_bytes(proteger(token.encode("utf-8")))
        nombre = cuenta.get("nickname") or cuenta.get("email") or str(cuenta["id"])
        anterior = self.ctx.config.obtener("mp_usuario_id")
        valores = {"mp_usuario_id": str(cuenta["id"]), "mp_cuenta": nombre}
        if anterior and anterior != str(cuenta["id"]):
            valores.update({"mp_caja": "", "mp_caja_nombre": "", "mp_caja_qr": ""})  # las cajas son de otra cuenta
        self.ctx.config.guardar(valores)
        return {"id": cuenta["id"], "nombre": nombre}

    def borrar_credencial(self) -> None:
        self.ctx.requiere("configuracion")
        _ruta_credencial().unlink(missing_ok=True)
        self.ctx.config.guardar({"mp_habilitado": False, "mp_usuario_id": "", "mp_cuenta": "", "mp_caja": "",
                                 "mp_caja_nombre": "", "mp_caja_qr": ""})

    def estado(self) -> EstadoIntegracion:
        cfg = self.ctx.config
        if not cfg.booleano("mp_habilitado"):
            return EstadoIntegracion(False, "El cobro automático con QR de Mercado Pago está desactivado. Los cobros con "
                                            "Mercado Pago se confirman a mano, después de verificarlos en la cuenta.")
        if not self.tiene_credencial():
            return EstadoIntegracion(False, "Falta cargar la credencial (Access Token) de Mercado Pago.")
        if not cfg.obtener("mp_caja"):
            return EstadoIntegracion(False, "Falta elegir la caja de Mercado Pago que va a recibir los cobros.")
        return EstadoIntegracion(True, f"Cobro con QR activo en la cuenta {cfg.obtener('mp_cuenta')}, "
                                       f"caja «{cfg.obtener('mp_caja_nombre')}».")

    # ---- sucursales y cajas ---------------------------------------------
    def cajas(self) -> list[dict]:
        """Cajas (puntos de venta) de la cuenta. Solo sirven las que tienen identificador externo."""
        datos = self._pedir("GET", "/v2/pos?limit=30")
        return [{"id": c.get("id"), "nombre": c.get("name") or "", "externo": c.get("external_id") or "",
                 "activa": c.get("status", "active") == "active", "qr": (c.get("qr_response") or {}).get("image") or ""}
                for c in datos.get("data") or datos.get("results") or []]

    def elegir_caja(self, caja: dict, modo: str) -> None:
        self.ctx.requiere("configuracion")
        if modo not in MODOS:
            raise ErrorNegocio("El modo de cobro no es válido.")
        if not caja.get("externo"):
            raise ErrorNegocio(
                "Esta caja no tiene identificador externo y no se puede usar desde un programa. "
                "Creá una caja nueva con el botón «Crear sucursal y caja»."
            )
        self.ctx.config.guardar({"mp_caja": caja["externo"], "mp_caja_nombre": caja["nombre"], "mp_caja_qr": caja.get("qr", ""),
                                 "mp_modo": modo})

    def crear_sucursal_y_caja(self, d: dict) -> dict:
        """Crea una sucursal con su caja. d: nombre, calle, numero, ciudad, provincia, latitud, longitud."""
        self.ctx.requiere("configuracion")
        for campo, nombre in [("nombre", "nombre del local"), ("calle", "calle"), ("numero", "número"),
                              ("ciudad", "ciudad"), ("provincia", "provincia")]:
            if not str(d.get(campo, "")).strip():
                raise ErrorNegocio(f"Completá el campo «{nombre}».")
        try:
            latitud, longitud = float(str(d["latitud"]).replace(",", ".")), float(str(d["longitud"]).replace(",", "."))
        except (KeyError, ValueError):
            raise ErrorNegocio("La latitud y la longitud deben ser números, por ejemplo -32,9468 y -60,6393.") from None
        usuario = self.ctx.config.obtener("mp_usuario_id")
        if not usuario:
            raise ErrorNegocio("Primero cargá la credencial de Mercado Pago.")
        sufijo = uuid.uuid4().hex[:8].upper()
        sucursal = self._pedir("POST", f"/users/{usuario}/stores", {
            "name": d["nombre"].strip(), "external_id": f"MCSUC{sufijo}",
            "location": {"street_number": str(d["numero"]).strip(), "street_name": d["calle"].strip(),
                         "city_name": d["ciudad"].strip(), "state_name": d["provincia"].strip(),
                         "latitude": latitud, "longitude": longitud, "reference": d["nombre"].strip()},
        })
        caja = self._pedir("POST", "/v2/pos", {
            "name": "Caja Exa Pyme", "store_id": str(sucursal.get("id")), "external_id": f"MCCAJA{sufijo}",
        }, idempotencia=str(uuid.uuid4()))
        return {"id": caja.get("id"), "nombre": caja.get("name") or "Caja Exa Pyme", "externo": caja.get("external_id") or f"MCCAJA{sufijo}",
                "activa": True, "qr": (caja.get("qr_response") or {}).get("image") or ""}

    # ---- cobros ----------------------------------------------------------
    def _pago(self, pago_id: int):
        pago = self.ctx.db.uno("SELECT * FROM pagos WHERE id = ?", (pago_id,))
        if pago is None or pago["medio"] != "mercadopago" or pago["tipo"] != "cobro":
            raise ErrorNegocio("El pago no es un cobro de Mercado Pago.")
        return pago

    @staticmethod
    def _referencia(pago) -> str:
        return f"MC-{pago['venta_id']}-{pago['id']}"

    def crear_cobro(self, pago_id: int) -> dict:
        """Crea la orden de cobro para un pago pendiente. Devuelve {orden, qr, modo}; qr es el contenido del QR a mostrar."""
        self.ctx.requiere("vender")
        estado = self.estado()
        if not estado.disponible:
            raise ErrorNegocio(estado.mensaje)
        pago = self._pago(pago_id)
        if pago["estado"] != "pendiente":
            raise ErrorNegocio("Este pago ya no está pendiente.")
        cfg = self.ctx.config
        importe = f"{de_centavos(pago['monto_cent']):.2f}"
        # Cada intento usa una referencia propia: Mercado Pago exige que no se repita entre órdenes.
        referencia = f"{self._referencia(pago)}-{uuid.uuid4().hex[:8]}"
        orden = self._pedir("POST", "/v1/orders", {
            "type": "qr", "total_amount": importe, "description": f"Venta N° {pago['venta_id']}",
            "external_reference": referencia, "expiration_time": VENCIMIENTO,
            "config": {"qr": {"external_pos_id": cfg.obtener("mp_caja"), "mode": cfg.obtener("mp_modo")}},
            "transactions": {"payments": [{"amount": importe}]},
        }, idempotencia=str(uuid.uuid4()))
        if not orden.get("id"):
            raise ErrorNegocio("Mercado Pago no devolvió el identificador del cobro.")
        with self.ctx.db.transaccion():
            self.ctx.ventas.asociar_externo(pago_id, str(orden["id"]))
            self.ctx.db.ejecutar("UPDATE pagos SET referencia = ? WHERE id = ?", (referencia, pago_id))
        return {"orden": str(orden["id"]), "qr": (orden.get("type_response") or {}).get("qr_data") or "",
                "modo": cfg.obtener("mp_modo"), "monto_cent": pago["monto_cent"]}

    def datos_consulta(self, pago_id: int) -> dict:
        """Lo necesario para consultar una orden sin tocar la base (sirve para hacerlo en segundo plano)."""
        pago = self._pago(pago_id)
        if not pago["id_externo"]:
            raise ErrorNegocio("Este pago no se cobró con el QR automático: verificalo en tu cuenta y confirmalo a mano.")
        return {"orden": pago["id_externo"], "monto_cent": pago["monto_cent"], "referencia": pago["referencia"], "token": self._token()}

    def consultar_orden(self, datos: dict) -> EstadoCobro:
        """Pregunta a Mercado Pago por la orden. Solo usa la red: no lee ni escribe la base."""
        orden = self._pedir("GET", f"/v1/orders/{quote(datos['orden'])}", token=datos["token"])
        return interpretar_orden(orden, datos["monto_cent"], datos["referencia"])

    def _comision(self, referencia: str) -> int:
        """Comisión que descontó Mercado Pago, si la informa. Si no se puede saber, 0 (se puede cargar a mano)."""
        if not referencia.isdigit():
            return 0
        try:
            pago = self._pedir("GET", f"/v1/payments/{referencia}")
            return max(0, a_centavos(sum(Decimal(str(f.get("amount") or 0)) for f in pago.get("fee_details") or []
                                         if f.get("fee_payer", "collector") == "collector")))
        except (ErrorNegocio, InvalidOperation, TypeError):
            return 0

    def aplicar(self, pago_id: int, cobro: EstadoCobro) -> str:
        """Lleva al sistema lo que informó Mercado Pago. Devuelve el estado en que quedó el pago."""
        pago = self._pago(pago_id)
        if pago["estado"] != "pendiente":
            return pago["estado"]
        if cobro.estado == "confirmado":
            comision = min(self._comision(cobro.referencia), pago["monto_cent"])
            self.ctx.ventas.confirmar_pago(pago_id, f"MP {cobro.referencia}" if cobro.referencia else "", comision)
            log.info("Pago %s confirmado por Mercado Pago (%s)", pago_id, fmt_dinero(pago["monto_cent"]))
            return "confirmado"
        if cobro.estado in ("vencido", "cancelado", "devuelto"):
            self.ctx.ventas.descartar_pago(pago_id, "cancelado")
            return "cancelado"
        if cobro.estado == "rechazado":
            self.ctx.ventas.descartar_pago(pago_id, "rechazado")
            return "rechazado"
        return "pendiente"

    def verificar(self, pago_id: int) -> str:
        """Consulta la orden y actualiza el pago. Para usar desde Historial de ventas."""
        self.ctx.requiere("caja")
        pago = self._pago(pago_id)
        if pago["estado"] != "pendiente":
            return pago["estado"]  # ya resuelto: no hay nada que consultar
        return self.aplicar(pago_id, self.consultar_orden(self.datos_consulta(pago_id)))

    def cancelar(self, pago_id: int) -> str:
        """Cancela el cobro en Mercado Pago. Si el cliente llegó a pagar justo antes, lo confirma en lugar de cancelarlo."""
        self.ctx.requiere("caja")
        pago = self._pago(pago_id)
        if pago["estado"] != "pendiente":
            return pago["estado"]
        datos = self.datos_consulta(pago_id)
        estado = self.aplicar(pago_id, self.consultar_orden(datos))
        if estado != "pendiente":
            return estado
        try:
            self._pedir("POST", f"/v1/orders/{quote(datos['orden'])}/cancel", idempotencia=str(uuid.uuid4()))
        except ErrorNegocio as e:
            if isinstance(e, ErrorConexionMP) or getattr(e, "codigo", "") == "instore_order_locked_error":
                raise
            # No se pudo cancelar porque cambió de estado: se vuelve a mirar qué pasó.
            return self.aplicar(pago_id, self.consultar_orden(datos))
        self.ctx.ventas.descartar_pago(pago_id, "cancelado")
        return "cancelado"

    def pendientes(self):
        return self.ctx.db.consultar(
            """SELECT p.* FROM pagos p JOIN ventas v ON v.id = p.venta_id
               WHERE p.medio = 'mercadopago' AND p.tipo = 'cobro' AND p.estado = 'pendiente'
                 AND p.id_externo IS NOT NULL AND v.estado = 'completada' ORDER BY p.id"""
        )

    def verificar_pendientes(self) -> dict:
        resultado = {"confirmado": 0, "cancelado": 0, "rechazado": 0, "pendiente": 0, "errores": []}
        for pago in self.pendientes():
            try:
                resultado[self.verificar(pago["id"])] += 1
            except ErrorConexionMP as e:
                resultado["errores"].append(str(e))
                break
            except ErrorNegocio as e:
                resultado["errores"].append(f"Venta N° {pago['venta_id']}: {e}")
        return resultado


def crear_servicio(ctx) -> ServicioMercadoPago:
    return ServicioMercadoPago(ctx)
