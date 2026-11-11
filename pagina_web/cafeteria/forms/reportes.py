from django import forms

from ..models import Categorias, MovimientosInventario, Pedidos


class FiltrosReporteForm(forms.Form):
    q = forms.CharField(label='Buscar', required=False, max_length=150,
        widget=forms.TextInput(attrs={'type':'search', 'placeholder':'Buscar', 'autocomplete':'off'}))
    desde = forms.DateField(label='Desde', required=False, input_formats=['%Y-%m-%d'],
        widget=forms.DateInput(attrs={'type':'date'}, format='%Y-%m-%d'))
    hasta = forms.DateField(label='Hasta', required=False, input_formats=['%Y-%m-%d'],
        widget=forms.DateInput(attrs={'type':'date'}, format='%Y-%m-%d'))
    estado = forms.ChoiceField(label='Estado', required=False)
    origen = forms.ChoiceField(label='Origen', required=False,
        choices=[('', 'Todos'), ('presencial', 'Venta directa'), ('pedido', 'Pedido')])
    responsable = forms.CharField(label='Responsable', required=False, max_length=150,
        widget=forms.TextInput(attrs={'placeholder':'Nombre del empleado'}))
    categoria = forms.ModelChoiceField(label='Categoría', required=False,
        queryset=Categorias.objects.none(), empty_label='Todas')
    tipo = forms.ChoiceField(label='Tipo', required=False,
        choices=[('', 'Todos'), *MovimientosInventario._meta.get_field('tipo').choices])
    venta = forms.ChoiceField(label='Venta habilitada', required=False,
        choices=[('', 'Todos'), ('habilitado', 'Sí'), ('deshabilitado', 'No')])

    def __init__(self, *args, tipo, **kwargs):
        super().__init__(*args, **kwargs)
        campos = {
            'ventas':('q','desde','hasta','estado','origen','responsable'),
            'pedidos':('q','desde','hasta','estado'),
            'caja':('responsable','desde','hasta','estado'),
            'inventario':('q','categoria','estado','venta'),
            'movimientos':('q','desde','hasta','tipo','responsable','categoria'),
        }[tipo]
        self.fields = {nombre:self.fields[nombre] for nombre in campos}
        estados = {
            'ventas':[('completada','Completada'),('anulada','Anulada')],
            'pedidos':Pedidos._meta.get_field('estado').choices,
            'caja':[('abierta','Abierta'),('cerrada','Cerrada')],
            'inventario':[('agotado','Sin stock físico'),('bajo','Stock bajo mínimo'),('normal','Stock sobre mínimo')],
        }
        if 'estado' in self.fields:
            self.fields['estado'].choices = [('', 'Todos'), *estados[tipo]]
        if 'categoria' in self.fields:
            self.fields['categoria'].queryset = Categorias.objects.order_by('nombre','pk')
        if 'q' in self.fields:
            self.fields['q'].widget.attrs['placeholder'] = {
                'ventas':'Número de venta o cliente', 'pedidos':'Número de pedido o estudiante',
                'inventario':'Nombre o código del producto', 'movimientos':'Producto, código o motivo',
            }[tipo]
        if tipo == 'ventas':
            self.fields['responsable'].label = 'Cajero'
        if tipo == 'caja':
            self.fields['responsable'].label = 'Abierta por'
            self.fields['desde'].label, self.fields['hasta'].label = 'Desde apertura', 'Hasta apertura'
        for campo in self.fields.values():
            campo.widget.attrs['class'] = 'form-select' if isinstance(campo.widget, forms.Select) else 'form-control'

    def clean(self):
        datos = super().clean()
        for nombre in ('desde','hasta'):
            valor = datos.get(nombre)
            if valor and not 1900 <= valor.year <= 9998:
                self.add_error(nombre, 'La fecha debe estar entre los años 1900 y 9998.')
        if datos.get('desde') and datos.get('hasta') and datos['desde'] > datos['hasta']:
            self.add_error('hasta', 'La fecha final debe ser igual o posterior a la inicial.')
        return datos
