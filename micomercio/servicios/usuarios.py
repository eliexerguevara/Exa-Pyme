from __future__ import annotations

import hashlib
import hmac
import secrets
import time

from ..core.errores import ErrorNegocio
from ..core.util import ahora
from .contexto import ROLES

ITERACIONES = 240_000
LARGO_MINIMO_CLAVE = 4
# Código de recuperación: 20 caracteres sin letras ni números que se confundan (0/O, 1/I).
ALFABETO_CODIGO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
DEMORA_FALLO = 1.0  # segundos de espera tras un código incorrecto


def _normalizar_codigo(codigo: str) -> str:
    return "".join(c for c in (codigo or "").upper() if c.isalnum())


def _nuevo_codigo() -> str:
    crudo = "".join(secrets.choice(ALFABETO_CODIGO) for _ in range(20))
    return "-".join(crudo[i:i + 4] for i in range(0, 20, 4))


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

    # ---- recuperación de la contraseña del administrador -------------------
    def tiene_codigo(self, usuario_id: int | None = None) -> bool:
        fila = self.db.uno("SELECT recuperacion_hash FROM usuarios WHERE id = ?", (usuario_id or self.ctx.usuario_id,))
        return bool(fila and fila["recuperacion_hash"])

    def _guardar_codigo(self, usuario_id: int) -> str:
        codigo, sal = _nuevo_codigo(), secrets.token_bytes(16)
        self.db.ejecutar("UPDATE usuarios SET recuperacion_hash = ?, recuperacion_sal = ? WHERE id = ?",
                         (_hash(_normalizar_codigo(codigo), sal), sal.hex(), usuario_id))
        return codigo

    def generar_codigo_recuperacion(self) -> str:
        """Crea un código de recuperación para el administrador que tiene la sesión iniciada y lo devuelve.

        Es la única vez que se puede ver: en la base queda solo su huella. El código anterior deja de servir.
        """
        if not self.ctx.es_admin:
            raise ErrorNegocio("El código de recuperación es solo para administradores. La contraseña de un cajero "
                               "la cambia un administrador desde Configuración → Usuarios.")
        with self.db.transaccion():
            codigo = self._guardar_codigo(self.ctx.usuario_id)
            self.ctx.auditar("codigo_recuperacion", "usuarios", self.ctx.usuario_id, "Se generó un código de recuperación nuevo")
        return codigo

    def recuperar(self, usuario: str, codigo: str, clave_nueva: str) -> str:
        """Cambia la contraseña de un administrador que la olvidó, usando su código de recuperación.

        No hace falta tener la sesión iniciada. El código sirve una sola vez: se devuelve uno nuevo.
        """
        self._validar_clave(clave_nueva)
        fila = self.db.uno("SELECT * FROM usuarios WHERE usuario = ?", ((usuario or "").strip(),))
        correcto = False
        if fila is not None and fila["rol"] == "admin" and fila["activo"] and fila["recuperacion_hash"]:
            correcto = hmac.compare_digest(
                _hash(_normalizar_codigo(codigo), bytes.fromhex(fila["recuperacion_sal"])), fila["recuperacion_hash"])
        if not correcto:
            time.sleep(DEMORA_FALLO)
            raise ErrorNegocio("El usuario o el código de recuperación no son correctos.")
        sal = secrets.token_bytes(16)
        with self.db.transaccion():
            self.db.ejecutar("UPDATE usuarios SET clave_hash = ?, clave_sal = ? WHERE id = ?",
                             (_hash(clave_nueva, sal), sal.hex(), fila["id"]))
            nuevo = self._guardar_codigo(fila["id"])
            self.ctx.auditar("clave_recuperada", "usuarios", fila["id"],
                             f"{fila['usuario']} cambió su contraseña con el código de recuperación")
        return nuevo

    def administradores(self):
        return self.db.consultar("SELECT id, usuario, nombre FROM usuarios WHERE rol = 'admin' AND activo = 1 ORDER BY nombre")

    def restablecer_sin_codigo(self, usuario_id: int, clave_nueva: str) -> None:
        """Último recurso, para quien perdió la contraseña y el código: solo se usa desde la herramienta
        ExaPyme.exe --restablecer-clave, en la computadora que tiene los datos. Queda registrado y el programa
        lo avisa en el próximo ingreso de un administrador."""
        self._validar_clave(clave_nueva)
        fila = self.db.uno("SELECT * FROM usuarios WHERE id = ? AND rol = 'admin' AND activo = 1", (usuario_id,))
        if fila is None:
            raise ErrorNegocio("Elegí un administrador activo.")
        sal = secrets.token_bytes(16)
        with self.db.transaccion():
            self.db.ejecutar(
                "UPDATE usuarios SET clave_hash = ?, clave_sal = ?, recuperacion_hash = NULL, recuperacion_sal = NULL WHERE id = ?",
                (_hash(clave_nueva, sal), sal.hex(), usuario_id))
            self.ctx.config.guardar({"seguridad_aviso": f"{ahora()}|{fila['usuario']}"}, auditar=False)
            self.ctx.auditar("clave_restablecida", "usuarios", usuario_id,
                             f"Contraseña de {fila['usuario']} restablecida sin código, desde la herramienta de emergencia")

    def aviso_de_seguridad(self) -> str:
        """Texto para mostrar al administrador si su contraseña fue restablecida sin código. Se muestra una vez."""
        if not self.ctx.es_admin:
            return ""
        valor = self.ctx.config.obtener("seguridad_aviso")
        if not valor:
            return ""
        self.ctx.config.guardar({"seguridad_aviso": ""})
        fecha, _, usuario = valor.partition("|")
        return (f"La contraseña del administrador «{usuario}» fue restablecida el {fecha[:16]} con la herramienta de "
                "emergencia, sin usar el código de recuperación.\n\nSi no fuiste vos, alguien tuvo acceso a la "
                "computadora principal: cambiá la contraseña y revisá el registro de operaciones.")
