import asyncio
from contextlib import asynccontextmanager, suppress
import logging
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, select

from commerce import clear_cart
from database import engine
from models import Carrito, utcnow
from routers import auth, carrito, pedidos, productos
import settings


def cleanup_carts():
    with Session(engine) as session, session.begin():
        rows = session.exec(select(Carrito).where(Carrito.expira_en <= utcnow()).order_by(Carrito.id)
                            .limit(100).with_for_update(skip_locked=True)).all()
        for row in rows:
            clear_cart(session, row)


async def maintenance():
    while True:
        try:
            await asyncio.to_thread(cleanup_carts)
        except Exception:
            logging.getLogger(__name__).warning('No se pudo completar la limpieza de carritos.')
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(maintenance())
    yield
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
    engine.dispose()


app = FastAPI(title='API Cafetería ITCA', version='2.0.0', lifespan=lifespan)
app.add_middleware(CORSMiddleware,
    allow_origins=[v.strip() for v in os.getenv('CORS_ORIGINS', 'http://localhost:8000,http://127.0.0.1:8000').split(',')],
    allow_credentials=False, allow_headers=['Authorization', 'Content-Type'], allow_methods=['GET', 'POST', 'PUT', 'DELETE'])
app.include_router(auth.router, prefix='/api/v1/auth', tags=['Autenticación'])
app.include_router(productos.router, prefix='/api/v1/productos', tags=['Menú'])
app.include_router(carrito.router, prefix='/api/v1/carrito', tags=['Carrito'])
app.include_router(pedidos.router, prefix='/api/v1/pedidos', tags=['Pedidos'])
app.mount('/media', StaticFiles(directory=str(settings.MEDIA_ROOT), check_dir=False), name='media')


@app.middleware('http')
async def no_cache_private_data(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@app.exception_handler(OperationalError)
async def unavailable(request, exc):
    return JSONResponse(status_code=503, content={'detail': 'La base de datos no está disponible. Inténtalo de nuevo.'})


@app.get('/')
def root():
    return {'servicio': 'API Cafetería ITCA', 'version': '2.0.0'}
