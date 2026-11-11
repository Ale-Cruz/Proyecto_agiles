import smtplib
import ssl
import sys

import settings

if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
    print('Falta configurar la cuenta o la contrasena de aplicacion.')
    sys.exit(1)
try:
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as smtp:
        smtp.ehlo()
        smtp.starttls(context=ssl.create_default_context())
        smtp.ehlo()
        smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
except (smtplib.SMTPException, OSError):
    print('No se pudo autenticar con Gmail. Revisa la cuenta, la contrasena de aplicacion y la conexion.')
    sys.exit(1)
print('Conexion y autenticacion con Gmail correctas. No se envio ningun correo de prueba.')
