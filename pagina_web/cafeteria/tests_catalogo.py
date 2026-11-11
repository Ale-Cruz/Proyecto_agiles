from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
import io
from pathlib import Path
import tempfile
import uuid
from unittest.mock import patch

import bcrypt
from PIL import Image
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, close_old_connections
from django.test import Client, TransactionTestCase, override_settings

from .inventario import productos_vendibles, registrar_movimiento
from .models import (Auditoria, Caja, Categorias, DetallesVenta, MovimientosInventario,
                     Pedidos, Productos, Usuarios, Ventas)


class CatalogoInventarioTests(TransactionTestCase):
    tablas = [Usuarios, Auditoria, Categorias, Productos, Caja, Pedidos, Ventas, DetallesVenta, MovimientosInventario]

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with connection.schema_editor() as editor:
            for modelo in cls.tablas:
                editor.create_model(modelo)
        cls.hash_prueba = bcrypt.hashpw(b'Temporal!2026', bcrypt.gensalt(rounds=4)).decode()

    @classmethod
    def tearDownClass(cls):
        with connection.schema_editor() as editor:
            for modelo in reversed(cls.tablas):
                editor.delete_model(modelo)
        super().tearDownClass()

    def setUp(self):
        self.admin = Usuarios.objects.create(nombre='admin', correo='admin@itca.edu.sv', password=self.hash_prueba, rol='administrador')
        self.cajero = Usuarios.objects.create(nombre='cajero', correo='cajero@itca.edu.sv', password=self.hash_prueba, rol='cajero')
        self.categoria = Categorias.objects.create(nombre='Bebidas', activo=True)
        self.producto = Productos.objects.create(categoria=self.categoria, nombre='Café', codigo='CAFE-1', precio='1.00', fotografia='', stock=20, stock_minimo=5)
        self.client.force_login(self.admin)
        self.media = tempfile.TemporaryDirectory(prefix='codex_catalogo_')
        self.assertEqual(Path(self.media.name).resolve().parent, Path(tempfile.gettempdir()).resolve())
        self.config_media = override_settings(MEDIA_ROOT=self.media.name)
        self.config_media.enable()

    def tearDown(self):
        for modelo in reversed(self.tablas):
            modelo.objects.all().delete()
        self.config_media.disable()
        self.assertTrue(Path(self.media.name).resolve().name.startswith('codex_catalogo_'))
        self.media.cleanup()

    def datos_producto(self, **cambios):
        datos = {'nombre':'Nuevo producto', 'codigo':'NUEVO-1', 'categoria':self.categoria.pk,
                 'descripcion':'Descripción', 'precio':'1.25', 'stock_minimo':3,
                 'disponible_para_venta':'on', 'activo':'on'}
        datos.update(cambios)
        return datos

    def movimiento(self, **cambios):
        datos = {'usuario':self.admin, 'producto_id':self.producto.pk, 'operacion':'entrada',
                 'cantidad':5, 'motivo':'Reposición', 'operacion_id':uuid.uuid4()}
        datos.update(cambios)
        return registrar_movimiento(**datos)

    def test_listados_submenu_y_fragmentos(self):
        for url in ('/productos/', '/categorias/', '/inventario/', '/inventario/?vista=movimientos'):
            response = self.client.get(url)
            self.assertContains(response, 'nav-submenu')
            self.assertContains(response, '<details class="nav-group" open')
            fragmento = self.client.get(url, HTTP_HX_REQUEST='true')
            self.assertContains(fragmento, 'id="module-list"')
            self.assertNotContains(fragmento, '<html')

    def test_solo_admin_puede_consultar_y_escribir(self):
        for url in ('/productos/', '/categorias/', '/inventario/', '/productos/nuevo/', '/categorias/nueva/', '/inventario/nuevo/', '/inventario/producto-info/'):
            self.assertEqual(Client().get(url).status_code, 302)
            self.client.force_login(self.cajero)
            self.assertEqual(self.client.get(url).status_code, 403)
            self.assertEqual(self.client.post(url, {}).status_code, 403)

    def test_crear_categoria_y_auditar(self):
        response = self.client.post('/categorias/nueva/', {'nombre':'Comidas','activo':'on'}, HTTP_HX_REQUEST='true')
        self.assertEqual(response.status_code, 204)
        evento = Auditoria.objects.get()
        self.assertEqual((evento.modulo,evento.accion), ('Categorías','Añadido'))

    def test_categoria_duplicada_y_reactivacion(self):
        response = self.client.post('/categorias/nueva/', {'nombre':'BEBIDAS','activo':'on'})
        self.assertIn('nombre', response.context['form'].errors)
        self.client.post(f'/categorias/{self.categoria.pk}/editar/', {'nombre':'Bebidas'})
        self.assertFalse(productos_vendibles().exists())
        self.assertEqual(Auditoria.objects.get().accion, 'Eliminado/desactivado')
        self.producto.refresh_from_db()
        self.assertTrue(self.producto.disponible_para_venta)
        self.client.post(f'/categorias/{self.categoria.pk}/editar/', {'nombre':'Bebidas','activo':'on'})
        self.assertTrue(productos_vendibles().exists())

    def test_crear_producto_sin_permitir_stock_directo(self):
        response = self.client.post('/productos/nuevo/', self.datos_producto(stock=900), HTTP_HX_REQUEST='true')
        self.assertEqual(response.status_code, 204)
        nuevo = Productos.objects.get(codigo='NUEVO-1')
        self.assertEqual(nuevo.stock,0)
        self.assertFalse(MovimientosInventario.objects.exists())
        self.assertEqual(Auditoria.objects.get().modulo,'Productos')

    def test_editar_producto_no_sobrescribe_stock(self):
        datos = self.datos_producto(codigo='CAFE-1', nombre='Café editado', stock=999)
        self.assertEqual(self.client.post(f'/productos/{self.producto.pk}/editar/',datos).status_code,302)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock,20)
        self.assertEqual(self.producto.nombre,'Café editado')

    def test_producto_codigo_unico_y_valores_no_negativos(self):
        response = self.client.post('/productos/nuevo/',self.datos_producto(codigo='cafe-1',precio='-1',stock_minimo=-2))
        for campo in ('codigo','precio','stock_minimo'):
            self.assertIn(campo,response.context['form'].errors)
        self.assertEqual(Productos.objects.count(),1)

    def test_categoria_inactiva_no_se_puede_asignar_a_producto_nuevo(self):
        self.categoria.activo=False
        self.categoria.save()
        response = self.client.post('/productos/nuevo/',self.datos_producto())
        self.assertIn('categoria',response.context['form'].errors)

    def test_desactivar_venta_conserva_producto_stock_e_historial(self):
        response = self.client.post(f'/productos/{self.producto.pk}/editar/', self.datos_producto(codigo='CAFE-1', disponible_para_venta=''))
        self.assertEqual(response.status_code,302)
        self.producto.refresh_from_db()
        self.assertFalse(self.producto.disponible_para_venta)
        self.assertEqual(self.producto.stock,20)
        self.assertFalse(productos_vendibles().exists())
        self.assertEqual(Auditoria.objects.get().accion,'Eliminado/desactivado')

    def test_guardar_sin_cambios_no_duplica_auditoria(self):
        datos = self.datos_producto(nombre='Café',codigo='CAFE-1',descripcion='',precio='1.00',stock_minimo=5)
        self.producto.descripcion=''
        self.producto.save()
        self.client.post(f'/productos/{self.producto.pk}/editar/',datos)
        self.assertFalse(Auditoria.objects.exists())

    def test_foto_se_reconvierte_y_archivo_invalido_se_rechaza(self):
        contenido=io.BytesIO()
        Image.new('RGB',(30,20),'red').save(contenido,format='PNG')
        foto=SimpleUploadedFile('foto.png',contenido.getvalue(),content_type='image/png')
        self.assertEqual(self.client.post('/productos/nuevo/',self.datos_producto(imagen=foto)).status_code,302)
        nuevo=Productos.objects.get(codigo='NUEVO-1')
        ruta=Path(settings.MEDIA_ROOT)/nuevo.fotografia.removeprefix(settings.MEDIA_URL)
        self.assertTrue(ruta.is_file())
        with Image.open(ruta) as imagen:
            self.assertEqual(imagen.format,'WEBP')
        falso=SimpleUploadedFile('foto.svg',b'<svg><script>alert(1)</script></svg>',content_type='image/svg+xml')
        response=self.client.post('/productos/nuevo/',self.datos_producto(codigo='NUEVO-2',imagen=falso))
        self.assertIn('imagen',response.context['form'].errors)
        self.assertFalse(Productos.objects.filter(codigo='NUEVO-2').exists())

    def test_csrf_tambien_se_exige_en_htmx(self):
        cliente=Client(enforce_csrf_checks=True)
        cliente.force_login(self.admin)
        self.assertEqual(cliente.post('/productos/nuevo/',self.datos_producto(),HTTP_HX_REQUEST='true').status_code,403)

    def test_entrada_registra_cantidad_responsable_y_auditoria(self):
        movimiento,creado=self.movimiento()
        self.producto.refresh_from_db()
        self.assertTrue(creado)
        self.assertEqual(self.producto.stock,25)
        self.assertEqual((movimiento.cantidad,movimiento.tipo,movimiento.usuario_id),(5,'entrada',self.admin.pk))
        evento=Auditoria.objects.get()
        self.assertEqual(evento.valor_anterior,{'stock':20})
        self.assertEqual(evento.valor_nuevo['stock'],25)

    def test_salida_excesiva_no_cambia_nada(self):
        with self.assertRaises(ValidationError):
            self.movimiento(operacion='salida',cantidad=21)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock,20)
        self.assertFalse(MovimientosInventario.objects.exists())
        self.assertFalse(Auditoria.objects.exists())

    def test_salida_manual_puede_dejar_stock_en_cero(self):
        movimiento,_=self.movimiento(operacion='salida',cantidad=20)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock,0)
        self.assertEqual((movimiento.tipo,movimiento.cantidad),('salida_manual',20))

    def test_solo_entrada_y_salida_con_cantidades_positivas(self):
        for operacion,cantidad in (('conteo',12),('entrada',0),('salida',0),('entrada',-1)):
            with self.assertRaises(ValidationError):
                self.movimiento(operacion=operacion,cantidad=cantidad)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock,20)
        self.assertFalse(MovimientosInventario.objects.exists())

    def test_busqueda_de_producto_por_nombre_y_codigo(self):
        Productos.objects.create(categoria=self.categoria,codigo='INACTIVO',nombre='Fuera de venta',precio='1',fotografia='',activo=False)
        por_nombre=self.client.get('/inventario/buscar-producto/',{'producto_busqueda':self.producto.nombre})
        self.assertContains(por_nombre,self.producto.codigo)
        por_codigo=self.client.get('/inventario/buscar-producto/',{'producto_busqueda':self.producto.codigo})
        self.assertContains(por_codigo,self.producto.nombre)
        self.assertContains(self.client.get('/inventario/buscar-producto/',{'producto_busqueda':'INACTIVO'}),'Fuera de venta')
        sin_resultados=self.client.get('/inventario/buscar-producto/',{'producto_busqueda':"' OR 1=1 --"})
        self.assertNotContains(sin_resultados,self.producto.codigo)
        self.client.force_login(self.cajero)
        self.assertEqual(self.client.get('/inventario/buscar-producto/',{'producto_busqueda':'CAFE'}).status_code,403)

    def test_busqueda_no_carga_catalogo_completo_y_limita_resultados(self):
        Productos.objects.bulk_create([Productos(categoria=self.categoria,codigo=f'BUS-{n}',nombre=f'Prueba {n}',precio='1',fotografia='') for n in range(50)])
        response=self.client.get('/inventario/buscar-producto/',{'producto_busqueda':'Prueba'})
        self.assertEqual(len(response.context['productos_encontrados']),20)
        self.assertEqual(list(self.client.get('/inventario/buscar-producto/').context['productos_encontrados']),[])

    def test_movimiento_exige_producto_seleccionado_y_rechaza_conteo_antiguo(self):
        datos={'operacion':'entrada','cantidad':2,'motivo':'Prueba','operacion_id':str(uuid.uuid4()),'producto_busqueda':self.producto.nombre}
        response=self.client.post('/inventario/nuevo/',datos,HTTP_HX_REQUEST='true')
        self.assertIn('producto',response.context['form'].errors)
        datos.update(producto=self.producto.pk,operacion='conteo')
        response=self.client.post('/inventario/nuevo/',datos,HTTP_HX_REQUEST='true')
        self.assertIn('operacion',response.context['form'].errors)
        self.assertFalse(MovimientosInventario.objects.exists())

    def test_seleccion_y_stock_se_conservan_si_otro_campo_es_invalido(self):
        datos={'producto':self.producto.pk,'operacion':'salida','cantidad':2,'motivo':'','operacion_id':str(uuid.uuid4())}
        response=self.client.post('/inventario/nuevo/',datos,HTTP_HX_REQUEST='true')
        self.assertEqual(response.context['producto_seleccionado'].pk,self.producto.pk)
        self.assertIn('motivo',response.context['form'].errors)
        self.assertContains(response,'name="producto"')
        self.assertContains(response,f'value="{self.producto.pk}"')

    def test_mismo_envio_no_duplica_movimiento(self):
        operacion=uuid.uuid4()
        primero,creado=self.movimiento(operacion_id=operacion)
        segundo,creado_otra_vez=self.movimiento(operacion_id=operacion)
        self.assertEqual(primero.pk,segundo.pk)
        self.assertTrue(creado)
        self.assertFalse(creado_otra_vez)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock,25)
        self.assertEqual(Auditoria.objects.count(),1)

    def test_entradas_simultaneas_no_pierden_stock(self):
        def entrada(cantidad):
            close_old_connections()
            try:
                self.movimiento(cantidad=cantidad)
            finally:
                connection.close()
        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(entrada,[3,7]))
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock,30)
        self.assertEqual(MovimientosInventario.objects.count(),2)

    def test_auditoria_y_stock_se_revierten_juntos(self):
        with patch('cafeteria.inventario.registrar_evento',side_effect=RuntimeError('Fallo simulado')):
            with self.assertRaises(RuntimeError):
                self.movimiento()
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock,20)
        self.assertFalse(MovimientosInventario.objects.exists())

    def test_post_movimiento_y_filtros_de_historial(self):
        datos={'producto':self.producto.pk,'operacion':'entrada','cantidad':4,'motivo':'Reposición','operacion_id':str(uuid.uuid4())}
        self.assertEqual(self.client.post('/inventario/nuevo/',datos,HTTP_HX_REQUEST='true').status_code,204)
        response=self.client.get('/inventario/',{'vista':'movimientos','estado':'entrada','q':'cajero'})
        self.assertEqual(response.context['page_obj'].paginator.count,0)
        response=self.client.get('/inventario/',{'vista':'movimientos','q':'admin'})
        self.assertContains(response,'Reposición')
        self.assertEqual(self.client.get('/inventario/1/editar/').status_code,404)
        self.assertEqual(self.client.delete('/inventario/').status_code,405)

    def test_stock_bajo_busqueda_y_paginacion(self):
        self.producto.stock=3
        self.producto.save()
        response=self.client.get('/inventario/',{'estado':'bajo'})
        self.assertContains(response,'Stock bajo')
        self.assertEqual(response.context['page_obj'].paginator.count,1)
        response=self.client.get('/productos/',{'q':"' OR 1=1 --"})
        self.assertEqual(response.context['page_obj'].paginator.count,0)
        Productos.objects.bulk_create([Productos(categoria=self.categoria,codigo=f'P-{n}',nombre=f'Producto {n}',precio='1',fotografia='') for n in range(16)])
        self.assertEqual(len(self.client.get('/productos/').context['page_obj']),15)


class MigracionCatalogoTests(TransactionTestCase):
    def test_migrar_tablas_anteriores_sin_duplicar_indices(self):
        with connection.cursor() as cursor:
            cursor.execute('CREATE TABLE categorias(id INT PRIMARY KEY AUTO_INCREMENT,nombre VARCHAR(100) NOT NULL,activo BOOL NOT NULL DEFAULT 1)')
            cursor.execute('CREATE TABLE movimientos_inventario(id INT PRIMARY KEY AUTO_INCREMENT)')
        try:
            migracion=import_module('cafeteria.migrations.0004_catalogo_inventario')
            with connection.schema_editor() as editor:
                migracion.preparar_catalogo(None,editor)
                migracion.preparar_catalogo(None,editor)
            with connection.cursor() as cursor:
                cursor.execute('INSERT INTO movimientos_inventario () VALUES ()')
                cursor.execute('SELECT operacion_id FROM movimientos_inventario')
                self.assertEqual(cursor.fetchone(),(None,))
                indices=connection.introspection.get_constraints(cursor,'categorias')
                self.assertTrue(any(indice['unique'] and indice['columns']==['nombre'] for indice in indices.values()))
        finally:
            with connection.cursor() as cursor:
                cursor.execute('DROP TABLE movimientos_inventario')
                cursor.execute('DROP TABLE categorias')
