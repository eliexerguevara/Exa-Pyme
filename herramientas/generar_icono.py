"""Genera recursos/micomercio.ico (el ícono del .exe) a partir del ícono dibujado en ui/tema.py."""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from PySide6.QtGui import QGuiApplication  # noqa: E402

from micomercio.ui import tema  # noqa: E402

app = QGuiApplication([])
destino = RAIZ / "recursos" / "micomercio.ico"
destino.parent.mkdir(exist_ok=True)
if not tema.icono_aplicacion().pixmap(256, 256).save(str(destino), "ICO"):
    sys.exit("No se pudo generar el ícono.")
print(f"Ícono generado: {destino}")
