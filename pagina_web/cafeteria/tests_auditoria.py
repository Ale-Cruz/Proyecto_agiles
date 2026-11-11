from datetime import timedelta
from importlib import import_module

import bcrypt
from django.db import connection
from django.test import Client, TransactionTestCase
from django.utils import timezone

from .auditoria import registrar_evento
from .models import Auditoria, Usuarios


class AuditoriaConsultaTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with connection.schema_editor() as editor:
            editor.create_model(Usuarios)
            editor.create_model(Auditoria)
        cls.hash_prueba = bcrypt.hashpw(b'ClaveTemporal!2026', bcrypt.gensalt(rounds=4)).decode()

    @classmethod
    def tearDownClass(cls):
        with connection.schema_editor() as editor:
            editor.delete_model(Auditoria)
            editor.delete_model(Usuarios)
        super().tearDownClass()

    def setUp(self):
        self.admin = Usuarios.objects.create(nombre='admin', correo='admin@itca.edu.sv', password=self.hash_prueba, rol='administrador')
        self.cajero = Usuarios.objects.create(nombre='cajero1', correo='cajero1@itca.edu.sv', password=self.hash_prueba, rol='cajero')
        self.evento = Auditoria.objects.create(usuario=self.admin, accion=Auditoria.Accion.EDITADO,
            modulo=Auditoria.Modulo.USUARIOS, entidad_afectada='usuarios', registro_afectado_id=self.cajero.pk,
            descripcion='Se cambió información de un usuario.',
            valor_nuevo={'password_hash':'no-mostrar-este-hash', 'token':'no-mostrar-este-token'})
        self.automatico = Auditoria.objects.create(usuario=None, accion=Auditoria.Accion.ANADIDO,
            modulo=Auditoria.Modulo.INVENTARIO, entidad_afectada='movimientos_inventario', registro_afectado_id=9,
            descripcion='Se registró un movimiento de inventario.')
        self.baja = Auditoria.objects.create(usuario=self.cajero, accion=Auditoria.Accion.ELIMINADO_DESACTIVADO,
            modulo=Auditoria.Modulo.PRODUCTOS, entidad_afectada='productos', registro_afectado_id=12,
            descripcion='Se desactivó un producto.')
        self.client.force_login(self.admin)

    def tearDown(self):
        Auditoria.objects.all().delete()
        Usuarios.objects.all().delete()

    def test_historial_muestra_responsable_modulo_fecha_y_referencia(self):
        response = self.client.get('/auditoria/')
        for valor in ('Auditoría', 'Fecha y hora', 'Responsable', 'Usuarios', 'Sistema',
                      'Se cambió información de un usuario.', 'usuarios'):
            self.assertContains(response, valor)
        self.assertEqual(response.context['seccion'], 'auditoria')
        self.assertNotContains(response, 'no-mostrar-este-hash')
        self.assertNotContains(response, 'no-mostrar-este-token')
        self.assertNotContains(response, self.hash_prueba)

    def test_filtrar_por_accion(self):
        response = self.client.get('/auditoria/', {'accion':Auditoria.Accion.ELIMINADO_DESACTIVADO})
        self.assertEqual(list(response.context['page_obj']), [self.baja])

    def test_filtrar_por_modulo(self):
        response = self.client.get('/auditoria/', {'modulo':Auditoria.Modulo.USUARIOS})
        self.assertEqual(list(response.context['page_obj']), [self.evento])

    def test_buscar_responsable_por_nombre_o_correo(self):
        for texto in ('ADMIN', 'admin@itca.edu.sv'):
            response = self.client.get('/auditoria/', {'usuario':texto})
            self.assertEqual(list(response.context['page_obj']), [self.evento])

    def test_buscar_sistema_incluye_operaciones_automaticas(self):
        response = self.client.get('/auditoria/', {'usuario':'Sistema'})
        self.assertEqual(list(response.context['page_obj']), [self.automatico])

    def test_combinar_filtros(self):
        response = self.client.get('/auditoria/', {'usuario':'cajero', 'accion':Auditoria.Accion.ELIMINADO_DESACTIVADO, 'modulo':Auditoria.Modulo.PRODUCTOS})
        self.assertEqual(list(response.context['page_obj']), [self.baja])
        response = self.client.get('/auditoria/', {'usuario':'cajero', 'modulo':Auditoria.Modulo.USUARIOS})
        self.assertContains(response, 'No se encontraron registros')

    def test_paginacion_ordena_recientes_y_conserva_filtros(self):
        fecha = timezone.now() - timedelta(days=1)
        Auditoria.objects.bulk_create([Auditoria(usuario=self.admin, accion=Auditoria.Accion.EDITADO,
            modulo=Auditoria.Modulo.USUARIOS, entidad_afectada='usuarios', registro_afectado_id=100+n,
            descripcion='Se cambió información de un usuario.', creado_en=fecha) for n in range(27)])
        response = self.client.get('/auditoria/', {'modulo':'Usuarios', 'usuario':'admin'})
        self.assertEqual(len(response.context['page_obj']), 25)
        self.assertEqual(response.context['page_obj'][0], self.evento)
        self.assertContains(response, 'modulo=Usuarios')
        self.assertContains(response, 'usuario=admin')
        segunda = self.client.get('/auditoria/', {'modulo':'Usuarios', 'page':2})
        self.assertEqual(len(segunda.context['page_obj']), 3)

    def test_filtros_htmx_devuelven_fragmento_y_historial_pagina_completa(self):
        response = self.client.get('/auditoria/', {'modulo':'Usuarios'}, HTTP_HX_REQUEST='true')
        self.assertContains(response, 'id="audit-list"')
        self.assertNotContains(response, '<html')
        response = self.client.get('/auditoria/', HTTP_HX_REQUEST='true', HTTP_HX_HISTORY_RESTORE_REQUEST='true')
        self.assertContains(response, '<html')
        self.assertContains(response, 'hx-history-elt')

    def test_solo_admin_puede_consultar(self):
        anonimo = Client()
        self.assertEqual(anonimo.get('/auditoria/').status_code, 302)
        self.assertIn('HX-Redirect', anonimo.get('/auditoria/', HTTP_HX_REQUEST='true'))
        self.client.force_login(self.cajero)
        self.assertEqual(self.client.get('/auditoria/').status_code, 403)
        self.assertEqual(self.client.get('/auditoria/', HTTP_HX_REQUEST='true').status_code, 403)

    def test_consulta_no_admite_escrituras_ni_genera_mas_eventos(self):
        for metodo in ('post', 'put', 'patch', 'delete'):
            self.assertEqual(getattr(self.client, metodo)('/auditoria/').status_code, 405)
        self.client.get('/auditoria/')
        self.assertEqual(Auditoria.objects.count(), 3)

    def test_busqueda_no_interpreta_html_ni_sql(self):
        texto = '<script>alert(1)</script>'
        response = self.client.get('/auditoria/', {'usuario':texto})
        self.assertNotContains(response, texto)
        self.assertContains(response, '&lt;script&gt;')
        response = self.client.get('/auditoria/', {'usuario':"' OR 1=1 --"})
        self.assertEqual(response.context['page_obj'].paginator.count, 0)

    def test_registro_comun_elimina_secretos_incluso_anidados(self):
        evento = registrar_evento(usuario=self.admin, accion=Auditoria.Accion.EDITADO,
            modulo=Auditoria.Modulo.USUARIOS, entidad='usuarios', registro_id=1,
            descripcion='Se cambió información de un usuario.', nuevo={
                'nombre':'otro', 'Password_Hash':'secreto', 'contrasena_actualizada':True,
                'datos':[{'token_sesion_hash':'privado', 'habilitado':True}],
            })
        self.assertEqual(evento.valor_nuevo, {'nombre':'otro', 'contrasena_actualizada':True, 'datos':[{'habilitado':True}]})


class MigracionAuditoriaTests(TransactionTestCase):
    def setUp(self):
        with connection.cursor() as cursor:
            cursor.execute('''CREATE TABLE auditoria (
                id INT PRIMARY KEY AUTO_INCREMENT, usuario_id INT NULL,
                accion VARCHAR(100) NOT NULL, entidad_afectada VARCHAR(100) NOT NULL,
                registro_afectado_id INT NOT NULL, descripcion TEXT NOT NULL,
                valor_anterior JSON NULL, valor_nuevo JSON NULL,
                creado_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')
            cursor.execute("INSERT INTO auditoria (usuario_id,accion,entidad_afectada,registro_afectado_id,descripcion) VALUES (1,'editar_usuario','usuarios',2,'Anterior')")
            cursor.execute('''INSERT INTO auditoria (accion,entidad_afectada,registro_afectado_id,descripcion,valor_anterior,valor_nuevo)
                VALUES ('editar_usuario','usuarios',3,'Anterior','{"habilitado":true}','{"habilitado":false}')''')

    def tearDown(self):
        with connection.cursor() as cursor:
            cursor.execute('DROP TABLE auditoria')

    def test_migracion_conserva_datos_normaliza_y_puede_reintentarse(self):
        migracion = import_module('cafeteria.migrations.0003_auditoria_modulo')
        with connection.schema_editor() as editor:
            migracion.actualizar_auditoria(None, editor)
            migracion.actualizar_auditoria(None, editor)
        with connection.cursor() as cursor:
            cursor.execute('SELECT accion,modulo,descripcion,registro_afectado_id FROM auditoria ORDER BY id')
            self.assertEqual(cursor.fetchall(), (
                ('Editado','Usuarios','Se cambió información de un usuario.',2),
                ('Eliminado/desactivado','Usuarios','Se desactivó un usuario.',3),
            ))
            indices = connection.introspection.get_constraints(cursor, 'auditoria')
            self.assertIn('idx_auditoria_modulo', indices)
            self.assertIn('idx_auditoria_accion', indices)
            self.assertIn('idx_auditoria_fecha', indices)
            # Una inserción antigua que omite la columna recibe un valor compatible.
            cursor.execute("INSERT INTO auditoria (accion,entidad_afectada,registro_afectado_id,descripcion) VALUES ('Editado','productos',4,'Cambio')")
            cursor.execute('SELECT modulo FROM auditoria ORDER BY id DESC LIMIT 1')
            self.assertEqual(cursor.fetchone()[0], 'General')
