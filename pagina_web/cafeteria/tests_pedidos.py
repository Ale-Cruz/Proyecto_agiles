from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import PermissionDenied
from django.db import close_old_connections, connection
from django.test import Client, TransactionTestCase
from django.utils import timezone

from .models import (Auditoria, Caja, Categorias, DetallesPedido, Pedidos,
                     Productos, Usuarios, Ventas)
from .pedidos import PedidoNoActualizable, cambiar_estado_pedido


class PedidosCocinaTests(TransactionTestCase):
    tablas = [Usuarios, Auditoria, Categorias, Productos, Pedidos, DetallesPedido, Caja, Ventas]

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with connection.schema_editor() as editor:
            for modelo in cls.tablas:
                editor.create_model(modelo)

    @classmethod
    def tearDownClass(cls):
        with connection.schema_editor() as editor:
            for modelo in reversed(cls.tablas):
                editor.delete_model(modelo)
        super().tearDownClass()

    def setUp(self):
        self.admin = Usuarios.objects.create(nombre='admin', correo='admin@test.local', password='!', rol='administrador')
        self.cajero = Usuarios.objects.create(nombre='cajero', correo='cajero@test.local', password='!', rol='cajero')
        self.categoria = Categorias.objects.create(nombre='Prueba')
        self.producto = Productos.objects.create(categoria=self.categoria, nombre='Pan de queso', codigo='PAN', precio='1.13', fotografia='', stock=20)
        self.client.force_login(self.cajero)

    def tearDown(self):
        for modelo in reversed(self.tablas):
            modelo.objects.all().delete()

    def pedido(self, numero, estado='en_preparacion', **datos):
        estudiante = Usuarios.objects.create(nombre='Alumno ' + numero, correo=numero + '@itca.edu.sv', password='!', rol='estudiante')
        pedido = Pedidos.objects.create(numero=numero, estudiante=estudiante, estado=estado, **datos)
        pedido.refresh_from_db()
        DetallesPedido.objects.create(pedido=pedido, producto=self.producto, cantidad=2, precio_unitario='1.13')
        return pedido

    def cambiar(self, pedido, destino, **datos):
        return self.client.post(f'/pedidos/{pedido.pk}/estado/', {
            'destino': destino, 'version': pedido.estado_actualizado_en.isoformat(), **datos,
        }, HTTP_HX_REQUEST='true')

    def test_panel_respeta_orden_de_envio_y_detalle(self):
        reciente = self.pedido('PED-B234')
        antiguo = self.pedido('PED-A234', creado_en=timezone.now() - timedelta(hours=1))
        self.pedido('PED-CANC', estado='cancelado')
        self.pedido('PED-ENTR', estado='entregado')
        response = self.client.get('/pedidos/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual([p.pk for p in response.context['pedidos_preparacion']], [antiguo.pk, reciente.pk])
        self.assertContains(response, antiguo.estudiante.nombre)
        self.assertContains(response, self.producto.nombre)
        self.assertContains(response, '2×')
        self.assertNotContains(response, 'PED-CANC')
        self.assertNotContains(response, 'PED-ENTR')

    def test_solo_tres_listos_ordenados_por_momento_de_cambio(self):
        pedidos = [self.pedido(f'PED-L00{i}', estado='listo', estado_actualizado_en=timezone.now()-timedelta(minutes=i)) for i in range(4)]
        response = self.client.get('/pedidos/', HTTP_HX_REQUEST='true')
        self.assertEqual([p.pk for p in response.context['pedidos_listos']], [p.pk for p in pedidos[:3]])
        self.assertNotContains(response, '<html')
        self.assertNotContains(response, pedidos[3].numero)

    def test_marcar_listo_audita_sin_descontar_existencias(self):
        pedido = self.pedido('PED-LIST', estado_actualizado_en=timezone.now()-timedelta(hours=1))
        creado = pedido.creado_en
        response = self.cambiar(pedido, 'listo')
        self.assertEqual(response.status_code, 200)
        pedido.refresh_from_db()
        self.assertEqual(pedido.estado, 'listo')
        self.assertGreater(pedido.estado_actualizado_en, creado-timedelta(seconds=1))
        self.assertEqual(pedido.creado_en, creado)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 20)
        self.assertEqual(DetallesPedido.objects.filter(pedido__estado__in=['listo','en_preparacion']).count(), 1)
        evento = Auditoria.objects.get()
        self.assertEqual((evento.usuario_id, evento.modulo, evento.accion), (self.cajero.pk, 'Pedidos', 'Editado'))
        self.assertEqual(evento.valor_anterior['estado'], 'en_preparacion')
        self.assertEqual(evento.valor_nuevo['estado'], 'listo')
        self.assertContains(response, 'Volver a preparación')

    def test_deshacer_recupera_posicion_original(self):
        antiguo = self.pedido('PED-ANTG', creado_en=timezone.now()-timedelta(hours=1))
        self.pedido('PED-NUEV')
        self.cambiar(antiguo, 'listo')
        antiguo.refresh_from_db()
        response = self.cambiar(antiguo, 'en_preparacion')
        self.assertEqual(response.context['pedidos_preparacion'][0].pk, antiguo.pk)
        self.assertEqual(Auditoria.objects.count(), 2)

    def test_no_deshace_el_cuarto_listo(self):
        viejo = self.pedido('PED-VIEJ', estado='listo', estado_actualizado_en=timezone.now()-timedelta(hours=1))
        for i in range(3):
            self.pedido(f'PED-NEW{i}', estado='listo')
        response = self.cambiar(viejo, 'en_preparacion')
        self.assertContains(response, 'Solo se pueden devolver')
        viejo.refresh_from_db()
        self.assertEqual(viejo.estado, 'listo')
        self.assertFalse(Auditoria.objects.exists())

    def test_rechaza_doble_clic_y_version_antigua(self):
        pedido = self.pedido('PED-DOBL')
        self.cambiar(pedido, 'listo')
        self.cambiar(pedido, 'listo')
        self.assertEqual(Auditoria.objects.count(), 1)
        pedido.refresh_from_db()
        response = self.cambiar(pedido, 'en_preparacion', version='anterior')
        self.assertContains(response, 'Este pedido ya cambió')
        self.assertEqual(Auditoria.objects.count(), 1)

    def test_estados_ajenos_no_se_modifican(self):
        for estado in ('cancelado', 'entregado', 'pendiente'):
            pedido = self.pedido('PED-' + estado, estado=estado)
            self.cambiar(pedido, 'listo')
            pedido.refresh_from_db()
            self.assertEqual(pedido.estado, estado)
        self.assertFalse(Auditoria.objects.exists())

    def test_no_permite_cancelar_desde_cocina(self):
        pedido = self.pedido('PED-NOCN')
        self.cambiar(pedido, 'cancelado')
        pedido.refresh_from_db()
        self.assertEqual(pedido.estado, 'en_preparacion')

    def test_pedido_con_venta_no_se_devuelve(self):
        pedido = self.pedido('PED-SALE', estado='listo')
        caja = Caja.objects.create(abierta_por=self.admin, observaciones='')
        Ventas.objects.create(numero='V-TEST', pedido=pedido, caja=caja, cajero=self.cajero, efectivo_recibido='3.00')
        self.assertContains(self.cambiar(pedido, 'en_preparacion'), 'ya tiene una venta')
        pedido.refresh_from_db()
        self.assertEqual(pedido.estado, 'listo')

    def test_fallo_auditoria_revierte_cambio(self):
        pedido = self.pedido('PED-FAIL')
        with patch('cafeteria.pedidos.registrar_evento', side_effect=RuntimeError('fallo')):
            with self.assertRaises(RuntimeError):
                self.cambiar(pedido, 'listo')
        pedido.refresh_from_db()
        self.assertEqual(pedido.estado, 'en_preparacion')

    def test_sesion_csrf_y_metodo_obligatorios(self):
        pedido = self.pedido('PED-AUTH')
        self.assertEqual(Client().get('/pedidos/').status_code, 302)
        self.assertEqual(self.client.get(f'/pedidos/{pedido.pk}/estado/').status_code, 405)
        seguro = Client(enforce_csrf_checks=True)
        seguro.force_login(self.admin)
        self.assertEqual(seguro.post(f'/pedidos/{pedido.pk}/estado/', {'destino':'listo'}).status_code, 403)

    def test_estudiante_y_empleado_deshabilitado_no_pueden_cambiar(self):
        pedido = self.pedido('PED-ROLE')
        for usuario in (pedido.estudiante, self.cajero):
            if usuario == self.cajero:
                usuario.habilitado = False
                usuario.save(update_fields=['habilitado'])
            with self.assertRaises(PermissionDenied):
                cambiar_estado_pedido(usuario=usuario, pedido_id=pedido.pk, destino='listo', version=pedido.estado_actualizado_en.isoformat())

    def test_dos_empleados_no_duplican_cambio_ni_auditoria(self):
        if connection.vendor != 'mysql':
            self.skipTest('La prueba de bloqueo requiere MySQL.')
        pedido = self.pedido('PED-RACE')
        version = pedido.estado_actualizado_en.isoformat()
        def cambiar(actor_id):
            close_old_connections()
            try:
                usuario = Usuarios.objects.get(pk=actor_id)
                cambiar_estado_pedido(usuario=usuario, pedido_id=pedido.pk, destino='listo', version=version)
                return 'ok'
            except PedidoNoActualizable:
                return 'actualizado'
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            resultados = list(pool.map(cambiar, [self.admin.pk, self.cajero.pk]))
        self.assertCountEqual(resultados, ['ok', 'actualizado'])
        self.assertEqual(Auditoria.objects.count(), 1)
