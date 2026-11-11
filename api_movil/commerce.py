from datetime import timedelta, timezone, datetime
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urlsplit

from fastapi import HTTPException
from sqlalchemy import delete, func
from sqlmodel import select

from models import (Carrito, Categoria, Configuracion, DetalleCarrito, DetallePedido,
                    Horario, Pedido, Producto, utcnow)
import settings

ACTIVE_STATES = ('en_preparacion', 'listo')
CENT = Decimal('0.01')


def money(value):
    return format(Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP), '.2f')


def totals(total):
    total = Decimal(money(total))
    subtotal = (total / Decimal('1.13')).quantize(CENT, rounding=ROUND_HALF_UP)
    return {'subtotal': money(subtotal), 'iva': money(total - subtotal), 'total': money(total)}


def iso(value):
    return value.isoformat(timespec='seconds') + 'Z' if value else None


def committed_quantities(session, product_ids, *, exclude_cart_id=None):
    if not product_ids:
        return {}
    rows = session.exec(select(DetallePedido.producto_id, func.sum(DetallePedido.cantidad))
                        .join(Pedido, Pedido.id == DetallePedido.pedido_id)
                        .where(Pedido.estado.in_(ACTIVE_STATES), DetallePedido.producto_id.in_(product_ids))
                        .group_by(DetallePedido.producto_id)).all()
    result = {product_id: int(quantity) for product_id, quantity in rows}
    carts = (select(DetalleCarrito.producto_id, func.sum(DetalleCarrito.cantidad))
             .join(Carrito, Carrito.id == DetalleCarrito.carrito_id)
             .where(Carrito.expira_en > utcnow(), DetalleCarrito.producto_id.in_(product_ids)))
    if exclude_cart_id is not None:
        carts = carts.where(Carrito.id != exclude_cart_id)
    for product_id, quantity in session.exec(carts.group_by(DetalleCarrito.producto_id)).all():
        result[product_id] = result.get(product_id, 0) + int(quantity)
    return result


def image_url(path, request):
    path = (path or '').strip()
    parsed = urlsplit(path)
    if parsed.scheme in ('http', 'https') and parsed.netloc:
        return path
    if path.startswith('/media/productos/') and '..' not in path and '\\' not in path:
        return (settings.PUBLIC_BASE_URL or str(request.base_url).rstrip('/')) + path
    return None


def product_json(product, category, committed, request):
    enabled = bool(product.activo and product.disponible_para_venta and category and category.activo)
    available = max(0, product.stock - committed) if enabled else 0
    return {'id': product.id, 'codigo': product.codigo, 'nombre': product.nombre,
            'descripcion': product.descripcion, 'categoria_id': product.categoria_id,
            'categoria': category.nombre if category else '', 'precio': money(product.precio),
            'precio_sin_iva': totals(product.precio)['subtotal'], 'stock': available,
            'habilitado': enabled, 'imagen': image_url(product.fotografia, request)}


def locked_products(session, product_ids):
    if not product_ids:
        return {}
    rows = session.exec(select(Producto).where(Producto.id.in_(sorted(set(product_ids))))
                        .order_by(Producto.id).with_for_update()
                        .execution_options(populate_existing=True)).all()
    return {row.id: row for row in rows}


def categories(session):
    return {row.id: row for row in session.exec(select(Categoria)).all()}


def clear_cart(session, cart):
    session.exec(delete(DetalleCarrito).where(DetalleCarrito.carrito_id == cart.id))
    session.delete(cart)
    session.flush()


def find_cart(session, user_id):
    cart = session.exec(select(Carrito).where(Carrito.usuario_id == user_id).with_for_update()).first()
    expired = bool(cart and cart.expira_en <= utcnow())
    if expired:
        clear_cart(session, cart)
        cart = None
    return cart, expired



def require_cart_time(session, cart, expected_id=None):
    if cart and cart.expira_en <= utcnow():
        clear_cart(session, cart)
        session.commit()
        raise HTTPException(409, 'Los 5 minutos terminaron. Tu carrito venció; agrega los productos de nuevo.')
    if expected_id is not None and (not cart or cart.id != expected_id):
        raise HTTPException(409, 'Tu carrito cambió o venció. Actualízalo antes de continuar.')


def cart_minutes(session):
    config = session.exec(select(Configuracion).order_by(Configuracion.id)).first()
    return config.minutos_carrito if config else 5


def cart_snapshot(session, cart, request, *, expired=False):
    if not cart:
        return {'id': None, 'items': [], 'expira_en': None, 'servidor_en': iso(utcnow()), 'expirado': expired, **totals(0)}
    rows = session.exec(select(DetalleCarrito, Producto)
                        .join(Producto, Producto.id == DetalleCarrito.producto_id)
                        .where(DetalleCarrito.carrito_id == cart.id).order_by(DetalleCarrito.id)).all()
    cat = categories(session)
    committed = committed_quantities(session, [p.id for _, p in rows], exclude_cart_id=cart.id)
    items, total = [], Decimal('0.00')
    for line, product in rows:
        product_data = product_json(product, cat.get(product.categoria_id), committed.get(product.id, 0), request)
        items.append({'producto': product_data, 'cantidad': line.cantidad,
                      'importe': money(product.precio * line.cantidad),
                      'disponible': product_data['habilitado'] and line.cantidad <= product_data['stock']})
        total += product.precio * line.cantidad
    return {'id': cart.id, 'items': items, 'expira_en': iso(cart.expira_en), 'servidor_en': iso(utcnow()), 'expirado': expired, **totals(total)}


def order_json(session, order, request):
    rows = session.exec(select(DetallePedido, Producto)
                        .join(Producto, Producto.id == DetallePedido.producto_id)
                        .where(DetallePedido.pedido_id == order.id).order_by(DetallePedido.id)).all()
    return {'id': order.id, 'numero': order.numero, 'estado': order.estado,
            'creado_en': iso(order.creado_en), 'estado_actualizado_en': iso(order.estado_actualizado_en),
            'puede_cancelar': order.estado in settings.CANCEL_ALLOWED_STATES,
            'items': [{'producto_id': product.id, 'nombre': product.nombre, 'cantidad': detail.cantidad,
                       'precio_unitario': money(detail.precio_unitario),
                       'importe': money(detail.precio_unitario * detail.cantidad),
                       'imagen': image_url(product.fotografia, request)} for detail, product in rows],
            **totals(order.total)}


def validate_schedule(session):
    config = session.exec(select(Configuracion).order_by(Configuracion.id)).first()
    if not config or not config.horarios_habilitados:
        return
    local = datetime.now(timezone(timedelta(hours=-6)))
    horarios = session.exec(select(Horario).where(Horario.activo == True,
                                                 Horario.configuracion_id == config.id)).all()
    for row in horarios:
        if row.hora_inicio <= row.hora_fin:
            if row.dia_semana == local.isoweekday() and row.hora_inicio <= local.time().replace(tzinfo=None) < row.hora_fin:
                return
        elif ((row.dia_semana == local.isoweekday() and local.time().replace(tzinfo=None) >= row.hora_inicio)
              or (row.dia_semana == ((local.isoweekday() - 2) % 7) + 1
                  and local.time().replace(tzinfo=None) < row.hora_fin)):
            return
    raise HTTPException(409, 'Los pedidos están fuera del horario de atención.')
