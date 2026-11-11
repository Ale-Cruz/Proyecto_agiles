from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
import uuid
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, connection
from django.test import Client, TransactionTestCase
from django.utils import timezone

from . import tests_pos
from .cobros_pedidos import procesar_pedido, resumen_pedido
from .models import (Auditoria, Caja, Carritos, DetallesCarrito, DetallesPedido,
    DetallesVenta, MovimientosCaja, MovimientosInventario, Pedidos, Productos, Usuarios, Ventas)
from .pedidos import PedidoNoActualizable, cambiar_estado_pedido
from .pos import cantidades_apartadas, resumen_apertura


class CobrosPedidosTests(TransactionTestCase):
    tablas = tests_pos.PuntoVentaTests.tablas
    setUp = tests_pos.PuntoVentaTests.setUp
    tearDown = tests_pos.PuntoVentaTests.tearDown
    abrir = tests_pos.PuntoVentaTests.abrir
    estudiante = tests_pos.PuntoVentaTests.estudiante
    reservar = tests_pos.PuntoVentaTests.reservar
    post = tests_pos.PuntoVentaTests.post

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with connection.schema_editor() as editor:
            for modelo in cls.tablas:
                editor.create_model(modelo)
        cls.hash_prueba = '!'

    @classmethod
    def tearDownClass(cls):
        with connection.schema_editor() as editor:
            for modelo in reversed(cls.tablas):
                editor.delete_model(modelo)
        super().tearDownClass()

    def pedido(self, cantidad=2, **datos):
        alumno = self.estudiante()
        pedido = Pedidos.objects.create(estudiante=alumno, numero=f'PED-T{self.seq:03}',
            estado=datos.pop('estado', 'listo'), total=Decimal('1.13')*cantidad, **datos)
        DetallesPedido.objects.create(pedido=pedido, producto=self.producto,
            cantidad=cantidad, precio_unitario='1.13')
        return pedido

    def resumen(self, pedido, apertura):
        return resumen_pedido(usuario=self.cajero, apertura_id=apertura.pk, pedido_id=pedido.pk)

    def procesar(self, resumen, **datos):
        parametros = {'usuario':self.cajero, 'cotizacion':resumen['cotizacion'],
            'operacion_id':uuid.uuid4(), 'accion':'cobrar', 'efectivo':'5.00'}
        parametros.update(datos)
        return procesar_pedido(**parametros)

    def test_cobro_guarda_precio_original_impuesto_cambio_y_todos_los_movimientos(self):
        pedido, apertura = self.pedido(), self.abrir()
        resumen = self.resumen(pedido, apertura)
        self.assertEqual((resumen['subtotal'],resumen['iva'],resumen['total']), ('2.00','0.26','2.26'))
        resultado = self.procesar(resumen)
        pedido.refresh_from_db()
        self.producto.refresh_from_db()
        venta = Ventas.objects.get()
        self.assertEqual((pedido.estado, venta.pedido_id, venta.caja_id, venta.cajero_id),
            ('entregado', pedido.pk, apertura.pk, self.cajero.pk))
        self.assertEqual(resultado['cambio'], '2.74')
        self.assertEqual(self.producto.stock, 8)
        self.assertEqual(DetallesVenta.objects.get().precio_unitario, Decimal('1.13'))
        self.assertEqual(MovimientosInventario.objects.get().cantidad, 2)
        self.assertEqual(MovimientosInventario.objects.get().tipo, 'salida_venta')
        self.assertEqual(MovimientosCaja.objects.get().monto, Decimal('2.26'))
        self.assertEqual(resumen_apertura(apertura)['esperado'], '12.26')
        self.assertEqual(Auditoria.objects.filter(modulo='Pedidos', accion='Editado').count(), 1)

    def test_precio_del_catalogo_y_deshabilitacion_no_alteran_pedido_aceptado(self):
        pedido, apertura = self.pedido(), self.abrir()
        resumen = self.resumen(pedido, apertura)
        Productos.objects.filter(pk=self.producto.pk).update(precio='9.99', activo=False, disponible_para_venta=False)
        self.categoria.activo = False
        self.categoria.save(update_fields=['activo'])
        self.procesar(resumen)
        self.assertEqual(Ventas.objects.get().total, Decimal('2.26'))
        self.assertEqual(DetallesVenta.objects.get().precio_unitario, Decimal('1.13'))

    def test_reserva_propia_no_se_cuenta_dos_veces(self):
        pedido, apertura = self.pedido(cantidad=10), self.abrir()
        self.assertEqual(cantidades_apartadas([self.producto.pk])[self.producto.pk], 10)
        self.procesar(self.resumen(pedido, apertura), efectivo='20')
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 0)

    def test_cobro_respeta_otros_pedidos_y_carritos_activos(self):
        pedido, apertura = self.pedido(cantidad=4), self.abrir()
        self.reservar(4)
        self.reservar(3, carrito=True)
        with self.assertRaises(ValidationError): self.procesar(self.resumen(pedido, apertura))
        self.assertFalse(Ventas.objects.exists())
        Carritos.objects.update(expira_en=timezone.now()-timedelta(seconds=1))
        self.procesar(self.resumen(pedido, apertura))
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 6)

    def test_efectivo_insuficiente_y_falta_stock_no_dejan_registros_parciales(self):
        pedido, apertura = self.pedido(), self.abrir()
        resumen = self.resumen(pedido, apertura)
        with self.assertRaises(ValidationError): self.procesar(resumen, efectivo='1')
        Productos.objects.filter(pk=self.producto.pk).update(stock=1)
        with self.assertRaises(ValidationError): self.procesar(resumen)
        pedido.refresh_from_db()
        self.assertEqual(pedido.estado, 'listo')
        self.assertFalse(Ventas.objects.exists())
        self.assertFalse(MovimientosInventario.objects.exists())
        self.assertFalse(MovimientosCaja.objects.exists())

    def test_reintento_cobro_no_duplica_incluso_con_caja_cerrada_y_resumen_vencido(self):
        pedido, apertura = self.pedido(), self.abrir()
        resumen, operacion = self.resumen(pedido, apertura), uuid.uuid4()
        self.assertTrue(self.procesar(resumen, operacion_id=operacion)['creada'])
        Caja.objects.filter(pk=apertura.pk).update(estado='cerrada')
        with patch('django.core.signing.time.time', return_value=timezone.now().timestamp()+600):
            self.assertFalse(self.procesar(resumen, operacion_id=operacion)['creada'])
        self.assertEqual(Ventas.objects.count(), 1)
        self.assertEqual(MovimientosInventario.objects.count(), 1)
        self.assertEqual(MovimientosCaja.objects.count(), 1)
        with self.assertRaises(ValidationError): self.procesar(resumen, operacion_id=operacion, efectivo='6')
        with self.assertRaises(ValidationError): self.procesar(resumen)

    def test_anulacion_exige_motivo_libera_reserva_y_no_mueve_dinero_ni_stock(self):
        pedido, apertura = self.pedido(), self.abrir()
        resumen = self.resumen(pedido, apertura)
        for motivo in [None, '', '   ', 'x'*1001]:
            with self.assertRaises(ValidationError): self.procesar(resumen, accion='anular', motivo=motivo)
        resultado = self.procesar(resumen, accion='anular', motivo='No vino a recogerlo', efectivo=None)
        pedido.refresh_from_db()
        self.assertEqual(resultado['accion'], 'anular')
        self.assertEqual((pedido.estado,pedido.anulado_por_id,pedido.motivo_anulacion),
            ('cancelado',self.cajero.pk,'No vino a recogerlo'))
        self.assertIsNotNone(pedido.anulado_en)
        self.assertEqual(cantidades_apartadas([self.producto.pk]).get(self.producto.pk, 0), 0)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 10)
        self.assertEqual(DetallesPedido.objects.filter(pedido=pedido).count(), 1)
        self.assertFalse(Ventas.objects.exists())
        self.assertFalse(MovimientosCaja.objects.exists())
        self.assertFalse(MovimientosInventario.objects.exists())

    def test_reintento_anulacion_es_idempotente_sin_reutilizar_id_de_api_movil(self):
        origen = uuid.uuid4()
        pedido, apertura = self.pedido(operacion_id=origen), self.abrir()
        resumen, operacion = self.resumen(pedido, apertura), uuid.uuid4()
        self.procesar(resumen, accion='anular', motivo='No recogido', operacion_id=operacion)
        pedido.refresh_from_db()
        anulado_en = pedido.anulado_en
        Caja.objects.filter(pk=apertura.pk).update(estado='cerrada')
        self.assertFalse(self.procesar(resumen, accion='anular', motivo='No recogido', operacion_id=operacion)['creada'])
        pedido.refresh_from_db()
        self.assertEqual((pedido.operacion_id,pedido.anulado_en), (origen,anulado_en))
        self.assertEqual(Auditoria.objects.filter(modulo='Pedidos').count(), 1)
        with self.assertRaises(ValidationError): self.procesar(resumen, accion='anular', motivo='Otro', operacion_id=operacion)
        with self.assertRaises(ValidationError): self.procesar(resumen, operacion_id=operacion)

    def test_otra_operacion_no_puede_cobrar_ni_anular_un_pedido_atendido(self):
        pedido, apertura = self.pedido(), self.abrir()
        resumen = self.resumen(pedido, apertura)
        self.procesar(resumen)
        for accion in ['cobrar','anular']:
            with self.assertRaises(ValidationError): self.procesar(resumen, accion=accion, motivo='Tarde')
        self.assertEqual(Ventas.objects.count(), 1)

    def test_cambio_desde_cocina_invalida_resumen_y_reinicia_reloj_al_marcar_listo(self):
        pedido, apertura = self.pedido(estado_actualizado_en=timezone.now()-timedelta(minutes=40)), self.abrir()
        resumen = self.resumen(pedido, apertura)
        cambiar_estado_pedido(usuario=self.otro,pedido_id=pedido.pk,destino='en_preparacion',version=pedido.estado_actualizado_en.isoformat())
        pedido.refresh_from_db()
        cambiar_estado_pedido(usuario=self.otro,pedido_id=pedido.pk,destino='listo',version=pedido.estado_actualizado_en.isoformat())
        with self.assertRaises(ValidationError): self.procesar(resumen)
        nuevo = self.resumen(pedido, apertura)
        self.assertEqual(nuevo['minutos_espera'], 0)
        self.procesar(nuevo)
        pedido.refresh_from_db()
        with self.assertRaises(PedidoNoActualizable):
            cambiar_estado_pedido(usuario=self.otro,pedido_id=pedido.pk,destino='en_preparacion',version=pedido.estado_actualizado_en.isoformat())

    def test_preparacion_cancelados_entregados_no_se_pueden_cobrar(self):
        apertura = self.abrir()
        for estado in ['en_preparacion','cancelado','entregado']:
            with self.assertRaises(ValidationError): self.resumen(self.pedido(estado=estado), apertura)

    def test_resumen_vencido_firma_modificada_y_detalle_modificado_se_rechazan(self):
        pedido, apertura = self.pedido(), self.abrir()
        resumen = self.resumen(pedido, apertura)
        with patch('django.core.signing.time.time', return_value=timezone.now().timestamp()+600):
            with self.assertRaises(ValidationError): self.procesar(resumen)
        with self.assertRaises(ValidationError): self.procesar({**resumen,'cotizacion':resumen['cotizacion']+'x'})
        DetallesPedido.objects.filter(pedido=pedido).update(precio_unitario='2.26', cantidad=1)
        with self.assertRaises(ValidationError): self.procesar(resumen)
        self.assertFalse(Ventas.objects.exists())

    def test_total_incoherente_se_puede_anular_pero_no_cobrar(self):
        pedido, apertura = self.pedido(), self.abrir()
        Pedidos.objects.filter(pk=pedido.pk).update(total='99')
        resumen = self.resumen(pedido, apertura)
        self.assertFalse(resumen['cobrable'])
        with self.assertRaises(ValidationError): self.procesar(resumen, efectivo='100')
        self.procesar(resumen, accion='anular', motivo='Detalle incorrecto')

    def test_fallo_de_registro_revierte_venta_stock_estado_y_efectivo(self):
        pedido, apertura = self.pedido(), self.abrir()
        resumen = self.resumen(pedido, apertura)
        with patch('cafeteria.cobros_pedidos.registrar_evento', side_effect=RuntimeError('fallo simulado')):
            with self.assertRaises(RuntimeError): self.procesar(resumen)
        pedido.refresh_from_db()
        self.producto.refresh_from_db()
        self.assertEqual((pedido.estado,self.producto.stock), ('listo',10))
        for modelo in [Ventas,DetallesVenta,MovimientosCaja,MovimientosInventario]:
            self.assertFalse(modelo.objects.exists())

    def test_otros_empleados_y_estudiantes_no_operan_apertura(self):
        pedido, apertura = self.pedido(), self.abrir()
        resumen = self.resumen(pedido, apertura)
        for actor in [self.otro, pedido.estudiante]:
            with self.assertRaises(PermissionDenied): self.procesar(resumen, usuario=actor)
            with self.assertRaises(PermissionDenied): resumen_pedido(usuario=actor,apertura_id=apertura.pk,pedido_id=pedido.pk)

    def test_panel_solo_listos_ordenado_y_separado_por_hora_de_listo(self):
        ahora = timezone.now()
        reciente = self.pedido(creado_en=ahora-timedelta(days=1),estado_actualizado_en=ahora-timedelta(minutes=1))
        veinte = self.pedido(estado_actualizado_en=ahora-timedelta(minutes=20))
        viejo = self.pedido(estado_actualizado_en=ahora-timedelta(minutes=30))
        preparacion = self.pedido(estado='en_preparacion')
        apertura = self.abrir()
        response = self.client.get('/pos/pedidos/', {'apertura':apertura.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([p.pk for p in response.context['pedidos_recientes']], [reciente.pk])
        self.assertEqual([p.pk for p in response.context['pedidos_demorados']], [viejo.pk,veinte.pk])
        self.assertNotContains(response, preparacion.numero)
        self.assertContains(response, self.producto.nombre)
        self.assertContains(response, '20 minutos')
        filtrado = self.client.get('/pos/pedidos/', {'apertura':apertura.pk,'q':viejo.numero})
        self.assertContains(filtrado, viejo.numero)
        self.assertNotContains(filtrado, reciente.numero)
        nombre = self.client.get('/pos/pedidos/', {'apertura':apertura.pk,'q':reciente.estudiante.nombre})
        self.assertEqual([p.pk for p in nombre.context['pedidos_recientes']], [reciente.pk])
        self.client.force_login(self.otro)
        self.assertNotContains(self.client.get('/pos/pedidos/', {'apertura':apertura.pk}), viejo.numero)

    def test_http_cobro_anulacion_metodos_sesion_csrf_y_pantalla(self):
        apertura, pedido = self.abrir(), self.pedido()
        pantalla = self.client.get('/pos/')
        for selector in ['id="pos-tab-orders"','id="pickup-dialog"','id="pos-sale-pane"']:
            self.assertContains(pantalla, selector)
        url = f'/pos/pedidos/{pedido.pk}/resumen/'
        respuesta = self.post(url, {'apertura':apertura.pk})
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(Client().get('/pos/pedidos/').status_code, 302)
        seguro = Client(enforce_csrf_checks=True)
        seguro.force_login(self.cajero)
        self.assertEqual(self.post('/pos/pedidos/atender/', {}, cliente=seguro).status_code, 403)
        self.assertEqual(self.post(url, {'apertura':True}).status_code, 409)
        cobro = self.post('/pos/pedidos/atender/', {'cotizacion':respuesta.json()['cotizacion'],
            'accion':'cobrar','operacion_id':str(uuid.uuid4()),'efectivo':'5.00'})
        self.assertEqual(cobro.status_code, 200)
        self.assertEqual(cobro.json()['cambio'], '2.74')
        segundo = self.pedido()
        quote = self.post(f'/pos/pedidos/{segundo.pk}/resumen/', {'apertura':apertura.pk}).json()
        anular = self.post('/pos/pedidos/atender/', {'cotizacion':quote['cotizacion'],
            'accion':'anular','operacion_id':str(uuid.uuid4()),'motivo':'No vino'})
        self.assertEqual(anular.status_code, 200)
        self.assertEqual(anular.json()['accion'], 'anular')

    def test_dos_cobros_simultaneos_del_mismo_pedido_registran_una_venta(self):
        if connection.vendor != 'mysql': self.skipTest('Requiere MySQL.')
        pedido, apertura = self.pedido(), self.abrir()
        resumen = self.resumen(pedido, apertura)
        def atender(_):
            close_old_connections()
            try:
                self.procesar(resumen)
                return 'ok'
            except ValidationError: return 'atendido'
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            resultados = list(pool.map(atender, range(2)))
        self.assertCountEqual(resultados, ['ok','atendido'])
        self.assertEqual(Ventas.objects.count(), 1)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 8)

    def test_cobro_y_anulacion_simultaneos_solo_aplican_una_transicion(self):
        pedido, apertura = self.pedido(), self.abrir()
        resumen = self.resumen(pedido, apertura)
        def atender(accion):
            close_old_connections()
            try:
                self.procesar(resumen, accion=accion, motivo='No vino')
                return accion
            except ValidationError: return 'atendido'
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            resultados = list(pool.map(atender, ['cobrar','anular']))
        self.assertEqual(resultados.count('atendido'), 1)
        pedido.refresh_from_db()
        self.producto.refresh_from_db()
        cobrado = pedido.estado == 'entregado'
        self.assertEqual(Ventas.objects.count(), int(cobrado))
        self.assertEqual(self.producto.stock, 8 if cobrado else 10)

    def test_cocina_y_caja_simultaneos_no_dejan_pedido_cobrado_en_preparacion(self):
        pedido, apertura = self.pedido(), self.abrir()
        resumen = self.resumen(pedido, apertura)
        def atender(tarea):
            close_old_connections()
            try:
                if tarea == 'caja':
                    self.procesar(resumen)
                else:
                    cambiar_estado_pedido(usuario=self.otro,pedido_id=pedido.pk,
                        destino='en_preparacion',version=pedido.estado_actualizado_en.isoformat())
                return tarea
            except (ValidationError, PedidoNoActualizable): return 'atendido'
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            resultados = list(pool.map(atender, ['caja','cocina']))
        self.assertEqual(resultados.count('atendido'), 1)
        pedido.refresh_from_db()
        self.producto.refresh_from_db()
        cobrado = pedido.estado == 'entregado'
        self.assertEqual(pedido.estado, 'entregado' if cobrado else 'en_preparacion')
        self.assertEqual(Ventas.objects.count(), int(cobrado))
        self.assertEqual(self.producto.stock, 8 if cobrado else 10)
