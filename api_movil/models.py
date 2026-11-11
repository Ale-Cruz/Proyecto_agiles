"""Mapeo del esquema compartido con Django. No crea tablas al importarse."""
from datetime import datetime, time, timezone
from decimal import Decimal
from typing import Optional

from pydantic import NaiveDatetime
from sqlalchemy import Column, Computed, Integer, Numeric, Text
from sqlmodel import Field, SQLModel


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Usuario(SQLModel, table=True):
    __tablename__ = 'usuarios'
    id: Optional[int] = Field(default=None, primary_key=True)
    nombre: str = Field(max_length=150)
    correo: str = Field(max_length=254)
    password_hash: str = Field(max_length=255)
    rol: str = 'estudiante'
    habilitado: bool = True
    token_sesion_hash: Optional[str] = None
    sesion_expira_en: Optional[NaiveDatetime] = None


class Categoria(SQLModel, table=True):
    __tablename__ = 'categorias'
    id: Optional[int] = Field(default=None, primary_key=True)
    nombre: str = Field(max_length=100)
    activo: bool = True


class Producto(SQLModel, table=True):
    __tablename__ = 'productos'
    id: Optional[int] = Field(default=None, primary_key=True)
    categoria_id: int = Field(foreign_key='categorias.id')
    codigo: str = Field(max_length=50)
    nombre: str = Field(max_length=150)
    descripcion: Optional[str] = None
    precio: Decimal = Field(sa_column=Column(Numeric(12, 2), nullable=False))
    fotografia: str = ''
    stock: int = 0
    stock_minimo: int = 0
    disponible_para_venta: bool = True
    activo: bool = True


class Carrito(SQLModel, table=True):
    __tablename__ = 'carritos'
    id: Optional[int] = Field(default=None, primary_key=True)
    usuario_id: int = Field(foreign_key='usuarios.id')
    ultima_actividad: NaiveDatetime = Field(default_factory=utcnow)
    expira_en: NaiveDatetime


class DetalleCarrito(SQLModel, table=True):
    __tablename__ = 'detalles_carrito'
    id: Optional[int] = Field(default=None, primary_key=True)
    carrito_id: int = Field(foreign_key='carritos.id')
    producto_id: int = Field(foreign_key='productos.id')
    cantidad: int


class Pedido(SQLModel, table=True):
    __tablename__ = 'pedidos'
    id: Optional[int] = Field(default=None, primary_key=True)
    numero: str = Field(max_length=50)
    operacion_id: Optional[str] = Field(default=None, max_length=32)
    estudiante_id: int = Field(foreign_key='usuarios.id')
    estado: str = 'en_preparacion'
    creado_en: NaiveDatetime = Field(default_factory=utcnow)
    estado_actualizado_en: NaiveDatetime = Field(default_factory=utcnow)
    total: Decimal = Field(default=Decimal('0.00'), sa_column=Column(Numeric(12, 2), nullable=False))
    anulado_por: Optional[int] = Field(default=None, foreign_key='usuarios.id')
    anulado_en: Optional[NaiveDatetime] = None
    motivo_anulacion: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    estudiante_activo_id: Optional[int] = Field(default=None, sa_column=Column(Integer, Computed(
        "CASE WHEN estado IN ('pendiente','en_preparacion','listo') THEN estudiante_id ELSE NULL END",
        persisted=True), nullable=True))


class DetallePedido(SQLModel, table=True):
    __tablename__ = 'detalles_pedido'
    id: Optional[int] = Field(default=None, primary_key=True)
    pedido_id: int = Field(foreign_key='pedidos.id')
    producto_id: int = Field(foreign_key='productos.id')
    cantidad: int
    precio_unitario: Decimal = Field(sa_column=Column(Numeric(12, 2), nullable=False))


class Configuracion(SQLModel, table=True):
    __tablename__ = 'configuracion'
    id: Optional[int] = Field(default=None, primary_key=True)
    minutos_carrito: int = 5
    horarios_habilitados: bool = False


class Horario(SQLModel, table=True):
    __tablename__ = 'horarios_pedidos'
    id: Optional[int] = Field(default=None, primary_key=True)
    configuracion_id: int = Field(foreign_key='configuracion.id')
    dia_semana: int
    hora_inicio: time
    hora_fin: time
    activo: bool = True


class CodigoVerificacion(SQLModel, table=True):
    __tablename__ = 'codigos_verificacion_movil'
    correo: str = Field(primary_key=True, max_length=254)
    proposito: str = Field(primary_key=True, max_length=20)
    codigo_hash: str = Field(max_length=64)
    expira_en: NaiveDatetime
    enviado_en: NaiveDatetime = Field(default_factory=utcnow)
    intentos: int = 0


class SesionMovil(SQLModel, table=True):
    __tablename__ = 'sesiones_movil'
    token_hash: str = Field(primary_key=True, max_length=64)
    usuario_id: int = Field(foreign_key='usuarios.id')
    creado_en: NaiveDatetime = Field(default_factory=utcnow)
    expira_en: Optional[NaiveDatetime] = None
