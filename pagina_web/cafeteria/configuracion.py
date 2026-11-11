from datetime import time

from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from .auditoria import registrar_evento
from .models import Auditoria, Configuracion, HorariosPedidos, Usuarios


def estado_horario(configuracion, horarios):
    return {'id':configuracion.pk if configuracion else None,
        'habilitado':bool(configuracion and configuracion.horarios_habilitados),
        'horarios':[{'id':h.pk,'dia':h.dia_semana,'inicio':h.hora_inicio.isoformat(),
                    'fin':h.hora_fin.isoformat(),'activo':h.activo} for h in horarios]}


def leer_horario():
    configuracion = Configuracion.objects.order_by('pk').first()
    horarios = list(HorariosPedidos.objects.filter(configuracion=configuracion).order_by('pk')) if configuracion else []
    return configuracion, horarios


@transaction.atomic
def guardar_horario(*, usuario, habilitado, hora_inicio, hora_fin, version):
    actor = Usuarios.objects.select_for_update().filter(pk=usuario.pk, habilitado=True, rol='administrador').first()
    if actor is None:
        raise PermissionDenied
    if type(habilitado) is not bool:
        raise ValidationError('Revisa la configuración del horario.')
    if habilitado and (not isinstance(hora_inicio,time) or not isinstance(hora_fin,time) or hora_inicio >= hora_fin):
        raise ValidationError('Selecciona una hora de inicio anterior a la hora final.')
    try:
        esperado = signing.loads(version, salt='cafeteria.horario')
    except (signing.BadSignature, TypeError, ValueError):
        raise ValidationError('Recarga la página antes de guardar el horario.') from None
    configuracion = Configuracion.objects.select_for_update().order_by('pk').first()
    creada = False
    if configuracion is None and habilitado:
        configuracion, creada = Configuracion.objects.select_for_update().get_or_create(pk=1, defaults={'minutos_carrito':5})
    horarios = list(HorariosPedidos.objects.select_for_update().filter(configuracion=configuracion).order_by('pk')) if configuracion else []
    anterior = estado_horario(None if creada else configuracion, horarios)
    if anterior != esperado:
        raise ValidationError('El horario cambió en otra ventana. Recarga la página y revisa los valores antes de guardar.')
    if configuracion is None:
        return None, False
    if habilitado:
        usados = set()
        for horario in horarios:
            activo = horario.dia_semana in range(1,6) and horario.dia_semana not in usados
            if activo:
                usados.add(horario.dia_semana)
                horario.hora_inicio, horario.hora_fin = hora_inicio, hora_fin
            horario.activo = activo
            horario.save(update_fields=['hora_inicio','hora_fin','activo'])
        for dia in range(1,6):
            if dia not in usados:
                HorariosPedidos.objects.create(configuracion=configuracion, dia_semana=dia,
                    hora_inicio=hora_inicio, hora_fin=hora_fin, activo=True)
    configuracion.horarios_habilitados = habilitado
    configuracion.save(update_fields=['horarios_habilitados'])
    actuales = list(HorariosPedidos.objects.filter(configuracion=configuracion).order_by('pk'))
    nuevo = estado_horario(configuracion, actuales)
    cambio = anterior != nuevo
    if cambio:
        registrar_evento(usuario=actor, accion=Auditoria.Accion.EDITADO, modulo=Auditoria.Modulo.CONFIGURACION,
            entidad='configuracion', registro_id=configuracion.pk,
            descripcion='Se actualizó la configuración de horario.', anterior=anterior, nuevo=nuevo)
    return configuracion, cambio
