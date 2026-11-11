import uuid

from django import forms
from django.db.models import Q

from ..models import Categorias, Productos


MAX_STOCK = 2147483647


def presentar_campos(form):
    for campo in form.fields.values():
        campo.widget.attrs['class'] = ('form-check-input' if isinstance(campo.widget, forms.CheckboxInput)
            else 'form-select' if isinstance(campo.widget, forms.Select) else 'form-control')
    primero = next((c for c in form.fields.values() if not c.widget.is_hidden), None)
    if primero:
        primero.widget.attrs['autofocus'] = True


class CategoriaForm(forms.ModelForm):
    class Meta:
        model = Categorias
        fields = ['nombre', 'activo']
        labels = {'nombre':'Nombre', 'activo':'Categoría activa'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        presentar_campos(self)

    def clean_nombre(self):
        nombre = self.cleaned_data['nombre'].strip()
        if Categorias.objects.filter(nombre__iexact=nombre).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('Ya existe una categoría con ese nombre.')
        return nombre


class ProductoForm(forms.ModelForm):
    imagen = forms.ImageField(label='Fotografía', required=False, help_text='JPG, PNG o WEBP. Máximo 5 MB.')
    quitar_imagen = forms.BooleanField(label='Quitar fotografía actual', required=False)
    precio = forms.DecimalField(label='Precio ($)', max_digits=12, decimal_places=2, min_value=0)
    stock_minimo = forms.IntegerField(label='Stock mínimo', min_value=0, max_value=MAX_STOCK, initial=0)

    class Meta:
        model = Productos
        fields = ['nombre', 'codigo', 'categoria', 'descripcion', 'precio', 'stock_minimo', 'disponible_para_venta', 'activo']
        labels = {'codigo':'Código', 'categoria':'Categoría', 'descripcion':'Descripción',
                  'disponible_para_venta':'Habilitado para venta', 'activo':'Producto activo'}
        widgets = {'descripcion':forms.Textarea(attrs={'rows':2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        categorias = Q(activo=True)
        if self.instance.pk:
            categorias |= Q(pk=self.instance.categoria_id)
        self.fields['categoria'].queryset = Categorias.objects.filter(categorias).order_by('nombre')
        self.fields['codigo'].widget.attrs['autocomplete'] = 'off'
        self.fields['imagen'].widget.attrs['accept'] = 'image/jpeg,image/png,image/webp'
        if not self.instance.fotografia:
            self.fields.pop('quitar_imagen')
        presentar_campos(self)

    def clean_codigo(self):
        codigo = self.cleaned_data['codigo'].strip()
        if Productos.objects.filter(codigo__iexact=codigo).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('Ya existe un producto con ese código.')
        return codigo

    def clean_imagen(self):
        imagen = self.cleaned_data.get('imagen')
        if imagen:
            if imagen.size > 5 * 1024 * 1024:
                raise forms.ValidationError('La fotografía no puede superar 5 MB.')
            if imagen.image.format not in ('JPEG', 'PNG', 'WEBP') or imagen.image.width * imagen.image.height > 16000000:
                raise forms.ValidationError('Usa una imagen JPG, PNG o WEBP de hasta 16 megapíxeles.')
        return imagen


class MovimientoForm(forms.Form):
    producto = forms.ModelChoiceField(label='Producto', queryset=Productos.objects.none(), widget=forms.HiddenInput)
    operacion = forms.ChoiceField(label='Operación', choices=[('entrada','Entrada'), ('salida','Salida')])
    cantidad = forms.IntegerField(label='Cantidad', min_value=1, max_value=MAX_STOCK)
    motivo = forms.CharField(label='Motivo', max_length=1000, widget=forms.Textarea(attrs={'rows':2}))
    operacion_id = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, producto=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['producto'].queryset = Productos.objects.order_by('nombre', 'codigo')
        self.initial['operacion_id'] = uuid.uuid4()
        if producto:
            self.initial['producto'] = producto.pk
        presentar_campos(self)
        self.fields['operacion'].widget.attrs.pop('autofocus', None)
