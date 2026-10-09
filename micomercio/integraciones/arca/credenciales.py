"""Clave privada, pedido de certificado y certificado de ARCA.

Dónde se guarda cada cosa (carpeta %LOCALAPPDATA%\\MiComercio\\arca\\<entorno>):
    clave.dpapi          clave privada en uso, cifrada para el usuario de Windows (DPAPI)
    clave_nueva.dpapi    clave recién generada, a la espera de su certificado
    certificado.crt      certificado emitido por ARCA (no es secreto)
    ticket.dpapi         ticket de acceso vigente (token y sign), también cifrado

La clave privada nunca se guarda sin cifrar, no entra en la base de datos ni en
las copias de seguridad, y solo puede descifrarla el mismo usuario de Windows
en la misma computadora. Si se cambia de computadora hay que generar un
certificado nuevo, que es lo que corresponde.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs7
from cryptography.x509.oid import NameOID

from ...core.errores import ErrorNegocio
from ...proteccion import desproteger, proteger  # noqa: F401
from ...rutas import carpeta_datos
from . import cuit_valido, solo_digitos


# ---- archivos ----------------------------------------------------------------
def carpeta(entorno: str) -> Path:
    ruta = carpeta_datos() / "arca" / entorno
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


def _clave_pem(clave) -> bytes:
    return clave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


def _leer_clave(ruta: Path):
    if not ruta.exists():
        return None
    return serialization.load_pem_private_key(desproteger(ruta.read_bytes()), password=None)


def _misma_clave(clave, certificado) -> bool:
    return clave is not None and clave.public_key().public_numbers() == certificado.public_key().public_numbers()


# ---- pedido de certificado -------------------------------------------------
def generar_pedido(entorno: str, cuit: str, razon_social: str, alias: str = "micomercio") -> bytes:
    """Crea una clave privada nueva y devuelve el pedido de certificado (CSR) para subir a ARCA.

    La clave en uso no se toca: la nueva queda aparte hasta que se importe su certificado.
    """
    if not cuit_valido(cuit):
        raise ErrorNegocio("Antes de generar el pedido, cargá un CUIT válido en los datos fiscales.")
    if not razon_social.strip():
        raise ErrorNegocio("Antes de generar el pedido, cargá la razón social en los datos fiscales.")
    clave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    sujeto = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "AR"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, razon_social.strip()[:64]),
        x509.NameAttribute(NameOID.COMMON_NAME, alias),
        x509.NameAttribute(NameOID.SERIAL_NUMBER, f"CUIT {solo_digitos(cuit)}"),
    ])
    pedido = x509.CertificateSigningRequestBuilder().subject_name(sujeto).sign(clave, hashes.SHA256())
    (carpeta(entorno) / "clave_nueva.dpapi").write_bytes(proteger(_clave_pem(clave)))
    return pedido.public_bytes(serialization.Encoding.PEM)


def importar_clave(entorno: str, contenido: bytes) -> None:
    """Para quien ya tiene una clave privada (.key) generada con otra herramienta."""
    try:
        clave = serialization.load_pem_private_key(contenido, password=None)
    except TypeError:
        raise ErrorNegocio("La clave privada está protegida con contraseña. Exportala sin contraseña para importarla.") from None
    except ValueError:
        raise ErrorNegocio("El archivo elegido no es una clave privada válida (se espera un archivo .key en formato PEM).") from None
    (carpeta(entorno) / "clave_nueva.dpapi").write_bytes(proteger(_clave_pem(clave)))


def _cargar_certificado(contenido: bytes):
    try:
        if b"-----BEGIN" in contenido:
            return x509.load_pem_x509_certificate(contenido.strip())
        return x509.load_der_x509_certificate(contenido)
    except ValueError:
        raise ErrorNegocio("El archivo elegido no es un certificado válido (se espera el .crt que entrega ARCA).") from None


def _cuit_del_certificado(certificado) -> str:
    for atributo in certificado.subject.get_attributes_for_oid(NameOID.SERIAL_NUMBER):
        return solo_digitos(str(atributo.value))
    return ""


def importar_certificado(entorno: str, contenido: bytes, cuit: str) -> dict:
    """Guarda el certificado emitido por ARCA si corresponde a una clave privada de esta computadora."""
    certificado = _cargar_certificado(contenido)
    base = carpeta(entorno)
    nueva, actual = _leer_clave(base / "clave_nueva.dpapi"), _leer_clave(base / "clave.dpapi")
    if _misma_clave(nueva, certificado):
        (base / "clave.dpapi").write_bytes((base / "clave_nueva.dpapi").read_bytes())
        (base / "clave_nueva.dpapi").unlink()
    elif not _misma_clave(actual, certificado):
        raise ErrorNegocio(
            "Este certificado no corresponde a la clave privada de esta computadora. Tiene que ser el certificado "
            "que ARCA emitió a partir del pedido generado acá."
        )
    cuit_cert = _cuit_del_certificado(certificado)
    if cuit_cert and solo_digitos(cuit) and cuit_cert != solo_digitos(cuit):
        raise ErrorNegocio("El certificado pertenece a otro CUIT, distinto del cargado en los datos fiscales.")
    (base / "certificado.crt").write_bytes(certificado.public_bytes(serialization.Encoding.PEM))
    (base / "ticket.dpapi").unlink(missing_ok=True)
    return estado(entorno)


def estado(entorno: str) -> dict:
    base = carpeta(entorno)
    info = {"clave": (base / "clave.dpapi").exists(), "pedido_pendiente": (base / "clave_nueva.dpapi").exists(),
            "certificado": None}
    ruta = base / "certificado.crt"
    if ruta.exists():
        try:
            c = _cargar_certificado(ruta.read_bytes())
            hasta = c.not_valid_after_utc
            info["certificado"] = {
                "sujeto": c.subject.rfc4514_string(), "cuit": _cuit_del_certificado(c),
                "desde": c.not_valid_before_utc.astimezone().strftime("%d/%m/%Y"),
                "hasta": hasta.astimezone().strftime("%d/%m/%Y"),
                "vencido": hasta < datetime.now(timezone.utc),
                "dias_restantes": (hasta - datetime.now(timezone.utc)).days,
            }
        except ErrorNegocio:
            pass
    return info


def cargar(entorno: str):
    """Devuelve (certificado, clave privada) listos para firmar."""
    base = carpeta(entorno)
    if not (base / "certificado.crt").exists() or not (base / "clave.dpapi").exists():
        raise ErrorNegocio("Falta el certificado de ARCA. Cargalo en Facturación → Certificado.")
    certificado = _cargar_certificado((base / "certificado.crt").read_bytes())
    if certificado.not_valid_after_utc < datetime.now(timezone.utc):
        raise ErrorNegocio("El certificado de ARCA está vencido. Generá uno nuevo en Facturación → Certificado.")
    clave = _leer_clave(base / "clave.dpapi")
    if not _misma_clave(clave, certificado):
        raise ErrorNegocio("El certificado no coincide con la clave privada guardada. Volvé a importarlo.")
    return certificado, clave


def firmar_cms(datos: bytes, certificado, clave) -> bytes:
    """Firma en formato CMS (PKCS#7) con el contenido incluido, como exige WSAA."""
    return (pkcs7.PKCS7SignatureBuilder().set_data(datos).add_signer(certificado, clave, hashes.SHA256())
            .sign(serialization.Encoding.DER, [pkcs7.PKCS7Options.Binary]))
