"""Integraciones externas (ARCA y Mercado Pago).

Cada integración es un módulo independiente que la aplicación consulta a través
de una interfaz pequeña. En el MVP ninguna está habilitada: `disponible()`
devuelve False y la aplicación funciona completa sin ellas.
"""
