from concurrent.futures import ThreadPoolExecutor
from datetime import time
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection
from django.test import Client, TransactionTestCase

from .configuracion import guardar_horario
from .models import Auditoria, Configuracion, HorariosPedidos, Usuarios


class ConfiguracionHorarioTests(TransactionTestCase):
    tablas = [Usuarios,Auditoria,Configuracion,HorariosPedidos]

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
        self.admin = Usuarios.objects.create(nombre='admin',correo='admin@test.local',password='!',rol='administrador')
        self.otro = Usuarios.objects.create(nombre='otro',correo='otro@test.local',password='!',rol='administrador')
        self.cajero = Usuarios.objects.create(nombre='cajero',correo='cajero@test.local',password='!',rol='cajero')
        self.config = Configuracion.objects.create(minutos_carrito=5,horarios_habilitados=False)
        self.client.force_login(self.admin)

    def tearDown(self):
        for modelo in reversed(self.tablas):
            modelo.objects.all().delete()

    def version(self, cliente=None):
        return (cliente or self.client).get('/configuracion/').context['form']['version'].value()

    def activar(self, **datos):
        campos = {'horarios_habilitados':'on','hora_inicio':'07:00','hora_fin':'17:00','version':self.version()}
        campos.update(datos)
        return self.client.post('/configuracion/',campos)

    def test_inicial_vacio_bloqueado_y_get_no_escribe(self):
        response = self.client.get('/configuracion/')
        self.assertContains(response,'id="schedule-fields" disabled')
        self.assertContains(response,'id="schedule-submit" disabled')
        self.assertContains(response,'Pedidos de lunes a viernes')
        self.assertContains(response,'Configuración de horario')
        self.assertFalse(HorariosPedidos.objects.exists())
        self.assertFalse(Auditoria.objects.exists())
        self.assertEqual(response.context['seccion'],'configuracion')

    def test_activar_crea_cinco_dias_no_modifica_carrito_y_audita(self):
        response = self.activar()
        self.assertEqual(response.status_code,302)
        self.config.refresh_from_db()
        self.assertTrue(self.config.horarios_habilitados)
        self.assertEqual(self.config.minutos_carrito,5)
        horarios = list(HorariosPedidos.objects.order_by('dia_semana'))
        self.assertEqual([h.dia_semana for h in horarios],[1,2,3,4,5])
        self.assertTrue(all(h.hora_inicio==time(7) and h.hora_fin==time(17) and h.activo for h in horarios))
        evento = Auditoria.objects.get()
        self.assertEqual(evento.modulo,Auditoria.Modulo.CONFIGURACION)
        self.assertEqual(evento.usuario_id,self.admin.pk)
        self.assertEqual(evento.valor_anterior['habilitado'],False)
        self.assertEqual(evento.valor_nuevo['habilitado'],True)
        self.assertEqual(self.client.get('/configuracion/').context['form'].initial['hora_inicio'],time(7))

    def test_desactivar_guarda_sin_horas_y_preserva_horario_anterior(self):
        self.activar()
        response = self.client.post('/configuracion/',{'version':self.version()})
        self.assertEqual(response.status_code,302)
        self.config.refresh_from_db()
        self.assertFalse(self.config.horarios_habilitados)
        self.assertEqual(HorariosPedidos.objects.count(),5)
        self.assertEqual(Auditoria.objects.count(),2)
        self.assertContains(self.client.get('/configuracion/'),'id="schedule-fields" disabled')

    def test_horas_obligatorias_validas_y_orden_correcto(self):
        for inicio,fin in [('', ''),('07:00',''),('','17:00'),('17:00','07:00'),('07:00','07:00'),('25:00','17:00')]:
            with self.subTest(inicio=inicio,fin=fin):
                response = self.activar(hora_inicio=inicio,hora_fin=fin)
                self.assertEqual(response.status_code,200)
                self.assertTrue(response.context['form'].errors)
                self.config.refresh_from_db()
                self.assertFalse(self.config.horarios_habilitados)
                self.assertFalse(HorariosPedidos.objects.exists())

    def test_version_falsa_y_version_vieja_no_sobrescriben(self):
        anterior = self.version()
        self.assertEqual(self.activar(version='falsa').status_code,200)
        self.assertFalse(HorariosPedidos.objects.exists())
        self.activar()
        response = self.activar(version=anterior,hora_fin='18:00')
        self.assertContains(response,'El horario cambió en otra ventana')
        self.assertTrue(all(h.hora_fin==time(17) for h in HorariosPedidos.objects.all()))
        self.assertEqual(Auditoria.objects.count(),1)

    def test_sin_cambios_no_duplica_horarios_ni_auditoria(self):
        self.activar()
        self.activar()
        self.assertEqual(HorariosPedidos.objects.count(),5)
        self.assertEqual(Auditoria.objects.count(),1)

    def test_horarios_previos_duplicados_y_fines_de_semana_se_desactivan(self):
        HorariosPedidos.objects.create(configuracion=self.config,dia_semana=1,hora_inicio=time(6),hora_fin=time(8))
        HorariosPedidos.objects.create(configuracion=self.config,dia_semana=1,hora_inicio=time(9),hora_fin=time(10))
        HorariosPedidos.objects.create(configuracion=self.config,dia_semana=6,hora_inicio=time(6),hora_fin=time(18))
        self.activar()
        activos = list(HorariosPedidos.objects.filter(activo=True).order_by('dia_semana'))
        self.assertEqual([h.dia_semana for h in activos],[1,2,3,4,5])
        self.assertTrue(all(h.hora_inicio==time(7) and h.hora_fin==time(17) for h in activos))
        self.assertEqual(HorariosPedidos.objects.filter(activo=False).count(),2)

    def test_sesion_permisos_y_csrf(self):
        self.assertEqual(Client().get('/configuracion/').status_code,302)
        self.client.force_login(self.cajero)
        self.assertEqual(self.client.get('/configuracion/').status_code,403)
        self.assertEqual(self.client.post('/configuracion/',{}).status_code,403)
        seguro = Client(enforce_csrf_checks=True)
        seguro.force_login(self.admin)
        self.assertEqual(seguro.post('/configuracion/',{}).status_code,403)

    def test_get_sin_configuracion_no_crea_y_primer_guardado_es_valido(self):
        self.config.delete()
        self.version()
        self.assertFalse(Configuracion.objects.exists())
        self.assertEqual(self.activar().status_code,302)
        self.assertEqual(Configuracion.objects.count(),1)
        self.assertEqual(Configuracion.objects.get().minutos_carrito,5)
        self.assertEqual(HorariosPedidos.objects.count(),5)

    def test_fallo_de_auditoria_revierte_todo_el_cambio(self):
        version = self.version()
        with patch('cafeteria.configuracion.registrar_evento',side_effect=RuntimeError('Fallo simulado')):
            with self.assertRaises(RuntimeError):
                guardar_horario(usuario=self.admin,habilitado=True,hora_inicio=time(7),hora_fin=time(17),version=version)
        self.config.refresh_from_db()
        self.assertFalse(self.config.horarios_habilitados)
        self.assertFalse(HorariosPedidos.objects.exists())

    def test_dos_administradores_no_pisan_sus_cambios_simultaneos(self):
        version = self.version()
        def guardar(actor_id):
            close_old_connections()
            try:
                guardar_horario(usuario=Usuarios.objects.get(pk=actor_id),habilitado=True,
                    hora_inicio=time(7),hora_fin=time(17),version=version)
                return 'ok'
            except ValidationError: return 'desactualizado'
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            resultados = list(pool.map(guardar,[self.admin.pk,self.otro.pk]))
        self.assertCountEqual(resultados,['ok','desactualizado'])
        self.assertEqual(HorariosPedidos.objects.count(),5)
        self.assertEqual(Auditoria.objects.count(),1)
