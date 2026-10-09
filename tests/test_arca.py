"""Facturación electrónica contra un ARCA simulado (mismos mensajes SOAP que los servicios reales)."""
import base64
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from conftest import vender
from micomercio.core.errores import ErrorNegocio
from micomercio.db import BaseDatos
from micomercio.db.esquema import MIGRACIONES
from micomercio.integraciones import arca
from micomercio.integraciones.arca import credenciales, impreso, wsaa
from micomercio.integraciones.arca.servicio import ServicioArca, numero_completo
from micomercio.integraciones.arca.transporte import ErrorConexion
from micomercio.integraciones.arca.wsfe import Wsfe

CUIT = "20-12345678-6"
NS = "http://ar.gov.afip.dif.FEV1/"
ORDEN_OFICIAL = ["Concepto", "DocTipo", "DocNro", "CbteDesde", "CbteHasta", "CbteFch", "ImpTotal", "ImpTotConc", "ImpNeto",
                 "ImpOpEx", "ImpTrib", "ImpIVA", "FchServDesde", "FchServHasta", "FchVtoPago", "MonId", "MonCotiz",
                 "CanMisMonExt", "CondicionIVAReceptorId", "CbtesAsoc", "Tributos", "Iva", "Opcionales", "Compradores",
                 "PeriodoAsoc", "Actividades"]


def emitir_certificado(pedido_pem: bytes, cuit_en_certificado: str | None = None, dias: int = 365) -> bytes:
    """Hace de ARCA: firma el pedido con una autoridad de prueba."""
    pedido = x509.load_pem_x509_csr(pedido_pem)
    autoridad = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    sujeto = pedido.subject
    if cuit_en_certificado:
        sujeto = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "otro"),
                            x509.NameAttribute(NameOID.SERIAL_NUMBER, f"CUIT {cuit_en_certificado}")])
    ahora = datetime.now(timezone.utc)
    certificado = (x509.CertificateBuilder().subject_name(sujeto)
                   .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Autoridad de prueba")]))
                   .public_key(pedido.public_key()).serial_number(x509.random_serial_number())
                   .not_valid_before(ahora - timedelta(days=1)).not_valid_after(ahora + timedelta(days=dias))
                   .sign(autoridad, hashes.SHA256()))
    return certificado.public_bytes(serialization.Encoding.PEM)


class ArcaSimulado:
    """Responde como WSAA y WSFEv1. Lleva la numeración y registra lo que se le pide."""

    def __init__(self):
        self.ultimo: dict[tuple[int, int], int] = {}
        self.autorizados: dict[tuple[int, int, int], dict] = {}
        self.llamadas: list[str] = []
        self.pedidos: list[str] = []
        self.modo = "aprobar"        # aprobar | rechazar | sin_cae | cortar_antes | cortar_despues
        self.cae = 75000000000000

    def _sobre(self, contenido: str) -> bytes:
        return (f'<?xml version="1.0"?><soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body>'
                f"{contenido}</soap:Body></soap:Envelope>").encode()

    def __call__(self, url: str, accion: str, cuerpo: str) -> bytes:
        if "loginCms" in cuerpo:
            self.llamadas.append("loginCms")
            cms = base64.b64decode(re.search(r"<wsaa:in0>(.*?)</wsaa:in0>", cuerpo).group(1))
            assert b"<service>wsfe</service>" in cms          # la firma lleva el pedido adentro
            vence = (datetime.now().astimezone() + timedelta(hours=12)).isoformat()
            ticket = (f'<loginTicketResponse version="1.0"><header><expirationTime>{vence}</expirationTime></header>'
                      "<credentials><token>TOKEN-DE-PRUEBA</token><sign>SIGN-DE-PRUEBA</sign></credentials></loginTicketResponse>")
            return self._sobre('<loginCmsResponse xmlns="http://wsaa.view.sua.dvadac.desein.afip.gov"><loginCmsReturn>'
                               + ticket.replace("<", "&lt;").replace(">", "&gt;") + "</loginCmsReturn></loginCmsResponse>")
        operacion = accion.rsplit("/", 1)[-1]
        self.llamadas.append(operacion)
        if operacion != "FEDummy":
            assert "<Token>TOKEN-DE-PRUEBA</Token><Sign>SIGN-DE-PRUEBA</Sign><Cuit>20123456786</Cuit>" in cuerpo
        n = lambda nombre: re.search(rf"<{nombre}>(.*?)</{nombre}>", cuerpo).group(1)  # noqa: E731
        if operacion == "FEDummy":
            r = "<AppServer>OK</AppServer><DbServer>OK</DbServer><AuthServer>OK</AuthServer>"
        elif operacion == "FECompUltimoAutorizado":
            clave = (int(n("PtoVta")), int(n("CbteTipo")))
            r = f"<PtoVta>{clave[0]}</PtoVta><CbteTipo>{clave[1]}</CbteTipo><CbteNro>{self.ultimo.get(clave, 0)}</CbteNro>"
        elif operacion == "FECompConsultar":
            dato = self.autorizados.get((int(n("PtoVta")), int(n("CbteTipo")), int(n("CbteNro"))))
            if dato is None:
                r = "<Errors><Err><Code>602</Code><Msg>No existen datos en nuestros registros</Msg></Err></Errors>"
            else:
                r = (f"<ResultGet><DocNro>{dato['doc']}</DocNro><CbteFch>{dato['fecha']}</CbteFch><ImpTotal>{dato['total']}</ImpTotal>"
                     f"<Resultado>A</Resultado><CodAutorizacion>{dato['cae']}</CodAutorizacion><EmisionTipo>CAE</EmisionTipo>"
                     f"<FchVto>{dato['vto']}</FchVto></ResultGet>")
        elif operacion == "FECAESolicitar":
            self.pedidos.append(cuerpo)
            if self.modo == "cortar_antes":
                raise ErrorConexion("No se pudo conectar con ARCA. Revisá la conexión a Internet.")
            punto, tipo, numero = int(n("PtoVta")), int(n("CbteTipo")), int(n("CbteDesde"))
            if self.modo == "rechazar" or numero != self.ultimo.get((punto, tipo), 0) + 1:
                r = ("<FeCabResp><Resultado>R</Resultado></FeCabResp><FeDetResp><FECAEDetResponse><Resultado>R</Resultado>"
                     "<CAE></CAE><CAEFchVto></CAEFchVto><Observaciones><Obs><Code>10015</Code>"
                     "<Msg>El campo DocNro es invalido</Msg></Obs></Observaciones></FECAEDetResponse></FeDetResp>")
            elif self.modo == "sin_cae":
                r = ("<FeCabResp><Resultado>A</Resultado></FeCabResp><FeDetResp><FECAEDetResponse><Resultado>A</Resultado>"
                     "<CAE></CAE><CAEFchVto></CAEFchVto></FECAEDetResponse></FeDetResp>")
            else:
                self.cae += 1
                vto = (datetime.now() + timedelta(days=10)).strftime("%Y%m%d")
                self.ultimo[(punto, tipo)] = numero
                self.autorizados[(punto, tipo, numero)] = {"cae": str(self.cae), "vto": vto, "total": n("ImpTotal"),
                                                           "fecha": n("CbteFch"), "doc": n("DocNro")}
                if self.modo == "cortar_despues":     # ARCA autorizó, pero la respuesta no llega
                    raise ErrorConexion("ARCA no respondió a tiempo.")
                r = (f"<FeCabResp><Resultado>A</Resultado></FeCabResp><FeDetResp><FECAEDetResponse><Resultado>A</Resultado>"
                     f"<CAE>{self.cae}</CAE><CAEFchVto>{vto}</CAEFchVto></FECAEDetResponse></FeDetResp>")
        return self._sobre(f'<{operacion}Response xmlns="{NS}"><{operacion}Result>{r}</{operacion}Result></{operacion}Response>')


@pytest.fixture
def fiscal(ctx, producto):
    """Comercio responsable inscripto, en producción, con certificado cargado y caja abierta."""
    ctx.config.guardar({
        "fiscal_razon_social": "Almacén Don Pepe SRL", "fiscal_cuit": CUIT, "fiscal_condicion_iva": "Responsable inscripto",
        "fiscal_domicilio": "San Martín 123, Rosario", "fiscal_punto_venta": "3", "fiscal_entorno": "produccion",
        "fiscal_habilitado": True,
    })
    pedido = credenciales.generar_pedido("produccion", CUIT, "Almacén Don Pepe SRL")
    credenciales.importar_certificado("produccion", emitir_certificado(pedido), CUIT)
    ctx.caja.abrir(0)
    simulado = ArcaSimulado()
    return ServicioArca(ctx, simulado), simulado


# ---- certificado ------------------------------------------------------------
def test_pedido_y_certificado(ctx, tmp_path):
    assert arca.cuit_valido(CUIT) and not arca.cuit_valido("20-12345678-5")
    pedido = credenciales.generar_pedido("homologacion", CUIT, "Mi Comercio")
    sujeto = x509.load_pem_x509_csr(pedido).subject.rfc4514_string()
    assert "CUIT 20123456786" in sujeto and "C=AR" in sujeto
    carpeta = credenciales.carpeta("homologacion")
    guardada = (carpeta / "clave_nueva.dpapi").read_bytes()
    assert b"PRIVATE KEY" not in guardada                     # la clave no queda en texto plano
    assert credenciales.estado("homologacion") == {"clave": False, "pedido_pendiente": True, "certificado": None}
    with pytest.raises(ErrorNegocio):
        credenciales.cargar("homologacion")

    otro = credenciales.generar_pedido("produccion", CUIT, "Mi Comercio")
    with pytest.raises(ErrorNegocio):                         # certificado de otra clave
        credenciales.importar_certificado("homologacion", emitir_certificado(otro), CUIT)
    with pytest.raises(ErrorNegocio):                         # certificado de otro CUIT
        credenciales.importar_certificado("homologacion", emitir_certificado(pedido, "30999999995"), CUIT)
    with pytest.raises(ErrorNegocio):
        credenciales.importar_certificado("homologacion", b"esto no es un certificado", CUIT)

    info = credenciales.importar_certificado("homologacion", emitir_certificado(pedido), CUIT)
    assert info["clave"] and not info["pedido_pendiente"] and not info["certificado"]["vencido"]
    certificado, clave = credenciales.cargar("homologacion")
    firmado = credenciales.firmar_cms(b"<loginTicketRequest/>", certificado, clave)
    assert b"<loginTicketRequest/>" in firmado and firmado[0] == 0x30

    # Un pedido nuevo no rompe el certificado que ya funciona.
    credenciales.generar_pedido("homologacion", CUIT, "Mi Comercio")
    assert credenciales.cargar("homologacion")


def test_ticket_de_acceso(ctx):
    pedido = wsaa.crear_pedido().decode()
    assert "<service>wsfe</service>" in pedido and "generationTime" in pedido and "expirationTime" in pedido
    falla = (b'<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"><soapenv:Body><soapenv:Fault>'
             b"<faultcode xmlns:ns1=\"http://xml.apache.org/axis/\">ns1:cms.cert.untrusted</faultcode>"
             b"<faultstring>Certificado no emitido por AC de confianza</faultstring></soapenv:Fault></soapenv:Body></soapenv:Envelope>")
    with pytest.raises(ErrorNegocio, match="no reconoce el certificado"):
        wsaa.interpretar(falla)

    credenciales.importar_certificado("homologacion", emitir_certificado(credenciales.generar_pedido("homologacion", CUIT, "X")), CUIT)
    simulado = ArcaSimulado()
    t1 = wsaa.obtener_ticket("homologacion", simulado)
    t2 = wsaa.obtener_ticket("homologacion", simulado)        # se reutiliza: ARCA no da otro mientras haya uno vigente
    assert (t1.token, t2.sign) == ("TOKEN-DE-PRUEBA", "SIGN-DE-PRUEBA") and simulado.llamadas == ["loginCms"]
    assert b"TOKEN" not in (credenciales.carpeta("homologacion") / "ticket.dpapi").read_bytes()


def test_orden_de_campos_del_pedido():
    detalle = Wsfe.armar_detalle({
        "tipo": 8, "punto_venta": 3, "numero": 7, "fecha": "20261009", "doc_tipo": 80, "doc_nro": "20123456786",
        "condicion_receptor": 1, "total_cent": 12100, "neto_cent": 10000, "iva_cent": 2100, "alicuotas": [[5, 10000, 2100]],
        "asociado": {"tipo": 6, "punto_venta": 3, "numero": 5, "cuit": "20123456786", "fecha": "20261001"},
    })
    sin_anidados = re.sub(r"<CbteAsoc>.*?</CbteAsoc>|<AlicIva>.*?</AlicIva>", "", detalle)
    campos = re.findall(r"<(\w+)>", sin_anidados.split("<FECAEDetRequest>")[1])
    principales = [c for c in campos if c in ORDEN_OFICIAL]
    assert principales == sorted(principales, key=ORDEN_OFICIAL.index)     # mismo orden que el WSDL de ARCA
    assert "<ImpTotal>121.00</ImpTotal>" in detalle and "<AlicIva><Id>5</Id><BaseImp>100.00</BaseImp><Importe>21.00</Importe>" in detalle


# ---- emisión ------------------------------------------------------------------
def test_factura_b_a_consumidor_final(fiscal, ctx, producto):
    servicio, simulado = fiscal
    assert servicio.estado().disponible
    venta = vender(ctx, producto, "2")                               # 34.571,42
    c = servicio.autorizar_venta(venta)
    assert (c["estado"], c["letra"], int(c["tipo"]), c["numero"], c["cae"]) == ("autorizada", "B", 6, 1, "75000000000001")
    assert c["neto_cent"] + c["iva_cent"] == c["total_cent"] == 3457142
    assert numero_completo(c) == "B 00003-00000001"
    pedido = simulado.pedidos[0]
    assert "<DocTipo>99</DocTipo><DocNro>0</DocNro>" in pedido and "<CondicionIVAReceptorId>5</CondicionIVAReceptorId>" in pedido
    assert "<ImpTotal>34571.42</ImpTotal>" in pedido and "<ImpNeto>28571.42</ImpNeto>" in pedido and "<ImpIVA>6000.00</ImpIVA>" in pedido
    assert ctx.ventas.obtener(venta)["estado_fiscal"] == "autorizada"

    assert servicio.autorizar_venta(venta)["id"] == c["id"]          # no se factura dos veces
    assert simulado.llamadas.count("FECAESolicitar") == 1
    assert servicio.autorizar_venta(vender(ctx, producto))["numero"] == 2

    html = impreso.html_comprobante(ctx, c["id"])
    assert "FACTURA B" in html and "75000000000001" in html and "IVA contenido: $ 6.000,00" in html
    assert "SIN VALIDEZ FISCAL" not in html and "NO VÁLIDO COMO FACTURA" not in html
    qr = json.loads(base64.b64decode(impreso.url_qr(c).split("?p=")[1]))
    assert qr == {"ver": 1, "fecha": f"{c['fecha'][:4]}-{c['fecha'][4:6]}-{c['fecha'][6:]}", "cuit": 20123456786, "ptoVta": 3,
                  "tipoCmp": 6, "nroCmp": 1, "importe": 34571.42, "moneda": "PES", "ctz": 1, "tipoDocRec": 99,
                  "nroDocRec": 0, "tipoCodAut": "E", "codAut": 75000000000001}
    with pytest.raises(ErrorNegocio, match="nota de"):               # con factura no se anula directo
        ctx.ventas.anular(venta, "error")


def test_factura_a_exige_cuit(fiscal, ctx, producto):
    servicio, simulado = fiscal
    cliente = ctx.clientes.guardar({"nombre": "Ferretería Norte", "condicion_iva": "Responsable inscripto",
                                    "tipo_documento": "DNI", "documento": "30111222"})
    p = ctx.productos.obtener(producto)
    registrar = lambda: ctx.ventas.registrar(  # noqa: E731
        __import__("uuid").uuid4().hex, [{"producto_id": producto, "cantidad": D(1), "precio_unit_cent": p["precio_final_cent"]}],
        [{"medio": "efectivo", "monto_cent": p["precio_final_cent"]}], cliente_id=cliente)
    venta = registrar()
    with pytest.raises(ErrorNegocio, match="CUIT válido"):
        servicio.autorizar_venta(venta)
    assert servicio.comprobantes(venta) == [] and simulado.pedidos == []
    ctx.clientes.guardar({"nombre": "Ferretería Norte", "condicion_iva": "Responsable inscripto",
                          "tipo_documento": "CUIT", "documento": "30-71234567-2"}, cliente)
    with pytest.raises(ErrorNegocio):                                # dígito verificador incorrecto
        servicio.autorizar_venta(venta)
    ctx.clientes.guardar({"nombre": "Ferretería Norte", "condicion_iva": "Responsable inscripto",
                          "tipo_documento": "CUIT", "documento": "20-12345678-6"}, cliente)
    c = servicio.autorizar_venta(venta)
    assert (c["letra"], int(c["tipo"])) == ("A", 1)
    assert "<DocTipo>80</DocTipo><DocNro>20123456786</DocNro>" in simulado.pedidos[0]
    assert "Importe neto gravado" in impreso.html_comprobante(ctx, c["id"])


def test_factura_c_de_monotributista(fiscal, ctx, producto):
    servicio, simulado = fiscal
    ctx.config.guardar({"fiscal_condicion_iva": "Monotributista"})
    c = servicio.autorizar_venta(vender(ctx, producto))
    assert (c["letra"], int(c["tipo"]), c["neto_cent"], c["iva_cent"]) == ("C", 11, 1728571, 0)
    assert "<Iva>" not in simulado.pedidos[0] and "<ImpNeto>17285.71</ImpNeto><ImpOpEx>0.00</ImpOpEx>" in simulado.pedidos[0]


def test_alicuota_que_no_es_de_iva(fiscal, ctx):
    servicio, _ = fiscal
    raro = ctx.productos.crear({"nombre": "Raro", "costo": D(100), "impuesto_pct": D("3.5"), "ganancia_pct": D(10), "stock": D(5)})
    with pytest.raises(ErrorNegocio, match="alícuota de IVA"):
        servicio.autorizar_venta(vender(ctx, raro))


def test_rechazo_de_arca(fiscal, ctx, producto):
    servicio, simulado = fiscal
    simulado.modo = "rechazar"
    venta = vender(ctx, producto)
    with pytest.raises(ErrorNegocio, match="DocNro es invalido"):
        servicio.autorizar_venta(venta)
    c = servicio.comprobantes(venta)[0]
    assert c["estado"] == "rechazada" and c["cae"] is None
    assert ctx.ventas.obtener(venta)["estado_fiscal"] == "sin_comprobante"
    with pytest.raises(ErrorNegocio):
        impreso.html_comprobante(ctx, c["id"])                       # sin CAE no hay factura
    simulado.modo = "aprobar"
    assert servicio.autorizar_venta(venta)["estado"] == "autorizada"  # corregido el problema, se puede reintentar


def test_nunca_se_inventa_un_cae(fiscal, ctx, producto):
    servicio, simulado = fiscal
    simulado.modo = "sin_cae"                                        # «aprobado» pero sin CAE: no vale
    venta = vender(ctx, producto)
    with pytest.raises(ErrorNegocio):
        servicio.autorizar_venta(venta)
    assert ctx.db.valor("SELECT COUNT(*) FROM comprobantes_fiscales WHERE estado = 'autorizada' OR cae IS NOT NULL") == 0


def test_corte_despues_de_enviar_no_duplica(fiscal, ctx, producto):
    servicio, simulado = fiscal
    simulado.modo = "cortar_despues"                                 # ARCA autoriza, pero no llega la respuesta
    venta = vender(ctx, producto)
    with pytest.raises(ErrorConexion, match="PENDIENTE"):
        servicio.autorizar_venta(venta)
    pendiente = servicio.comprobantes(venta)[0]
    assert pendiente["estado"] == "pendiente" and pendiente["numero"] == 1 and pendiente["cae"] is None
    assert ctx.ventas.obtener(venta)["estado_fiscal"] == "pendiente"
    with pytest.raises(ErrorNegocio):                                # ya se envió: no se puede descartar a ciegas
        servicio.descartar_pendiente(pendiente["id"])

    simulado.modo = "aprobar"
    assert servicio.reintentar_pendientes() == {"autorizados": 1, "fallidos": []}
    c = servicio.comprobantes(venta)[0]
    assert c["estado"] == "autorizada" and c["cae"] == "75000000000001" and c["numero"] == 1
    assert simulado.llamadas.count("FECAESolicitar") == 1            # se recuperó el CAE, no se pidió otro
    assert len(simulado.autorizados) == 1


def test_sin_conexion_queda_pendiente_y_se_puede_descartar(fiscal, ctx, producto):
    servicio, simulado = fiscal

    def sin_red(url, accion, cuerpo):
        raise ErrorConexion("No se pudo conectar con ARCA. Revisá la conexión a Internet.")

    venta = vender(ctx, producto)
    with pytest.raises(ErrorConexion):
        ServicioArca(ctx, sin_red).autorizar_venta(venta)
    pendiente = servicio.pendientes()[0]
    assert pendiente["numero"] is None
    assert ctx.db.valor("SELECT COUNT(*) FROM ventas") == 1          # la venta quedó guardada igual
    servicio.descartar_pendiente(pendiente["id"])
    assert ctx.ventas.obtener(venta)["estado_fiscal"] == "sin_comprobante"

    simulado.modo = "cortar_antes"
    with pytest.raises(ErrorConexion):
        servicio.autorizar_venta(venta)
    simulado.modo = "aprobar"
    assert servicio.reintentar_pendientes()["autorizados"] == 1
    assert len(simulado.autorizados) == 1


def test_nota_de_credito_anula_la_venta(fiscal, ctx, producto):
    servicio, simulado = fiscal
    venta = vender(ctx, producto, "2")
    factura = servicio.autorizar_venta(venta)
    with pytest.raises(ErrorNegocio):
        servicio.emitir_nota_credito(venta, "")
    nota = servicio.emitir_nota_credito(venta, "Devolución del cliente")
    assert (nota["clase"], int(nota["tipo"]), nota["estado"], nota["total_cent"]) == ("nota_credito", 8, "autorizada", 3457142)
    assert "<CbtesAsoc><CbteAsoc><Tipo>6</Tipo><PtoVta>3</PtoVta><Nro>1</Nro><Cuit>20123456786</Cuit>" in simulado.pedidos[1]
    v = ctx.ventas.obtener(venta)
    assert (v["estado"], v["estado_fiscal"]) == ("anulada", "nota_credito")
    assert ctx.productos.obtener(producto)["stock_mil"] == 10000
    assert servicio.emitir_nota_credito(venta, "otra vez")["id"] == nota["id"]   # no se emite dos veces
    assert simulado.llamadas.count("FECAESolicitar") == 2
    html = impreso.html_comprobante(ctx, nota["id"])
    assert "NOTA DE CRÉDITO B" in html and f"Anula: Factura {numero_completo(factura)}" in html
    fila = servicio.ventas("2000-01-01", "2999-01-01")[0]
    assert fila["situacion"] == "nota_credito"


def test_homologacion_es_solo_de_prueba(fiscal, ctx, producto):
    servicio, simulado = fiscal
    ctx.config.guardar({"fiscal_entorno": "homologacion"})
    assert not servicio.estado().disponible                          # cada entorno necesita su certificado
    credenciales.importar_certificado("homologacion", emitir_certificado(credenciales.generar_pedido("homologacion", CUIT, "X")), CUIT)
    assert "HOMOLOGACIÓN" in servicio.estado().mensaje
    venta = vender(ctx, producto)
    c = servicio.autorizar_venta(venta)
    assert c["entorno"] == "homologacion" and "SIN VALIDEZ FISCAL" in impreso.html_comprobante(ctx, c["id"])
    assert ctx.ventas.obtener(venta)["estado_fiscal"] == "sin_comprobante"   # una prueba no cuenta como factura real
    servicio.emitir_nota_credito(venta, "prueba")
    assert ctx.ventas.obtener(venta)["estado"] == "completada"       # ni anula la venta real
    ctx.config.guardar({"fiscal_entorno": "produccion"})
    assert servicio.ventas("2000-01-01", "2999-01-01")[0]["situacion"] == "sin_comprobante"


def test_desactivada_o_incompleta_no_factura(ctx, producto):
    servicio = ServicioArca(ctx, ArcaSimulado())
    ctx.caja.abrir(0)
    venta = vender(ctx, producto)
    assert not servicio.estado().disponible
    with pytest.raises(ErrorNegocio, match="desactivada"):
        servicio.autorizar_venta(venta)
    ctx.config.guardar({"fiscal_habilitado": True})
    assert "Faltan datos fiscales" in servicio.estado().mensaje
    assert "DOCUMENTO NO VÁLIDO COMO FACTURA" in __import__("micomercio.servicios.tickets", fromlist=["x"]).html_ticket(ctx, venta)


def test_prueba_de_conexion(fiscal):
    servicio, simulado = fiscal
    lineas = servicio.probar_conexion()
    assert "AppServer OK" in lineas[0] and "correcto" in lineas[1]
    assert any("Factura B: último número autorizado 0" in l for l in lineas)
    assert simulado.llamadas[0] == "FEDummy"


def test_migracion_desde_la_version_1(tmp_path):
    ruta = tmp_path / "vieja.db"
    conn = sqlite3.connect(ruta)
    conn.executescript(f"BEGIN;{MIGRACIONES[0]}PRAGMA user_version = 1;COMMIT;")
    conn.execute("INSERT INTO usuarios (usuario, nombre, rol, clave_hash, clave_sal, creado_en) VALUES ('a','A','admin','x','y','z')")
    conn.commit()
    conn.close()
    db = BaseDatos(ruta)
    assert db.valor("PRAGMA user_version") == 2 and db.valor("SELECT COUNT(*) FROM usuarios") == 1
    assert "cuit_emisor" in [c["name"] for c in db.consultar("PRAGMA table_info(comprobantes_fiscales)")]
    db.cerrar()


# ---- pantalla ---------------------------------------------------------------
def test_pantalla_de_facturacion(app, fiscal, ctx, producto, monkeypatch):
    from micomercio.ui.paginas import facturacion as modulo
    from micomercio.ui.ventana import VentanaPrincipal

    servicio, simulado = fiscal
    vender(ctx, producto)
    ventana = VentanaPrincipal(ctx)
    ventana.reloj_copias.stop()
    pagina = ventana.paginas["facturacion"]
    pagina.servicio.transporte = simulado
    ventana.ir("facturacion")
    assert pagina.tabla.rowCount() == 1 and pagina.tabla.item(0, 4).text() == "Sin comprobante fiscal"
    assert "producción" in pagina.estado.text() and "válido hasta" in pagina.estado_cert.text()

    mostrados = []
    monkeypatch.setattr(modulo, "confirmar", lambda *a, **k: True)
    monkeypatch.setattr(modulo, "mostrar_comprobante", lambda padre, ctx, html, titulo: mostrados.append((titulo, html)))
    pagina.tabla.selectRow(0)
    pagina.emitir()
    assert mostrados[0][0] == "Factura B 00000001" and "CAE N°" in mostrados[0][1]
    assert pagina.tabla.item(0, 4).text() == "Factura B 00003-00000001"
    pagina.tabla.selectRow(0)
    with pytest.raises(ErrorNegocio):                                # ya está facturada
        pagina.emitir()
    pagina.ver()
    assert len(mostrados) == 2 and simulado.llamadas.count("FECAESolicitar") == 1
    ventana.close()


def test_factura_automatica_al_vender(app, fiscal, ctx, producto, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from micomercio.ui.paginas import venta as modulo
    from micomercio.ui.ventana import VentanaPrincipal

    servicio, simulado = fiscal
    ctx.config.guardar({"fiscal_automatico": True})
    monkeypatch.setattr(modulo.arca, "crear_servicio", lambda c: ServicioArca(c, simulado))
    ventana = VentanaPrincipal(ctx)
    ventana.reloj_copias.stop()
    ventana.show()
    ventana.ir("venta")
    pagina = ventana.paginas["venta"]
    recibidos = []

    class Cobro:
        def __init__(self, padre, medio, total):
            self.pago, self.vuelto_cent = {"medio": medio, "monto_cent": total, "estado": "confirmado"}, 0

        def exec(self):
            return QDialog.Accepted

    class Registrada:
        def __init__(self, padre, ctx, venta_id, vuelto, pendiente, factura, error):
            recibidos.append((factura, error))

        def exec(self):
            return QDialog.Accepted

    monkeypatch.setattr(modulo, "DialogoCobro", Cobro)
    monkeypatch.setattr(modulo, "DialogoVentaRegistrada", Registrada)
    pagina.agregar(ctx.productos.obtener(producto))
    pagina.cobrar("efectivo")
    assert recibidos[0][0]["cae"] == "75000000000001" and recibidos[0][1] == ""

    simulado.modo = "cortar_antes"                                   # sin ARCA la venta se registra igual
    pagina.agregar(ctx.productos.obtener(producto))
    pagina.cobrar("efectivo")
    assert recibidos[1][0] is None and "PENDIENTE" in recibidos[1][1]
    assert ctx.db.valor("SELECT COUNT(*) FROM ventas") == 2 and len(servicio.pendientes()) == 1
    ventana.close()