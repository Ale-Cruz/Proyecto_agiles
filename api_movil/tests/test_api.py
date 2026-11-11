from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
import re
import sys
from threading import Barrier
import uuid
import bcrypt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlmodel import Session, select
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import database, main, security
from models import Carrito, Categoria, CodigoVerificacion, Configuracion, DetalleCarrito, DetallePedido, Pedido, Producto, Usuario, utcnow
from routers import auth
TABLES=['usuarios','sesiones_movil','categorias','productos','configuracion','horarios_pedidos','carritos','detalles_carrito','pedidos','detalles_pedido','codigos_verificacion_movil','intentos_acceso']
PASSWORD='ClaveSegura2026!'
HASH=bcrypt.hashpw(PASSWORD.encode(),bcrypt.gensalt(rounds=4)).decode()
@pytest.fixture(scope='session',autouse=True)
def db():
    original=database.engine
    name='test_movil_codex_'+uuid.uuid4().hex[:10]
    assert name.startswith('test_movil_codex_') and len(name)==27
    with original.connect() as c:
        assert c.scalar(text('SELECT DATABASE()'))=='sistema_pedidos'
        ddl=[c.exec_driver_sql(f'SHOW CREATE TABLE {t}').one()[1] for t in TABLES]
        c.exec_driver_sql(f'CREATE DATABASE {name} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci')
    engine=create_engine(original.url.set(database=name),isolation_level='READ COMMITTED',pool_pre_ping=True,connect_args={'init_command':"SET time_zone = '+00:00'"})
    patch=pytest.MonkeyPatch()
    try:
        with engine.begin() as c:
            for sql in ddl:c.exec_driver_sql(sql)
        for mod in (database,main,security):patch.setattr(mod,'engine',engine)
        yield engine
    finally:
        patch.undo();engine.dispose()
        with original.connect() as c:c.exec_driver_sql(f'DROP DATABASE {name}')
@pytest.fixture(autouse=True)
def seed(db):
    with db.begin() as c:
        for t in reversed(TABLES):c.exec_driver_sql(f'DELETE FROM {t}')
    with Session(db) as s,s.begin():
        s.add(Categoria(id=1,nombre='Bebidas'))
        s.add(Configuracion(id=1,minutos_carrito=5,horarios_habilitados=False))
        for i in (1,10,11):s.add(Usuario(id=i,nombre=f'Persona {i}',correo=f'persona{i}@itca.edu.sv',password_hash=HASH,rol='administrador' if i==1 else 'estudiante'))
        s.flush()
        s.add(Producto(id=1,categoria_id=1,codigo='CAFE-1',nombre='Cafe',precio=Decimal('1.13'),fotografia='',stock=10))
@pytest.fixture
def client():
    with TestClient(main.app) as c:yield c
def headers(c,i=10):
    r=c.post('/api/v1/auth/login',json={'correo':f'persona{i}@itca.edu.sv','password':PASSWORD})
    assert r.status_code==200,r.text
    return {'Authorization':'Bearer '+r.json()['access_token']}
def cart(c,h,n=1):return c.put('/api/v1/carrito/items/1',json={'cantidad':n},headers=h)
def send(c,h,total='1.13',key=None):return c.post('/api/v1/pedidos/',headers=h,json={'operacion_id':key or str(uuid.uuid4()),'total_esperado':total})
def edit(db,table,sql,params=None):
    with db.begin() as c:c.execute(text(f'UPDATE {table} SET {sql}'),params or {})
def test_catalog_and_images(client,db):
    r=client.get('/api/v1/productos/').json()
    assert len(r)==1 and r[0]['nombre']=='Cafe'
    assert (r[0]['precio'],r[0]['precio_sin_iva'])==('1.13','1.00')
    edit(db,'productos',"fotografia='/media/productos/foto.webp'")
    assert client.get('/api/v1/productos/1').json()['imagen']=='http://testserver/media/productos/foto.webp'
    assert client.get('/api/v1/productos/categorias').json()==[{'id':1,'nombre':'Bebidas'}]
@pytest.mark.parametrize('table,sql',[('productos','activo=0'),('productos','disponible_para_venta=0'),('categorias','activo=0')])
def test_paused_products(client,db,table,sql):
    h=headers(client);edit(db,table,sql)
    assert client.get('/api/v1/productos/').json()==[]
    assert cart(client,h).status_code==409
def test_bad_login_employees_and_private_routes(client):
    for mail,pw in [('inexistente@itca.edu.sv',PASSWORD),('persona10@itca.edu.sv','mal'),('persona1@itca.edu.sv',PASSWORD)]:
        assert client.post('/api/v1/auth/login',json={'correo':mail,'password':pw}).status_code==401
    assert client.get('/api/v1/carrito/').status_code==401
    assert client.get('/api/v1/pedidos/mios').status_code==401
    for method in ['POST','PUT','DELETE']:assert client.request(method,'/api/v1/productos/1',json={}).status_code in (404,405)
def test_disabled_account(client,db):
    h=headers(client);assert client.get('/api/v1/auth/me',headers=h).json()['id']==10
    edit(db,'usuarios','habilitado=0 WHERE id=10')
    assert client.get('/api/v1/carrito/',headers=h).status_code==401
def test_rate_limit(client):
    for _ in range(5):assert client.post('/api/v1/auth/login',json={'correo':'persona10@itca.edu.sv','password':'mal'}).status_code==401
    assert client.post('/api/v1/auth/login',json={'correo':'persona10@itca.edu.sv','password':PASSWORD}).status_code==429
def test_register_real_single_use_code(client,db,monkeypatch):
    sent=[];monkeypatch.setattr(auth,'send_code',lambda *args:sent.append(args));mail='nuevo@itca.edu.sv'
    assert client.post('/api/v1/auth/enviar-codigo',json={'correo':mail}).status_code==200
    code=sent[0][1]
    with Session(db) as s:
        saved=s.get(CodigoVerificacion,(mail,'registro'));assert len(saved.codigo_hash)==64 and saved.codigo_hash!=code
    data={'nombre':'Nuevo','correo':mail,'password':PASSWORD,'codigo':code}
    assert client.post('/api/v1/auth/verificar-registro',json={**data,'rol':'administrador'}).status_code==422
    assert client.post('/api/v1/auth/verificar-registro',json=data).status_code==201
    assert client.post('/api/v1/auth/verificar-registro',json=data).status_code==400
    assert client.post('/api/v1/auth/login',json={'correo':mail,'password':PASSWORD}).status_code==200
    with Session(db) as s:assert s.exec(select(Usuario).where(Usuario.correo==mail)).one().rol=='estudiante'
def test_register_rejects_existing_email_before_code(client,db,monkeypatch):
    sent=[];monkeypatch.setattr(auth,'send_code',lambda *args:sent.append(args))
    response=client.post('/api/v1/auth/enviar-codigo',json={'correo':'Persona10@ITCA.EDU.SV'})
    assert response.status_code==409
    assert 'ya está registrado' in response.json()['detail']
    assert sent==[]
    with Session(db) as s:
        assert s.get(CodigoVerificacion,('persona10@itca.edu.sv','registro')) is None
def test_bad_codes_and_resend_limit(client,db,monkeypatch):
    sent=[];monkeypatch.setattr(auth,'send_code',lambda *args:sent.append(args));mail='nuevo@itca.edu.sv'
    assert client.post('/api/v1/auth/enviar-codigo',json={'correo':mail}).status_code==200
    assert client.post('/api/v1/auth/enviar-codigo',json={'correo':mail}).status_code==429
    wrong='000000' if sent[0][1]!='000000' else '111111'
    data={'nombre':'Nuevo','correo':mail,'password':PASSWORD,'codigo':wrong}
    for _ in range(5):assert client.post('/api/v1/auth/verificar-registro',json=data).status_code==400
    with Session(db) as s:assert s.get(CodigoVerificacion,(mail,'registro')).intentos==5
    assert client.post('/api/v1/auth/verificar-registro',json={**data,'codigo':sent[0][1]}).status_code==400
def test_expired_code(client,db,monkeypatch):
    sent=[];monkeypatch.setattr(auth,'send_code',lambda *args:sent.append(args));mail='nuevo@itca.edu.sv'
    client.post('/api/v1/auth/enviar-codigo',json={'correo':mail})
    edit(db,'codigos_verificacion_movil','expira_en=:t',{'t':utcnow()-timedelta(seconds=1)})
    assert client.post('/api/v1/auth/verificar-registro',json={'nombre':'Nuevo','correo':mail,'password':PASSWORD,'codigo':sent[0][1]}).status_code==400
def test_smtp_failure_not_success(client,monkeypatch):
    from fastapi import HTTPException
    def fail(*args):raise HTTPException(503,'Correo no disponible')
    monkeypatch.setattr(auth,'send_code',fail)
    assert client.post('/api/v1/auth/enviar-codigo',json={'correo':'nuevo@itca.edu.sv'}).status_code==503
def test_password_reset_revokes_session(client,monkeypatch):
    h=headers(client);other=headers(client);sent=[];monkeypatch.setattr(auth,'send_code',lambda *args:sent.append(args));mail='persona10@itca.edu.sv'
    assert client.post('/api/v1/auth/recuperar',json={'correo':mail}).status_code==200
    assert client.post('/api/v1/auth/cambiar-password',json={'correo':mail,'password':'OtraClave2026!','codigo':sent[0][1]}).status_code==200
    assert client.get('/api/v1/auth/me',headers=h).status_code==401
    assert client.get('/api/v1/auth/me',headers=other).status_code==401
    assert client.post('/api/v1/auth/login',json={'correo':mail,'password':PASSWORD}).status_code==401
    assert client.post('/api/v1/auth/login',json={'correo':mail,'password':'OtraClave2026!'}).status_code==200
@pytest.mark.parametrize('n',[-1,True,0.5,2147483648])
def test_quantity_validation(client,n):assert cart(client,headers(client),n).status_code==422
def test_cart_totals_isolation_and_logout(client):
    a,b=headers(client),headers(client,11);r=cart(client,a,2);assert r.status_code==200,r.text
    r=r.json();assert (r['subtotal'],r['iva'],r['total'])==('2.00','0.26','2.26')
    assert client.get('/api/v1/carrito/',headers=b).json()['items']==[]
    assert cart(client,a,11).status_code==409
    assert client.post('/api/v1/auth/logout',headers=a).status_code==200
    assert client.get('/api/v1/carrito/',headers=a).status_code==401
    assert client.get('/api/v1/carrito/',headers=headers(client)).json()['items'][0]['cantidad']==2
def test_cart_cleanup_without_app_request(client,db):
    h=headers(client);cart(client,h)
    edit(db,'carritos','expira_en=:t',{'t':utcnow()-timedelta(seconds=1)})
    main.cleanup_carts()
    with Session(db) as s:assert s.exec(select(Carrito)).all()==[] and s.exec(select(DetalleCarrito)).all()==[]
def test_order_persistence_idempotency_and_no_inventory_decrease(client,db):
    h=headers(client);cart(client,h,2);key=str(uuid.uuid4());r=send(client,h,'2.26',key);assert r.status_code==201,r.text
    order=r.json();assert order['estado']=='en_preparacion'
    assert re.fullmatch(r'PED-[A-HJ-NP-Z2-9]{4}',order['numero'])
    again=send(client,h,'2.26',key);assert again.status_code==200 and again.json()['id']==order['id']
    assert client.get('/api/v1/carrito/',headers=h).json()['items']==[]
    assert client.get('/api/v1/productos/1').json()['stock']==8
    with Session(db) as s:
        assert s.get(Producto,1).stock==10 and len(s.exec(select(Pedido)).all())==1
        assert s.get(Pedido,order['id']).operacion_id==uuid.UUID(key).hex
    assert client.get('/api/v1/pedidos/mios',headers=h).json()['pedido_activo']['id']==order['id']
def test_short_number_collision_uses_another_code(client,db,monkeypatch):
    from routers import pedidos as order_router
    with Session(db) as s,s.begin():
        s.add(Pedido(numero='PED-AAAA',estudiante_id=11,estado='cancelado',total=Decimal('0.00')))
    candidates=iter(['PED-AAAA','PED-BBBB'])
    monkeypatch.setattr(order_router,'nuevo_numero',lambda:next(candidates))
    h=headers(client)
    assert cart(client,h).status_code==200
    key=str(uuid.uuid4())
    result=send(client,h,'1.13',key)
    assert result.status_code==201,result.text
    assert result.json()['numero']=='PED-BBBB'
    assert send(client,h,'1.13',key).json()['numero']=='PED-BBBB'
def test_cancel_ownership_and_ready_limit(client,db):
    a,b=headers(client),headers(client,11);cart(client,a,2);order=send(client,a,'2.26').json();url=f"/api/v1/pedidos/{order['id']}/cancelar"
    assert client.put(url,headers=b).status_code==404
    assert client.put(url,headers=a).status_code==200
    assert client.get('/api/v1/productos/1').json()['stock']==10
    cart(client,a,2);assert send(client,a,'2.26').status_code==201
    edit(db,'pedidos',"estado='listo' WHERE estado='en_preparacion'")
    order=client.get('/api/v1/pedidos/mios',headers=a).json()['pedido_activo'];assert not order['puede_cancelar']
    assert client.put(f"/api/v1/pedidos/{order['id']}/cancelar",headers=a).status_code==409
def test_price_revalidation_and_one_active_order(client,db):
    h=headers(client);cart(client,h,2);edit(db,'productos','precio=2.00')
    assert send(client,h,'2.26').status_code==409
    assert client.get('/api/v1/carrito/',headers=h).json()['total']=='4.00'
    assert send(client,h,'4.00').status_code==201
    cart(client,h);assert send(client,h,'2.00').status_code==409
def test_empty_and_forged_order_rejected(client):
    h=headers(client);assert send(client,h).status_code==409
    assert client.post('/api/v1/pedidos/',headers=h,json={'estudiante_id':11,'items':[]}).status_code==422
def test_schedule_switch(client,db):
    h=headers(client);cart(client,h);edit(db,'configuracion','horarios_habilitados=1')
    assert send(client,h).status_code==409
def test_two_students_last_unit(client,db):
    edit(db,'productos','stock=1');a,b=headers(client),headers(client,11)
    gate=Barrier(2)
    def compete(h):
        gate.wait(timeout=10)
        return h,cart(client,h)
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs=[pool.submit(compete,h) for h in (a,b)]
        results=[j.result(timeout=30) for j in jobs]
    assert sorted(r.status_code for _,r in results)==[200,409],[(r.status_code,r.text) for _,r in results]
    winner=next(h for h,r in results if r.status_code==200)
    loser=next(h for h,r in results if r.status_code==409)
    assert client.get('/api/v1/productos/1').json()['stock']==0
    assert send(client,winner).status_code==201
    assert send(client,loser).status_code==409
    assert client.get('/api/v1/productos/1').json()['stock']==0
    with Session(db) as s:
        assert s.get(Producto,1).stock==1
        assert len(s.exec(select(Pedido)).all())==1


def test_same_account_sessions_share_one_cart_and_logout_only_one(client,db):
    a,b=headers(client),headers(client)
    assert a != b
    assert cart(client,a,2).status_code==200
    assert client.get('/api/v1/carrito/',headers=b).json()['items'][0]['cantidad']==2
    assert cart(client,b,3).status_code==200
    assert client.get('/api/v1/carrito/',headers=a).json()['items'][0]['cantidad']==3
    with Session(db) as s:
        assert len(s.exec(select(Carrito)).all())==1
        rows=s.execute(text('SELECT token_hash FROM sesiones_movil')).scalars().all()
        assert len(rows)==2 and all(len(v)==64 for v in rows)
        assert all(v not in a['Authorization'] and v not in b['Authorization'] for v in rows)
    assert client.post('/api/v1/auth/logout',headers=a).status_code==200
    assert client.get('/api/v1/auth/me',headers=a).status_code==401
    assert client.get('/api/v1/auth/me',headers=b).status_code==200
    assert client.get('/api/v1/carrito/',headers=b).json()['items'][0]['cantidad']==3

def test_same_account_two_phones_submit_shared_cart_once(client,db):
    a,b=headers(client),headers(client)
    cart(client,a,2)
    gate=Barrier(2)
    def compete(h):
        gate.wait(timeout=10)
        return send(client,h,'2.26')
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs=[pool.submit(compete,h) for h in (a,b)]
        results=[j.result(timeout=30) for j in jobs]
    assert sorted(r.status_code for r in results)==[201,409]
    with Session(db) as s:
        assert len(s.exec(select(Pedido)).all())==1
        assert s.get(Producto,1).stock==10

def test_availability_counts_only_preparing_and_ready(client,db):
    with Session(db) as s,s.begin():
        for i,state,student in [(1,'en_preparacion',10),(2,'listo',11),(3,'cancelado',10),(4,'entregado',11)]:
            order=Pedido(numero='COUNT-'+str(i),estudiante_id=student,estado=state,total=Decimal('3.39'))
            s.add(order);s.flush()
            s.add(DetallePedido(pedido_id=order.id,producto_id=1,cantidad=3,precio_unitario=Decimal('1.13')))
    assert client.get('/api/v1/productos/1').json()['stock']==4
    h=headers(client)
    assert cart(client,h,5).status_code==409
    assert cart(client,h,4).status_code==200


def test_cart_holds_stock_and_excludes_own_hold(client,db):
    a,b=headers(client),headers(client,11)
    first=cart(client,a,6).json()
    assert first['id'] and first['servidor_en']
    assert client.get('/api/v1/productos/1').json()['stock']==4
    assert client.get('/api/v1/carrito/',headers=a).json()['items'][0]['producto']['stock']==10
    assert cart(client,a,7).status_code==200
    assert cart(client,b,4).status_code==409
    assert cart(client,b,3).status_code==200
    assert client.get('/api/v1/productos/1').json()['stock']==0
    assert send(client,a,'7.91').status_code==201
    assert client.get('/api/v1/productos/1').json()['stock']==0
    assert client.get('/api/v1/carrito/',headers=b).json()['items'][0]['disponible']
    assert send(client,b,'3.39').status_code==201
    assert client.get('/api/v1/productos/1').json()['stock']==0
    with Session(db) as s:
        assert s.get(Producto,1).stock==10
        assert not s.exec(select(Carrito)).all()


def test_five_minute_deadline_survives_edits_emptying_and_other_phone(client,db):
    a,b=headers(client),headers(client)
    before=utcnow().replace(microsecond=0)
    first=cart(client,a,2).json()
    after=utcnow().replace(microsecond=0)
    with Session(db) as s:
        saved=s.get(Carrito,first['id'])
        assert before+timedelta(minutes=5)<=saved.expira_en<=after+timedelta(minutes=5)
    for h,n in [(a,3),(b,1),(a,0),(b,4)]:
        result=cart(client,h,n)
        assert result.status_code==200,result.text
        assert result.json()['expira_en']==first['expira_en']
        assert result.json()['id']==first['id']
    result=client.delete('/api/v1/carrito/',headers=a).json()
    assert result['items']==[] and result['expira_en']==first['expira_en']
    assert client.get('/api/v1/productos/1').json()['stock']==10
    again=cart(client,b,2).json()
    assert again['expira_en']==first['expira_en'] and again['id']==first['id']


def test_expired_cart_frees_stock_before_cleanup_and_cannot_submit(client,db):
    a,b=headers(client),headers(client,11)
    first=cart(client,a,10).json()
    assert client.get('/api/v1/productos/1').json()['stock']==0
    edit(db,'carritos','expira_en=:t',{'t':utcnow()-timedelta(seconds=1)})
    assert client.get('/api/v1/productos/1').json()['stock']==10
    with Session(db) as s: assert s.get(Carrito,first['id']) is not None
    assert cart(client,b,10).status_code==200
    assert send(client,a,'11.30').status_code==409
    assert send(client,b,'11.30').status_code==201
    with Session(db) as s: assert not s.exec(select(Carrito)).all()


def test_stale_phone_cannot_recreate_or_replace_expired_cart(client,db):
    h=headers(client)
    previous=cart(client,h).json()['id']
    edit(db,'carritos','expira_en=:t',{'t':utcnow()-timedelta(seconds=1)})
    main.cleanup_carts()
    response=client.put('/api/v1/carrito/items/1',headers=h,
                        json={'cantidad':2,'carrito_id':previous})
    assert response.status_code==409
    with Session(db) as s: assert not s.exec(select(Carrito)).all()
    current=cart(client,h,3).json()
    assert current['id']!=previous
    assert client.put('/api/v1/carrito/items/1',headers=h,
                      json={'cantidad':2,'carrito_id':previous}).status_code==409
    assert client.post('/api/v1/pedidos/',headers=h,
                       json={'operacion_id':str(uuid.uuid4()),'total_esperado':'3.39',
                             'carrito_id':previous}).status_code==409
    assert client.get('/api/v1/carrito/',headers=h).json()['items'][0]['cantidad']==3


@pytest.mark.parametrize('operation',['edit','submit'])
def test_deadline_rechecked_after_waiting_for_product_lock(client,db,monkeypatch,operation):
    import commerce
    from routers import carrito as cart_router, pedidos as order_router
    h=headers(client)
    first=cart(client,h,2).json()
    with Session(db) as s: expires=s.get(Carrito,first['id']).expira_en
    module=cart_router if operation=='edit' else order_router
    original=module.locked_products
    def after_wait(*args):
        result=original(*args)
        monkeypatch.setattr(commerce,'utcnow',lambda:expires+timedelta(seconds=1))
        return result
    monkeypatch.setattr(module,'locked_products',after_wait)
    response=cart(client,h,3) if operation=='edit' else send(client,h,'2.26')
    assert response.status_code==409,response.text
    with Session(db) as s:
        assert not s.exec(select(Carrito)).all()
        assert not s.exec(select(DetalleCarrito)).all()
        assert not s.exec(select(Pedido)).all()
        assert s.get(Producto,1).stock==10


def test_new_cart_after_expiry_gets_new_five_minutes_without_reviving_items(client,db):
    h=headers(client)
    first=cart(client,h,6).json()
    edit(db,'carritos','expira_en=:t',{'t':utcnow()-timedelta(seconds=1)})
    fresh=cart(client,h,1)
    assert fresh.status_code==200,fresh.text
    fresh=fresh.json()
    assert fresh['id']!=first['id']
    assert fresh['items'][0]['cantidad']==1
    with Session(db) as s:
        saved=s.get(Carrito,fresh['id'])
        assert saved.expira_en-saved.ultima_actividad<=timedelta(minutes=5)
        assert saved.expira_en>utcnow()+timedelta(minutes=4,seconds=55)
    assert client.get('/api/v1/productos/1').json()['stock']==9
