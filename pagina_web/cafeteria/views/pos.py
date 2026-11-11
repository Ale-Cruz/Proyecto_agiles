import json
from datetime import timedelta
from functools import wraps

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import OperationalError
from django.db.models import Prefetch, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .. import pos as operaciones
from .. import cobros_pedidos
from ..models import DetallesPedido, Pedidos, Productos, Ventas
from ..seguridad import controlar_intentos
from ..web import solo_empleados


def respuesta_error(error, status=409, **extra):
    texto = ' '.join(error.messages) if isinstance(error, ValidationError) else str(error)
    return JsonResponse({'error':texto, **extra}, status=status)


def json_pos(vista):
    @wraps(vista)
    def protegida(request, *args, **kwargs):
        try:
            if len(request.body) > 65536:
                raise ValidationError('La solicitud supera el tamaño permitido.')
            datos = json.loads(request.body)
            if not isinstance(datos, dict):
                raise ValidationError('La solicitud no es válida.')
            return vista(request, datos, *args, **kwargs)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return respuesta_error('La solicitud no es válida.', 400)
        except operaciones.ResumenCambio as error:
            return respuesta_error(error, resumen=error.resumen)
        except ValidationError as error:
            return respuesta_error(error)
        except PermissionDenied:
            return respuesta_error('Tu usuario no tiene permiso para realizar esta operación.', 403)
        except OperationalError:
            return respuesta_error('No se pudo completar la operación. Revisa el estado de la caja y vuelve a intentarlo.', 503)
    return protegida


def apertura_id(valor):
    if type(valor) is not int or not 0 < valor <= 4294967295:
        raise ValidationError('Actualiza la página del punto de venta.')
    return valor


@solo_empleados
@require_GET
def punto_venta(request):
    apertura = operaciones.apertura_actual()
    propia = apertura is not None and apertura.abierta_por_id == request.user.pk
    plantilla = 'cafeteria/pos/venta.html' if propia else 'cafeteria/pos/acceso.html'
    return render(request, plantilla, {'apertura':apertura, 'token_apertura':operaciones.token_apertura(request.user) if apertura is None else ''})


@solo_empleados
@require_GET
def pedidos_para_cobrar(request):
    try:
        raw = request.GET.get('apertura', '')
        if not raw.isascii() or not raw.isdigit() or len(raw) > 10:
            raise ValidationError('Actualiza la página del punto de venta.')
        operaciones.requerir_apertura(request.user, apertura_id(int(raw)))
        ahora = timezone.now()
        q = request.GET.get('q', '').strip()[:150]
        pedidos = Pedidos.objects.filter(estado='listo')
        if q:
            pedidos = pedidos.filter(Q(numero__icontains=q) | Q(estudiante__nombre__icontains=q))
        lineas = Prefetch('detallespedido_set', queryset=DetallesPedido.objects.select_related('producto').order_by('pk'), to_attr='lineas_comanda')
        pedidos = pedidos.select_related('estudiante').prefetch_related(lineas).order_by('estado_actualizado_en', 'pk')
        recientes, demorados = [], []
        for pedido in pedidos:
            pedido.minutos_espera = max(0, int((ahora-pedido.estado_actualizado_en).total_seconds()//60))
            (demorados if pedido.estado_actualizado_en <= ahora-timedelta(minutes=20) else recientes).append(pedido)
        return render(request, 'cafeteria/pos/_pedidos.html', {
            'pedidos_recientes':recientes, 'pedidos_demorados':demorados, 'busqueda':q,
        })
    except (ValidationError, PermissionDenied):
        return render(request, 'cafeteria/pos/_pedidos.html', {'error_pedidos':'La apertura cambió o pertenece a otro empleado. Actualiza la página.'})


@solo_empleados
@require_POST
@json_pos
def detalle_pedido(request, datos, pk):
    return JsonResponse(cobros_pedidos.resumen_pedido(usuario=request.user,
        apertura_id=apertura_id(datos.get('apertura')), pedido_id=pk))


@solo_empleados
@require_POST
@json_pos
def atender_pedido(request, datos):
    resultado = cobros_pedidos.procesar_pedido(usuario=request.user,
        cotizacion=datos.get('cotizacion'), accion=datos.get('accion'),
        operacion_id=datos.get('operacion_id'), efectivo=datos.get('efectivo'), motivo=datos.get('motivo'))
    if resultado['accion'] == 'cobrar':
        resultado['factura_url'] = reverse('pos_factura', kwargs={'numero':resultado['venta']})
    return JsonResponse(resultado)


@solo_empleados
@require_POST
@json_pos
def abrir_apertura(request, datos):
    operaciones.abrir_caja(usuario=request.user, monto=datos.get('monto'), token=datos.get('token'))
    return JsonResponse({'redirect':reverse('pos_inicio')})


@solo_empleados
@require_GET
def buscar_productos(request):
    try:
        raw = request.GET.get('apertura','')
        if not raw.isascii() or not raw.isdigit() or len(raw)>10:
            raise ValidationError('Actualiza la página del punto de venta.')
        operaciones.requerir_apertura(request.user, apertura_id(int(raw)))
        q = request.GET.get('q','').strip()[:150]
        qs = Productos.objects.filter(activo=True, disponible_para_venta=True, categoria__activo=True)
        if q:
            qs = qs.filter(Q(nombre__icontains=q)|Q(codigo__icontains=q))
        productos = list(qs.order_by('nombre','pk')[:30])
        apartadas = operaciones.cantidades_apartadas(p.pk for p in productos)
        return JsonResponse({'productos':[{'id':p.pk,'nombre':p.nombre,'codigo':p.codigo,
            'precio':operaciones.dinero(p.precio),'disponible':max(0,p.stock-apartadas.get(p.pk,0))} for p in productos]})
    except ValidationError as error:
        return respuesta_error(error)
    except PermissionDenied:
        return respuesta_error('La caja pertenece a otro empleado.', 403)


@solo_empleados
@require_POST
@json_pos
def cotizar_venta(request, datos):
    return JsonResponse(operaciones.cotizar(usuario=request.user, apertura_id=apertura_id(datos.get('apertura')), items=datos.get('items')))


@solo_empleados
@require_POST
@json_pos
def cobrar_venta(request, datos):
    venta, creada = operaciones.realizar_venta(usuario=request.user, cotizacion=datos.get('cotizacion'),
        efectivo=datos.get('efectivo'), operacion_id=datos.get('operacion_id'))
    return JsonResponse({'numero':venta.numero,'creada':creada,
        'factura_url':reverse('pos_factura', kwargs={'numero':venta.numero}),
        **operaciones.desglose(venta.total),'efectivo':operaciones.dinero(venta.efectivo_recibido),
        'cambio':operaciones.dinero(venta.efectivo_recibido-venta.total)})


@solo_empleados
@require_GET
def factura_venta(request, numero):
    venta = get_object_or_404(Ventas.objects.select_related('cajero','pedido__estudiante'), numero=numero)
    lineas = []
    for detalle in venta.detallesventa_set.select_related('producto').order_by('pk'):
        lineas.append({'nombre':detalle.producto.nombre, 'cantidad':detalle.cantidad,
            'precio':operaciones.dinero(detalle.precio_unitario),
            'importe':operaciones.dinero(detalle.precio_unitario*detalle.cantidad)})
    contexto = {'venta':venta, 'cliente':venta.pedido.estudiante.nombre if venta.pedido_id else 'Cliente general',
        'lineas_factura':lineas, **operaciones.desglose(venta.total),
        'efectivo':operaciones.dinero(venta.efectivo_recibido),
        'cambio':operaciones.dinero(venta.efectivo_recibido-venta.total)}
    if request.GET.get('formato') == 'json':
        return JsonResponse({'html':render_to_string('cafeteria/pos/_factura.html', contexto, request=request)})
    return render(request, 'cafeteria/pos/factura.html', contexto)


@solo_empleados
@require_POST
@json_pos
def verificar_cierre(request, datos):
    actor = operaciones.actor_actual(request.user)
    apertura = operaciones.requerir_apertura(actor, apertura_id(datos.get('apertura')))
    nombre, password = datos.get('usuario'), datos.get('password')
    if not isinstance(nombre,str) or not isinstance(password,str) or len(nombre)>150 or len(password)>256:
        return respuesta_error('Usuario o contraseña incorrectos.', 400)
    correcto = False
    with controlar_intentos(nombre, request.META.get('REMOTE_ADDR','')) as control:
        bloqueado = control.bloqueado
        if not bloqueado:
            correcto = nombre.strip().casefold()==actor.nombre.casefold() and actor.check_password(password)
            control.correcto = correcto
    if bloqueado:
        return respuesta_error('Demasiados intentos. Espera 15 minutos antes de volver a intentar.', 429)
    if not correcto:
        return respuesta_error('Usuario o contraseña incorrectos.', 400)
    return JsonResponse({'autorizacion':operaciones.autorizar_cierre(actor,apertura,request.session.session_key),
        'resumen':operaciones.resumen_apertura(apertura)})


@solo_empleados
@require_POST
@json_pos
def cerrar_apertura(request, datos):
    apertura = operaciones.cerrar_caja(usuario=request.user, autorizacion=datos.get('autorizacion'),
        sesion=request.session.session_key, contado=datos.get('contado'), esperado=datos.get('esperado'))
    messages.success(request, 'Caja cerrada correctamente.')
    return JsonResponse({'redirect':reverse('dashboard'), 'diferencia':operaciones.dinero(apertura.efectivo_contado-apertura.efectivo_esperado)})
