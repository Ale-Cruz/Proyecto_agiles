from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
import json
import time
import uuid
from unittest.mock import patch

import bcrypt
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, connection, IntegrityError, transaction
from django.test import Client, TransactionTestCase
from django.utils import timezone

from .models import (Auditoria, Caja, Carritos, Categorias, DetallesCarrito, DetallesPedido,
    DetallesVenta, MovimientosCaja, MovimientosInventario, Pedidos, Productos, Usuarios, Ventas)
from .pos import (abrir_caja, autorizar_cierre, cerrar_caja, cotizar, dinero,
    realizar_venta, resumen_apertura, ResumenCambio, token_apertura)


class PuntoVentaTests(TransactionTestCase):
    tablas = [Usuarios, Auditoria, Categorias, Productos, Carritos, DetallesCarrito,
        Pedidos, DetallesPedido, Caja, Ventas, DetallesVenta, MovimientosCaja, MovimientosInventario]

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with connection.schema_editor() as editor:
            for modelo in cls.tablas:
                editor.create_model(modelo)
        cls.clave = 'Temporal!2026'
        cls.hash_prueba = bcrypt.hashpw(cls.clave.encode(), bcrypt.gensalt(rounds=4)).decode()

    @classmethod
    def tearDownClass(cls):
        with connection.schema_editor() as editor:
            for modelo in reversed(cls.tablas):
                editor.delete_model(modelo)
        super().tearDownClass()

    def setUp(self):
        self.cajero = Usuarios.objects.create(nombre='miguel', correo='miguel@test.local', password=self.hash_prueba, rol='cajero')
        self.otro = Usuarios.objects.create(nombre='ana', correo='ana@test.local', password=self.hash_prueba, rol='administrador')
        self.categoria = Categorias.objects.create(nombre='Panes')
        self.producto = Productos.objects.create(categoria=self.categoria,nombre='Pan',codigo='P1',precio='1.13',stock=10,fotografia='')
        self.seq = 0
        self.client.force_login(self.cajero)

    def tearDown(self):
        for modelo in reversed(self.tablas):
            modelo.objects.all().delete()

    def abrir(self, usuario=None, monto='10.00'):
        usuario = usuario or self.cajero
        return abrir_caja(usuario=usuario,monto=monto,token=token_apertura(usuario))

    def cotizacion(self, apertura, cantidad=1, usuario=None, producto=None):
        return cotizar(usuario=usuario or self.cajero,apertura_id=apertura.pk,
            items=[{'id':(producto or self.producto).pk,'cantidad':cantidad}])

    def vender(self, apertura, cantidad=1, efectivo='5.00', cotizacion=None, operacion=None):
        quote = cotizacion or self.cotizacion(apertura,cantidad)
        return realizar_venta(usuario=self.cajero,cotizacion=quote['cotizacion'],efectivo=efectivo,operacion_id=operacion or uuid.uuid4())

    def estudiante(self):
        self.seq += 1
        return Usuarios.objects.create(nombre=f'Estudiante {self.seq}',correo=f'e{self.seq}@itca.edu.sv',password='!',rol='estudiante')

    def reservar(self, cantidad, *, estado='en_preparacion', carrito=False, vencido=False):
        alumno = self.estudiante()
        if carrito:
            cart = Carritos.objects.create(usuario=alumno,expira_en=timezone.now()+timedelta(minutes=-1 if vencido else 5))
            DetallesCarrito.objects.create(carrito=cart,producto=self.producto,cantidad=cantidad)
        else:
            pedido = Pedidos.objects.create(estudiante=alumno,numero=f'PED-{self.seq}',estado=estado)
            DetallesPedido.objects.create(pedido=pedido,producto=self.producto,cantidad=cantidad,precio_unitario='1.13')

    def post(self, url, datos, cliente=None):
        return (cliente or self.client).post(url,json.dumps(datos),content_type='application/json',HTTP_HX_REQUEST='true')

    def test_entrada_exige_apertura_y_no_muestra_el_pos(self):
        response = self.client.get('/pos/')
        self.assertContains(response,'pos-opening-form')
        self.assertNotContains(response,'id="pos-app"')
        apertura = self.abrir(self.otro)
        self.assertContains(self.client.get('/pos/'),'Caja en uso')
        self.assertNotContains(self.client.get('/pos/'),'pos-opening-form')

    def test_apertura_guarda_responsable_monto_fecha_y_auditoria(self):
        apertura = self.abrir(monto='15.25')
        self.assertEqual(apertura.abierta_por_id,self.cajero.pk)
        self.assertEqual(apertura.monto_inicial,Decimal('15.25'))
        self.assertEqual(apertura.estado,'abierta')
        self.assertIsNotNone(apertura.abierta_en)
        self.assertFalse(MovimientosCaja.objects.exists())
        self.assertEqual(Auditoria.objects.get().modulo,'Caja')
        self.assertContains(self.client.get('/pos/'),'id="pos-app"')

    def test_una_sola_apertura_y_reintento_no_cambia_monto(self):
        primera = self.abrir()
        self.assertEqual(self.abrir(monto='999').pk,primera.pk)
        with self.assertRaises(ValidationError): self.abrir(self.otro)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Caja.objects.create(abierta_por=self.otro,observaciones='')
        primera.refresh_from_db()
        self.assertEqual(primera.monto_inicial,Decimal('10.00'))
        self.assertEqual(Caja.objects.count(),1)

    def test_apertura_rechaza_montos_invalidos_y_token_ajeno(self):
        for monto in ('-1','NaN','1.001',True):
            with self.assertRaises(ValidationError): self.abrir(monto=monto)
        with self.assertRaises(PermissionDenied):
            abrir_caja(usuario=self.cajero,monto='0',token=token_apertura(self.otro))
        self.assertFalse(Caja.objects.exists())

    def test_reservas_de_pedidos_y_carritos_vigentes_reducen_disponible(self):
        apertura = self.abrir()
        self.reservar(2)
        self.reservar(3,estado='listo')
        self.reservar(9,estado='entregado')
        self.reservar(9,estado='cancelado')
        self.reservar(1,carrito=True)
        self.reservar(9,carrito=True,vencido=True)
        response = self.client.get('/pos/productos/',{'apertura':apertura.pk,'q':'Pan'})
        self.assertEqual(response.json()['productos'][0]['disponible'],4)
        self.assertEqual(self.cotizacion(apertura,4)['total'],'4.52')
        with self.assertRaises(ValidationError): self.cotizacion(apertura,5)

    def test_busqueda_por_codigo_y_excluye_inactivos(self):
        apertura = self.abrir()
        self.assertEqual(len(self.client.get('/pos/productos/',{'apertura':apertura.pk,'q':'P1'}).json()['productos']),1)
        self.producto.disponible_para_venta = False
        self.producto.save(update_fields=['disponible_para_venta'])
        self.assertEqual(self.client.get('/pos/productos/',{'apertura':apertura.pk}).json()['productos'],[])

    def test_iva_esta_incluido_y_no_se_suma_de_nuevo(self):
        quote = self.cotizacion(self.abrir(),2)
        self.assertEqual((quote['subtotal'],quote['iva'],quote['total']),('2.00','0.26','2.26'))

    def test_venta_registra_todo_y_caja_solo_recibe_total_neto_del_cambio(self):
        apertura = self.abrir()
        venta, creada = self.vender(apertura,2,efectivo='5.00')
        self.assertTrue(creada)
        self.assertEqual(venta.total,Decimal('2.26'))
        self.assertEqual(venta.efectivo_recibido,Decimal('5.00'))
        self.assertIsNone(venta.pedido_id)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock,8)
        detalle = DetallesVenta.objects.get()
        movimiento = MovimientosInventario.objects.get()
        self.assertEqual((detalle.cantidad,movimiento.cantidad,movimiento.tipo),(2,2,'salida_venta'))
        self.assertEqual(movimiento.detalle_venta_id,detalle.pk)
        self.assertEqual(MovimientosCaja.objects.get().monto,Decimal('2.26'))
        self.assertEqual(resumen_apertura(apertura)['esperado'],'12.26')
        self.assertEqual(Auditoria.objects.filter(modulo='Ventas').count(),1)

    def test_efectivo_insuficiente_y_cotizacion_alterada_no_registran(self):
        apertura = self.abrir()
        quote = self.cotizacion(apertura)
        with self.assertRaises(ValidationError): self.vender(apertura,efectivo='1.00',cotizacion=quote)
        quote['cotizacion'] += 'x'
        with self.assertRaises(ValidationError): self.vender(apertura,cotizacion=quote)
        self.assertFalse(Ventas.objects.exists())
        self.assertFalse(MovimientosInventario.objects.exists())

    def test_cambios_de_precio_stock_y_reservas_se_revalidan_al_cobrar(self):
        apertura = self.abrir()
        quote = self.cotizacion(apertura,5)
        self.reservar(6)
        with self.assertRaises(ValidationError): self.vender(apertura,cotizacion=quote,efectivo='20')
        Pedidos.objects.all().update(estado='cancelado')
        self.producto.precio = Decimal('2.00')
        self.producto.save(update_fields=['precio'])
        with self.assertRaises(ValidationError): self.vender(apertura,cotizacion=quote,efectivo='20')
        self.assertFalse(Ventas.objects.exists())

    def test_producto_o_categoria_desactivados_impiden_cobro(self):
        apertura = self.abrir()
        quote = self.cotizacion(apertura)
        self.categoria.activo = False
        self.categoria.save(update_fields=['activo'])
        with self.assertRaises(ValidationError): self.vender(apertura,cotizacion=quote)

    def test_reintento_no_duplica_venta_stock_ni_movimientos(self):
        apertura = self.abrir()
        quote, operacion = self.cotizacion(apertura,2), uuid.uuid4()
        primera, _ = self.vender(apertura,cotizacion=quote,operacion=operacion)
        segunda, creada = self.vender(apertura,cotizacion=quote,operacion=operacion)
        self.assertEqual(primera.pk,segunda.pk)
        self.assertFalse(creada)
        self.assertEqual(Ventas.objects.count(),1)
        self.assertEqual(MovimientosCaja.objects.count(),1)
        self.assertEqual(MovimientosInventario.objects.count(),1)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock,8)
        with self.assertRaises(ValidationError): self.vender(apertura,cotizacion=quote,operacion=operacion,efectivo='6.00')

    def test_fallo_de_auditoria_revierte_venta_y_todos_sus_movimientos(self):
        apertura = self.abrir()
        with patch('cafeteria.pos.registrar_evento',side_effect=RuntimeError('fallo')):
            with self.assertRaises(RuntimeError): self.vender(apertura)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock,10)
        for modelo in (Ventas,DetallesVenta,MovimientosCaja,MovimientosInventario):
            self.assertEqual(modelo.objects.count(),0)

    def test_cotizacion_vencida_no_cobra(self):
        apertura = self.abrir()
        with patch('django.core.signing.time.time',return_value=time.time()-400):
            quote = self.cotizacion(apertura)
        with self.assertRaises(ValidationError): self.vender(apertura,cotizacion=quote)

    def test_cantidades_invalidas_o_productos_duplicados_se_rechazan(self):
        apertura = self.abrir()
        for items in ([],[{'id':self.producto.pk,'cantidad':True}],[{'id':self.producto.pk,'cantidad':-1}],
                      [{'id':self.producto.pk,'cantidad':1}]*2):
            with self.assertRaises(ValidationError): cotizar(usuario=self.cajero,apertura_id=apertura.pk,items=items)

    def test_venta_gratuita_no_crea_ingreso_de_efectivo(self):
        self.producto.precio = Decimal('0')
        self.producto.save(update_fields=['precio'])
        venta, _ = self.vender(self.abrir(),efectivo='0')
        self.assertEqual(venta.total,0)
        self.assertFalse(MovimientosCaja.objects.exists())
        self.assertEqual(MovimientosInventario.objects.count(),1)

    def test_otro_empleado_no_puede_operar_esta_apertura(self):
        apertura = self.abrir()
        with self.assertRaises(PermissionDenied): self.cotizacion(apertura,usuario=self.otro)
        quote = self.cotizacion(apertura)
        with self.assertRaises(PermissionDenied):
            realizar_venta(usuario=self.otro,cotizacion=quote['cotizacion'],efectivo='5',operacion_id=uuid.uuid4())

    def test_cierre_exige_reautenticacion_y_misma_sesion(self):
        apertura = self.abrir()
        response = self.post('/pos/cierre/verificar/',{'apertura':apertura.pk,'usuario':self.cajero.nombre,'password':'mala'})
        self.assertEqual(response.status_code,400)
        self.assertNotIn('resumen',response.json())
        proof = autorizar_cierre(self.cajero,apertura,'sesion-a')
        with self.assertRaises(PermissionDenied):
            cerrar_caja(usuario=self.cajero,autorizacion=proof,sesion='sesion-b',contado='10',esperado='10')
        with self.assertRaises(ValidationError):
            cerrar_caja(usuario=self.cajero,autorizacion='falsa',sesion='sesion-a',contado='10',esperado='10')

    def test_cierre_por_http_guarda_conteo_diferencia_y_libera_caja(self):
        apertura = self.abrir()
        self.vender(apertura,2)
        verificacion = self.post('/pos/cierre/verificar/',{'apertura':apertura.pk,'usuario':self.cajero.nombre,'password':self.clave})
        self.assertEqual(verificacion.status_code,200)
        self.assertEqual(verificacion.json()['resumen']['esperado'],'12.26')
        datos = {'autorizacion':verificacion.json()['autorizacion'],'contado':'12.00','esperado':'12.26'}
        cierre = self.post('/pos/cierre/',datos)
        self.assertEqual(cierre.status_code,200)
        self.assertEqual(cierre.json()['diferencia'],'-0.26')
        apertura.refresh_from_db()
        self.assertEqual((apertura.estado,apertura.cerrada_por_id),('cerrada',self.cajero.pk))
        self.assertEqual(apertura.efectivo_contado,Decimal('12.00'))
        self.assertIsNotNone(apertura.cerrada_en)
        self.assertEqual(self.post('/pos/cierre/',datos).status_code,200)
        self.assertEqual(Auditoria.objects.filter(modulo='Caja',accion='Editado').count(),1)
        self.assertEqual(self.abrir(self.otro).estado,'abierta')

    def test_credenciales_de_otro_usuario_no_autorizan_cierre(self):
        apertura = self.abrir()
        response = self.post('/pos/cierre/verificar/',{'apertura':apertura.pk,'usuario':self.otro.nombre,'password':self.clave})
        self.assertEqual(response.status_code,400)

    def test_limite_de_intentos_de_reautenticacion(self):
        apertura = self.abrir()
        for _ in range(5):
            self.post('/pos/cierre/verificar/',{'apertura':apertura.pk,'usuario':self.cajero.nombre,'password':'mala'})
        response = self.post('/pos/cierre/verificar/',{'apertura':apertura.pk,'usuario':self.cajero.nombre,'password':self.clave})
        self.assertEqual(response.status_code,429)

    def test_movimientos_nuevos_exigen_revisar_conteo(self):
        apertura = self.abrir()
        proof = autorizar_cierre(self.cajero,apertura,'s')
        self.vender(apertura)
        with self.assertRaises(ResumenCambio): cerrar_caja(usuario=self.cajero,autorizacion=proof,sesion='s',contado='10',esperado='10')
        apertura.refresh_from_db()
        self.assertEqual(apertura.estado,'abierta')

    def test_password_modificado_invalida_autorizacion_de_cierre(self):
        apertura = self.abrir()
        proof = autorizar_cierre(self.cajero,apertura,'s')
        Usuarios.objects.filter(pk=self.cajero.pk).update(password='!')
        with self.assertRaises(PermissionDenied): cerrar_caja(usuario=self.cajero,autorizacion=proof,sesion='s',contado='10',esperado='10')

    def test_venta_cerrada_no_acepta_nuevos_cobros_pero_reconoce_reintentos(self):
        apertura = self.abrir()
        quote, op = self.cotizacion(apertura), uuid.uuid4()
        venta, _ = self.vender(apertura,cotizacion=quote,operacion=op)
        apertura.estado = 'cerrada'
        apertura.save(update_fields=['estado'])
        repetida, creada = self.vender(apertura,cotizacion=quote,operacion=op)
        self.assertFalse(creada)
        self.assertEqual(venta.pk,repetida.pk)
        with self.assertRaises(ValidationError): self.vender(apertura,cotizacion=quote)

    def test_api_exige_sesion_post_y_csrf(self):
        self.assertEqual(Client().get('/pos/').status_code,302)
        self.assertEqual(self.client.get('/pos/venta/').status_code,405)
        seguro = Client(enforce_csrf_checks=True)
        seguro.force_login(self.cajero)
        self.assertEqual(self.post('/pos/apertura/',{},cliente=seguro).status_code,403)

    def test_dos_aperturas_simultaneas_solo_crean_una(self):
        if connection.vendor != 'mysql': self.skipTest('Requiere MySQL.')
        tokens = {u.pk:token_apertura(u) for u in (self.cajero,self.otro)}
        def abrir(actor_id):
            close_old_connections()
            try:
                abrir_caja(usuario=Usuarios.objects.get(pk=actor_id),monto='10',token=tokens[actor_id])
                return 'ok'
            except ValidationError: return 'ocupada'
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            resultados = list(pool.map(abrir,[self.cajero.pk,self.otro.pk]))
        self.assertCountEqual(resultados,['ok','ocupada'])
        self.assertEqual(Caja.objects.count(),1)

    def test_ventas_simultaneas_no_sobrevenden(self):
        if connection.vendor != 'mysql': self.skipTest('Requiere MySQL.')
        self.producto.stock = 1
        self.producto.save(update_fields=['stock'])
        apertura = self.abrir()
        quote = self.cotizacion(apertura)
        def cobrar(_):
            close_old_connections()
            try:
                self.vender(apertura,cotizacion=quote)
                return 'ok'
            except ValidationError: return 'agotado'
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            resultados = list(pool.map(cobrar,range(2)))
        self.assertCountEqual(resultados,['ok','agotado'])
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock,0)
        self.assertEqual(Ventas.objects.count(),1)
