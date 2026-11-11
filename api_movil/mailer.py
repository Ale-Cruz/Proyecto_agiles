from email.message import EmailMessage
import smtplib
import ssl

from fastapi import HTTPException
import settings


def send_code(correo, codigo, proposito):
    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        raise HTTPException(503, 'El envío de correo todavía no está configurado. Contacta a la cafetería.')
    message = EmailMessage()
    message['From'] = f'Cafetería ITCA <{settings.SMTP_USER}>'
    message['To'] = correo
    message['Subject'] = 'Código de ' + ('registro' if proposito == 'registro' else 'recuperación') + ' - Cafetería ITCA'
    message.set_content(f'Tu código es: {codigo}\n\nVence en 10 minutos y solo puede usarse una vez. '
                        'Si no lo solicitaste, ignora este mensaje.')
    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
            smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            smtp.send_message(message)
    except (smtplib.SMTPException, OSError):
        # No exponer credenciales, respuestas SMTP ni códigos en logs o HTTP.
        raise HTTPException(503, 'No fue posible enviar el correo. Inténtalo más tarde.') from None
