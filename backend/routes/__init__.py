from .auth import auth_bp
from .ai import ai_bp
from .farmer import farmer_bp
from .expert import expert_bp
from .crop import crop_bp
from .soil import soil_bp
from .pest import pest_bp
from .disease import disease_bp
from .fertilizer import fertilizer_bp
from .activity import activity_bp
from .weather import weather_bp
from .market import market_bp
from .schemes import schemes_bp
from .disease_alert import disease_alert_bp
from .equipment import equipment_bp
from .recommendation import recommendation_bp
from .smart_ai import smart_bp
from .yield_prediction import yield_bp
from .notification import notif_bp

def register_blueprints(app):
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(farmer_bp, url_prefix="/farmer")
    app.register_blueprint(ai_bp, url_prefix="/ai")
    app.register_blueprint(expert_bp, url_prefix="/expert")
    app.register_blueprint(crop_bp, url_prefix='/crop')
    app.register_blueprint(soil_bp, url_prefix="/soil")
    app.register_blueprint(pest_bp, url_prefix="/pest")
    app.register_blueprint(disease_bp, url_prefix="/disease")
    app.register_blueprint(fertilizer_bp, url_prefix="/fertilizer")
    app.register_blueprint(activity_bp, url_prefix="/activity")
    app.register_blueprint(weather_bp, url_prefix="/weather")
    app.register_blueprint(market_bp, url_prefix="/market")
    app.register_blueprint(schemes_bp, url_prefix="/schemes")
    app.register_blueprint(disease_alert_bp, url_prefix="/disease")
    app.register_blueprint(equipment_bp, url_prefix="/equipment")
    app.register_blueprint(recommendation_bp, url_prefix="/api")
    app.register_blueprint(smart_bp, url_prefix="/smart")
    app.register_blueprint(yield_bp, url_prefix="/yield")
    app.register_blueprint(notif_bp, url_prefix="/notifications")
