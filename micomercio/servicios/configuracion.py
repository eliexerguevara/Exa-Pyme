from __future__ import annotations

from decimal import Decimal

from ..core.dinero import D

PREDETERMINADOS = {
    # Datos del comercio (se imprimen en el ticket)
    "comercio_nombre": "Mi Comercio",
    "comercio_direccion": "",
    "comercio_telefono": "",
    "ticket_pie": "¡Gracias por su compra!",
    # Impresión
    "impresora": "",
    "ticket_ancho": "80",  # 80 | 58 | A4
    "ticket_imprimir_automatico": "0",
    # Ventas
    "descuento_maximo_cajero_pct": "10",
    "permitir_stock_negativo": "0",
    # Precios
    "impuesto_predeterminado": "21",
    "metodo_precio_predeterminado": "margen",
    # Copias de seguridad
    "copias_carpeta": "",
    "copias_automaticas": "1",
    "copias_conservar": "30",
    "copias_ultima_automatica": "",
    # Datos fiscales (los usa el módulo ARCA; no contiene claves ni certificados)
    "fiscal_razon_social": "",
    "fiscal_cuit": "",
    "fiscal_condicion_iva": "",
    "fiscal_domicilio": "",
    "fiscal_ingresos_brutos": "",
    "fiscal_inicio_actividades": "",
    "fiscal_punto_venta": "",
    "fiscal_entorno": "homologacion",
    "fiscal_habilitado": "0",
    "fiscal_automatico": "0",
}


class Configuracion:
    def __init__(self, ctx):
        self.ctx = ctx

    def obtener(self, clave: str) -> str:
        valor = self.ctx.db.valor("SELECT valor FROM configuracion WHERE clave = ?", (clave,))
        if valor is None:
            return PREDETERMINADOS.get(clave, "")
        return valor

    def booleano(self, clave: str) -> bool:
        return self.obtener(clave) == "1"

    def decimal(self, clave: str) -> Decimal:
        try:
            return D(self.obtener(clave) or "0")
        except Exception:
            return D(PREDETERMINADOS.get(clave, "0") or "0")

    def entero(self, clave: str) -> int:
        try:
            return int(self.obtener(clave))
        except ValueError:
            return int(PREDETERMINADOS.get(clave, "0") or 0)

    def guardar(self, valores: dict[str, str], auditar: bool = True) -> None:
        if auditar:
            self.ctx.requiere("configuracion")
        with self.ctx.db.transaccion():
            for clave, valor in valores.items():
                if isinstance(valor, bool):
                    valor = "1" if valor else "0"
                self.ctx.db.ejecutar(
                    "INSERT INTO configuracion (clave, valor) VALUES (?, ?) "
                    "ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor",
                    (clave, str(valor)),
                )
            if auditar:
                self.ctx.auditar("configuracion", "configuracion", None, ", ".join(sorted(valores)))
