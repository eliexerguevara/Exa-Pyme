from __future__ import annotations

from PySide6.QtWidgets import QListWidget, QTextBrowser

from ..comunes import Pagina, fila

ESTILO = """
<style>
  body { font-family: 'Segoe UI'; font-size: 11pt; color: #1F2937; }
  h2 { font-size: 16pt; color: #2563EB; margin-bottom: 4px; }
  h3 { font-size: 12pt; margin-top: 16px; margin-bottom: 2px; }
  li { margin-bottom: 6px; }
  .nota { background: #EFF4FF; color: #1E3A8A; }
  .ojo { background: #FEF3C7; color: #78350F; }
</style>
"""


def _nota(texto: str, clase: str = "nota") -> str:
    return f"<table width='100%' cellpadding='9'><tr><td class='{clase}'>{texto}</td></tr></table>"


# (título del tema, contenido)
TEMAS: list[tuple[str, str]] = [
    ("1. Primeros pasos", """
<h2>Primeros pasos</h2>
<p>Si es la primera vez que usás Exa Pyme, seguí estos pasos en orden. Después, el trabajo de todos los días
es más corto: abrir la caja, vender y cerrar la caja.</p>
<ol>
  <li><b>Completá los datos del comercio.</b> Entrá a <b>Configuración</b> → pestaña <b>Comercio y ticket</b>,
      escribí el nombre, la dirección y el teléfono (salen impresos en el ticket) y pulsá <b>Guardar</b>.</li>
  <li><b>Elegí la impresora de tickets</b>, si tenés una, en esa misma pestaña. Si no tenés, dejá
      «Elegir la impresora al imprimir»: igual vas a poder ver los tickets y guardarlos como PDF.</li>
  <li><b>Cargá los productos</b> desde <b>Productos</b> (ver el tema 2).</li>
  <li><b>Abrí la caja</b> desde <b>Caja diaria</b> (ver el tema 4). Sin la caja abierta no se puede vender.</li>
  <li><b>Empezá a vender</b> desde <b>Nueva venta</b> (ver el tema 5).</li>
  <li><b>Al terminar el día, cerrá la caja</b> (ver el tema 8).</li>
</ol>
""" + _nota("El menú de la izquierda siempre está a la vista. En la parte de abajo dice si la caja está abierta "
            "o cerrada y qué usuario está trabajando.")),

    ("2. Cargar productos", """
<h2>Cargar productos</h2>
<h3>Crear un producto</h3>
<ol>
  <li>Entrá a <b>Productos</b> y pulsá <b>Nuevo producto</b>.</li>
  <li>Escribí el <b>Nombre del producto</b>. Es el único dato obligatorio.</li>
  <li>En <b>Código de barras</b>, hacé clic en el campo y escaneá el producto con el lector (o escribí el número).
      El <b>Código interno</b> se genera solo si lo dejás vacío.</li>
  <li>Elegí o escribí la <b>Categoría</b>. Si no existe, se crea sola al guardar.</li>
  <li>Elegí la <b>Unidad de medida</b>. Para lo que se vende por peso usá «kg»: después vas a poder vender 0,5 o 1,25.</li>
  <li>Escribí la <b>Cantidad disponible</b> (lo que tenés hoy) y el <b>Stock mínimo</b> (cuando queda esa cantidad
      o menos, el programa avisa que hay que reponer).</li>
  <li>Completá el precio a la derecha (ver el tema 3) y pulsá <b>Guardar</b>.</li>
</ol>
<h3>Buscar, editar y duplicar</h3>
<ul>
  <li><b>Buscar:</b> escribí en el buscador parte del nombre, el código de barras, el código interno o la categoría.</li>
  <li><b>Editar:</b> hacé doble clic sobre el producto, o seleccionalo y pulsá <b>Editar</b>.</li>
  <li><b>Duplicar:</b> sirve para cargar productos parecidos (otro sabor, otro tamaño). Copia todos los datos
      menos los códigos y el stock.</li>
  <li><b>Desactivar:</b> el producto deja de aparecer en las ventas, pero no se borra nada de su historial.
      Para verlo de nuevo tildá <b>Mostrar inactivos</b>; con el mismo botón se vuelve a activar.</li>
</ul>
<h3>Cargar muchos productos desde Excel</h3>
<ol>
  <li>Pulsá <b>Exportar CSV</b> y guardá el archivo: sirve de modelo, con las columnas correctas.</li>
  <li>Abrilo con Excel, completá una fila por producto y guardalo sin cambiarle el formato (CSV).</li>
  <li>Pulsá <b>Importar CSV</b> y elegí el archivo. Al terminar, el programa informa cuántos productos creó,
      cuántos actualizó y qué filas tenían errores.</li>
</ol>
""" + _nota("Una vez creado el producto, la cantidad disponible no se cambia desde esta pantalla sino desde "
            "<b>Inventario</b>, para que quede anotado quién la cambió y por qué.")),

    ("3. Precios", """
<h2>Precios</h2>
<h3>Cómo se calcula el precio</h3>
<p>En la ficha del producto escribís tres datos y el programa calcula el resto mientras escribís:</p>
<ol>
  <li><b>Precio Costo:</b> lo que te cuesta comprar el producto.</li>
  <li><b>Impuestos:</b> elegí 0, 10,5, 21 o 27, o escribí otro porcentaje.</li>
  <li><b>Porcentaje de ganancia:</b> la ganancia que querés obtener.</li>
</ol>
<p>Con eso aparecen el <b>Precio de venta sin impuestos</b> y el <b>Precio de venta final</b>, que es lo que paga el cliente.</p>
<p><b>Ejemplo:</b> Precio Costo $ 10.000, Impuestos 21 %, Porcentaje de ganancia 30 % →
Precio de venta sin impuestos $ 14.285,71 → Precio de venta final $ 17.285,71.</p>
<h3>Margen o recargo</h3>
<ul>
  <li><b>Margen sobre el precio de venta</b> (la opción normal): el 30 % es la parte del precio de venta que te queda
      como ganancia. Con costo $ 10.000 el precio sin impuestos es $ 14.285,71.</li>
  <li><b>Recargo sobre el costo:</b> al costo se le suma el 30 %. Con costo $ 10.000 el precio sin impuestos es $ 13.000.</li>
</ul>
<p>Se elige en «La ganancia se calcula como». El método para los productos nuevos se define en
<b>Configuración</b> → <b>Ventas y precios</b>.</p>
<h3>Poner un precio a mano</h3>
<ol>
  <li>Escribí directamente el importe en <b>Precio de venta final</b> (por ejemplo, para redondearlo).</li>
  <li>Aparece un aviso amarillo que dice qué ganancia te deja ese precio.</li>
  <li>Si querés que el campo de ganancia muestre ese valor, pulsá <b>Recalcular margen</b>. Si te arrepentís,
      pulsá <b>Volver al cálculo automático</b>.</li>
</ol>
<h3>Aumentar o bajar muchos precios juntos</h3>
<ol>
  <li>En <b>Productos</b> pulsá <b>Cambio masivo de precios</b>.</li>
  <li>Elegí qué modificar: el <b>Precio Costo</b> (el precio de venta se recalcula manteniendo tu ganancia) o
      directamente el <b>Precio de venta final</b>.</li>
  <li>Elegí <b>Aumentar</b> o <b>Disminuir</b>, escribí el valor e indicá si es un porcentaje o un importe fijo.</li>
  <li>Si querés, elegí un redondeo (a $ 10, $ 50 o $ 100) y limitá el cambio a una categoría o a un proveedor.</li>
  <li>Pulsá <b>Ver vista previa</b> y revisá en la tabla cómo quedaría cada producto. Todavía no se guardó nada.</li>
  <li>Si está bien, pulsá <b>Guardar cambios</b>.</li>
</ol>
<p>Con <b>Historial de precios</b> podés ver todos los cambios: fecha, valores anteriores y nuevos, y quién los hizo.</p>
"""),

    ("4. Abrir la caja", """
<h2>Abrir la caja</h2>
<p>La caja se abre al empezar la jornada y se cierra al terminar. Todo lo que se vende y se cobra queda anotado
en la caja que está abierta. Si el comercio tiene varias computadoras, cada una tiene su propia caja: se abre y
se cierra en cada una (ver el tema 17).</p>
<ol>
  <li>Entrá a <b>Caja diaria</b> y pulsá <b>Abrir caja</b>.</li>
  <li>Contá el efectivo que hay en el cajón y escribilo en <b>Saldo inicial</b>. El programa propone el importe
      que se contó en el último cierre.</li>
  <li>Pulsá <b>Abrir caja</b>. Abajo a la izquierda pasa a decir «Caja abierta».</li>
</ol>
<h3>Dinero que entra o sale y no es una venta</h3>
<ul>
  <li><b>Entrada de efectivo:</b> por ejemplo, cuando traés cambio.</li>
  <li><b>Salida de efectivo:</b> por ejemplo, un pago a un proveedor, un gasto o un retiro.</li>
</ul>
<p>En los dos casos se escribe el importe y el motivo. Así el efectivo esperado al cierre da bien.</p>
"""),

    ("5. Hacer una venta", """
<h2>Hacer una venta</h2>
<ol>
  <li>Entrá a <b>Nueva venta</b> (o pulsá <b>F2</b> desde cualquier pantalla). El cursor ya queda en el buscador.</li>
  <li><b>Con lector:</b> escaneá el producto y se agrega solo. Si escaneás el mismo otra vez, suma una unidad.</li>
  <li><b>Sin lector:</b> escribí parte del nombre, elegí el producto en la lista que aparece (con la flecha hacia
      abajo y Enter, o con un clic).</li>
  <li>Para cargar varias unidades de una vez, escribí la cantidad, un asterisco y el código: <b>6*7791234567890</b>.
      Para productos por peso: <b>0,75*queso</b>.</li>
  <li>Para corregir una cantidad, seleccioná el producto en la lista y usá <b>+ 1</b>, <b>− 1</b> o
      <b>Cambiar cantidad</b> (también con doble clic). Con <b>Quitar producto</b> lo sacás de la venta.</li>
  <li>Si el cliente está registrado, elegilo en <b>Cliente</b>. Si no, dejá «Consumidor final»: no hace falta
      registrar a nadie para vender.</li>
  <li>Si corresponde, pulsá <b>Aplicar descuento</b> y escribí un porcentaje o un importe.</li>
  <li>Revisá el <b>TOTAL</b> y pulsá el botón del medio de pago: <b>Efectivo (F5)</b>, <b>Tarjeta (F6)</b>,
      <b>Transferencia (F7)</b> o <b>Mercado Pago (F8)</b>.</li>
  <li>Confirmá el cobro:
    <ul>
      <li><b>Efectivo:</b> escribí con cuánto paga el cliente y el programa muestra el vuelto.</li>
      <li><b>Tarjeta:</b> pasá la tarjeta por la terminal y confirmá recién cuando el pago esté aprobado.</li>
      <li><b>Transferencia y Mercado Pago:</b> ver el tema 6.</li>
    </ul>
  </li>
  <li>Pulsá <b>Confirmar venta</b>. Aparece el número de venta y el vuelto; desde ahí podés <b>Imprimir ticket</b>.
      Con Enter queda todo listo para la venta siguiente.</li>
</ol>
""<h3>Pago combinado: cobrar con dos o más medios</h3>
<ol>
  <li>Con los productos ya cargados, pulsá <b>Pago combinado (F9)</b>.</li>
  <li>Escribí cuánto paga el cliente con cada medio. Por ejemplo, $ 10.000 en <b>Efectivo</b>.</li>
  <li>En el otro medio pulsá <b>Resto</b>: se completa solo con lo que falta para llegar al total.</li>
  <li>Cuando «Falta asignar» diga <b>«Nada: está completo»</b>, pulsá <b>Confirmar venta</b>.</li>
</ol>
<p>La parte de transferencia o Mercado Pago puede quedar pendiente de verificar, igual que en un cobro simple.
En la caja, cada parte se suma a su medio de pago.</p>
""" + _nota("Al confirmar, el stock se descuenta solo. Si no hay stock suficiente de un producto, el programa avisa "
            "y no deja agregarlo.") + _nota(
    "El ticket es un comprobante interno y dice «Documento no válido como factura». Para entregar una factura "
    "electrónica de ARCA, mirá el tema 16.", "ojo")),

    ("6. Transferencias y Mercado Pago", """
<h2>Cobros con transferencia y Mercado Pago</h2>
<p>En estos medios el dinero no pasa por tus manos, así que el programa separa dos cosas: lo que <b>vendiste</b>
y lo que <b>realmente cobraste</b>.</p>
<h3>Mercado Pago con QR automático</h3>
<p>Si conectás tu cuenta de Mercado Pago, el programa genera el cobro por el importe exacto y Mercado Pago le avisa
cuando el cliente pagó. No hay que mirar el celular ni confirmar nada a mano.</p>
<p><b>Configurarlo (una sola vez, el administrador):</b></p>
<ol>
  <li>Entrá a <b>Configuración</b> → pestaña <b>Mercado Pago</b>.</li>
  <li>Seguí las instrucciones de la pantalla para obtener el <b>Access Token</b>, pegalo y pulsá
      <b>Guardar credencial</b>. Debe aparecer el nombre de tu cuenta.</li>
  <li>Pulsá <b>Actualizar lista</b> y elegí la caja que va a recibir los cobros. Si no tenés ninguna que sirva,
      usá <b>Crear sucursal y caja</b>.</li>
  <li>Elegí cómo paga el cliente: con un QR que aparece en la pantalla en cada venta, o con el QR impreso de la caja.</li>
  <li>Tildá <b>Cobrar con QR de Mercado Pago</b> y guardá.</li>
</ol>
<p><b>Cobrar:</b></p>
<ol>
  <li>En la venta, pulsá <b>Mercado Pago (F8)</b> y confirmá con la opción «Cobrar con QR de Mercado Pago».</li>
  <li>Aparece el código QR con el total. El cliente lo escanea con la app de Mercado Pago o de su banco y paga.</li>
  <li>En unos segundos la ventana muestra <b>«Pago acreditado»</b> y se cierra sola. La venta queda cobrada y, si
      Mercado Pago informa la comisión, también queda anotada.</li>
</ol>
<ul>
  <li><b>Si el cliente no puede pagar:</b> pulsá <b>Cobrar de otra forma</b>. El cobro se cancela en Mercado Pago y
      podés cobrar en efectivo o con tarjeta.</li>
  <li><b>Si el QR vence</b> (a los 10 minutos): pulsá <b>Generar otro QR</b>.</li>
  <li><b>Si se corta Internet:</b> pulsá <b>Dejar pendiente</b>. Después, en <b>Historial de ventas</b> → detalle de la
      venta, pulsá <b>Verificar en Mercado Pago</b> y el programa averigua si el cliente llegó a pagar.</li>
</ul>
<h3>Transferencias, y Mercado Pago sin la conexión automática</h3>
<ol>
  <li>Pulsá <b>Transferencia</b> o <b>Mercado Pago</b>.</li>
  <li>Abrí tu cuenta (la app del banco o de Mercado Pago) y fijate si el dinero ingresó.</li>
  <li>Si ya lo ves acreditado, elegí <b>«Ya verifiqué en mi cuenta que el dinero ingresó»</b>.</li>
  <li>Si todavía no lo ves, dejá <b>«Todavía no lo verifiqué: dejar el pago como pendiente»</b>. La venta se
      registra igual, pero el pago no se cuenta como cobrado.</li>
  <li>Si querés, anotá el número de operación y, en Mercado Pago, la comisión que te descontaron.</li>
</ol>
""" + _nota("Una captura de pantalla que te muestre el cliente no alcanza: las capturas se pueden falsificar. "
            "Confirmá solo lo que veas en tu propia cuenta.", "ojo") + """
<h3>Confirmar después un pago pendiente</h3>
<ol>
  <li>Entrá a <b>Historial de ventas</b>. Las ventas con pago pendiente aparecen en color naranja
      (podés filtrar por «Pago pendiente»).</li>
  <li>Seleccioná la venta y pulsá <b>Ver detalle y pagos</b>.</li>
  <li>Cuando hayas verificado el ingreso, pulsá <b>Confirmar cobro pendiente</b>.</li>
  <li>Si el pago nunca llegó, pulsá <b>Marcar rechazado</b> o <b>Marcar cancelado</b>. La venta queda «Sin cobrar»
      y con <b>Registrar cobro</b> podés cobrarla de otra forma.</li>
</ol>
<p>Para anotar más tarde la comisión de Mercado Pago, seleccioná el pago y pulsá <b>Cargar comisión de Mercado Pago</b>.
En la caja vas a ver el importe neto que recibiste.</p>
"""),

    ("7. Historial, tickets y anulaciones", """
<h2>Historial de ventas, tickets y anulaciones</h2>
<h3>Consultar ventas</h3>
<ol>
  <li>Entrá a <b>Historial de ventas</b>.</li>
  <li>Elegí el período (Hoy, Ayer, Esta semana, Este mes o las fechas que quieras).</li>
  <li>Podés filtrar por estado o buscar por número de venta o nombre del cliente.</li>
  <li>Con doble clic sobre una venta se abre el detalle: productos, pagos y totales.</li>
</ol>
<h3>Volver a imprimir un ticket</h3>
<p>Seleccioná la venta y pulsá <b>Ticket</b>. Desde esa ventana se imprime o se guarda como PDF.</p>
<h3>Anular una venta</h3>
<p>Solo puede hacerlo un administrador.</p>
<ol>
  <li>Abrí el detalle de la venta y pulsá <b>Anular venta</b>.</li>
  <li>Escribí el motivo y confirmá.</li>
</ol>
<p>Al anular, los productos vuelven al stock y el dinero cobrado se anota como devolución en la caja abierta.
La venta no se borra: queda en el historial marcada como «Anulada».</p>
<h3>Devolver solo algunos productos</h3>
<p>Cuando el cliente devuelve una parte de lo que compró. Solo puede hacerlo un administrador, con la caja abierta
y la venta ya cobrada.</p>
<ol>
  <li>Abrí el detalle de la venta y pulsá <b>Devolver productos</b>.</li>
  <li>Escribí cuántas unidades devuelve de cada producto (el botón <b>Todo</b> pone todo lo que queda de ese producto).</li>
  <li>Elegí por qué medio le devolvés el dinero y escribí el motivo.</li>
  <li>Revisá el <b>Importe a devolver</b> y pulsá <b>Registrar devolución</b>.</li>
</ol>
<p>Los productos devueltos vuelven al stock, el dinero sale de la caja como devolución y la venta sigue vigente por
el resto. El importe se calcula con el precio que realmente pagó el cliente, incluido el descuento de la venta.
En el detalle, la columna <b>Devuelto</b> muestra lo ya devuelto de cada producto.</p>
""" + _nota("Si la venta tiene factura de ARCA, al registrar la devolución el programa emite una nota de crédito "
            "por lo devuelto. Necesita Internet y no se puede deshacer.", "ojo") + _nota(
    "Si se cobró con tarjeta o Mercado Pago, el programa anota la devolución pero no mueve el dinero: hacela también "
    "desde la terminal o desde tu cuenta de Mercado Pago.")),

    ("8. Cerrar la caja", """
<h2>Cerrar la caja</h2>
<ol>
  <li>Entrá a <b>Caja diaria</b>. Arriba vas a ver el resumen de la jornada.</li>
  <li>Pulsá <b>Cerrar caja</b>.</li>
  <li>Contá el efectivo que hay en el cajón y escribilo en <b>Efectivo contado</b>.</li>
  <li>El programa lo compara con el <b>Efectivo esperado</b> y muestra la <b>Diferencia de caja</b>
      (si sobra o falta). Podés anotar una explicación en <b>Notas</b>.</li>
  <li>Pulsá <b>Cerrar caja</b>. Te ofrece ver el reporte del cierre para imprimirlo.</li>
</ol>
<h3>Cómo leer el resumen</h3>
<ul>
  <li><b>Total de ventas del día:</b> todo lo que se vendió, se haya cobrado o no.</li>
  <li><b>Total efectivamente cobrado:</b> solo los pagos confirmados, menos las devoluciones.</li>
  <li><b>Pagos pendientes:</b> ventas hechas cuyo cobro todavía no verificaste.</li>
  <li><b>Efectivo esperado al cierre:</b> saldo inicial + ventas en efectivo + entradas − salidas − devoluciones en efectivo.</li>
</ul>
<h3>Ver jornadas anteriores</h3>
<p>En la lista <b>Jornadas de caja</b>, seleccioná cualquier día para ver su resumen. Con <b>Imprimir resumen</b>
podés imprimir el cierre de la jornada seleccionada.</p>
""" + _nota("Si confirmás un pago pendiente después de haber cerrado la caja, ese dinero cuenta en la caja que esté "
            "abierta en ese momento, no en la anterior.")),

    ("9. Inventario", """
<h2>Inventario</h2>
<p>Arriba se ve el valor estimado de la mercadería y cuántos productos tienen stock bajo o están agotados.
En la lista, los agotados aparecen en rojo y los de stock bajo en naranja.</p>
<h3>Registrar un movimiento</h3>
<ol>
  <li>En la pestaña <b>Existencias</b>, seleccioná el producto y pulsá <b>Registrar movimiento</b>.</li>
  <li>Elegí el tipo:
    <ul>
      <li><b>Entrada:</b> suma al stock (mercadería que entra y no es una compra cargada).</li>
      <li><b>Salida:</b> resta del stock (rotura, vencimiento, consumo propio).</li>
      <li><b>Devolución de un cliente:</b> suma al stock.</li>
      <li><b>Ajuste:</b> escribís la cantidad real que contaste y el programa corrige la diferencia.</li>
    </ul>
  </li>
  <li>Escribí la cantidad y el <b>motivo</b> (es obligatorio) y pulsá <b>Registrar</b>.</li>
</ol>
<h3>Ver el historial</h3>
<p>En la pestaña <b>Historial de movimientos</b> están todas las entradas y salidas, con fecha, motivo y usuario.
Para ver solo las de un producto, seleccionalo en Existencias y pulsá <b>Ver movimientos del producto</b>.</p>
""" + _nota("Las ventas y las compras mueven el stock solas: no hace falta cargarlas acá.")),

    ("10. Compras y proveedores", """
<h2>Compras y proveedores</h2>
<h3>Cargar un proveedor</h3>
<p>En la pestaña <b>Proveedores</b> pulsá <b>Nuevo proveedor</b>. Solo el nombre es obligatorio.</p>
<h3>Registrar una compra</h3>
<ol>
  <li>En la pestaña <b>Compras</b> pulsá <b>Nueva compra</b>.</li>
  <li>Elegí el proveedor y, si querés, anotá el número de factura o remito.</li>
  <li>Pulsá <b>Agregar producto</b>, buscá el producto (o escanealo) y escribí la cantidad comprada y el
      Precio Costo por unidad. Repetí para cada producto.</li>
  <li>Dejá tildada la opción <b>«Actualizar el Precio de venta final según el nuevo costo»</b> si querés que el
      precio de venta suba o baje junto con el costo, manteniendo tu ganancia. Si la destildás, el precio de venta
      no cambia.</li>
  <li>Pulsá <b>Confirmar compra</b>.</li>
</ol>
<p>Al confirmar se suma el stock y queda registrado el nuevo costo. Las ventas anteriores no se modifican.</p>
"""),

    ("11. Clientes", """
<h2>Clientes</h2>
<p>Registrar clientes es opcional. Sirve para que el nombre figure en el ticket y en el historial, y para tener sus
datos fiscales cuando se habilite la facturación electrónica.</p>
<ol>
  <li>Entrá a <b>Clientes</b> y pulsá <b>Nuevo cliente</b>.</li>
  <li>Escribí el nombre. El documento, la condición frente al IVA y los datos de contacto son opcionales.</li>
  <li>Pulsá <b>Guardar</b>. Desde ese momento aparece en la lista <b>Cliente</b> de la pantalla Nueva venta.</li>
</ol>
"""),

    ("12. Reportes", """
<h2>Reportes</h2>
<ol>
  <li>Entrá a <b>Reportes</b>.</li>
  <li>Elegí el reporte en la primera lista: resumen del período, ventas por medio de pago, productos más vendidos,
      productos con stock bajo, compras, movimientos de inventario, valor del stock, o devoluciones y descuentos.</li>
  <li>Elegí el período: Hoy, Esta semana, Este mes, o cambiá las fechas para un período personalizado.</li>
  <li>Para abrirlo en Excel, pulsá <b>Exportar a CSV (Excel)</b> y elegí dónde guardarlo.</li>
</ol>
<h3>Qué significa cada cifra del resumen</h3>
<ul>
  <li><b>Ventas totales (facturación):</b> todo lo vendido, con impuestos.</li>
  <li><b>Ingresos cobrados:</b> el dinero que realmente entró.</li>
  <li><b>Ganancia bruta estimada:</b> ventas sin impuestos menos el Precio Costo de lo vendido.</li>
  <li><b>Ganancia neta:</b> el programa no la calcula, porque no conoce tus gastos (alquiler, sueldos, servicios,
      otros impuestos). Hay que restarlos de la ganancia bruta.</li>
</ul>
"""),

    ("13. Copias de seguridad", """
<h2>Copias de seguridad</h2>
<p>Una copia guarda todos los datos del comercio en un solo archivo. Si la computadora se rompe o se pierde,
con una copia se recupera todo.</p>
<h3>Copias automáticas</h3>
<p>El programa hace una copia por día al abrirse y conserva las últimas 30. Se puede cambiar en esta pantalla.</p>
<h3>Hacer una copia a mano</h3>
<ol>
  <li>Entrá a <b>Copias de seguridad</b> y pulsá <b>Crear copia de seguridad ahora</b>.</li>
  <li>El programa crea el archivo, lo verifica y muestra dónde quedó.</li>
</ol>
""" + _nota("Las copias guardadas en esta misma computadora no sirven si se rompe el disco. Conectá un pendrive, "
            "pulsá <b>Cambiar carpeta</b> y elegilo, o copiá los archivos a otro lado cada tanto con "
            "<b>Abrir carpeta</b>.", "ojo") + """
<h3>Restaurar una copia</h3>
<ol>
  <li>Seleccioná la copia en la lista y pulsá <b>Restaurar la copia seleccionada</b>, o usá
      <b>Restaurar desde un archivo…</b> si está en un pendrive.</li>
  <li>El programa revisa que el archivo esté sano y muestra cuántos productos y ventas contiene.</li>
  <li>Confirmá. Antes de reemplazar, se guarda sola una copia de los datos actuales, por si hay que volver atrás.</li>
  <li>El programa se cierra. Volvé a abrirlo para seguir trabajando.</li>
</ol>
<p>Al restaurar, lo que se haya cargado después de esa copia se pierde.</p>
"""),

    ("14. Usuarios y permisos", """
<h2>Usuarios y permisos</h2>
<p>Hay dos tipos de usuario:</p>
<ul>
  <li><b>Administrador:</b> puede hacer todo.</li>
  <li><b>Cajero:</b> puede vender, manejar la caja, confirmar pagos, consultar productos y cargar clientes.
      No puede cambiar precios, anular ventas, ajustar el inventario, ver reportes ni cambiar la configuración.</li>
</ul>
<h3>Crear un usuario</h3>
<ol>
  <li>Entrá a <b>Configuración</b> → pestaña <b>Usuarios</b> y pulsá <b>Nuevo usuario</b>.</li>
  <li>Escribí el nombre de la persona, un nombre de usuario, el rol y la contraseña.</li>
  <li>Pulsá <b>Guardar</b>. Para entrar con ese usuario hay que cerrar el programa y volver a abrirlo.</li>
</ol>
<p>Con <b>Editar / cambiar contraseña</b> se cambia la contraseña o se desactiva un usuario que ya no trabaja.</p>
<h3>Otras opciones del administrador</h3>
<p>En <b>Configuración</b> → <b>Ventas y precios</b> se define el descuento máximo que puede aplicar un cajero y si se
permite vender sin stock. En <b>Registro de operaciones</b> quedan anotados los cambios de precios, las anulaciones,
los ajustes de inventario y los cierres de caja, con fecha y usuario.</p>
<h3>Si el administrador olvida su contraseña</h3>
<p>Cada administrador tiene un <b>código de recuperación</b>: veinte letras y números que el programa muestra una
sola vez, al crear el usuario, y que conviene anotar o imprimir y guardar fuera de la computadora.</p>
<ol>
  <li>En la pantalla de ingreso, pulsá <b>Olvidé mi contraseña</b>.</li>
  <li>Escribí tu usuario, el código de recuperación y la contraseña nueva (dos veces).</li>
  <li>El programa cambia la contraseña y te muestra un <b>código nuevo</b>: el anterior ya no sirve. Guardalo igual que el primero.</li>
</ol>
<p>Si todavía no tenés código, o querés cambiarlo, generalo desde <b>Configuración</b> → <b>Usuarios</b> →
<b>Mi código de recuperación</b>. Al ingresar, el programa también te lo ofrece si ve que no tenés uno.</p>
<p>La contraseña de un <b>cajero</b> no necesita código: se la cambia un administrador desde
<b>Configuración</b> → <b>Usuarios</b> → <b>Editar / cambiar contraseña</b>.</p>
""" + _nota("Quien tenga el código puede cambiar la contraseña del administrador: no lo dejes pegado en el monitor "
            "ni en un archivo de la computadora. Si perdiste la contraseña y también el código, consultá con el soporte "
            "técnico.", "ojo")),

    ("15. Atajos de teclado", """
<h2>Atajos de teclado</h2>
<table cellpadding="7" cellspacing="0" border="0">
  <tr><td><b>F2</b></td><td>Ir a Nueva venta desde cualquier pantalla</td></tr>
  <tr><td><b>Enter</b></td><td>Agregar a la venta el producto escaneado o escrito</td></tr>
  <tr><td><b>Flecha abajo</b></td><td>Pasar del buscador a la lista de productos sugeridos</td></tr>
  <tr><td><b>cantidad*código</b></td><td>Agregar varias unidades de una vez (ejemplo: 6*7791234567890)</td></tr>
  <tr><td><b>F5</b></td><td>Cobrar en efectivo</td></tr>
  <tr><td><b>F6</b></td><td>Cobrar con tarjeta</td></tr>
  <tr><td><b>F7</b></td><td>Cobrar con transferencia</td></tr>
  <tr><td><b>F8</b></td><td>Cobrar con Mercado Pago</td></tr>
  <tr><td><b>F9</b></td><td>Pago combinado (dos o más medios)</td></tr>
  <tr><td><b>+</b> y <b>−</b></td><td>Sumar o restar una unidad al producto seleccionado en la venta</td></tr>
  <tr><td><b>Supr</b></td><td>Quitar de la venta el producto seleccionado</td></tr>
</table>
<p>Las teclas +, − y Supr funcionan después de hacer clic en un producto de la lista de la venta.</p>
<p>En cualquier tabla, un clic en el título de una columna ordena la lista por esa columna.</p>
"""),

    ("16. Facturación electrónica (ARCA)", """
<h2>Facturación electrónica (ARCA)</h2>
<p>Exa Pyme puede emitir facturas electrónicas A, B y C y notas de crédito, pidiendo el CAE a ARCA por Internet.
Viene desactivado: hasta que lo configures, el programa sigue entregando tickets internos.</p>
<h3>Configurarlo por primera vez</h3>
<ol>
  <li>Entrá a <b>Facturación</b> → pestaña <b>Datos fiscales</b> y completá razón social, CUIT, condición frente al
      IVA, domicilio y punto de venta. Dejá el entorno en <b>Homologación</b> (pruebas), tildá
      <b>Activar la facturación electrónica</b> y guardá.</li>
  <li>Pasá a la pestaña <b>Certificado</b> y seguí los pasos que figuran ahí: el programa genera el pedido, vos lo
      presentás en el sitio de ARCA con tu clave fiscal y después cargás el certificado que ARCA te entrega.</li>
  <li>Pulsá <b>3. Probar conexión</b>. Si todo está bien, informa el último número autorizado.</li>
  <li>Hacé algunas facturas de prueba. En homologación los comprobantes dicen «sin validez fiscal».</li>
  <li>Cuando funcione, repetí los pasos 1 y 2 eligiendo el entorno <b>Producción</b>, que usa otro certificado.
      Desde ese momento las facturas son reales.</li>
</ol>
<h3>Emitir una factura</h3>
<ul>
  <li><b>Al terminar una venta:</b> en la ventana «Venta registrada» pulsá <b>Emitir factura</b>.</li>
  <li><b>Siempre, sin preguntar:</b> tildá «Emitir la factura automáticamente al registrar cada venta» en Datos fiscales.</li>
  <li><b>Más tarde:</b> en <b>Facturación</b> → <b>Comprobantes</b>, seleccioná la venta y pulsá <b>Emitir factura</b>.</li>
</ul>
<p>El tipo de factura lo decide el programa: si el comercio es monotributista o exento, Factura C. Si es responsable
inscripto, Factura A cuando el cliente es responsable inscripto o monotributista (tiene que tener CUIT cargado) y
Factura B en los demás casos. Por eso, para una Factura A hay que elegir el cliente antes de cobrar.</p>
<h3>Si no hay Internet o ARCA no responde</h3>
<p>La venta se guarda igual y la factura queda <b>pendiente</b>. Cuando vuelva la conexión, entrá a
<b>Facturación</b> y pulsá <b>Reintentar pendientes</b>. El programa primero averigua si ARCA llegó a autorizarla,
para no facturar dos veces.</p>
<h3>Si ARCA rechaza la factura</h3>
<p>En la lista aparece en rojo, con el motivo que informó ARCA. Corregí el dato (por ejemplo, el documento del
cliente) y volvé a pulsar <b>Emitir factura</b>.</p>
<h3>Anular una venta facturada</h3>
<p>Una factura autorizada no se borra: se anula con una nota de crédito. En <b>Facturación</b> → <b>Comprobantes</b>,
seleccioná la venta y pulsá <b>Emitir nota de crédito</b>. Cuando ARCA la autoriza, la venta queda anulada, los
productos vuelven al stock y la devolución del dinero se registra en la caja.</p>
""" + _nota("Solo es una factura lo que tiene CAE y código QR. El programa nunca imprime como factura un comprobante "
            "que ARCA no autorizó.") + _nota(
    "El certificado vence (la pantalla muestra la fecha). Antes de que venza, generá un pedido nuevo y cargá el "
    "certificado nuevo: el anterior sigue funcionando mientras tanto.", "ojo")),
    ("17. Varias computadoras (servidor y clientes)", """
<h2>Varias computadoras: servidor y clientes</h2>
<p>Si el comercio tiene más de una caja, todas pueden trabajar con los mismos productos, precios, stock y ventas.
Una computadora es el <b>servidor</b> (la principal: guarda los datos) y las demás son <b>clientes</b>.</p>
<h3>1. En la computadora principal (servidor)</h3>
<ol>
  <li>Al instalar Exa Pyme, elegí <b>Servidor</b> y tildá «Otras computadoras se van a conectar a esta».
      Si el programa ya estaba instalado, entrá a <b>Configuración</b> → pestaña <b>Red</b>, tildá
      «Permitir que otras computadoras se conecten a esta» y pulsá <b>Guardar</b>.</li>
  <li>Si Windows pregunta si permitís que Exa Pyme se comunique por la red, elegí <b>Permitir</b> en redes privadas.</li>
  <li>En esa misma pestaña figuran la <b>IP</b> y el <b>puerto</b> que hay que escribir en las otras computadoras.</li>
  <li>Creá un usuario para cada cajero en <b>Configuración</b> → <b>Usuarios</b>.</li>
</ol>
<h3>2. En cada una de las otras computadoras (clientes)</h3>
<ol>
  <li>Instalá Exa Pyme y elegí <b>Cliente</b>.</li>
  <li>Escribí la <b>IP</b> y el <b>puerto</b> del servidor.</li>
  <li>Tildá <b>«Recordar la IP y el puerto en esta computadora»</b> para no tener que escribirlos cada vez.</li>
  <li>En <b>Nombre de esta caja</b> poné un nombre distinto en cada computadora (por ejemplo «Caja 2»): con ese
      nombre figuran sus jornadas de caja. Conviene no cambiarlo después.</li>
  <li>Escribí tu <b>usuario</b> y tu <b>contraseña</b> y pulsá <b>Ingresar</b>. La contraseña nunca queda guardada.</li>
</ol>
<h3>Cómo se trabaja</h3>
<ul>
  <li>Todas las computadoras ven los mismos datos al instante: lo que vende una, se descuenta del stock para todas.</li>
  <li><b>Cada computadora tiene su propia caja diaria</b>, con su saldo inicial, sus entradas y salidas y su
      arqueo al cierre. Cada cajero abre y cierra la suya, y cuenta solo el efectivo de su cajón.</li>
  <li>Las ventas y los cobros cuentan en la caja de la computadora donde se hicieron. Si un pago pendiente se confirma
      desde otra computadora, o una devolución se hace en otra, el dinero se anota en la caja de esa otra.</li>
  <li>El administrador ve las jornadas de todas las cajas en <b>Caja diaria</b> y en el reporte
      <b>«Cierres de caja por computadora»</b>. Un cajero ve solo las de su caja.</li>
  <li>Si una caja quedó abierta en una computadora que ya se apagó, el administrador puede cerrarla desde cualquier
      otra: en <b>Caja diaria</b>, seleccioná esa jornada y pulsá <b>Cerrar la caja seleccionada</b>.</li>
  <li>Cada computadora usa <b>su propia impresora</b>: se elige en Configuración → Comercio y ticket de esa computadora.</li>
  <li>Las <b>copias de seguridad</b> se hacen solo en el servidor, que es donde están los datos.</li>
  <li>La facturación de ARCA y los cobros de Mercado Pago se configuran una sola vez y sirven para todas.</li>
</ul>
<h3>Si un cliente no se puede conectar</h3>
<ul>
  <li>La computadora principal tiene que estar <b>encendida y con Exa Pyme abierto</b>. Si se cierra, las otras dejan de funcionar.</li>
  <li>Las dos tienen que estar en la <b>misma red</b> (mismo router o Wi-Fi).</li>
  <li>Revisá la IP y el puerto en Configuración → Red del servidor. Si la IP cambió, pedile a quien maneje la red que
      le deje una IP fija a esa computadora.</li>
  <li>Las dos tienen que tener la <b>misma versión</b>: actualizá primero el servidor y después cada cliente, con el
      botón «Actualizar programa» de la pantalla de ingreso.</li>
</ul>
""" + _nota("La comunicación entre las computadoras va cifrada, y los permisos de cada usuario se comprueban en el "
            "servidor: un cajero no puede hacer desde otra computadora lo que no puede hacer en la principal.") + _nota(
    "Está pensado para computadoras dentro del mismo local. No abras el puerto a Internet desde el router.", "ojo")),

    ("18. Actualizar el programa", """
<h2>Actualizar el programa</h2>
<p>Cuando se publica una versión nueva de Exa Pyme, aparece el botón azul <b>Update</b> en la parte de abajo del
menú, con el número de la versión. El programa lo consulta solo al abrirse (hace falta Internet) y solo lo ve
el administrador.</p>
<ol>
  <li>Terminá la venta que estés cargando. No hace falta cerrar la caja.</li>
  <li>Pulsá <b>Update</b>. Se muestra qué versión es y qué novedades trae.</li>
  <li>Pulsá <b>Actualizar ahora</b>. El programa hace primero una copia de seguridad de tus datos y después
      descarga la versión nueva.</li>
  <li>Al terminar, Exa Pyme se cierra y se vuelve a abrir solo, ya actualizado. Ingresá con tu usuario como siempre.</li>
</ol>
<p>Para consultar a mano si hay una versión nueva: <b>Configuración</b> → <b>Comercio y ticket</b> →
<b>Buscar actualizaciones</b>. Ahí también figura la versión instalada.</p>
""" + _nota("Actualizar no cambia tus productos, ventas ni configuración: los datos están guardados aparte del "
            "programa. Si la descarga falla o llega dañada, se descarta y el programa queda como estaba.")),

    ("19. Problemas frecuentes", """
<h2>Problemas frecuentes</h2>
<h3>Los botones de cobro están apagados</h3>
<p>La caja está cerrada o la venta no tiene productos. Abrí la caja desde <b>Caja diaria</b>.</p>
<h3>Escaneo un producto y dice que no lo encuentra</h3>
<p>El producto no tiene cargado ese código de barras. Abrilo en <b>Productos</b>, hacé clic en
<b>Código de barras</b>, escanealo y guardá.</p>
<h3>El lector no escribe nada</h3>
<p>Hacé clic en el buscador de Nueva venta para que el cursor esté ahí y probá de nuevo. El lector funciona como un
teclado: si lo probás en el Bloc de notas de Windows y tampoco escribe, el problema es del lector o del cable.</p>
<h3>Dice que no hay stock suficiente</h3>
<p>El sistema tiene anotada menos mercadería de la que hay. Corregilo en <b>Inventario</b> →
<b>Registrar movimiento</b> → «Ajuste». Un administrador también puede permitir vender sin stock desde
<b>Configuración</b> → <b>Ventas y precios</b>.</p>
<h3>No imprime el ticket</h3>
<p>Revisá que la impresora esté encendida y que sea la elegida en <b>Configuración</b> → <b>Comercio y ticket</b>.
Mientras tanto, la venta queda guardada y el ticket se puede reimprimir desde <b>Historial de ventas</b>.</p>
<h3>El efectivo contado no coincide con el esperado</h3>
<p>Lo más habitual es un retiro o un pago que no se cargó como <b>Salida de efectivo</b>, o un vuelto mal dado.
La diferencia queda registrada en el cierre.</p>
<h3>Apareció un mensaje de problema inesperado</h3>
<p>La operación no se completó y los datos están a salvo. Si se repite, el archivo de registro indicado en el mensaje
tiene el detalle para el soporte técnico.</p>
"""),
]


class PaginaGuia(Pagina):
    titulo = "Guía de uso"

    def armar(self) -> None:
        self.temas = QListWidget()
        self.temas.setFixedWidth(270)
        self.temas.addItems([titulo for titulo, _ in TEMAS])
        self.texto = QTextBrowser()
        self.texto.setOpenLinks(False)
        self.texto.document().setDocumentMargin(22)
        self.temas.currentRowChanged.connect(self.mostrar)
        self.cuerpo.addLayout(fila(self.temas, self.texto, espacio=12), 1)
        self.temas.setCurrentRow(0)

    def mostrar(self, n: int) -> None:
        if 0 <= n < len(TEMAS):
            self.texto.setHtml(ESTILO + TEMAS[n][1])
