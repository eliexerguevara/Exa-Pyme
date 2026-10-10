"""Prepara las imágenes del catálogo de productos (una por código de barras).

    python herramientas/preparar_imagenes.py <carpeta_origen> <carpeta_destino> [--limite N]

Cada imagen de origen se llama como el código de barras del producto (7790001000012.jpg, .png, .webp...).
En destino queda <código>.jpg, de 500 píxeles de lado como máximo y con fondo blanco: es lo que el programa
muestra, y pesa mucho menos que el original. Las que ya están en destino y son más nuevas que el origen se saltean.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QGuiApplication  # noqa: E402

from micomercio.ui.imagenes import normalizar  # noqa: E402


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    origen, destino = Path(sys.argv[1]), Path(sys.argv[2])
    limite = int(sys.argv[sys.argv.index("--limite") + 1]) if "--limite" in sys.argv else None
    destino.mkdir(parents=True, exist_ok=True)
    app = QGuiApplication([])  # noqa: F841  (hace falta para leer todos los formatos de imagen)
    hechas = salteadas = 0
    fallidas, repetidas = [], []
    vistos = set()
    archivos = sorted(a for a in origen.iterdir() if a.is_file())
    for n, archivo in enumerate(archivos[:limite], start=1):
        codigo = archivo.stem.strip()
        if codigo.lower() in vistos:
            repetidas.append(archivo.name)
            continue
        vistos.add(codigo.lower())
        salida = destino / f"{codigo}.jpg"
        if salida.exists() and salida.stat().st_mtime >= archivo.stat().st_mtime:
            salteadas += 1
            continue
        try:
            salida.write_bytes(normalizar(archivo.read_bytes()))
            hechas += 1
        except Exception as e:
            fallidas.append(f"{archivo.name}: {e}")
        if n % 1000 == 0:
            print(f"{n} de {len(archivos)}...", flush=True)
    total = sum(a.stat().st_size for a in destino.glob("*.jpg"))
    print(f"Listo: {hechas} preparadas, {salteadas} ya estaban, {len(repetidas)} repetidas, {len(fallidas)} con error.")
    print(f"Destino: {len(list(destino.glob('*.jpg')))} imágenes, {total / 1048576:.1f} MB")
    for linea in fallidas[:40]:
        print("  no se pudo leer", linea)
    return 0


if __name__ == "__main__":
    sys.exit(main())
