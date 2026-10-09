import hashlib
import io
import json
import urllib.error

import pytest

from micomercio.core.errores import ErrorNegocio
from micomercio.servicios import actualizador as act

EXE = b"MZ" + b"contenido del programa nuevo" * 1000
BASE = act.PREFIJO_DESCARGAS + "v1.2.0/"


def publicacion(etiqueta="v1.2.0", archivos=("ExaPyme.exe", "ExaPyme.exe.sha256"), base=BASE, **extra):
    datos = {"tag_name": etiqueta, "body": "Mejoras varias", "draft": False, "prerelease": False,
             "assets": [{"name": n, "browser_download_url": base + n, "size": len(EXE)} for n in archivos]}
    datos.update(extra)
    return lambda url: json.dumps(datos).encode()


class Respuesta(io.BytesIO):
    headers = {"Content-Length": str(len(EXE))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def test_comparacion_de_versiones():
    assert act.version_tupla("v1.10.2") > act.version_tupla("1.9.9")
    assert act.version_tupla("v1.1.0") == act.version_tupla("1.1.0")


def test_detecta_version_nueva():
    a = act.buscar("1.1.0", publicacion())
    assert (a.version, a.notas, a.url_exe) == ("1.2.0", "Mejoras varias", BASE + "ExaPyme.exe")
    assert act.buscar("1.2.0", publicacion()) is None           # ya está al día
    assert act.buscar("2.0.0", publicacion()) is None           # nunca vuelve a una versión anterior


def test_ignora_publicaciones_que_no_sirven():
    assert act.buscar("1.0.0", publicacion(archivos=("ExaPyme.exe",))) is None          # sin suma de verificación
    assert act.buscar("1.0.0", publicacion(prerelease=True)) is None
    assert act.buscar("1.0.0", publicacion(base="https://otro-sitio.example/")) is None    # descarga fuera del repositorio

    def sin_versiones(url):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    assert act.buscar("1.0.0", sin_versiones) is None

    def sin_internet(url):
        raise OSError("sin red")

    with pytest.raises(ErrorNegocio):
        act.buscar("1.0.0", sin_internet)


def test_descarga_verifica_la_suma(tmp_path):
    a = act.buscar("1.1.0", publicacion())
    correcta = hashlib.sha256(EXE).hexdigest().encode() + b"  ExaPyme.exe\n"
    avances = []
    destino = act.descargar(a, tmp_path / "nuevo.exe", lambda h, t: avances.append((h, t)),
                            obtener=lambda url: correcta, abrir=lambda pedido, timeout: Respuesta(EXE))
    assert destino.read_bytes() == EXE and avances[-1] == (len(EXE), len(EXE))

    for contenido, suma in [(EXE + b"x", correcta), (EXE, b"0" * 64), (b"<html>error</html>", correcta), (EXE, b"basura")]:
        with pytest.raises(ErrorNegocio):
            act.descargar(a, tmp_path / "malo.exe", obtener=lambda url: suma, abrir=lambda pedido, timeout: Respuesta(contenido))
        assert not (tmp_path / "malo.exe").exists()             # lo dañado se descarta


def test_instalar_reemplaza_y_conserva_el_anterior(tmp_path):
    exe, nuevo = tmp_path / "ExaPyme.exe", tmp_path / "ExaPyme.exe.nuevo"
    exe.write_bytes(b"viejo")
    nuevo.write_bytes(b"nuevo")
    act.instalar(nuevo, exe)
    assert exe.read_bytes() == b"nuevo" and not nuevo.exists()
    assert (tmp_path / "ExaPyme.exe.anterior").read_bytes() == b"viejo"

    with pytest.raises(ErrorNegocio):                           # falta el archivo nuevo: se deshace
        act.instalar(tmp_path / "no-existe", exe)
    assert exe.read_bytes() == b"nuevo"
