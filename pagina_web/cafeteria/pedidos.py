"""Cambios de preparación; las existencias físicas se descuentan al cobrar."""
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from .auditoria import registrar_evento
from .models import Auditoria, Pedidos, Usuarios, Ventas


class PedidoNoActualizable(ValueError):
    pass


def ultimos_listos():
    return Pedidos.objects.filter(estado='listo').order_by('-estado_actualizado_en', '-id')[:3]


@transaction.atomic
def cambiar_estado_pedido(*, usuario, pedido_id, destino, version):
    actor = Usuarios.objects.select_for_update().filter(
        pk=usuario.pk, habilitado=True, rol__in=('administrador', 'cajero'),
    ).first()
    if actor is None:
        raise PermissionDenied
    if destino not in ('listo', 'en_preparacion'):
        raise PedidoNoActualizable('El cambio solicitado no está permitido.')
    pedido = get_object_or_404(Pedidos.objects.select_for_update(), pk=pedido_id)
    origen = 'en_preparacion' if destino == 'listo' else 'listo'
    if pedido.estado != origen or version != pedido.estado_actualizado_en.isoformat():
        raise PedidoNoActualizable('Este pedido ya cambió. Revisa el panel actualizado antes de continuar.')
    if Ventas.objects.filter(pedido_id=pedido.pk).exists():
        raise PedidoNoActualizable('Este pedido ya tiene una venta registrada y no puede volver a preparación.')
    if destino == 'en_preparacion' and pedido.pk not in ultimos_listos().values_list('pk', flat=True):
        raise PedidoNoActualizable('Solo se pueden devolver a preparación los últimos tres pedidos listos.')
    anterior = {'estado': pedido.estado, 'estado_actualizado_en': pedido.estado_actualizado_en.isoformat()}
    pedido.estado = destino
    pedido.estado_actualizado_en = timezone.now()
    pedido.save(update_fields=['estado', 'estado_actualizado_en'])
    registrar_evento(
        usuario=actor, accion=Auditoria.Accion.EDITADO, modulo=Auditoria.Modulo.PEDIDOS,
        entidad='pedidos', registro_id=pedido.pk, descripcion='Se actualizó el estado de un pedido.',
        anterior=anterior,
        nuevo={'estado': destino, 'estado_actualizado_en': pedido.estado_actualizado_en.isoformat()},
    )
    return pedido
