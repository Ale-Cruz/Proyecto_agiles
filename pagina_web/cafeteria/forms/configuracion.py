from django import forms


class HorarioForm(forms.Form):
    horarios_habilitados = forms.BooleanField(label='Activar horario', required=False,
        widget=forms.CheckboxInput(attrs={'id':'schedule-enabled'}))
    hora_inicio = forms.TimeField(label='Inicia', required=False, input_formats=['%H:%M'],
        widget=forms.TimeInput(format='%H:%M', attrs={'type':'time','class':'form-control','step':'60'}))
    hora_fin = forms.TimeField(label='Termina', required=False, input_formats=['%H:%M'],
        widget=forms.TimeInput(format='%H:%M', attrs={'type':'time','class':'form-control','step':'60'}))
    version = forms.CharField(widget=forms.HiddenInput)

    def clean(self):
        datos = super().clean()
        if datos.get('horarios_habilitados'):
            for campo in ('hora_inicio','hora_fin'):
                if not datos.get(campo) and campo not in self.errors:
                    self.add_error(campo, 'Selecciona una hora.')
            if datos.get('hora_inicio') and datos.get('hora_fin') and datos['hora_inicio'] >= datos['hora_fin']:
                self.add_error('hora_fin', 'La hora final debe ser posterior a la inicial.')
        return datos
