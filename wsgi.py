# wsgi.py - Entry point for Gunicorn
from core.app import app

if __name__ == "__main__":
    app.run()
