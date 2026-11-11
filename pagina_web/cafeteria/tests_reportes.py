from datetime import datetime, timedelta, timezone as utc_timezone
from decimal import Decimal
import uuid

from django.db import connection
from django.test import Client, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from . import tests_pos
from .models import (Auditoria, Caja, Categorias, DetallesPedido, MovimientosCaja,
    MovimientosInventario, Pedidos, Productos, Usuarios, Ventas)


class ReportesTests(TransactionTestCase):
    tablas = tests_pos.PuntoVentaTests.tablas
    setUp = tests_pos.PuntoVentaTests.setUp
    tearDown = tests_pos.PuntoVentaTests.tearDown
    abrir = tests_pos.PuntoVentaTests.abrir
    estudiante = tests_pos.PuntoVentaTests.estudiante
    reservar = tests_pos.PuntoVentaTests.reservar
    vender = tests_pos.PuntoVentaTests.vender
    cotizacion = tests_pos.PuntoVentaTests.cotizacion

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

    def venta(self, apertura, **datos):
        total = datos.pop('total','1.13')
        return Ventas.objects.create(numero='VTA-'+uuid.uuid4().hex[:8], caja=apertura,
            cajero=datos.pop('cajero',self.cajero), total=total, efectivo_recibido='5.00', **datos)

    def pedido(self, estado='en_preparacion', **datos):
        alumno = self.estudiante()
        pedido = Pedidos.objects.create(numero=f'PED-{self.seq:04}', estudiante=alumno,
            estado=estado, total='2.26', **datos)
        DetallesPedido.objects.create(pedido=pedido,producto=self.producto,cantidad=2,precio_unitario='1.13')
        return pedido

    def filas(self, reporte, **filtros):
        response = self.client.get(f'/reportes/{reporte}/', filtros)
        self.assertEqual(response.status_code, 200)
        return response, list(response.context['page_obj'])

    def test_cinco_tarjetas_enlaces_dashboard_y_seccion_activa(self):
        response = self.client.get('/reportes/')
        self.assertEqual(len(response.context['tarjetas_reportes']),5)
        self.assertEqual(response.context['seccion'],'reportes')
        self.assertNotContains(response,'Productos más vendidos')
        for tipo in ['ventas','pedidos','caja','inventario','movimientos']:
            self.assertContains(response,f'/reportes/{tipo}/')
            self.filas(tipo)
        self.client.force_login(self.otro)
        dashboard = self.client.get('/dashboard/')
        self.assertContains(dashboard,'href="/reportes/"')
        self.assertContains(dashboard,'href="/configuracion/"')
        self.assertNotContains(dashboard,'En desarrollo')

    def test_sesion_rol_y_metodos(self):
        self.assertEqual(Client().get('/reportes/').status_code,302)
        self.assertEqual(self.client.post('/reportes/ventas/').status_code,405)
        self.assertEqual(self.client.get('/reportes/desconocido/').status_code,404)
        self.client.force_login(self.estudiante())
        self.assertEqual(self.client.get('/reportes/').status_code,302)

    def test_ventas_rango_inclusivo_local_y_total_sin_anuladas(self):
        apertura = self.abrir()
        antes = self.venta(apertura,creada_en=datetime(2026,11,10,5,59,59,tzinfo=utc_timezone.utc))
        primera = self.venta(apertura,creada_en=datetime(2026,11,10,6,tzinfo=utc_timezone.utc))
        ultima = self.venta(apertura,creada_en=datetime(2026,11,11,5,59,59,999999,tzinfo=utc_timezone.utc))
        despues = self.venta(apertura,creada_en=datetime(2026,11,11,6,tzinfo=utc_timezone.utc))
        anulada = self.venta(apertura,estado='anulada',total='100',creada_en=primera.creada_en)
        response, filas = self.filas('ventas',desde='2026-11-10',hasta='2026-11-10')
        self.assertEqual([v.pk for v in filas],[ultima.pk,anulada.pk,primera.pk])
        self.assertEqual(response.context['total_cobrado'],'2.26')
        self.assertNotContains(response,antes.numero)
        self.assertNotContains(response,despues.numero)

    def test_ventas_filtros_combinados_factura_y_empleado_inhabilitado_historico(self):
        apertura, pedido = self.abrir(), self.pedido(estado='entregado')
        directa = self.venta(apertura)
        cobro = self.venta(apertura,pedido=pedido,cajero=self.otro)
        Usuarios.objects.filter(pk=self.otro.pk).update(habilitado=False)
        response, filas = self.filas('ventas',q=pedido.estudiante.nombre,origen='pedido',responsable=self.otro.nombre,estado='completada')
        self.assertEqual([v.pk for v in filas],[cobro.pk])
        self.assertContains(response,reverse('pos_factura',kwargs={'numero':cobro.numero})+'?imprimir=1')
        self.assertContains(response,'Factura / PDF')
        self.assertNotContains(response,directa.numero)
        _, filas = self.filas('ventas',q='Cliente general',origen='presencial')
        self.assertEqual([v.pk for v in filas],[directa.pk])

    def test_filtros_invalidos_no_fallan_ni_muestran_todo_el_historial(self):
        self.venta(self.abrir())
        casos = [('ventas',{'desde':'no-fecha'}),('ventas',{'desde':'2026-11-11','hasta':'2026-11-10'}),
            ('ventas',{'estado':'falso'}),('ventas',{'origen':'falso'}),('ventas',{'desde':'9999-12-31'}),
            ('inventario',{'categoria':'x'}),('inventario',{'categoria':'9'*200}),
            ('movimientos',{'tipo':'borrar'}),('ventas',{'q':'x'*151})]
        for tipo, filtros in casos:
            with self.subTest(tipo=tipo,filtros=filtros):
                response, filas = self.filas(tipo,**filtros)
                self.assertFalse(response.context['form'].is_valid())
                self.assertEqual(filas,[])
                self.assertContains(response,'role="alert"')

    def test_pedidos_historial_detalle_estados_y_fechas_por_envio(self):
        antiguo = self.pedido(estado='cancelado',creado_en=timezone.now()-timedelta(days=4),motivo_anulacion='No recogido',anulado_por=self.cajero)
        actual = self.pedido(estado='listo')
        response, filas = self.filas('pedidos',estado='cancelado',q=antiguo.numero)
        self.assertEqual([p.pk for p in filas],[antiguo.pk])
        self.assertContains(response,'No recogido')
        self.assertContains(response,self.producto.nombre)
        self.assertContains(response,'2×')
        _, filas = self.filas('pedidos',desde=timezone.localdate().isoformat())
        self.assertEqual([p.pk for p in filas],[actual.pk])

    def test_inventario_calcula_reservas_pedidos_y_carritos_vigentes(self):
        self.reservar(2)
        self.reservar(1,estado='listo')
        self.reservar(3,carrito=True)
        self.reservar(30,carrito=True,vencido=True)
        self.reservar(30,estado='cancelado')
        self.reservar(30,estado='entregado')
        response, filas = self.filas('inventario')
        producto = filas[0]
        self.assertEqual((producto.stock,producto.apartado_reporte,producto.disponible_reporte),(10,6,4))
        self.assertContains(response,'report-state-positive">Sí')
        self.assertNotIn('desde',response.context['form'].fields)
        self.assertNotIn('hasta',response.context['form'].fields)

    def test_inventario_filtra_categoria_y_habilitacion_incluye_inactivos(self):
        categoria = Categorias.objects.create(nombre='Otra',activo=False)
        producto = Productos.objects.create(categoria=categoria,nombre='Otro producto',codigo='OTRO',precio='1',stock=0,fotografia='')
        response, filas = self.filas('inventario',categoria=str(categoria.pk),venta='deshabilitado',estado='agotado')
        self.assertEqual([p.pk for p in filas],[producto.pk])
        self.assertContains(response,'report-state-negative">No')
        _, filas = self.filas('inventario',venta='habilitado')
        self.assertEqual([p.pk for p in filas],[self.producto.pk])
        Productos.objects.filter(pk=self.producto.pk).update(stock_minimo=12)
        _, filas = self.filas('inventario',estado='bajo')
        self.assertEqual([p.pk for p in filas],[self.producto.pk])

    def test_movimientos_incluye_ventas_filtros_signos_y_responsable(self):
        venta, _ = self.vender(self.abrir())
        entrada = MovimientosInventario.objects.create(producto=self.producto,usuario=self.otro,
            tipo='entrada',cantidad=3,motivo='Compra proveedor')
        response, filas = self.filas('movimientos',q='proveedor',tipo='entrada',responsable=self.otro.nombre,categoria=str(self.categoria.pk))
        self.assertEqual([m.pk for m in filas],[entrada.pk])
        self.assertContains(response,'+3')
        response, filas = self.filas('movimientos',tipo='salida_venta')
        self.assertEqual(len(filas),1)
        self.assertContains(response,venta.numero)
        self.assertContains(response,'−1')

    def test_caja_esperado_con_ingresos_retiros_devoluciones_y_cierre(self):
        apertura = self.abrir()
        for tipo,monto in [('ingreso_venta','5'),('ingreso_adicional','2'),('retiro','1'),('devolucion','1')]:
            MovimientosCaja.objects.create(caja=apertura,usuario=self.cajero,tipo=tipo,monto=monto,motivo='Prueba')
        response, filas = self.filas('caja',estado='abierta',responsable=self.cajero.nombre)
        self.assertEqual(filas[0].esperado_reporte,Decimal('15'))
        self.assertEqual(filas[0].ventas_reporte,Decimal('5'))
        self.assertIsNone(filas[0].diferencia_reporte)
        Caja.objects.filter(pk=apertura.pk).update(estado='cerrada',cerrada_por=self.cajero,cerrada_en=timezone.now(),efectivo_esperado='14',efectivo_contado='13.50')
        response, filas = self.filas('caja',estado='cerrada')
        self.assertEqual(filas[0].esperado_reporte,Decimal('14'))
        self.assertEqual(filas[0].diferencia_reporte,Decimal('-0.50'))
        self.assertContains(response,'$-0.50')

    def test_fechas_caja_filtran_apertura_y_movimientos_su_fecha(self):
        apertura = self.abrir()
        Caja.objects.filter(pk=apertura.pk).update(abierta_en=timezone.now()-timedelta(days=3))
        MovimientosInventario.objects.create(producto=self.producto,usuario=self.cajero,tipo='entrada',cantidad=1,
            motivo='Antiguo',creado_en=timezone.now()-timedelta(days=3))
        for tipo in ['caja','movimientos']:
            _, filas = self.filas(tipo,desde=timezone.localdate().isoformat())
            self.assertEqual(filas,[])

    def test_paginacion_conserva_filtros_htmx_y_recupera_pagina_completa(self):
        apertura = self.abrir()
        for _ in range(27):
            self.venta(apertura)
        response = self.client.get('/reportes/ventas/',{'estado':'completada','q':'VTA-'},HTTP_HX_REQUEST='true')
        self.assertEqual(len(response.context['page_obj']),25)
        self.assertNotContains(response,'<html')
        self.assertContains(response,'estado=completada')
        self.assertContains(response,'q=VTA-')
        self.assertContains(response,'page=2')
        response = self.client.get('/reportes/ventas/',{'estado':'completada','page':2},HTTP_HX_REQUEST='true',HTTP_HX_HISTORY_RESTORE_REQUEST='true')
        self.assertContains(response,'<html')
        self.assertEqual(len(response.context['page_obj']),2)

    def test_consulta_y_factura_no_registran_operaciones_nuevas(self):
        venta, _ = self.vender(self.abrir())
        modelos = self.tablas
        antes = [m.objects.count() for m in modelos]
        for tipo in ['ventas','pedidos','caja','inventario','movimientos']:
            self.filas(tipo)
        self.client.get(reverse('pos_factura',kwargs={'numero':venta.numero}))
        self.assertEqual([m.objects.count() for m in modelos],antes)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock,9)
