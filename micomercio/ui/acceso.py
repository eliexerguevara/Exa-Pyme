"""Primer uso (creación del administrador) e inicio de sesión."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QCheckBox, QLineEdit, QRadioButton, QSpinBox

from .. import preferencias
from ..core.errores import ErrorNegocio
from ..red.cliente import Cliente, ContextoRemoto, HuellaDistinta
from .comunes import Dialogo, boton, confirmar, etiqueta, fila


class DialogoPrimerUso(Dialogo):
    def __init__(self, ctx):
        super().__init__(None, "Bienvenido a Exa Pyme", "Crear y empezar", 480)
        self.ctx = ctx
        self.cuerpo.insertWidget(0, etiqueta("Bienvenido a Exa Pyme", "titulo"))
        self.cuerpo.insertWidget(1, etiqueta(
            "Es la primera vez que se abre el programa en esta computadora. Creá el usuario administrador: "
            "es quien puede cambiar precios, anular ventas y configurar el sistema.", "suave", True))
        self.comercio, self.nombre, self.usuario = QLineEdit(), QLineEdit(), QLineEdit("admin")
        self.clave, self.clave2 = QLineEdit(), QLineEdit()
        for campo in (self.clave, self.clave2):
            campo.setEchoMode(QLineEdit.Password)
        self.formulario.addRow("Nombre del comercio:", self.comercio)
        self.formulario.addRow("Tu nombre:", self.nombre)
        self.formulario.addRow("Nombre de usuario:", self.usuario)
        self.formulario.addRow("Contraseña:", self.clave)
        self.formulario.addRow("Repetir contraseña:", self.clave2)
        self.cuerpo.addWidget(etiqueta("Anotá la contraseña en un lugar seguro: sin ella no se puede entrar al sistema.",
                                       "aviso", True))
        self.terminar()
        self.comercio.setFocus()

    def guardar(self) -> None:
        if not self.comercio.text().strip():
            raise ErrorNegocio("Escribí el nombre del comercio.")
        if self.clave.text() != self.clave2.text():
            raise ErrorNegocio("Las dos contraseñas no coinciden.")
        self.ctx.usuarios.crear(self.usuario.text(), self.nombre.text(), self.clave.text(), "admin")
        self.ctx.usuarios.iniciar_sesion(self.usuario.text(), self.clave.text())
        self.ctx.config.guardar({"comercio_nombre": self.comercio.text().strip()})
        self.accept()


class DialogoIngreso(Dialogo):
    def __init__(self, ctx):
        super().__init__(None, "Exa Pyme", "Ingresar", 380)
        self.ctx = ctx
        self.cuerpo.insertWidget(0, etiqueta(ctx.config.obtener("comercio_nombre"), "titulo"))
        self.cuerpo.insertWidget(1, etiqueta("Ingresá con tu usuario y contraseña.", "suave"))
        self.usuario, self.clave = QLineEdit(), QLineEdit()
        self.clave.setEchoMode(QLineEdit.Password)
        usuarios = ctx.usuarios.listar()
        activos = [u for u in usuarios if u["activo"]]
        if len(activos) == 1:
            self.usuario.setText(activos[0]["usuario"])
        self.formulario.addRow("Usuario:", self.usuario)
        self.formulario.addRow("Contraseña:", self.clave)
        self.terminar()
        (self.clave if self.usuario.text() else self.usuario).setFocus()

    def guardar(self) -> None:
        try:
            self.ctx.usuarios.iniciar_sesion(self.usuario.text(), self.clave.text())
        except ErrorNegocio:
            self.clave.clear()
            self.clave.setFocus()
            raise
        self.accept()


class DialogoModo(Dialogo):
    """Se muestra al instalar: ¿esta computadora guarda los datos (servidor) o se conecta a otra (cliente)?"""

    def __init__(self, padre=None, prefs: dict | None = None):
        super().__init__(padre, "Exa Pyme - ¿Cómo va a trabajar esta computadora?", "Continuar", 560)
        prefs = prefs or preferencias.leer()
        self.modo = ""
        self.cuerpo.insertWidget(0, etiqueta("¿Cómo va a trabajar esta computadora?", "titulo"))
        self.servidor = QRadioButton("Servidor: es la computadora principal y guarda los datos del comercio")
        self.cliente = QRadioButton("Cliente: se conecta a la computadora principal")
        (self.cliente if prefs.get("modo") == "cliente" else self.servidor).setChecked(True)
        self.red = QCheckBox("Otras computadoras se van a conectar a esta")
        self.red.setChecked(bool(prefs.get("red_activa")))
        self.puerto = QSpinBox()
        self.puerto.setRange(1024, 65535)
        self.puerto.setValue(int(prefs.get("red_puerto") or preferencias.PUERTO_PREDETERMINADO))
        self.cuerpo.insertWidget(1, self.servidor)
        self.cuerpo.insertWidget(2, etiqueta(
            "Elegí esta opción si el comercio tiene una sola computadora, o si esta es la principal. "
            "Desde acá también se usa el sistema normalmente.", "suave", True))
        self.cuerpo.insertLayout(3, fila(24, self.red, 12, etiqueta("Puerto:"), self.puerto, None))
        self.cuerpo.insertWidget(4, self.cliente)
        self.cuerpo.insertWidget(5, etiqueta(
            "Elegí esta opción en las demás cajas. No guardan datos: usan los de la computadora principal, "
            "indicando su dirección IP y su puerto.", "suave", True))
        self.servidor.toggled.connect(lambda marcado: (self.red.setEnabled(marcado), self.puerto.setEnabled(marcado)))
        self.red.setEnabled(self.servidor.isChecked())
        self.puerto.setEnabled(self.servidor.isChecked())
        self.terminar()

    def valores(self) -> dict:
        if self.modo == "cliente":
            return {"modo": "cliente"}
        return {"modo": "servidor", "red_activa": self.red.isChecked(), "red_puerto": self.puerto.value()}

    def guardar(self) -> None:
        self.modo = "cliente" if self.cliente.isChecked() else "servidor"
        self.accept()


class DialogoConexion(Dialogo):
    """Ingreso en una computadora cliente: dirección del servidor, usuario y contraseña."""

    def __init__(self, padre=None):
        super().__init__(padre, "Exa Pyme", "Ingresar", 600)
        prefs = preferencias.leer()
        self.ctx, self.cambiar_modo = None, False
        self.huella = prefs["servidor_huella"]
        self.origen = (prefs["servidor_host"], int(prefs["servidor_puerto"]))
        self.cuerpo.insertWidget(0, etiqueta("Conectarse al servidor", "titulo"))
        self.cuerpo.insertWidget(1, etiqueta(
            "Escribí la dirección IP y el puerto de la computadora principal. Los muestra en Configuración → Red.",
            "suave", True))
        self.host = QLineEdit(prefs["servidor_host"])
        self.host.setPlaceholderText("Por ejemplo 192.168.0.10")
        self.puerto = QSpinBox()
        self.puerto.setRange(1, 65535)
        self.puerto.setValue(int(prefs["servidor_puerto"]))
        self.puerto.setMaximumWidth(120)
        self.recordar = QCheckBox("Recordar la IP y el puerto en esta computadora")
        self.recordar.setChecked(bool(prefs["servidor_host"]))
        self.usuario, self.clave = QLineEdit(), QLineEdit()
        self.clave.setEchoMode(QLineEdit.Password)
        self.puesto = QLineEdit(prefs["puesto"] or preferencias.nombre_equipo())
        self.puesto.setMaxLength(40)
        self.puesto.setToolTip("Cada computadora tiene su propia caja diaria. Poné un nombre distinto en cada una, por ejemplo «Caja 2».")
        self.formulario.addRow("IP del servidor:", self.host)
        self.formulario.addRow("Puerto:", self.puerto)
        self.formulario.addRow("", self.recordar)
        self.formulario.addRow("Nombre de esta caja:", self.puesto)
        self.formulario.addRow("Usuario:", self.usuario)
        self.formulario.addRow("Contraseña:", self.clave)
        self.terminar()
        self.botones.addButton(boton("Usar como servidor…", self.pasar_a_servidor, ayuda="Esta computadora pasa a ser la principal y trabaja con sus propios datos."), self.botones.ButtonRole.ResetRole)
        self.botones.addButton(boton("Actualizar programa", self.actualizar,
                                     ayuda="El cliente y el servidor tienen que tener la misma versión."),
                               self.botones.ButtonRole.ResetRole)
        (self.usuario if self.host.text() else self.host).setFocus()

    def actualizar(self) -> None:
        from ..servicios import actualizador
        from .comunes import informar

        exe = actualizador.ruta_ejecutable()
        if exe is None:
            raise ErrorNegocio("La actualización automática solo funciona en el programa instalado (ExaPyme.exe).")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            instalada = actualizador.actualizar(exe)
        finally:
            QApplication.restoreOverrideCursor()
        if instalada is None:
            informar(self, "Esta computadora ya tiene la última versión de Exa Pyme.")
            return
        informar(self, f"Exa Pyme se actualizó a la versión {instalada.version}. El programa se va a reiniciar.")
        actualizador.reiniciar(exe)
        self.reject()

    def pasar_a_servidor(self) -> None:
        self.cambiar_modo = True
        self.reject()

    def _conectar(self):
        host, puerto = self.host.text().strip(), self.puerto.value()
        if not host:
            raise ErrorNegocio("Escribí la dirección IP del servidor.")
        if not self.usuario.text().strip():
            raise ErrorNegocio("Escribí tu usuario.")
        if not self.puesto.text().strip():
            raise ErrorNegocio("Escribí un nombre para esta caja, por ejemplo «Caja 2».")
        # La huella guardada vale solo para el mismo servidor; con otra dirección se confía en el nuevo.
        huella = self.huella if (host, puerto) == self.origen else ""
        ctx = ContextoRemoto(Cliente(host, puerto, huella))
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            ctx.ingresar(self.usuario.text(), self.clave.text(), self.puesto.text().strip())
        finally:
            QApplication.restoreOverrideCursor()
        return ctx

    def guardar(self) -> None:
        try:
            ctx = self._conectar()
        except HuellaDistinta as e:
            if not confirmar(self, str(e) + "\n\n¿Confiar en este servidor?", "Confiar"):
                return
            self.huella, self.origen = e.huella, (self.host.text().strip(), self.puerto.value())
            ctx = self._conectar()
        except ErrorNegocio:
            self.clave.clear()
            self.clave.setFocus()
            raise
        preferencias.guardar(puesto=ctx.puesto)
        if self.recordar.isChecked():
            preferencias.guardar(servidor_host=ctx.cliente.host, servidor_puerto=ctx.cliente.puerto, servidor_huella=ctx.cliente.huella)
        else:
            preferencias.guardar(servidor_host="", servidor_huella="")
        self.ctx = ctx
        self.accept()
