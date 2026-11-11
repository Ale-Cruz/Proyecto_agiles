from django.contrib import messages
from django.core import signing
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from ..configuracion import estado_horario, guardar_horario, leer_horario
from ..forms.configuracion import HorarioForm
from ..web import solo_administradores


@solo_administradores
@require_http_methods(['GET','POST'])
def configuracion_horario(request):
    configuracion, horarios = leer_horario()
    estado = estado_horario(configuracion, horarios)
    activos = [h for h in horarios if h.activo]
    rangos = {(h.hora_inicio,h.hora_fin) for h in activos}
    valores = next(iter(rangos)) if len(rangos) == 1 else (None,None)
    inicial = {'horarios_habilitados':estado['habilitado'], 'hora_inicio':valores[0], 'hora_fin':valores[1],
        'version':signing.dumps(estado, salt='cafeteria.horario', compress=True)}
    form = HorarioForm(request.POST if request.method == 'POST' else None, initial=inicial)
    if request.method == 'POST' and form.is_valid():
        try:
            guardar_horario(usuario=request.user, habilitado=form.cleaned_data['horarios_habilitados'],
                hora_inicio=form.cleaned_data['hora_inicio'], hora_fin=form.cleaned_data['hora_fin'],
                version=form.cleaned_data['version'])
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, 'Horario guardado.')
            return redirect('configuracion_horario')
    return render(request, 'cafeteria/configuracion/horario.html', {
        'form':form, 'horario_habilitado':estado['habilitado'], 'horarios_distintos':len(rangos)>1})
