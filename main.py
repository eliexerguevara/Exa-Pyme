"""Punto de entrada de Exa Pyme (también es el script que empaqueta PyInstaller)."""
import sys

if __name__ == "__main__":
    if "--autoprueba" in sys.argv:
        from micomercio.autoprueba import ejecutar

        posicion = sys.argv.index("--autoprueba")
        sys.exit(ejecutar(sys.argv[posicion + 1] if len(sys.argv) > posicion + 1 else None))

    if "--actualizar" in sys.argv:
        from micomercio.servicios.actualizador import actualizar_sin_interfaz

        posicion = sys.argv.index("--actualizar")
        sys.exit(actualizar_sin_interfaz(sys.argv[posicion + 1] if len(sys.argv) > posicion + 1 else None))

    from micomercio.app import main

    sys.exit(main())
