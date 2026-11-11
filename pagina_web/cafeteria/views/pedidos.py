from django.contrib import messages
from django.db.models import Prefetch
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.vary import vary_on_headers

from ..models import DetallesPedido, Pedidos
from ..pedidos import PedidoNoActualizable, cambiar_estado_pedido, ultimos_listos
from ..web import es_peticion_htmx, solo_empleados


def renderizar_panel(request, *, mensaje='', error=False):
    lineas = Prefetch('detallespedido_set', queryset=DetallesPedido.objects.select_related('producto').order_by('id'), to_attr='lineas_comanda')
    pendientes = list(Pedidos.objects.filter(estado='en_preparacion').select_related('estudiante').prefetch_related(lineas).order_by('creado_en', 'id'))
    listos = list(ultimos_listos().select_related('estudiante').prefetch_related(lineas))
    plantilla = 'cafeteria/pedidos/_panel.html' if es_peticion_htmx(request) else 'cafeteria/pedidos/lista.html'
    return render(request, plantilla, {
        'pedidos_preparacion': pendientes, 'pedidos_listos': listos,
        'actualizado_en': timezone.now(), 'mensaje_pedido': mensaje, 'error_pedido': error,
    })


@solo_empleados
@vary_on_headers('HX-Request', 'HX-History-Restore-Request')
@require_GET
def lista_pedidos(request):
    return renderizar_panel(request)


@solo_empleados
@require_POST
def actualizar_pedido(request, pk):
    try:
        pedido = cambiar_estado_pedido(
            usuario=request.user, pedido_id=pk, destino=request.POST.get('destino'),
            version=request.POST.get('version', ''),
        )
        mensaje = f'{pedido.numero}: listo para recoger.' if pedido.estado == 'listo' else f'{pedido.numero}: de nuevo en preparación.'
        error = False
    except PedidoNoActualizable as exc:
        mensaje, error = str(exc), True
    if es_peticion_htmx(request):
        return renderizar_panel(request, mensaje=mensaje, error=error)
    (messages.error if error else messages.success)(request, mensaje)
    return redirect('pedidos_lista')
