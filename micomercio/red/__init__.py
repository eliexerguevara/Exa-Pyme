"""Trabajo en red: una computadora es el servidor (tiene los datos) y las demás son clientes.

    codec     cómo viajan los datos (JSON con importes exactos)
    servidor  atiende los pedidos de los clientes y aplica los permisos de cada usuario
    cliente   lo que usa la interfaz en una computadora cliente, en lugar de la base local

La comunicación va cifrada (TLS). Toda regla de negocio y todo permiso se comprueba en el
servidor: un cliente solo puede pedir operaciones, nunca tocar la base directamente.
"""
