from django import forms
from django.contrib.auth.forms import AuthenticationForm


class AccesoEmpleadosForm(AuthenticationForm):
    username = forms.CharField(
        label='Usuario', max_length=150,
        widget=forms.TextInput(attrs={
            'class': 'form-control', 'placeholder': 'Tu usuario de empleado',
            'autocomplete': 'username', 'autofocus': True, 'spellcheck': 'false',
        }),
    )
    password = forms.CharField(
        label='Contraseña', strip=False, max_length=128,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control', 'placeholder': 'Tu contraseña',
            'autocomplete': 'current-password',
        }),
    )
    error_messages = {
        'invalid_login': 'Usuario o contraseña incorrectos.',
        'inactive': 'Usuario o contraseña incorrectos.',
    }
