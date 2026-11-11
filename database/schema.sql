-- Estructura sin datos. Importar en una base MySQL vacia antes de manage.py migrate.
-- Las tablas internas administradas por Django las crean sus migraciones.
SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS=0;

CREATE TABLE `aperturas_caja` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `abierta_por` int unsigned NOT NULL,
  `abierta_en` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `monto_inicial` decimal(12,2) NOT NULL DEFAULT '0.00',
  `estado` enum('abierta','cerrada') COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'abierta',
  `cerrada_por` int unsigned DEFAULT NULL,
  `cerrada_en` datetime DEFAULT NULL,
  `efectivo_esperado` decimal(12,2) DEFAULT NULL,
  `efectivo_contado` decimal(12,2) DEFAULT NULL,
  `observaciones` text COLLATE utf8mb4_unicode_ci NOT NULL,
  `activa_unica` int unsigned GENERATED ALWAYS AS ((case when (`estado` = _utf8mb4'abierta') then 1 else NULL end)) STORED,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_apertura_unica` (`activa_unica`),
  KEY `fk_caja_abierta_por` (`abierta_por`),
  KEY `fk_caja_cerrada_por` (`cerrada_por`),
  CONSTRAINT `fk_caja_abierta_por` FOREIGN KEY (`abierta_por`) REFERENCES `usuarios` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `fk_caja_cerrada_por` FOREIGN KEY (`cerrada_por`) REFERENCES `usuarios` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `chk_caja_efectivo_contado` CHECK ((`efectivo_contado` >= 0)),
  CONSTRAINT `chk_caja_monto_inicial` CHECK ((`monto_inicial` >= 0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `auditoria` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `usuario_id` int unsigned DEFAULT NULL COMMENT 'NULL para una accion automatica',
  `accion` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `modulo` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'General',
  `entidad_afectada` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `registro_afectado_id` int NOT NULL,
  `descripcion` text COLLATE utf8mb4_unicode_ci NOT NULL,
  `valor_anterior` json DEFAULT NULL,
  `valor_nuevo` json DEFAULT NULL,
  `creado_en` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `fk_auditoria_usuario` (`usuario_id`),
  KEY `idx_auditoria_fecha` (`creado_en` DESC,`id` DESC),
  KEY `idx_auditoria_modulo` (`modulo`,`creado_en` DESC),
  KEY `idx_auditoria_accion` (`accion`,`creado_en` DESC),
  CONSTRAINT `fk_auditoria_usuario` FOREIGN KEY (`usuario_id`) REFERENCES `usuarios` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `carritos` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `usuario_id` int unsigned NOT NULL,
  `ultima_actividad` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `expira_en` datetime NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_carritos_usuario` (`usuario_id`),
  CONSTRAINT `fk_carritos_usuario` FOREIGN KEY (`usuario_id`) REFERENCES `usuarios` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `categorias` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `nombre` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `activo` tinyint(1) NOT NULL DEFAULT '1',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_categorias_nombre` (`nombre`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `codigos_verificacion_movil` (
  `correo` varchar(254) COLLATE utf8mb4_unicode_ci NOT NULL,
  `proposito` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `codigo_hash` char(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `expira_en` datetime NOT NULL,
  `enviado_en` datetime NOT NULL,
  `intentos` int unsigned NOT NULL DEFAULT '0',
  PRIMARY KEY (`correo`,`proposito`),
  KEY `idx_codigo_expira` (`expira_en`),
  CONSTRAINT `chk_codigo_proposito` CHECK ((`proposito` in (_utf8mb4'registro',_utf8mb4'recuperacion')))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `configuracion` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `minutos_carrito` int NOT NULL DEFAULT '10',
  `horarios_habilitados` tinyint(1) NOT NULL DEFAULT '0',
  PRIMARY KEY (`id`),
  CONSTRAINT `chk_config_minutos_carrito` CHECK ((`minutos_carrito` > 0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `detalles_carrito` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `carrito_id` int unsigned NOT NULL,
  `producto_id` int unsigned NOT NULL,
  `cantidad` int NOT NULL,
  PRIMARY KEY (`id`),
  KEY `fk_detalles_carrito_carrito` (`carrito_id`),
  KEY `fk_detalles_carrito_producto` (`producto_id`),
  CONSTRAINT `fk_detalles_carrito_carrito` FOREIGN KEY (`carrito_id`) REFERENCES `carritos` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `fk_detalles_carrito_producto` FOREIGN KEY (`producto_id`) REFERENCES `productos` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `chk_detalles_carrito_cantidad` CHECK ((`cantidad` > 0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `detalles_pedido` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `pedido_id` int unsigned NOT NULL,
  `producto_id` int unsigned NOT NULL,
  `cantidad` int NOT NULL,
  `precio_unitario` decimal(12,2) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `fk_detalles_pedido_pedido` (`pedido_id`),
  KEY `fk_detalles_pedido_producto` (`producto_id`),
  CONSTRAINT `fk_detalles_pedido_pedido` FOREIGN KEY (`pedido_id`) REFERENCES `pedidos` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `fk_detalles_pedido_producto` FOREIGN KEY (`producto_id`) REFERENCES `productos` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `chk_detalles_pedido_cantidad` CHECK ((`cantidad` > 0)),
  CONSTRAINT `chk_detalles_pedido_precio` CHECK ((`precio_unitario` >= 0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `detalles_venta` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `venta_id` int unsigned NOT NULL,
  `producto_id` int unsigned NOT NULL,
  `cantidad` int NOT NULL,
  `precio_unitario` decimal(12,2) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `fk_detalles_venta_venta` (`venta_id`),
  KEY `fk_detalles_venta_producto` (`producto_id`),
  CONSTRAINT `fk_detalles_venta_producto` FOREIGN KEY (`producto_id`) REFERENCES `productos` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `fk_detalles_venta_venta` FOREIGN KEY (`venta_id`) REFERENCES `ventas` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `chk_detalles_venta_cantidad` CHECK ((`cantidad` > 0)),
  CONSTRAINT `chk_detalles_venta_precio` CHECK ((`precio_unitario` >= 0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `horarios_pedidos` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `configuracion_id` int unsigned NOT NULL,
  `dia_semana` int NOT NULL COMMENT '1=lunes, 2=martes, ... 7=domingo',
  `hora_inicio` time NOT NULL,
  `hora_fin` time NOT NULL,
  `activo` tinyint(1) NOT NULL DEFAULT '1',
  PRIMARY KEY (`id`),
  KEY `fk_horarios_configuracion` (`configuracion_id`),
  CONSTRAINT `fk_horarios_configuracion` FOREIGN KEY (`configuracion_id`) REFERENCES `configuracion` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `chk_horarios_dia` CHECK ((`dia_semana` between 1 and 7))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `movimientos_caja` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `caja_id` int unsigned NOT NULL,
  `usuario_id` int unsigned NOT NULL,
  `venta_id` int unsigned DEFAULT NULL,
  `tipo` enum('ingreso_venta','ingreso_adicional','retiro','devolucion') COLLATE utf8mb4_unicode_ci NOT NULL,
  `monto` decimal(12,2) NOT NULL,
  `motivo` text COLLATE utf8mb4_unicode_ci NOT NULL,
  `creado_en` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `fk_mov_caja_caja` (`caja_id`),
  KEY `fk_mov_caja_usuario` (`usuario_id`),
  KEY `fk_mov_caja_venta` (`venta_id`),
  CONSTRAINT `fk_mov_caja_caja` FOREIGN KEY (`caja_id`) REFERENCES `aperturas_caja` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `fk_mov_caja_usuario` FOREIGN KEY (`usuario_id`) REFERENCES `usuarios` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `fk_mov_caja_venta` FOREIGN KEY (`venta_id`) REFERENCES `ventas` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `chk_mov_caja_monto` CHECK ((`monto` > 0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `movimientos_inventario` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `producto_id` int unsigned NOT NULL,
  `usuario_id` int unsigned NOT NULL,
  `detalle_venta_id` int unsigned DEFAULT NULL,
  `tipo` enum('entrada','salida_venta','salida_manual','ajuste_entrada','ajuste_salida','reversion_venta') COLLATE utf8mb4_unicode_ci NOT NULL,
  `cantidad` int NOT NULL,
  `motivo` text COLLATE utf8mb4_unicode_ci NOT NULL,
  `creado_en` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `operacion_id` char(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_inventario_operacion` (`operacion_id`),
  KEY `fk_mov_inventario_producto` (`producto_id`),
  KEY `fk_mov_inventario_usuario` (`usuario_id`),
  KEY `fk_mov_inventario_detalle_venta` (`detalle_venta_id`),
  CONSTRAINT `fk_mov_inventario_detalle_venta` FOREIGN KEY (`detalle_venta_id`) REFERENCES `detalles_venta` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `fk_mov_inventario_producto` FOREIGN KEY (`producto_id`) REFERENCES `productos` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `fk_mov_inventario_usuario` FOREIGN KEY (`usuario_id`) REFERENCES `usuarios` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `chk_mov_inventario_cantidad` CHECK ((`cantidad` > 0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `pedidos` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `numero` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `estudiante_id` int unsigned NOT NULL,
  `estado` enum('pendiente','en_preparacion','listo','entregado','cancelado') COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'pendiente',
  `creado_en` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `estado_actualizado_en` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `total` decimal(12,2) NOT NULL DEFAULT '0.00',
  `anulado_por` int unsigned DEFAULT NULL,
  `anulado_en` datetime DEFAULT NULL,
  `motivo_anulacion` text COLLATE utf8mb4_unicode_ci,
  `estudiante_activo_id` int unsigned GENERATED ALWAYS AS ((case when (`estado` in (_utf8mb4'pendiente',_utf8mb4'en_preparacion',_utf8mb4'listo')) then `estudiante_id` else NULL end)) STORED,
  `operacion_id` char(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_pedidos_numero` (`numero`),
  UNIQUE KEY `uk_pedidos_estudiante_activo` (`estudiante_activo_id`),
  UNIQUE KEY `uq_pedidos_operacion_id` (`operacion_id`),
  KEY `fk_pedidos_estudiante` (`estudiante_id`),
  KEY `fk_pedidos_anulado_por` (`anulado_por`),
  CONSTRAINT `fk_pedidos_anulado_por` FOREIGN KEY (`anulado_por`) REFERENCES `usuarios` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `fk_pedidos_estudiante` FOREIGN KEY (`estudiante_id`) REFERENCES `usuarios` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `chk_pedidos_total` CHECK ((`total` >= 0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `productos` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `categoria_id` int unsigned NOT NULL,
  `codigo` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `nombre` varchar(150) COLLATE utf8mb4_unicode_ci NOT NULL,
  `descripcion` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `precio` decimal(12,2) NOT NULL,
  `fotografia` varchar(2048) COLLATE utf8mb4_unicode_ci NOT NULL,
  `stock` int NOT NULL DEFAULT '0',
  `stock_minimo` int NOT NULL DEFAULT '0',
  `disponible_para_venta` tinyint(1) NOT NULL DEFAULT '1',
  `activo` tinyint(1) NOT NULL DEFAULT '1',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_productos_codigo` (`codigo`),
  KEY `fk_productos_categoria` (`categoria_id`),
  CONSTRAINT `fk_productos_categoria` FOREIGN KEY (`categoria_id`) REFERENCES `categorias` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `chk_productos_precio` CHECK ((`precio` >= 0)),
  CONSTRAINT `chk_productos_stock` CHECK ((`stock` >= 0)),
  CONSTRAINT `chk_productos_stock_minimo` CHECK ((`stock_minimo` >= 0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `sesiones_movil` (
  `token_hash` char(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `usuario_id` int unsigned NOT NULL,
  `creado_en` datetime NOT NULL,
  `expira_en` datetime DEFAULT NULL,
  PRIMARY KEY (`token_hash`),
  KEY `idx_sesion_usuario` (`usuario_id`),
  CONSTRAINT `fk_sesion_movil_usuario` FOREIGN KEY (`usuario_id`) REFERENCES `usuarios` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `usuarios` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `nombre` varchar(150) COLLATE utf8mb4_unicode_ci NOT NULL,
  `correo` varchar(254) COLLATE utf8mb4_unicode_ci NOT NULL,
  `password_hash` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `rol` enum('administrador','cajero','estudiante') COLLATE utf8mb4_unicode_ci NOT NULL,
  `habilitado` tinyint(1) NOT NULL DEFAULT '1',
  `token_sesion_hash` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `sesion_expira_en` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_usuarios_correo` (`correo`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `ventas` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `numero` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `pedido_id` int unsigned DEFAULT NULL COMMENT 'NULL para una venta presencial',
  `caja_id` int unsigned NOT NULL,
  `cajero_id` int unsigned NOT NULL,
  `creada_en` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `total` decimal(12,2) NOT NULL DEFAULT '0.00',
  `efectivo_recibido` decimal(12,2) NOT NULL,
  `estado` enum('completada','anulada') COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'completada',
  `anulado_por` int unsigned DEFAULT NULL,
  `anulado_en` datetime DEFAULT NULL,
  `motivo_anulacion` text COLLATE utf8mb4_unicode_ci,
  `operacion_id` char(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_ventas_numero` (`numero`),
  UNIQUE KEY `uk_ventas_pedido` (`pedido_id`),
  UNIQUE KEY `uk_venta_operacion` (`operacion_id`),
  KEY `fk_ventas_caja` (`caja_id`),
  KEY `fk_ventas_cajero` (`cajero_id`),
  KEY `fk_ventas_anulado_por` (`anulado_por`),
  CONSTRAINT `fk_ventas_anulado_por` FOREIGN KEY (`anulado_por`) REFERENCES `usuarios` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `fk_ventas_caja` FOREIGN KEY (`caja_id`) REFERENCES `aperturas_caja` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `fk_ventas_cajero` FOREIGN KEY (`cajero_id`) REFERENCES `usuarios` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `fk_ventas_pedido` FOREIGN KEY (`pedido_id`) REFERENCES `pedidos` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `chk_ventas_efectivo` CHECK ((`efectivo_recibido` >= 0)),
  CONSTRAINT `chk_ventas_total` CHECK ((`total` >= 0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

SET FOREIGN_KEY_CHECKS=1;
