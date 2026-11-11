from datetime import timedelta
import json

import bcrypt
from django.conf import settings
from django.contrib.auth import SESSION_KEY
from django.contrib.auth.hashers import make_password
from django.db import DatabaseError, connection
from django.test import Client, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from .models import Auditoria, Caja, IntentosAcceso, Usuarios


class AccesoEmpleadosTests(TransactionTestCase):
    """Pruebas en una BD temporal; no usan cuentas de la BD de desarrollo."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Los modelos importados son unmanaged: Django no crea sus tablas al probar.
        with connection.schema_editor() as editor:
            editor.create_model(Usuarios)
        cls.hash_php = bcrypt.hashpw(b'clave-prueba', bcrypt.gensalt(rounds=4)).decode().replace('$2b$', '$2y$', 1)

    @classmethod
    def tearDownClass(cls):
        with connection.schema_editor() as editor:
            editor.delete_model(Usuarios)
        super().tearDownClass()

    def setUp(self):
        self.admin = Usuarios.objects.create(nombre='admin', correo='admin@itca.edu.sv', password=self.hash_php, rol='administrador')
        self.cajero = Usuarios.objects.create(nombre='cajero1', correo='cajero1@itca.edu.sv', password=self.hash_php, rol='cajero')
        self.estudiante = Usuarios.objects.create(nombre='estudiante', correo='alumno@itca.edu.sv', password=self.hash_php, rol='estudiante')

    def tearDown(self):
        Usuarios.objects.all().delete()

    def entrar(self, usuario='admin', password='clave-prueba', **extra):
        return self.client.post(reverse('login'), {'username': usuario, 'password': password, **extra})

    def test_url_privada_exige_sesion(self):
        for url in ('/', '/dashboard/'):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn('/login/', response.url)

    def test_admin_entra_con_bcrypt_php(self):
        self.assertRedirects(self.entrar(), '/dashboard/')
        self.assertEqual(self.client.session[SESSION_KEY], str(self.admin.pk))
        response = self.client.get('/dashboard/')
        self.assertContains(response, 'Hola,')
        self.assertContains(response, 'Auditoría')
        self.assertIn('no-store', response['Cache-Control'])

    def test_cajero_entra_sin_modulos_de_administrador(self):
        self.assertRedirects(self.entrar('cajero1'), '/dashboard/')
        response = self.client.get('/dashboard/')
        self.assertContains(response, 'Punto de venta')
        self.assertNotContains(response, 'Auditoría')
        self.assertNotContains(response, '>Usuarios<')

    def test_contrasena_incorrecta(self):
        self.assertContains(self.entrar(password='incorrecta'), 'Usuario o contraseña incorrectos.')
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_estudiante_no_puede_acceder(self):
        self.assertContains(self.entrar('estudiante'), 'Usuario o contraseña incorrectos.')
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_no_se_acepta_correo_en_login(self):
        self.assertContains(self.entrar('admin@itca.edu.sv'), 'Usuario o contraseña incorrectos.')

    def test_empleado_deshabilitado(self):
        Usuarios.objects.filter(pk=self.admin.pk).update(habilitado=False)
        self.assertContains(self.entrar(), 'Usuario o contraseña incorrectos.')

    def test_nombres_duplicados_no_eligen_una_cuenta(self):
        Usuarios.objects.create(nombre='admin', correo='otro@itca.edu.sv', password=self.hash_php, rol='cajero')
        self.assertContains(self.entrar(), 'Usuario o contraseña incorrectos.')

    def test_hash_django_tambien_es_compatible(self):
        Usuarios.objects.filter(pk=self.admin.pk).update(password=make_password('otra-clave'))
        self.assertRedirects(self.entrar(password='otra-clave'), '/dashboard/')

    def test_redireccion_externa_no_se_acepta(self):
        self.assertRedirects(self.entrar(next='https://ejemplo.invalid/robar'), '/dashboard/')

    def test_sql_no_autentica(self):
        self.assertContains(self.entrar("admin' OR 1=1 --"), 'Usuario o contraseña incorrectos.')
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_bloqueo_tras_cinco_fallos_y_recuperacion(self):
        for _ in range(settings.LOGIN_MAX_ATTEMPTS):
            self.assertEqual(self.entrar(password='incorrecta').status_code, 200)
        self.assertEqual(self.entrar().status_code, 429)
        IntentosAcceso.objects.update(inicio_ventana=timezone.now()-timedelta(minutes=16))
        self.assertRedirects(self.entrar(), '/dashboard/')

    def test_limite_por_ip_entre_varios_usuarios(self):
        IntentosAcceso.objects.all().delete()
        with self.settings(LOGIN_IP_MAX_ATTEMPTS=2):
            self.entrar('inexistente-1')
            self.entrar('inexistente-2')
            self.assertEqual(self.entrar('admin').status_code, 429)

    def test_login_y_logout_exigen_csrf(self):
        cliente = Client(enforce_csrf_checks=True)
        self.assertEqual(cliente.post('/login/', {'username':'admin','password':'clave-prueba'}).status_code, 403)
        cliente.get('/login/')
        token = cliente.cookies['csrftoken'].value
        self.assertEqual(cliente.post('/login/', {'username':'admin','password':'clave-prueba','csrfmiddlewaretoken':token}).status_code, 302)
        self.assertEqual(cliente.post('/logout/').status_code, 403)
        self.assertEqual(cliente.post('/logout/', {'csrfmiddlewaretoken':cliente.cookies['csrftoken'].value}).status_code, 302)
        self.assertEqual(cliente.get('/dashboard/').status_code, 302)

    def test_logout_solo_post_y_revoca_sesion(self):
        self.entrar()
        self.assertEqual(self.client.get('/logout/').status_code, 405)
        self.assertRedirects(self.client.post('/logout/'), '/login/')
        self.assertEqual(self.client.get('/dashboard/').status_code, 302)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_cookie_segura_y_sesion_persistente(self):
        self.entrar()
        cookie=self.client.cookies[settings.SESSION_COOKIE_NAME]
        self.assertTrue(cookie['httponly'])
        self.assertEqual(cookie['samesite'], 'Lax')
        self.assertFalse(self.client.session.get_expire_at_browser_close())

    def test_desactivar_usuario_invalida_sesion_existente(self):
        self.entrar()
        Usuarios.objects.filter(pk=self.admin.pk).update(habilitado=False)
        self.assertEqual(self.client.get('/dashboard/').status_code, 302)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_cambio_de_password_invalida_sesion(self):
        self.entrar()
        Usuarios.objects.filter(pk=self.admin.pk).update(password=make_password('nuevo-secreto'))
        self.assertEqual(self.client.get('/dashboard/').status_code, 302)

    def test_login_rota_identificador_de_sesion(self):
        session=self.client.session
        session['dato_previo']='ejemplo'
        session.save()
        anterior=session.session_key
        self.client.cookies[settings.SESSION_COOKIE_NAME]=anterior
        self.entrar()
        self.assertNotEqual(self.client.session.session_key, anterior)

    def test_usuario_autenticado_no_regresa_al_formulario(self):
        self.entrar()
        self.assertRedirects(self.client.get('/login/'), '/dashboard/')


class UsuariosEmpleadosTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with connection.schema_editor() as editor:
            editor.create_model(Usuarios)
            editor.create_model(Auditoria)
            editor.create_model(Caja)
        cls.clave = 'Temporal!2026'
        cls.hash_prueba = bcrypt.hashpw(cls.clave.encode(), bcrypt.gensalt(rounds=4)).decode()

    @classmethod
    def tearDownClass(cls):
        with connection.schema_editor() as editor:
            editor.delete_model(Caja)
            editor.delete_model(Auditoria)
            editor.delete_model(Usuarios)
        super().tearDownClass()

    def setUp(self):
        self.admin = Usuarios.objects.create(nombre='admin', correo='admin@itca.edu.sv', password=self.hash_prueba, rol='administrador')
        self.cajero = Usuarios.objects.create(nombre='cajero1', correo='cajero1@itca.edu.sv', password=self.hash_prueba, rol='cajero')
        self.estudiante = Usuarios.objects.create(nombre='estudiante', correo='estudiante@itca.edu.sv', password=self.hash_prueba, rol='estudiante')
        self.client.force_login(self.admin)

    def tearDown(self):
        Caja.objects.all().delete()
        Auditoria.objects.all().delete()
        Usuarios.objects.all().delete()

    def datos(self, **cambios):
        datos = {'nombre': 'nuevo', 'correo': 'nuevo@itca.edu.sv', 'rol': 'cajero',
                 'habilitado': 'on', 'password1': self.clave, 'password2': self.clave}
        datos.update(cambios)
        return datos

    def test_no_desactiva_cajero_con_apertura_activa(self):
        Caja.objects.create(abierta_por=self.cajero, observaciones='')
        datos = self.datos(nombre=self.cajero.nombre, correo=self.cajero.correo, habilitado='', password1='', password2='')
        response = self.client.post(f'/usuarios/{self.cajero.pk}/editar/', datos)
        self.assertIn('habilitado', response.context['form'].errors)
        self.cajero.refresh_from_db()
        self.assertTrue(self.cajero.habilitado)

    def test_lista_excluye_estudiantes_y_hashes(self):
        response = self.client.get('/usuarios/')
        self.assertContains(response, 'cajero1@itca.edu.sv')
        self.assertNotContains(response, self.estudiante.correo)
        self.assertNotContains(response, self.hash_prueba)

    def test_buscar_y_filtrar_no_incluye_estudiantes(self):
        for query in ({'q': 'estudiante'}, {'rol': 'estudiante', 'q': 'estudiante'}):
            self.assertNotContains(self.client.get('/usuarios/', query), self.estudiante.correo)
        response = self.client.get('/usuarios/', {'rol': 'cajero'})
        self.assertContains(response, self.cajero.correo)
        self.assertNotContains(response, self.admin.correo)

    def test_paginacion_y_filtro_estado(self):
        for n in range(16):
            Usuarios.objects.create(nombre=f'personal{n:02}', correo=f'personal{n}@itca.edu.sv', password=self.hash_prueba, rol='cajero', habilitado=False)
        response = self.client.get('/usuarios/', {'estado': 'inactivo'})
        self.assertEqual(len(response.context['page_obj']), 15)
        self.assertEqual(response.context['page_obj'].paginator.count, 16)

    def test_anonimo_no_puede_listar_ni_crear(self):
        client = Client()
        self.assertEqual(client.get('/usuarios/').status_code, 302)
        self.assertEqual(client.post('/usuarios/nuevo/', self.datos()).status_code, 302)

    def test_cajero_no_puede_acceder_ni_escribir(self):
        self.client.force_login(self.cajero)
        for url in ('/usuarios/', '/usuarios/nuevo/', f'/usuarios/{self.admin.pk}/editar/'):
            self.assertEqual(self.client.get(url).status_code, 403)
            self.assertEqual(self.client.post(url, self.datos()).status_code, 403)

    def test_estudiante_no_es_editable_por_url(self):
        url = reverse('usuarios_editar', args=[self.estudiante.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, self.datos()).status_code, 404)
        self.estudiante.refresh_from_db()
        self.assertEqual(self.estudiante.rol, 'estudiante')

    def test_crear_cajero_con_password_cifrada_y_auditoria(self):
        self.assertRedirects(self.client.post('/usuarios/nuevo/', self.datos()), '/usuarios/')
        nuevo = Usuarios.objects.get(nombre='nuevo')
        self.assertEqual(nuevo.correo, 'nuevo@itca.edu.sv')
        self.assertTrue(nuevo.check_password(self.clave))
        self.assertNotEqual(nuevo.password, self.clave)
        evento = Auditoria.objects.get(accion=Auditoria.Accion.ANADIDO)
        self.assertEqual(evento.modulo, Auditoria.Modulo.USUARIOS)
        self.assertEqual(evento.usuario_id, self.admin.pk)
        self.assertEqual(evento.registro_afectado_id, nuevo.pk)
        self.assertNotIn('password', str(evento.valor_nuevo))
        self.assertNotIn(self.clave, str(evento.valor_nuevo))
        client = Client()
        self.assertEqual(client.post('/login/', {'username':'nuevo', 'password':self.clave}).status_code, 302)

    def test_crear_administrador(self):
        self.assertRedirects(self.client.post('/usuarios/nuevo/', self.datos(rol='administrador')), '/usuarios/')
        self.assertEqual(Usuarios.objects.get(nombre='nuevo').rol, 'administrador')

    def test_rol_estudiante_se_rechaza(self):
        response = self.client.post('/usuarios/nuevo/', self.datos(rol='estudiante'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('rol', response.context['form'].errors)
        self.assertFalse(Usuarios.objects.filter(nombre='nuevo').exists())

    def test_nombre_duplicado_sin_distinguir_mayusculas(self):
        response = self.client.post('/usuarios/nuevo/', self.datos(nombre='ADMIN'))
        self.assertIn('nombre', response.context['form'].errors)

    def test_correo_de_estudiante_tambien_es_unico(self):
        response = self.client.post('/usuarios/nuevo/', self.datos(correo=self.estudiante.correo))
        self.assertEqual(response.status_code, 200, response.headers.get('Location', ''))
        self.assertIn('correo', response.context['form'].errors)

    def test_password_debil_y_confirmacion(self):
        response = self.client.post('/usuarios/nuevo/', self.datos(password1='123', password2='diferente'))
        self.assertIn('password1', response.context['form'].errors)
        self.assertIn('password2', response.context['form'].errors)
        self.assertFalse(Usuarios.objects.filter(nombre='nuevo').exists())

    def test_no_se_acepta_correo_como_nombre(self):
        response = self.client.post('/usuarios/nuevo/', self.datos(nombre='nuevo@itca.edu.sv'))
        self.assertIn('nombre', response.context['form'].errors)

    def test_editar_sin_password_conserva_hash(self):
        datos = self.datos(nombre='cajero-editado', correo=self.cajero.correo, password1='', password2='')
        self.assertRedirects(self.client.post(reverse('usuarios_editar', args=[self.cajero.pk]), datos), '/usuarios/')
        self.cajero.refresh_from_db()
        self.assertEqual(self.cajero.nombre, 'cajero-editado')
        self.assertEqual(self.cajero.correo, 'cajero1@itca.edu.sv')
        self.assertEqual(self.cajero.password, self.hash_prueba)
        self.assertEqual(Auditoria.objects.get().valor_anterior['nombre'], 'cajero1')

    def test_cambio_password_revoca_otras_sesiones(self):
        otro = Client()
        otro.force_login(self.cajero)
        datos = self.datos(nombre=self.cajero.nombre, correo=self.cajero.correo, password1='NuevaClave!2026', password2='NuevaClave!2026')
        self.assertRedirects(self.client.post(reverse('usuarios_editar', args=[self.cajero.pk]), datos), '/usuarios/')
        self.assertEqual(otro.get('/dashboard/').status_code, 302)

    def test_actualizar_password_propia_conserva_sesion_actual(self):
        otro = Client()
        otro.force_login(self.admin)
        datos = self.datos(nombre='admin', correo=self.admin.correo, rol='administrador', password1='NuevaClave!2026', password2='NuevaClave!2026')
        self.assertRedirects(self.client.post(reverse('usuarios_editar', args=[self.admin.pk]), datos), '/usuarios/')
        self.assertEqual(self.client.get('/dashboard/').status_code, 200)
        self.assertEqual(otro.get('/dashboard/').status_code, 302)

    def test_no_puede_deshabilitar_su_cuenta(self):
        datos = self.datos(nombre='admin', correo=self.admin.correo, rol='administrador', habilitado='', password1='', password2='')
        response = self.client.post(reverse('usuarios_editar', args=[self.admin.pk]), datos)
        self.assertIn('habilitado', response.context['form'].errors)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.habilitado)

    def test_no_puede_quitarse_rol_admin(self):
        datos = self.datos(nombre='admin', correo=self.admin.correo, rol='cajero', password1='', password2='')
        response = self.client.post(reverse('usuarios_editar', args=[self.admin.pk]), datos)
        self.assertIn('rol', response.context['form'].errors)

    def test_deshabilitar_otro_empleado(self):
        datos = self.datos(nombre='cajero1', correo=self.cajero.correo, habilitado='', password1='', password2='')
        self.assertRedirects(self.client.post(reverse('usuarios_editar', args=[self.cajero.pk]), datos), '/usuarios/')
        self.cajero.refresh_from_db()
        self.assertFalse(self.cajero.habilitado)
        evento = Auditoria.objects.get()
        self.assertEqual(evento.accion, Auditoria.Accion.ELIMINADO_DESACTIVADO)
        self.assertEqual(evento.descripcion, 'Se desactivó un usuario.')

    def test_guardar_sin_cambios_no_crea_evento(self):
        datos = self.datos(nombre=self.cajero.nombre, correo=self.cajero.correo, password1='', password2='')
        self.assertEqual(self.client.post(reverse('usuarios_editar', args=[self.cajero.pk]), datos, HTTP_HX_REQUEST='true').status_code, 204)
        self.assertFalse(Auditoria.objects.exists())

    def test_fallo_al_guardar_auditoria_revierte_edicion(self):
        from unittest.mock import patch
        datos = self.datos(nombre='cambio-no-confirmado', correo=self.cajero.correo, password1='', password2='')
        with patch('cafeteria.auditoria.Auditoria.objects.create', side_effect=RuntimeError('Fallo simulado')):
            with self.assertRaises(RuntimeError):
                self.client.post(reverse('usuarios_editar', args=[self.cajero.pk]), datos)
        self.cajero.refresh_from_db()
        self.assertEqual(self.cajero.nombre, 'cajero1')
        self.assertFalse(Auditoria.objects.exists())

    def test_post_exige_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.post('/usuarios/nuevo/', self.datos()).status_code, 403)

    def test_campos_no_permitidos_no_se_guardan(self):
        response = self.client.post('/usuarios/nuevo/', self.datos(password_hash='texto-plano', token_sesion_hash='token-inyectado', is_superuser=True))
        self.assertEqual(response.status_code, 302)
        nuevo = Usuarios.objects.get(nombre='nuevo')
        self.assertNotEqual(nuevo.password, 'texto-plano')
        self.assertIsNone(nuevo.token_sesion_hash)

    def test_usuario_nuevo_por_defecto_es_cajero(self):
        response = self.client.get('/usuarios/nuevo/')
        self.assertEqual(response.context['form'].initial['rol'], 'cajero')

    def test_htmx_abre_formulario_parcial_con_csrf(self):
        response = self.client.get('/usuarios/nuevo/', HTTP_HX_REQUEST='true')
        self.assertContains(response, 'id="employee-modal-title"')
        self.assertContains(response, 'csrfmiddlewaretoken')
        self.assertContains(response, 'hx-post="/usuarios/nuevo/"')
        self.assertNotContains(response, '<html')
        self.assertNotContains(response, 'panel-sidebar')
        self.assertIn('HX-Request', response['Vary'])

    def test_htmx_crear_notifica_guardado_sin_redireccion_y_audita(self):
        response = self.client.post('/usuarios/nuevo/', self.datos(), HTTP_HX_REQUEST='true')
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b'')
        self.assertIn('empleadoGuardado', json.loads(response['HX-Trigger']))
        nuevo = Usuarios.objects.get(nombre='nuevo')
        self.assertTrue(nuevo.check_password(self.clave))
        self.assertEqual(Auditoria.objects.get().registro_afectado_id, nuevo.pk)
        self.assertNotIn(self.clave, str(Auditoria.objects.get().valor_nuevo))
        # El aviso no debe reaparecer como un mensaje antiguo al recargar.
        self.assertNotContains(self.client.get('/usuarios/'), 'Usuario creado correctamente.')

    def test_htmx_errores_permanecen_en_modal_sin_crear_usuario(self):
        response = self.client.post('/usuarios/nuevo/', self.datos(nombre='ADMIN', password1='123', password2='otra'), HTTP_HX_REQUEST='true')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="employee-modal-title"')
        self.assertNotContains(response, '<html')
        self.assertNotIn('HX-Trigger', response)
        self.assertIn('nombre', response.context['form'].errors)
        self.assertIn('password2', response.context['form'].errors)
        self.assertEqual(Usuarios.objects.count(), 3)
        self.assertFalse(Auditoria.objects.exists())

    def test_htmx_editar_conserva_password_y_refleja_cambios_al_listar(self):
        datos = self.datos(nombre='cajero-editado', correo=self.cajero.correo, password1='', password2='')
        response = self.client.post(reverse('usuarios_editar', args=[self.cajero.pk]), datos, HTTP_HX_REQUEST='true')
        self.assertEqual(response.status_code, 204)
        self.cajero.refresh_from_db()
        self.assertEqual(self.cajero.password, self.hash_prueba)
        listado = self.client.get('/usuarios/', {'q':'cajero-editado'}, HTTP_HX_REQUEST='true')
        self.assertContains(listado, 'Editar cajero-editado')
        self.assertNotContains(listado, self.estudiante.correo)

    def test_htmx_listado_filtrado_devuelve_solo_la_tabla_y_sus_filtros(self):
        response = self.client.get('/usuarios/', {'q':'cajero', 'rol':'cajero', 'estado':'activo'}, HTTP_HX_REQUEST='true')
        self.assertContains(response, 'id="employee-list"')
        self.assertContains(response, self.cajero.correo)
        self.assertNotContains(response, self.admin.correo)
        self.assertNotContains(response, '<html')
        self.assertEqual(response.context['consulta'], 'cajero')
        self.assertEqual(response.context['filtro_rol'], 'cajero')

    def test_htmx_recuperar_historial_devuelve_pagina_completa(self):
        response = self.client.get('/usuarios/', HTTP_HX_REQUEST='true', HTTP_HX_HISTORY_RESTORE_REQUEST='true')
        self.assertContains(response, '<html')
        self.assertContains(response, 'id="employee-modal"')
        self.assertContains(response, 'id="employee-list-history" hx-history-elt')

    def test_htmx_no_elude_permisos_ni_expone_estudiantes(self):
        self.assertEqual(self.client.get(reverse('usuarios_editar', args=[self.estudiante.pk]), HTTP_HX_REQUEST='true').status_code, 404)
        self.client.force_login(self.cajero)
        self.assertEqual(self.client.get('/usuarios/', HTTP_HX_REQUEST='true').status_code, 403)
        self.assertEqual(self.client.post('/usuarios/nuevo/', self.datos(), HTTP_HX_REQUEST='true').status_code, 403)
        self.assertFalse(Usuarios.objects.filter(nombre='nuevo').exists())

    def test_htmx_sin_sesion_ordena_redireccion_al_login(self):
        cliente = Client()
        for url in ('/usuarios/', '/usuarios/nuevo/'):
            response = cliente.get(url, HTTP_HX_REQUEST='true')
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response['HX-Redirect'].startswith('/login/'))
            self.assertEqual(response.content, b'')

    def test_htmx_sigue_exigiendo_csrf(self):
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.admin)
        response = cliente.post('/usuarios/nuevo/', self.datos(), HTTP_HX_REQUEST='true')
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Usuarios.objects.filter(nombre='nuevo').exists())

    def test_htmx_cambio_password_propia_conserva_sesion_y_revoca_otras(self):
        otro = Client()
        otro.force_login(self.admin)
        datos = self.datos(nombre='admin', correo=self.admin.correo, rol='administrador', password1='NuevaClave!2026', password2='NuevaClave!2026')
        response = self.client.post(reverse('usuarios_editar', args=[self.admin.pk]), datos, HTTP_HX_REQUEST='true')
        self.assertEqual(response.status_code, 204)
        self.assertEqual(json.loads(response['HX-Trigger'])['empleadoGuardado']['nombreActual'], 'admin')
        self.assertEqual(self.client.get('/usuarios/', HTTP_HX_REQUEST='true').status_code, 200)
        self.assertEqual(otro.get('/dashboard/').status_code, 302)


class ProteccionAdminTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from importlib import import_module
        with connection.schema_editor() as editor:
            editor.create_model(Usuarios)
        import_module('cafeteria.migrations.0002_proteger_admin_principal').instalar_proteccion(connection)
        cls.hash_prueba = bcrypt.hashpw(b'Principal!2026', bcrypt.gensalt(rounds=4)).decode()

    @classmethod
    def tearDownClass(cls):
        with connection.schema_editor() as editor:
            editor.delete_model(Usuarios)
        super().tearDownClass()

    def setUp(self):
        self.principal, _ = Usuarios.objects.get_or_create(pk=1, defaults={
            'nombre':'admin', 'correo':'admin@itca.edu.sv', 'password':self.hash_prueba,
            'rol':'administrador', 'habilitado':True,
        })
        self.actor = Usuarios.objects.create(pk=100, nombre='otro-admin', correo='otro@itca.edu.sv', password=self.hash_prueba, rol='administrador')
        self.cajero = Usuarios.objects.create(pk=200, nombre='cajero', correo='cajero@itca.edu.sv', password=self.hash_prueba, rol='cajero')
        self.client.force_login(self.actor)

    def tearDown(self):
        Usuarios.objects.exclude(pk=1).delete()

    def test_delete_sql_directo_bloqueado(self):
        with self.assertRaises(DatabaseError):
            with connection.cursor() as cursor:
                cursor.execute('DELETE FROM usuarios WHERE id=1')
        self.assertTrue(Usuarios.objects.filter(pk=1, habilitado=True).exists())

    def test_delete_orm_bloqueado(self):
        with self.assertRaises(DatabaseError):
            Usuarios.objects.filter(pk=1).delete()

    def test_borrado_masivo_es_atomico_y_conserva_admin(self):
        with self.assertRaises(DatabaseError):
            Usuarios.objects.all().delete()
        self.assertEqual(Usuarios.objects.count(), 3)

    def test_update_no_puede_deshabilitar_admin(self):
        with self.assertRaises(DatabaseError):
            Usuarios.objects.filter(pk=1).update(habilitado=False)

    def test_update_no_puede_cambiar_rol_admin(self):
        with self.assertRaises(DatabaseError):
            Usuarios.objects.filter(pk=1).update(rol='cajero')

    def test_update_no_puede_cambiar_nombre_admin(self):
        with self.assertRaises(DatabaseError):
            Usuarios.objects.filter(pk=1).update(nombre='otro-nombre')

    def test_update_no_puede_cambiar_id_admin(self):
        with self.assertRaises(DatabaseError):
            Usuarios.objects.filter(pk=1).update(id=999)

    def test_correo_y_contrasena_siguen_editables(self):
        clave = make_password('ClaveNueva!2026')
        Usuarios.objects.filter(pk=1).update(correo='nuevo@itca.edu.sv', password=clave)
        self.principal.refresh_from_db()
        self.assertEqual(self.principal.correo, 'nuevo@itca.edu.sv')
        self.assertTrue(self.principal.check_password('ClaveNueva!2026'))

    def test_otro_admin_no_puede_alterar_cuenta_principal_por_post(self):
        response = self.client.post('/usuarios/1/editar/', {
            'nombre':'renombrado', 'correo':'admin@itca.edu.sv', 'rol':'cajero',
            'password1':'', 'password2':'',
        })
        self.assertEqual(response.status_code, 200)
        for campo in ('nombre','rol','habilitado'):
            self.assertIn(campo, response.context['form'].errors)
        self.principal.refresh_from_db()
        self.assertEqual((self.principal.nombre,self.principal.rol,self.principal.habilitado),('admin','administrador',True))

    def test_formulario_muestra_cuenta_protegida(self):
        response = self.client.get('/usuarios/1/editar/')
        self.assertContains(response, 'Cuenta principal protegida')
        self.assertTrue(response.context['form'].fields['nombre'].widget.attrs['readonly'])
        self.assertTrue(response.context['form'].fields['rol'].widget.attrs['disabled'])

    def test_htmx_tampoco_permite_alterar_cuenta_principal(self):
        response = self.client.post('/usuarios/1/editar/', {
            'nombre':'renombrado', 'correo':'admin@itca.edu.sv', 'rol':'cajero',
            'password1':'', 'password2':'',
        }, HTTP_HX_REQUEST='true')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Cuenta principal protegida')
        self.assertNotIn('HX-Trigger', response)
        self.assertNotContains(response, '<html')
        self.principal.refresh_from_db()
        self.assertEqual((self.principal.nombre, self.principal.rol, self.principal.habilitado), ('admin', 'administrador', True))

    def test_otras_cuentas_pueden_deshabilitarse(self):
        Usuarios.objects.filter(pk=self.cajero.pk).update(habilitado=False)
        self.cajero.refresh_from_db()
        self.assertFalse(self.cajero.habilitado)
