"""Lado cliente: la interfaz usa un ContextoRemoto, que pide cada operación al servidor."""
from __future__ import annotations

import hashlib
import http.client
import socket
import ssl
import threading
from decimal import Decimal

from .. import __version__, preferencias
from ..core.dinero import D
from ..core.errores import ErrorNegocio, PermisoDenegado
from .codec import codificar, decodificar

# Preferencias de impresión: son de cada computadora, no del comercio.
CLAVES_LOCALES = ("impresora", "ticket_ancho", "ticket_imprimir_automatico")


class ErrorServidor(ErrorNegocio):
    """No se pudo hablar con el servidor."""


class HuellaDistinta(ErrorNegocio):
    """El servidor no es el mismo en el que se confió antes (o fue reinstalado)."""

    def __init__(self, huella: str):
        super().__init__(
            "El servidor al que te estás conectando no es el mismo de antes (o fue reinstalado). "
            "Si cambiaste o reinstalaste la computadora principal, podés volver a confiar en ella."
        )
        self.huella = huella


def _errores() -> dict:
    from ..integraciones.arca.transporte import ErrorConexion
    from ..integraciones.mercadopago import ErrorConexionMP
    from .servidor import SesionVencida

    return {"ErrorNegocio": ErrorNegocio, "PermisoDenegado": PermisoDenegado, "ErrorConexion": ErrorConexion,
            "ErrorConexionMP": ErrorConexionMP, "SesionVencida": SesionVencida}


class Cliente:
    """Conexión cifrada con el servidor. Cada hilo usa su propia conexión."""

    def __init__(self, host: str, puerto: int, huella: str = "", tiempo: int = 90):
        self.host, self.puerto, self.huella, self.tiempo = host.strip(), int(puerto), huella, tiempo
        self.sesion = ""
        self._local = threading.local()

    def _conexion(self) -> http.client.HTTPSConnection:
        conexion = getattr(self._local, "conexion", None)
        if conexion is not None:
            return conexion
        contexto = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        # El servidor usa un certificado propio: en vez de una autoridad, se verifica su huella.
        contexto.check_hostname = False
        contexto.verify_mode = ssl.CERT_NONE
        conexion = http.client.HTTPSConnection(self.host, self.puerto, timeout=self.tiempo, context=contexto)
        conexion.connect()
        huella = hashlib.sha256(conexion.sock.getpeercert(binary_form=True)).hexdigest()
        if self.huella and huella != self.huella:
            conexion.close()
            raise HuellaDistinta(huella)
        self.huella = huella  # primera vez: se confía en este servidor y se recuerda su huella
        self._local.conexion = conexion
        return conexion

    def _cerrar(self) -> None:
        conexion = getattr(self._local, "conexion", None)
        if conexion is not None:
            conexion.close()
            self._local.conexion = None

    def pedir(self, pedido: dict):
        cuerpo = codificar(pedido)
        for intento in (1, 2):
            reutilizada = getattr(self._local, "conexion", None) is not None
            try:
                conexion = self._conexion()
                conexion.request("POST", "/rpc", body=cuerpo, headers={"Content-Type": "application/json"})
                respuesta = conexion.getresponse()
                datos = respuesta.read()
                if respuesta.status != 200:
                    raise ErrorServidor("El servidor respondió con un error. Revisá que la dirección y el puerto sean los de Exa Pyme.")
                break
            except HuellaDistinta:
                raise
            except (http.client.HTTPException, ssl.SSLError, ConnectionError, socket.timeout, OSError) as e:
                self._cerrar()
                # Una conexión que quedó abierta sin uso puede haberse cortado: se reintenta una vez si es seguro.
                if intento == 1 and reutilizada and isinstance(
                        e, (http.client.RemoteDisconnected, ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
                    continue
                if isinstance(e, ErrorNegocio):
                    raise
                raise ErrorServidor(
                    f"No se pudo conectar con el servidor ({self.host}:{self.puerto}). Revisá que la computadora "
                    "principal esté encendida con Exa Pyme abierto, y que las dos estén en la misma red."
                ) from None
        respuesta = decodificar(datos)
        if respuesta.get("ok"):
            return respuesta.get("resultado")
        raise _errores().get(respuesta.get("error"), ErrorNegocio)(respuesta.get("mensaje") or "El servidor rechazó la operación.")

    def hola(self) -> dict:
        return self.pedir({"accion": "hola"})

    def ingresar(self, usuario: str, clave: str) -> dict:
        datos = self.pedir({"accion": "ingresar", "usuario": usuario, "clave": clave, "version": __version__})
        self.sesion = datos["sesion"]
        return datos

    def salir(self) -> None:
        if self.sesion:
            try:
                self.pedir({"accion": "salir", "sesion": self.sesion})
            except ErrorNegocio:
                pass
            self.sesion = ""
        self._cerrar()

    def llamar(self, servicio: str, metodo: str, *args, **kwargs):
        return self.pedir({"accion": "llamar", "sesion": self.sesion, "servicio": servicio, "metodo": metodo,
                           "args": list(args), "kwargs": kwargs})


class Remoto:
    """Representa un servicio del servidor: cada método llamado se pide por la red."""

    def __init__(self, cliente: Cliente, servicio: str):
        self._cliente, self._servicio = cliente, servicio

    def __getattr__(self, metodo: str):
        if metodo.startswith("_"):
            raise AttributeError(metodo)
        return lambda *args, **kwargs: self._cliente.llamar(self._servicio, metodo, *args, **kwargs)


class ArcaRemoto(Remoto):
    @property
    def entorno(self) -> str:
        return self.entorno_actual()


class ConfiguracionRemota:
    """Configuración del comercio (en el servidor), salvo la impresión, que es propia de cada computadora."""

    def __init__(self, cliente: Cliente):
        self._cliente = cliente

    def obtener(self, clave: str) -> str:
        if clave in CLAVES_LOCALES:
            return str(preferencias.leer().get(clave, ""))
        return self._cliente.llamar("config", "obtener", clave)

    def booleano(self, clave: str) -> bool:
        return self.obtener(clave) == "1"

    def decimal(self, clave: str) -> Decimal:
        try:
            return D(self.obtener(clave) or "0")
        except Exception:
            return Decimal(0)

    def entero(self, clave: str) -> int:
        try:
            return int(self.obtener(clave))
        except (TypeError, ValueError):
            return 0

    def guardar(self, valores: dict, auditar: bool = True) -> None:
        normalizar = lambda v: ("1" if v else "0") if isinstance(v, bool) else str(v)  # noqa: E731
        locales = {k: normalizar(v) for k, v in valores.items() if k in CLAVES_LOCALES}
        remotos = {k: normalizar(v) for k, v in valores.items() if k not in CLAVES_LOCALES}
        if locales:
            preferencias.guardar(**locales)
        if remotos:
            self._cliente.llamar("config", "guardar", remotos)


class ContextoRemoto:
    """Lo mismo que Contexto, pero los datos están en el servidor. Los permisos que valen son los del servidor;
    acá solo se usan para mostrar u ocultar opciones."""

    remoto = True
    db = None  # un cliente nunca tiene base de datos propia

    def __init__(self, cliente: Cliente):
        self.cliente = cliente
        self.usuario: dict | None = None
        self.permisos: set[str] = set()
        self.config = ConfiguracionRemota(cliente)
        for nombre in ("usuarios", "productos", "inventario", "clientes", "compras", "caja", "ventas", "reportes", "sistema"):
            setattr(self, nombre, Remoto(cliente, nombre))
        self.arca = ArcaRemoto(cliente, "arca")
        self.mp = Remoto(cliente, "mp")

    def ingresar(self, usuario: str, clave: str) -> dict:
        datos = self.cliente.ingresar(usuario, clave)
        self.usuario, self.permisos = datos["usuario"], set(datos["permisos"])
        return self.usuario

    @property
    def usuario_id(self):
        return self.usuario["id"] if self.usuario else None

    @property
    def es_admin(self) -> bool:
        return bool(self.usuario) and self.usuario["rol"] == "admin"

    def puede(self, permiso: str) -> bool:
        return bool(self.usuario) and ("*" in self.permisos or permiso in self.permisos)

    def requiere(self, permiso: str) -> None:
        if not self.puede(permiso):
            raise PermisoDenegado("Tu usuario no tiene permiso para hacer esta operación.")

    def auditoria(self, limite: int = 500):
        return self.sistema.auditoria(limite)
