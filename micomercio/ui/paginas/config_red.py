from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QSpinBox, QVBoxLayout, QWidget

from ... import preferencias
from ...red.servidor import direcciones_locales
from ..comunes import Tabla, boton, confirmar, etiqueta, fila, informar, panel


class PanelRed(QWidget):
    """Pestaña de Configuración: cómo trabaja esta computadora con las demás (servidor o cliente)."""

    def __init__(self, ctx, ventana):
        super().__init__()
        self.ctx, self.ventana = ctx, ventana
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 12, 0, 0)
        self.estado = etiqueta("", "nota", True)
        v.addWidget(self.estado)

        self.marco_servidor, vs = panel("Esta computadora es el servidor (tiene los datos del comercio)")
        self.activa = QCheckBox("Permitir que otras computadoras se conecten a esta")
        self.puerto = QSpinBox()
        self.puerto.setRange(1024, 65535)
        vs.addLayout(fila(self.activa, 16, etiqueta("Puerto:"), self.puerto, boton("Guardar", self.guardar, "primario"), None))
        self.direcciones = etiqueta("", "subtitulo", True)
        vs.addWidget(self.direcciones)
        vs.addWidget(etiqueta(
            "La primera vez, Windows puede preguntar si permitís que Exa Pyme se comunique por la red: elegí «Permitir» "
            "en redes privadas. Las otras computadoras tienen que estar en la misma red (mismo router o Wi-Fi) y esta "
            "tiene que estar encendida con Exa Pyme abierto. Conviene que esta computadora tenga siempre la misma IP.",
            "suave", True))
        vs.addWidget(etiqueta("Computadoras conectadas ahora", "subtitulo"))
        self.tabla = Tabla(["Usuario", "Dirección", "Última actividad"], estirar=0, ordenable=False)
        self.tabla.setMaximumHeight(180)
        vs.addWidget(self.tabla)
        vs.addLayout(fila(boton("Actualizar lista", self.refrescar), None))
        v.addWidget(self.marco_servidor)

        v.addLayout(fila(boton("Cambiar el modo de esta computadora…", self.cambiar_modo), None))
        v.addStretch(1)

    def refrescar(self) -> None:
        prefs = preferencias.leer()
        remoto = getattr(self.ctx, "remoto", False)
        self.marco_servidor.setVisible(not remoto)
        if remoto:
            cliente = self.ctx.cliente
            self.estado.setText(f"Esta computadora es un CLIENTE. Está conectada al servidor {cliente.host}, puerto {cliente.puerto}. "
                                "Los datos del comercio están en esa computadora.")
            return
        servidor = self.ventana.servidor
        self.activa.setChecked(bool(prefs["red_activa"]))
        self.puerto.setValue(int(prefs["red_puerto"]))
        if servidor is not None and servidor.activo:
            ips = direcciones_locales()
            self.estado.setText("El servidor está activo: otras computadoras pueden conectarse.")
            self.direcciones.setText("En las otras computadoras escribí:   IP  " + "  o  ".join(ips) + f"     Puerto  {servidor.puerto}")
            conectados = servidor.conectados()
            self.tabla.cargar([[c["usuario"], c["ip"], "recién" if c["hace"] < 60 else f"hace {c['hace'] // 60} min"]
                               for c in conectados])
        else:
            self.estado.setText("Esta computadora trabaja sola: ninguna otra puede conectarse. Para sumar otras cajas, "
                                "tildá la opción de abajo y guardá.")
            self.direcciones.setText("")
            self.tabla.cargar([])

    def guardar(self) -> None:
        self.ctx.requiere("configuracion")
        preferencias.guardar(red_activa=self.activa.isChecked(), red_puerto=self.puerto.value())
        self.ventana.aplicar_red()
        self.refrescar()
        informar(self, "La configuración de red se guardó.")

    def cambiar_modo(self) -> None:
        from ..acceso import DialogoModo

        self.ctx.requiere("configuracion")
        dialogo = DialogoModo(self, preferencias.leer())
        if not dialogo.exec():
            return
        actual = "cliente" if getattr(self.ctx, "remoto", False) else "servidor"
        if dialogo.modo == actual:
            preferencias.guardar(**dialogo.valores())
            self.ventana.aplicar_red()
            self.refrescar()
            return
        aviso = ("Esta computadora va a pasar a ser un CLIENTE: va a usar los datos de otra computadora. Los datos "
                 "guardados acá no se borran, pero dejan de usarse." if dialogo.modo == "cliente" else
                 "Esta computadora va a pasar a ser el SERVIDOR: va a trabajar con sus propios datos, no con los de la otra.")
        if not confirmar(self, aviso + "\n\nEl programa se va a cerrar para aplicar el cambio. ¿Continuar?", "Cambiar"):
            return
        preferencias.guardar(**dialogo.valores())
        self.ventana.close()
