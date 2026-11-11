from datetime import timedelta
import hmac
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from database import get_session
from mailer import send_code
from models import CodigoVerificacion, SesionMovil, Usuario, utcnow
from schemas import CorreoInput, LoginInput, PasswordInput, RegistroInput
from security import (CurrentSession, clear_login_limit, current_session, issue_session,
                      locked_user, password_hash, password_valid, public_user, rate_limit, secret_hash)

router = APIRouter()


@router.post('/login')
def login(data: LoginInput, request: Request, session: Session = Depends(get_session, scope="function")):
    rate_limit(request, 'login', data.correo)
    user = session.exec(select(Usuario).where(Usuario.correo == data.correo).with_for_update()).first()
    valid = password_valid(data.password, user.password_hash if user else '')
    if not valid or not user or user.rol != 'estudiante' or not user.habilitado:
        raise HTTPException(401, 'Correo o contraseña incorrectos.')
    token = issue_session(session, user)
    session.add(user)
    session.flush()
    clear_login_limit(data.correo)
    return {'access_token': token, 'token_type': 'bearer', 'usuario': public_user(user)}


def request_code(data, purpose, request, session):
    rate_limit(request, 'codigo-' + purpose, data.correo, limit=5, seconds=900, ip_limit=20)
    user = session.exec(select(Usuario).where(Usuario.correo == data.correo)).first()
    if purpose == 'registro' and user:
        raise HTTPException(409, 'Este correo ya está registrado. Inicia sesión o recupera tu contraseña.')
    eligible = (not user) if purpose == 'registro' else bool(user and user.rol == 'estudiante' and user.habilitado)
    generic = {'mensaje': 'Si el correo corresponde al proceso solicitado, recibirás un código de verificación.'}
    if not eligible:
        return generic
    now = utcnow()
    statement = insert(CodigoVerificacion).values(correo=data.correo, proposito=purpose,
        codigo_hash='', expira_en=now, enviado_en=now - timedelta(minutes=2), intentos=0)
    session.execute(statement.on_duplicate_key_update(correo=statement.inserted.correo))
    row = session.exec(select(CodigoVerificacion).where(CodigoVerificacion.correo == data.correo,
        CodigoVerificacion.proposito == purpose).with_for_update()).one()
    if now < row.enviado_en + timedelta(seconds=60):
        raise HTTPException(429, 'Espera un minuto antes de pedir otro código.', headers={'Retry-After': '60'})
    code = f'{secrets.randbelow(1_000_000):06d}'
    row.codigo_hash = secret_hash(f'codigo:{purpose}:{data.correo}:{code}')
    row.enviado_en, row.expira_en, row.intentos = now, now + timedelta(minutes=10), 0
    send_code(data.correo, code, purpose)
    session.add(row)
    return generic


@router.post('/enviar-codigo')
def enviar_codigo(data: CorreoInput, request: Request, session: Session = Depends(get_session, scope="function")):
    return request_code(data, 'registro', request, session)


@router.post('/recuperar')
def recuperar(data: CorreoInput, request: Request, session: Session = Depends(get_session, scope="function")):
    return request_code(data, 'recuperacion', request, session)


def verified_code(session, data, purpose):
    row = session.exec(select(CodigoVerificacion).where(CodigoVerificacion.correo == data.correo,
        CodigoVerificacion.proposito == purpose).with_for_update()).first()
    if not row or row.expira_en <= utcnow() or row.intentos >= 5:
        raise HTTPException(400, 'El código no es válido o ha vencido. Solicita uno nuevo.')
    expected = secret_hash(f'codigo:{purpose}:{data.correo}:{data.codigo}')
    if not hmac.compare_digest(expected, row.codigo_hash):
        row.intentos += 1
        session.add(row)
        session.commit()
        raise HTTPException(400, 'El código no es válido o ha vencido. Solicita uno nuevo.')
    return row


@router.post('/verificar-registro', status_code=201)
def verificar_registro(data: RegistroInput, request: Request, session: Session = Depends(get_session, scope="function")):
    rate_limit(request, 'verificar-registro', data.correo, limit=10, ip_limit=40)
    code = verified_code(session, data, 'registro')
    if session.exec(select(Usuario.id).where(Usuario.correo == data.correo)).first():
        raise HTTPException(409, 'Este correo ya está registrado. Inicia sesión o recupera tu contraseña.')
    user = Usuario(nombre=data.nombre, correo=data.correo, password_hash=password_hash(data.password),
                   rol='estudiante', habilitado=True)
    session.add(user)
    session.delete(code)
    try:
        session.flush()
    except IntegrityError:
        raise HTTPException(409, 'Este correo ya está registrado.') from None
    return {'mensaje': 'Cuenta creada. Ya puedes iniciar sesión.'}


@router.post('/cambiar-password')
def cambiar_password(data: PasswordInput, request: Request, session: Session = Depends(get_session, scope="function")):
    rate_limit(request, 'verificar-recuperacion', data.correo, limit=10, ip_limit=40)
    code = verified_code(session, data, 'recuperacion')
    user = session.exec(select(Usuario).where(Usuario.correo == data.correo).with_for_update()).first()
    if not user or not user.habilitado or user.rol != 'estudiante':
        raise HTTPException(400, 'No se pudo completar la recuperación.')
    user.password_hash = password_hash(data.password)
    user.token_sesion_hash = user.sesion_expira_en = None
    session.exec(delete(SesionMovil).where(SesionMovil.usuario_id == user.id))
    session.add(user)
    session.delete(code)
    return {'mensaje': 'Contraseña actualizada. Inicia sesión de nuevo.'}


@router.get('/me')
def me(auth: CurrentSession = Depends(current_session), session: Session = Depends(get_session, scope="function")):
    return public_user(session.get(Usuario, auth.user_id))


@router.post('/logout')
def logout(auth: CurrentSession = Depends(current_session), session: Session = Depends(get_session, scope="function")):
    locked_user(session, auth)
    session.exec(delete(SesionMovil).where(SesionMovil.token_hash == auth.token_hash))
    # El carrito pertenece a la cuenta y sigue disponible en los otros teléfonos.
    return {'mensaje': 'Sesión cerrada.'}
