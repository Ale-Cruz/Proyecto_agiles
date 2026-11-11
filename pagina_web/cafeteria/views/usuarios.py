import json

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.vary import vary_on_headers
from django.views.decorators.http import require_http_methods

from ..forms.empleados import EmpleadoForm, ROLES_EMPLEADOS
from ..models import Auditoria, Caja, Usuarios
from ..auditoria import registrar_evento
from ..web import es_peticion_htmx, solo_administradores


def empleados():
    return Usuarios.objects.filter(rol__in=dict(ROLES_EMPLEADOS))


def datos_auditoria(usuario):
    return {campo: getattr(usuario, campo) for campo in ('nombre', 'correo', 'rol', 'habilitado')}


@solo_administradores
@vary_on_headers('HX-Request', 'HX-History-Restore-Request')
@require_http_methods(['GET'])
def lista_usuarios(request):
    consulta = request.GET.get('q', '').strip()[:150]
    rol = request.GET.get('rol', '')
    estado = request.GET.get('estado', '')
    queryset = empleados().order_by('nombre', 'id')
    if consulta:
        queryset = queryset.filter(Q(nombre__icontains=consulta) | Q(correo__icontains=consulta))
    if rol in dict(ROLES_EMPLEADOS):
        queryset = queryset.filter(rol=rol)
    if estado in ('activo', 'inactivo'):
        queryset = queryset.filter(habilitado=estado == 'activo')
    plantilla = 'cafeteria/usuarios/_listado.html' if es_peticion_htmx(request) else 'cafeteria/usuarios/lista.html'
    return render(request, plantilla, {
        'page_obj': Paginator(queryset, 15).get_page(request.GET.get('page')),
        'consulta': consulta, 'filtro_rol': rol, 'filtro_estado': estado,
    })


@solo_administradores
@vary_on_headers('HX-Request', 'HX-History-Restore-Request')
@require_http_methods(['GET', 'POST'])
def guardar_usuario(request, pk=None):
    if request.method == 'POST':
        with transaction.atomic():
            # Serializar altas/ediciones: nombres de acceso y administradores activos.
            personal = list(empleados().select_for_update().order_by('pk'))
            actor = next((u for u in personal if u.pk == request.user.pk), None)
            if actor is None or not actor.habilitado or actor.rol != 'administrador':
                raise PermissionDenied
            empleado = get_object_or_404(empleados(), pk=pk) if pk is not None else Usuarios()
            anterior = datos_auditoria(empleado) if empleado.pk else None
            form = EmpleadoForm(request.POST, instance=empleado, actor=actor)
            valido = form.is_valid()
            if valido and empleado.pk and not form.cleaned_data.get('habilitado') and Caja.objects.filter(abierta_por=empleado, estado='abierta').exists():
                form.add_error('habilitado', 'Este usuario tiene una caja abierta. Debe cerrarla antes de deshabilitar su cuenta.')
                valido = False
            if valido:
                empleado = form.save()
                nuevo = datos_auditoria(empleado)
                cambio_clave = bool(form.cleaned_data.get('password1'))
                if pk is None or anterior != nuevo or cambio_clave:
                    if pk is None:
                        accion, descripcion = Auditoria.Accion.ANADIDO, 'Se añadió un usuario.'
                    elif anterior['habilitado'] and not nuevo['habilitado']:
                        accion = Auditoria.Accion.ELIMINADO_DESACTIVADO
                        descripcion = 'Se desactivó un usuario.'
                    else:
                        accion, descripcion = Auditoria.Accion.EDITADO, 'Se cambió información de un usuario.'
                    registrar_evento(
                        usuario=actor, accion=accion, modulo=Auditoria.Modulo.USUARIOS,
                        entidad='usuarios', registro_id=empleado.pk, descripcion=descripcion,
                        anterior=anterior, nuevo={**nuevo, 'contrasena_actualizada': cambio_clave},
                    )
                if empleado.pk == request.user.pk:
                    update_session_auth_hash(request, empleado)
                mensaje = 'Usuario creado correctamente.' if pk is None else 'Cambios guardados correctamente.'
                if es_peticion_htmx(request):
                    detalle = {'mensaje': mensaje}
                    if empleado.pk == request.user.pk:
                        detalle['nombreActual'] = empleado.nombre
                    return HttpResponse(status=204, headers={'HX-Trigger': json.dumps({'empleadoGuardado': detalle})})
                messages.success(request, mensaje)
                return redirect('usuarios_lista')
    else:
        empleado = get_object_or_404(empleados(), pk=pk) if pk is not None else Usuarios()
        form = EmpleadoForm(instance=empleado, actor=request.user)
    es_modal = es_peticion_htmx(request)
    plantilla = 'cafeteria/usuarios/_formulario.html' if es_modal else 'cafeteria/usuarios/formulario.html'
    return render(request, plantilla, {
        'form': form, 'empleado': empleado, 'es_nuevo': pk is None,
        'es_cuenta_propia': pk == request.user.pk,
        'es_modal': es_modal,
    })
