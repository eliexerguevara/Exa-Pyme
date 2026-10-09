"""Actualización del programa desde las versiones publicadas en GitHub.

Cada versión publicada (release) del repositorio trae dos archivos:
    ExaPyme.exe          el programa
    ExaPyme.exe.sha256   su suma de verificación

El programa consulta cuál es la última versión, descarga el .exe por HTTPS desde
ese repositorio, comprueba la suma y recién entonces reemplaza el ejecutable.
Los datos del comercio no se tocan: están en otra carpeta.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .. import __version__
from ..core.errores import ErrorNegocio
from ..registro import log

REPOSITORIO = "eliexerguevara/Exa-Pyme"
URL_REPOSITORIO = f"https://github.com/{REPOSITORIO}"
URL_ULTIMA_VERSION = f"https://api.github.com/repos/{REPOSITORIO}/releases/latest"
PREFIJO_DESCARGAS = f"{URL_REPOSITORIO}/releases/download/"
ARCHIVO = "ExaPyme.exe"
ARCHIVO_SUMA = ARCHIVO + ".sha256"
SUFIJO_ANTERIOR = ".anterior"
SUFIJO_NUEVO = ".nuevo"
ARGUMENTO_REINICIO = "--tras-actualizar"


@dataclass
class Actualizacion:
    version: str
    notas: str
    url_exe: str
    url_suma: str
    tamano: int


def version_tupla(texto: str) -> tuple[int, ...]:
    """'v1.10.2' -> (1, 10, 2)"""
    return tuple(int(n) for n in re.findall(r"\d+", texto.split("-")[0])[:4])


def _obtener(url: str, tiempo: int = 15) -> bytes:
    pedido = urllib.request.Request(url, headers={"User-Agent": f"ExaPyme/{__version__}", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(pedido, timeout=tiempo) as respuesta:
        return respuesta.read()


def buscar(version_actual: str = __version__, obtener=_obtener) -> Actualizacion | None:
    """Devuelve la actualización disponible, o None si ya se tiene la última versión."""
    try:
        datos = json.loads(obtener(URL_ULTIMA_VERSION))
    except urllib.error.HTTPError as e:
        if e.code == 404:  # todavía no hay ninguna versión publicada
            return None
        raise ErrorNegocio("No se pudo consultar si hay actualizaciones. Probá de nuevo más tarde.") from None
    except (OSError, ValueError):
        raise ErrorNegocio("No se pudo consultar si hay actualizaciones. Revisá la conexión a Internet.") from None

    etiqueta = str(datos.get("tag_name", ""))
    if not etiqueta or datos.get("draft") or datos.get("prerelease"):
        return None
    if version_tupla(etiqueta) <= version_tupla(version_actual):
        return None
    archivos = {a.get("name"): a for a in datos.get("assets", [])}
    exe, suma = archivos.get(ARCHIVO), archivos.get(ARCHIVO_SUMA)
    if not exe or not suma:
        log.warning("La versión %s no trae %s y %s", etiqueta, ARCHIVO, ARCHIVO_SUMA)
        return None
    urls = (exe.get("browser_download_url", ""), suma.get("browser_download_url", ""))
    if not all(u.startswith(PREFIJO_DESCARGAS) for u in urls):
        log.warning("La versión %s tiene direcciones de descarga inesperadas", etiqueta)
        return None
    return Actualizacion(etiqueta.lstrip("vV"), (datos.get("body") or "").strip(), urls[0], urls[1], int(exe.get("size") or 0))


def descargar(actualizacion: Actualizacion, destino: Path, progreso=None, obtener=_obtener, abrir=urllib.request.urlopen) -> Path:
    """Descarga el ejecutable nuevo y comprueba su suma SHA-256. progreso(descargado, total) es opcional."""
    destino = Path(destino)
    try:
        esperada = obtener(actualizacion.url_suma).decode("ascii", "ignore").split()[0].lower()
        if not re.fullmatch(r"[0-9a-f]{64}", esperada):
            raise ValueError("suma inválida")
        calculada, descargado = hashlib.sha256(), 0
        pedido = urllib.request.Request(actualizacion.url_exe, headers={"User-Agent": f"ExaPyme/{__version__}"})
        with abrir(pedido, timeout=30) as respuesta, open(destino, "wb") as archivo:
            total = int(respuesta.headers.get("Content-Length") or actualizacion.tamano or 0)
            primero = True
            while True:
                bloque = respuesta.read(256 * 1024)
                if not bloque:
                    break
                if primero and not bloque.startswith(b"MZ"):
                    raise ValueError("no es un ejecutable de Windows")
                primero = False
                archivo.write(bloque)
                calculada.update(bloque)
                descargado += len(bloque)
                if progreso:
                    progreso(descargado, total)
        if descargado == 0 or calculada.hexdigest() != esperada:
            raise ValueError("la suma de verificación no coincide")
    except PermissionError:
        raise ErrorNegocio(
            "No se pudo guardar la actualización en la carpeta del programa. "
            "Cerrá Exa Pyme, descargá la versión nueva desde la página y reemplazá el archivo a mano."
        ) from None
    except (OSError, ValueError) as e:
        log.warning("Falló la descarga de la actualización: %s", e)
        destino.unlink(missing_ok=True)
        if isinstance(e, ValueError):
            raise ErrorNegocio("La descarga llegó incompleta o dañada y se descartó. El programa no se modificó. "
                               "Probá de nuevo.") from None
        raise ErrorNegocio("No se pudo descargar la actualización. Revisá la conexión a Internet. "
                           "El programa no se modificó.") from None
    return destino


def ruta_ejecutable() -> Path | None:
    """Ruta de ExaPyme.exe cuando se ejecuta empaquetado; None en modo desarrollo."""
    return Path(sys.executable) if getattr(sys, "frozen", False) else None


def instalar(descargado: Path, exe: Path) -> None:
    """Reemplaza el ejecutable. Windows permite renombrar un .exe en uso, pero no sobrescribirlo:
    el actual pasa a llamarse *.anterior y el nuevo ocupa su lugar. Si algo falla, se deshace."""
    descargado, exe = Path(descargado), Path(exe)
    anterior = exe.with_name(exe.name + SUFIJO_ANTERIOR)
    try:
        anterior.unlink(missing_ok=True)
        os.replace(exe, anterior)
        try:
            os.replace(descargado, exe)
        except OSError:
            os.replace(anterior, exe)
            raise
    except OSError as e:
        log.exception("No se pudo reemplazar el ejecutable")
        raise ErrorNegocio(f"No se pudo instalar la actualización. El programa no se modificó.\n{e}") from None
    log.info("Ejecutable actualizado: %s", exe)


def actualizar(exe: Path, version_actual: str = __version__, progreso=None) -> Actualizacion | None:
    """Busca, descarga, verifica e instala. Devuelve la actualización instalada o None si no había."""
    actualizacion = buscar(version_actual)
    if actualizacion is None:
        return None
    nuevo = descargar(actualizacion, exe.with_name(exe.name + SUFIJO_NUEVO), progreso)
    instalar(nuevo, exe)
    return actualizacion


def reiniciar(exe: Path) -> None:
    """Abre la versión recién instalada. La instancia actual debe cerrarse enseguida."""
    entorno = dict(os.environ)
    # Sin esto, el .exe nuevo heredaría la carpeta temporal del proceso viejo de PyInstaller.
    entorno["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    subprocess.Popen([str(exe), ARGUMENTO_REINICIO], env=entorno, cwd=str(exe.parent), close_fds=True)


def limpiar_restos() -> None:
    """Borra, al arrancar, lo que dejó una actualización anterior."""
    exe = ruta_ejecutable()
    if exe is None:
        return
    for sufijo in (SUFIJO_ANTERIOR, SUFIJO_NUEVO):
        try:
            exe.with_name(exe.name + sufijo).unlink(missing_ok=True)
        except OSError:
            pass  # todavía en uso: se borra en el próximo arranque


def actualizar_sin_interfaz(ruta_resultado: str | None = None) -> int:
    """ExaPyme.exe --actualizar [archivo_resultado]: actualiza sin abrir ventanas. Devuelve 0 si salió bien."""
    codigo = 0
    try:
        exe = ruta_ejecutable()
        if exe is None:
            raise ErrorNegocio("La actualización automática solo funciona en el programa instalado (ExaPyme.exe).")
        instalada = actualizar(exe)
        mensaje = f"ACTUALIZADO {instalada.version}" if instalada else f"AL DIA {__version__}"
    except ErrorNegocio as e:
        codigo, mensaje = 1, f"ERROR {e}"
    if ruta_resultado:
        Path(ruta_resultado).write_text(mensaje, encoding="utf-8")
    return codigo
