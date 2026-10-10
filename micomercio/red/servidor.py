"""Servidor: atiende a las computadoras cliente sobre la base de datos de esta computadora."""
from __future__ import annotations

import hashlib
import secrets
import socket
import ssl
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from .. import __version__
from ..core.errores import ErrorNegocio
from ..proteccion import desproteger, proteger
from ..registro import log
from ..rutas import carpeta_datos
from .codec import codificar, decodificar

TAMANO_MAXIMO = 30 * 1024 * 1024
INACTIVIDAD_MAXIMA = 12 * 60 * 60  # una sesión sin uso durante 12 horas se cierra
INTENTOS_MAXIMOS, BLOQUEO_SEGUNDOS = 5, 30

# Qué puede pedir un cliente. Lo que no figura acá no se puede llamar desde la red.
# None = todos los métodos públicos del servicio, menos los de BLOQUEADOS.
SERVICIOS = {
    "config": {"obtener", "booleano", "decimal", "entero", "guardar"},
    "usuarios": {"hay_usuarios", "listar", "crear", "cambiar_clave", "actualizar"},
    "productos": None, "inventario": None, "clientes": None, "compras": None, "caja": None, "ventas": None,
    "reportes": {"generar"},
    "arca": None,
    "mp": {"estado", "tiene_credencial", "guardar_credencial", "borrar_credencial", "cajas", "elegir_caja",
           "crear_sucursal_y_caja", "crear_cobro", "verificar", "cancelar", "verificar_pendientes", "pendientes"},
    "sistema": None,
}
# Métodos internos que no comprueban permisos por sí mismos: solo se usan dentro del servidor.
BLOQUEADOS = {
    "productos": {"actualizar_costo"},
    "inventario": {"mover"},
    "ventas": {"asociar_externo"},
}


def direcciones_locales() -> list[str]:
    """Direcciones IP de esta computadora en la red local, para informárselas a los clientes."""
    encontradas = []
    try:
        sonda = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sonda.connect(("10.255.255.255", 1))  # no envía nada: solo averigua qué interfaz se usaría
        encontradas.append(sonda.getsockname()[0])
        sonda.close()
    except OSError:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip not in encontradas:
                encontradas.append(ip)
    except OSError:
        pass
    return [ip for ip in encontradas if not ip.startswith("127.")] or ["127.0.0.1"]


def preparar_tls() -> tuple[ssl.SSLContext, str]:
    """Certificado propio del servidor (se crea la primera vez). Devuelve el contexto TLS y la huella SHA-256."""
    carpeta = carpeta_datos() / "red"
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta_cert, ruta_clave = carpeta / "servidor.crt", carpeta / "servidor.clave.dpapi"
    if not ruta_cert.exists() or not ruta_clave.exists():
        clave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        nombre = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Exa Pyme - servidor")])
        ahora = datetime.now(timezone.utc)
        certificado = (x509.CertificateBuilder().subject_name(nombre).issuer_name(nombre).public_key(clave.public_key())
                       .serial_number(x509.random_serial_number()).not_valid_before(ahora - timedelta(days=1))
                       .not_valid_after(ahora + timedelta(days=3650)).sign(clave, hashes.SHA256()))
        ruta_cert.write_bytes(certificado.public_bytes(serialization.Encoding.PEM))
        ruta_clave.write_bytes(proteger(clave.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())))
    certificado = x509.load_pem_x509_certificate(ruta_cert.read_bytes())
    huella = hashlib.sha256(certificado.public_bytes(serialization.Encoding.DER)).hexdigest()
    # ssl solo carga la clave desde un archivo: se descifra a un temporal que se borra enseguida.
    temporal = carpeta / f"clave_{secrets.token_hex(8)}.tmp"
    try:
        temporal.write_bytes(desproteger(ruta_clave.read_bytes()))
        contexto = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        contexto.minimum_version = ssl.TLSVersion.TLSv1_2
        contexto.load_cert_chain(str(ruta_cert), str(temporal))
    finally:
        temporal.unlink(missing_ok=True)
    return contexto, huella


class Sistema:
    """Operaciones que la interfaz hace con funciones sueltas y que, en red, tienen que correr en el servidor."""

    def __init__(self, ctx):
        self.ctx = ctx

    def auditoria(self, limite: int = 500):
        self.ctx.requiere("configuracion")
        return self.ctx.auditoria(limite)

    def html_ticket(self, venta_id: int) -> str:
        from ..servicios import tickets

        return tickets.html_ticket(self.ctx, venta_id)

    def html_cierre_caja(self, caja_id: int) -> str:
        from ..servicios import tickets

        return tickets.html_cierre_caja(self.ctx, caja_id)

    def html_comprobante(self, comprobante_id: int) -> str:
        from ..integraciones.arca import impreso

        return impreso.html_comprobante(self.ctx, comprobante_id)

    def importar_productos(self, texto: str) -> dict:
        from ..servicios import csv_io

        return csv_io.importar_productos_texto(self.ctx, texto)


@dataclass
class Sesion:
    ctx: object
    ip: str
    usuario: str
    ultimo_uso: float = field(default_factory=time.time)
    servicios: dict = field(default_factory=dict)


class Servidor:
    def __init__(self, db, puerto: int):
        self.db, self.puerto = db, int(puerto)
        self.sesiones: dict[str, Sesion] = {}
        self.fallos: dict[str, list[float]] = {}
        self.candado = threading.Lock()
        self.http: ThreadingHTTPServer | None = None
        self.huella = ""

    # ---- ciclo de vida ---------------------------------------------------
    def iniciar(self, direccion: str = "0.0.0.0") -> None:
        contexto, self.huella = preparar_tls()
        servidor = self

        class Manejador(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self):  # noqa: N802
                try:
                    largo = int(self.headers.get("Content-Length") or 0)
                    if self.path != "/rpc" or largo <= 0 or largo > TAMANO_MAXIMO:
                        self.send_error(400)
                        return
                    respuesta = servidor.atender(decodificar(self.rfile.read(largo)), self.client_address[0])
                    cuerpo = codificar(respuesta)
                except Exception:
                    log.exception("Error al atender a un cliente")
                    cuerpo = codificar({"ok": False, "error": "interno", "mensaje": "El servidor no pudo atender el pedido."})
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(cuerpo)))
                self.end_headers()
                self.wfile.write(cuerpo)

            def log_message(self, *args):
                pass

        try:
            self.http = ThreadingHTTPServer((direccion, self.puerto), Manejador)
        except OSError as e:
            raise ErrorNegocio(
                f"No se pudo abrir el puerto {self.puerto} para atender a las otras computadoras. "
                f"Puede estar usándolo otro programa: elegí otro puerto en Configuración → Red.\n{e}"
            ) from None
        self.http.daemon_threads = True
        self.http.socket = contexto.wrap_socket(self.http.socket, server_side=True)
        self.puerto = self.http.server_address[1]
        threading.Thread(target=self.http.serve_forever, name="servidor-exapyme", daemon=True).start()
        log.info("Servidor de red activo en el puerto %s", self.puerto)

    def detener(self) -> None:
        if self.http is not None:
            self.http.shutdown()
            self.http.server_close()
            self.http = None
        with self.candado:
            self.sesiones.clear()

    @property
    def activo(self) -> bool:
        return self.http is not None

    def conectados(self) -> list[dict]:
        limite = time.time() - INACTIVIDAD_MAXIMA
        with self.candado:
            for token in [t for t, s in self.sesiones.items() if s.ultimo_uso < limite]:
                del self.sesiones[token]
            return [{"usuario": s.usuario, "ip": s.ip, "hace": int(time.time() - s.ultimo_uso)} for s in self.sesiones.values()]

    # ---- pedidos ---------------------------------------------------------
    def atender(self, pedido: dict, ip: str) -> dict:
        try:
            accion = pedido.get("accion")
            if accion == "hola":
                from ..servicios import Contexto

                return {"ok": True, "resultado": {"version": __version__,
                                                  "comercio": Contexto(self.db).config.obtener("comercio_nombre")}}
            if accion == "ingresar":
                return {"ok": True, "resultado": self._ingresar(pedido, ip)}
            sesion = self._sesion(pedido.get("sesion"))
            if accion == "salir":
                with self.candado:
                    self.sesiones.pop(pedido.get("sesion"), None)
                return {"ok": True, "resultado": None}
            if accion == "llamar":
                return {"ok": True, "resultado": self._llamar(sesion, pedido)}
            raise ErrorNegocio("Pedido desconocido.")
        except ErrorNegocio as e:
            return {"ok": False, "error": type(e).__name__, "mensaje": str(e)}
        except Exception:
            log.exception("Error inesperado al atender un pedido de la red")
            return {"ok": False, "error": "interno",
                    "mensaje": "Ocurrió un problema inesperado en el servidor y la operación no se completó."}

    def _ingresar(self, pedido: dict, ip: str) -> dict:
        from ..servicios import Contexto
        from ..servicios.contexto import PERMISOS

        ahora = time.time()
        with self.candado:
            recientes = [t for t in self.fallos.get(ip, []) if ahora - t < BLOQUEO_SEGUNDOS]
            self.fallos[ip] = recientes
            if len(recientes) >= INTENTOS_MAXIMOS:
                raise ErrorNegocio("Demasiados intentos fallidos. Esperá medio minuto y volvé a probar.")
        if pedido.get("version") != __version__:
            raise ErrorNegocio(
                f"Esta computadora tiene la versión {pedido.get('version')} de Exa Pyme y el servidor la {__version__}. "
                "Las dos tienen que tener la misma versión: actualizá el programa."
            )
        ctx = Contexto(self.db)
        try:
            usuario = ctx.usuarios.iniciar_sesion(str(pedido.get("usuario", "")), str(pedido.get("clave", "")))
        except ErrorNegocio:
            with self.candado:
                self.fallos.setdefault(ip, []).append(ahora)
            raise
        token = secrets.token_urlsafe(32)
        with self.candado:
            self.sesiones[token] = Sesion(ctx, ip, usuario["nombre"])
        log.info("Ingreso desde la red: %s (%s)", usuario["usuario"], ip)
        return {"sesion": token, "usuario": usuario, "permisos": sorted(PERMISOS.get(usuario["rol"], set())),
                "version": __version__}

    def _sesion(self, token) -> Sesion:
        with self.candado:
            sesion = self.sesiones.get(token or "")
            if sesion is None or time.time() - sesion.ultimo_uso > INACTIVIDAD_MAXIMA:
                self.sesiones.pop(token or "", None)
                raise SesionVencida("La sesión con el servidor terminó. Cerrá el programa y volvé a ingresar.")
            sesion.ultimo_uso = time.time()
            return sesion

    def _objeto(self, sesion: Sesion, nombre: str):
        if nombre not in sesion.servicios:
            if nombre == "arca":
                from ..integraciones.arca.servicio import ServicioArca

                sesion.servicios[nombre] = ServicioArca(sesion.ctx)
            elif nombre == "mp":
                from ..integraciones.mercadopago import ServicioMercadoPago

                sesion.servicios[nombre] = ServicioMercadoPago(sesion.ctx)
            elif nombre == "sistema":
                sesion.servicios[nombre] = Sistema(sesion.ctx)
            else:
                sesion.servicios[nombre] = getattr(sesion.ctx, nombre)
        return sesion.servicios[nombre]

    def _llamar(self, sesion: Sesion, pedido: dict):
        servicio, metodo = str(pedido.get("servicio", "")), str(pedido.get("metodo", ""))
        permitidos = SERVICIOS.get(servicio, set()) if servicio in SERVICIOS else set()
        if (servicio not in SERVICIOS or metodo.startswith("_") or metodo in BLOQUEADOS.get(servicio, ())
                or (permitidos is not None and metodo not in permitidos)):
            log.warning("Pedido de red rechazado: %s.%s (%s)", servicio, metodo, sesion.ip)
            raise ErrorNegocio("Esa operación no está disponible desde otra computadora.")
        funcion = getattr(self._objeto(sesion, servicio), metodo, None)
        if not callable(funcion):
            raise ErrorNegocio("Esa operación no existe en el servidor.")
        args, kwargs = list(pedido.get("args") or []), dict(pedido.get("kwargs") or {})
        if (servicio, metodo) == ("config", "guardar"):
            args, kwargs = args[:1], {}  # desde la red siempre se comprueba el permiso y se registra
        return funcion(*args, **kwargs)


class SesionVencida(ErrorNegocio):
    pass
