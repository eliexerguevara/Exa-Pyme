from __future__ import annotations

from ..core.errores import ErrorNegocio
from ..core.util import ahora

TIPOS_DOCUMENTO = ["DNI", "CUIT", "CUIL", "Pasaporte", "Otro"]
CONDICIONES_IVA = [
    "Consumidor final", "Responsable inscripto", "Monotributista", "Exento", "No categorizado",
]
CAMPOS = ("nombre", "tipo_documento", "documento", "condicion_iva", "telefono", "email", "direccion", "notas")


class Clientes:
    def __init__(self, ctx):
        self.ctx = ctx
        self.db = ctx.db

    def buscar(self, texto: str = "", solo_activos: bool = True):
        donde, params = [], []
        if texto.strip():
            donde.append("(nombre LIKE ? OR documento LIKE ? OR telefono LIKE ?)")
            params += [f"%{texto.strip()}%"] * 3
        if solo_activos:
            donde.append("activo = 1")
        return self.db.consultar(
            f"SELECT * FROM clientes {'WHERE ' + ' AND '.join(donde) if donde else ''} ORDER BY nombre COLLATE NOCASE",
            params,
        )

    def obtener(self, cliente_id: int):
        fila = self.db.uno("SELECT * FROM clientes WHERE id = ?", (cliente_id,))
        if fila is None:
            raise ErrorNegocio("El cliente no existe.")
        return fila

    def guardar(self, datos: dict, cliente_id: int | None = None) -> int:
        self.ctx.requiere("clientes")
        valores = {c: (datos.get(c) or "").strip() for c in CAMPOS}
        if not valores["nombre"]:
            raise ErrorNegocio("Escribí el nombre del cliente.")
        valores["tipo_documento"] = valores["tipo_documento"] or "DNI"
        valores["condicion_iva"] = valores["condicion_iva"] or "Consumidor final"
        with self.db.transaccion():
            if cliente_id is None:
                cur = self.db.ejecutar(
                    f"INSERT INTO clientes ({', '.join(CAMPOS)}, creado_en) VALUES ({', '.join('?' * len(CAMPOS))}, ?)",
                    (*valores.values(), ahora()),
                )
                return cur.lastrowid
            self.db.ejecutar(
                f"UPDATE clientes SET {', '.join(c + ' = ?' for c in CAMPOS)} WHERE id = ?",
                (*valores.values(), cliente_id),
            )
            return cliente_id

    def cambiar_estado(self, cliente_id: int, activo: bool) -> None:
        self.ctx.requiere("clientes")
        with self.db.transaccion():
            self.db.ejecutar("UPDATE clientes SET activo = ? WHERE id = ?", (1 if activo else 0, cliente_id))
