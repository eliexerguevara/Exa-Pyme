"""Aspecto visual: fondo claro, detalles azules, tipografía Segoe UI."""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

AZUL = "#2563EB"
AZUL_OSCURO = "#1D4ED8"
AZUL_CLARO = "#EFF4FF"
FONDO = "#F4F6FA"
BORDE = "#DFE3EB"
TEXTO = "#1F2937"
TEXTO_SUAVE = "#6B7280"
VERDE = "#15803D"
ROJO = "#DC2626"
NARANJA = "#B45309"

HOJA_DE_ESTILO = f"""
* {{ font-family: 'Segoe UI'; font-size: 10pt; color: {TEXTO}; }}
QMainWindow, QDialog, #contenido {{ background: {FONDO}; }}
QToolTip {{ background: #111827; color: white; border: 0; padding: 4px 6px; }}

#lateral {{ background: white; border-right: 1px solid {BORDE}; }}
#marca {{ font-size: 15pt; font-weight: 700; color: {AZUL}; padding: 18px 18px 4px 18px; }}
#submarca {{ color: {TEXTO_SUAVE}; font-size: 9pt; padding: 0 18px 12px 18px; }}
#lateral QPushButton {{
    text-align: left; padding: 9px 14px; margin: 1px 10px; border: 0; border-radius: 8px;
    background: transparent; color: #374151; font-size: 10.5pt;
}}
#lateral QPushButton:hover {{ background: {FONDO}; }}
#lateral QPushButton:checked {{ background: {AZUL_CLARO}; color: {AZUL}; font-weight: 600; }}
#lateral QPushButton#actualizar {{
    background: {AZUL}; color: white; text-align: center; font-weight: 600; margin: 4px 18px 10px 18px; padding: 9px 8px;
}}
#lateral QPushButton#actualizar:hover {{ background: {AZUL_OSCURO}; }}
#usuario {{ color: {TEXTO_SUAVE}; font-size: 9pt; padding: 10px 18px; border-top: 1px solid {BORDE}; }}

#titulo {{ font-size: 17pt; font-weight: 600; }}
#subtitulo {{ font-size: 11.5pt; font-weight: 600; }}
#suave {{ color: {TEXTO_SUAVE}; }}
#aviso {{ background: #FEF3C7; color: #78350F; border: 1px solid #FCD34D; border-radius: 8px; padding: 8px 10px; }}
#nota {{ background: {AZUL_CLARO}; color: #1E3A8A; border: 1px solid #C7D7FE; border-radius: 8px; padding: 8px 10px; }}
#tarjeta {{ background: white; border: 1px solid {BORDE}; border-radius: 10px; }}
#tarjetaTitulo {{ color: {TEXTO_SUAVE}; font-size: 9.5pt; }}
#tarjetaValor {{ font-size: 16pt; font-weight: 600; }}
#total {{ font-size: 26pt; font-weight: 700; color: {AZUL}; }}
#grande {{ font-size: 13pt; font-weight: 600; }}
#chip {{ border-radius: 11px; padding: 3px 12px; font-size: 9.5pt; font-weight: 600; }}

QPushButton {{
    background: white; border: 1px solid #CBD2DD; border-radius: 7px; padding: 7px 14px; min-height: 18px;
}}
QPushButton:hover {{ background: #F9FAFB; border-color: #9AA5B5; }}
QPushButton:pressed {{ background: #EEF1F5; }}
QPushButton:disabled {{ color: #A3ABB8; background: #F3F4F6; border-color: {BORDE}; }}
QPushButton:focus {{ border: 1px solid {AZUL}; }}
QPushButton[tipo="primario"] {{ background: {AZUL}; color: white; border: 1px solid {AZUL}; font-weight: 600; }}
QPushButton[tipo="primario"]:hover {{ background: {AZUL_OSCURO}; }}
QPushButton[tipo="primario"]:disabled {{ background: #A9C0F5; border-color: #A9C0F5; color: white; }}
QPushButton[tipo="peligro"] {{ color: {ROJO}; border-color: #F1B5B5; }}
QPushButton[tipo="peligro"]:hover {{ background: #FEF2F2; }}
QPushButton[tipo="cobro"] {{
    background: {AZUL}; color: white; border: 0; border-radius: 10px; font-size: 12pt; font-weight: 600; padding: 14px 8px;
}}
QPushButton[tipo="cobro"]:hover {{ background: {AZUL_OSCURO}; }}
QPushButton[tipo="cobro"]:disabled {{ background: #A9C0F5; }}
QPushButton[tipo="grande"] {{ font-size: 12pt; font-weight: 600; padding: 14px 22px; border-radius: 10px; }}

QLineEdit, QComboBox, QDateEdit, QSpinBox, QPlainTextEdit, QTextEdit {{
    background: white; border: 1px solid #CBD2DD; border-radius: 7px; padding: 6px 8px; min-height: 18px;
    selection-background-color: {AZUL}; selection-color: white;
}}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QSpinBox:focus, QPlainTextEdit:focus {{ border: 1px solid {AZUL}; }}
QLineEdit:read-only {{ background: #F3F4F6; color: #4B5563; }}
QLineEdit#buscador {{ font-size: 13pt; padding: 10px 12px; border-radius: 9px; }}
QComboBox::drop-down {{ border: 0; width: 22px; }}
QComboBox QAbstractItemView {{ background: white; border: 1px solid {BORDE}; selection-background-color: {AZUL_CLARO}; selection-color: {TEXTO}; }}

QTableWidget, QListWidget, QTextBrowser {{
    background: white; border: 1px solid {BORDE}; border-radius: 8px; gridline-color: #EEF0F4;
    alternate-background-color: #FAFBFC; selection-background-color: {AZUL_CLARO}; selection-color: {TEXTO}; outline: 0;
}}
QTableWidget::item {{ padding: 4px 6px; }}
QListWidget::item {{ padding: 7px 8px; }}
QHeaderView::section {{
    background: #F3F5F9; border: 0; border-bottom: 1px solid {BORDE}; padding: 7px 6px; font-weight: 600; color: #4B5563;
}}
QTableCornerButton::section {{ background: #F3F5F9; border: 0; }}

QTabWidget::pane {{ border: 0; border-top: 1px solid {BORDE}; }}
QTabBar::tab {{ background: transparent; padding: 8px 16px; border: 0; border-bottom: 2px solid transparent; color: {TEXTO_SUAVE}; }}
QTabBar::tab:selected {{ color: {AZUL}; border-bottom: 2px solid {AZUL}; font-weight: 600; }}
QCheckBox, QRadioButton {{ spacing: 7px; }}
QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #C5CBD6; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #C5CBD6; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
"""

# Íconos de línea propios (24 x 24), dibujados para Exa Pyme.
_SVG = {
    "inicio": "<path d='M4 11l8-7 8 7v8a1 1 0 0 1-1 1h-4v-6h-6v6H5a1 1 0 0 1-1-1z'/>",
    "venta": "<circle cx='9' cy='20' r='1.4'/><circle cx='17' cy='20' r='1.4'/><path d='M3 4h2.5l2.2 11h10.2l2-8H7'/>",
    "productos": "<path d='M12 3l8 4.5v9L12 21l-8-4.5v-9z'/><path d='M4 7.5l8 4.5 8-4.5M12 12v9'/>",
    "inventario": "<rect x='4' y='4' width='16' height='6' rx='1'/><rect x='4' y='14' width='16' height='6' rx='1'/><path d='M8 7h2M8 17h2'/>",
    "compras": "<path d='M3 7h11v9H3zM14 10h4l3 3v3h-7'/><circle cx='7' cy='18' r='1.6'/><circle cx='17' cy='18' r='1.6'/>",
    "clientes": "<circle cx='9' cy='8' r='3.2'/><path d='M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6'/><circle cx='17' cy='9' r='2.4'/><path d='M16.5 14.2c2.6.3 4.5 2.6 4.5 5.3'/>",
    "historial": "<circle cx='12' cy='12' r='8.5'/><path d='M12 7v5l3.5 2'/>",
    "caja": "<rect x='3' y='6' width='18' height='12' rx='2'/><circle cx='12' cy='12' r='2.6'/><path d='M6.5 9.5v5M17.5 9.5v5'/>",
    "facturacion": "<path d='M6 3h12v18l-3-2-3 2-3-2-3 2z'/><path d='M9 8h6M9 12h6'/>",
    "reportes": "<path d='M4 20V4M4 20h16'/><path d='M8 16v-4M12 16V8M16 16v-6'/>",
    "configuracion": "<circle cx='12' cy='12' r='3'/><path d='M12 3v2.5M12 18.5V21M3 12h2.5M18.5 12H21M5.6 5.6l1.8 1.8M16.6 16.6l1.8 1.8M5.6 18.4l1.8-1.8M16.6 7.4l1.8-1.8'/>",
    "guia": "<circle cx='12' cy='12' r='8.5'/><path d='M9.6 9.4a2.5 2.5 0 1 1 3.6 2.3c-.8.4-1.2 1-1.2 1.9'/><path d='M12 16.6v.2'/>",
    "copias": "<path d='M7 18a4.5 4.5 0 0 1-.6-8.96A6 6 0 0 1 18 10.5a3.8 3.8 0 0 1-.5 7.5z'/><path d='M12 11v5M9.8 13.2L12 11l2.2 2.2'/>",
}


def icono(nombre: str, color: str = "#4B5563", tamano: int = 22) -> QIcon:
    svg = (
        f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='{color}' "
        f"stroke-width='1.7' stroke-linecap='round' stroke-linejoin='round'>{_SVG[nombre]}</svg>"
    )
    render = QSvgRenderer(QByteArray(svg.encode()))
    imagen = QPixmap(QSize(tamano * 2, tamano * 2))
    imagen.fill(Qt.transparent)
    pintor = QPainter(imagen)
    render.render(pintor)
    pintor.end()
    return QIcon(imagen)


def icono_menu(nombre: str) -> QIcon:
    """Ícono gris que pasa a azul cuando el botón del menú está seleccionado."""
    ic = icono(nombre)
    ic.addPixmap(icono(nombre, AZUL).pixmap(44, 44), QIcon.Normal, QIcon.On)
    return ic


def icono_aplicacion() -> QIcon:
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>"
        f"<rect width='64' height='64' rx='14' fill='{AZUL}'/>"
        "<path d='M42 20H24v24h18M24 32h14' fill='none' stroke='white' stroke-width='6' "
        "stroke-linecap='round' stroke-linejoin='round'/></svg>"
    )
    render = QSvgRenderer(QByteArray(svg.encode()))
    imagen = QPixmap(256, 256)
    imagen.fill(Qt.transparent)
    pintor = QPainter(imagen)
    render.render(pintor)
    pintor.end()
    return QIcon(imagen)
