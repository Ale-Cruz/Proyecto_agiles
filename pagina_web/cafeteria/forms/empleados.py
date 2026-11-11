from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from ..models import Usuarios


ROLES_EMPLEADOS = (('administrador', 'Administrador'), ('cajero', 'Cajero'))


class EmpleadoForm(forms.ModelForm):
    nombre = forms.CharField(label='Nombre de usuario', max_length=150)
    correo = forms.EmailField(label='Correo', max_length=254)
    rol = forms.ChoiceField(label='Rol', choices=ROLES_EMPLEADOS)
    habilitado = forms.BooleanField(label='Cuenta habilitada', required=False, initial=True)
    password1 = forms.CharField(label='Contraseña', required=False, strip=False, max_length=128,
                                widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}))
    password2 = forms.CharField(label='Confirmar contraseña', required=False, strip=False, max_length=128,
                                widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}))

    class Meta:
        model = Usuarios
        fields = ['nombre', 'correo', 'rol', 'habilitado']

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        self.es_nuevo = self.instance.pk is None
        if self.es_nuevo:
            self.initial['rol'] = 'cajero'
        self.fields['password1'].required = self.es_nuevo
        self.fields['password2'].required = self.es_nuevo
        self.fields['nombre'].widget.attrs.update({'autocomplete': 'off', 'autofocus': True, 'spellcheck': 'false'})
        for campo in self.fields.values():
            campo.widget.attrs['class'] = ('form-check-input' if isinstance(campo.widget, forms.CheckboxInput)
                                           else 'form-select' if isinstance(campo.widget, forms.Select) else 'form-control')
        if self.instance.es_cuenta_principal:
            self.fields['nombre'].widget.attrs['readonly'] = True
            self.fields['rol'].widget.attrs['disabled'] = True
            self.fields['habilitado'].widget.attrs['disabled'] = True

    def clean_nombre(self):
        nombre = self.cleaned_data['nombre'].strip()
        if self.instance.es_cuenta_principal and nombre != self.instance.nombre:
            raise ValidationError('El nombre de la cuenta admin es permanente.')
        if '@' in nombre:
            raise ValidationError('Usa un nombre de usuario, no un correo.')
        if Usuarios.objects.filter(rol__in=dict(ROLES_EMPLEADOS), nombre__iexact=nombre).exclude(pk=self.instance.pk).exists():
            raise ValidationError('Este nombre de usuario ya está en uso.')
        return nombre

    def clean_correo(self):
        return self.cleaned_data['correo'].strip().lower()

    def clean(self):
        datos = super().clean()
        clave = datos.get('password1')
        confirmacion = datos.get('password2')
        if clave != confirmacion:
            self.add_error('password2', 'Las contraseñas no coinciden.')
        if clave:
            try:
                validate_password(clave, self.instance)
            except ValidationError as error:
                self.add_error('password1', error)
        if self.instance.es_cuenta_principal:
            if datos.get('rol') != 'administrador':
                self.add_error('rol', 'La cuenta admin debe conservar el rol de administrador.')
            if not datos.get('habilitado'):
                self.add_error('habilitado', 'La cuenta admin debe permanecer habilitada.')
        elif self.instance.pk == self.actor.pk:
            if datos.get('rol') != 'administrador':
                self.add_error('rol', 'No puedes quitarte el rol de administrador.')
            if not datos.get('habilitado'):
                self.add_error('habilitado', 'No puedes deshabilitar tu propia cuenta.')
        if (self.instance.pk and self.instance.rol == 'administrador' and self.instance.habilitado
                and (datos.get('rol') != 'administrador' or not datos.get('habilitado'))
                and not Usuarios.objects.filter(rol='administrador', habilitado=True).exclude(pk=self.instance.pk).exists()):
            raise ValidationError('Debe permanecer al menos un administrador habilitado.')
        return datos

    def save(self, commit=True):
        empleado = super().save(commit=False)
        if self.cleaned_data.get('password1'):
            empleado.set_password(self.cleaned_data['password1'])
            empleado.token_sesion_hash = None
            empleado.sesion_expira_en = None
        if commit:
            empleado.save()
        return empleado
