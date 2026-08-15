def register_blueprints(app):
    """注册所有蓝图"""
    from main_routes import main as main_bp
    app.register_blueprint(main_bp)

    from blueprints.auth import auth_bp
    from blueprints.asset import asset_bp
    from blueprints.about import about_bp
    from blueprints.device import device_bp
    from blueprints.alert import alert_bp
    from blueprints.cabinet import cabinet_bp
    from blueprints.user import user_bp
    from blueprints.location import location_bp
    from blueprints.monitoring import monitoring_bp
    from blueprints.topology import topology_bp
    from blueprints.system import system_bp
    from blueprints.config import config_bp
    from blueprints.report_routes import report_bp
    from blueprints.maintenance_routes import maintenance_bp
    # 必须在 register_blueprint(maintenance_bp) 之前导入，使 CAB 审批链路由注册到该 blueprint
    from blueprints import cab_chain  # noqa: F401
    from blueprints.settings import settings_bp
    from blueprints.profile import profile_bp
    from blueprints.api import api_bp
    from blueprints.link_routes import link_bp
    from blueprints.asset_extra import asset_extra_bp
    from blueprints.config_compliance import config_compliance_bp
    from blueprints.monitoring_extra import monitoring_extra_bp
    from blueprints.maintenance_extra import maintenance_extra_bp
    from blueprints.report_extra import report_extra_bp
    from blueprints.device_group import device_group_bp
    from blueprints.cmdb import cmdb_bp
    from blueprints.itsm_adv import itsm_adv_bp
    from blueprints.dc_view import dc_view_bp
    from blueprints.event_monitor import event_monitor_bp
    from blueprints.sysjobs import sysjobs_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(asset_bp)
    app.register_blueprint(about_bp)
    app.register_blueprint(device_bp)
    app.register_blueprint(alert_bp)
    app.register_blueprint(cabinet_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(location_bp)
    app.register_blueprint(monitoring_bp)
    app.register_blueprint(topology_bp)
    app.register_blueprint(system_bp)
    app.register_blueprint(config_bp)
    app.register_blueprint(report_bp)
    app.register_blueprint(maintenance_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(link_bp)
    app.register_blueprint(asset_extra_bp)
    app.register_blueprint(config_compliance_bp)
    app.register_blueprint(monitoring_extra_bp)
    app.register_blueprint(maintenance_extra_bp)
    app.register_blueprint(report_extra_bp)
    app.register_blueprint(device_group_bp)
    app.register_blueprint(cmdb_bp)
    app.register_blueprint(itsm_adv_bp)
    app.register_blueprint(dc_view_bp)
    app.register_blueprint(event_monitor_bp)
    app.register_blueprint(sysjobs_bp)

    print("所有蓝图注册成功")
