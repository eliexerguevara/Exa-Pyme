from __future__ import annotations

from ...core.dinero import fmt_dinero
from ...core.util import fecha_legible
from .. import tema
from ..comunes import Pagina, Tarjeta, boton, etiqueta, fila
from ..resumen_caja import ResumenCaja


class PaginaInicio(Pagina):
    titulo = "Inicio"

    def armar(self) -> None:
        self.estado = etiqueta("", "suave")
        self.cuerpo.addWidget(self.estado)

        self.boton_venta = boton("Nueva venta  (F2)", lambda: self.ventana.ir("venta"), "primario", "venta")
        self.boton_venta.setProperty("tipo", "primario")
        self.boton_venta.setMinimumHeight(48)
        self.boton_caja = boton("Abrir caja", lambda: self.ventana.ir("caja"), icono="caja")
        self.boton_caja.setMinimumHeight(48)
        self.cuerpo.addLayout(fila(self.boton_venta, self.boton_caja, None))

        self.t_ventas = Tarjeta("Ventas del día")
        self.t_cobrado = Tarjeta("Efectivamente cobrado")
        self.t_pendientes = Tarjeta("Pagos pendientes")
        self.t_bajo = Tarjeta("Productos con stock bajo")
        self.t_agotados = Tarjeta("Productos agotados")
        self.cuerpo.addLayout(fila(self.t_ventas, self.t_cobrado, self.t_pendientes, self.t_bajo, self.t_agotados, espacio=12))

        self.titulo_resumen = etiqueta("Caja del día", "subtitulo")
        self.cuerpo.addWidget(self.titulo_resumen)
        self.resumen = ResumenCaja()
        self.cuerpo.addWidget(self.resumen)
        self.cuerpo.addStretch(1)

    def refrescar(self) -> None:
        ctx = self.ctx
        self.boton_venta.setVisible(ctx.puede("vender"))
        self.boton_caja.setVisible(ctx.puede("caja"))
        caja = ctx.caja.abierta()
        ultima = caja or ctx.caja.ultima()
        r = ctx.caja.resumen(ultima["id"]) if ultima else None
        if caja:
            self.estado.setText(f"{ctx.puesto}: caja abierta desde el {fecha_legible(caja['abierta_en'])}.")
            self.boton_caja.setText("Ver caja diaria")
            self.titulo_resumen.setText("Caja del día")
        else:
            self.estado.setText(f"{ctx.puesto}: la caja está cerrada. Abrila para empezar a vender.")
            self.boton_caja.setText("Abrir caja")
            self.titulo_resumen.setText(
                f"Última jornada de caja (cerrada el {fecha_legible(ultima['cerrada_en'])})" if ultima else "Caja del día"
            )
        self.resumen.mostrar(r)
        if r and caja:
            self.t_ventas.poner(f"{fmt_dinero(r['ventas_total_cent'])}")
            self.t_cobrado.poner(fmt_dinero(r["cobrado_total_cent"]), tema.VERDE)
        else:
            self.t_ventas.poner("—")
            self.t_cobrado.poner("—")
        pendientes = sum(p["monto_cent"] for p in ctx.ventas.pagos_pendientes())
        self.t_pendientes.poner(fmt_dinero(pendientes), tema.NARANJA if pendientes else tema.TEXTO)
        alertas = ctx.inventario.alertas()
        self.t_bajo.poner(str(alertas["bajos"]), tema.NARANJA if alertas["bajos"] else tema.TEXTO)
        self.t_agotados.poner(str(alertas["agotados"]), tema.ROJO if alertas["agotados"] else tema.TEXTO)
