from __future__ import annotations

import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from ..core.errores import ErrorNegocio
from ..core.util import hoy
from ..db.esquema import TABLAS_REQUERIDAS, VERSION_ESQUEMA
from ..registro import log
from ..rutas import carpeta_copias_predeterminada

PREFIJO = "MiComercio_"


def validar_copia(ruta: str | Path) -> dict:
    """Comprueba que el archivo sea una base de MiComercio sana. Lanza ErrorNegocio si no lo es."""
    ruta = Path(ruta)
    if not ruta.is_file() or ruta.stat().st_size == 0:
        raise ErrorNegocio("El archivo de la copia no existe o está vacío.")
    try:
        conn = sqlite3.connect(str(ruta))
        try:
            integridad = conn.execute("PRAGMA integrity_check").fetchone()[0]
            claves = conn.execute("PRAGMA foreign_key_check").fetchall()
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            tablas = {f[0] for f in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            if integridad == "ok" and TABLAS_REQUERIDAS <= tablas:
                ventas = conn.execute("SELECT COUNT(*) FROM ventas").fetchone()[0]
                productos = conn.execute("SELECT COUNT(*) FROM productos").fetchone()[0]
            # Deja la copia como un único archivo, sin archivos auxiliares.
            try:
                conn.execute("PRAGMA journal_mode = DELETE")
            except sqlite3.OperationalError:
                pass  # medio de solo lectura: la copia igual es válida
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        raise ErrorNegocio("El archivo elegido no es una copia de seguridad válida o está dañado.") from None
    if integridad != "ok" or claves:
        raise ErrorNegocio("La copia de seguridad está dañada: no pasó la verificación de integridad.")
    if not TABLAS_REQUERIDAS <= tablas or version < 1:
        raise ErrorNegocio("El archivo elegido no es una copia de seguridad de MiComercio.")
    if version > VERSION_ESQUEMA:
        raise ErrorNegocio("La copia fue creada con una versión más nueva de MiComercio. Actualizá el programa para restaurarla.")
    return {"version": version, "ventas": ventas, "productos": productos}


class Copias:
    def __init__(self, ctx):
        self.ctx = ctx
        self.db = ctx.db

    def carpeta(self) -> Path:
        elegida = self.ctx.config.obtener("copias_carpeta")
        if elegida:
            ruta = Path(elegida)
            try:
                ruta.mkdir(parents=True, exist_ok=True)
                return ruta
            except OSError:
                log.warning("No se pudo usar la carpeta de copias %s; se usa la predeterminada", elegida)
        return carpeta_copias_predeterminada()

    def crear(self, tipo: str = "manual", carpeta: Path | None = None) -> Path:
        """Crea una copia completa y verificada de la base de datos. tipo: manual | auto | antes_de_restaurar"""
        carpeta = carpeta or self.carpeta()
        if not os.path.isdir(carpeta):
            raise ErrorNegocio("La carpeta de copias de seguridad no está disponible.")
        marca = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        destino = Path(carpeta) / f"{PREFIJO}{marca}_{tipo}.db"
        temporal = destino.with_suffix(".tmp")
        try:
            copia = sqlite3.connect(str(temporal))
            try:
                self.db.conn.backup(copia)
            finally:
                copia.close()
            validar_copia(temporal)
            os.replace(temporal, destino)
        except OSError as e:
            log.exception("Error al crear la copia de seguridad")
            raise ErrorNegocio(f"No se pudo guardar la copia de seguridad en {carpeta}.\n{e}") from None
        finally:
            if temporal.exists():
                temporal.unlink()
        log.info("Copia de seguridad creada: %s", destino)
        return destino

    def listar(self) -> list[dict]:
        copias = []
        for archivo in self.carpeta().glob(f"{PREFIJO}*.db"):
            info = archivo.stat()
            partes = archivo.stem.split("_")
            copias.append({
                "ruta": archivo, "nombre": archivo.name, "tamano": info.st_size,
                "fecha": datetime.fromtimestamp(info.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "tipo": {"auto": "Automática", "manual": "Manual"}.get(partes[-1], "Antes de restaurar"),
            })
        return sorted(copias, key=lambda c: c["nombre"], reverse=True)

    def automatica_si_corresponde(self) -> Path | None:
        """Una copia automática por día, conservando solo las más recientes."""
        if not self.ctx.config.booleano("copias_automaticas"):
            return None
        if self.ctx.config.obtener("copias_ultima_automatica") == hoy():
            return None
        try:
            ruta = self.crear("auto")
        except ErrorNegocio:
            return None
        self.ctx.config.guardar({"copias_ultima_automatica": hoy()}, auditar=False)
        conservar = max(self.ctx.config.entero("copias_conservar"), 1)
        automaticas = [c for c in self.listar() if c["tipo"] == "Automática"]
        for vieja in automaticas[conservar:]:
            try:
                vieja["ruta"].unlink()
            except OSError:
                log.warning("No se pudo borrar la copia antigua %s", vieja["ruta"])
        return ruta

    def restaurar(self, ruta: str | Path) -> dict:
        """Reemplaza la base actual por una copia, solo después de verificarla.

        Antes de reemplazar se guarda una copia de la base actual, para poder volver atrás.
        """
        self.ctx.requiere("copias")
        ruta = Path(ruta)
        temporal = self.db.ruta.with_name("restaurar_tmp.db")
        try:
            shutil.copyfile(ruta, temporal)
        except OSError:
            raise ErrorNegocio("No se pudo leer el archivo de la copia de seguridad.") from None
        try:
            info = validar_copia(temporal)
            resguardo = self.crear("antes_de_restaurar", carpeta_copias_predeterminada())
            nombre_usuario = self.ctx.usuario["nombre"] if self.ctx.usuario else ""
            self.db.cerrar()
            try:
                os.replace(temporal, self.db.ruta)
                for sufijo in ("-wal", "-shm"):
                    auxiliar = Path(str(self.db.ruta) + sufijo)
                    if auxiliar.exists():
                        auxiliar.unlink()
                self.db.abrir()
            except Exception:
                log.exception("Falló la restauración; se vuelve a la base anterior")
                self.db.cerrar()
                shutil.copyfile(resguardo, self.db.ruta)
                self.db.abrir()
                raise ErrorNegocio("No se pudo restaurar la copia. Tus datos anteriores siguen intactos.") from None
        finally:
            if temporal.exists():
                temporal.unlink()
        # Los usuarios de la copia pueden ser otros: hay que volver a iniciar sesión.
        self.ctx.usuario = None
        with self.db.transaccion():
            self.ctx.auditar("copia_restaurada", "copias", None, f"{ruta.name} (restaurada por {nombre_usuario})")
        log.info("Copia restaurada: %s", ruta)
        info["resguardo"] = resguardo
        return info
