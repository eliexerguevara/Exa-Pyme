# MiComercio

Sistema de ventas e inventario para Windows 10 y 11, pensado para un comercio minorista de Argentina.
Aplicación de escritorio (Python + PySide6 + SQLite), empaquetada en un único `MiComercio.exe`.

Estado: **MVP, etapas 1 a 6 completas**, con guía de uso y actualización desde el programa. Las etapas 7 (ARCA) y 8 (Mercado Pago) están preparadas pero no conectadas.

## Para el usuario final

**[Descargar MiComercio.exe (última versión)](https://github.com/eliexerguevara/Exa-Pyme/releases/latest/download/MiComercio.exe)**

Guardar el archivo en una carpeta propia (por ejemplo `C:\MiComercio`) y abrirlo con doble clic. No hay que instalar nada más.
La primera vez pide crear el usuario administrador.

Los datos se guardan en `%LOCALAPPDATA%\MiComercio`:

| Archivo o carpeta | Contenido |
|---|---|
| `micomercio.db` | Base de datos |
| `copias\` | Copias de seguridad (la carpeta se puede cambiar desde el programa) |
| `registros\micomercio.log` | Registro técnico para diagnóstico |

Windows puede mostrar el aviso «Windows protegió su PC» porque el ejecutable no está firmado
digitalmente: se abre con «Más información» → «Ejecutar de todas formas».

### Actualizaciones

Cuando se publica una versión nueva, el programa muestra el botón **Update** en el menú (solo al administrador).
Al pulsarlo hace una copia de seguridad, descarga la versión nueva desde este repositorio, comprueba su suma
SHA-256, reemplaza el ejecutable y se reinicia. Los datos no se tocan. También se puede consultar a mano desde
Configuración → Comercio y ticket → Buscar actualizaciones.

## Para el desarrollador

Requiere Python 3.11 o superior (probado con 3.13).

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe main.py                # ejecutar
.\.venv\Scripts\python.exe -m pytest tests -q     # pruebas
```

Para trabajar con una base de datos de prueba sin tocar la real, definir la variable
`MICOMERCIO_DATOS` con otra carpeta antes de ejecutar.

### Generar el .exe

```powershell
powershell -ExecutionPolicy Bypass -File .\construir.ps1
```

El script instala las dependencias con versiones fijas, ejecuta las pruebas, genera el ícono, empaqueta con
PyInstaller (`MiComercio.spec`) y por último ejecuta `MiComercio.exe --autoprueba`, que comprueba el
ejecutable sobre una base temporal. Si algún paso falla, se detiene. Resultado: `dist\MiComercio.exe`.

### Publicar una versión nueva

```powershell
powershell -ExecutionPolicy Bypass -File .\publicar.ps1 -Version 1.2.0 -Notas "Qué cambió en esta versión"
```

El script cambia el número de versión, corre las pruebas, guarda los cambios y sube el código con la etiqueta
`v1.2.0`. Con esa etiqueta, GitHub Actions (`.github/workflows/publicar.yml`) genera el `.exe` en Windows y lo
publica como release junto con su suma de verificación. Los programas instalados lo detectan solos.

### Organización del código

```
main.py                    punto de entrada
micomercio/
  core/                    dinero (centavos, redondeo), precios (fórmulas), errores
  db/                      conexión SQLite, transacciones, esquema y migraciones
  servicios/               reglas de negocio, sin interfaz: productos, inventario, ventas,
                           caja, compras, clientes, reportes, copias, CSV, tickets, usuarios
  integraciones/           arca.py y mercadopago.py (interfaces preparadas)
  ui/                      ventana principal, tema, piezas comunes e impresión
  ui/paginas/              una pantalla por cada opción del menú
tests/                     pruebas de precios, servicios e interfaz
```

Reglas que conviene mantener:

- La interfaz nunca escribe en la base: llama a `servicios`. Toda operación que toca varias tablas
  va dentro de `db.transaccion()`, que guarda todo o nada.
- Importes en centavos y cantidades en milésimas (enteros); cálculos con `Decimal` y redondeo comercial.
- Los errores para el usuario son `ErrorNegocio` con el mensaje en español; cualquier otra excepción se
  registra en el log y se muestra un mensaje genérico.
- Para cambiar el esquema se agrega una migración al final de `db/esquema.py`; no se editan las anteriores.
- Nada se borra: productos, clientes y proveedores se desactivan; las ventas se anulan.

### Cálculo de precios

```
Margen (predeterminado):  Precio de venta sin impuestos = Precio Costo / (1 - ganancia / 100)
Recargo:                  Precio de venta sin impuestos = Precio Costo × (1 + ganancia / 100)
Precio de venta final = Precio de venta sin impuestos × (1 + Impuestos / 100)
```

Ejemplo verificado en las pruebas: costo $ 10.000, impuestos 21 %, ganancia 30 % → $ 14.285,71 y $ 17.285,71.

## Lo que el MVP todavía no hace

- **ARCA**: no emite facturas ni pide CAE. Los tickets llevan la leyenda «Documento no válido como factura».
  La pantalla Facturación guarda los datos fiscales; el plan de la etapa 7 está en `integraciones/arca.py`.
- **Mercado Pago**: no se conecta a la API. Los cobros quedan pendientes hasta que se confirman a mano
  después de verificarlos en la cuenta. El plan de la etapa 8 está en `integraciones/mercadopago.py`.
- Devoluciones parciales: una venta se anula completa. Una devolución suelta se carga como movimiento
  de inventario.
- Pago combinado (parte en efectivo y parte con tarjeta) desde la pantalla de venta.
- Recuperación de la contraseña del administrador si se la olvida.
