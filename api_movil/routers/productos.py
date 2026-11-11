from fastapi import APIRouter, Depends, HTTPException, Path, Request
from sqlmodel import Session, select

from commerce import committed_quantities, product_json
from database import get_session
from models import Categoria, Producto

router = APIRouter()


@router.get('/categorias')
def categorias(session: Session = Depends(get_session, scope="function")):
    return [{'id': c.id, 'nombre': c.nombre} for c in session.exec(
        select(Categoria).where(Categoria.activo == True).order_by(Categoria.nombre)).all()]


@router.get('/')
def productos(request: Request, session: Session = Depends(get_session, scope="function")):
    rows = session.exec(select(Producto, Categoria).join(Categoria, Categoria.id == Producto.categoria_id)
        .where(Producto.activo == True, Producto.disponible_para_venta == True, Categoria.activo == True)
        .order_by(Producto.nombre)).all()
    committed = committed_quantities(session, [p.id for p, _ in rows])
    return [product_json(p, c, committed.get(p.id, 0), request) for p, c in rows]


@router.get('/{producto_id}')
def producto(request: Request, producto_id: int = Path(gt=0), session: Session = Depends(get_session, scope="function")):
    row = session.exec(select(Producto, Categoria).join(Categoria, Categoria.id == Producto.categoria_id)
        .where(Producto.id == producto_id, Producto.activo == True,
               Producto.disponible_para_venta == True, Categoria.activo == True)).first()
    if not row:
        raise HTTPException(404, 'El producto no está disponible.')
    product, category = row
    committed = committed_quantities(session, [product.id])
    return product_json(product, category, committed.get(product.id, 0), request)
