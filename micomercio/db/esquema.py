"""Esquema de la base de datos y migraciones.

Cada elemento de MIGRACIONES lleva la base de la versión N-1 a la N. Para
cambiar el esquema se agrega una migración nueva al final; nunca se modifican
las anteriores, así las bases de los clientes se actualizan solas al abrir.

Convenciones: importes en centavos (*_cent), cantidades en milésimas (*_mil),
porcentajes como texto decimal, fechas como texto 'AAAA-MM-DD HH:MM:SS'.
"""
from __future__ import annotations

MIGRACIONES: list[str] = [
    # ---- versión 1 -------------------------------------------------------
    """
    CREATE TABLE usuarios (
        id          INTEGER PRIMARY KEY,
        usuario     TEXT NOT NULL UNIQUE COLLATE NOCASE,
        nombre      TEXT NOT NULL,
        rol         TEXT NOT NULL CHECK (rol IN ('admin', 'cajero')),
        clave_hash  TEXT NOT NULL,
        clave_sal   TEXT NOT NULL,
        activo      INTEGER NOT NULL DEFAULT 1,
        creado_en   TEXT NOT NULL
    );

    CREATE TABLE configuracion (
        clave TEXT PRIMARY KEY,
        valor TEXT NOT NULL
    );

    CREATE TABLE auditoria (
        id          INTEGER PRIMARY KEY,
        fecha       TEXT NOT NULL,
        usuario_id  INTEGER REFERENCES usuarios(id),
        accion      TEXT NOT NULL,
        entidad     TEXT,
        entidad_id  INTEGER,
        detalle     TEXT
    );
    CREATE INDEX ix_auditoria_fecha ON auditoria(fecha);

    CREATE TABLE categorias (
        id      INTEGER PRIMARY KEY,
        nombre  TEXT NOT NULL UNIQUE COLLATE NOCASE
    );

    CREATE TABLE proveedores (
        id          INTEGER PRIMARY KEY,
        nombre      TEXT NOT NULL,
        cuit        TEXT NOT NULL DEFAULT '',
        telefono    TEXT NOT NULL DEFAULT '',
        email       TEXT NOT NULL DEFAULT '',
        direccion   TEXT NOT NULL DEFAULT '',
        notas       TEXT NOT NULL DEFAULT '',
        activo      INTEGER NOT NULL DEFAULT 1,
        creado_en   TEXT NOT NULL
    );

    CREATE TABLE clientes (
        id              INTEGER PRIMARY KEY,
        nombre          TEXT NOT NULL,
        tipo_documento  TEXT NOT NULL DEFAULT 'DNI',
        documento       TEXT NOT NULL DEFAULT '',
        condicion_iva   TEXT NOT NULL DEFAULT 'Consumidor final',
        telefono        TEXT NOT NULL DEFAULT '',
        email           TEXT NOT NULL DEFAULT '',
        direccion       TEXT NOT NULL DEFAULT '',
        notas           TEXT NOT NULL DEFAULT '',
        activo          INTEGER NOT NULL DEFAULT 1,
        creado_en       TEXT NOT NULL
    );

    CREATE TABLE productos (
        id                  INTEGER PRIMARY KEY,
        codigo              TEXT NOT NULL UNIQUE COLLATE NOCASE,
        codigo_barras       TEXT NOT NULL DEFAULT '',
        nombre              TEXT NOT NULL,
        descripcion         TEXT NOT NULL DEFAULT '',
        categoria_id        INTEGER REFERENCES categorias(id),
        marca               TEXT NOT NULL DEFAULT '',
        proveedor_id        INTEGER REFERENCES proveedores(id),
        costo_cent          INTEGER NOT NULL DEFAULT 0 CHECK (costo_cent >= 0),
        impuesto_pct        TEXT NOT NULL DEFAULT '21',
        ganancia_pct        TEXT NOT NULL DEFAULT '0',
        metodo_precio       TEXT NOT NULL DEFAULT 'margen' CHECK (metodo_precio IN ('margen', 'recargo')),
        precio_neto_cent    INTEGER NOT NULL DEFAULT 0 CHECK (precio_neto_cent >= 0),
        precio_final_cent   INTEGER NOT NULL DEFAULT 0 CHECK (precio_final_cent >= 0),
        precio_manual       INTEGER NOT NULL DEFAULT 0,
        stock_mil           INTEGER NOT NULL DEFAULT 0,
        stock_minimo_mil    INTEGER NOT NULL DEFAULT 0,
        unidad              TEXT NOT NULL DEFAULT 'unidad',
        fecha_alta          TEXT NOT NULL,
        activo              INTEGER NOT NULL DEFAULT 1
    );
    CREATE UNIQUE INDEX ux_productos_barras ON productos(codigo_barras) WHERE codigo_barras <> '';
    CREATE INDEX ix_productos_nombre ON productos(nombre COLLATE NOCASE);

    CREATE TABLE historial_precios (
        id              INTEGER PRIMARY KEY,
        producto_id     INTEGER NOT NULL REFERENCES productos(id),
        fecha           TEXT NOT NULL,
        usuario_id      INTEGER REFERENCES usuarios(id),
        origen          TEXT NOT NULL,
        costo_ant_cent  INTEGER,
        costo_cent      INTEGER NOT NULL,
        impuesto_ant    TEXT,
        impuesto_pct    TEXT NOT NULL,
        ganancia_ant    TEXT,
        ganancia_pct    TEXT NOT NULL,
        final_ant_cent  INTEGER,
        final_cent      INTEGER NOT NULL
    );
    CREATE INDEX ix_historial_precios_producto ON historial_precios(producto_id, fecha);

    CREATE TABLE movimientos_stock (
        id                  INTEGER PRIMARY KEY,
        producto_id         INTEGER NOT NULL REFERENCES productos(id),
        fecha               TEXT NOT NULL,
        tipo                TEXT NOT NULL CHECK (tipo IN
                                ('inicial', 'venta', 'compra', 'entrada', 'salida', 'ajuste', 'devolucion', 'anulacion')),
        cantidad_mil        INTEGER NOT NULL,
        stock_resultante_mil INTEGER NOT NULL,
        motivo              TEXT NOT NULL DEFAULT '',
        ref_tipo            TEXT,
        ref_id              INTEGER,
        costo_cent          INTEGER,
        usuario_id          INTEGER REFERENCES usuarios(id)
    );
    CREATE INDEX ix_movstock_producto ON movimientos_stock(producto_id, fecha);
    CREATE INDEX ix_movstock_fecha ON movimientos_stock(fecha);

    CREATE TABLE cajas (
        id                      INTEGER PRIMARY KEY,
        abierta_en              TEXT NOT NULL,
        abierta_por             INTEGER REFERENCES usuarios(id),
        saldo_inicial_cent      INTEGER NOT NULL DEFAULT 0,
        cerrada_en              TEXT,
        cerrada_por             INTEGER REFERENCES usuarios(id),
        efectivo_esperado_cent  INTEGER,
        efectivo_contado_cent   INTEGER,
        diferencia_cent         INTEGER,
        notas                   TEXT NOT NULL DEFAULT '',
        estado                  TEXT NOT NULL DEFAULT 'abierta' CHECK (estado IN ('abierta', 'cerrada'))
    );
    -- Solo puede haber una caja abierta a la vez.
    CREATE UNIQUE INDEX ux_caja_abierta ON cajas(estado) WHERE estado = 'abierta';

    CREATE TABLE movimientos_caja (
        id          INTEGER PRIMARY KEY,
        caja_id     INTEGER NOT NULL REFERENCES cajas(id),
        fecha       TEXT NOT NULL,
        tipo        TEXT NOT NULL CHECK (tipo IN ('entrada', 'salida')),
        monto_cent  INTEGER NOT NULL CHECK (monto_cent > 0),
        motivo      TEXT NOT NULL,
        usuario_id  INTEGER REFERENCES usuarios(id)
    );

    CREATE TABLE ventas (
        id                  INTEGER PRIMARY KEY,
        uuid                TEXT NOT NULL UNIQUE,
        fecha               TEXT NOT NULL,
        caja_id             INTEGER REFERENCES cajas(id),
        cliente_id          INTEGER REFERENCES clientes(id),
        usuario_id          INTEGER REFERENCES usuarios(id),
        bruto_cent          INTEGER NOT NULL,
        descuento_cent      INTEGER NOT NULL DEFAULT 0,
        neto_cent           INTEGER NOT NULL,
        impuestos_cent      INTEGER NOT NULL,
        total_cent          INTEGER NOT NULL,
        estado              TEXT NOT NULL DEFAULT 'completada' CHECK (estado IN ('completada', 'anulada')),
        anulada_en          TEXT,
        anulada_por         INTEGER REFERENCES usuarios(id),
        motivo_anulacion    TEXT NOT NULL DEFAULT '',
        -- sin_comprobante | pendiente | autorizada | rechazada  (lo maneja el módulo ARCA)
        estado_fiscal       TEXT NOT NULL DEFAULT 'sin_comprobante',
        notas               TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX ix_ventas_fecha ON ventas(fecha);
    CREATE INDEX ix_ventas_caja ON ventas(caja_id);

    CREATE TABLE venta_items (
        id                  INTEGER PRIMARY KEY,
        venta_id            INTEGER NOT NULL REFERENCES ventas(id),
        producto_id         INTEGER NOT NULL REFERENCES productos(id),
        -- Copia de los datos del producto al momento de vender: las ventas
        -- históricas no cambian aunque después se edite el producto.
        codigo              TEXT NOT NULL,
        nombre              TEXT NOT NULL,
        unidad              TEXT NOT NULL,
        cantidad_mil        INTEGER NOT NULL CHECK (cantidad_mil > 0),
        precio_unit_cent    INTEGER NOT NULL,
        impuesto_pct        TEXT NOT NULL,
        costo_unit_cent     INTEGER NOT NULL,
        bruto_cent          INTEGER NOT NULL,
        descuento_cent      INTEGER NOT NULL DEFAULT 0,
        total_cent          INTEGER NOT NULL,
        neto_cent           INTEGER NOT NULL,
        impuesto_cent       INTEGER NOT NULL
    );
    CREATE INDEX ix_venta_items_venta ON venta_items(venta_id);
    CREATE INDEX ix_venta_items_producto ON venta_items(producto_id);

    CREATE TABLE pagos (
        id              INTEGER PRIMARY KEY,
        venta_id        INTEGER NOT NULL REFERENCES ventas(id),
        tipo            TEXT NOT NULL DEFAULT 'cobro' CHECK (tipo IN ('cobro', 'devolucion')),
        medio           TEXT NOT NULL CHECK (medio IN ('efectivo', 'tarjeta', 'transferencia', 'mercadopago')),
        monto_cent      INTEGER NOT NULL CHECK (monto_cent > 0),
        estado          TEXT NOT NULL CHECK (estado IN ('pendiente', 'confirmado', 'rechazado', 'cancelado')),
        comision_cent   INTEGER NOT NULL DEFAULT 0 CHECK (comision_cent >= 0),
        referencia      TEXT NOT NULL DEFAULT '',
        -- Identificador del cobro en el proveedor de pagos (lo completa el módulo Mercado Pago).
        id_externo      TEXT,
        creado_en       TEXT NOT NULL,
        confirmado_en   TEXT,
        -- Caja en la que el dinero ingresó (o salió) realmente. NULL mientras está pendiente.
        caja_id         INTEGER REFERENCES cajas(id),
        usuario_id      INTEGER REFERENCES usuarios(id)
    );
    CREATE INDEX ix_pagos_venta ON pagos(venta_id);
    CREATE INDEX ix_pagos_caja ON pagos(caja_id);
    CREATE UNIQUE INDEX ux_pagos_externo ON pagos(id_externo) WHERE id_externo IS NOT NULL;

    CREATE TABLE compras (
        id              INTEGER PRIMARY KEY,
        fecha           TEXT NOT NULL,
        proveedor_id    INTEGER REFERENCES proveedores(id),
        comprobante     TEXT NOT NULL DEFAULT '',
        total_cent      INTEGER NOT NULL,
        notas           TEXT NOT NULL DEFAULT '',
        usuario_id      INTEGER REFERENCES usuarios(id)
    );
    CREATE INDEX ix_compras_fecha ON compras(fecha);

    CREATE TABLE compra_items (
        id                  INTEGER PRIMARY KEY,
        compra_id           INTEGER NOT NULL REFERENCES compras(id),
        producto_id         INTEGER NOT NULL REFERENCES productos(id),
        cantidad_mil        INTEGER NOT NULL CHECK (cantidad_mil > 0),
        costo_unit_cent     INTEGER NOT NULL CHECK (costo_unit_cent >= 0),
        subtotal_cent       INTEGER NOT NULL
    );
    CREATE INDEX ix_compra_items_compra ON compra_items(compra_id);

    -- Preparada para la etapa 7 (ARCA). El MVP no escribe en esta tabla:
    -- un CAE solo puede venir de una respuesta real de los servicios de ARCA.
    CREATE TABLE comprobantes_fiscales (
        id                  INTEGER PRIMARY KEY,
        venta_id            INTEGER NOT NULL REFERENCES ventas(id),
        comprobante_asociado_id INTEGER REFERENCES comprobantes_fiscales(id),
        entorno             TEXT NOT NULL CHECK (entorno IN ('homologacion', 'produccion')),
        tipo                TEXT NOT NULL,
        punto_venta         INTEGER NOT NULL,
        numero              INTEGER,
        estado              TEXT NOT NULL CHECK (estado IN ('pendiente', 'autorizada', 'rechazada')),
        cae                 TEXT,
        cae_vencimiento     TEXT,
        total_cent          INTEGER NOT NULL,
        solicitado_en       TEXT NOT NULL,
        autorizado_en       TEXT,
        respuesta           TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX ix_fiscales_venta ON comprobantes_fiscales(venta_id);
    """,
]

VERSION_ESQUEMA = len(MIGRACIONES)

TABLAS_REQUERIDAS = {
    "usuarios", "configuracion", "auditoria", "categorias", "proveedores", "clientes",
    "productos", "historial_precios", "movimientos_stock", "cajas", "movimientos_caja",
    "ventas", "venta_items", "pagos", "compras", "compra_items", "comprobantes_fiscales",
}


def migrar(db) -> None:
    actual = db.conn.execute("PRAGMA user_version").fetchone()[0]
    if actual > VERSION_ESQUEMA:
        from ..core.errores import ErrorNegocio

        raise ErrorNegocio(
            "La base de datos fue creada con una versión más nueva de MiComercio. "
            "Actualizá el programa para poder abrirla."
        )
    for version in range(actual + 1, VERSION_ESQUEMA + 1):
        db.conn.executescript(
            f"BEGIN;\n{MIGRACIONES[version - 1]}\nPRAGMA user_version = {version};\nCOMMIT;"
        )
