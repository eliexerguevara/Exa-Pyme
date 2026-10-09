from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .esquema import migrar


class BaseDatos:
    """Conexión SQLite con claves foráneas activas y transacciones explícitas."""

    def __init__(self, ruta: str | Path):
        self.ruta = Path(ruta)
        self.conn: sqlite3.Connection | None = None
        self._nivel = 0
        self.abrir()

    def abrir(self) -> None:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        # isolation_level=None: las transacciones las abre y cierra transaccion()
        self.conn = sqlite3.connect(str(self.ruta), isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA synchronous = FULL")
        self._nivel = 0
        migrar(self)

    def cerrar(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    @contextmanager
    def transaccion(self):
        """Todo lo que se haga adentro se guarda completo o no se guarda nada."""
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
        return self.conn.execute(sql, params)

    def consultar(self, sql: str, params=()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    def uno(self, sql: str, params=()) -> sqlite3.Row | None:
        return self.conn.execute(sql, params).fetchone()

    def valor(self, sql: str, params=(), defecto=None):
        fila = self.conn.execute(sql, params).fetchone()
        if fila is None or fila[0] is None:
            return defecto
        return fila[0]
