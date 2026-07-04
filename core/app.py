# core/app.py - Flask application factory
from flask import Flask
from flask_login import LoginManager
from core.config import Config
from core.database import close_db, init_db
from core.scheduler import start_scheduler

app = Flask(__name__, template_folder='../modules/web_ui/templates')
app.config['SECRET_KEY'] = Config.SECRET_KEY

# Database teardown
app.teardown_appcontext(close_db)

# Initialize Login Manager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "authentication.login"

# Import user loader
from modules.authentication.models import load_user
login_manager.user_loader(load_user)

# Register Blueprints
from modules.authentication.routes import auth_bp
from modules.web_ui.routes import ui_bp
from modules.api.routes import api_bp

app.register_blueprint(auth_bp)
app.register_blueprint(ui_bp)
app.register_blueprint(api_bp, url_prefix='/api')

# Initialize database
with app.app_context():
    init_db()

# Start scheduler
start_scheduler(app)

print("🚀 SysWatch Core initialized successfully.")
