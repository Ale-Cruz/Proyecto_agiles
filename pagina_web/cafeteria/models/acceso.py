from django.db import models
from django.utils import timezone


class IntentosAcceso(models.Model):
    """Contadores compartidos por todos los procesos de la futura VPS."""

    clave = models.CharField(max_length=64, primary_key=True)
    fallos = models.PositiveIntegerField(default=0)
    inicio_ventana = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'intentos_acceso'
        verbose_name_plural = 'intentos de acceso'
