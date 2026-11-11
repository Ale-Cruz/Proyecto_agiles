from decimal import Decimal
import re
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=False)


class CorreoInput(Input):
    correo: str = Field(max_length=254)

    @field_validator('correo')
    @classmethod
    def institutional_email(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r'[a-z0-9.!#$%&\'*+/=?^_`{|}~-]+@itca\.edu\.sv', value):
            raise ValueError('Usa un correo institucional @itca.edu.sv válido.')
        return value


class LoginInput(CorreoInput):
    password: str = Field(min_length=1, max_length=128)


class PasswordInput(CorreoInput):
    password: str = Field(min_length=8, max_length=72)
    codigo: str = Field(pattern=r'^\d{6}$')

    @field_validator('password')
    @classmethod
    def password_length(cls, value):
        if len(value.encode('utf-8')) > 72 or not value.strip():
            raise ValueError('La contraseña debe tener de 8 a 72 bytes y no estar vacía.')
        return value


class RegistroInput(PasswordInput):
    nombre: str = Field(min_length=1, max_length=150)

    @field_validator('nombre')
    @classmethod
    def valid_name(cls, value):
        value = ' '.join(value.split())
        if not value:
            raise ValueError('Ingresa tu nombre.')
        return value


class CantidadInput(Input):
    carrito_id: int | None = Field(default=None, strict=True, gt=0)
    cantidad: int = Field(strict=True, ge=0, le=2147483647)


class PedidoInput(Input):
    carrito_id: int | None = Field(default=None, strict=True, gt=0)
    operacion_id: UUID
    total_esperado: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
