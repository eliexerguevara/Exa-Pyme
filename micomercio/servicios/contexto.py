"""Punto de acceso único a los servicios: base de datos, usuario actual y permisos."""
from __future__ import annotations

from ..core.errores import PermisoDenegado
from ..core.util import ahora
from ..db import BaseDatos

# Permisos por rol. Para agregar un rol nuevo alcanza con sumarlo acá
# (y al CHECK de la tabla usuarios mediante una migración).
PERMISOS = {
    "admin": {"*"},
    "cajero": {"vender", "caja", "productos_ver", "clientes", "historial"},
}
ROLES = {"admin": "Administrador", "cajero": "Cajero"}
# Nombre de la caja de la computadora principal (y de las jornadas anteriores a tener varias cajas).
PUESTO_PRINCIPAL = "Caja principal"


class Contexto:
    def __init__(self, db: BaseDatos):
        self.db = db
        self.usuario: dict | None = None
        self.puesto = PUESTO_PRINCIPAL  # nombre de esta computadora como caja

        from .caja import Caja
        from .clientes import Clientes
        from .compras import Compras
        from .configuracion import Configuracion
        from .copias import Copias
        from .inventario import Inventario
        from .productos import Productos
        from .reportes import Reportes
        from .usuarios import Usuarios
        from .ventas import Ventas

        self.config = Configuracion(self)
        self.usuarios = Usuarios(self)
        self.productos = Productos(self)
        self.inventario = Inventario(self)
        self.clientes = Clientes(self)
        self.compras = Compras(self)
        self.caja = Caja(self)
        self.ventas = Ventas(self)
        self.reportes = Reportes(self)
        self.copias = Copias(self)

    # ---- usuario y permisos ---------------------------------------------
    @property
    def usuario_id(self) -> int | None:
        return self.usuario["id"] if self.usuario else None

    @property
    def es_admin(self) -> bool:
        return bool(self.usuario) and self.usuario["rol"] == "admin"

    def puede(self, permiso: str) -> bool:
        if not self.usuario:
            return False
        permisos = PERMISOS.get(self.usuario["rol"], set())
        return "*" in permisos or permiso in permisos

    def requiere(self, permiso: str) -> None:
        if not self.puede(permiso):
            raise PermisoDenegado("Tu usuario no tiene permiso para hacer esta operación.")

    # ---- auditoría -------------------------------------------------------
    def auditar(self, accion: str, entidad: str = "", entidad_id: int | None = None, detalle: str = "") -> None:
        self.db.ejecutar(
            "INSERT INTO auditoria (fecha, usuario_id, accion, entidad, entidad_id, detalle) VALUES (?,?,?,?,?,?)",
            (ahora(), self.usuario_id, accion, entidad, entidad_id, detalle),
        )

    def auditoria(self, limite: int = 500):
        return self.db.consultar(
            """SELECT a.*, COALESCE(u.nombre, '') AS usuario
               FROM auditoria a LEFT JOIN usuarios u ON u.id = a.usuario_id
               ORDER BY a.id DESC LIMIT ?""",
            (limite,),
        )
