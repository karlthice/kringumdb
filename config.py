import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, 'kringum.db')
EXPORT_DIR = os.path.join(BASE_DIR, 'export')
GOOGLE_TRANSLATE_API_KEY = ''  # Set your Google Translate API key here, or leave empty to disable
