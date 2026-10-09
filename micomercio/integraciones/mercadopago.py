"""Cobros con Mercado Pago — módulo preparado para la etapa 8.

Estado actual: NO se conecta con Mercado Pago. Los cobros con este medio se
registran a mano: quedan «pendientes» hasta que el comerciante confirma, después
de verificarlo en su propia cuenta, que el dinero ingresó.

Qué debe implementar la etapa 8 (con las APIs oficiales vigentes):
  1. crear_cobro(): generar la orden o el QR por el importe de la venta, usando
     el id de la venta como referencia externa, y guardar el identificador que
     devuelve Mercado Pago en pagos.id_externo (tiene índice único: un mismo
     cobro no puede registrarse dos veces).
  2. consultar_estado(): preguntar a la API por ese identificador y traducir la
     respuesta con ESTADOS. Solo un estado aprobado informado por la API (o por
     una notificación con firma verificada) confirma el pago, mediante
     ventas.confirmar_pago(); nunca una captura de pantalla.
  3. Registrar la comisión informada por Mercado Pago en pagos.comision_cent.

Credenciales: el access token se guarda en el Administrador de credenciales de
Windows. Nunca en el código fuente, en la base de datos ni en los registros.
"""
from __future__ import annotations

from dataclasses import dataclass

# Estado informado por Mercado Pago -> estado del pago en MiComercio
ESTADOS = {
    "approved": "confirmado",
    "pending": "pendiente",
    "in_process": "pendiente",
    "authorized": "pendiente",
    "rejected": "rechazado",
    "cancelled": "cancelado",
}


@dataclass
class EstadoIntegracion:
    disponible: bool
    mensaje: str


class ServicioMercadoPago:
    """Interfaz que usa la aplicación. La etapa 8 la implementa en una subclase."""

    def __init__(self, ctx):
        self.ctx = ctx

    def estado(self) -> EstadoIntegracion:
        return EstadoIntegracion(
            False,
            "La conexión automática con Mercado Pago todavía no está habilitada en esta versión. "
            "Los cobros se confirman a mano, después de verificarlos en la cuenta.",
        )

    def crear_cobro(self, venta_id: int, monto_cent: int):
        raise NotImplementedError("La creación de cobros corresponde a la etapa 8.")

    def consultar_estado(self, id_externo: str) -> str:
        raise NotImplementedError("La consulta de pagos corresponde a la etapa 8.")


def crear_servicio(ctx) -> ServicioMercadoPago:
    return ServicioMercadoPago(ctx)
