from datetime import datetime, timezone, date
from flask import current_app
from flask_login import current_user
from extensions import db
from models.models import Device, Alert
from models.maintenance_models import InspectionTask, WorkOrder


def register_context_processors(app):
    @app.template_filter('nl2br')
    def nl2br_filter(value):
        """将换行符替换为HTML <br>"""
        if value:
            from html import escape
            return escape(str(value)).replace('\n', '<br>\n')
        return ''

    @app.context_processor
    def inject_global_variables():
        if current_user.is_authenticated:
            alert_count = db.session.query(Alert).filter_by(status='active').count()
            online_count = db.session.query(Device).filter_by(status='online').count()
            offline_count = db.session.query(Device).filter_by(status='offline').count()
            pending_inspections = db.session.query(InspectionTask).filter_by(status='pending').count()
            active_maintenance = db.session.query(InspectionTask).filter(
                InspectionTask.status.in_(['in_progress', 'scheduled'])
            ).count()
            open_work_orders = db.session.query(WorkOrder).filter_by(status='open').count()
            my_assigned_orders = db.session.query(WorkOrder).filter(
                WorkOrder.assigned_to_id == current_user.id,
                WorkOrder.status.in_(['assigned', 'in_progress'])
            ).count()
            return {
                'alert_count': alert_count,
                'stats': {
                    'online_count': online_count,
                    'offline_count': offline_count,
                    'alert_count': alert_count,
                },
                'pending_inspections': pending_inspections,
                'active_maintenance': active_maintenance,
                'open_work_orders': open_work_orders,
                'my_assigned_orders': my_assigned_orders,
                'unread_reports': 0
            }
        return {
            'alert_count': 0,
            'stats': {
                'online_count': 0,
                'offline_count': 0,
                'alert_count': 0,
            },
            'pending_inspections': 0,
            'active_maintenance': 0,
            'open_work_orders': 0,
            'my_assigned_orders': 0,
            'unread_reports': 0
        }

    @app.context_processor
    def utility_processor():
        def get_status_color(status):
            return {
                'online': 'success',
                'active': 'info',
                'inactive': 'secondary',
                'maintenance': 'warning',
                'offline': 'danger',
                'unknown': 'secondary'
            }.get((status or '').lower(), 'secondary')

        def get_type_color(device_type):
            return {
                'server': '#28a745',
                'network': '#007bff',
                'storage': '#17a2b8',
                'security': '#dc3545',
                'virtual': '#ffc107',
                'appliance': '#6c757d',
                'other': '#6c757d',
            }.get((device_type or 'other').lower(), '#6c757d')

        def get_type_color_class(device_type):
            return {
                'server': 'success',
                'network': 'primary',
                'storage': 'info',
                'security': 'danger',
                'virtual': 'warning',
                'appliance': 'secondary',
                'other': 'secondary',
            }.get((device_type or 'other').lower(), 'secondary')

        def get_type_icon(device_type):
            return {
                'server': 'fa-server',
                'network': 'fa-network-wired',
                'storage': 'fa-hdd',
                'security': 'fa-shield-alt',
                'virtual': 'fa-cloud',
                'appliance': 'fa-cube',
                'other': 'fa-microchip',
            }.get((device_type or 'other').lower(), 'fa-microchip')

        return dict(
            get_status_color=get_status_color,
            get_type_color=get_type_color,
            get_type_color_class=get_type_color_class,
            get_type_icon=get_type_icon,
            enumerate=enumerate
        )

    @app.context_processor
    def inject_global_vars():
        return dict(
            app_name='机房资产管理系统',
            current_year=datetime.now(timezone.utc).year,
            is_admin=lambda: current_user.is_authenticated and current_user.is_admin,
            datetime=datetime,
            date=date,
        )

    @app.context_processor
    def inject_current_date():
        now = datetime.now(timezone.utc)
        return {
            'current_date': now,
            'current_year': now.year,
            'current_month': now.month,
            'current_day': now.day
        }
