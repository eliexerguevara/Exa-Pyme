from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QLineEdit, QPlainTextEdit, QTabWidget, QVBoxLayout,
    QWidget,
)

from ...core.errores import ErrorNegocio
from ...integraciones import arca
from ...integraciones.arca import impreso
from ...integraciones.arca.transporte import ErrorConexion
from .. import tema
from ..comunes import (
    Dialogo, Pagina, SelectorPeriodo, Tabla, advertir, boton, cd, cf, confirmar, etiqueta, fila, informar, panel,
)
from ..impresion import mostrar_comprobante

COLORES = {"pendiente": tema.NARANJA, "rechazada": tema.ROJO, "nota_credito": "#9CA3AF", "autorizada": tema.VERDE}

PASOS_HOMOLOGACION = """<b>Cómo obtener el certificado de homologación (pruebas)</b>
<ol>
<li>Pulsá <b>1. Generar pedido de certificado</b> y guardá el archivo <i>.csr</i>.</li>
<li>Entrá al sitio de ARCA con tu clave fiscal y abrí el servicio <b>«WSASS - Autogestión Certificados Homologación»</b>
(si no aparece, agregalo desde «Administrador de Relaciones de Clave Fiscal»).</li>
<li>En <b>Nuevo Certificado</b>, escribí un nombre, pegá el contenido del archivo <i>.csr</i> y creá el certificado.
Copiá el texto del certificado que devuelve.</li>
<li>En <b>Crear autorización a servicio</b>, autorizá ese certificado para el servicio <b>wsfe</b>.</li>
<li>Volvé acá, pulsá <b>2. Pegar certificado</b> y pegá el texto. Después, <b>3. Probar conexión</b>.</li>
</ol>"""

PASOS_PRODUCCION = """<b>Cómo obtener el certificado de producción (facturas reales)</b>
<ol>
<li>Pulsá <b>1. Generar pedido de certificado</b> y guardá el archivo <i>.csr</i>.</li>
<li>En el sitio de ARCA, con clave fiscal, abrí <b>«Administración de Certificados Digitales»</b>, agregá un alias
(por ejemplo <i>micomercio</i>), subí el archivo <i>.csr</i> y descargá el certificado <i>.crt</i>.</li>
<li>En <b>«Administrador de Relaciones de Clave Fiscal»</b> creá una nueva relación: servicio ARCA → WebServices →
<b>«Facturación Electrónica»</b>, y como representante elegí el alias del paso anterior.</li>
<li>En <b>«Administración de puntos de venta y domicilios»</b> dá de alta un punto de venta del tipo
<b>«RECE para aplicativo y web services»</b> y cargá ese número en la pestaña Datos fiscales.</li>
<li>Volvé acá, pulsá <b>2. Importar certificado (.crt)</b> y después <b>3. Probar conexión</b>.</li>
</ol>"""


def con_espera(funcion):
    """Ejecuta una operación que habla con ARCA mostrando el cursor de espera."""
    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        return funcion()
    finally:
        QApplication.restoreOverrideCursor()


def mostrar_factura(padre, ctx, comprobante) -> None:
    titulo = f"{arca.NOMBRES_CLASE[comprobante['clase']]} {comprobante['letra']} {int(comprobante['numero']):08d}"
    mostrar_comprobante(padre, ctx, impreso.html_comprobante(ctx, comprobante["id"]), titulo)


class PaginaFacturacion(Pagina):
    titulo = "Facturación"

    def armar(self) -> None:
        self.servicio = arca.crear_servicio(self.ctx)
        self.estado = etiqueta("", "nota", True)
        self.cuerpo.addWidget(self.estado)
        self.pestanas = QTabWidget()
        self.pestanas.addTab(self._armar_comprobantes(), "Comprobantes")
        self.pestanas.addTab(self._armar_datos(), "Datos fiscales")
        self.pestanas.addTab(self._armar_certificado(), "Certificado")
        self.cuerpo.addWidget(self.pestanas, 1)

    # ---- pestaña comprobantes -------------------------------------------
    def _armar_comprobantes(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 12, 0, 0)
        self.periodo = SelectorPeriodo("Hoy")
        self.periodo.cambiado.connect(self.cargar_ventas)
        self.b_pendientes = boton("Reintentar pendientes", self.reintentar)
        v.addLayout(fila(self.periodo, None, self.b_pendientes))
        v.addLayout(fila(
            boton("Emitir factura", self.emitir, "primario"), boton("Ver / imprimir comprobante", self.ver),
            boton("Emitir nota de crédito", self.nota_credito, "peligro"), None,
            boton("Descartar pendiente", self.descartar),
        ))
        self.tabla = Tabla(["Venta N°", "Fecha", "Cliente", "Total", "Situación fiscal", "Detalle"], estirar=5)
        self.tabla.activada.connect(self.ver)
        v.addWidget(self.tabla, 1)
        return w

    def cargar_ventas(self) -> None:
        self.filas = {f["id"]: f for f in self.servicio.ventas(*self.periodo.rango())}
        filas, colores = [], {}
        for n, f in enumerate(self.filas.values()):
            detalle = f["motivo"]
            if f["estado"] == "anulada" and f["situacion"] == "sin_comprobante":
                detalle = "Venta anulada"
            filas.append([(str(f["id"]), f["id"]), cf(f["fecha"]), f["cliente"], cd(f["total_cent"]), f["texto"], detalle])
            if f["situacion"] in COLORES:
                colores[n] = COLORES[f["situacion"]]
        self.tabla.cargar(filas, list(self.filas), colores)
        pendientes = len(self.servicio.pendientes())
        self.b_pendientes.setText(f"Reintentar pendientes ({pendientes})")
        self.b_pendientes.setEnabled(pendientes > 0)

    def _fila(self) -> dict:
        return self.filas[self.tabla.id_requerido("Seleccioná una venta de la lista.")]

    def emitir(self) -> None:
        f = self._fila()
        if f["situacion"] == "autorizada":
            raise ErrorNegocio("Esta venta ya tiene factura. Usá «Ver / imprimir comprobante».")
        datos = self.servicio.armar(f["id"])
        real = self.servicio.entorno == "produccion"
        if not confirmar(
            self, f"Se va a emitir una Factura {datos['letra']} por la venta N° {f['id']} a nombre de "
                  f"{datos['receptor']['nombre']}.\n\n"
                  + ("Es una factura REAL: una vez autorizada por ARCA solo se anula con una nota de crédito."
                     if real else "Estás en HOMOLOGACIÓN: es un comprobante de prueba, sin validez fiscal.")
                  + "\n\n¿Emitir?", "Emitir factura"):
            return
        try:
            comprobante = con_espera(lambda: self.servicio.autorizar_venta(f["id"]))
        finally:
            self.refrescar()
        mostrar_factura(self, self.ctx, comprobante)

    def ver(self) -> None:
        f = self._fila()
        comprobante = f["nota"] if f["nota"] is not None and f["nota"]["estado"] == "autorizada" else f["factura"]
        if comprobante is None or comprobante["estado"] != "autorizada":
            raise ErrorNegocio("Esta venta no tiene un comprobante autorizado por ARCA para mostrar.")
        mostrar_factura(self, self.ctx, comprobante)

    def nota_credito(self) -> None:
        f = self._fila()
        if f["situacion"] != "autorizada" and not (f["nota"] is not None and f["nota"]["estado"] == "pendiente"):
            raise ErrorNegocio("Solo se puede emitir una nota de crédito de una venta con factura autorizada.")
        real = self.servicio.entorno == "produccion"
        dialogo = Dialogo(self, "Emitir nota de crédito", "Emitir nota de crédito", 500)
        dialogo.cuerpo.insertWidget(0, etiqueta(
            f"Se va a emitir una nota de crédito por el total de la {f['texto']}.\n\n"
            + ("La venta queda anulada: los productos vuelven al stock y el dinero cobrado se registra como "
               "devolución en la caja abierta. No se puede deshacer."
               if real else "Estás en HOMOLOGACIÓN: es una prueba y la venta no se anula."), ajustar=True))
        motivo = QLineEdit()
        dialogo.formulario.addRow("Motivo:", motivo)
        dialogo.terminar()
        if not dialogo.exec():
            return
        try:
            nota = con_espera(lambda: self.servicio.emitir_nota_credito(f["id"], motivo.text()))
        finally:
            self.refrescar()
            self.ventana.actualizar_estado()
        mostrar_factura(self, self.ctx, nota)

    def reintentar(self) -> None:
        r = con_espera(self.servicio.reintentar_pendientes)
        self.refrescar()
        texto = f"Comprobantes autorizados: {r['autorizados']}"
        if r["fallidos"]:
            advertir(self, texto + "\n\nNo se pudieron resolver:\n" + "\n".join(r["fallidos"][:10]), "Pendientes")
        else:
            informar(self, texto, "Pendientes")

    def descartar(self) -> None:
        f = self._fila()
        pendiente = next((c for c in (f["nota"], f["factura"]) if c is not None and c["estado"] == "pendiente"), None)
        if pendiente is None:
            raise ErrorNegocio("Esta venta no tiene un comprobante pendiente.")
        self.servicio.descartar_pendiente(pendiente["id"])
        self.refrescar()

    # ---- pestaña datos fiscales -----------------------------------------
    def _armar_datos(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 12, 0, 0)
        marco, vm = panel("Datos fiscales del comercio")
        formulario = QFormLayout()
        formulario.setSpacing(9)
        self.razon, self.cuit, self.domicilio = QLineEdit(), QLineEdit(), QLineEdit()
        self.iibb, self.inicio, self.punto = QLineEdit(), QLineEdit(), QLineEdit()
        self.cuit.setPlaceholderText("30-12345678-9")
        self.inicio.setPlaceholderText("dd/mm/aaaa")
        self.punto.setPlaceholderText("Punto de venta del tipo «RECE para aplicativo y web services»")
        self.condicion = QComboBox()
        self.condicion.addItems(arca.CONDICIONES_EMISOR)
        self.entorno = QComboBox()
        for clave, nombre in arca.ENTORNOS.items():
            self.entorno.addItem(nombre, clave)
        self.comprobantes = etiqueta("", "suave", True)
        self.condicion.currentTextChanged.connect(self.mostrar_comprobantes)
        self.habilitado = QCheckBox("Activar la facturación electrónica")
        self.automatico = QCheckBox("Emitir la factura automáticamente al registrar cada venta")
        formulario.addRow("Razón social:", self.razon)
        formulario.addRow("CUIT:", self.cuit)
        formulario.addRow("Condición frente al IVA:", self.condicion)
        formulario.addRow("Comprobantes que corresponden:", self.comprobantes)
        formulario.addRow("Domicilio comercial:", self.domicilio)
        formulario.addRow("Ingresos Brutos:", self.iibb)
        formulario.addRow("Inicio de actividades:", self.inicio)
        formulario.addRow("Punto de venta autorizado:", self.punto)
        formulario.addRow("Entorno:", self.entorno)
        formulario.addRow("", self.habilitado)
        formulario.addRow("", self.automatico)
        vm.addLayout(formulario)
        vm.addLayout(fila(boton("Guardar", self.guardar, "primario"), None))
        marco.setMaximumWidth(860)
        v.addWidget(marco)
        v.addStretch(1)
        return w

    def mostrar_comprobantes(self, condicion: str) -> None:
        textos = {
            "Responsable inscripto": "Factura A a responsables inscriptos y monotributistas (el cliente debe tener CUIT); "
                                     "Factura B a consumidores finales y exentos; notas de crédito A y B.",
            "Monotributista": "Factura C y nota de crédito C.",
            "Exento": "Factura C y nota de crédito C.",
        }
        self.comprobantes.setText(textos.get(condicion, "Elegí la condición frente al IVA."))

    def guardar(self) -> None:
        cuit, punto = self.cuit.text().strip(), self.punto.text().strip()
        if cuit and not arca.cuit_valido(cuit):
            raise ErrorNegocio("El CUIT no es válido. Revisá que tenga 11 números y que estén bien escritos.")
        if punto and not punto.isdigit():
            raise ErrorNegocio("El punto de venta debe ser un número.")
        cfg = self.ctx.config
        pasa_a_real = (self.entorno.currentData() == "produccion" and self.habilitado.isChecked()
                       and not (cfg.obtener("fiscal_entorno") == "produccion" and cfg.booleano("fiscal_habilitado")))
        if pasa_a_real and not confirmar(
            self, "Vas a activar la facturación en PRODUCCIÓN.\n\nA partir de ahora, cada factura que emitas es real y "
                  "queda registrada en ARCA. Conviene haber probado antes en homologación.\n\n¿Continuar?", "Activar producción"):
            return
        cfg.guardar({
            "fiscal_razon_social": self.razon.text().strip(), "fiscal_cuit": arca.formatear_cuit(cuit),
            "fiscal_condicion_iva": self.condicion.currentText(), "fiscal_domicilio": self.domicilio.text().strip(),
            "fiscal_ingresos_brutos": self.iibb.text().strip(), "fiscal_inicio_actividades": self.inicio.text().strip(),
            "fiscal_punto_venta": punto, "fiscal_entorno": self.entorno.currentData(),
            "fiscal_habilitado": self.habilitado.isChecked(), "fiscal_automatico": self.automatico.isChecked(),
        })
        self.refrescar()
        informar(self, "Los datos fiscales se guardaron.")

    # ---- pestaña certificado --------------------------------------------
    def _armar_certificado(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 12, 0, 0)
        self.estado_cert = etiqueta("", "subtitulo", True)
        v.addWidget(self.estado_cert)
        v.addLayout(fila(
            boton("1. Generar pedido de certificado", self.generar_pedido, "primario"),
            boton("2. Importar certificado (.crt)", self.importar_certificado), boton("2. Pegar certificado", self.pegar_certificado),
            boton("3. Probar conexión", self.probar), None, boton("Ya tengo una clave privada (.key)", self.importar_clave),
        ))
        self.pasos = etiqueta("", "tarjeta", True)
        self.pasos.setTextFormat(Qt.RichText)
        self.pasos.setMargin(14)
        v.addWidget(self.pasos)
        v.addWidget(etiqueta(
            "La clave privada se genera en esta computadora y queda cifrada para tu usuario de Windows: no se guarda en "
            "la base de datos ni en las copias de seguridad, y no se puede copiar a otra PC. Si cambiás de computadora, "
            "generá un certificado nuevo.", "suave", True))
        v.addStretch(1)
        return w

    def generar_pedido(self) -> None:
        self.ctx.requiere("facturacion")
        entorno = self.servicio.entorno
        pedido = self.servicio.generar_pedido()
        ruta, _ = QFileDialog.getSaveFileName(self, "Guardar el pedido de certificado", f"micomercio_{entorno}.csr",
                                              "Pedido de certificado (*.csr)")
        if ruta:
            Path(ruta).write_bytes(pedido)
            informar(self, f"El pedido se guardó en:\n{ruta}\n\nSeguí los pasos que figuran abajo para obtener el certificado en ARCA.")
        self.refrescar()

    def _importar(self, contenido: bytes) -> None:
        self.ctx.requiere("facturacion")
        info = self.servicio.importar_certificado(contenido)
        self.refrescar()
        informar(self, f"Certificado cargado. Es válido hasta el {info['certificado']['hasta']}.\n\nAhora pulsá «Probar conexión».")

    def importar_certificado(self) -> None:
        ruta, _ = QFileDialog.getOpenFileName(self, "Elegir el certificado", "", "Certificados (*.crt *.cer *.pem);;Todos (*.*)")
        if ruta:
            self._importar(Path(ruta).read_bytes())

    def pegar_certificado(self) -> None:
        dialogo = Dialogo(self, "Pegar certificado", "Cargar certificado", 620)
        dialogo.cuerpo.insertWidget(0, etiqueta(
            "Pegá el texto completo del certificado, desde «-----BEGIN CERTIFICATE-----» hasta «-----END CERTIFICATE-----».",
            ajustar=True))
        texto = QPlainTextEdit()
        texto.setMinimumHeight(260)
        dialogo.cuerpo.insertWidget(1, texto)
        dialogo.terminar()
        if dialogo.exec():
            self._importar(texto.toPlainText().strip().encode("ascii", "ignore"))

    def importar_clave(self) -> None:
        self.ctx.requiere("facturacion")
        ruta, _ = QFileDialog.getOpenFileName(self, "Elegir la clave privada", "", "Clave privada (*.key *.pem);;Todos (*.*)")
        if ruta:
            self.servicio.importar_clave(Path(ruta).read_bytes())
            self.refrescar()
            informar(self, "La clave privada se guardó cifrada. Ahora importá el certificado que le corresponde.")

    def probar(self) -> None:
        try:
            lineas = con_espera(self.servicio.probar_conexion)
        except ErrorConexion as e:
            advertir(self, str(e), "Prueba de conexión")
            return
        informar(self, "La conexión con ARCA funciona.\n\n" + "\n".join(lineas), "Prueba de conexión")

    # ---- general ---------------------------------------------------------
    def refrescar(self) -> None:
        cfg = self.ctx.config
        self.razon.setText(cfg.obtener("fiscal_razon_social"))
        self.cuit.setText(cfg.obtener("fiscal_cuit"))
        self.condicion.setCurrentText(cfg.obtener("fiscal_condicion_iva"))
        self.mostrar_comprobantes(self.condicion.currentText())
        self.domicilio.setText(cfg.obtener("fiscal_domicilio"))
        self.iibb.setText(cfg.obtener("fiscal_ingresos_brutos"))
        self.inicio.setText(cfg.obtener("fiscal_inicio_actividades"))
        self.punto.setText(cfg.obtener("fiscal_punto_venta"))
        self.entorno.setCurrentIndex(max(0, self.entorno.findData(cfg.obtener("fiscal_entorno"))))
        self.habilitado.setChecked(cfg.booleano("fiscal_habilitado"))
        self.automatico.setChecked(cfg.booleano("fiscal_automatico"))

        estado = self.servicio.estado()
        self.estado.setText(estado.mensaje)
        self.estado.setObjectName("nota" if estado.disponible and self.servicio.entorno == "produccion" else "aviso")
        self.estado.setStyleSheet("")  # vuelve a aplicar el estilo según el nombre
        self.estado.style().unpolish(self.estado)
        self.estado.style().polish(self.estado)

        entorno = self.servicio.entorno
        info = self.servicio.estado_certificado()
        nombre = "homologación" if entorno == "homologacion" else "producción"
        if info["certificado"] and info["clave"]:
            c = info["certificado"]
            texto = (f"Certificado de {nombre}: VENCIDO el {c['hasta']}." if c["vencido"]
                     else f"Certificado de {nombre}: cargado, válido hasta el {c['hasta']} ({c['dias_restantes']} días).")
        elif info["pedido_pendiente"]:
            texto = f"Certificado de {nombre}: pedido generado; falta cargar el certificado que entrega ARCA."
        else:
            texto = f"Certificado de {nombre}: todavía no se cargó."
        if info["certificado"] and info["pedido_pendiente"]:
            texto += " Hay un pedido nuevo generado, a la espera de su certificado."
        self.estado_cert.setText(texto)
        self.pasos.setText(PASOS_HOMOLOGACION if entorno == "homologacion" else PASOS_PRODUCCION)
        self.cargar_ventas()
