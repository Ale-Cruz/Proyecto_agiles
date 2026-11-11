from decimal import Decimal
import secrets

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from commerce import (ACTIVE_STATES, cart_snapshot, clear_cart, find_cart, locked_products,
                      order_json, validate_schedule, require_cart_time)
from database import get_session
from models import DetalleCarrito, DetallePedido, Pedido, utcnow
from schemas import PedidoInput
from security import CurrentSession, current_session, locked_user
import settings

router = APIRouter()
ALFABETO_PEDIDO = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'


def nuevo_numero():
    return 'PED-' + ''.join(secrets.choice(ALFABETO_PEDIDO) for _ in range(4))


@router.post('/', status_code=201)
def crear(data: PedidoInput, request: Request, response: Response,
          auth: CurrentSession = Depends(current_session), session: Session = Depends(get_session, scope="function")):
    user = locked_user(session, auth)
    operation_id = data.operacion_id.hex
    previous = session.exec(select(Pedido).where(Pedido.operacion_id == operation_id)).first()
    if previous:
        if previous.estudiante_id != user.id:
            raise HTTPException(409, 'La solicitud no es válida. Abre un carrito nuevo.')
        response.status_code = 200
        return order_json(session, previous, request)
    if session.exec(select(Pedido.id).where(Pedido.estudiante_id == user.id,
                                            Pedido.estado.in_(('pendiente', *ACTIVE_STATES)))).first():
        raise HTTPException(409, 'Ya tienes un pedido activo. Recógelo antes de enviar otro.')
    validate_schedule(session)
    cart, expired = find_cart(session, user.id)
    if not cart:
        if expired:
            session.commit()
        raise HTTPException(409, 'Tu carrito venció o está vacío. Agrega los productos de nuevo.')
    require_cart_time(session, cart, data.carrito_id)
    details = session.exec(select(DetalleCarrito).where(DetalleCarrito.carrito_id == cart.id)).all()
    if not details:
        raise HTTPException(409, 'Agrega al menos un producto al carrito.')
    locked_products(session, [line.producto_id for line in details])
    require_cart_time(session, cart, data.carrito_id)
    snapshot = cart_snapshot(session, cart, request)
    for item in snapshot['items']:
        if not item['disponible']:
            product = item['producto']
            raise HTTPException(409, f"La disponibilidad de {product['nombre']} cambió. Quedan {product['stock']} unidades.")
    if Decimal(snapshot['total']) != data.total_esperado:
        raise HTTPException(409, 'Los precios cambiaron. Revisa el nuevo total antes de confirmar.')
    for _ in range(40):
        number = nuevo_numero()
        if session.exec(select(Pedido.id).where(Pedido.numero == number)).first():
            continue
        order = Pedido(numero=number, operacion_id=operation_id,
                       estudiante_id=user.id, estado='en_preparacion',
                       total=Decimal(snapshot['total']))
        try:
            with session.begin_nested():
                session.add(order)
                session.flush()
        except IntegrityError:
            if session.exec(select(Pedido.id).where(Pedido.numero == number)).first():
                continue
            raise HTTPException(409, 'Ya tienes un pedido activo o esta solicitud ya fue procesada.') from None
        break
    else:
        raise HTTPException(503, 'No se pudo asignar un número de pedido. Intenta de nuevo.')
    for line in snapshot['items']:
        session.add(DetallePedido(pedido_id=order.id, producto_id=line['producto']['id'], cantidad=line['cantidad'],
                                  precio_unitario=Decimal(line['producto']['precio'])))
    clear_cart(session, cart)
    session.flush()
    return order_json(session, order, request)


@router.get('/mios')
def mios(request: Request, auth: CurrentSession = Depends(current_session), session: Session = Depends(get_session, scope="function")):
    active = session.exec(select(Pedido).where(Pedido.estudiante_id == auth.user_id,
                                              Pedido.estado.in_(ACTIVE_STATES)).order_by(Pedido.id.desc())).first()
    history = session.exec(select(Pedido).where(Pedido.estudiante_id == auth.user_id,
                                               Pedido.estado.in_(('entregado', 'cancelado')))
                           .order_by(Pedido.id.desc()).limit(30)).all()
    return {'pedido_activo': order_json(session, active, request) if active else None,
            'historial': [order_json(session, order, request) for order in history]}


@router.put('/{pedido_id}/cancelar')
def cancelar(request: Request, pedido_id: int = Path(gt=0), auth: CurrentSession = Depends(current_session),
             session: Session = Depends(get_session, scope="function")):
    user = locked_user(session, auth)
    order = session.exec(select(Pedido).where(Pedido.id == pedido_id, Pedido.estudiante_id == user.id)).first()
    if not order:
        raise HTTPException(404, 'El pedido no existe.')
    lines = session.exec(select(DetallePedido).where(DetallePedido.pedido_id == order.id)).all()
    locked_products(session, [line.producto_id for line in lines])
    session.refresh(order, with_for_update=True)
    if order.estado == 'cancelado':
        return order_json(session, order, request)
    if order.estado not in settings.CANCEL_ALLOWED_STATES:
        raise HTTPException(409, 'Ya no puedes cancelar desde la app. Acércate al cajero.')
    order.estado, order.estado_actualizado_en = 'cancelado', utcnow()
    order.anulado_por, order.anulado_en = user.id, utcnow()
    order.motivo_anulacion = 'Cancelado por el estudiante desde la app.'
    session.add(order)
    session.flush()
    return order_json(session, order, request)
