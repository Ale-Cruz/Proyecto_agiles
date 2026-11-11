from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render
from django.views.decorators.http import require_GET
from django.views.decorators.vary import vary_on_headers

from ..models import Auditoria
from ..web import es_peticion_htmx, solo_administradores


@solo_administradores
@vary_on_headers('HX-Request', 'HX-History-Restore-Request')
@require_GET
def lista_auditoria(request):
    usuario = request.GET.get('usuario', '').strip()[:150]
    accion = request.GET.get('accion', '')
    modulo = request.GET.get('modulo', '')
    accion = accion if accion in Auditoria.Accion.values else ''
    modulo = modulo if modulo in Auditoria.Modulo.values else ''
    registros = Auditoria.objects.select_related('usuario').only(
        'id', 'accion', 'modulo', 'descripcion', 'entidad_afectada',
        'registro_afectado_id', 'creado_en', 'usuario__id', 'usuario__nombre',
    ).order_by('-creado_en', '-id')
    if usuario:
        responsable = Q(usuario__nombre__icontains=usuario) | Q(usuario__correo__icontains=usuario)
        if usuario.casefold() in 'sistema':
            responsable |= Q(usuario__isnull=True)
        registros = registros.filter(responsable)
    if accion:
        registros = registros.filter(accion=accion)
    if modulo:
        registros = registros.filter(modulo=modulo)
    plantilla = 'cafeteria/auditoria/_listado.html' if es_peticion_htmx(request) else 'cafeteria/auditoria/lista.html'
    return render(request, plantilla, {
        'page_obj': Paginator(registros, 25).get_page(request.GET.get('page')),
        'consulta_usuario': usuario, 'filtro_accion': accion, 'filtro_modulo': modulo,
        'acciones': Auditoria.Accion.choices, 'modulos_auditoria': Auditoria.Modulo.choices,
    })
