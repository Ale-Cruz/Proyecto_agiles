"""Aperturas, cobros y cierres atómicos de la única caja física."""
import secrets
import uuid
from decimal import Decimal, ROUND_HALF_UP

from django import forms
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.crypto import salted_hmac

from .auditoria import registrar_evento
from .models import (Auditoria, Caja, Categorias, DetallesCarrito, DetallesPedido,
                     DetallesVenta, MovimientosCaja, MovimientosInventario, Productos, Usuarios, Ventas)

CENTAVO = Decimal('0.01')
MAX_DINERO = Decimal('9999999999.99')
CAMPO_DINERO = forms.DecimalField(min_value=0, max_digits=12, decimal_places=2)


def dinero(valor):
    return format(Decimal(valor).quantize(CENTAVO, rounding=ROUND_HALF_UP), '.2f')


def importe(valor):
    if isinstance(valor, (bool, float)) or not isinstance(valor, (str, int, Decimal)):
        raise ValidationError('Ingresa un monto válido con un máximo de dos decimales.')
    return CAMPO_DINERO.clean(valor)


def desglose(total):
    total = Decimal(dinero(total))
    base = (total / Decimal('1.13')).quantize(CENTAVO, rounding=ROUND_HALF_UP)
    return {'subtotal': dinero(base), 'iva': dinero(total-base), 'total': dinero(total)}


def actor_actual(usuario, *, bloquear=False):
    qs = Usuarios.objects.select_for_update() if bloquear else Usuarios.objects
    actor = qs.filter(pk=usuario.pk, habilitado=True, rol__in=('administrador','cajero')).first()
    if actor is None:
        raise PermissionDenied
    return actor


def apertura_actual():
    return Caja.objects.filter(estado='abierta').select_related('abierta_por').first()


def requerir_apertura(usuario, apertura_id, *, bloquear=False):
    qs = Caja.objects.select_for_update() if bloquear else Caja.objects
    apertura = qs.filter(pk=apertura_id, estado='abierta').first()
    if apertura is None:
        raise ValidationError('La apertura ya no está disponible. Actualiza el punto de venta.')
    if apertura.abierta_por_id != usuario.pk:
        raise PermissionDenied('Solo quien abrió la caja puede operar en ella.')
    return apertura


def token_apertura(usuario):
    ultima = Caja.objects.order_by('-pk').values_list('pk', flat=True).first()
    return signing.dumps({'usuario':usuario.pk, 'ultima':ultima}, salt='pos.apertura')


@transaction.atomic
def abrir_caja(*, usuario, monto, token):
    actor = actor_actual(usuario, bloquear=True)
    monto = importe(monto)
    try:
        datos = signing.loads(token, salt='pos.apertura', max_age=900)
    except (signing.BadSignature, TypeError):
        raise ValidationError('Actualiza la página antes de abrir la caja.') from None
    if datos.get('usuario') != actor.pk:
        raise PermissionDenied
    abierta = Caja.objects.select_for_update().filter(estado='abierta').first()
    if abierta:
        if abierta.abierta_por_id == actor.pk:
            return abierta
        raise ValidationError('Otro empleado ya tiene la caja abierta. Debe cerrarla antes de continuar.')
    ultima = Caja.objects.order_by('-pk').values_list('pk', flat=True).first()
    if ultima != datos.get('ultima'):
        raise ValidationError('La caja cambió. Actualiza la página antes de abrirla.')
    try:
        with transaction.atomic():
            apertura = Caja.objects.create(abierta_por=actor, monto_inicial=monto, estado='abierta', observaciones='')
    except IntegrityError:
        raise ValidationError('La caja ya fue abierta en otra sesión. Actualiza la página.') from None
    registrar_evento(usuario=actor, accion=Auditoria.Accion.ANADIDO, modulo=Auditoria.Modulo.CAJA,
        entidad='aperturas_caja', registro_id=apertura.pk, descripcion='Se registró una apertura de caja.',
        nuevo={'monto_inicial':dinero(monto), 'estado':'abierta'})
    return apertura


def cantidades_apartadas(producto_ids):
    ids = list(producto_ids)
    resultado = dict(DetallesPedido.objects.filter(producto_id__in=ids,
        pedido__estado__in=('en_preparacion','listo')).values('producto_id').annotate(cantidad=Sum('cantidad')).values_list('producto_id','cantidad'))
    carritos = DetallesCarrito.objects.filter(producto_id__in=ids, carrito__expira_en__gt=timezone.now()).values('producto_id').annotate(cantidad=Sum('cantidad'))
    for fila in carritos:
        resultado[fila['producto_id']] = resultado.get(fila['producto_id'], 0) + fila['cantidad']
    return resultado


def normalizar_items(items):
    if not isinstance(items, list) or not 1 <= len(items) <= 100:
        raise ValidationError('Añade entre 1 y 100 productos a la venta.')
    resultado = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValidationError('La lista de productos no es válida.')
        pid, cantidad = item.get('id'), item.get('cantidad')
        if type(pid) is not int or type(cantidad) is not int or not 0 < pid <= 2147483647 or not 0 < cantidad <= 2147483647 or pid in resultado:
            raise ValidationError('Revisa los productos y sus cantidades.')
        resultado[pid] = cantidad
    return dict(sorted(resultado.items()))


def calcular_items(items, *, bloquear=False):
    cantidades = normalizar_items(items)
    if bloquear:
        # El catálogo toma las categorías antes que los productos: mismo orden de bloqueo.
        list(Categorias.objects.select_for_update().order_by('pk'))
        productos = list(Productos.objects.select_for_update().filter(pk__in=cantidades).order_by('pk'))
        categorias = {c.pk:c for c in Categorias.objects.filter(pk__in=[p.categoria_id for p in productos])}
    else:
        productos = list(Productos.objects.filter(pk__in=cantidades).select_related('categoria').order_by('pk'))
        categorias = {p.categoria_id:p.categoria for p in productos}
    if len(productos) != len(cantidades):
        raise ValidationError('Uno de los productos ya no existe. Revisa la venta.')
    apartadas = cantidades_apartadas(cantidades)
    lineas, total = [], Decimal('0.00')
    for producto in productos:
        if not (producto.activo and producto.disponible_para_venta and categorias[producto.categoria_id].activo):
            raise ValidationError(f'{producto.nombre} ya no está habilitado para vender.')
        disponible = max(0, producto.stock-apartadas.get(producto.pk, 0))
        cantidad = cantidades[producto.pk]
        if cantidad > disponible:
            raise ValidationError(f'{producto.nombre}: solo hay {disponible} unidades disponibles.')
        importe_linea = producto.precio*cantidad
        total += importe_linea
        lineas.append({'id':producto.pk, 'nombre':producto.nombre, 'codigo':producto.codigo,
            'cantidad':cantidad, 'precio':dinero(producto.precio), 'importe':dinero(importe_linea), 'disponible':disponible})
    if total > MAX_DINERO:
        raise ValidationError('El total de la venta supera el monto permitido.')
    return lineas, desglose(total)


def cotizar(*, usuario, apertura_id, items):
    actor = actor_actual(usuario)
    requerir_apertura(actor, apertura_id)
    lineas, totales = calcular_items(items)
    payload = {'usuario':actor.pk, 'apertura':apertura_id, 'items':[
        {'id':l['id'], 'cantidad':l['cantidad'], 'precio':l['precio']} for l in lineas], 'total':totales['total']}
    return {'items':lineas, **totales, 'cotizacion':signing.dumps(payload, salt='pos.venta', compress=True)}


@transaction.atomic
def realizar_venta(*, usuario, cotizacion, efectivo, operacion_id):
    actor = actor_actual(usuario, bloquear=True)
    efectivo = importe(efectivo)
    try:
        operacion = uuid.UUID(str(operacion_id))
        datos = signing.loads(cotizacion, salt='pos.venta')
    except (ValueError, TypeError, signing.BadSignature):
        raise ValidationError('La venta no es válida. Revisa los productos y vuelve a confirmar.') from None
    if datos.get('usuario') != actor.pk:
        raise PermissionDenied
    anterior = Ventas.objects.filter(operacion_id=operacion).first()
    if anterior:
        lineas = list(anterior.detallesventa_set.order_by('producto_id').values('producto_id','cantidad','precio_unitario'))
        esperado = [{'id':l['producto_id'], 'cantidad':l['cantidad'], 'precio':dinero(l['precio_unitario'])} for l in lineas]
        if (anterior.cajero_id != actor.pk or anterior.caja_id != datos.get('apertura') or esperado != datos.get('items') or anterior.efectivo_recibido != efectivo or dinero(anterior.total) != datos.get('total')):
            raise ValidationError('Esta operación ya fue utilizada para otra venta. Actualiza el POS.')
        return anterior, False
    try:
        signing.loads(cotizacion, salt='pos.venta', max_age=300)
    except signing.SignatureExpired:
        raise ValidationError('La venta lleva varios minutos sin actualizarse. Revisa y confirma de nuevo.') from None
    apertura = requerir_apertura(actor, datos.get('apertura'), bloquear=True)
    lineas, totales = calcular_items(datos['items'], bloquear=True)
    actuales = [{'id':l['id'], 'cantidad':l['cantidad'], 'precio':l['precio']} for l in lineas]
    if actuales != datos['items'] or totales['total'] != datos['total']:
        raise ValidationError('Los precios cambiaron. Revisa el total y confirma de nuevo.')
    total = Decimal(totales['total'])
    if efectivo < total:
        raise ValidationError('El efectivo recibido es insuficiente para completar la venta.')
    return _registrar_venta(actor=actor, apertura=apertura, lineas=lineas, total=total,
        efectivo=efectivo, operacion=operacion), True


def _registrar_venta(*, actor, apertura, lineas, total, efectivo, operacion, pedido=None):
    """Llamar dentro de una transacción, con apertura y productos bloqueados."""
    for _ in range(40):
        numero = 'VTA-' + ''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(8))
        try:
            with transaction.atomic():
                venta = Ventas.objects.create(numero=numero, operacion_id=operacion, caja=apertura, pedido=pedido,
                    cajero=actor, total=total, efectivo_recibido=efectivo, estado='completada')
            break
        except IntegrityError:
            if Ventas.objects.filter(operacion_id=operacion).exists():
                raise ValidationError('La operación ya se procesó. Revisa el resultado antes de repetirla.') from None
            if pedido is not None and Ventas.objects.filter(pedido=pedido).exists():
                raise ValidationError('Este pedido ya tiene un cobro registrado.') from None
    else:
        raise ValidationError('No se pudo asignar un número a la venta. Intenta de nuevo.')
    motivo = 'Cobro de pedido.' if pedido else 'Venta en punto de venta.'
    for linea in lineas:
        detalle = DetallesVenta.objects.create(venta=venta, producto_id=linea['id'], cantidad=linea['cantidad'], precio_unitario=linea['precio'])
        producto = Productos.objects.get(pk=linea['id'])
        producto.stock -= linea['cantidad']
        producto.save(update_fields=['stock'])
        MovimientosInventario.objects.create(producto=producto, usuario=actor, detalle_venta=detalle,
            tipo='salida_venta', cantidad=linea['cantidad'], motivo=motivo,
            operacion_id=uuid.uuid5(operacion, str(producto.pk)))
    if total > 0:
        MovimientosCaja.objects.create(caja=apertura, usuario=actor, venta=venta, tipo='ingreso_venta', monto=total, motivo=motivo)
    registrar_evento(usuario=actor, accion=Auditoria.Accion.ANADIDO, modulo=Auditoria.Modulo.VENTAS,
        entidad='ventas', registro_id=venta.pk, descripcion='Se registró una venta.',
        nuevo={'numero':venta.numero, 'total':dinero(total), 'efectivo_recibido':dinero(efectivo),
               'cambio':dinero(efectivo-total), 'apertura_id':apertura.pk, 'pedido_id':pedido.pk if pedido else None})
    return venta


def resumen_apertura(apertura):
    grupos = dict(MovimientosCaja.objects.filter(caja=apertura).values('tipo').annotate(total=Sum('monto')).values_list('tipo','total'))
    ventas = grupos.get('ingreso_venta', Decimal('0'))
    otros = grupos.get('ingreso_adicional', Decimal('0'))-grupos.get('retiro', Decimal('0'))-grupos.get('devolucion', Decimal('0'))
    return {'monto_inicial':dinero(apertura.monto_inicial), 'ventas':dinero(ventas), 'otros':dinero(otros),
            'esperado':dinero(apertura.monto_inicial+ventas+otros)}


def firma_sesion(sesion):
    return salted_hmac('pos.cierre.sesion', sesion or '').hexdigest()


def autorizar_cierre(usuario, apertura, sesion):
    return signing.dumps({'usuario':usuario.pk, 'apertura':apertura.pk,
        'credencial':usuario.get_session_auth_hash(), 'sesion':firma_sesion(sesion)}, salt='pos.cierre')


class ResumenCambio(ValidationError):
    def __init__(self, resumen):
        self.resumen = resumen
        super().__init__('Hubo movimientos mientras contabas. Revisa el efectivo esperado y confirma de nuevo.')


@transaction.atomic
def cerrar_caja(*, usuario, autorizacion, sesion, contado, esperado):
    actor = actor_actual(usuario, bloquear=True)
    contado, esperado = importe(contado), importe(esperado)
    try:
        datos = signing.loads(autorizacion, salt='pos.cierre', max_age=300)
    except (signing.BadSignature, TypeError):
        raise ValidationError('Verifica de nuevo tus credenciales para cerrar la caja.') from None
    if (datos.get('usuario') != actor.pk or datos.get('credencial') != actor.get_session_auth_hash()
            or datos.get('sesion') != firma_sesion(sesion)):
        raise PermissionDenied
    apertura = Caja.objects.select_for_update().filter(pk=datos.get('apertura'), abierta_por=actor).first()
    if apertura is None:
        raise PermissionDenied
    if apertura.estado == 'cerrada':
        if apertura.cerrada_por_id == actor.pk and apertura.efectivo_contado == contado:
            return apertura
        raise ValidationError('Esta apertura ya está cerrada.')
    resumen = resumen_apertura(apertura)
    if Decimal(resumen['esperado']) != esperado:
        raise ResumenCambio(resumen)
    apertura.estado, apertura.cerrada_por, apertura.cerrada_en = 'cerrada', actor, timezone.now()
    apertura.efectivo_esperado, apertura.efectivo_contado = esperado, contado
    apertura.save(update_fields=['estado','cerrada_por','cerrada_en','efectivo_esperado','efectivo_contado'])
    registrar_evento(usuario=actor, accion=Auditoria.Accion.EDITADO, modulo=Auditoria.Modulo.CAJA,
        entidad='aperturas_caja', registro_id=apertura.pk, descripcion='Se registró un cierre de caja.',
        anterior={'estado':'abierta'}, nuevo={'estado':'cerrada','efectivo_esperado':dinero(esperado),
            'efectivo_contado':dinero(contado), 'diferencia':dinero(contado-esperado)})
    return apertura
