# Exa Pyme

Sistema de ventas e inventario para Windows 10 y 11, pensado para un comercio minorista de Argentina.
Aplicación de escritorio (Python + PySide6 + SQLite), empaquetada en un único `ExaPyme.exe`.

Estado: **las 8 etapas están implementadas**: ventas, inventario, caja, reportes, copias, facturación
electrónica de ARCA y cobro con QR de Mercado Pago.

## Para el usuario final

**[Descargar ExaPyme.exe (última versión)](https://github.com/eliexerguevara/Exa-Pyme/releases/latest/download/ExaPyme.exe)**

Guardar el archivo en una carpeta propia (por ejemplo `C:\ExaPyme`) y abrirlo con doble clic. No hay que instalar nada más.
La primera vez pide crear el usuario administrador.

Los datos se guardan en `%LOCALAPPDATA%\ExaPyme`. El programa antes se llamaba MiComercio: si encuentra la carpeta
`%LOCALAPPDATA%\MiComercio`, la renombra y sigue usando los mismos datos.

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
`EXAPYME_DATOS` con otra carpeta antes de ejecutar.

### Generar el .exe

```powershell
powershell -ExecutionPolicy Bypass -File .\construir.ps1
```

El script instala las dependencias con versiones fijas, ejecuta las pruebas, genera el ícono, empaqueta con
PyInstaller (`ExaPyme.spec`) y por último ejecuta `ExaPyme.exe --autoprueba`, que comprueba el
ejecutable sobre una base temporal. Si algún paso falla, se detiene. Resultado: `dist\ExaPyme.exe`.

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
  integraciones/           arca/ (facturación electrónica) y mercadopago.py (cobro con QR)
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

## Facturación electrónica (ARCA)

Está en `micomercio/integraciones/arca/` y se activa desde la pantalla **Facturación**. Viene desactivada.

- **WSAA**: firma el pedido de acceso (CMS) con el certificado del comercio y guarda el ticket hasta que vence.
- **WSFEv1**: `FECompUltimoAutorizado`, `FECAESolicitar` y `FECompConsultar`, con los campos en el orden del WSDL oficial.
- **Comprobantes**: facturas A, B y C y notas de crédito, con CAE, vencimiento y código QR.
- **Certificado**: el programa genera la clave privada y el pedido (`.csr`); la clave queda cifrada con DPAPI para el
  usuario de Windows, fuera de la base de datos y de las copias de seguridad.
- **Sin conexión**: la venta se guarda igual y la factura queda pendiente. Al reintentar, primero se consulta a ARCA si
  el comprobante ya había sido autorizado, para no duplicarlo.
- **Entornos**: homologación y producción, cada uno con su certificado. Los comprobantes de homologación se imprimen
  con la leyenda «sin validez fiscal» y no cambian el estado de las ventas.
- Un CAE solo se guarda si vino en una respuesta aprobada de ARCA.

Las pruebas (`tests/test_arca.py`) usan un ARCA simulado que responde los mismos mensajes SOAP. Contra los servidores
reales se verificó la conexión, el formato de los pedidos y la firma; la emisión de un comprobante real requiere el
certificado del comercio y debe probarse primero en homologación.

## Cobro con QR de Mercado Pago

Está en `micomercio/integraciones/mercadopago.py` y se activa desde **Configuración → Mercado Pago**. Viene desactivado.

- Usa la **API de Orders** vigente (`POST /v1/orders` con `type: "qr"`); la API anterior de QR está deprecada.
- Modos: QR dinámico en pantalla, QR estático de la caja, o ambos (híbrido).
- El pago se confirma solo cuando `GET /v1/orders/{id}` informa la orden procesada, por el mismo importe y con la
  misma referencia. Vencida, cancelada o rechazada no generan ingreso.
- No usa webhooks (un programa de escritorio no tiene dirección pública): consulta la API cada pocos segundos mientras
  la ventana de cobro está abierta, y a pedido desde Historial de ventas.
- El Access Token se guarda cifrado con DPAPI, fuera de la base, de las copias y de los registros.
- Las devoluciones de dinero no se hacen desde el programa: se hacen en la cuenta de Mercado Pago.

Las pruebas (`tests/test_mercadopago.py`) usan una API simulada. Contra la API real solo se verificó la dirección, el
formato del pedido y el rechazo de una credencial inventada: el primer cobro real hay que probarlo con la cuenta del
comercio (Mercado Pago ofrece credenciales y usuarios de prueba).

## Varias computadoras: servidor y clientes

Está en `micomercio/red/`. Al instalar, el programa pregunta si la computadora es el **servidor** (guarda los datos) o
un **cliente** (se conecta al servidor con su IP y su puerto; hay una casilla para recordarlos).

- El servidor es el mismo programa, que además atiende a los clientes en un puerto (8765 por defecto). Se enciende y
  se apaga desde Configuración → Red.
- Los clientes no tienen base de datos: cada operación de la interfaz se pide al servidor (`ContextoRemoto`).
- La comunicación es HTTPS con un certificado propio del servidor; el cliente recuerda su huella y avisa si cambia.
- Los permisos se comprueban en el servidor, con el usuario de cada sesión. Solo se pueden pedir las operaciones
  públicas de los servicios; las internas están bloqueadas (`SERVICIOS` y `BLOQUEADOS` en `red/servidor.py`).
- Cliente y servidor deben tener la misma versión.
- La base admite varios hilos: un candado hace que cada transacción se ejecute completa antes de la siguiente.
- La caja diaria es una sola para todas las computadoras. La impresora se configura en cada una.

Las pruebas (`tests/test_red.py`) levantan un servidor real en la misma máquina y conectan clientes por la red local
(127.0.0.1), incluidas cuatro cajas vendiendo a la vez. No se probó entre dos computadoras físicas distintas.

## Lo que todavía no hace

- Mercado Pago: no hace devoluciones ni recibe notificaciones (webhooks); no cobra con Point ni con link de pago.
- Facturación: solo productos (no servicios), en pesos, sin percepciones ni otros tributos. No emite Factura de Crédito MiPyME ni comprobantes de exportación.
- Red: una caja diaria por computadora (hoy es una sola compartida); trabajar si el servidor está apagado.
- Recuperación de la contraseña del administrador si se la olvida.
