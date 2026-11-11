"""Modelos de la BD existente sistema_pedidos; las tablas se administran en MySQL."""

from decimal import Decimal

from django.db import models
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.hashers import check_password
from django.utils import timezone


class Auditoria(models.Model):
    class Accion(models.TextChoices):
        ANADIDO = 'Añadido', 'Añadido'
        EDITADO = 'Editado', 'Editado'
        ELIMINADO_DESACTIVADO = 'Eliminado/desactivado', 'Eliminado/desactivado'

    class Modulo(models.TextChoices):
        USUARIOS = 'Usuarios', 'Usuarios'
        PRODUCTOS = 'Productos', 'Productos'
        INVENTARIO = 'Inventario', 'Inventario'
        CATEGORIAS = 'Categorías', 'Categorías'
        VENTAS = 'Ventas', 'Ventas'
        CAJA = 'Caja', 'Caja'
        PEDIDOS = 'Pedidos', 'Pedidos'
        CONFIGURACION = 'Configuración', 'Configuración'
        GENERAL = 'General', 'General'

    id = models.AutoField(primary_key=True)
    usuario = models.ForeignKey('Usuarios', models.DO_NOTHING, blank=True, null=True, db_comment='NULL para una accion automatica')
    accion = models.CharField(max_length=100, choices=Accion.choices)
    modulo = models.CharField(max_length=50, choices=Modulo.choices, default=Modulo.GENERAL)
    entidad_afectada = models.CharField(max_length=100)
    registro_afectado_id = models.IntegerField()
    descripcion = models.TextField()
    valor_anterior = models.JSONField(blank=True, null=True)
    valor_nuevo = models.JSONField(blank=True, null=True)
    creado_en = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = False
        db_table = 'auditoria'
        indexes = [
            models.Index(fields=['-creado_en', '-id'], name='idx_auditoria_fecha'),
            models.Index(fields=['modulo', '-creado_en'], name='idx_auditoria_modulo'),
            models.Index(fields=['accion', '-creado_en'], name='idx_auditoria_accion'),
        ]


class Caja(models.Model):
    id = models.AutoField(primary_key=True)
    abierta_por = models.ForeignKey('Usuarios', models.DO_NOTHING, db_column='abierta_por')
    abierta_en = models.DateTimeField(default=timezone.now)
    monto_inicial = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    estado = models.CharField(max_length=7, choices=[('abierta', 'Abierta'), ('cerrada', 'Cerrada')], default='abierta')
    cerrada_por = models.ForeignKey('Usuarios', models.DO_NOTHING, db_column='cerrada_por', related_name='caja_cerrada_por_set', blank=True, null=True)
    cerrada_en = models.DateTimeField(blank=True, null=True)
    efectivo_esperado = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    efectivo_contado = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    observaciones = models.TextField()
    activa_unica = models.GeneratedField(
        expression=models.Case(models.When(estado='abierta', then=models.Value(1)), default=models.Value(None), output_field=models.PositiveIntegerField()),
        output_field=models.PositiveIntegerField(), db_persist=True, unique=True, null=True,
    )

    class Meta:
        managed = False
        db_table = 'aperturas_caja'


class Carritos(models.Model):
    id = models.AutoField(primary_key=True)
    usuario = models.OneToOneField('Usuarios', models.DO_NOTHING)
    ultima_actividad = models.DateTimeField(default=timezone.now)
    expira_en = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'carritos'


class Categorias(models.Model):
    id = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=100, unique=True)
    activo = models.BooleanField(default=True)

    def __str__(self):
        return self.nombre

    class Meta:
        managed = False
        db_table = 'categorias'


class Configuracion(models.Model):
    id = models.AutoField(primary_key=True)
    minutos_carrito = models.IntegerField(default=10)
    horarios_habilitados = models.BooleanField(default=False)

    class Meta:
        managed = False
        db_table = 'configuracion'


class DetallesCarrito(models.Model):
    id = models.AutoField(primary_key=True)
    carrito = models.ForeignKey(Carritos, models.DO_NOTHING)
    producto = models.ForeignKey('Productos', models.DO_NOTHING)
    cantidad = models.IntegerField()

    class Meta:
        managed = False
        db_table = 'detalles_carrito'


class DetallesPedido(models.Model):
    id = models.AutoField(primary_key=True)
    pedido = models.ForeignKey('Pedidos', models.DO_NOTHING)
    producto = models.ForeignKey('Productos', models.DO_NOTHING)
    cantidad = models.IntegerField()
    precio_unitario = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        managed = False
        db_table = 'detalles_pedido'


class DetallesVenta(models.Model):
    id = models.AutoField(primary_key=True)
    venta = models.ForeignKey('Ventas', models.DO_NOTHING)
    producto = models.ForeignKey('Productos', models.DO_NOTHING)
    cantidad = models.IntegerField()
    precio_unitario = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        managed = False
        db_table = 'detalles_venta'


class HorariosPedidos(models.Model):
    id = models.AutoField(primary_key=True)
    configuracion = models.ForeignKey(Configuracion, models.DO_NOTHING)
    dia_semana = models.IntegerField(db_comment='1=lunes, 2=martes, ... 7=domingo')
    hora_inicio = models.TimeField()
    hora_fin = models.TimeField()
    activo = models.BooleanField(default=True)

    class Meta:
        managed = False
        db_table = 'horarios_pedidos'


class MovimientosCaja(models.Model):
    id = models.AutoField(primary_key=True)
    caja = models.ForeignKey(Caja, models.DO_NOTHING)
    usuario = models.ForeignKey('Usuarios', models.DO_NOTHING)
    venta = models.ForeignKey('Ventas', models.DO_NOTHING, blank=True, null=True)
    tipo = models.CharField(max_length=17, choices=[('ingreso_venta', 'Ingreso venta'), ('ingreso_adicional', 'Ingreso adicional'), ('retiro', 'Retiro'), ('devolucion', 'Devolucion')])
    monto = models.DecimalField(max_digits=12, decimal_places=2)
    motivo = models.TextField()
    creado_en = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = False
        db_table = 'movimientos_caja'


class MovimientosInventario(models.Model):
    id = models.AutoField(primary_key=True)
    producto = models.ForeignKey('Productos', models.DO_NOTHING)
    usuario = models.ForeignKey('Usuarios', models.DO_NOTHING)
    detalle_venta = models.ForeignKey(DetallesVenta, models.DO_NOTHING, blank=True, null=True)
    tipo = models.CharField(max_length=15, choices=[('entrada', 'Entrada'), ('salida_venta', 'Salida venta'), ('salida_manual', 'Salida manual'), ('ajuste_entrada', 'Ajuste entrada'), ('ajuste_salida', 'Ajuste salida'), ('reversion_venta', 'Reversion venta')])
    cantidad = models.IntegerField()
    motivo = models.TextField()
    creado_en = models.DateTimeField(default=timezone.now)
    operacion_id = models.UUIDField(unique=True, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'movimientos_inventario'


class Pedidos(models.Model):
    id = models.AutoField(primary_key=True)
    numero = models.CharField(unique=True, max_length=50)
    operacion_id = models.UUIDField(unique=True, blank=True, null=True)
    estudiante = models.ForeignKey('Usuarios', models.DO_NOTHING)
    estado = models.CharField(max_length=14, choices=[('pendiente', 'Pendiente'), ('en_preparacion', 'En preparacion'), ('listo', 'Listo'), ('entregado', 'Entregado'), ('cancelado', 'Cancelado')], default='pendiente')
    creado_en = models.DateTimeField(default=timezone.now)
    estado_actualizado_en = models.DateTimeField(default=timezone.now)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    anulado_por = models.ForeignKey('Usuarios', models.DO_NOTHING, db_column='anulado_por', related_name='pedidos_anulado_por_set', blank=True, null=True)
    anulado_en = models.DateTimeField(blank=True, null=True)
    motivo_anulacion = models.TextField(blank=True, null=True)
    # MySQL calcula esta columna; nunca se debe enviar en INSERT/UPDATE.
    estudiante_activo_id = models.GeneratedField(
        expression=models.Case(
            models.When(estado__in=['pendiente', 'en_preparacion', 'listo'], then=models.F('estudiante_id')),
            default=models.Value(None),
            output_field=models.PositiveIntegerField(),
        ),
        output_field=models.PositiveIntegerField(),
        db_persist=True,
        unique=True,
        null=True,
    )

    class Meta:
        managed = False
        db_table = 'pedidos'


class Productos(models.Model):
    id = models.AutoField(primary_key=True)
    categoria = models.ForeignKey(Categorias, models.DO_NOTHING)
    codigo = models.CharField(unique=True, max_length=50)
    nombre = models.CharField(max_length=150)
    descripcion = models.CharField(max_length=255, blank=True, null=True)
    precio = models.DecimalField(max_digits=12, decimal_places=2)
    fotografia = models.CharField(max_length=2048)
    stock = models.IntegerField(default=0)
    stock_minimo = models.IntegerField(default=0)
    disponible_para_venta = models.BooleanField(default=True)
    activo = models.BooleanField(default=True)

    def __str__(self):
        return f'{self.codigo} · {self.nombre}'

    @property
    def foto_url(self):
        from django.conf import settings
        ruta = self.fotografia or ''
        prefijo = settings.MEDIA_URL + 'productos/'
        return ruta if ruta.startswith(prefijo) and '..' not in ruta else ''

    @property
    def habilitado_para_venta(self):
        return self.activo and self.disponible_para_venta and self.categoria.activo

    class Meta:
        managed = False
        db_table = 'productos'


class Usuarios(AbstractBaseUser):
    id = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=150)
    correo = models.CharField(unique=True, max_length=254)
    password = models.CharField(max_length=255, db_column='password_hash')
    last_login = None  # La tabla existente no contiene esta columna.
    rol = models.CharField(max_length=13, choices=[('administrador', 'Administrador'), ('cajero', 'Cajero'), ('estudiante', 'Estudiante')])
    habilitado = models.BooleanField(default=True)
    token_sesion_hash = models.CharField(max_length=255, blank=True, null=True)
    sesion_expira_en = models.DateTimeField(blank=True, null=True)

    # El correo es la identidad unica de la BD. El backend web autentica por nombre.
    USERNAME_FIELD = 'correo'
    REQUIRED_FIELDS = ['nombre']

    @property
    def es_cuenta_principal(self):
        # Identidad permanente del admin inicial, tambien protegida en MySQL.
        return self.pk == 1

    @property
    def is_active(self):
        return bool(self.habilitado)

    @property
    def is_staff(self):
        return self.rol in ('administrador', 'cajero')

    @property
    def password_hash(self):
        return self.password

    @password_hash.setter
    def password_hash(self, value):
        self.password = value

    def check_password(self, raw_password):
        # Compatibilidad con los hashes PHP existentes, sin guardar texto plano.
        if self.password.startswith(('$2a$', '$2b$', '$2y$')):
            import bcrypt
            try:
                return bcrypt.checkpw(raw_password.encode('utf-8'), self.password.encode('ascii'))
            except (ValueError, UnicodeError):
                return False
        return check_password(raw_password, self.password)

    def __str__(self):
        return self.nombre

    class Meta:
        managed = False
        db_table = 'usuarios'


class Ventas(models.Model):
    id = models.AutoField(primary_key=True)
    numero = models.CharField(unique=True, max_length=50)
    operacion_id = models.UUIDField(unique=True, blank=True, null=True)
    pedido = models.OneToOneField(Pedidos, models.DO_NOTHING, blank=True, null=True, db_comment='NULL para una venta presencial')
    caja = models.ForeignKey(Caja, models.DO_NOTHING)
    cajero = models.ForeignKey(Usuarios, models.DO_NOTHING)
    creada_en = models.DateTimeField(default=timezone.now)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    efectivo_recibido = models.DecimalField(max_digits=12, decimal_places=2)
    estado = models.CharField(max_length=10, choices=[('completada', 'Completada'), ('anulada', 'Anulada')], default='completada')
    anulado_por = models.ForeignKey(Usuarios, models.DO_NOTHING, db_column='anulado_por', related_name='ventas_anulado_por_set', blank=True, null=True)
    anulado_en = models.DateTimeField(blank=True, null=True)
    motivo_anulacion = models.TextField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'ventas'
