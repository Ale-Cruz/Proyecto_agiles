-- Referencia para el esquema compartido sistema_pedidos.
-- Ya aplicado localmente mediante la migración Django 0006.
-- En otra instalación usar Django migrate, o ejecutar este SQL una sola vez.
CREATE TABLE IF NOT EXISTS sesiones_movil (
    token_hash CHAR(64) NOT NULL PRIMARY KEY,
    usuario_id INT UNSIGNED NOT NULL,
    creado_en DATETIME NOT NULL,
    expira_en DATETIME NULL,
    INDEX idx_sesion_usuario (usuario_id),
    CONSTRAINT fk_sesion_movil_usuario FOREIGN KEY (usuario_id)
        REFERENCES usuarios(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO sesiones_movil (token_hash,usuario_id,creado_en,expira_en)
SELECT token_sesion_hash,id,UTC_TIMESTAMP(),sesion_expira_en
FROM usuarios WHERE rol='estudiante' AND CHAR_LENGTH(token_sesion_hash)=64;

UPDATE usuarios SET token_sesion_hash=NULL,sesion_expira_en=NULL
WHERE rol='estudiante';
