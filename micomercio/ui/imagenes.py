"""Imágenes de productos: se guardan chicas (500 px, JPEG, fondo blanco) para que la base no crezca de más."""
from __future__ import annotations

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap

from ..core.errores import ErrorNegocio

LADO_MAXIMO = 500
CALIDAD = 82


def normalizar(datos: bytes) -> bytes:
    """Convierte cualquier imagen (JPG, PNG, WEBP...) al formato en que se guarda. Lanza ErrorNegocio si no es una imagen."""
    imagen = QImage()
    if not datos or not imagen.loadFromData(QByteArray(datos)) or imagen.isNull():
        raise ErrorNegocio("El archivo elegido no es una imagen que se pueda leer (probá con JPG o PNG).")
    if max(imagen.width(), imagen.height()) > LADO_MAXIMO:
        imagen = imagen.scaled(LADO_MAXIMO, LADO_MAXIMO, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    lienzo = QImage(imagen.size(), QImage.Format_RGB32)
    lienzo.fill(QColor("white"))  # las transparencias quedan sobre blanco
    pintor = QPainter(lienzo)
    pintor.drawImage(0, 0, imagen)
    pintor.end()
    salida = QByteArray()
    memoria = QBuffer(salida)
    memoria.open(QIODevice.WriteOnly)
    if not lienzo.save(memoria, "JPG", CALIDAD):
        raise ErrorNegocio("No se pudo preparar la imagen.")
    return bytes(salida)


def pixmap(datos: bytes | None, lado: int) -> QPixmap | None:
    """Imagen lista para mostrar en un cuadro de `lado` píxeles, o None si no hay."""
    if not datos:
        return None
    imagen = QPixmap()
    if not imagen.loadFromData(QByteArray(datos)):
        return None
    return imagen.scaled(lado, lado, Qt.KeepAspectRatio, Qt.SmoothTransformation)
