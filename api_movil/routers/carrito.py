from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from sqlalchemy import delete
from sqlmodel import Session, select

from commerce import (cart_minutes, cart_snapshot, categories, clear_cart, committed_quantities,
                      find_cart, locked_products, product_json, require_cart_time)
from database import get_session
from models import Carrito, DetalleCarrito, utcnow
from schemas import CantidadInput
from security import CurrentSession, current_session, locked_user

router = APIRouter()


@router.get('/')
def consultar(request: Request, auth: CurrentSession = Depends(current_session), session: Session = Depends(get_session, scope="function")):
    user = locked_user(session, auth)
    cart, expired = find_cart(session, user.id)
    return cart_snapshot(session, cart, request, expired=expired)


@router.put('/items/{producto_id}')
def cantidad(data: CantidadInput, request: Request, producto_id: int = Path(gt=0),
             auth: CurrentSession = Depends(current_session), session: Session = Depends(get_session, scope="function")):
    user = locked_user(session, auth)
    cart, expired = find_cart(session, user.id)
    if expired and data.carrito_id is not None:
        session.commit()
        raise HTTPException(409, 'Los 5 minutos terminaron. Tu carrito venció; agrega los productos de nuevo.')
    require_cart_time(session, cart, data.carrito_id)
    product = locked_products(session, [producto_id]).get(producto_id)
    if not product:
        raise HTTPException(404, 'El producto no existe.')
    require_cart_time(session, cart, data.carrito_id)
    if data.cantidad:
        category = categories(session).get(product.categoria_id)
        committed = committed_quantities(session, [producto_id], exclude_cart_id=cart.id if cart else None)
        available = product_json(product, category, committed.get(producto_id, 0), request)
        if not available['habilitado'] or data.cantidad > available['stock']:
            raise HTTPException(409, f"Solo hay {available['stock']} unidades disponibles de {product.nombre}.")
        if not cart:
            started = utcnow().replace(microsecond=0)
            cart = Carrito(usuario_id=user.id, ultima_actividad=started,
                           expira_en=started + timedelta(minutes=cart_minutes(session)))
            session.add(cart)
            session.flush()
    if cart:
        detail = session.exec(select(DetalleCarrito).where(DetalleCarrito.carrito_id == cart.id,
                                                          DetalleCarrito.producto_id == producto_id)).first()
        if data.cantidad:
            if detail:
                detail.cantidad = data.cantidad
            else:
                detail = DetalleCarrito(carrito_id=cart.id, producto_id=producto_id, cantidad=data.cantidad)
            session.add(detail)
        elif detail:
            session.delete(detail)
        cart.ultima_actividad = utcnow()
        session.add(cart)
        session.flush()
    return cart_snapshot(session, cart, request)


@router.delete('/')
def vaciar(request: Request, auth: CurrentSession = Depends(current_session), session: Session = Depends(get_session, scope="function")):
    user = locked_user(session, auth)
    cart, expired = find_cart(session, user.id)
    if cart:
        # Quitar todos los productos libera unidades, pero conserva el plazo original.
        session.execute(delete(DetalleCarrito).where(DetalleCarrito.carrito_id == cart.id))
        cart.ultima_actividad = utcnow()
        session.add(cart)
        session.flush()
    return cart_snapshot(session, cart, request, expired=expired)
