from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from .esquema import migrar


class BaseDatos:
    """Conexión SQLite con claves foráneas activas y transacciones explícitas.

    Se puede usar desde varios hilos (la ventana y el servidor que atiende a las otras cajas):
    un candado garantiza que una transacción completa se ejecute sin que otro hilo se intercale.
    """

    def __init__(self, ruta: str | Path):
        self.ruta = Path(ruta)
        self.conn: sqlite3.Connection | None = None
        self.candado = threading.RLock()
        self._nivel = 0
        self.abrir()

    def abrir(self) -> None:
        with self.candado:
            self.ruta.parent.mkdir(parents=True, exist_ok=True)
            # isolation_level=None: las transacciones las abre y cierra transaccion()
            self.conn = sqlite3.connect(str(self.ruta), isolation_level=None, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA foreign_keys = ON")
            self.conn.execute("PRAGMA journal_mode = WAL")
            self.conn.execute("PRAGMA synchronous = FULL")
            self._nivel = 0
            migrar(self)

    def cerrar(self) -> None:
        with self.candado:
            if self.conn is not None:
                self.conn.close()
                self.conn = None

    @contextmanager
    def transaccion(self):
        """Todo lo que se haga adentro se guarda completo o no se guarda nada."""
        with self.candado:  # se mantiene tomado hasta terminar: otro hilo espera su turno
            if self._nivel > 0:
                self._nivel += 1
                try:
                    yield
                finally:
                    self._nivel -= 1
                return
            self.conn.execute("BEGIN IMMEDIATE")
            self._nivel = 1
            try:
                yield
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise
            else:
                self.conn.execute("COMMIT")
            finally:
                self._nivel = 0

    def ejecutar(self, sql: str, params=()) -> sqlite3.Cursor:
        with self.candado:
            return self.conn.execute(sql, params)

    def consultar(self, sql: str, params=()) -> list[sqlite3.Row]:
        with self.candado:
            return self.conn.execute(sql, params).fetchall()

    def uno(self, sql: str, params=()) -> sqlite3.Row | None:
        with self.candado:
            return self.conn.execute(sql, params).fetchone()

    def valor(self, sql: str, params=(), defecto=None):
        with self.candado:
            fila = self.conn.execute(sql, params).fetchone()
        if fila is None or fila[0] is None:
            return defecto
        return fila[0]
