# modules/web_ui/routes.py - Dashboard UI
from flask import Blueprint, render_template
from flask_login import login_required

ui_bp = Blueprint('web_ui', __name__)

@ui_bp.route('/')
@login_required
def dashboard():
    return render_template('dashboard.html')
