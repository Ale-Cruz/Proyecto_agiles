-- Solo almacenamiento temporal de códigos; no cambia tablas de la app web.
CREATE TABLE IF NOT EXISTS codigos_verificacion_movil (
    correo VARCHAR(254) NOT NULL,
    proposito VARCHAR(20) NOT NULL,
    codigo_hash CHAR(64) NOT NULL,
    expira_en DATETIME NOT NULL,
    enviado_en DATETIME NOT NULL,
    intentos INT UNSIGNED NOT NULL DEFAULT 0,
    PRIMARY KEY (correo, proposito),
    INDEX idx_codigo_expira (expira_en),
    CONSTRAINT chk_codigo_proposito CHECK (proposito IN ('registro','recuperacion'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
