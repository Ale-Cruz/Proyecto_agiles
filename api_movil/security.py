import base64
from dataclasses import dataclass
from datetime import timedelta
import hashlib
import hmac
import secrets

import bcrypt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlmodel import Session, select

from database import engine, get_session
from models import SesionMovil, Usuario, utcnow
import settings

bearer = HTTPBearer(auto_error=False)
DUMMY_HASH = bcrypt.hashpw(b'not-a-user-password', bcrypt.gensalt())


def secret_hash(value):
    return hmac.new(settings.SECRET_KEY.encode(), value.encode(), hashlib.sha256).hexdigest()


def password_hash(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(rounds=12)).decode()


def password_valid(password, encoded):
    raw = password.encode('utf-8')
    try:
        if encoded.startswith(('$2a$', '$2b$', '$2y$')):
            return len(raw) <= 72 and bcrypt.checkpw(raw, encoded.encode())
        if encoded.startswith('pbkdf2_sha256$'):
            _, iterations, salt, expected = encoded.split('$', 3)
            if not 1 <= int(iterations) <= 10_000_000:
                return False
            actual = base64.b64encode(hashlib.pbkdf2_hmac('sha256', raw, salt.encode(), int(iterations))).decode()
            return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        pass
    bcrypt.checkpw(b'not-a-user-password', DUMMY_HASH)
    return False


def rate_limit(request: Request, action: str, correo: str, *, limit=5, seconds=900, ip_limit=30):
    """Contadores persistentes, independientes de la transacción del endpoint."""
    ip = request.client.host if request.client else 'unknown'
    keys = {secret_hash(f'movil:{action}:correo:{correo}'): limit,
            secret_hash(f'movil:{action}:ip:{ip}'): ip_limit}
    now = utcnow()
    with Session(engine) as session, session.begin():
        rows = []
        for key in sorted(keys):
            session.execute(text('INSERT INTO intentos_acceso (clave,fallos,inicio_ventana) '
                                 'VALUES (:key,0,:now) ON DUPLICATE KEY UPDATE clave=clave'),
                            {'key': key, 'now': now})
            row = session.execute(text('SELECT fallos,inicio_ventana FROM intentos_acceso '
                                       'WHERE clave=:key FOR UPDATE'), {'key': key}).mappings().one()
            count = row['fallos'] if now < row['inicio_ventana'] + timedelta(seconds=seconds) else 0
            start = row['inicio_ventana'] if count else now
            rows.append((key, count, start))
        if any(count >= keys[key] for key, count, _ in rows):
            raise HTTPException(429, 'Demasiados intentos. Espera unos minutos e inténtalo de nuevo.',
                                headers={'Retry-After': str(seconds)})
        for key, count, start in rows:
            session.execute(text('UPDATE intentos_acceso SET fallos=:count,inicio_ventana=:start WHERE clave=:key'),
                            {'key': key, 'count': count + 1, 'start': start})


def clear_login_limit(correo):
    with Session(engine) as session, session.begin():
        session.execute(text('DELETE FROM intentos_acceso WHERE clave=:key'),
                        {'key': secret_hash(f'movil:login:correo:{correo}')})


@dataclass(frozen=True)
class CurrentSession:
    user_id: int
    token_hash: str


def validate_user(user, stored_session):
    if (not user or not user.habilitado or user.rol != 'estudiante'
            or not stored_session or stored_session.usuario_id != user.id
            or (stored_session.expira_en is not None and stored_session.expira_en <= utcnow())):
        raise HTTPException(401, 'Tu sesión terminó. Inicia sesión de nuevo.', headers={'WWW-Authenticate': 'Bearer'})
    return user


def current_session(credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
                    session: Session = Depends(get_session, scope="function")):
    if not credentials or credentials.scheme.lower() != 'bearer' or len(credentials.credentials) > 200:
        raise HTTPException(401, 'Inicia sesión para continuar.', headers={'WWW-Authenticate': 'Bearer'})
    hashed = secret_hash('session:' + credentials.credentials)
    stored = session.get(SesionMovil, hashed)
    user = session.get(Usuario, stored.usuario_id) if stored else None
    validate_user(user, stored)
    return CurrentSession(user.id, hashed)


def locked_user(session, auth):
    # Mismo orden de bloqueo en login, carrito, pedidos, logout y recuperación.
    user = session.exec(select(Usuario).where(Usuario.id == auth.user_id).with_for_update()
                        .execution_options(populate_existing=True)).first()
    stored = session.exec(select(SesionMovil).where(SesionMovil.token_hash == auth.token_hash)
                          .with_for_update().execution_options(populate_existing=True)).first()
    return validate_user(user, stored)


def issue_session(session, user):
    token = secrets.token_urlsafe(48)
    expires = utcnow() + timedelta(days=settings.SESSION_DAYS) if settings.SESSION_DAYS else None
    session.add(SesionMovil(token_hash=secret_hash('session:' + token), usuario_id=user.id, expira_en=expires))
    return token


def public_user(user):
    return {'id': user.id, 'nombre': user.nombre, 'correo': user.correo}
