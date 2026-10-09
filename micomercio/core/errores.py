class ErrorNegocio(Exception):
    """Error esperable, con un mensaje en español pensado para mostrar al usuario."""


class PermisoDenegado(ErrorNegocio):
    pass
