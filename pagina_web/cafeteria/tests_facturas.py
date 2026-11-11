from datetime import datetime, timezone as dt_timezone
from decimal import Decimal
import uuid

from django.db import connection
from django.test import Client, TransactionTestCase
from django.urls import reverse

from . import tests_cobros, tests_pos
from .models import (Auditoria, Caja, DetallesVenta, MovimientosCaja,
    MovimientosInventario, Productos, Usuarios, Ventas)


class FacturasTests(TransactionTestCase):
    tablas = tests_pos.PuntoVentaTests.tablas
    setUp = tests_pos.PuntoVentaTests.setUp
    tearDown = tests_pos.PuntoVentaTests.tearDown
    abrir = tests_pos.PuntoVentaTests.abrir
    cotizacion = tests_pos.PuntoVentaTests.cotizacion
    vender = tests_pos.PuntoVentaTests.vender
    estudiante = tests_pos.PuntoVentaTests.estudiante
    post = tests_pos.PuntoVentaTests.post
    pedido = tests_cobros.CobrosPedidosTests.pedido

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

    def test_venta_directa_responde_factura_con_detalle_iva_efectivo_y_cambio(self):
        apertura = self.abrir()
        quote = self.cotizacion(apertura, 2)
        resultado = self.post('/pos/venta/', {'cotizacion':quote['cotizacion'],
            'efectivo':'5.00','operacion_id':str(uuid.uuid4())})
        self.assertEqual(resultado.status_code, 200)
        venta = Ventas.objects.get()
        self.assertEqual(resultado.json()['factura_url'], reverse('pos_factura', kwargs={'numero':venta.numero}))
        response = self.client.get(resultado.json()['factura_url'])
        self.assertEqual(response.status_code, 200)
        for texto in ['Cafetería ITCA','Número de generación','Fecha de creación',venta.numero,
                self.cajero.nombre,'Cliente general',self.producto.nombre,'$2.00','$0.26','$2.26','$5.00','$2.74']:
            self.assertContains(response, texto)
        self.assertContains(response, 'factura.js')
        self.assertContains(response, 'data-print-invoice')

    def test_cobro_pedido_identifica_estudiante_y_reintento_devuelve_misma_factura(self):
        pedido, apertura = self.pedido(), self.abrir()
        resumen = self.post(f'/pos/pedidos/{pedido.pk}/resumen/', {'apertura':apertura.pk}).json()
        datos = {'cotizacion':resumen['cotizacion'],'accion':'cobrar','efectivo':'5.00','operacion_id':str(uuid.uuid4())}
        resultado = self.post('/pos/pedidos/atender/', datos)
        self.assertEqual(resultado.status_code, 200)
        url = resultado.json()['factura_url']
        Caja.objects.filter(pk=apertura.pk).update(estado='cerrada')
        repetido = self.post('/pos/pedidos/atender/', datos)
        self.assertEqual(repetido.json()['factura_url'], url)
        self.assertFalse(repetido.json()['creada'])
        self.assertEqual(Ventas.objects.count(), 1)
        response = self.client.get(url, {'formato':'json'})
        self.assertEqual(response.status_code, 200)
        self.assertIn(pedido.estudiante.nombre, response.json()['html'])
        self.assertIn(pedido.numero, response.json()['html'])
        self.assertNotIn('<html', response.json()['html'])

    def test_anular_pedido_no_genera_factura(self):
        pedido, apertura = self.pedido(), self.abrir()
        resumen = self.post(f'/pos/pedidos/{pedido.pk}/resumen/', {'apertura':apertura.pk}).json()
        response = self.post('/pos/pedidos/atender/', {'cotizacion':resumen['cotizacion'],
            'accion':'anular','motivo':'No recogido','operacion_id':str(uuid.uuid4())})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('factura_url', response.json())
        self.assertFalse(Ventas.objects.exists())

    def test_factura_conserva_precios_fecha_local_y_no_modifica_registros_al_reimprimir(self):
        venta, _ = self.vender(self.abrir(), cantidad=2)
        Ventas.objects.filter(pk=venta.pk).update(creada_en=datetime(2026,11,11,2,10,tzinfo=dt_timezone.utc))
        Productos.objects.filter(pk=self.producto.pk).update(precio='9.99')
        url = reverse('pos_factura', kwargs={'numero':venta.numero})
        modelos = [Ventas,DetallesVenta,MovimientosCaja,MovimientosInventario,Auditoria]
        antes = [modelo.objects.count() for modelo in modelos]
        stock = Productos.objects.get(pk=self.producto.pk).stock
        for parametros in [{},{'formato':'json'},{'imprimir':'1'}]:
            response = self.client.get(url, parametros)
            self.assertEqual(response.status_code, 200)
            html = response.json()['html'] if parametros.get('formato') else response.content.decode()
            for texto in ['10/11/2026','20:10','$1.13','$2.26']:
                self.assertIn(texto, html)
            self.assertNotIn('$9.99', html)
            self.assertIn('no-store', response.headers['Cache-Control'])
        self.assertEqual([modelo.objects.count() for modelo in modelos], antes)
        self.assertEqual(Productos.objects.get(pk=self.producto.pk).stock, stock)

    def test_factura_exige_empleado_autenticado_y_no_acepta_post(self):
        venta, _ = self.vender(self.abrir())
        url = reverse('pos_factura', kwargs={'numero':venta.numero})
        self.assertEqual(Client().get(url).status_code, 302)
        self.client.force_login(self.estudiante())
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.cajero)
        self.assertEqual(self.client.post(url).status_code, 405)
        self.assertEqual(self.client.get('/pos/facturas/NO-EXISTE/').status_code, 404)
        Usuarios.objects.filter(pk=self.cajero.pk).update(habilitado=False)
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_datos_de_productos_y_usuarios_se_escapan_en_html(self):
        venta, _ = self.vender(self.abrir())
        Productos.objects.filter(pk=self.producto.pk).update(nombre='<script>alert(1)</script>')
        Usuarios.objects.filter(pk=self.cajero.pk).update(nombre='<img src=x onerror=alert(1)>')
        url = reverse('pos_factura', kwargs={'numero':venta.numero})
        html = self.client.get(url, {'formato':'json'}).json()['html']
        self.assertIn('&lt;script&gt;', html)
        self.assertIn('&lt;img', html)
        self.assertNotIn('<script>', html)
        self.assertNotIn('<img', html)

    def test_venta_gratuita_y_venta_anulada_se_representan_sin_cambiar_cobros(self):
        Productos.objects.filter(pk=self.producto.pk).update(precio=Decimal('0'))
        venta, _ = self.vender(self.abrir(), efectivo='0')
        url = reverse('pos_factura', kwargs={'numero':venta.numero})
        self.assertContains(self.client.get(url), '$0.00')
        Ventas.objects.filter(pk=venta.pk).update(estado='anulada')
        self.assertContains(self.client.get(url), 'Venta anulada')
