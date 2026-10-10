from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QComboBox, QFileDialog, QFormLayout, QLineEdit, QTabWidget, QVBoxLayout, QWidget

from ... import __version__
from ...core import precios
from ...core.dinero import D, fmt_pct, parse_decimal
from ...core.errores import ErrorNegocio
from ...rutas import carpeta_datos, carpeta_registros
from ...servicios.contexto import ROLES
from ..comunes import CampoDecimal, Dialogo, Pagina, Tabla, boton, cf, etiqueta, fila, informar
from ..impresion import impresoras
from .config_mp import PanelMercadoPago
from .config_red import PanelRed

ACCIONES = {
    "cambio_precio": "Cambio de precio", "cambio_masivo_precios": "Cambio masivo de precios",
    "venta_anulada": "Venta anulada", "devolucion_parcial": "Devolución de productos", "movimiento_stock": "Ajuste de inventario", "caja_abierta": "Apertura de caja",
    "caja_cerrada": "Cierre de caja", "caja_entrada": "Entrada de efectivo", "caja_salida": "Salida de efectivo",
    "descuento": "Descuento en venta", "pago_confirmado": "Pago confirmado", "pago_rechazado": "Pago rechazado",
    "pago_cancelado": "Pago cancelado", "pago_agregado": "Cobro registrado", "pago_comision": "Comisión cargada",
    "compra": "Compra", "configuracion": "Cambio de configuración", "usuario_creado": "Usuario creado",
    "usuario_modificado": "Usuario modificado", "usuario_clave": "Cambio de contraseña",
    "codigo_recuperacion": "Código de recuperación generado", "clave_recuperada": "Contraseña recuperada con el código",
    "clave_restablecida": "Contraseña restablecida sin código",
    "copia_restaurada": "Copia de seguridad restaurada", "importacion_productos": "Importación de productos",
    "comprobante_autorizado": "Comprobante autorizado por ARCA", "comprobante_rechazado": "Comprobante rechazado por ARCA",
    "producto_activado": "Producto activado", "producto_desactivado": "Producto desactivado",
}


class DialogoUsuario(Dialogo):
    def __init__(self, padre, ctx, usuario=None):
        super().__init__(padre, "Editar usuario" if usuario else "Nuevo usuario", ancho=440)
        self.ctx, self.usuario = ctx, usuario
        self.nombre = QLineEdit(usuario["nombre"] if usuario else "")
        self.login = QLineEdit(usuario["usuario"] if usuario else "")
        self.login.setReadOnly(bool(usuario))
        self.rol = QComboBox()
        for clave, nombre in ROLES.items():
            self.rol.addItem(nombre, clave)
        self.rol.setCurrentIndex(self.rol.findData(usuario["rol"] if usuario else "cajero"))
        self.clave, self.clave2 = QLineEdit(), QLineEdit()
        for campo in (self.clave, self.clave2):
            campo.setEchoMode(QLineEdit.Password)
        self.activo = QCheckBox("Usuario activo")
        self.activo.setChecked(bool(usuario["activo"]) if usuario else True)
        self.formulario.addRow("Nombre de la persona:", self.nombre)
        self.formulario.addRow("Nombre de usuario:", self.login)
        self.formulario.addRow("Rol:", self.rol)
        self.formulario.addRow("Contraseña nueva:" if usuario else "Contraseña:", self.clave)
        self.formulario.addRow("Repetir contraseña:", self.clave2)
        self.formulario.addRow("", self.activo)
        if usuario:
            self.clave.setPlaceholderText("Dejala vacía para no cambiarla")
        self.cuerpo.addWidget(etiqueta(
            "El cajero puede vender, manejar la caja, consultar productos y clientes. "
            "El administrador puede hacer todo.", "suave", True))
        self.terminar()

    def guardar(self) -> None:
        if self.clave.text() != self.clave2.text():
            raise ErrorNegocio("Las dos contraseñas no coinciden.")
        if self.usuario:
            self.ctx.usuarios.actualizar(self.usuario["id"], self.nombre.text(), self.rol.currentData(), self.activo.isChecked())
            if self.clave.text():
                self.ctx.usuarios.cambiar_clave(self.usuario["id"], self.clave.text())
        else:
            self.ctx.usuarios.crear(self.login.text(), self.nombre.text(), self.clave.text(), self.rol.currentData())
        self.accept()


class PaginaConfiguracion(Pagina):
    titulo = "Configuración"

    def armar(self) -> None:
        pestanas = QTabWidget()

        # --- comercio y ticket ---
        general = QWidget()
        f = QFormLayout(general)
        f.setContentsMargins(4, 16, 4, 4)
        f.setSpacing(10)
        self.nombre, self.direccion, self.telefono, self.pie = QLineEdit(), QLineEdit(), QLineEdit(), QLineEdit()
        self.impresora = QComboBox()
        self.ancho = QComboBox()
        for clave, nombre in [("80", "Ticket de 80 mm"), ("58", "Ticket de 58 mm"), ("A4", "Hoja A4")]:
            self.ancho.addItem(nombre, clave)
        self.automatico = QCheckBox("Imprimir el ticket automáticamente al registrar cada venta")
        f.addRow("Nombre del comercio:", self.nombre)
        f.addRow("Dirección:", self.direccion)
        f.addRow("Teléfono:", self.telefono)
        f.addRow("Texto al pie del ticket:", self.pie)
        f.addRow("Impresora de tickets:", self.impresora)
        f.addRow("Tamaño del papel:", self.ancho)
        f.addRow("", self.automatico)
        f.addRow("", boton("Guardar", self.guardar_general, "primario"))
        f.addRow(f"Versión instalada: {__version__}", boton(
            "Buscar actualizaciones", lambda: self.ventana.actualizaciones.buscar(manual=True)))
        for campo in (self.nombre, self.direccion, self.telefono, self.pie, self.impresora, self.ancho):
            campo.setMaximumWidth(520)
        pestanas.addTab(general, "Comercio y ticket")

        # --- ventas y precios ---
        ventas = QWidget()
        f2 = QFormLayout(ventas)
        f2.setContentsMargins(4, 16, 4, 4)
        f2.setSpacing(10)
        self.descuento = CampoDecimal("Descuento máximo")
        self.negativo = QCheckBox("Permitir vender sin stock (el stock puede quedar negativo)")
        self.impuesto = QComboBox()
        self.impuesto.setEditable(True)
        self.impuesto.addItems([fmt_pct(D(i)) for i in precios.IMPUESTOS_HABITUALES])
        self.impuesto.setMaximumWidth(170)
        self.metodo = QComboBox()
        for clave, nombre in precios.METODOS.items():
            self.metodo.addItem(nombre, clave)
        self.metodo.setMaximumWidth(380)
        f2.addRow("Descuento máximo que puede aplicar un cajero (%):", self.descuento)
        f2.addRow("", self.negativo)
        f2.addRow("Impuestos para productos nuevos (%):", self.impuesto)
        f2.addRow("Cálculo del Porcentaje de ganancia en productos nuevos:", self.metodo)
        f2.addRow("", etiqueta(
            "«Margen sobre el precio de venta»: con costo $ 10.000 y 30 % el precio sin impuestos es $ 14.285,71.\n"
            "«Recargo sobre el costo»: con los mismos datos el precio sin impuestos es $ 13.000,00.", "suave", True))
        self.catalogo = QLineEdit()
        self.catalogo.setPlaceholderText("Carpeta con las imágenes, nombradas por código de barras")
        self.b_catalogo = boton("Elegir carpeta…", self.elegir_catalogo)
        self.estado_catalogo = etiqueta("", "suave", True)
        f2.addRow("Catálogo de imágenes de productos:", fila(self.catalogo, self.b_catalogo))
        f2.addRow("", self.estado_catalogo)
        f2.addRow("", boton("Guardar", self.guardar_ventas, "primario"))
        pestanas.addTab(ventas, "Ventas y precios")

        self.mercado_pago = PanelMercadoPago(self.ctx)
        pestanas.addTab(self.mercado_pago, "Mercado Pago")

        self.red = PanelRed(self.ctx, self.ventana)
        pestanas.addTab(self.red, "Red")

        # --- usuarios ---
        usuarios = QWidget()
        vu = QVBoxLayout(usuarios)
        vu.setContentsMargins(0, 12, 0, 0)
        vu.addLayout(fila(boton("Nuevo usuario", self.nuevo_usuario, "primario"), boton("Editar / cambiar contraseña", self.editar_usuario), None,
                         boton("Mi código de recuperación…", self.codigo_recuperacion,
                               ayuda="Para poder cambiar tu contraseña de administrador si la olvidás.")))
        self.tabla_usuarios = Tabla(["Nombre", "Usuario", "Rol", "Estado", "Creado"], estirar=0)
        self.tabla_usuarios.activada.connect(self.editar_usuario)
        vu.addWidget(self.tabla_usuarios)
        pestanas.addTab(usuarios, "Usuarios")

        # --- registro de operaciones ---
        registro = QWidget()
        vr = QVBoxLayout(registro)
        vr.setContentsMargins(0, 12, 0, 0)
        vr.addWidget(etiqueta(
            f"Últimas operaciones importantes. Los datos se guardan en {carpeta_datos()} y los registros "
            f"técnicos en {carpeta_registros()}.", "suave", True))
        self.tabla_registro = Tabla(["Fecha", "Usuario", "Operación", "Detalle"], estirar=3)
        vr.addWidget(self.tabla_registro)
        pestanas.addTab(registro, "Registro de operaciones")
        self.cuerpo.addWidget(pestanas, 1)

    def refrescar(self) -> None:
        cfg = self.ctx.config
        self.nombre.setText(cfg.obtener("comercio_nombre"))
        self.direccion.setText(cfg.obtener("comercio_direccion"))
        self.telefono.setText(cfg.obtener("comercio_telefono"))
        self.pie.setText(cfg.obtener("ticket_pie"))
        self.impresora.clear()
        self.impresora.addItem("(Elegir la impresora al imprimir)", "")
        for nombre in impresoras():
            self.impresora.addItem(nombre, nombre)
        self.impresora.setCurrentIndex(max(0, self.impresora.findData(cfg.obtener("impresora"))))
        self.ancho.setCurrentIndex(max(0, self.ancho.findData(cfg.obtener("ticket_ancho"))))
        self.automatico.setChecked(cfg.booleano("ticket_imprimir_automatico"))
        self.descuento.poner(cfg.decimal("descuento_maximo_cajero_pct"))
        self.negativo.setChecked(cfg.booleano("permitir_stock_negativo"))
        self.impuesto.setCurrentText(fmt_pct(cfg.decimal("impuesto_predeterminado")))
        self.metodo.setCurrentIndex(max(0, self.metodo.findData(cfg.obtener("metodo_precio_predeterminado"))))
        self.catalogo.setText(cfg.obtener("catalogo_carpeta"))
        remoto = getattr(self.ctx, "remoto", False)
        self.b_catalogo.setVisible(not remoto)  # la carpeta está en la computadora principal
        self.catalogo.setReadOnly(remoto)
        catalogo = self.ctx.productos.estado_catalogo()
        if catalogo["existe"]:
            texto = f"{catalogo['imagenes']} imágenes en {catalogo['carpeta']}."
        else:
            texto = "Todavía no hay catálogo. Es una carpeta con una imagen por producto, cuyo nombre es el código de barras (7790001000012.jpg)."
        self.estado_catalogo.setText(texto + (" Se configura en la computadora principal." if remoto else ""))
        self.mercado_pago.refrescar()
        self.red.refrescar()
        self.cargar_usuarios()
        self.tabla_registro.cargar([[cf(a["fecha"]), a["usuario"], ACCIONES.get(a["accion"], a["accion"]), a["detalle"] or ""]
                                    for a in self.ctx.auditoria()])

    def guardar_general(self) -> None:
        if not self.nombre.text().strip():
            raise ErrorNegocio("Escribí el nombre del comercio.")
        self.ctx.config.guardar({
            "comercio_nombre": self.nombre.text().strip(), "comercio_direccion": self.direccion.text().strip(),
            "comercio_telefono": self.telefono.text().strip(), "ticket_pie": self.pie.text().strip(),
            "impresora": self.impresora.currentData() or "", "ticket_ancho": self.ancho.currentData(),
            "ticket_imprimir_automatico": self.automatico.isChecked(),
        })
        self.ventana.actualizar_estado()
        informar(self, "La configuración se guardó.")

    def guardar_ventas(self) -> None:
        descuento = self.descuento.valor()
        if descuento > 100:
            raise ErrorNegocio("El descuento máximo no puede superar el 100 %.")
        try:
            impuesto = parse_decimal(self.impuesto.currentText())
        except ValueError:
            raise ErrorNegocio("El valor de «Impuestos» no es un número válido.") from None
        if impuesto < 0:
            raise ErrorNegocio("Los Impuestos no pueden ser negativos.")
        self.ctx.config.guardar({
            "descuento_maximo_cajero_pct": str(descuento), "permitir_stock_negativo": self.negativo.isChecked(),
            "impuesto_predeterminado": str(impuesto), "metodo_precio_predeterminado": self.metodo.currentData(),
            "catalogo_carpeta": self.catalogo.text().strip(),
        })
        asociadas = self.ctx.productos.asociar_catalogo(True)  # con el catálogo elegido, las imágenes se cargan solas
        self.refrescar()
        informar(self, "La configuración se guardó." + (
            f"\n\nSe cargó la imagen de {asociadas} productos desde el catálogo." if asociadas else ""))

    def elegir_catalogo(self) -> None:
        carpeta = QFileDialog.getExistingDirectory(self, "Carpeta del catálogo de imágenes", self.catalogo.text())
        if carpeta:
            self.catalogo.setText(carpeta)

    def cargar_usuarios(self) -> None:
        usuarios = self.ctx.usuarios.listar()
        self.tabla_usuarios.cargar([[u["nombre"], u["usuario"], ROLES[u["rol"]], "Activo" if u["activo"] else "Inactivo",
                                     cf(u["creado_en"])] for u in usuarios], [u["id"] for u in usuarios])

    def codigo_recuperacion(self) -> None:
        from ..acceso import DialogoCodigo
        from ..comunes import confirmar

        texto = ("Se va a generar un código de recuperación nuevo para tu usuario."
                 + (" El código anterior deja de servir." if self.ctx.usuarios.tiene_codigo() else "") + "\n\n¿Continuar?")
        if confirmar(self, texto, "Generar código"):
            DialogoCodigo(self, self.ctx.usuarios.generar_codigo_recuperacion(), self.ctx).exec()
            self.refrescar()

    def nuevo_usuario(self) -> None:
        if DialogoUsuario(self, self.ctx).exec():
            self.cargar_usuarios()

    def editar_usuario(self) -> None:
        usuario_id = self.tabla_usuarios.id_requerido("Seleccioná un usuario de la lista.")
        usuario = next(u for u in self.ctx.usuarios.listar() if u["id"] == usuario_id)
        if DialogoUsuario(self, self.ctx, usuario).exec():
            self.cargar_usuarios()
