from __future__ import annotations

import hashlib
import hmac
import secrets

from ..core.errores import ErrorNegocio
from ..core.util import ahora
from .contexto import ROLES

ITERACIONES = 240_000
LARGO_MINIMO_CLAVE = 4


def _hash(clave: str, sal: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", clave.encode("utf-8"), sal, ITERACIONES).hex()


class Usuarios:
    def __init__(self, ctx):
        self.ctx = ctx
        self.db = ctx.db

    def hay_usuarios(self) -> bool:
        return self.db.valor("SELECT COUNT(*) FROM usuarios", defecto=0) > 0

    def listar(self):
        return self.db.consultar("SELECT id, usuario, nombre, rol, activo, creado_en FROM usuarios ORDER BY nombre")

    def _validar(self, usuario: str, nombre: str, rol: str) -> None:
        if not usuario.strip():
            raise ErrorNegocio("Escribí un nombre de usuario.")
        if not nombre.strip():
            raise ErrorNegocio("Escribí el nombre de la persona.")
        if rol not in ROLES:
            raise ErrorNegocio("El rol elegido no es válido.")

    def _validar_clave(self, clave: str) -> None:
        if len(clave) < LARGO_MINIMO_CLAVE:
            raise ErrorNegocio(f"La contraseña debe tener al menos {LARGO_MINIMO_CLAVE} caracteres.")

    def crear(self, usuario: str, nombre: str, clave: str, rol: str = "cajero") -> int:
        # El primer usuario se crea sin sesión iniciada y siempre es administrador.
        if self.hay_usuarios():
            self.ctx.requiere("usuarios")
        else:
            rol = "admin"
        self._validar(usuario, nombre, rol)
        self._validar_clave(clave)
        if self.db.uno("SELECT 1 FROM usuarios WHERE usuario = ?", (usuario.strip(),)):
            raise ErrorNegocio("Ya existe un usuario con ese nombre.")
        sal = secrets.token_bytes(16)
        with self.db.transaccion():
            cur = self.db.ejecutar(
                "INSERT INTO usuarios (usuario, nombre, rol, clave_hash, clave_sal, creado_en) VALUES (?,?,?,?,?,?)",
                (usuario.strip(), nombre.strip(), rol, _hash(clave, sal), sal.hex(), ahora()),
            )
            self.ctx.auditar("usuario_creado", "usuarios", cur.lastrowid, f"{usuario.strip()} ({rol})")
        return cur.lastrowid

    def iniciar_sesion(self, usuario: str, clave: str) -> dict:
        fila = self.db.uno("SELECT * FROM usuarios WHERE usuario = ?", (usuario.strip(),))
        correcto = False
        if fila is not None:
            correcto = hmac.compare_digest(_hash(clave, bytes.fromhex(fila["clave_sal"])), fila["clave_hash"])
        if not correcto:
            raise ErrorNegocio("El usuario o la contraseña no son correctos.")
        if not fila["activo"]:
            raise ErrorNegocio("Este usuario está desactivado. Consultá con el administrador.")
        self.ctx.usuario = {k: fila[k] for k in ("id", "usuario", "nombre", "rol")}
        return self.ctx.usuario

    def cambiar_clave(self, usuario_id: int, clave_nueva: str) -> None:
        if usuario_id != self.ctx.usuario_id:
            self.ctx.requiere("usuarios")
        self._validar_clave(clave_nueva)
        sal = secrets.token_bytes(16)
        with self.db.transaccion():
            self.db.ejecutar(
                "UPDATE usuarios SET clave_hash = ?, clave_sal = ? WHERE id = ?",
                (_hash(clave_nueva, sal), sal.hex(), usuario_id),
            )
            self.ctx.auditar("usuario_clave", "usuarios", usuario_id)

    def actualizar(self, usuario_id: int, nombre: str, rol: str, activo: bool) -> None:
        self.ctx.requiere("usuarios")
        fila = self.db.uno("SELECT * FROM usuarios WHERE id = ?", (usuario_id,))
        if fila is None:
            raise ErrorNegocio("El usuario no existe.")
        self._validar(fila["usuario"], nombre, rol)
        deja_de_ser_admin = fila["rol"] == "admin" and fila["activo"] and (rol != "admin" or not activo)
        if deja_de_ser_admin:
            otros = self.db.valor(
                "SELECT COUNT(*) FROM usuarios WHERE rol = 'admin' AND activo = 1 AND id <> ?", (usuario_id,)
            )
            if not otros:
                raise ErrorNegocio("Tiene que quedar al menos un administrador activo.")
        with self.db.transaccion():
            self.db.ejecutar(
                "UPDATE usuarios SET nombre = ?, rol = ?, activo = ? WHERE id = ?",
                (nombre.strip(), rol, 1 if activo else 0, usuario_id),
            )
            self.ctx.auditar("usuario_modificado", "usuarios", usuario_id, f"rol={rol} activo={int(activo)}")
