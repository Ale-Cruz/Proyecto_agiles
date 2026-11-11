"""Cobro o anulación de pedidos listos, usando sus precios y reservas originales."""
from decimal import Decimal
import uuid

from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .auditoria import registrar_evento
from .models import Auditoria, DetallesPedido, Pedidos, Productos, Ventas
from .pos import (MAX_DINERO, _registrar_venta, actor_actual, cantidades_apartadas,
                  desglose, dinero, importe, requerir_apertura)


def snapshot_pedido(pedido, detalles):
    lineas, usados, total = [], set(), Decimal('0.00')
    valido = bool(detalles)
    for detalle in detalles:
        valido = valido and detalle.cantidad > 0 and detalle.precio_unitario >= 0 and detalle.producto_id not in usados
        usados.add(detalle.producto_id)
        monto = detalle.precio_unitario*detalle.cantidad
        total += monto
        lineas.append({'id':detalle.producto_id, 'cantidad':detalle.cantidad,
            'precio':dinero(detalle.precio_unitario), 'importe':dinero(monto),
            'nombre':detalle.producto.nombre, 'codigo':detalle.producto.codigo})
    valido = valido and 0 <= total <= MAX_DINERO and total == pedido.total
    return {'items':lineas, **desglose(pedido.total), 'cobrable':bool(valido),
        'advertencia':'' if valido else 'El detalle y el total del pedido no coinciden. Revisa el registro antes de cobrar.'}


def huella(snapshot):
    return [{'id':l['id'], 'cantidad':l['cantidad'], 'precio':l['precio']} for l in snapshot['items']]


def resumen_pedido(*, usuario, apertura_id, pedido_id):
    actor = actor_actual(usuario)
    requerir_apertura(actor, apertura_id)
    pedido = Pedidos.objects.select_related('estudiante').filter(pk=pedido_id, estado='listo').first()
    if pedido is None:
        raise ValidationError('Este pedido ya no está listo para recoger. Actualiza el panel.')
    detalles = list(DetallesPedido.objects.filter(pedido=pedido).select_related('producto').order_by('producto_id','pk'))
    resumen = snapshot_pedido(pedido, detalles)
    version = pedido.estado_actualizado_en.isoformat()
    datos = {'usuario':actor.pk, 'apertura':apertura_id, 'pedido':pedido.pk, 'version':version,
        'items':huella(resumen), 'total':resumen['total']}
    return {'id':pedido.pk, 'numero':pedido.numero, 'estudiante':pedido.estudiante.nombre,
        'listo_en':version, 'minutos_espera':max(0,int((timezone.now()-pedido.estado_actualizado_en).total_seconds()//60)),
        **resumen, 'cotizacion':signing.dumps(datos, salt='pos.pedido', compress=True)}


def evento_cancelacion(operacion):
    return Auditoria.objects.filter(modulo=Auditoria.Modulo.PEDIDOS,
        accion=Auditoria.Accion.ELIMINADO_DESACTIVADO, entidad_afectada='pedidos',
        valor_nuevo__operacion_id=str(operacion)).first()


@transaction.atomic
def procesar_pedido(*, usuario, cotizacion, accion, operacion_id, efectivo=None, motivo=''):
    actor = actor_actual(usuario, bloquear=True)
    if accion not in ('cobrar','anular'):
        raise ValidationError('Selecciona cobrar o anular el pedido.')
    try:
        operacion = uuid.UUID(str(operacion_id))
        datos = signing.loads(cotizacion, salt='pos.pedido')
    except (ValueError, TypeError, signing.BadSignature):
        raise ValidationError('Abre de nuevo el resumen del pedido antes de continuar.') from None
    if datos.get('usuario') != actor.pk:
        raise PermissionDenied
    if accion == 'cobrar':
        recibido = importe(efectivo)
    else:
        if not isinstance(motivo,str) or not motivo.strip() or len(motivo.strip())>1000:
            raise ValidationError('Escribe el motivo de la anulación, con un máximo de 1000 caracteres.')
        motivo = motivo.strip()
    anterior = Ventas.objects.filter(operacion_id=operacion).first()
    if anterior:
        detalle_venta = [{'id':l.producto_id,'cantidad':l.cantidad,'precio':dinero(l.precio_unitario)}
            for l in anterior.detallesventa_set.order_by('producto_id','pk')]
        if (accion != 'cobrar' or anterior.pedido_id != datos.get('pedido') or anterior.caja_id != datos.get('apertura')
                or anterior.cajero_id != actor.pk or anterior.efectivo_recibido != recibido
                or dinero(anterior.total) != datos.get('total') or detalle_venta != datos.get('items')):
            raise ValidationError('Esta operación ya fue utilizada. Revisa el resultado antes de continuar.')
        return {'accion':'cobrar', 'numero':anterior.pedido.numero, 'venta':anterior.numero,
            'total':dinero(anterior.total), 'cambio':dinero(recibido-anterior.total), 'creada':False}
    cancelacion = evento_cancelacion(operacion)
    if cancelacion:
        if (accion != 'anular' or cancelacion.usuario_id != actor.pk or cancelacion.registro_afectado_id != datos.get('pedido')
                or cancelacion.valor_nuevo.get('apertura_id') != datos.get('apertura') or cancelacion.valor_nuevo.get('motivo') != motivo):
            raise ValidationError('Esta operación ya fue utilizada. Revisa el resultado antes de continuar.')
        pedido = Pedidos.objects.get(pk=datos['pedido'])
        if pedido.estado != 'cancelado':
            raise ValidationError('El estado del pedido cambió después de esta operación. Actualiza el panel.')
        return {'accion':'anular', 'numero':pedido.numero, 'creada':False}
    try:
        signing.loads(cotizacion, salt='pos.pedido', max_age=300)
    except signing.SignatureExpired:
        raise ValidationError('El resumen lleva varios minutos abierto. Ciérralo y selecciona de nuevo el pedido.') from None
    apertura = requerir_apertura(actor, datos.get('apertura'), bloquear=True)
    # La API móvil toma productos antes que pedido al cancelar: conservar ese orden.
    ids = list(DetallesPedido.objects.filter(pedido_id=datos.get('pedido')).values_list('producto_id',flat=True))
    productos = {p.pk:p for p in Productos.objects.select_for_update().filter(pk__in=ids).order_by('pk')}
    pedido = Pedidos.objects.select_for_update().filter(pk=datos.get('pedido')).first()
    if pedido is None or pedido.estado != 'listo' or pedido.estado_actualizado_en.isoformat() != datos.get('version'):
        raise ValidationError('El pedido cambió o ya fue atendido. Actualiza el panel antes de continuar.')
    if Ventas.objects.filter(pedido=pedido).exists():
        raise ValidationError('Este pedido ya tiene una venta registrada y no puede cobrarse ni anularse aquí.')
    anterior_estado = {'estado':pedido.estado,'estado_actualizado_en':pedido.estado_actualizado_en.isoformat()}
    ahora = timezone.now()
    if accion == 'anular':
        pedido.estado, pedido.estado_actualizado_en = 'cancelado', ahora
        pedido.anulado_por, pedido.anulado_en, pedido.motivo_anulacion = actor, ahora, motivo
        pedido.save(update_fields=['estado','estado_actualizado_en','anulado_por','anulado_en','motivo_anulacion'])
        registrar_evento(usuario=actor,accion=Auditoria.Accion.ELIMINADO_DESACTIVADO,modulo=Auditoria.Modulo.PEDIDOS,
            entidad='pedidos',registro_id=pedido.pk,descripcion='Se anuló un pedido.',anterior=anterior_estado,
            nuevo={'estado':'cancelado','motivo':motivo,'operacion_id':str(operacion),'apertura_id':apertura.pk})
        return {'accion':'anular','numero':pedido.numero,'creada':True}
    detalles = list(DetallesPedido.objects.select_for_update().filter(pedido=pedido).select_related('producto').order_by('producto_id','pk'))
    resumen = snapshot_pedido(pedido, detalles)
    if not resumen['cobrable']:
        raise ValidationError(resumen['advertencia'])
    if huella(resumen) != datos.get('items') or resumen['total'] != datos.get('total'):
        raise ValidationError('El detalle del pedido cambió. Abre de nuevo su resumen antes de cobrar.')
    apartadas = cantidades_apartadas(productos)
    for linea in resumen['items']:
        producto = productos.get(linea['id'])
        if producto is None:
            raise ValidationError('El detalle del pedido cambió. Abre de nuevo su resumen.')
        otras_reservas = max(0,apartadas.get(producto.pk,0)-linea['cantidad'])
        if producto.stock-otras_reservas < linea['cantidad']:
            raise ValidationError(f'{producto.nombre}: no hay stock suficiente para entregar este pedido respetando las demás reservas.')
    total = Decimal(resumen['total'])
    if recibido < total:
        raise ValidationError('El efectivo recibido es insuficiente para completar el cobro.')
    venta = _registrar_venta(actor=actor,apertura=apertura,lineas=resumen['items'],total=total,
        efectivo=recibido,operacion=operacion,pedido=pedido)
    pedido.estado, pedido.estado_actualizado_en = 'entregado', ahora
    pedido.save(update_fields=['estado','estado_actualizado_en'])
    registrar_evento(usuario=actor,accion=Auditoria.Accion.EDITADO,modulo=Auditoria.Modulo.PEDIDOS,
        entidad='pedidos',registro_id=pedido.pk,descripcion='Se entregó un pedido.',anterior=anterior_estado,
        nuevo={'estado':'entregado','venta_id':venta.pk})
    return {'accion':'cobrar','numero':pedido.numero,'venta':venta.numero,'total':dinero(total),
        'cambio':dinero(recibido-total),'creada':True}
