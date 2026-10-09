"""Primer uso (creación del administrador) e inicio de sesión."""
from __future__ import annotations

from PySide6.QtWidgets import QLineEdit

from ..core.errores import ErrorNegocio
from .comunes import Dialogo, etiqueta


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
