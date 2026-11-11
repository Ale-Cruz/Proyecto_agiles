from functools import wraps

from django.core.exceptions import PermissionDenied


def solo_administradores(vista):
    @wraps(vista)
    def protegida(request, *args, **kwargs):
        if not request.user.is_authenticated or request.user.rol != 'administrador' or not request.user.habilitado:
            raise PermissionDenied
        return vista(request, *args, **kwargs)
    return protegida


def es_peticion_htmx(request):
    return request.headers.get('HX-Request') == 'true' and request.headers.get('HX-History-Restore-Request') != 'true'


def solo_empleados(vista):
    @wraps(vista)
    def protegida(request, *args, **kwargs):
        if (not request.user.is_authenticated or not request.user.habilitado
                or request.user.rol not in ('administrador', 'cajero')):
            raise PermissionDenied
        return vista(request, *args, **kwargs)
    return protegida
