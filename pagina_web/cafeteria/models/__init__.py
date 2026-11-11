"""Expone los modelos para que Django los descubra al iniciar la aplicacion."""

from .models import (
    Auditoria,
    Caja,
    Carritos,
    Categorias,
    Configuracion,
    DetallesCarrito,
    DetallesPedido,
    DetallesVenta,
    HorariosPedidos,
    MovimientosCaja,
    MovimientosInventario,
    Pedidos,
    Productos,
    Usuarios,
    Ventas,
)

from .acceso import IntentosAcceso

__all__ = [
    "IntentosAcceso",
    "Auditoria",
    "Caja",
    "Carritos",
    "Categorias",
    "Configuracion",
    "DetallesCarrito",
    "DetallesPedido",
    "DetallesVenta",
    "HorariosPedidos",
    "MovimientosCaja",
    "MovimientosInventario",
    "Pedidos",
    "Productos",
    "Usuarios",
    "Ventas",
]
