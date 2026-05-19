import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, 'kringum.db')
EXPORT_DIR = os.path.join(BASE_DIR, 'export')
GOOGLE_TRANSLATE_API_KEY = ''  # Deprecated, use GEMINI_API_KEY instead
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')  # Set your Gemini API key here or via env var
