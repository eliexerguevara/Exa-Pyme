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
        -- sin_comprobante | pendiente | autorizada | nota_credito  (lo maneja el módulo ARCA)
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

    -- Comprobantes de ARCA. Un CAE solo se guarda si vino en una respuesta real de sus servicios.
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
    # ---- versión 2: datos de los comprobantes de ARCA (etapa 7) ----------
    """
    ALTER TABLE comprobantes_fiscales ADD COLUMN clase TEXT NOT NULL DEFAULT 'factura';
    ALTER TABLE comprobantes_fiscales ADD COLUMN letra TEXT NOT NULL DEFAULT '';
    ALTER TABLE comprobantes_fiscales ADD COLUMN fecha TEXT NOT NULL DEFAULT '';
    ALTER TABLE comprobantes_fiscales ADD COLUMN doc_tipo INTEGER NOT NULL DEFAULT 99;
    ALTER TABLE comprobantes_fiscales ADD COLUMN doc_nro TEXT NOT NULL DEFAULT '0';
    ALTER TABLE comprobantes_fiscales ADD COLUMN condicion_receptor INTEGER NOT NULL DEFAULT 5;
    ALTER TABLE comprobantes_fiscales ADD COLUMN neto_cent INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE comprobantes_fiscales ADD COLUMN iva_cent INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE comprobantes_fiscales ADD COLUMN alicuotas TEXT NOT NULL DEFAULT '[]';
    ALTER TABLE comprobantes_fiscales ADD COLUMN cuit_emisor TEXT NOT NULL DEFAULT '';
    ALTER TABLE comprobantes_fiscales ADD COLUMN receptor TEXT NOT NULL DEFAULT '{}';
    ALTER TABLE comprobantes_fiscales ADD COLUMN emisor TEXT NOT NULL DEFAULT '{}';
    ALTER TABLE comprobantes_fiscales ADD COLUMN observaciones TEXT NOT NULL DEFAULT '';
    ALTER TABLE comprobantes_fiscales ADD COLUMN usuario_id INTEGER REFERENCES usuarios(id);
    -- Un mismo número de comprobante no puede quedar autorizado dos veces.
    CREATE UNIQUE INDEX ux_fiscal_numero
        ON comprobantes_fiscales(entorno, cuit_emisor, punto_venta, tipo, numero) WHERE estado = 'autorizada';
    """,
    # ---- versión 3: devoluciones parciales --------------------------------
    """
    CREATE TABLE devoluciones (
        id              INTEGER PRIMARY KEY,
        venta_id        INTEGER NOT NULL REFERENCES ventas(id),
        fecha           TEXT NOT NULL,
        caja_id         INTEGER REFERENCES cajas(id),
        usuario_id      INTEGER REFERENCES usuarios(id),
        motivo          TEXT NOT NULL,
        medio           TEXT NOT NULL,
        total_cent      INTEGER NOT NULL,
        neto_cent       INTEGER NOT NULL,
        impuestos_cent  INTEGER NOT NULL,
        costo_cent      INTEGER NOT NULL
    );
    CREATE INDEX ix_devoluciones_venta ON devoluciones(venta_id);
    CREATE INDEX ix_devoluciones_fecha ON devoluciones(fecha);

    CREATE TABLE devolucion_items (
        id              INTEGER PRIMARY KEY,
        devolucion_id   INTEGER NOT NULL REFERENCES devoluciones(id),
        venta_item_id   INTEGER NOT NULL REFERENCES venta_items(id),
        producto_id     INTEGER NOT NULL REFERENCES productos(id),
        cantidad_mil    INTEGER NOT NULL CHECK (cantidad_mil > 0),
        total_cent      INTEGER NOT NULL,
        neto_cent       INTEGER NOT NULL,
        impuesto_cent   INTEGER NOT NULL
    );
    CREATE INDEX ix_devolucion_items_item ON devolucion_items(venta_item_id);
    CREATE INDEX ix_devolucion_items_devolucion ON devolucion_items(devolucion_id);

    -- Notas de crédito parciales: guardan qué se devuelve hasta que la devolución queda registrada.
    ALTER TABLE comprobantes_fiscales ADD COLUMN parcial INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE comprobantes_fiscales ADD COLUMN devolucion_json TEXT;
    ALTER TABLE comprobantes_fiscales ADD COLUMN devolucion_id INTEGER REFERENCES devoluciones(id);
    """,
    # ---- versión 4: trabajo en red -----------------------------------------
    """
    -- Con varias cajas a la vez, dos personas no pueden facturar (ni anular con nota de crédito) la misma venta.
    CREATE UNIQUE INDEX ux_fiscal_vigente ON comprobantes_fiscales(venta_id, entorno, clase)
        WHERE parcial = 0 AND estado IN ('pendiente', 'autorizada');
    """,
    # ---- versión 5: una caja diaria por computadora --------------------------
    """
    -- «puesto» es el nombre de la computadora (caja) a la que pertenece cada jornada.
    ALTER TABLE cajas ADD COLUMN puesto TEXT NOT NULL DEFAULT 'Caja principal';
    DROP INDEX ux_caja_abierta;
    -- Cada computadora puede tener una sola caja abierta a la vez.
    CREATE UNIQUE INDEX ux_caja_abierta ON cajas(puesto COLLATE NOCASE) WHERE estado = 'abierta';
    """,
    # ---- versión 6: recuperación de la contraseña del administrador -----------
    """
    -- Del código de recuperación se guarda solo su huella, igual que con las contraseñas.
    ALTER TABLE usuarios ADD COLUMN recuperacion_hash TEXT;
    ALTER TABLE usuarios ADD COLUMN recuperacion_sal TEXT;
    """,
    # ---- versión 7: imágenes de productos ------------------------------------
    """
    -- Aparte de la tabla de productos, para que las consultas habituales no carguen las imágenes.
    CREATE TABLE producto_imagenes (
        producto_id INTEGER PRIMARY KEY REFERENCES productos(id),
        datos       BLOB NOT NULL,
        origen      TEXT NOT NULL,      -- 'catalogo' (por código de barras) o 'manual'
        actualizado TEXT NOT NULL
    );
    """,
    # ---- versión 8: miniaturas para las listas ---------------------------------
    """
    ALTER TABLE producto_imagenes ADD COLUMN miniatura BLOB;
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
            "La base de datos fue creada con una versión más nueva de Exa Pyme. "
            "Actualizá el programa para poder abrirla."
        )
    for version in range(actual + 1, VERSION_ESQUEMA + 1):
        db.conn.executescript(
            f"BEGIN;\n{MIGRACIONES[version - 1]}\nPRAGMA user_version = {version};\nCOMMIT;"
        )
