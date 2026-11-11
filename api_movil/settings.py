import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')
SECRET_KEY = os.getenv('API_SECRET_KEY', '')
if len(SECRET_KEY) < 32:
    raise RuntimeError('Configura API_SECRET_KEY en .env con una clave aleatoria de al menos 32 caracteres.')

SMTP_HOST = os.getenv('SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
SMTP_USER = os.getenv('SMTP_USER', '').strip()
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', '').replace(' ', '')
MEDIA_ROOT = Path(os.getenv('MEDIA_ROOT', str(ROOT.parent / 'pagina_web' / 'media')))
PUBLIC_BASE_URL = os.getenv('PUBLIC_BASE_URL', '').rstrip('/')
SESSION_DAYS = int(os.getenv('SESSION_DAYS', '0'))
CANCEL_ALLOWED_STATES = tuple(s.strip() for s in os.getenv('CANCEL_ALLOWED_STATES', 'en_preparacion').split(',') if s.strip())
