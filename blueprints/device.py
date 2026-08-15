# blueprints/device.py
from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash, current_app, send_file, abort
from flask_login import login_required, current_user
import socket, platform, subprocess, ipaddress, concurrent.futures, threading, traceback, re, time, os, uuid
from sqlalchemy import or_, and_, text, func  # ← 添加 func
from io import BytesIO
import xlsxwriter
from extensions import db
from models.models import Device, OperationLog, InterfaceRelationship, TopologyLog, Location, Cabinet, Interface, AlertEvent, MonitorData, DeviceMonitorLog, InventoryTransaction, DeviceMonitorConfig, ConnectionPath, InterfaceMonitorData, DiscoveryTask
from models.device_performance_models import DevicePerformance
from models.settings_models import SystemConfig
from models.maintenance_models import SparePart, InspectionTask
from models.config_models import SNMPSetting, Credential
from models.compliance_models import ConfigBaseline, ConfigDrift, ConfigVersion, ComplianceCheckResult
from utils.utils import parse_ip_range, ping_device, calculate_checksum, ping_device_tcp, ping_device_socket, scan_ip_range_worker, get_device_status_color, scan_ip_with_snmp, ping_device_strict, snmp_get_device_info
from sqlalchemy.exc import OperationalError, IntegrityError
from datetime import datetime, timezone, timedelta,date
from openpyxl import Workbook
from io import BytesIO
from utils.utils import ip_range_import, infer_device_type_from_snmp, snmp_discover_interfaces_real, save_discovered_interfaces
from utils.snmp_utils import clean_snmp_device_name
from services.device_service import find_or_create_device, find_device_by_any, normalize_mac
import csv 
import io
import pandas as pd
from werkzeug.utils import secure_filename
from utils.utils import log_activity
from auth import log_operation
from validators import validate_ip, validate_mac
from utils.audit import log_audit
from utils.permission import permission_required
# ========== 引入 device_import 工具函数 ==========
from utils.device_import import import_devices_from_file, generate_import_template
# ============ 进度管理器（支持文件持久化） ============
import json
import tempfile



# ============ 设备蓝图 ============
device_bp = Blueprint('device', __name__, url_prefix='/devices')


# ========== 模板过滤器 ==========
@device_bp.app_template_filter('utc_to_local')
def utc_to_local_filter(dt):
    """将UTC时间转换为本地时间显示"""
    if not dt:
        return '未检测'
    try:
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
        if hasattr(dt, 'tzinfo') and dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return str(dt)


@device_bp.app_template_filter('get_device_status_color')
def get_device_status_color(status):
    """获取设备状态对应的Bootstrap颜色"""
    color_map = {
        'online': 'success',
        'offline': 'danger',
        'fault': 'danger',
        'warning': 'warning',
        'unknown': 'secondary',
        'active': 'success',
        'inactive': 'secondary',
        'maintenance': 'warning'
    }
    return color_map.get(status, 'secondary')





class ProgressManager:
    """批量操作进度管理器 - 支持内存和文件持久化"""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._progress = {}
                    cls._instance._storage_file = os.path.join(
                        tempfile.gettempdir(), 
                        'device_import_progress.json'
                    )
                    # 尝试从文件恢复
                    cls._instance._load_from_file()
        return cls._instance
    
    def _load_from_file(self):
        """从文件加载进度数据"""
        try:
            if os.path.exists(self._storage_file):
                with open(self._storage_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # 只加载最近1小时内的任务
                    now = datetime.now()
                    for task_id, task in data.items():
                        start_time = datetime.fromisoformat(task['start_time'])
                        if (now - start_time).total_seconds() < 3600:
                            self._progress[task_id] = task
        except Exception as e:
            print(f"加载进度文件失败: {e}")
    
    def _save_to_file(self):
        """保存进度数据到文件"""
        try:
            with open(self._storage_file, 'w', encoding='utf-8') as f:
                json.dump(self._progress, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存进度文件失败: {e}")
    
    def create_task(self, task_type='import'):
        """创建新任务"""
        task_id = str(uuid.uuid4())[:8]
        self._progress[task_id] = {
            'task_id': task_id,
            'task_type': task_type,
            'status': 'pending',
            'progress': 0,
            'current_step': '准备开始...',
            'total': 0,
            'processed': 0,
            'added': 0,
            'skipped': 0,
            'failed': 0,
            'start_time': datetime.now().isoformat(),
            'end_time': None,
            'message': '',
            'results': []
        }
        self._save_to_file()
        return task_id
    
    def update_progress(self, task_id, **kwargs):
        """更新进度"""
        if task_id in self._progress:
            self._progress[task_id].update(kwargs)
            self._progress[task_id]['last_update'] = datetime.now().isoformat()
            self._save_to_file()
    
    def get_progress(self, task_id):
        """获取进度"""
        return self._progress.get(task_id)
    
    def get_all_tasks(self):
        """获取所有任务"""
        return self._progress
    
    def cleanup_old_tasks(self, max_age_minutes=60):
        """清理旧任务"""
        now = datetime.now()
        to_delete = []
        for task_id, task in self._progress.items():
            start_time = datetime.fromisoformat(task['start_time'])
            if now - start_time > timedelta(minutes=max_age_minutes):
                to_delete.append(task_id)
        for task_id in to_delete:
            if task_id in self._progress:
                del self._progress[task_id]
        if to_delete:
            self._save_to_file()

# 全局进度管理器实例
progress_manager = ProgressManager()

# ============ 跨平台文件锁 ============
try:
    import portalocker
    HAS_PORTALOCKER = True
except ImportError:
    HAS_PORTALOCKER = False
    print("警告: portalocker 未安装，请运行: pip install portalocker")

class CrossPlatformLock:
    """跨平台文件锁"""
    
    def __init__(self, lock_name='ip_range_import'):
        self.lock_name = lock_name
        self.lock_file = None
        self.lock_fd = None
        
    def acquire(self, timeout=30):
        """获取锁"""
        try:
            import tempfile
            lock_dir = tempfile.gettempdir()
            lock_path = os.path.join(lock_dir, f'{self.lock_name}.lock')
            self.lock_fd = open(lock_path, 'w')
            self.lock_file = lock_path
            
            if HAS_PORTALOCKER:
                portalocker.lock(self.lock_fd, portalocker.LOCK_EX | portalocker.LOCK_NB)
                return True
            else:
                return True
        except portalocker.LockException:
            start_time = time.time()
            while True:
                try:
                    time.sleep(0.5)
                    if HAS_PORTALOCKER:
                        portalocker.lock(self.lock_fd, portalocker.LOCK_EX | portalocker.LOCK_NB)
                        return True
                    else:
                        return True
                except portalocker.LockException:
                    if time.time() - start_time > timeout:
                        return False
        except Exception as e:
            print(f"获取锁失败: {e}")
            return False
    
    def release(self):
        """释放锁"""
        try:
            if self.lock_fd:
                if HAS_PORTALOCKER:
                    try:
                        portalocker.unlock(self.lock_fd)
                    except:
                        pass
                self.lock_fd.close()
                self.lock_fd = None
            if self.lock_file and os.path.exists(self.lock_file):
                try:
                    os.remove(self.lock_file)
                except:
                    pass
        except Exception as e:
            print(f"释放锁失败: {e}")




# ============ 进度查询API ============
@device_bp.route('/progress/<task_id>', methods=['GET'])
@login_required
@permission_required('device:view')
def get_progress(task_id):
    """获取任务进度"""
    print(f"📊 查询进度: {task_id}")
    
    progress = progress_manager.get_progress(task_id)
    
    if not progress:
        print(f"❌ 任务不存在: {task_id}")
        return jsonify({
            'success': False,
            'message': '任务不存在或已过期'
        }), 404
    
    print(f"✅ 进度: {progress.get('progress', 0)}%, 状态: {progress.get('status', 'unknown')}")
    
    return jsonify({
        'success': True,
        'progress': progress
    })

@device_bp.route('/progress/list', methods=['GET'])
@login_required
@permission_required('device:view')
def list_progress():
    """列出所有任务"""
    tasks = progress_manager.get_all_tasks()
    # 清理过期任务
    progress_manager.cleanup_old_tasks()
    return jsonify({
        'success': True,
        'tasks': tasks
    })

def batch_detect_devices_strict(ip_list, timeout=2, max_workers=20, task_id=None, progress_callback=None):
    """
    严格的批量设备检测 - 只有确认在线的才返回True
    使用多种检测方法，要求至少两种方法确认才认为在线
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import subprocess
    import platform
    import socket
    import re
    
    results = {}
    total = len(ip_list)
    completed = 0
    
    def detect_single_ip(ip):
        """严格检测单个IP - 使用多种方法验证"""
        detection_results = {}
        
        # 方法1: 系统Ping（最可靠）
        try:
            param = '-n' if platform.system().lower() == 'windows' else '-c'
            timeout_param = '-w' if platform.system().lower() == 'windows' else '-W'
            timeout_val = str(int(timeout * 1000)) if platform.system().lower() == 'windows' else str(int(timeout))
            
            cmd = ['ping', param, '1', timeout_param, timeout_val, ip]
            result = subprocess.run(cmd, capture_output=True, timeout=timeout+1, text=True)
            
            if result.returncode == 0:
                # 解析响应时间
                match = re.search(r'(?:时间|time)[=<](\d+\.?\d*)', result.stdout, re.IGNORECASE)
                response_time = float(match.group(1)) if match else timeout * 1000
                detection_results['ping'] = {
                    'success': True,
                    'response_time': response_time
                }
            else:
                detection_results['ping'] = {
                    'success': False,
                    'response_time': 0
                }
        except Exception as e:
            detection_results['ping'] = {
                'success': False,
                'response_time': 0,
                'error': str(e)
            }
        
        # 方法2: TCP端口检测（多个常见端口）
        common_ports = [80, 443, 22, 23, 8080, 8443, 3389, 3306, 1433, 5432, 6379, 27017]
        tcp_success = False
        tcp_response = 0
        tcp_port = None
        
        for port in common_ports:
            try:
                import time
                start = time.time()
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(timeout)
                result = sock.connect_ex((ip, port))
                sock.close()
                
                if result == 0:
                    tcp_success = True
                    tcp_response = (time.time() - start) * 1000
                    tcp_port = port
                    break
            except:
                pass
        
        detection_results['tcp'] = {
            'success': tcp_success,
            'response_time': tcp_response,
            'port': tcp_port
        }
        
        # 方法3: ARP缓存检查（局域网内更准确）
        try:
            import subprocess
            if platform.system().lower() == 'windows':
                cmd = ['arp', '-a', ip]
            else:
                cmd = ['arp', '-n', ip]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
            
            # 检查ARP缓存中是否有该IP，且MAC地址不是全0
            if ip in result.stdout:
                # 检查是否包含有效的MAC地址（不是00-00-00-00-00-00）
                import re
                mac_pattern = r'([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}'
                macs = re.findall(mac_pattern, result.stdout)
                if macs:
                    # 检查MAC地址是否有效（不全为0）
                    for mac in macs:
                        if mac.replace('-', '').replace(':', '') != '000000000000':
                            detection_results['arp'] = {
                                'success': True,
                                'mac': mac
                            }
                            break
                    else:
                        detection_results['arp'] = {
                            'success': False
                        }
                else:
                    detection_results['arp'] = {
                        'success': False
                    }
            else:
                detection_results['arp'] = {
                    'success': False
                }
        except:
            detection_results['arp'] = {
                'success': False
            }
        
        # ★★★ 判断逻辑：至少两种方法确认在线 ★★★
        success_count = 0
        best_response = 0
        methods_used = []
        
        if detection_results.get('ping', {}).get('success', False):
            success_count += 1
            best_response = detection_results['ping'].get('response_time', timeout * 1000)
            methods_used.append('ping')
        
        if detection_results.get('tcp', {}).get('success', False):
            success_count += 1
            tcp_resp = detection_results['tcp'].get('response_time', 0)
            if tcp_resp > 0 and (best_response == 0 or tcp_resp < best_response):
                best_response = tcp_resp
            methods_used.append(f"tcp_{detection_results['tcp'].get('port', 'unknown')}")
        
        if detection_results.get('arp', {}).get('success', False):
            success_count += 1
            methods_used.append('arp')
        
        # ★★★ 至少需要2种方法确认，才认为设备在线 ★★★
        is_online = success_count >= 2
        
        # 如果没有响应时间，使用默认值
        if best_response == 0 and is_online:
            best_response = timeout * 1000
        
        return {
            'ip': ip,
            'online': is_online,
            'response_time': best_response,
            'detection_method': '+'.join(methods_used) if methods_used else 'all_failed',
            'success_count': success_count,
            'methods': methods_used,
            'details': detection_results
        }
    
    # 并发执行检测
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_ip = {executor.submit(detect_single_ip, ip): ip for ip in ip_list}
        
        for future in as_completed(future_to_ip):
            ip = future_to_ip[future]
            try:
                result = future.result(timeout=timeout+3)
                results[ip] = result
            except Exception as e:
                results[ip] = {
                    'ip': ip,
                    'online': False,
                    'response_time': 0,
                    'detection_method': 'error',
                    'reason': str(e)
                }
            
            completed += 1
            if progress_callback and completed % 5 == 0:
                progress = completed / total
                progress_callback(progress, f'检测中 {completed}/{total}: {ip}')
    
    return results

def batch_detect_devices_with_progress(ip_list, timeout=2, max_retries=2, max_workers=20, 
                                        task_id=None, progress_callback=None):
    """批量检测设备在线状态 - 带进度回调"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    results = {}
    total = len(ip_list)
    completed = 0
    
    def detect_single_ip(ip):
        """检测单个IP"""
        common_ports = [80, 443, 22, 23, 8080, 8443]
        
        for port in common_ports:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(timeout)
                result = sock.connect_ex((ip, port))
                sock.close()
                if result == 0:
                    return {
                        'ip': ip,
                        'online': True,
                        'response_time': timeout * 1000,
                        'detection_method': f'tcp_{port}'
                    }
            except:
                pass
        
        # 系统Ping
        try:
            import subprocess
            import platform
            param = '-n' if platform.system().lower() == 'windows' else '-c'
            timeout_param = '-w' if platform.system().lower() == 'windows' else '-W'
            timeout_val = '1000' if platform.system().lower() == 'windows' else str(int(timeout))
            
            cmd = ['ping', param, '1', timeout_param, timeout_val, ip]
            result = subprocess.run(cmd, capture_output=True, timeout=timeout+1, text=True)
            
            if result.returncode == 0:
                import re
                match = re.search(r'(?:时间|time)[=<](\d+\.?\d*)', result.stdout, re.IGNORECASE)
                response_time = float(match.group(1)) if match else timeout * 1000
                return {
                    'ip': ip,
                    'online': True,
                    'response_time': response_time,
                    'detection_method': 'system_ping'
                }
        except:
            pass
        
        return {
            'ip': ip,
            'online': False,
            'response_time': 0,
            'detection_method': 'all_failed'
        }
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_ip = {executor.submit(detect_single_ip, ip): ip for ip in ip_list}
        
        for future in as_completed(future_to_ip):
            ip = future_to_ip[future]
            try:
                result = future.result(timeout=timeout+2)
                results[ip] = result
            except Exception as e:
                results[ip] = {
                    'ip': ip,
                    'online': False,
                    'response_time': 0,
                    'detection_method': 'error',
                    'reason': str(e)
                }
            
            completed += 1
            if progress_callback and completed % 5 == 0:
                progress = completed / total
                progress_callback(progress, f'检测中 {completed}/{total}: {ip}')
    
    return results

def log_operation(operation_type, resource_type=None, resource_id=None, resource_name=None, details=None, user=None):
    """
    记录操作日志
    Args:
        operation_type: 操作类型 (如 'create', 'update', 'delete')
        resource_type: 资源类型 (如 'device', 'cabinet')
        resource_id: 资源ID
        resource_name: 资源名称
        details: 操作详情
        user: 可选的用户对象（优先使用），若未提供则尝试从 current_user 获取
    """
    # 确定用户信息
    user_id = None
    username = "系统"

    if user and hasattr(user, 'id'):
        user_id = user.id
        username = getattr(user, 'username', '未知用户')
    else:
        try:
            if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated:
                user_id = current_user.id
                username = getattr(current_user, 'username', '未知用户')
        except RuntimeError:
            # 后台线程中无请求上下文，使用默认"系统"
            pass

    try:
        # 获取请求信息（可能无请求上下文）
        remote_addr = None
        user_agent_str = None
        try:
            remote_addr = request.remote_addr
            user_agent_str = request.user_agent.string if hasattr(request, 'user_agent') and request.user_agent else None
        except RuntimeError:
            pass

        log = OperationLog(
            user_id=user_id,
            username=username,
            operation_type=operation_type,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_name=resource_name,
            details=details,
            ip_address=remote_addr,
            user_agent=user_agent_str,
            created_at=datetime.utcnow()
        )
        db.session.add(log)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"记录操作日志失败: {e}")

def export_to_excel(data, headers, is_template=False):
    """导出数据到Excel"""
    output = BytesIO()
    workbook = xlsxwriter.Workbook(output)
    worksheet = workbook.add_worksheet('设备列表')
    
    # 设置表头样式
    header_format = workbook.add_format({
        'bold': True,
        'bg_color': '#f8f9fa',
        'border': 1,
        'align': 'center'
    })
    
    # 写入表头
    for col, header in enumerate(headers):
        worksheet.write(0, col, header, header_format)
    
    # 如果是模板，写入示例数据
    if is_template:
        example_data = [
            ['核心交换机-01', 1, 15, 1, 'switch', 'Cisco', 'WS-C2960X', 'FOC123456', 
             '192.168.1.1', '00:1A:2B:3C:4D:5E', 'public', 'admin', 'password', 'online',
             '2023-01-01', '2026-01-01', '核心交换机']
        ]
        for row, data_row in enumerate(example_data, start=1):
            for col, value in enumerate(data_row):
                worksheet.write(row, col, value)
    
    # 写入真实数据
    else:
        for row, data_row in enumerate(data, start=1):
            for col, value in enumerate(data_row):
                worksheet.write(row, col, value)
    
    # 调整列宽
    worksheet.set_column(0, len(headers)-1, 20)
    workbook.close()
    output.seek(0)
    return workbook

def parse_excel_file(file):
    """解析Excel文件"""
    import pandas as pd
    # 根据文件扩展名选择引擎
    if file.filename.endswith('.xlsx'):
        df = pd.read_excel(file, engine='openpyxl')
    else:
        df = pd.read_excel(file, engine='xlrd')
    return df


# ========== 主要路由 ==========

@device_bp.route('/devices')
@login_required
@permission_required('device:view')
def device_list():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    search = request.args.get('search', '').strip()
    status = request.args.get('status')
    device_type = request.args.get('device_type')
    location_id = request.args.get('location_id')
    cabinet_id = request.args.get('cabinet_id')

    query = Device.query.filter(Device.is_decommissioned == False)  # 只显示未下架设备

    # ---------- 搜索逻辑 ----------
    if search:
        query = query.filter(
            or_(
                Device.name.ilike(f'%{search}%'),
                Device.management_ip.ilike(f'%{search}%'),
                Device.serial_number.ilike(f'%{search}%'),
                Device.asset_number.ilike(f'%{search}%'),
                Device.mac_address.ilike(f'%{search}%'),
                Device.model.ilike(f'%{search}%'),
                Device.brand.ilike(f'%{search}%'),
                Device.manufacturer.ilike(f'%{search}%')
            )
        )

    # ---------- 状态筛选 ----------
    if status and status in ['online', 'offline', 'fault', 'unknown']:
        query = query.filter(Device.status == status)

    # ---------- 设备类型筛选 ----------
    if device_type:
        query = query.filter(Device.device_type == device_type)

    # ---------- 位置筛选（通过机柜关联）----------
    if location_id:
        query = query.join(Cabinet).filter(Cabinet.location_id == location_id)

    # ---------- 机柜筛选 ----------
    if cabinet_id:
        query = query.filter(Device.cabinet_id == cabinet_id)

    # 分页
    pagination = query.order_by(Device.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    devices = pagination.items

    # ==================== 处理时间显示（直接在这里格式化） ====================
    from datetime import timedelta
    
    for device in devices:
        if device.last_checked:
            # 直接加 8 小时
            beijing_time = device.last_checked + timedelta(hours=8)
            device.last_checked_display = beijing_time.strftime('%Y-%m-%d %H:%M:%S')
        else:
            device.last_checked_display = '未检测'

    # 统计信息（全局，排除已下架）
    total_devices = Device.query.filter(Device.is_decommissioned == False).count()
    online_devices = Device.query.filter(Device.status == 'online', Device.is_decommissioned == False).count()
    offline_devices = total_devices - online_devices

    # ==================== 获取最后检测时间 ====================
    import pytz
    beijing_tz = pytz.timezone('Asia/Shanghai')
    last_device = Device.query.order_by(Device.last_checked.desc()).first()
    
    if last_device and last_device.last_checked:
        if hasattr(last_device.last_checked, 'strftime'):
            if last_device.last_checked.tzinfo is None:
                utc_time = last_device.last_checked.replace(tzinfo=timezone.utc)
            else:
                utc_time = last_device.last_checked.astimezone(timezone.utc)
            beijing_time = utc_time.astimezone(beijing_tz)
            last_check_time = beijing_time.strftime('%Y-%m-%d %H:%M')
        else:
            last_check_time = str(last_device.last_checked)
    else:
        last_check_time = '从未检测'

    # 获取所有位置和机柜（用于下拉框）
    locations = Location.query.order_by(Location.name).all()
    cabinets = Cabinet.query.options(db.joinedload(Cabinet.location)).all()

    # 将 cabinets 转换为可 JSON 序列化的字典列表
    cabinets_data = []
    for cabinet in cabinets:
        location_id_val = None
        if hasattr(cabinet, 'location_id'):
            location_id_val = cabinet.location_id
        elif cabinet.location:
            location_id_val = cabinet.location.id
        
        cabinets_data.append({
            'id': cabinet.id,
            'name': cabinet.name,
            'location_id': location_id_val
        })

    return render_template(
        'device_list.html',
        devices=devices,
        total_devices=total_devices,
        online_devices=online_devices,
        offline_devices=offline_devices,
        pagination=pagination,
        locations=locations,
        cabinets=cabinets_data,
        last_check_time=last_check_time
    )



@device_bp.route('/add', methods=['GET', 'POST'])
@device_bp.route('/cabinet/<int:cabinet_id>/add', methods=['GET', 'POST'])
@login_required
@permission_required('device:edit')
def device_add(cabinet_id=None):
    """添加设备"""
    cabinet = None
    if cabinet_id:
        cabinet = Cabinet.query.get_or_404(cabinet_id)
    
    cabinets = Cabinet.query.all()
    snmp_settings = SNMPSetting.query.filter_by(enabled=True).order_by(SNMPSetting.name).all()
    credentials = Credential.query.filter_by(enabled=True).order_by(Credential.name).all()
    
    if request.method == 'POST':
        try:
            # 获取必填字段
            name = request.form.get('name')
            management_ip = request.form.get('management_ip')
            
            if not name or not management_ip:
                flash('设备名称和管理IP地址为必填项', 'error')
                return render_template('device_add.html',
                                     cabinet=cabinet,
                                     cabinets=cabinets,
                                     cabinet_id=cabinet_id,
                                     snmp_settings=snmp_settings,
                                     credentials=credentials)

            # 检查设备名称是否已存在
            existing = Device.query.filter_by(name=name).first()
            if existing:
                flash(f'设备名称 {name} 已存在', 'error')
                return render_template('device_add.html',
                                     cabinet=cabinet,
                                     cabinets=cabinets,
                                     cabinet_id=cabinet_id,
                                     snmp_settings=snmp_settings,
                                     credentials=credentials)

            # 检查管理IP是否已存在
            existing = Device.query.filter_by(management_ip=management_ip).first()
            if existing:
                flash(f'管理IP {management_ip} 已存在', 'error')
                return render_template('device_add.html',
                                     cabinet=cabinet,
                                     cabinets=cabinets,
                                     cabinet_id=cabinet_id,
                                     snmp_settings=snmp_settings,
                                     credentials=credentials)
            
            # 处理序列号和资产编号
            serial_number = request.form.get('serial_number', '').strip()
            asset_number = request.form.get('asset_number', '').strip()
            
            if serial_number:
                existing = Device.query.filter_by(serial_number=serial_number).first()
                if existing:
                    flash(f'序列号 {serial_number} 已存在', 'error')
                    return render_template('device_add.html',
                                         cabinet=cabinet,
                                         cabinets=cabinets,
                                         cabinet_id=cabinet_id,
                                         snmp_settings=snmp_settings,
                                         credentials=credentials)

            if asset_number:
                existing = Device.query.filter_by(asset_number=asset_number).first()
                if existing:
                    flash(f'资产编号 {asset_number} 已存在', 'error')
                    return render_template('device_add.html',
                                         cabinet=cabinet,
                                         cabinets=cabinets,
                                         cabinet_id=cabinet_id,
                                         snmp_settings=snmp_settings,
                                         credentials=credentials)
            
            # 创建设备对象
            device = Device(
                name=name,
                device_type=request.form.get('device_type'),
                brand=request.form.get('brand'),
                model=request.form.get('model'),
                serial_number=serial_number or None,
                asset_number=asset_number or None,
                cabinet_id=request.form.get('cabinet_id') or cabinet_id or None,
                position_u=request.form.get('position_u', type=int),  # 空字符串或非数字会返回 None
                height_u=request.form.get('height_u', 1, type=int),
                rack_side=request.form.get('rack_side'),
                management_ip=management_ip,
                mac_address=request.form.get('mac_address'),
                snmp_community=request.form.get('snmp_community'),
                snmp_version=request.form.get('snmp_version', 2, type=int),
                ssh_username=request.form.get('ssh_username'),
                ssh_password=request.form.get('ssh_password'),
                snmp_setting_id=request.form.get('snmp_setting_id', type=int) or None,
                credential_id=request.form.get('credential_id', type=int) or None,
                manufacturer=request.form.get('manufacturer'),
                owner=request.form.get('owner'),
                department=request.form.get('department'),
                power_supply=request.form.get('power_supply'),
                os_version=request.form.get('os_version'),
                software_info=request.form.get('software_info'),
                description=request.form.get('description')
            )
            
            # 处理日期字段 - 使用 datetime.strptime 而不是 datetime.strptime
            purchase_date_str = request.form.get('purchase_date')
            warranty_expiry_str = request.form.get('warranty_expiry')
            
            if purchase_date_str:
                device.purchase_date = datetime.strptime(purchase_date_str, '%Y-%m-%d').date()
            if warranty_expiry_str:
                device.warranty_expiry = datetime.strptime(warranty_expiry_str, '%Y-%m-%d').date()
            
            # 保存到数据库
            db.session.add(device)
            db.session.commit()
            log_audit('create', 'device', device.id, f"创建设备: {device.name}", details={'ip': device.management_ip, 'type': device.device_type})

            # 记录操作日志
            log_operation('create', 'device', device.id, device.name, '添加新设备')
            log_activity(
            type='device',
            device_type=device.device_type,
            name=device.name,
            action='添加设备',
            detail=f'IP: {device.management_ip}, 型号: {device.model}'
        )
            
            flash('设备添加成功', 'success')
            
            # 根据来源决定重定向
            if cabinet_id:
                return redirect(url_for('cabinet.cabinet_detail', id=cabinet_id))
            else:
                return redirect(url_for('device.device_list'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'添加设备失败: {str(e)}', 'error')
    
    return render_template('device_add.html',
                         cabinets=cabinets,
                         cabinet=cabinet,
                         cabinet_id=cabinet_id,
                         snmp_settings=snmp_settings,
                         credentials=credentials)

@device_bp.route('/<int:id>')
@login_required
@permission_required('device:view')
def device_detail(id):
    device = Device.query.get_or_404(id)
    
    # 获取关联的接口
    interfaces = Interface.query.filter_by(device_id=id).all()   # 新增
    
    # 原有代码...
    cabinet = device.cabinet if device.cabinet else None
    location = cabinet.location if cabinet else None
    
    if device.position_u and device.height_u:
        u_start = device.position_u
        u_end = device.position_u + device.height_u - 1
        u_range = f"{u_start}-{u_end}U"
    else:
        u_range = "未配置"
    
    operation_logs = OperationLog.query.filter(
        OperationLog.resource_type == 'device',
        OperationLog.resource_id == id
    ).order_by(OperationLog.created_at.desc()).limit(10).all()
    
    return render_template(
        'device_detail.html',
        device=device,
        interfaces=interfaces,          # 传入模板
        cabinet=cabinet,
        location=location,
        u_range=u_range,
        operation_logs=operation_logs,
        datetime=datetime
    )




@device_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('device:edit')
def device_edit(id):
    """编辑设备 - 支持名称/IP不变时不误报冲突"""
    device = Device.query.get_or_404(id)

    # 获取所有机房（用于下拉选择）
    all_locations = Location.query.order_by(Location.name).all()
    
    # 获取所有机柜（用于下拉选择）- 默认全部
    all_cabinets = Cabinet.query.join(Cabinet.location).order_by(
        Location.name, Cabinet.name
    ).all() if hasattr(Cabinet, 'location') else Cabinet.query.all()

    current_date = datetime.utcnow().date()
    snmp_settings = SNMPSetting.query.filter_by(enabled=True).order_by(SNMPSetting.name).all()
    credentials = Credential.query.filter_by(enabled=True).order_by(Credential.name).all()

    if request.method == 'POST':
        form_data = {
            'name': request.form.get('name', '').strip(),
            'device_type': request.form.get('device_type', '').strip(),
            'management_ip': request.form.get('management_ip', '').strip(),
            'management_mac': request.form.get('management_mac', '').strip(),
            'location_id': request.form.get('location_id'),
            'cabinet_id': request.form.get('cabinet_id'),
            'position_u': request.form.get('position_u'),
            'height_u': request.form.get('height_u', '1'),
            'manufacturer': request.form.get('manufacturer', '').strip(),
            'model': request.form.get('model', '').strip(),
            'serial_number': request.form.get('serial_number', '').strip(),
            'brand': request.form.get('brand', '').strip(),
            'status': request.form.get('status', 'unknown'),
            'snmp_community': request.form.get('snmp_community', '').strip(),
            'snmp_version': 1 if request.form.get('snmp_version') == '1' else 3 if request.form.get('snmp_version') == '3' else 2,
            'ssh_username': request.form.get('ssh_username', '').strip(),
            'ssh_password': request.form.get('ssh_password', '').strip(),
            'snmp_setting_id': request.form.get('snmp_setting_id', type=int),
            'credential_id': request.form.get('credential_id', type=int),
            'asset_number': request.form.get('asset_number', '').strip(),
            'owner': request.form.get('owner', '').strip(),
            'department': request.form.get('department', '').strip(),
            'power_supply': request.form.get('power_supply', '').strip(),
            'os_version': request.form.get('os_version', '').strip(),
            'software_info': request.form.get('software_info', '').strip(),
            'purchase_date': request.form.get('purchase_date'),
            'warranty_expiry': request.form.get('warranty_expiry'),
            'purchase_price': request.form.get('purchase_price'),
            'vendor': request.form.get('vendor', '').strip(),
            'description': request.form.get('description', '').strip(),
            'notes': request.form.get('notes', '').strip(),
            'is_wireless_controller': request.form.get('is_wireless_controller') == 'on',
            'controller_vendor': request.form.get('controller_vendor', 'auto').strip() or 'auto',
        }

        errors = []

        # ---------- 1. 必填与格式验证 ----------
        if not form_data['name']:
            errors.append('设备名称不能为空')

        if not form_data['management_ip']:
            errors.append('管理IP地址不能为空')
        elif not validate_ip(form_data['management_ip']):
            errors.append('管理IP地址格式不正确')

        # ---------- 2. 唯一性验证（排除当前设备）----------
        current_id = int(device.id)

        # 设备名称唯一性（排除自己）
        existing_name = Device.query.filter(
            Device.name == form_data['name'],
            Device.id != current_id
        ).first()
        if existing_name:
            errors.append(f'设备名称 "{form_data["name"]}" 已被其他设备使用（ID: {existing_name.id}）')

        # 管理IP唯一性（排除自己）
        existing_ip = Device.query.filter(
            Device.management_ip == form_data['management_ip'],
            Device.id != current_id
        ).first()
        if existing_ip:
            errors.append(f'管理IP地址 "{form_data["management_ip"]}" 已被其他设备使用（ID: {existing_ip.id}）')

        # ---------- 3. 机柜U位冲突检查（排除自身）----------
        if form_data['cabinet_id']:
            try:
                cabinet = Cabinet.query.get(int(form_data['cabinet_id']))
                if cabinet:
                    cabinet_height = cabinet.height_u or 42
                    pos = form_data['position_u']
                    height = form_data['height_u']
                    if pos:
                        pos = int(pos)
                    else:
                        pos = None
                    height = int(height) if height else 1

                    if pos:
                        if pos < 1 or pos > cabinet_height:
                            errors.append(f'U位位置必须在 1 到 {cabinet_height} 之间')
                        if pos + height - 1 > cabinet_height:
                            errors.append(f'设备高度超出机柜范围（机柜总高：{cabinet_height}U）')

                        # 检查U位重叠（排除当前设备）
                        overlap = Device.query.filter(
                            Device.cabinet_id == cabinet.id,
                            Device.id != device.id,
                            Device.position_u <= pos + height - 1,
                            Device.position_u + Device.height_u - 1 >= pos
                        ).all()
                        if overlap:
                            names = ', '.join([d.name for d in overlap])
                            errors.append(f'U位位置与以下设备冲突：{names}')
            except ValueError:
                errors.append('U位位置和设备高度必须是有效的数字')

        # ---------- 4. 价格有效性 ----------
        if form_data['purchase_price']:
            try:
                price = float(form_data['purchase_price'])
                if price < 0:
                    errors.append('购买价格不能为负数')
            except ValueError:
                errors.append('购买价格必须是有效的数字')

        # 如果有错误，返回编辑页面并保留用户输入
        if errors:
            for err in errors:
                flash(err, 'error')
            return render_template(
                'device_edit.html',
                device=device,
                all_cabinets=all_cabinets,
                current_date=current_date,
                form_data=form_data,
                snmp_settings=snmp_settings,
                credentials=credentials
            )

        # ---------- 5. 更新设备对象 ----------
        try:
            # 基础信息
            device.name = form_data['name']
            device.device_type = form_data['device_type'] or None
            device.management_ip = form_data['management_ip']
            device.management_mac = form_data['management_mac'] or None

            # 机房位置
            if form_data['location_id']:
                device.location_id = int(form_data['location_id'])
            else:
                device.location_id = None

            # 机柜位置
            if form_data['cabinet_id']:
                device.cabinet_id = int(form_data['cabinet_id'])
                device.position_u = int(form_data['position_u']) if form_data['position_u'] else None
                device.height_u = int(form_data['height_u']) if form_data['height_u'] else 1
            else:
                device.cabinet_id = None
                device.position_u = None
                device.height_u = 1

            # 规格信息
            device.manufacturer = form_data['manufacturer'] or None
            device.model = form_data['model'] or None
            device.serial_number = form_data['serial_number'] or None
            device.brand = form_data['brand'] or None
            device.status = form_data['status']

            # SNMP
            device.snmp_community = form_data['snmp_community'] or None
            device.snmp_version = form_data['snmp_version']
            device.snmp_setting_id = form_data['snmp_setting_id'] or None
            device.credential_id = form_data['credential_id'] or None

            # SSH（仅当密码非空时更新，否则保留原密码）
            if form_data['ssh_username']:
                device.ssh_username = form_data['ssh_username']
            if form_data['ssh_password']:
                device.ssh_password = form_data['ssh_password']  # 建议加密存储

            # 资产信息
            device.asset_number = form_data['asset_number'] or None
            device.owner = form_data['owner'] or None
            device.department = form_data['department'] or None

            # 技术规格
            device.power_supply = form_data['power_supply'] or None
            device.os_version = form_data['os_version'] or None
            device.software_info = form_data['software_info'] or None

            # 日期字段
            device.purchase_date = datetime.strptime(form_data['purchase_date'], '%Y-%m-%d').date() if form_data['purchase_date'] else None
            device.warranty_expiry = datetime.strptime(form_data['warranty_expiry'], '%Y-%m-%d').date() if form_data['warranty_expiry'] else None

            # 采购信息
            device.purchase_price = float(form_data['purchase_price']) if form_data['purchase_price'] else None
            device.vendor = form_data['vendor'] or None

            # 备注
            device.description = form_data['description'] or None
            device.notes = form_data['notes'] or None

            # 无线控制器标记（供 AC/CAPWAP 发现 AP）
            device.is_wireless_controller = form_data['is_wireless_controller']
            device.controller_vendor = form_data['controller_vendor']

            device.updated_at = datetime.utcnow()

            db.session.commit()
            log_audit('update', 'device', device.id, f"更新设备: {device.name}", details={'ip': device.management_ip})

            # 操作日志（假设你有一个 log_operation 函数）
            log_operation(
                'update', 'device', device.id, device.name,
                f'更新设备信息: {device.name} (IP: {device.management_ip})',
                current_user.id if hasattr(current_user, 'id') else None
            )

            flash(f'设备 {device.name} 已成功更新', 'success')
            return redirect(url_for('device.device_detail', id=device.id))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'设备编辑错误: {str(e)}\n{traceback.format_exc()}')
            flash(f'更新失败：{str(e)}', 'error')

    return render_template(
        'device_edit.html',
        device=device,
        all_cabinets=all_cabinets,
        all_locations=all_locations,
        current_date=current_date,
        snmp_settings=snmp_settings,
        credentials=credentials
    )

@device_bp.route('/api/cabinets_by_location')
@login_required
@permission_required('device:view')
def get_cabinets_by_location():
    """根据机房ID获取机柜列表"""
    location_id = request.args.get('location_id', type=int)
    
    if not location_id:
        return jsonify({'success': False, 'message': '请提供机房ID'}), 400
    
    cabinets = Cabinet.query.filter_by(location_id=location_id).order_by(Cabinet.name).all()
    
    cabinet_list = [{
        'id': c.id,
        'name': c.name,
        'height_u': c.height_u or 42,
        'description': c.description or ''
    } for c in cabinets]
    
    return jsonify({
        'success': True,
        'cabinets': cabinet_list,
        'count': len(cabinet_list)
    })

@device_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@permission_required('device:edit')
def delete_device(id):
    device = Device.query.get_or_404(id)
    try:
        # 删除设备监控配置（新增）
        DeviceMonitorConfig.query.filter_by(device_id=device.id).delete()

        # 解除备件关联
        SparePart.query.filter_by(installed_device_id=device.id).update({'installed_device_id': None})

        # 删除告警事件
        AlertEvent.query.filter_by(device_id=device.id).delete()

        # 删除监控数据
        MonitorData.query.filter_by(device_id=device.id).delete()
        DeviceMonitorLog.query.filter_by(device_id=device.id).delete()
        InterfaceMonitorData.query.filter_by(device_id=device.id).delete()

        # 删除库存事务
        InventoryTransaction.query.filter_by(device_id=device.id).delete()

        # 删除拓扑连接
        ConnectionPath.query.filter(
            (ConnectionPath.source_device_id == device.id) |
            (ConnectionPath.target_device_id == device.id)
        ).delete(synchronize_session=False)

        # 最后删除设备本身（接口会通过 cascade 自动删除）
        db.session.delete(device)
        db.session.commit()
        log_audit('delete', 'device', id, f"删除设备: {device.name}")

        # 根据请求类型返回响应
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({"success": True, "message": f"设备 '{device.name}' 已成功删除"})
        else:
            flash(f'设备 "{device.name}" 已成功删除', 'success')
            return redirect(url_for('device.device_list'))

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"删除设备失败 (ID: {id}): {str(e)}")

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({"success": False, "message": "删除失败，请检查关联数据或联系管理员"}), 500
        else:
            flash('删除失败！该设备存在关联数据，请先处理或联系管理员。', 'error')
            return redirect(request.referrer or url_for('device.device_list'))

    # 安全网：防止意外无返回
    return abort(500)

# device.py - 修改device_ping函数使用更严格的检测
@device_bp.route('/<int:id>/ping', methods=['POST'])
@login_required
@permission_required('device:edit')
def device_ping(id):
    """Ping设备 - 使用严格检测"""
    try:
        device = Device.query.get_or_404(id)
        
        if not device.management_ip:
            return jsonify({
                'success': False,
                'message': '设备未配置管理IP'
            }), 400
        
        # 执行严格的Ping检测
        #from utils import ping_device_strict
        success, response_time = ping_device_strict(device.management_ip)
        
        if success:
            device.status = 'online'
            device.last_seen = datetime.utcnow()
            device.ping_time = response_time
        else:
            device.status = 'offline'
            device.ping_time = 0
        
        device.last_checked = datetime.utcnow()
        db.session.commit()
        log_audit('execute', 'device', device.id, f"Ping检测设备: {device.name}", details={'success': success, 'response_time': response_time})

        log_operation('ping', 'device', device.id, device.name,
                     f'Ping检测: {"成功" if success else "失败"}, 响应时间: {response_time}ms')

        return jsonify({
            'success': True,
            'online': success,
            'response_time': response_time,
            'message': f'Ping检测{"成功" if success else "失败"}' +
                      (f'，响应时间: {response_time}ms' if success and response_time > 0 else '')
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Ping检测失败: {str(e)}'
        }), 500

@device_bp.route('/<int:id>/check_status', methods=['POST'])
@login_required
@permission_required('device:edit')
def device_check_status(id):
    """检查设备状态"""
    try:
        device = Device.query.get_or_404(id)
        
        if not device.management_ip:
            return jsonify({
                'success': False,
                'message': '设备未配置管理IP'
            })
        
        # 执行Ping检测
        success, response_time = ping_device(device.management_ip)
        
        if success:
            device.status = 'online'
            device.last_seen = datetime.utcnow()
            device.ping_time = response_time
        else:
            device.status = 'offline'
            device.ping_time = 0
        
        device.last_checked = datetime.utcnow()
        db.session.commit()
        log_audit('execute', 'device', device.id, f"状态检查: {device.name}", details={'status': 'online' if success else 'offline'})

        log_operation('check_status', 'device', device.id, device.name,
                     f'状态检查: {"在线" if success else "离线"}')

        return jsonify({
            'success': True,
            'status': 'online' if success else 'offline',
            'response_time': response_time,
            'message': f'设备状态: {"在线" if success else "离线"}'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'状态检查失败: {str(e)}'
        })

@device_bp.route('/batch_ping', methods=['POST'])
@login_required
@permission_required('device:edit')
def batch_ping():
    """批量Ping检测"""
    try:
        data = request.get_json()
        device_ids = data.get('device_ids', [])
        
        if not device_ids:
            return jsonify({
                'success': False,
                'message': '请选择要检测的设备'
            }), 400
        
        results = []
        online_count = 0
        offline_count = 0
        
        for device_id in device_ids:
            device = Device.query.get(device_id)
            if not device:
                continue
            
            success = False
            response_time = 0
            
            if device.management_ip:
                success, response_time = ping_device(device.management_ip)
            
            if success:
                device.status = 'online'
                device.last_seen = datetime.utcnow()
                device.ping_time = response_time
                online_count += 1
            else:
                device.status = 'offline'
                device.ping_time = 0
                offline_count += 1
            
            device.last_checked = datetime.utcnow()
            
            results.append({
                'device_id': device_id,
                'device_name': device.name,
                'online': success,
                'response_time': response_time
            })
        
        db.session.commit()
        log_audit('execute', 'device', None, f"批量Ping检测 {len(device_ids)} 个设备", details={'online_count': online_count, 'offline_count': offline_count})

        log_operation('batch_ping', 'device', None, None,
                     f'批量Ping检测{len(device_ids)}个设备，在线{online_count}个，离线{offline_count}个')

        return jsonify({
            'success': True,
            'online_count': online_count,
            'offline_count': offline_count,
            'results': results,
            'message': f'批量检测完成：在线{online_count}个，离线{offline_count}个'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'批量Ping检测失败: {str(e)}'
        }), 500

@device_bp.route('/ping_all', methods=['POST'])
@login_required
@permission_required('device:edit')
def ping_all():
    """Ping所有设备"""
    try:
        devices = Device.query.filter(Device.management_ip.isnot(None)).all()
        
        online_count = 0
        offline_count = 0
        
        for device in devices:
            success, response_time = ping_device(device.management_ip)
            
            if success:
                device.status = 'online'
                device.last_seen = datetime.utcnow()
                device.ping_time = response_time
                online_count += 1
            else:
                device.status = 'offline'
                device.ping_time = 0
                offline_count += 1
            
            device.last_checked = datetime.utcnow()
        
        db.session.commit()
        log_audit('execute', 'device', None, f"Ping所有设备: 在线{online_count}个, 离线{offline_count}个", details={'online_count': online_count, 'offline_count': offline_count})

        log_operation('ping_all', 'device', None, None,
                     f'Ping所有设备: 在线{online_count}个，离线{offline_count}个')

        return jsonify({
            'success': True,
            'online_count': online_count,
            'offline_count': offline_count,
            'message': f'Ping检测完成：在线{online_count}个，离线{offline_count}个'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'批量Ping检测失败: {str(e)}'
        }), 500


# ========== API路由：获取机柜U位信息 ==========

@device_bp.route('/api/cabinets/<int:cabinet_id>/u-info')
@login_required
@permission_required('device:view')
def get_cabinet_u_info(cabinet_id):
    """获取机柜U位占用信息（API接口）"""
    try:
        cabinet = Cabinet.query.get_or_404(cabinet_id)
        
        # 获取机柜中所有设备
        devices = Device.query.filter_by(cabinet_id=cabinet_id).all()
        
        # 构建已占用的U位信息
        used_u = []
        for device in devices:
            if device.position_u and device.height_u:
                used_u.append({
                    'start': device.position_u,
                    'end': device.position_u + device.height_u - 1,
                    'device': device.name,
                    'device_id': device.id
                })
        
        # 计算总U位数
        total_u = cabinet.total_u or 42  # 默认42U
        
        # 计算可用U位
        used_slots = set()
        for used in used_u:
            for i in range(used['start'], used['end'] + 1):
                used_slots.add(i)
        
        available_u = total_u - len(used_slots)
        
        return jsonify({
            'success': True,
            'cabinet_id': cabinet_id,
            'cabinet_name': cabinet.name,
            'total_u': total_u,
            'used_u': used_u,
            'available_u': available_u,
            'used_slots': sorted(list(used_slots))
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500

# ========== 导出功能 ==========

@device_bp.route('/export')
@login_required
@permission_required('device:view')
def export_devices():
    """导出设备列表为Excel"""
    try:
        # 获取所有设备
        devices = Device.query.all()
        
        # 准备数据
        headers = [
            '设备名称', '设备类型', '厂商', '型号', '序列号',
            '管理IP', 'MAC地址', '状态', '机柜', 'U位',
            '最后检查时间', '备注'
        ]
        
        data = []
        for device in devices:
            cabinet_name = device.cabinet.name if device.cabinet else ''
            position = f"{device.position_u}-{device.position_u + device.height_u - 1}" if device.position_u else ''
            
            data.append([
                device.name,
                device.device_type,
                device.brand,
                device.model,
                device.serial_number or '',
                device.management_ip,
                device.mac_address or '',
                device.status,
                cabinet_name,
                position,
                (device.last_checked + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S') if device.last_checked else '',
                device.description or ''
            ])
        
        # 创建Excel文件
        output = BytesIO()
        workbook = xlsxwriter.Workbook(output)
        worksheet = workbook.add_worksheet('设备列表')
        
        # 设置表头样式
        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#f8f9fa',
            'border': 1,
            'align': 'center'
        })
        
        # 写入表头
        for col, header in enumerate(headers):
            worksheet.write(0, col, header, header_format)
        
        # 写入数据
        for row, row_data in enumerate(data, start=1):
            for col, value in enumerate(row_data):
                worksheet.write(row, col, value)
        
        # 调整列宽
        worksheet.set_column(0, len(headers)-1, 20)
        workbook.close()
        
        output.seek(0)
        
        # 记录操作日志
        log_operation('export', 'device', None, None, f'导出{len(devices)}个设备')
        
        # 返回文件
        return send_file(
            output,
            as_attachment=True,
            download_name=f'设备列表_{dt.now().strftime("%Y%m%d_%H%M%S")}.xlsx',
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        
    except Exception as e:
        flash(f'导出失败：{str(e)}', 'error')
        return redirect(url_for('device.device_list'))


# 辅助函数：检查文件类型
def allowed_file(filename):
    """检查文件是否为允许的Excel格式"""
    ALLOWED_EXTENSIONS = {'xlsx', 'xls'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS




@device_bp.route('/devices/scan', methods=['GET', 'POST'])
@login_required
@permission_required('device:edit')
def device_scan():
    """SNMP扫描设备"""
    if request.method == 'POST':
        try:
            start_ip = request.form.get('start_ip')
            end_ip = request.form.get('end_ip')
            community = request.form.get('community') or 'public'
            
            scanner = SNMPScanner(community=community)
            results = scanner.scan_ip_range(start_ip, end_ip)
            
            discovered_devices = []
            
            for result in results:
                data = result['data']
                
                # 从sysName获取设备名称，如果没有则使用IP
                device_name = data.get('1.3.6.1.2.1.1.5.0', f'Device-{result["ip"]}')
                device_description = data.get('1.3.6.1.2.1.1.1.0', '')
                device_location = data.get('1.3.6.1.2.1.1.6.0', '')
                
                # 检查是否已存在
                existing = Device.query.filter_by(management_ip=result['ip']).first()
                
                if not existing:
                    device = Device(
                        name=device_name,
                        management_ip=result['ip'],
                        device_type='switch',  # 默认为交换机
                        manufacturer='Unknown',
                        model='Unknown',
                        snmp_community=community,
                        status='unknown',
                        description=f'通过SNMP扫描发现\n描述: {device_description}\n位置: {device_location}'
                    )
                    db.session.add(device)
                    discovered_devices.append(device_name)
            
            if discovered_devices:
                db.session.commit()
                log_audit('execute', 'device', None, f"SNMP扫描发现 {len(discovered_devices)} 台设备", details={'discovered_count': len(discovered_devices)})
                log_operation('scan', 'device', None, None, f'发现{len(discovered_devices)}台设备')
                flash(f'扫描完成，发现{len(discovered_devices)}台新设备', 'success')
            else:
                flash('扫描完成，未发现新设备', 'info')
            
        except Exception as e:
            db.session.rollback()
            flash(f'扫描失败: {str(e)}', 'danger')
    
    return render_template('device_scan.html')


# device.py - 修改 device_snmp_check 函数

# device.py - 修改 SNMP 检测函数
"""
@device_bp.route('/<int:id>/snmp_check', methods=['POST'])
@login_required
def device_snmp_check(id):
    #单个设备SNMP检测
    try:
        device = Device.query.get_or_404(id)
        
        if not device.management_ip:
            return jsonify({
                'success': False,
                'message': '设备未配置管理IP'
            })
        
        # 获取SNMP参数
        snmp_community = request.form.get('snmp_community', 'public')
        snmp_version = request.form.get('snmp_version', '2c')
        
        # 尝试使用修复版的 SNMP 检测
 
        result = scan_ip_with_snmp(
            ip=device.management_ip,
            community=snmp_community,
            version=snmp_version
        )


        if result.get('success'):
            # 更新设备信息
            if result.get('sys_name') and result['sys_name'] != f"设备_{device.management_ip}":
                device.name = result['sys_name']
            if result.get('sys_descr'):
                device.description = result['sys_descr']
            if result.get('manufacturer') and result['manufacturer'] != '未知厂商':
                device.manufacturer = result['manufacturer']
            if result.get('device_type') and result['device_type'] != 'unknown':
                device.device_type = result['device_type']
            
            device.snmp_community = snmp_community
            device.snmp_version = 1 if snmp_version == '1' else 2
            device.last_checked = datetime.utcnow()
            device.status = 'online'
            
            db.session.commit()
            
            log_operation('snmp_check', 'device', device.id, device.name, 
                         f'SNMP检测成功: {result.get("sys_name", "未知设备")}')
            
            return jsonify({
                'success': True,
                'sysinfo': result,
                'message': 'SNMP检测成功'
            })
        else:
            return jsonify({
                'success': False,
                'message': f'SNMP检测失败: {result.get("error", "未知错误")}'
            })
            
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'SNMP检测异常: {str(e)}'
        }), 500

"""
@device_bp.route('/<int:id>/snmp_check', methods=['POST'])
@login_required
@permission_required('device:edit')
def device_snmp_check(id):
    """单个设备SNMP检测 - 使用 cmdgen 同步方式，无 asyncio 依赖"""
    try:
        device = Device.query.get_or_404(id)
        
        if not device.management_ip:
            return jsonify({
                'success': False,
                'message': '设备未配置管理IP'
            })
        
        # 获取SNMP参数
        snmp_community = request.form.get('snmp_community', 'public')
        snmp_version = request.form.get('snmp_version', '2c')
        
        # === 直接内联 SNMP 查询逻辑（避免 utils 中的 hlapi 依赖）===
        try:
            from pysnmp.entity.rfc3413.oneliner import cmdgen
        except ImportError:
            return jsonify({
                'success': False,
                'message': 'pysnmp 未安装或版本不兼容（请使用 pysnmp==4.4.12）'
            })

        # 创建命令生成器（每次调用新建，线程安全）
        cmd_gen = cmdgen.CommandGenerator()
        mp_model = 0 if snmp_version == '1' else 1
        community_data = cmdgen.CommunityData(snmp_community, mpModel=mp_model)
        transport = cmdgen.UdpTransportTarget(
            (device.management_ip, 161),
            timeout=3,
            retries=1
        )

        # 执行 GET 请求
        errorIndication, errorStatus, errorIndex, varBinds = cmd_gen.getCmd(
            community_data,
            transport,
            cmdgen.MibVariable('1.3.6.1.2.1.1.1.0'),  # sysDescr
            cmdgen.MibVariable('1.3.6.1.2.1.1.5.0'),  # sysName
            cmdgen.MibVariable('1.3.6.1.2.1.1.6.0'),  # sysLocation
            cmdgen.MibVariable('1.3.6.1.2.1.1.2.0'),  # sysObjectID
            lookupMib=False
        )

        if errorIndication or errorStatus:
            error_msg = str(errorIndication) if errorIndication else str(errorStatus.prettyPrint())
            return jsonify({
                'success': False,
                'message': f'SNMP检测失败: {error_msg}'
            })

        # 解析结果
        sys_descr = str(varBinds[0][1]) if varBinds[0][1] else ''
        sys_name = str(varBinds[1][1]) if varBinds[1][1] else f"设备_{device.management_ip}"
        sys_location = str(varBinds[2][1]) if varBinds[2][1] else ''
        sys_object_id = str(varBinds[3][1]) if varBinds[3][1] else ''

        # 简单厂商/类型推断（可扩展）
        manufacturer = '未知厂商'
        device_type = 'unknown'
        descr_lower = sys_descr.lower()
        if 'cisco' in descr_lower:
            manufacturer = 'Cisco'
            device_type = 'switch' if 'switch' in descr_lower else 'router'
        elif 'huawei' in descr_lower or 'h3c' in descr_lower:
            manufacturer = 'Huawei'
            device_type = 'switch' if 'switch' in descr_lower else 'router'
        elif 'h3c' in descr_lower:
            manufacturer = 'H3C'
        elif 'linux' in descr_lower:
            manufacturer = 'Linux'
            device_type = 'server'

        result = {
            'success': True,
            'sys_name': sys_name,
            'sys_descr': sys_descr,
            'sys_location': sys_location,
            'sys_object_id': sys_object_id,
            'manufacturer': manufacturer,
            'device_type': device_type
        }

        # === 更新设备信息 ===
        if result['sys_name'] and result['sys_name'] != f"设备_{device.management_ip}":
            device.name = result['sys_name']
        if result['sys_descr']:
            device.description = result['sys_descr']
        if result['manufacturer'] != '未知厂商':
            device.manufacturer = result['manufacturer']
        if result['device_type'] != 'unknown':
            device.device_type = result['device_type']
        
        device.snmp_community = snmp_community
        device.snmp_version = 1 if snmp_version == '1' else 2
        device.last_checked = datetime.utcnow()
        device.status = 'online'
        
        db.session.commit()
        log_audit('execute', 'device', device.id, f"SNMP检测设备: {device.name}", details={'manufacturer': manufacturer, 'device_type': device_type})

        log_operation('snmp_check', 'device', device.id, device.name,
                     f'SNMP检测成功: {result["sys_name"]}')
        
        return jsonify({
            'success': True,
            'sysinfo': result,
            'message': 'SNMP检测成功'
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'SNMP检测异常: {str(e)}'
        }), 500


#====================================

def validate_mac(mac):
    """验证 MAC 地址格式 (00:11:22:33:44:55 或 00-11-22-33-44-55)"""
    if not mac:
        return True
    pattern = r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$'
    return re.match(pattern, mac) is not None

def validate_ip(ip):
    """验证 IPv4 地址格式 (简单点分十进制)"""
    if not ip:
        return True
    pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
    if not re.match(pattern, ip):
        return False
    # 检查每个段是否在 0-255 范围内
    parts = ip.split('.')
    for part in parts:
        if int(part) > 255:
            return False
    return True

#================
# def validate_mac(mac):
#     """验证 MAC 地址格式"""
#     if not mac:
#         return True
#     pattern = r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$'
#     return re.match(pattern, mac) is not None

# def validate_ip(ip):
#     """简单验证 IPv4 地址格式"""
#     if not ip:
#         return True
#     pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
#     if not re.match(pattern, ip):
#         return False
#     parts = ip.split('.')
#     return all(0 <= int(part) <= 255 for part in parts)

@device_bp.route('/interface/add', methods=['GET', 'POST'])
@login_required
@permission_required('device:edit')
def interface_add():
    """添加网络接口（可选关联邻居连接）"""
    devices = Device.query.order_by(Device.name).all()

    if request.method == 'POST':
        # 获取表单数据
        device_id = request.form.get('device_id', type=int)
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        mac_address = request.form.get('mac_address', '').strip()
        ip_address = request.form.get('ip_address', '').strip()
        subnet_mask = request.form.get('subnet_mask', '').strip()
        speed = request.form.get('speed', type=int)
        mtu = request.form.get('mtu', type=int, default=1500)
        admin_status = request.form.get('admin_status', 'up')
        oper_status = request.form.get('oper_status', 'down')

        # 邻居信息（可选）
        neighbor_device_id = request.form.get('neighbor_device_id', type=int)
        neighbor_interface_id = request.form.get('neighbor_interface_id', type=int)
        discovery_protocol = request.form.get('discovery_protocol', '').strip() or None

        # 基本验证
        errors = []
        if not device_id:
            errors.append('所属设备不能为空')
        if not name:
            errors.append('接口名称不能为空')
        if mac_address and not validate_mac(mac_address):
            errors.append('MAC地址格式不正确，正确格式如: 00:1A:2B:3C:4D:5E')
        if ip_address and not validate_ip(ip_address):
            errors.append('IP地址格式不正确')

        # 邻居信息一致性验证
        if neighbor_device_id and not neighbor_interface_id:
            errors.append('选择了邻居设备，必须选择对应的邻居接口')
        if neighbor_interface_id and not neighbor_device_id:
            errors.append('选择了邻居接口，必须选择对应的邻居设备')

        if errors:
            for error in errors:
                flash(error, 'danger')
            return render_template(
                'interface_add.html',
                devices=devices,
                selected_device_id=device_id,
                form_data=request.form
            )

        # 开始数据库操作
        try:
            # 1. 创建接口
            interface = Interface(
                device_id=device_id,
                name=name,
                description=description or None,
                mac_address=mac_address or None,
                ip_address=ip_address or None,
                subnet_mask=subnet_mask or None,
                speed=speed,
                mtu=mtu,
                admin_status=admin_status,
                oper_status=oper_status
            )
            db.session.add(interface)
            db.session.flush()  # 获取 interface.id

            # 2. 如果提供了完整的邻居信息，创建连接关系
            if neighbor_device_id and neighbor_interface_id:
                # 检查邻居接口是否存在且属于指定的邻居设备
                neighbor_iface = Interface.query.get(neighbor_interface_id)
                if not neighbor_iface:
                    raise ValueError('邻居接口不存在')
                if neighbor_iface.device_id != neighbor_device_id:
                    raise ValueError('邻居接口不属于所选邻居设备')

                connection = ConnectionPath(
                    source_device_id=device_id,
                    source_interface_id=interface.id,
                    source_port=name,
                    target_device_id=neighbor_device_id,
                    target_interface_id=neighbor_interface_id,
                    target_port=neighbor_iface.name,
                    connection_type='physical',      # 可根据需要从表单获取
                    link_status='active',
                    discovered_by=discovery_protocol or 'manual',
                    discovery_time=datetime.now(timezone.utc),
                    confidence=100
                )
                db.session.add(connection)

            # 3. 记录操作日志
            log = OperationLog(
                user_id=current_user.id,
                username=current_user.username,
                operation_type='create',
                resource_type='interface',
                resource_id=interface.id,
                resource_name=name,
                details=f'创建接口: {name} (设备ID: {device_id})' + 
                        ('，并建立连接关系' if neighbor_device_id else ''),
                ip_address=request.remote_addr,
                user_agent=request.user_agent.string
            )
            db.session.add(log)

            db.session.commit()
            log_audit('create', 'interface', interface.id, f"创建接口: {name}", details={'device_id': device_id, 'neighbor_device_id': neighbor_device_id})

            flash(f'接口 {name} 创建成功' +
                  ('，连接关系已建立' if neighbor_device_id else ''), 'success')
            return redirect(url_for('device.device_detail', id=device_id))

        except Exception as e:
            db.session.rollback()
            flash(f'创建失败: {str(e)}', 'danger')
            return render_template(
                'interface_add.html',
                devices=devices,
                selected_device_id=device_id,
                form_data=request.form
            )

    # GET 请求：显示表单，支持从设备详情页预选设备
    selected_device_id = request.args.get('device_id', type=int)
    return render_template(
        'interface_add.html',
        devices=devices,
        selected_device_id=selected_device_id
    )

@device_bp.route('/api/devices/<int:device_id>/interfaces')
@login_required
@permission_required('device:view')
def api_device_interfaces(device_id):
    interfaces = Interface.query.filter_by(device_id=device_id).all()
    data = [{'id': i.id, 'name': i.name, 'ip': i.ip_address} for i in interfaces]
    return jsonify(data)



@device_bp.route('/ip_scan', methods=['POST'])
@login_required
@permission_required('device:edit')
def device_ip_scan():
    """
    IP段SNMP扫描 - 异步模式：立即返回task_id，后台执行
    """
    import threading
    
    print("=" * 60)
    print("📥 收到IP段SNMP扫描请求（异步模式）")
    print("=" * 60)
    
    try:
        data = request.get_json()
        
        ip_range_str = data.get('ip_range')
        snmp_community = data.get('snmp_community', 'public')
        snmp_version = data.get('snmp_version', '2c')
        auto_add = data.get('auto_add', False)
        skip_existing = data.get('skip_existing', True)
        snmp_timeout = int(data.get('snmp_timeout', 2))
        snmp_retries = int(data.get('snmp_retries', 2))
        
        if not ip_range_str:
            return jsonify({'success': False, 'message': '请输入IP段'})
        
        # 创建进度任务
        task_id = progress_manager.create_task('snmp_scan')
        print(f"✅ 创建SNMP扫描任务: {task_id}")
        
        # 保存参数
        scan_params = {
            'ip_range': ip_range_str,
            'snmp_community': snmp_community,
            'snmp_version': snmp_version,
            'auto_add': auto_add,
            'skip_existing': skip_existing,
            'snmp_timeout': snmp_timeout,
            'snmp_retries': snmp_retries,
            'user_id': current_user.id if hasattr(current_user, 'id') else None,
            'username': current_user.username if hasattr(current_user, 'username') else '系统'
        }
        
        # 获取当前应用
        from flask import current_app
        app = current_app._get_current_object()
        
        # 启动后台线程
        thread = threading.Thread(
            target=_run_snmp_scan_task_with_app,
            args=(app, task_id, scan_params)
        )
        thread.daemon = True
        thread.start()
        
        print(f"🚀 SNMP扫描后台任务已启动: {task_id}")
        log_audit('execute', 'device', None, f"提交IP段SNMP扫描任务: {ip_range_str}", details={'ip_range': ip_range_str, 'auto_add': auto_add})

        return jsonify({
            'success': True,
            'message': 'SNMP扫描任务已提交，请查看进度',
            'task_id': task_id,
            'status': 'pending'
        })

    except Exception as e:
        print(f"❌ 提交SNMP扫描任务失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'提交扫描任务失败: {str(e)}'
        }), 500


def _run_snmp_scan_task_with_app(app, task_id, scan_params):
    """带应用上下文的SNMP扫描任务包装器"""
    with app.app_context():
        _run_snmp_scan_task_impl(task_id, scan_params)


def _run_snmp_scan_task_impl(task_id, scan_params):
    """
    实际执行SNMP扫描任务（在应用上下文中运行）
    使用统一的设备服务进行去重
    """
    import time
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    # 导入统一设备服务
    from services.device_service import find_or_create_device, find_device_by_any, update_device_info
    
    print(f"📋 SNMP扫描任务 {task_id} 开始执行")
    
    # 获取锁
    lock = CrossPlatformLock('snmp_scan')
    if not lock.acquire(timeout=30):
        progress_manager.update_progress(
            task_id,
            status='failed',
            message='另一个扫描任务正在执行中，请稍后再试',
            end_time=datetime.now().isoformat()
        )
        return
    
    try:
        # 提取参数
        ip_range_str = scan_params.get('ip_range')
        snmp_community = scan_params.get('snmp_community', 'public')
        snmp_version = scan_params.get('snmp_version', '2c')
        auto_add = scan_params.get('auto_add', False)
        skip_existing = scan_params.get('skip_existing', True)
        snmp_timeout = int(scan_params.get('snmp_timeout', 2))
        snmp_retries = int(scan_params.get('snmp_retries', 2))
        user_id = scan_params.get('user_id')
        username = scan_params.get('username', '系统')
        
        print(f"  - IP段: {ip_range_str}")
        print(f"  - SNMP社区: {snmp_community}")
        print(f"  - SNMP版本: {snmp_version}")
        print(f"  - 自动添加: {auto_add}")
        print(f"  - 超时: {snmp_timeout}秒")
        print(f"  - 重试: {snmp_retries}次")
        
        # 解析IP段
        try:
            ip_list = parse_ip_range(ip_range_str)
            if not ip_list:
                progress_manager.update_progress(
                    task_id, 
                    status='failed', 
                    message='无法解析IP段',
                    end_time=datetime.now().isoformat()
                )
                return
            print(f"📡 解析到 {len(ip_list)} 个IP地址")
        except Exception as e:
            progress_manager.update_progress(
                task_id, 
                status='failed', 
                message=f'IP段解析错误: {str(e)}',
                end_time=datetime.now().isoformat()
            )
            return
        
        total_ips = len(ip_list)
        progress_manager.update_progress(
            task_id,
            status='running',
            total=total_ips,
            current_step=f'开始SNMP扫描 {total_ips} 个IP地址...',
            progress=5,
            processed=0,
            added=0,
            skipped=0,
            failed=0
        )
        
        # 扫描结果
        found_devices = []
        non_snmp_devices = []
        added_count = 0
        skipped_count = 0
        updated_count = 0
        online_count = 0
        offline_count = 0
        completed = 0
        
        print(f"🔍 开始SNMP扫描 {total_ips} 个IP地址...")
        
        def scan_single_ip(ip):
            """扫描单个IP"""
            result = {
                'ip': ip,
                'online': False,
                'snmp_success': False,
                'ping_time': 0,
                'sysinfo': None,
                'error': None,
                'mac_address': None
            }
            
            # 1. Ping检测
            try:
                online, ping_time = ping_device(ip)
                result['online'] = online
                result['ping_time'] = ping_time
                if not online:
                    result['error'] = 'Ping不通'
                    return result
            except Exception as e:
                result['error'] = f'Ping异常: {str(e)}'
                return result
            
            # 2. SNMP检测（获取设备信息）
            try:
                snmp_success, sysinfo = snmp_get_device_info(
                    ip,
                    snmp_community,
                    snmp_version,
                    timeout=snmp_timeout,
                    retries=snmp_retries
                )
                
                if snmp_success:
                    result['snmp_success'] = True
                    result['sysinfo'] = sysinfo
                    
                    # 尝试获取MAC地址（通过ARP或接口表）
                    try:
                        # 方法1: 从ARP表获取MAC
                        arp_entries = get_arp_table(ip, snmp_community)
                        if arp_entries:
                            # 获取设备自身的MAC（通常是第一个）
                            for arp_ip, mac in arp_entries.items():
                                if arp_ip == ip:
                                    result['mac_address'] = mac
                                    break
                            # 如果没找到自己的MAC，取第一个
                            if not result['mac_address'] and arp_entries:
                                result['mac_address'] = list(arp_entries.values())[0]
                    except Exception as mac_error:
                        # MAC获取失败不影响主流程
                        pass
                else:
                    result['error'] = 'SNMP无响应'
            except Exception as e:
                result['error'] = f'SNMP异常: {str(e)}'
            
            return result
        
        # 并发扫描
        concurrent_workers = min(20, len(ip_list))
        with ThreadPoolExecutor(max_workers=concurrent_workers) as executor:
            future_to_ip = {executor.submit(scan_single_ip, ip): ip for ip in ip_list}
            
            for future in as_completed(future_to_ip):
                ip = future_to_ip[future]
                try:
                    result = future.result(timeout=snmp_timeout+5)
                    
                    if result.get('online', False):
                        online_count += 1
                    else:
                        offline_count += 1
                    
                    if result.get('snmp_success', False):
                        sysinfo = result.get('sysinfo', {})
                        device_name = sysinfo.get('sys_name', '').strip()
                        if not device_name:
                            device_name = f"设备_{ip}"
                        else:
                            # 二次清理（保险，snmp_get_device_info中已清理）
                            device_name = clean_snmp_device_name(device_name, ip)
                        
                        # 推断设备类型
                        detected_type, detected_brand, detected_model = infer_device_type_from_snmp(
                            sys_descr=sysinfo.get('sys_descr', ''),
                            sys_object_id=sysinfo.get('sys_object_id', ''),
                            sys_name=sysinfo.get('sys_name', '')
                        )
                        
                        device_data = {
                            'ip': ip,
                            'ping_time': result.get('ping_time', 0),
                            'snmp_success': True,
                            'sysinfo': sysinfo,
                            'device_name': device_name,
                            'description': sysinfo.get('sys_descr', ''),
                            'device_type': detected_type,
                            'brand': detected_brand,
                            'model': detected_model,
                            'mac_address': result.get('mac_address')
                        }
                        found_devices.append(device_data)
                        
                        # 自动添加设备（使用统一服务）
                        if auto_add:
                            try:
                                # ========== 使用统一服务查找设备 ==========
                                # 优先通过IP查找，如果没有则通过MAC查找
                                existing_device = find_device_by_any(
                                    ip=ip,
                                    mac=result.get('mac_address')
                                )
                                
                                if existing_device:
                                    # 设备已存在，更新信息
                                    updates = {
                                        'name': device_name if device_name and device_name != f"设备_{ip}" else None,
                                        'description': sysinfo.get('sys_descr', '')[:500],
                                        'device_type': detected_type if detected_type != 'unknown' else None,
                                        'brand': detected_brand if detected_brand != '未知厂商' else None,
                                        'model': detected_model if detected_model else None,
                                        'snmp_community': snmp_community,
                                        'snmp_version': 1 if snmp_version == '1' else 2,
                                        'status': 'online',
                                        'last_checked': datetime.utcnow(),
                                        'ping_time': result.get('ping_time', 0),
                                    }
                                    
                                    # 更新逻辑：SNMP 数据比默认值/占位值更可靠
                                    for key, value in updates.items():
                                        if value is not None:
                                            current = getattr(existing_device, key)
                                            if key == 'name':
                                                # 名称：占位名用 SNMP 真实名称覆盖；已有真实名仅清理无效字符
                                                current_str = str(current)
                                                is_placeholder = (
                                                    current_str.startswith('Device-') or
                                                    current_str.startswith('设备_') or
                                                    current_str == f"Device-{ip.replace('.', '_')}" or
                                                    current_str == f"设备_{ip}" or
                                                    re.match(r'^Device-\d{1,3}[\._]\d{1,3}[\._]\d{1,3}[\._]\d{1,3}', current_str)
                                                )
                                                if is_placeholder:
                                                    setattr(existing_device, key, value)
                                                else:
                                                    current_clean = clean_snmp_device_name(current_str, '')
                                                    if current_clean != current_str:
                                                        setattr(existing_device, key, value)
                                            elif key in ('device_type', 'brand', 'model', 'manufacturer'):
                                                # 类型/品牌/型号：SNMP 数据直接覆盖默认值、未知或不匹配的
                                                if current is None or current in ('', 'unknown', 'server', '未知厂商', '未知'):
                                                    setattr(existing_device, key, value)
                                                elif key == 'device_type' and current != value:
                                                    # SNMP 检测到不同类型时覆盖（如 server → switch）
                                                    setattr(existing_device, key, value)
                                            else:
                                                if current is None or current == '' or current == 'unknown':
                                                    setattr(existing_device, key, value)
                                    
                                    # 如果MAC地址为空，补充MAC
                                    if result.get('mac_address') and not existing_device.mac_address:
                                        existing_device.mac_address = result.get('mac_address')
                                    
                                    existing_device.updated_at = datetime.utcnow()
                                    db.session.commit()
                                    
                                    updated_count += 1
                                    device_data['added'] = False
                                    device_data['updated'] = True
                                    device_data['skipped'] = False
                                    device_data['device_id'] = existing_device.id
                                    device_data['device_name'] = existing_device.name
                                    
                                    print(f"  ✅ 更新已存在设备: {existing_device.name} ({ip})")
                                else:
                                    # 设备不存在，使用统一服务创建
                                    # 生成唯一名称
                                    final_name = device_name
                                    if Device.query.filter(Device.name == final_name).first():
                                        final_name = f"{device_name}_{ip.replace('.', '_')}"
                                    
                                    # 创建新设备
                                    snmp_ver_int = 1 if snmp_version == '1' else 2
                                    
                                    new_device = find_or_create_device(
                                        ip=ip,
                                        mac=result.get('mac_address'),
                                        name=final_name,
                                        device_type=detected_type if detected_type != 'unknown' else 'unknown',
                                        snmp_community=snmp_community,
                                        snmp_version=snmp_ver_int,
                                        status='online',
                                        last_checked=datetime.utcnow(),
                                        ping_time=result.get('ping_time', 0),
                                        description=sysinfo.get('sys_descr', '')[:500],
                                        brand=detected_brand if detected_brand != '未知厂商' else None,
                                        model=detected_model if detected_model else None,
                                        manufacturer=detected_brand if detected_brand != '未知厂商' else None
                                    )
                                    
                                    db.session.commit()
                                    
                                    added_count += 1
                                    device_data['added'] = True
                                    device_data['updated'] = False
                                    device_data['skipped'] = False
                                    device_data['device_id'] = new_device.id
                                    device_data['device_name'] = new_device.name
                                    
                                    print(f"  ✅ 添加新设备: {new_device.name} ({ip})")
                                    
                                    # 记录日志
                                    try:
                                        log_operation(
                                            'import',
                                            'device',
                                            new_device.id,
                                            final_name,
                                            f'通过SNMP扫描添加，IP: {ip}，类型: {detected_type}',
                                            user_id
                                        )
                                    except:
                                        pass
                                    
                            except IntegrityError as e:
                                db.session.rollback()
                                # 可能是并发导致的重复，尝试再次查找
                                retry_device = find_device_by_any(ip=ip)
                                if retry_device:
                                    updated_count += 1
                                    device_data['added'] = False
                                    device_data['updated'] = True
                                    device_data['skipped'] = False
                                    device_data['device_id'] = retry_device.id
                                    device_data['device_name'] = retry_device.name
                                    print(f"  ✅ 并发恢复: 找到已存在设备 {retry_device.name} ({ip})")
                                else:
                                    skipped_count += 1
                                    device_data['added'] = False
                                    device_data['skipped'] = True
                                    device_data['error'] = '唯一约束冲突'
                                    print(f"  ⚠️ 唯一约束冲突: {ip}")
                            except Exception as e:
                                db.session.rollback()
                                device_data['added'] = False
                                device_data['skipped'] = False
                                device_data['error'] = str(e)
                                print(f"  ❌ 添加设备失败: {ip} - {str(e)}")
                    else:
                        non_snmp_devices.append({
                            'ip': ip,
                            'ping_time': result.get('ping_time', 0),
                            'online': result.get('online', False),
                            'status': 'online_no_snmp' if result.get('online', False) else 'offline',
                            'reason': result.get('error', '未知错误'),
                            'device_name': f'设备_{ip}'
                        })
                    
                except Exception as e:
                    print(f"❌ 扫描IP {ip} 异常: {str(e)}")
                    non_snmp_devices.append({
                        'ip': ip,
                        'status': 'error',
                        'reason': f'扫描异常: {str(e)[:100]}'
                    })
                    offline_count += 1
                
                completed += 1
                progress_pct = 5 + int((completed / total_ips) * 85)
                progress_manager.update_progress(
                    task_id,
                    progress=progress_pct,
                    current_step=f'扫描中 {completed}/{total_ips}: {ip}',
                    processed=completed,
                    added=added_count,
                    skipped=skipped_count,
                    failed=0
                )
        
        # 构建结果
        all_results = []
        for device in found_devices:
            all_results.append({
                'ip': device['ip'],
                'device_name': device.get('device_name', f'设备_{device["ip"]}'),
                'status': 'online',
                'snmp_status': '支持',
                'description': device.get('description', ''),
                'added': device.get('added', False),
                'updated': device.get('updated', False),
                'skipped': device.get('skipped', False),
                'ping_time': device.get('ping_time'),
                'type': 'snmp_device',
                'device_id': device.get('device_id'),
                'device_type': device.get('device_type', 'unknown'),
                'brand': device.get('brand', ''),
                'model': device.get('model', ''),
                'mac_address': device.get('mac_address', '')
            })
        
        for device in non_snmp_devices:
            all_results.append({
                'ip': device['ip'],
                'device_name': device.get('device_name', f'设备_{device["ip"]}'),
                'status': device.get('status', 'unknown'),
                'snmp_status': '不支持',
                'description': device.get('reason', ''),
                'added': False,
                'updated': False,
                'skipped': False,
                'ping_time': device.get('ping_time'),
                'type': 'non_snmp',
                'device_id': None
            })
        
        # 完成
        progress_manager.update_progress(
            task_id,
            status='completed',
            progress=100,
            current_step='🎉 SNMP扫描完成！',
            added=added_count,
            updated=updated_count,
            skipped=skipped_count,
            failed=0,
            end_time=datetime.now().isoformat(),
            results=all_results[:500],
            message=f'扫描 {total_ips} 个IP，发现 {len(found_devices)} 个SNMP设备，添加 {added_count} 个，更新 {updated_count} 个'
        )
        
        print(f"\n{'='*60}")
        print(f"📊 SNMP扫描任务 {task_id} 完成统计:")
        print(f"  - 总IP数: {total_ips}")
        print(f"  - 在线设备: {online_count}")
        print(f"  - 离线设备: {offline_count}")
        print(f"  - SNMP设备: {len(found_devices)}")
        print(f"  - 非SNMP设备: {len(non_snmp_devices)}")
        print(f"  - 已添加: {added_count}")
        print(f"  - 已更新: {updated_count}")
        print(f"  - 已跳过: {skipped_count}")
        print(f"{'='*60}")
        
        # 记录日志
        try:
            log_operation(
                'scan',
                'device',
                None,
                'SNMP扫描',
                f'SNMP扫描完成: 总IP {total_ips}，发现 {len(found_devices)} 个SNMP设备，添加 {added_count} 个，更新 {updated_count} 个',
                user_id
            )
        except:
            pass
        
    except Exception as e:
        db.session.rollback()
        error_msg = str(e)
        print(f"❌ SNMP扫描任务 {task_id} 异常: {error_msg}")
        import traceback
        traceback.print_exc()
        
        progress_manager.update_progress(
            task_id,
            status='failed',
            message=f'SNMP扫描出错: {error_msg}',
            end_time=datetime.now().isoformat()
        )
        
    finally:
        lock.release()
        print(f"🔓 SNMP扫描任务 {task_id} 锁已释放")

# ==================== 设备导出功能 ====================

@device_bp.route('/devices/export')
@login_required
@permission_required('device:view')
def device_export():
    """
    导出设备数据到Excel
    """
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        
        # 获取要导出的设备ID列表
        device_ids = request.args.getlist('ids')
        if device_ids:
            devices = Device.query.filter(Device.id.in_(device_ids)).all()
        else:
            # 如果没有指定ID，导出所有设备
            devices = Device.query.order_by(Device.id).all()
        
        if not devices:
            flash('没有设备数据可导出', 'warning')
            return redirect(url_for('device.device_list'))
        
        # 创建Excel工作簿
        wb = Workbook()
        ws = wb.active
        ws.title = "设备列表"
        
        # 样式定义
        header_font = Font(bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        thin_border = Border(
            left=Side(style='thin'),
            right=Side(style='thin'),
            top=Side(style='thin'),
            bottom=Side(style='thin')
        )
        
        # 表头
        headers = [
            'ID', '设备名称', '管理IP', '设备类型', '品牌', '型号',
            '序列号', '资产编号', 'MAC地址', '厂商', '位置', '机柜',
            '高度(U)', '起始U位', '操作系统', '负责人', '部门',
            '采购日期', '保修到期', '状态', '最后检测', 'Ping时间(ms)',
            'SNMP社区', 'SSH用户名', '描述/备注', '创建时间', '更新时间'
        ]
        
        for col_idx, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_idx, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_alignment
            cell.border = thin_border
            ws.column_dimensions[chr(64 + col_idx) if col_idx <= 26 else f'A{chr(64 + col_idx - 26)}'].width = 15
        
        # 状态颜色映射
        status_color_map = {
            'online': 'success',
            'offline': 'danger',
            'fault': 'danger',
            'warning': 'warning',
            'unknown': 'secondary',
            'active': 'success',
            'inactive': 'secondary',
            'maintenance': 'warning'
        }
        
        # 设备类型中文映射
        type_map = {
            'router': '路由器',
            'switch': '交换机',
            'firewall': '防火墙',
            'server': '服务器',
            'pc': '计算机',
            'ap': '无线AP',
            'unknown': '未知设备'
        }
        
        # 写入数据
        for row_idx, device in enumerate(devices, 2):
            # 获取位置和机柜名称
            location_name = device.location.name if device.location else ''
            cabinet_name = device.cabinet.name if device.cabinet else ''
            
            # ========== 修复1: 使用 date 对象，而不是 dt ==========
            # 格式化日期
            purchase_date_str = device.purchase_date.strftime('%Y-%m-%d') if device.purchase_date else ''
            warranty_expiry_str = device.warranty_expiry.strftime('%Y-%m-%d') if device.warranty_expiry else ''
            
            # 计算保修状态
            warranty_status = ''
            if device.warranty_expiry:
                today = date.today()
                if device.warranty_expiry < today:
                    warranty_status = '已过期'
                elif device.warranty_expiry <= today + timedelta(days=90):
                    warranty_status = '即将过期'
                else:
                    warranty_status = '有效'
            
            # 状态颜色
            status_color = status_color_map.get(device.status, 'secondary')
            device_type_cn = type_map.get(device.device_type, device.device_type or '未知')
            
            row_data = [
                device.id,
                device.name,
                device.management_ip or '',
                device_type_cn,
                device.brand or '',
                device.model or '',
                device.serial_number or '',
                device.asset_number or '',
                device.mac_address or '',
                device.manufacturer or '',
                location_name,
                cabinet_name,
                device.height_u or 1,
                device.position_u or '',
                device.os_version or '',
                device.owner or '',
                device.department or '',
                purchase_date_str,
                warranty_expiry_str,
                f'{device.status}({status_color})',
                (device.last_checked + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S') if device.last_checked else '',
                device.ping_time or '',
                device.snmp_community or '',
                device.ssh_username or '',
                device.description or '',
                (device.created_at + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S') if device.created_at else '',
                (device.updated_at + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S') if device.updated_at else ''
            ]
            
            for col_idx, value in enumerate(row_data, 1):
                cell = ws.cell(row=row_idx, column=col_idx, value=value)
                cell.border = thin_border
                cell.alignment = Alignment(horizontal="left", vertical="center")
        
        # 保存到内存
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        
        # 生成文件名
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'设备列表_导出_{timestamp}.xlsx'
        
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        # ========== 修复2: 使用 current_app 而不是 app ==========
        current_app.logger.error(f"设备导出失败: {str(e)}")
        import traceback
        current_app.logger.error(traceback.format_exc())
        flash(f'导出失败: {str(e)}', 'danger')
        return redirect(url_for('device.device_list'))



@device_bp.route('/add_from_scan', methods=['POST'])
@login_required
@permission_required('device:edit')
def add_device_from_scan():
    """从扫描结果添加单个设备"""
    try:
        data = request.get_json()
        
        ip = data.get('ip')
        name = data.get('name')
        description = data.get('description', '')
        device_type = data.get('device_type', 'unknown')
        
        if not ip or not name:
            return jsonify({
                'success': False,
                'message': 'IP和名称不能为空'
            })
        
        # 检查是否已存在
        existing = Device.query.filter_by(management_ip=ip).first()
        if existing:
            return jsonify({
                'success': False,
                'message': f'IP地址 {ip} 的设备已存在'
            })
        
        # 创建新设备
        new_device = Device(
            name=name,
            management_ip=ip,
            model=description[:200] if description else '',
            device_type=device_type,
            status='online',
            last_checked=datetime.utcnow(),
            last_seen=datetime.utcnow(),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        db.session.add(new_device)
        db.session.commit()
        log_audit('create', 'device', new_device.id, f"从扫描添加设备: {name}", details={'ip': ip, 'device_type': device_type})

        return jsonify({
            'success': True,
            'message': f'设备 {name} 添加成功',
            'device_id': new_device.id
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"添加设备失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'添加失败: {str(e)}'
        })

@device_bp.route('/batch_add_from_scan', methods=['POST'])
@login_required
@permission_required('device:edit')
def batch_add_devices_from_scan():
    print("batch_add_from_scan called, method:", request.method)
    """批量添加扫描发现的设备"""
    current_app.logger.info("batch_add_from_scan 被调用")
    try:
        data = request.get_json()
        devices = data.get('devices', [])
        
        if not devices:
            return jsonify({
                'success': False,
                'message': '没有要添加的设备'
            })
        
        added_count = 0
        errors = []
        
        for device_data in devices:
            try:
                ip = device_data.get('ip')
                name = device_data.get('name')
                
                if not ip or not name:
                    errors.append(f'设备数据不完整: {device_data}')
                    continue
                
                # 检查是否已存在
                existing = Device.query.filter_by(management_ip=ip).first()
                if existing:
                    errors.append(f'设备 {ip} 已存在')
                    continue
                
                # 创建新设备
                new_device = Device(
                    name=name,
                    management_ip=ip,
                    model=device_data.get('description', '')[:200],
                    device_type=device_data.get('device_type', 'unknown'),
                    status='online',
                    last_checked=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                
                db.session.add(new_device)
                added_count += 1
                
            except Exception as e:
                errors.append(f'添加设备 {device_data.get("ip")} 失败: {str(e)}')
        
        db.session.commit()
        log_audit('create', 'device', None, f"批量从扫描添加 {added_count} 个设备", details={'added_count': added_count, 'error_count': len(errors)})

        message = f'成功添加 {added_count} 个设备'
        if errors:
            message += f'，失败 {len(errors)} 个'

        return jsonify({
            'success': True,
            'message': message,
            'added_count': added_count,
            'error_count': len(errors),
            'errors': errors[:10]  # 只返回前10个错误
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"批量添加设备失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'批量添加失败: {str(e)}'
        })
# 在 device.py 中添加以下路由

@device_bp.route('/api/devices/available')
@login_required
@permission_required('device:view')
def get_available_devices():
    """获取可分配到机柜的设备列表（未分配或可重新分配）"""
    try:
        cabinet_id = request.args.get('cabinet_id', type=int)
        
        # 获取未分配机柜的设备
        query = Device.query.filter((Device.cabinet_id.is_(None)) | (Device.cabinet_id == cabinet_id))
        
        # 获取可用设备
        devices = query.order_by(Device.name).all()
        
        result = []
        for device in devices:
            result.append({
                'id': device.id,
                'name': device.name,
                'management_ip': device.management_ip,
                'device_type': device.device_type,
                'model': device.model,
                'height_u': device.height_u or 1,
                'current_cabinet_id': device.cabinet_id,
                'current_position_u': device.position_u
            })
        
        return jsonify({
            'success': True,
            'devices': result
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500

# API路由，用于获取设备信息
@device_bp.route('/api/device/<int:device_id>', methods=['GET'])
@login_required
@permission_required('device:view')
def get_device_api(device_id):
    device = Device.query.get_or_404(device_id)
    return jsonify({
        'success': True,
        'device': {
            'id': device.id,
            'name': device.name,
            'management_ip': device.management_ip,
            'ip_address': device.ip_address,
            'position_u': device.position_u,
            'height_u': device.height_u,
            'device_type': device.device_type,
            'brand': device.brand,
            'model': device.model,
            'status': device.status,
            'mac_address': device.mac_address,
            'description': device.description
        }
    })


@device_bp.route('/<int:device_id>/json')
@login_required
@permission_required('device:view')
def get_device_json(device_id):
    """获取设备JSON数据"""
    device = Device.query.get_or_404(device_id)
    
    return jsonify({
        'id': device.id,
        'name': device.name,
        'management_ip': device.management_ip,
        'ip_address': device.ip_address,
        'device_type': device.device_type,
        'status': device.status,
        'brand': device.brand,
        'model': device.model,
        'location': device.location.name if device.location else None,
        'cabinet': device.cabinet.name if device.cabinet else None,
        'last_checked': device.last_checked.isoformat() if device.last_checked else None,
    })







@device_bp.route('/batch_delete', methods=['POST'])
@login_required
@permission_required('device:edit')
def batch_delete_devices():
    """
    批量删除设备。
    逻辑与单台删除 delete_device 保持一致，逐项清理所有关联数据。
    """
    try:
        data = request.get_json()
        device_ids = data.get('device_ids', [])
        if not device_ids:
            return jsonify({'success': False, 'message': '请选择要删除的设备'}), 400

        deleted_count = 0
        error_list = []

        # 预加载所有待删除的设备
        devices_to_delete = {}
        for device_id in device_ids:
            device = Device.query.get(device_id)
            if device:
                devices_to_delete[device_id] = device
            else:
                error_list.append(f"设备 ID {device_id} 不存在")

        # 如果没有有效设备，直接返回
        if not devices_to_delete:
            return jsonify({
                'success': False,
                'message': '未找到有效的设备进行删除',
                'error_count': len(error_list),
                'errors': error_list
            }), 400

        # 提取所有待删设备的 ID 列表，用于 IN 查询
        valid_device_ids = list(devices_to_delete.keys())

        # === 按照 delete_device 的顺序，批量清理关联数据 ===
        try:
            # 1. 删除设备监控配置
            DeviceMonitorConfig.query.filter(
                DeviceMonitorConfig.device_id.in_(valid_device_ids)
            ).delete(synchronize_session=False)

            # 2. 解除备件关联（设置为 NULL）
            SparePart.query.filter(
                SparePart.installed_device_id.in_(valid_device_ids)
            ).update({'installed_device_id': None}, synchronize_session=False)

            # 3. 删除告警事件
            AlertEvent.query.filter(
                AlertEvent.device_id.in_(valid_device_ids)
            ).delete(synchronize_session=False)

            # 4. 删除各类监控数据
            MonitorData.query.filter(
                MonitorData.device_id.in_(valid_device_ids)
            ).delete(synchronize_session=False)
            
            DeviceMonitorLog.query.filter(
                DeviceMonitorLog.device_id.in_(valid_device_ids)
            ).delete(synchronize_session=False)
            
            InterfaceMonitorData.query.filter(
                InterfaceMonitorData.device_id.in_(valid_device_ids)
            ).delete(synchronize_session=False)

            # 5. 删除库存事务
            InventoryTransaction.query.filter(
                InventoryTransaction.device_id.in_(valid_device_ids)
            ).delete(synchronize_session=False)

            # 6. 删除拓扑连接（关键！覆盖 source 和 target）
            ConnectionPath.query.filter(
                or_(
                    ConnectionPath.source_device_id.in_(valid_device_ids),
                    ConnectionPath.target_device_id.in_(valid_device_ids)
                )
            ).delete(synchronize_session=False)

            # 7. 删除合规/配置相关数据（避免 autoflush 时误将 device_id 设为 NULL）
            ConfigDrift.query.filter(
                ConfigDrift.device_id.in_(valid_device_ids)
            ).delete(synchronize_session=False)

            ConfigBaseline.query.filter(
                ConfigBaseline.device_id.in_(valid_device_ids)
            ).delete(synchronize_session=False)

            ConfigVersion.query.filter(
                ConfigVersion.device_id.in_(valid_device_ids)
            ).delete(synchronize_session=False)

            ComplianceCheckResult.query.filter(
                ComplianceCheckResult.device_id.in_(valid_device_ids)
            ).delete(synchronize_session=False)

            # === 关键修复：替换为循环调用 session.delete() ===
            # 8. 逐个删除设备对象，以触发 SQLAlchemy 的级联删除（特别是 interfaces）
            for device in devices_to_delete.values():
                db.session.delete(device)

            # 提交所有更改
            db.session.commit()
            deleted_count = len(valid_device_ids)
            log_audit('delete', 'device', None, f"批量删除 {deleted_count} 个设备", details={'deleted_count': deleted_count, 'device_ids': valid_device_ids})

        except Exception as cleanup_error:
            db.session.rollback()
            current_app.logger.error(f"批量删除清理关联数据失败: {traceback.format_exc()}")
            return jsonify({
                'success': False,
                'message': f'批量删除失败：清理关联数据时出错 - {str(cleanup_error)}'
            }), 500

        # 记录操作日志
        log_operation('batch_delete', 'device', None, None, f'批量删除设备，成功 {deleted_count} 个')

        # 构建成功响应
        message = f'成功删除 {deleted_count} 个设备'
        if error_list:
            message += f'，{len(error_list)} 个设备未找到。'

        return jsonify({
            'success': True,
            'deleted_count': deleted_count,
            'error_count': len(error_list),
            'errors': error_list[:10],
            'message': message
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"批量删除设备发生严重错误: {traceback.format_exc()}")
        return jsonify({
            'success': False,
            'message': f'批量删除失败: {str(e)}'
        }), 500


@device_bp.route('/snmp_all', methods=['POST'])
@login_required
@permission_required('device:edit')
def snmp_all_devices():
    """SNMP检测所有在线设备"""
    try:
        snmp_community = request.form.get('snmp_community', 'public')
        snmp_version = request.form.get('snmp_version', '2c')
        
        # 获取所有在线设备
        online_devices = Device.query.filter(
            Device.status == 'online',
            Device.management_ip.isnot(None)
        ).all()
        
        success_count = 0
        failure_count = 0
        results = []
        
        for device in online_devices:
            try:
                snmp_success, sysinfo = snmp_get_device_info(
                    device.management_ip,
                    snmp_community,
                    snmp_version
                )
                
                if snmp_success:
                    # 更新设备信息
                    if sysinfo.get('sys_name'):
                        device.name = sysinfo['sys_name']
                    if sysinfo.get('sys_descr'):
                        device.description = sysinfo['sys_descr'][:500]
                    
                    success_count += 1
                    results.append({
                        'device_id': device.id,
                        'device_name': device.name,
                        'success': True
                    })
                else:
                    failure_count += 1
                    results.append({
                        'device_id': device.id,
                        'device_name': device.name,
                        'success': False,
                        'error': 'SNMP无响应'
                    })
                    
            except Exception as e:
                failure_count += 1
                results.append({
                    'device_id': device.id,
                    'device_name': device.name,
                    'success': False,
                    'error': str(e)[:100]
                })
        
        db.session.commit()
        log_audit('execute', 'device', None, f"批量SNMP检测: 成功{success_count}个, 失败{failure_count}个", details={'success_count': success_count, 'failure_count': failure_count})

        log_operation('snmp_all', 'device', None, None,
                     f'批量SNMP检测: 成功{success_count}个，失败{failure_count}个')

        return jsonify({
            'success': True,
            'success_count': success_count,
            'failure_count': failure_count,
            'total': len(online_devices),
            'results': results[:20],  # 只返回前20个结果
            'message': f'SNMP检测完成：成功{success_count}个，失败{failure_count}个'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'批量SNMP检测失败: {str(e)}'
        }), 500


# 在 device.py 文件中添加以下路由

@device_bp.route('/batch_import', methods=['POST'])
@login_required
@permission_required('device:edit')
def batch_import():
    """处理IP段批量导入请求"""
    try:
        # 从请求中获取参数
        ip_range_str = request.form.get('ip_range')
        device_type = request.form.get('device_type', 'unknown')
        cabinet_id = request.form.get('cabinet_id')
        manufacturer = request.form.get('manufacturer')
        auto_naming = request.form.get('auto_naming') == 'on'
        skip_existing = request.form.get('skip_existing') == 'on'
        use_ping = request.form.get('use_ping') != 'off'  # 如果勾选了Ping检测
        ping_timeout = int(request.form.get('ping_timeout', 2))

        if not ip_range_str:
            return jsonify({'success': False, 'message': 'IP段不能为空'}), 400

        # 调用 utils.py 中的可靠导入函数
        # 注意：您需要将 ip_range_import 函数从 utils.py 中提取出来，
        # 并修改其签名以接收上述参数，而不是从全局 request 对象中读取。
        # 这里只是一个示意调用。
        from utils import ip_range_import
        results = ip_range_import(
            ip_range_str=ip_range_str,
            device_type=device_type,
            cabinet_id=cabinet_id,
            manufacturer=manufacturer,
            auto_naming=auto_naming,
            skip_existing=skip_existing,
            use_ping=use_ping,
            ping_timeout=ping_timeout
        )

        db.session.commit()
        log_audit('create', 'device', None, f"IP段批量导入设备", details={'ip_range': ip_range_str, 'device_type': device_type})
        return jsonify({'success': True, 'results': results})

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"批量导入失败: {traceback.format_exc()}")
        return jsonify({'success': False, 'message': f'导入失败: {str(e)}'}), 500


@device_bp.route('/ip_range_import', methods=['POST'])
@login_required
@permission_required('device:edit')
def ip_range_import():
    """
    IP段批量导入 - 异步模式：立即返回task_id，后台执行
    使用多种检测方法（Ping + TCP端口 + ARP缓存），至少两种确认才添加
    """
    import time
    import threading
    
    print("=" * 60)
    print("📥 收到批量导入请求（异步模式）")
    print("=" * 60)
    
    # 获取锁，防止并发执行
    lock = CrossPlatformLock('ip_range_import')
    if not lock.acquire(timeout=5):
        return jsonify({
            'success': False,
            'message': '另一个导入任务正在执行中，请稍后再试'
        }), 429
    
    # 创建进度任务
    task_id = progress_manager.create_task('import')
    print(f"✅ 创建任务: {task_id}")
    
    # 保存请求参数
    form_data = {
        'ip_range': request.form.get('ip_range', '').strip(),
        'device_type': request.form.get('device_type', 'unknown'),
        'cabinet_id': request.form.get('cabinet_id'),
        'manufacturer': request.form.get('manufacturer', '').strip(),
        'skip_existing': request.form.get('skip_existing', 'true') == 'true',
        'use_ping': request.form.get('use_ping', 'true') == 'true',
        'auto_naming': request.form.get('auto_naming', 'true') == 'true',
        'concurrent': int(request.form.get('concurrent', 20)) if request.form.get('concurrent') else 20,
        'ping_timeout': int(request.form.get('ping_timeout', 2)) if request.form.get('ping_timeout') else 2,
        'user_id': current_user.id if hasattr(current_user, 'id') else None,
        'username': current_user.username if hasattr(current_user, 'username') else '系统'
    }
    
    # 释放锁
    lock.release()
    
    # 获取当前应用
    from flask import current_app
    app = current_app._get_current_object()
    
    # 启动后台线程，传递应用
    thread = threading.Thread(
        target=_run_import_task_with_app,
        args=(app, task_id, form_data)
    )
    thread.daemon = True
    thread.start()
    
    print(f"🚀 后台任务已启动: {task_id}")
    log_audit('execute', 'device', None, f"提交IP段导入任务: {form_data['ip_range']}", details={'ip_range': form_data['ip_range'], 'device_type': form_data['device_type']})

    return jsonify({
        'success': True,
        'message': '导入任务已提交，请查看进度',
        'task_id': task_id,
        'status': 'pending'
    })


def _run_import_task_with_app(app, task_id, form_data):
    """带应用上下文的后台任务包装器"""
    with app.app_context():
        _run_import_task_impl(task_id, form_data)


def _run_import_task_impl(task_id, form_data):
    """
    实际执行导入任务（在应用上下文中运行）
    """
    import time
    import socket
    import subprocess
    import platform
    import re
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    print(f"📋 后台任务 {task_id} 开始执行")
    
    # 获取锁
    lock = CrossPlatformLock('ip_range_import')
    if not lock.acquire(timeout=30):
        progress_manager.update_progress(
            task_id,
            status='failed',
            message='无法获取锁，另一个任务正在执行',
            end_time=datetime.now().isoformat()
        )
        return
    
    try:
        # ========== 提取参数 ==========
        ip_range = form_data.get('ip_range')
        device_type = form_data.get('device_type', 'unknown')
        cabinet_id = form_data.get('cabinet_id')
        manufacturer = form_data.get('manufacturer', '').strip()
        skip_existing = form_data.get('skip_existing', True)
        use_ping = form_data.get('use_ping', True)
        auto_naming = form_data.get('auto_naming', True)
        concurrent = form_data.get('concurrent', 20)
        ping_timeout = form_data.get('ping_timeout', 2)
        user_id = form_data.get('user_id')
        username = form_data.get('username', '系统')
        
        print(f"  - IP段: {ip_range}")
        print(f"  - 设备类型: {device_type}")
        print(f"  - 并发数: {concurrent}")
        print(f"  - Ping超时: {ping_timeout}秒")
        print(f"  - 自动命名: {auto_naming}")
        print(f"  - 用户: {username}")
        
        # ========== 验证IP段 ==========
        if not ip_range:
            progress_manager.update_progress(
                task_id, 
                status='failed', 
                message='请输入IP段',
                end_time=datetime.now().isoformat()
            )
            return
        
        # ========== 解析IP段 ==========
        try:
            ip_list = parse_ip_range(ip_range)
            if not ip_list:
                progress_manager.update_progress(
                    task_id, 
                    status='failed', 
                    message='无法解析IP段',
                    end_time=datetime.now().isoformat()
                )
                return
            print(f"📡 解析到 {len(ip_list)} 个IP地址")
        except Exception as e:
            progress_manager.update_progress(
                task_id, 
                status='failed', 
                message=f'IP段解析错误: {str(e)}',
                end_time=datetime.now().isoformat()
            )
            return
        
        total_ips = len(ip_list)
        progress_manager.update_progress(
            task_id,
            status='running',
            total=total_ips,
            current_step=f'开始检测 {total_ips} 个IP地址...',
            progress=5,
            processed=0,
            added=0,
            skipped=0,
            failed=0
        )
        
        # ========== 检测设备在线状态 ==========
        detection_results = {}
        online_ips = []
        
        if use_ping:
            progress_manager.update_progress(
                task_id,
                current_step=f'正在严格检测 {total_ips} 个IP地址的在线状态...',
                progress=10
            )
            
            print(f"🔍 开始严格检测 {total_ips} 个IP地址...")
            
            def detect_single_ip(ip):
                """严格检测单个IP - 使用多种方法验证"""
                detection_methods = {}
                
                # 方法1: 系统Ping（最可靠）
                try:
                    param = '-n' if platform.system().lower() == 'windows' else '-c'
                    timeout_param = '-w' if platform.system().lower() == 'windows' else '-W'
                    timeout_val = str(int(ping_timeout * 1000)) if platform.system().lower() == 'windows' else str(int(ping_timeout))
                    
                    cmd = ['ping', param, '1', timeout_param, timeout_val, ip]
                    result = subprocess.run(cmd, capture_output=True, timeout=ping_timeout+1, text=True)
                    
                    if result.returncode == 0:
                        match = re.search(r'(?:时间|time)[=<](\d+\.?\d*)', result.stdout, re.IGNORECASE)
                        response_time = float(match.group(1)) if match else ping_timeout * 1000
                        detection_methods['ping'] = {
                            'success': True,
                            'response_time': response_time
                        }
                    else:
                        detection_methods['ping'] = {'success': False, 'response_time': 0}
                except Exception as e:
                    detection_methods['ping'] = {'success': False, 'response_time': 0, 'error': str(e)}
                
                # 方法2: TCP端口检测
                common_ports = [80, 443, 22, 23, 8080, 8443, 3389, 3306, 1433, 5432, 6379, 27017]
                tcp_success = False
                tcp_response = 0
                tcp_port = None
                
                for port in common_ports:
                    try:
                        start = time.time()
                        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        sock.settimeout(ping_timeout)
                        result = sock.connect_ex((ip, port))
                        sock.close()
                        
                        if result == 0:
                            tcp_success = True
                            tcp_response = (time.time() - start) * 1000
                            tcp_port = port
                            break
                    except:
                        pass
                
                detection_methods['tcp'] = {
                    'success': tcp_success,
                    'response_time': tcp_response,
                    'port': tcp_port
                }
                
                # 方法3: ARP缓存检查
                try:
                    if platform.system().lower() == 'windows':
                        cmd = ['arp', '-a', ip]
                    else:
                        cmd = ['arp', '-n', ip]
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
                    
                    if ip in result.stdout:
                        mac_pattern = r'([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}'
                        macs = re.findall(mac_pattern, result.stdout)
                        if macs:
                            for mac in macs:
                                if mac.replace('-', '').replace(':', '') != '000000000000':
                                    detection_methods['arp'] = {'success': True, 'mac': mac}
                                    break
                            else:
                                detection_methods['arp'] = {'success': False}
                        else:
                            detection_methods['arp'] = {'success': False}
                    else:
                        detection_methods['arp'] = {'success': False}
                except:
                    detection_methods['arp'] = {'success': False}
                
                # 判断：至少2种方法确认才认为在线
                success_count = 0
                best_response = 0
                methods_used = []
                
                if detection_methods.get('ping', {}).get('success', False):
                    success_count += 1
                    best_response = detection_methods['ping'].get('response_time', ping_timeout * 1000)
                    methods_used.append('ping')
                
                if detection_methods.get('tcp', {}).get('success', False):
                    success_count += 1
                    tcp_resp = detection_methods['tcp'].get('response_time', 0)
                    if tcp_resp > 0 and (best_response == 0 or tcp_resp < best_response):
                        best_response = tcp_resp
                    port = detection_methods['tcp'].get('port', 'unknown')
                    methods_used.append(f'tcp_{port}')
                
                if detection_methods.get('arp', {}).get('success', False):
                    success_count += 1
                    methods_used.append('arp')
                
                is_online = success_count >= 2
                
                if best_response == 0 and is_online:
                    best_response = ping_timeout * 1000
                
                # 提取ARP MAC（用于后续设备去重）
                arp_mac = ''
                arp_data = detection_methods.get('arp', {})
                if arp_data.get('success'):
                    arp_mac = arp_data.get('mac', '')

                return {
                    'ip': ip,
                    'online': is_online,
                    'response_time': best_response,
                    'detection_method': '+'.join(methods_used) if methods_used else 'all_failed',
                    'success_count': success_count,
                    'methods': methods_used,
                    'arp_mac': arp_mac           # 供后续设备去重使用
                }
            
            # 并发执行检测
            completed = 0
            with ThreadPoolExecutor(max_workers=concurrent) as executor:
                future_to_ip = {executor.submit(detect_single_ip, ip): ip for ip in ip_list}
                
                for future in as_completed(future_to_ip):
                    ip = future_to_ip[future]
                    try:
                        result = future.result(timeout=ping_timeout+3)
                        detection_results[ip] = result
                        
                        if result.get('online', False) and result.get('response_time', 0) > 0:
                            online_ips.append(ip)
                    except Exception as e:
                        detection_results[ip] = {
                            'ip': ip,
                            'online': False,
                            'response_time': 0,
                            'detection_method': 'error',
                            'reason': str(e)
                        }
                    
                    completed += 1
                    if completed % 10 == 0 or completed == total_ips:
                        progress_pct = 10 + int((completed / total_ips) * 35)
                        progress_manager.update_progress(
                            task_id,
                            progress=progress_pct,
                            current_step=f'检测中 {completed}/{total_ips}: {ip}'
                        )
            
            print(f"✅ 检测完成: 发现 {len(online_ips)} 个在线设备")
            
        else:
            # 不使用检测，不添加任何设备
            progress_manager.update_progress(
                task_id,
                status='completed',
                progress=100,
                current_step='未启用检测，没有新设备添加',
                message='请启用Ping检测来发现新设备',
                end_time=datetime.now().isoformat()
            )
            return
        
        online_count = len(online_ips)
        offline_count = total_ips - online_count
        print(f"  >>>>> DETECTION 结果: 在线={online_count}, 离线={offline_count}, 在线IP列表={online_ips}")

        progress_manager.update_progress(
            task_id,
            current_step=f'发现 {online_count} 个确认在线的设备，开始导入...',
            progress=50
        )
        
        # ========== 只添加确认在线的设备 ==========
        added_count = 0
        skipped_existing = 0
        error_count = 0
        processed = 0
        total_to_process = len(online_ips)
        results = []
        
        print(f"📥 开始导入 {total_to_process} 个在线设备...")
        
        for ip in online_ips:
            processed += 1
            progress_pct = 50 + int((processed / total_to_process) * 45) if total_to_process > 0 else 50
            
            progress_manager.update_progress(
                task_id,
                progress=progress_pct,
                current_step=f'正在导入设备 {processed}/{total_to_process}: {ip}',
                processed=processed
            )
            
            from services.device_service import find_device

            result = detection_results.get(ip, {})
            response_time = result.get('response_time', 0)
            detection_method = result.get('detection_method', 'unknown')

            # 生成设备名称
            if auto_naming:
                dev_name = f"设备_{ip}"
            else:
                dev_name = f"Device_{ip}"

            try:
                # 使用统一设备服务 - 按IP/MAC/名称查重，存在则跳过/更新
                device, action = find_device(
                    ip=ip,
                    mac=result.get('arp_mac', ''),
                    name=dev_name,
                    create_if_not_found=True,
                    device_type=device_type,
                    manufacturer=manufacturer if manufacturer else None,
                    status='online',
                    cabinet_id=int(cabinet_id) if cabinet_id and cabinet_id.isdigit() else None,
                    ping_time=response_time,
                    description=f"通过批量导入添加，检测方式: {detection_method}，响应时间: {response_time:.2f}ms",
                )

                db.session.commit()

                if action == 'created':
                    added_count += 1
                    results.append({
                        'ip': ip,
                        'status': 'added',
                        'reason': f'添加成功 (响应: {response_time:.2f}ms)',
                        'device_name': device.name,
                        'device_id': device.id
                    })
                    print(f"  ✅ 添加新设备: {device.name} ({ip})")

                    # 记录操作日志（设备已提交，日志失败不影响设备数据）
                    try:
                        log_operation(
                            'import',
                            'device',
                            device.id,
                            device.name,
                            f'通过IP段批量导入添加，IP: {ip}，检测方式: {detection_method}',
                            user=user_id
                        )
                    except:
                        pass
                else:
                    skipped_existing += 1
                    results.append({
                        'ip': ip,
                        'status': 'skipped',
                        'reason': f'设备已存在 ({device.name})',
                        'device_name': device.name
                    })
                    print(f"  ⏭ 跳过已存在: {ip} → 复用已有设备 {device.name} ({action})")

            except Exception as e:
                db.session.rollback()
                error_count += 1
                results.append({
                    'ip': ip,
                    'status': 'failed',
                    'reason': f'导入异常: {str(e)[:80]}'
                })
                print(f"  ❌ 导入失败: {ip} - {str(e)[:80]}")
            
            # 每5个设备更新一次进度详情
            if processed % 5 == 0:
                progress_manager.update_progress(
                    task_id,
                    added=added_count,
                    skipped=skipped_existing,
                    failed=error_count
                )
        
        # ========== 完成 ==========
        progress_manager.update_progress(
            task_id,
            status='completed',
            progress=100,
            current_step='🎉 导入完成！',
            added=added_count,
            skipped=skipped_existing,
            failed=error_count,
            end_time=datetime.now().isoformat(),
            results=results[:200],
            message=f'扫描 {total_ips} 个IP，发现 {online_count} 个在线设备，成功添加 {added_count} 个'
        )
        
        print(f"\n{'='*60}")
        print(f"📊 后台任务 {task_id} 完成统计:")
        print(f"  - 总IP数: {total_ips}")
        print(f"  - 在线设备: {online_count}")
        print(f"  - 成功添加: {added_count}")
        print(f"  - 已存在跳过: {skipped_existing}")
        print(f"  - 离线未添加: {offline_count}")
        print(f"  - 错误数量: {error_count}")
        print(f"{'='*60}")
        
        # 记录总体操作日志
        try:
            log_operation(
                'import', 
                'device', 
                None, 
                '批量导入',
                f'IP段批量导入完成: 总IP {total_ips}，在线 {online_count}，成功添加 {added_count}，跳过 {skipped_existing}，失败 {error_count}',
                user=user_id
            )
        except:
            pass
        
    except Exception as e:
        db.session.rollback()
        error_msg = str(e)
        print(f"❌ 后台任务 {task_id} 异常: {error_msg}")
        import traceback
        traceback.print_exc()
        
        progress_manager.update_progress(
            task_id,
            status='failed',
            message=f'批量导入出错: {error_msg}',
            end_time=datetime.now().isoformat()
        )
        
    finally:
        lock.release()
        print(f"🔓 后台任务 {task_id} 锁已释放")


def _run_import_task(task_id, form_data):
    """
    后台执行导入任务 - 带应用上下文
    """
    import time
    import socket
    import subprocess
    import platform
    import re
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    # ★★★ 关键修复：获取应用上下文 ★★★
    from flask import current_app
    app = current_app._get_current_object()
    
    with app.app_context():
        # 获取锁
        lock = CrossPlatformLock('ip_range_import')
        if not lock.acquire(timeout=30):
            progress_manager.update_progress(
                task_id,
                status='failed',
                message='无法获取锁，另一个任务正在执行',
                end_time=datetime.now().isoformat()
            )
            return
        
        try:
            # 提取参数
            ip_range = form_data.get('ip_range')
            device_type = form_data.get('device_type', 'unknown')
            cabinet_id = form_data.get('cabinet_id')
            manufacturer = form_data.get('manufacturer', '').strip()
            skip_existing = form_data.get('skip_existing', True)
            use_ping = form_data.get('use_ping', True)
            auto_naming = form_data.get('auto_naming', True)
            concurrent = form_data.get('concurrent', 20)
            ping_timeout = form_data.get('ping_timeout', 2)
            
            print(f"📋 后台任务 {task_id} 开始执行")
            print(f"  - IP段: {ip_range}")
            print(f"  - 设备类型: {device_type}")
            print(f"  - 并发数: {concurrent}")
            print(f"  - Ping超时: {ping_timeout}秒")
            
            # 验证IP段
            if not ip_range:
                progress_manager.update_progress(task_id, status='failed', message='请输入IP段')
                return
            
            # 解析IP段
            try:
                ip_list = parse_ip_range(ip_range)
                if not ip_list:
                    progress_manager.update_progress(task_id, status='failed', message='无法解析IP段')
                    return
                print(f"📡 解析到 {len(ip_list)} 个IP地址")
            except Exception as e:
                progress_manager.update_progress(task_id, status='failed', message=f'IP段解析错误: {str(e)}')
                return
            
            total_ips = len(ip_list)
            progress_manager.update_progress(
                task_id,
                status='running',
                total=total_ips,
                current_step=f'开始检测 {total_ips} 个IP地址...',
                progress=5
            )
            
            # 检测设备在线状态
            detection_results = {}
            online_ips = []
            
            if use_ping:
                progress_manager.update_progress(
                    task_id,
                    current_step=f'正在严格检测 {total_ips} 个IP地址的在线状态...',
                    progress=10
                )
                
                print(f"🔍 开始严格检测 {total_ips} 个IP地址...")
                
                def detect_single_ip(ip):
                    """严格检测单个IP"""
                    detection_methods = {}
                    
                    # 方法1: 系统Ping
                    try:
                        param = '-n' if platform.system().lower() == 'windows' else '-c'
                        timeout_param = '-w' if platform.system().lower() == 'windows' else '-W'
                        timeout_val = str(int(ping_timeout * 1000)) if platform.system().lower() == 'windows' else str(int(ping_timeout))
                        
                        cmd = ['ping', param, '1', timeout_param, timeout_val, ip]
                        result = subprocess.run(cmd, capture_output=True, timeout=ping_timeout+1, text=True)
                        
                        if result.returncode == 0:
                            match = re.search(r'(?:时间|time)[=<](\d+\.?\d*)', result.stdout, re.IGNORECASE)
                            response_time = float(match.group(1)) if match else ping_timeout * 1000
                            detection_methods['ping'] = {'success': True, 'response_time': response_time}
                        else:
                            detection_methods['ping'] = {'success': False, 'response_time': 0}
                    except:
                        detection_methods['ping'] = {'success': False, 'response_time': 0}
                    
                    # 方法2: TCP端口检测
                    common_ports = [80, 443, 22, 23, 8080, 8443, 3389, 3306, 1433, 5432, 6379, 27017]
                    tcp_success = False
                    tcp_response = 0
                    tcp_port = None
                    
                    for port in common_ports:
                        try:
                            start = time.time()
                            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                            sock.settimeout(ping_timeout)
                            result = sock.connect_ex((ip, port))
                            sock.close()
                            
                            if result == 0:
                                tcp_success = True
                                tcp_response = (time.time() - start) * 1000
                                tcp_port = port
                                break
                        except:
                            pass
                    
                    detection_methods['tcp'] = {
                        'success': tcp_success,
                        'response_time': tcp_response,
                        'port': tcp_port
                    }
                    
                    # 方法3: ARP缓存检查
                    try:
                        if platform.system().lower() == 'windows':
                            cmd = ['arp', '-a', ip]
                        else:
                            cmd = ['arp', '-n', ip]
                        result = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
                        
                        if ip in result.stdout:
                            mac_pattern = r'([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}'
                            macs = re.findall(mac_pattern, result.stdout)
                            if macs:
                                for mac in macs:
                                    if mac.replace('-', '').replace(':', '') != '000000000000':
                                        detection_methods['arp'] = {'success': True, 'mac': mac}
                                        break
                                else:
                                    detection_methods['arp'] = {'success': False}
                            else:
                                detection_methods['arp'] = {'success': False}
                        else:
                            detection_methods['arp'] = {'success': False}
                    except:
                        detection_methods['arp'] = {'success': False}
                    
                    # 判断：至少2种方法确认
                    success_count = 0
                    best_response = 0
                    methods_used = []
                    
                    if detection_methods.get('ping', {}).get('success', False):
                        success_count += 1
                        best_response = detection_methods['ping'].get('response_time', ping_timeout * 1000)
                        methods_used.append('ping')
                    
                    if detection_methods.get('tcp', {}).get('success', False):
                        success_count += 1
                        tcp_resp = detection_methods['tcp'].get('response_time', 0)
                        if tcp_resp > 0 and (best_response == 0 or tcp_resp < best_response):
                            best_response = tcp_resp
                        methods_used.append(f"tcp_{detection_methods['tcp'].get('port', 'unknown')}")
                    
                    if detection_methods.get('arp', {}).get('success', False):
                        success_count += 1
                        methods_used.append('arp')
                    
                    is_online = success_count >= 2
                    
                    if best_response == 0 and is_online:
                        best_response = ping_timeout * 1000
                    
                    return {
                        'ip': ip,
                        'online': is_online,
                        'response_time': best_response,
                        'detection_method': '+'.join(methods_used) if methods_used else 'all_failed',
                        'success_count': success_count,
                        'methods': methods_used
                    }
                
                completed = 0
                with ThreadPoolExecutor(max_workers=concurrent) as executor:
                    future_to_ip = {executor.submit(detect_single_ip, ip): ip for ip in ip_list}
                    
                    for future in as_completed(future_to_ip):
                        ip = future_to_ip[future]
                        try:
                            result = future.result(timeout=ping_timeout+3)
                            detection_results[ip] = result
                            
                            if result.get('online', False) and result.get('response_time', 0) > 0:
                                online_ips.append(ip)
                        except Exception as e:
                            detection_results[ip] = {
                                'ip': ip,
                                'online': False,
                                'response_time': 0,
                                'detection_method': 'error',
                                'reason': str(e)
                            }
                        
                        completed += 1
                        if completed % 10 == 0 or completed == total_ips:
                            progress_pct = 10 + int((completed / total_ips) * 35)
                            progress_manager.update_progress(
                                task_id,
                                progress=progress_pct,
                                current_step=f'检测中 {completed}/{total_ips}: {ip}'
                            )
                
                print(f"✅ 检测完成: 发现 {len(online_ips)} 个在线设备")
            else:
                progress_manager.update_progress(
                    task_id,
                    status='completed',
                    progress=100,
                    current_step='未启用检测，没有新设备添加'
                )
                return
            
            online_count = len(online_ips)
            offline_count = total_ips - online_count
            
            progress_manager.update_progress(
                task_id,
                current_step=f'发现 {online_count} 个确认在线的设备，开始导入...',
                progress=50
            )
            
            # 导入设备
            added_count = 0
            skipped_existing = 0
            error_count = 0
            processed = 0
            total_to_process = len(online_ips)
            results = []
            
            print(f"📥 开始导入 {total_to_process} 个在线设备...")
            
            for ip in online_ips:
                processed += 1
                progress_pct = 50 + int((processed / total_to_process) * 45) if total_to_process > 0 else 50
                
                progress_manager.update_progress(
                    task_id,
                    progress=progress_pct,
                    current_step=f'正在导入设备 {processed}/{total_to_process}: {ip}',
                    processed=processed
                )
                
                result = detection_results.get(ip, {})
                response_time = result.get('response_time', 0)
                detection_method = result.get('detection_method', 'unknown')
                
                # 检查IP是否已存在
                existing_ip = Device.query.filter_by(management_ip=ip).first()
                if existing_ip:
                    skipped_existing += 1
                    results.append({
                        'ip': ip,
                        'status': 'skipped',
                        'reason': 'IP已存在',
                        'device_name': existing_ip.name
                    })
                    continue
                
                # 生成唯一设备名称
                if auto_naming:
                    base_name = f"设备_{ip}"
                else:
                    base_name = f"Device_{ip}"
                
                final_name = base_name
                counter = 1
                existing = Device.query.filter_by(name=final_name).first()
                while existing:
                    final_name = f"{base_name}_{counter}"
                    counter += 1
                    existing = Device.query.filter_by(name=final_name).first()
                
                try:
                    new_device = Device(
                        name=final_name,
                        management_ip=ip,
                        device_type=device_type,
                        manufacturer=manufacturer if manufacturer else None,
                        status='online',
                        cabinet_id=int(cabinet_id) if cabinet_id and cabinet_id.isdigit() else None,
                        last_checked=datetime.utcnow(),
                        ping_time=response_time,
                        description=f"通过批量导入添加，检测方式: {detection_method}，响应时间: {response_time:.2f}ms",
                        model='未知型号' if device_type == 'unknown' else f'{device_type}_设备',
                        height_u=1,
                        updated_at=datetime.utcnow(),
                        created_at=datetime.utcnow()
                    )
                    
                    db.session.add(new_device)
                    db.session.commit()
                    
                    added_count += 1
                    results.append({
                        'ip': ip,
                        'status': 'added',
                        'reason': f'添加成功 (响应: {response_time:.2f}ms)',
                        'device_name': final_name,
                        'device_id': new_device.id
                    })
                    print(f"  ✅ 添加设备成功: {final_name} ({ip})")
                    
                except IntegrityError as e:
                    db.session.rollback()
                    error_msg = str(e)
                    if 'management_ip' in error_msg:
                        skipped_existing += 1
                        results.append({
                            'ip': ip,
                            'status': 'skipped',
                            'reason': 'IP已被占用'
                        })
                    else:
                        error_count += 1
                        results.append({
                            'ip': ip,
                            'status': 'failed',
                            'reason': f'数据库错误: {error_msg[:50]}'
                        })
                except Exception as e:
                    db.session.rollback()
                    error_count += 1
                    results.append({
                        'ip': ip,
                        'status': 'failed',
                        'reason': f'异常: {str(e)[:50]}'
                    })
                
                if processed % 5 == 0:
                    progress_manager.update_progress(
                        task_id,
                        added=added_count,
                        skipped=skipped_existing,
                        failed=error_count
                    )
            
            # 完成
            progress_manager.update_progress(
                task_id,
                status='completed',
                progress=100,
                current_step='🎉 导入完成！',
                added=added_count,
                skipped=skipped_existing,
                failed=error_count,
                end_time=datetime.now().isoformat(),
                results=results[:200],
                message=f'扫描 {total_ips} 个IP，发现 {online_count} 个在线设备，成功添加 {added_count} 个'
            )
            
            print(f"\n{'='*60}")
            print(f"📊 后台任务 {task_id} 完成:")
            print(f"  - 总IP数: {total_ips}")
            print(f"  - 在线设备: {online_count}")
            print(f"  - 成功添加: {added_count}")
            print(f"  - 已存在跳过: {skipped_existing}")
            print(f"  - 离线未添加: {offline_count}")
            print(f"  - 错误数量: {error_count}")
            print(f"{'='*60}")
            
        except Exception as e:
            db.session.rollback()
            error_msg = str(e)
            print(f"❌ 后台任务 {task_id} 异常: {error_msg}")
            import traceback
            traceback.print_exc()
            
            progress_manager.update_progress(
                task_id,
                status='failed',
                message=f'批量导入出错: {error_msg}',
                end_time=datetime.now().isoformat()
            )
            
        finally:
            lock.release()
            print(f"🔓 后台任务 {task_id} 锁已释放")

def batch_detect_devices(ip_list, timeout=2, max_retries=2, max_workers=20):
    """批量检测设备在线状态 - 改进版，检测更多设备"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import time
    import socket
    import subprocess
    import platform
    
    results = {}
    
    def detect_single_ip(ip):
        """检测单个IP的在线状态 - 使用多种方法"""
        
        # 方法1: TCP端口扫描（快速）
        common_ports = [80, 443, 22, 23, 8080, 8443, 3389, 3306, 1433, 5432]
        
        for port in common_ports:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(timeout)
                result = sock.connect_ex((ip, port))
                sock.close()
                if result == 0:
                    return {
                        'ip': ip,
                        'online': True,
                        'response_time': timeout * 1000,
                        'detection_method': f'tcp_{port}',
                        'port': port
                    }
            except:
                pass
        
        # 方法2: 系统Ping（更可靠）
        try:
            param = '-n' if platform.system().lower() == 'windows' else '-c'
            timeout_param = '-w' if platform.system().lower() == 'windows' else '-W'
            timeout_val = '1000' if platform.system().lower() == 'windows' else str(int(timeout))
            
            cmd = ['ping', param, '1', timeout_param, timeout_val, ip]
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                timeout=timeout + 1,
                text=True
            )
            
            if result.returncode == 0:
                # 解析响应时间
                import re
                match = re.search(r'(?:时间|time)[=<](\d+\.?\d*)', result.stdout, re.IGNORECASE)
                response_time = float(match.group(1)) if match else timeout * 1000
                return {
                    'ip': ip,
                    'online': True,
                    'response_time': response_time,
                    'detection_method': 'system_ping'
                }
        except:
            pass
        
        # 方法3: ARP缓存检查（局域网内更准确）
        try:
            if platform.system().lower() == 'windows':
                cmd = ['arp', '-a', ip]
            else:
                cmd = ['arp', '-n', ip]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
            if ip in result.stdout and '00-00-00-00-00-00' not in result.stdout:
                return {
                    'ip': ip,
                    'online': True,
                    'response_time': 1.0,
                    'detection_method': 'arp_cache'
                }
        except:
            pass
        
        return {
            'ip': ip,
            'online': False,
            'response_time': 0,
            'detection_method': 'all_failed',
            'reason': '所有检测方法均失败'
        }
    
    # 使用线程池并发执行
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_ip = {executor.submit(detect_single_ip, ip): ip for ip in ip_list}
        
        for future in as_completed(future_to_ip):
            ip = future_to_ip[future]
            try:
                result = future.result(timeout=timeout + 2)
                results[ip] = result
            except Exception as e:
                results[ip] = {
                    'ip': ip,
                    'online': False,
                    'response_time': 0,
                    'detection_method': 'error',
                    'reason': f'检测过程出错: {str(e)}'
                }
    
    return results



# ========== 下载模板路由 ==========
@device_bp.route('/download_template')
@login_required
@permission_required('device:view')
def download_device_template():
    """
    下载设备导入模板
    使用 utils/device_import.py 中的 generate_import_template()
    """
    try:
        # 调用工具函数生成模板
        template_path = generate_import_template()
        
        return send_file(
            template_path,
            as_attachment=True,
            download_name='设备导入模板.xlsx',
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    except Exception as e:
        current_app.logger.error(f"下载模板失败: {str(e)}")
        flash('下载模板失败，请重试', 'danger')
        return redirect(url_for('device.device_list'))


# ========== 导入设备路由 ==========
@device_bp.route('/import', methods=['POST'])
@login_required
@permission_required('device:edit')
def device_import():
    """
    导入设备
    使用 utils/device_import.py 中的 import_devices_from_file()
    """
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'message': '请选择文件'})
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'message': '请选择文件'})
        
        # 检查文件扩展名
        allowed_extensions = {'.xlsx', '.xls', '.csv'}
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in allowed_extensions:
            return jsonify({'success': False, 'message': '不支持的文件格式，请上传Excel或CSV文件'})
        
        # 保存临时文件
        filename = secure_filename(file.filename)
        temp_dir = tempfile.mkdtemp()
        filepath = os.path.join(temp_dir, filename)
        file.save(filepath)
        
        try:
            # ========== 调用导入工具函数 ==========
            result = import_devices_from_file(filepath, current_user.id)
            
            # 清理临时文件
            if os.path.exists(filepath):
                os.remove(filepath)
            if os.path.exists(temp_dir):
                os.rmdir(temp_dir)
            
            if result['success']:
                log_audit('create', 'device', None, f"文件导入设备: {result['imported_count']} 个", details={'imported_count': result.get('imported_count', 0), 'skipped_count': result.get('skipped_count', 0)})
                return jsonify({
                    'success': True,
                    'message': f"导入成功！共导入 {result['imported_count']} 台设备，跳过 {result['skipped_count']} 条记录",
                    'imported_count': result.get('imported_count', 0),
                    'skipped_count': result.get('skipped_count', 0),
                    'errors': result.get('errors', [])
                })
            else:
                return jsonify({
                    'success': False,
                    'message': result.get('message', '导入失败'),
                    'errors': result.get('errors', [])
                })
                
        except Exception as e:
            current_app.logger.error(f"导入处理失败: {str(e)}")
            if os.path.exists(filepath):
                os.remove(filepath)
            if os.path.exists(temp_dir):
                os.rmdir(temp_dir)
            return jsonify({'success': False, 'message': f'导入处理失败: {str(e)}'})
            
    except Exception as e:
        current_app.logger.error(f"导入设备失败: {str(e)}")
        return jsonify({'success': False, 'message': f'导入失败: {str(e)}'})


# ========== 清理无效设备路由 ==========
@device_bp.route('/cleanup_invalid_devices_preview')
@login_required
@permission_required('device:view')
def cleanup_invalid_devices_preview():
    """预览待清理的无效设备"""
    try:
        invalid_devices = Device.query.filter(
            (Device.management_ip.is_(None) | (Device.management_ip == '')) &
            (Device.mac_address.is_(None) | (Device.mac_address == ''))
        ).all()
        
        devices_data = []
        for dev in invalid_devices:
            devices_data.append({
                'id': dev.id,
                'name': dev.name,
                'device_type': dev.device_type,
                'management_ip': dev.management_ip or '-',
                'mac_address': dev.mac_address or '-',
                'created_at': dev.created_at.strftime('%Y-%m-%d %H:%M') if dev.created_at else '-'
            })
        
        return jsonify({
            'success': True,
            'count': len(devices_data),
            'devices': devices_data
        })
    except Exception as e:
        current_app.logger.error(f"预览无效设备失败: {str(e)}")
        return jsonify({'success': False, 'message': str(e)})


@device_bp.route('/cleanup_invalid_devices', methods=['POST'])
@login_required
@permission_required('device:edit')
def cleanup_invalid_devices():
    """清理无效设备"""
    try:
        invalid_devices = Device.query.filter(
            (Device.management_ip.is_(None) | (Device.management_ip == '')) &
            (Device.mac_address.is_(None) | (Device.mac_address == ''))
        ).all()
        
        deleted_count = 0
        deleted_names = []
        
        for dev in invalid_devices:
            deleted_names.append(dev.name)
            db.session.delete(dev)
            deleted_count += 1
        
        db.session.commit()
        log_audit('delete', 'device', None, f"清理 {deleted_count} 个无效设备", details={'deleted_count': deleted_count, 'deleted_names': deleted_names[:20]})

        return jsonify({
            'success': True,
            'message': f'成功清理 {deleted_count} 个无效设备',
            'deleted_count': deleted_count,
            'deleted_names': deleted_names[:20]
        })
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"清理无效设备失败: {str(e)}")
        return jsonify({'success': False, 'message': str(e)})


# ==================== 设备发现（任务模式） ====================

# 全局线程池用于设备发现
_device_discovery_executor = concurrent.futures.ThreadPoolExecutor(max_workers=5)
_device_stop_events = {}


def background_device_scan(task_id, app):
    """
    后台设备扫描任务 — 类似拓扑发现的 background_discovery
    支持 snmp_scan 和 ip_import 两种模式
    实时更新 task.progress 供前端轮询
    """
    import json

    with app.app_context():
        print(f"[设备发现] 后台任务 {task_id} 已启动")
        task = DiscoveryTask.query.get(task_id)
        if not task:
            print(f"[设备发现] 任务 {task_id} 不存在")
            return

        stop_event = _device_stop_events.get(task_id) or threading.Event()
        _device_stop_events[task_id] = stop_event

        task.status = 'running'
        task.last_run = datetime.now(timezone.utc)
        task.progress = 0
        task.discovered_count = 0
        db.session.commit()

        try:
            target_val = task.get_target_value()
            device_scan_mode = task.discovery_type or target_val.get('mode', 'snmp_scan')

            ip_range_str = target_val.get('ip_range', '')

            if not ip_range_str:
                task.status = 'failed'
                task.last_error = 'IP段为空'
                db.session.commit()
                return

            if device_scan_mode == 'ip_import':
                # ===== IP段批量导入模式 =====
                print(f"[设备发现] 执行 IP段批量导入: {ip_range_str}")
                device_type = target_val.get('device_type', 'unknown')
                manufacturer = target_val.get('manufacturer', '')
                skip_existing = target_val.get('skip_existing', True)
                use_ping = target_val.get('use_ping', True)
                concurrent = int(target_val.get('concurrent', 20))
                ping_timeout = int(target_val.get('ping_timeout', 2))

                # 使用进度管理器创建子任务
                scan_task_id = progress_manager.create_task('import')
                import_params = {
                    'ip_range': ip_range_str,
                    'device_type': device_type,
                    'cabinet_id': None,
                    'manufacturer': manufacturer,
                    'skip_existing': skip_existing,
                    'use_ping': use_ping,
                    'auto_naming': True,
                    'concurrent': concurrent,
                    'ping_timeout': ping_timeout,
                    'user_id': None,
                    'username': '系统'
                }
                # 启动进度同步线程
                sync_stop = threading.Event()
                def sync_progress_import():
                    while not sync_stop.is_set():
                        time.sleep(1)
                        try:
                            with app.app_context():
                                sp = progress_manager.get_progress(scan_task_id)
                                if sp:
                                    pct = sp.get('progress', 0)
                                    added = sp.get('added_count', 0) or sp.get('total_processed', 0) or sp.get('total_found', 0)
                                    db.session.query(DiscoveryTask).filter_by(id=task_id).update({
                                        'progress': int(float(pct)) if pct else 0,
                                        'discovered_count': int(added) if added else 0
                                    })
                                    db.session.commit()
                                    db.session.commit()
                        except Exception:
                            pass
                sync_thread = threading.Thread(target=sync_progress_import, daemon=True)
                sync_thread.start()

                try:
                    _run_import_task_impl(scan_task_id, import_params)
                finally:
                    sync_stop.set()
                    sync_thread.join(timeout=3)

                # 从进度管理器读取最终结果
                scan_progress = progress_manager.get_progress(scan_task_id)
                if scan_progress:
                    task.discovered_count = scan_progress.get('added_count', 0) or scan_progress.get('total_processed', 0)
                    if scan_progress.get('status') == 'failed':
                        task.status = 'failed'
                        task.last_error = scan_progress.get('message', '导入执行失败')

            else:
                # ===== IP段SNMP扫描模式 =====
                print(f"[设备发现] 执行 SNMP扫描: {ip_range_str}")
                snmp_community = target_val.get('snmp_community', 'public')
                snmp_version = target_val.get('snmp_version', '2c')
                snmp_timeout = int(target_val.get('snmp_timeout', 2))
                snmp_retries = int(target_val.get('snmp_retries', 2))
                auto_add = target_val.get('auto_add', True)
                skip_existing = target_val.get('skip_existing', True)

                scan_task_id = progress_manager.create_task('snmp_scan')
                scan_params = {
                    'ip_range': ip_range_str,
                    'snmp_community': snmp_community,
                    'snmp_version': snmp_version,
                    'auto_add': auto_add,
                    'skip_existing': skip_existing,
                    'snmp_timeout': snmp_timeout,
                    'snmp_retries': snmp_retries,
                    'user_id': None,
                    'username': '系统'
                }
                # 启动进度同步线程
                sync_stop = threading.Event()
                def sync_progress_snmp():
                    while not sync_stop.is_set():
                        time.sleep(1)
                        try:
                            with app.app_context():
                                sp = progress_manager.get_progress(scan_task_id)
                                if sp:
                                    pct = sp.get('progress', 0)
                                    added = sp.get('added_count', 0) or sp.get('total_found', 0) or sp.get('total_processed', 0)
                                    db.session.query(DiscoveryTask).filter_by(id=task_id).update({
                                        'progress': int(float(pct)) if pct else 0,
                                        'discovered_count': int(added) if added else 0
                                    })
                                    db.session.commit()
                        except Exception:
                            pass
                sync_thread = threading.Thread(target=sync_progress_snmp, daemon=True)
                sync_thread.start()

                try:
                    _run_snmp_scan_task_impl(scan_task_id, scan_params)
                finally:
                    sync_stop.set()
                    sync_thread.join(timeout=3)

                scan_progress = progress_manager.get_progress(scan_task_id)
                if scan_progress:
                    task.discovered_count = scan_progress.get('added_count', 0) or scan_progress.get('total_found', 0)
                    if scan_progress.get('status') == 'failed':
                        task.status = 'failed'
                        task.last_error = scan_progress.get('message', '扫描执行失败')

            if not stop_event.is_set():
                task.status = 'completed'
                task.progress = 100
                task.run_count = (task.run_count or 0) + 1
                task.success_count = (task.success_count or 0) + 1
                db.session.commit()

        except Exception as e:
            import traceback
            print(f"[设备发现] 任务 {task_id} 异常: {traceback.format_exc()}")
            task.status = 'failed'
            task.last_error = str(e)
            task.fail_count = (task.fail_count or 0) + 1
            db.session.commit()
        finally:
            if task_id in _device_stop_events:
                del _device_stop_events[task_id]
            print(f"[设备发现] 任务 {task_id} 结束，状态设为 {task.status}")


# ========== 设备发现路由 ==========

@device_bp.route('/discovery')
@login_required
@permission_required('device:view')
def device_discovery():
    """设备发现页面"""
    return render_template('device_discovery.html')


@device_bp.route('/discovery/tasks', methods=['GET'])
@login_required
@permission_required('device:view')
def discovery_task_list():
    """获取设备发现任务列表"""
    from scheduler import get_discovery_job_info

    tasks = DiscoveryTask.query.filter(
        DiscoveryTask.discovery_mode == 'device_scan'
    ).order_by(DiscoveryTask.created_at.desc()).all()

    task_list = []
    for task in tasks:
        task_dict = task.to_dict()
        # 附加调度器信息
        job_info = get_discovery_job_info(task.id)
        if job_info:
            task_dict['next_run_time'] = job_info['next_run_time']
            task_dict['schedule_status'] = 'scheduled'
        elif task.schedule_type in ('interval', 'cron') and task.enabled:
            task_dict['schedule_status'] = 'not_scheduled'
        else:
            task_dict['schedule_status'] = 'manual'
        task_list.append(task_dict)

    return jsonify({'success': True, 'tasks': task_list})


@device_bp.route('/discovery/create', methods=['POST'])
@login_required
@permission_required('device:edit')
def discovery_task_create():
    """创建设备发现任务"""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': '无效的请求数据'}), 400

    task_name = data.get('task_name')
    if not task_name:
        return jsonify({'success': False, 'message': '任务名称不能为空'}), 400

    target_value = data.get('target_value', {})

    task = DiscoveryTask(
        name=task_name,
        description=data.get('description', ''),
        discovery_mode='device_scan',
        discovery_type=data.get('device_scan_mode', 'snmp_scan'),
        target_type='ip_range',
        schedule_type=data.get('schedule_type', 'manual'),
        interval_seconds=data.get('interval_seconds', 3600),
        cron_expression=data.get('cron_expression'),
        use_lldp=False,
        use_cdp=False,
        use_snmp=(data.get('device_scan_mode', 'snmp_scan') == 'snmp_scan'),
        snmp_community=target_value.get('snmp_community', 'public'),
        snmp_version=int(target_value.get('snmp_version', '2c').replace('c', '').replace('v', '') or 2),
        snmp_timeout=int(target_value.get('snmp_timeout', 2)),
        snmp_retries=int(target_value.get('snmp_retries', 2)),
        max_threads=int(target_value.get('concurrent', 20)),
        auto_save=target_value.get('auto_add', True),
        enabled=True,
        status='idle',
        created_by=current_user.username
    )
    task.set_target_value(target_value)

    db.session.add(task)
    db.session.commit()

    # 注册调度器任务
    from scheduler import schedule_discovery_task, schedule_discovery_task_cron
    if task.schedule_type == 'interval':
        schedule_discovery_task(task.id, task.interval_seconds or 3600)
    elif task.schedule_type == 'cron' and task.cron_expression:
        schedule_discovery_task_cron(task.id, task.cron_expression)

    log_audit('create', 'discovery_task', task.id, f'创建设备发现任务 {task_name}',
              details={'device_scan_mode': data.get('device_scan_mode'), 'ip_range': target_value.get('ip_range')},
              user_id=current_user.id)
    return jsonify({'success': True, 'message': '发现任务创建成功', 'task_id': task.id})


@device_bp.route('/discovery/tasks/<int:task_id>', methods=['GET', 'PUT', 'DELETE'])
@login_required
@permission_required('device:edit')
def discovery_task_detail(task_id):
    """设备发现任务详情/更新/删除"""
    task = DiscoveryTask.query.get(task_id)
    if not task:
        return jsonify({'success': False, 'message': '任务不存在'}), 404

    if request.method == 'GET':
        task_dict = task.to_dict()
        from scheduler import get_discovery_job_info
        job_info = get_discovery_job_info(task.id)
        if job_info:
            task_dict['next_run_time'] = job_info['next_run_time']
            task_dict['schedule_status'] = 'scheduled'
        elif task.schedule_type in ('interval', 'cron') and task.enabled:
            task_dict['schedule_status'] = 'not_scheduled'
        else:
            task_dict['schedule_status'] = 'manual'
        return jsonify({'success': True, 'task': task_dict})

    elif request.method == 'PUT':
        try:
            data = request.get_json()
            if not data:
                return jsonify({'success': False, 'message': '无效的请求数据'}), 400

            if 'task_name' in data:
                task.name = data['task_name']
            if 'description' in data:
                task.description = data['description']
            if 'schedule_type' in data:
                task.schedule_type = data['schedule_type']
            if 'interval_seconds' in data:
                task.interval_seconds = data['interval_seconds']
            if 'cron_expression' in data:
                task.cron_expression = data['cron_expression']
            if 'enabled' in data:
                task.enabled = data['enabled']
            if 'device_scan_mode' in data:
                task.discovery_type = data['device_scan_mode']

            if 'target_value' in data:
                tv = data['target_value']
                task.set_target_value(tv)
                if tv.get('snmp_community'):
                    task.snmp_community = tv['snmp_community']
                if tv.get('concurrent'):
                    task.max_threads = int(tv['concurrent'])

            task.updated_at = datetime.now(timezone.utc)
            db.session.commit()

            # 更新调度器
            from scheduler import (schedule_discovery_task, schedule_discovery_task_cron,
                                   unschedule_discovery_task)
            unschedule_discovery_task(task.id)

            if task.enabled and task.schedule_type == 'interval':
                schedule_discovery_task(task.id, task.interval_seconds or 3600)
            elif task.enabled and task.schedule_type == 'cron' and task.cron_expression:
                schedule_discovery_task_cron(task.id, task.cron_expression)

            log_audit('update', 'discovery_task', task.id, f'更新设备发现任务 #{task.id}',
                      details={'task_name': task.name}, user_id=current_user.id)

            return jsonify({'success': True, 'message': '任务更新成功', 'task': task.to_dict()})
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'message': f'更新失败: {str(e)}'}), 500

    elif request.method == 'DELETE':
        try:
            task_name = task.name
            db.session.delete(task)
            db.session.commit()

            from scheduler import unschedule_discovery_task
            unschedule_discovery_task(task_id)

            log_audit('delete', 'discovery_task', task_id, f'删除设备发现任务 #{task_id} ({task_name})',
                      user_id=current_user.id)
            return jsonify({'success': True, 'message': '任务已删除'})
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'message': f'删除失败: {str(e)}'}), 500


@device_bp.route('/discovery/tasks/<int:task_id>/run', methods=['POST'])
@login_required
@permission_required('device:edit')
def discovery_task_run(task_id):
    """运行设备发现任务"""
    task = DiscoveryTask.query.get_or_404(task_id)
    if task.status == 'running':
        return jsonify({'success': False, 'message': '任务已在运行中'}), 400

    task.status = 'running'
    task.progress = 0
    db.session.commit()

    app = current_app._get_current_object()
    _device_stop_events[task.id] = threading.Event()
    _device_discovery_executor.submit(background_device_scan, task.id, app)

    log_audit('execute', 'discovery_task', task_id, f'启动设备发现任务 #{task_id}',
              user_id=current_user.id)
    return jsonify({'success': True, 'message': '任务已启动'})


@device_bp.route('/discovery/tasks/<int:task_id>/stop', methods=['POST'])
@login_required
@permission_required('device:edit')
def discovery_task_stop(task_id):
    """停止设备发现任务"""
    task = DiscoveryTask.query.get_or_404(task_id)
    if task.status != 'running':
        return jsonify({'success': False, 'message': '任务未在运行'}), 400

    if task_id in _device_stop_events:
        _device_stop_events[task_id].set()
    task.status = 'paused'
    db.session.commit()

    log_audit('update', 'discovery_task', task_id, f'停止设备发现任务 #{task_id}',
              user_id=current_user.id)
    return jsonify({'success': True, 'message': '任务已停止'})


@device_bp.route('/discovery/recent', methods=['GET'])
@login_required
@permission_required('device:view')
def discovery_recent_devices():
    """获取最近发现的设备（最近创建的设备）"""
    devices = Device.query.order_by(Device.created_at.desc()).limit(20).all()
    device_list = []
    for d in devices:
        device_list.append({
            'id': d.id,
            'name': d.name,
            'ip_address': d.ip_address,
            'management_ip': d.management_ip,
            'mac_address': d.mac_address,
            'device_type': d.device_type,
            'status': d.status,
            'created_at': d.created_at.isoformat() if d.created_at else None,
            'discovered_by': '设备发现'
        })
    return jsonify({'success': True, 'devices': device_list})


# ========== 设备下架 / 重新上架 / 永久删除 ==========

@device_bp.route('/<int:id>/decommission', methods=['POST'])
@login_required
@permission_required('device:edit')
def device_decommission(id):
    """下架设备（软删除，标记 is_decommissioned=True）"""
    device = Device.query.get_or_404(id)
    device.is_decommissioned = True
    device.status = 'offline'
    db.session.commit()
    log_audit('update', 'device', id, f'下架设备: {device.name}',
              user_id=current_user.id)
    flash(f'设备 "{device.name}" 已下架', 'success')
    return jsonify({'success': True, 'message': f'设备 "{device.name}" 已下架'})


@device_bp.route('/<int:id>/recommission', methods=['POST'])
@login_required
@permission_required('device:edit')
def device_recommission(id):
    """重新上架设备"""
    device = Device.query.get_or_404(id)
    device.is_decommissioned = False
    db.session.commit()
    log_audit('update', 'device', id, f'重新上架设备: {device.name}',
              user_id=current_user.id)
    flash(f'设备 "{device.name}" 已重新上架', 'success')
    return jsonify({'success': True, 'message': f'设备 "{device.name}" 已重新上架'})


@device_bp.route('/<int:id>/delete_permanent', methods=['POST'])
@login_required
@permission_required('device:edit')
def device_delete_permanent(id):
    """永久删除设备（物理删除）"""
    device = Device.query.get_or_404(id)
    device_name = device.name

    # 删除关联的接口
    Interface.query.filter_by(device_id=id).delete()
    # 删除关联的接口关系
    InterfaceRelationship.query.filter(
        (InterfaceRelationship.device_id == id) |
        (InterfaceRelationship.neighbor_device_id == id)
    ).delete(synchronize_session=False)
    # 删除关联的拓扑记录
    TopologyLog.query.filter(
        (TopologyLog.device_id == id) |
        (TopologyLog.neighbor_device_id == id)
    ).delete(synchronize_session=False)
    # 删除关联的告警
    AlertEvent.query.filter_by(device_id=id).delete()
    # 删除关联的监控数据
    MonitorData.query.filter_by(device_id=id).delete()
    DeviceMonitorLog.query.filter_by(device_id=id).delete()
    DeviceMonitorConfig.query.filter_by(device_id=id).delete()
    # 删除关联的配置记录
    ConfigBaseline.query.filter_by(device_id=id).delete()
    ConfigDrift.query.filter_by(device_id=id).delete()
    ConfigVersion.query.filter_by(device_id=id).delete()
    ComplianceCheckResult.query.filter_by(device_id=id).delete()
    # 删除关联的设备性能数据
    DevicePerformance.query.filter_by(device_id=id).delete()

    db.session.delete(device)
    db.session.commit()
    log_audit('delete', 'device', id, f'永久删除已下架设备: {device_name}',
              user_id=current_user.id)
    flash(f'设备 "{device_name}" 已永久删除', 'success')
    return jsonify({'success': True, 'message': f'设备 "{device_name}" 已永久删除'})


@device_bp.route('/decommissioned')
@login_required
@permission_required('device:view')
def decommissioned_list():
    """已下架设备列表"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    search = request.args.get('search', '').strip()
    device_type = request.args.get('device_type')

    query = Device.query.filter(Device.is_decommissioned == True)

    if search:
        query = query.filter(
            or_(
                Device.name.ilike(f'%{search}%'),
                Device.management_ip.ilike(f'%{search}%'),
                Device.serial_number.ilike(f'%{search}%'),
                Device.asset_number.ilike(f'%{search}%'),
                Device.model.ilike(f'%{search}%'),
                Device.brand.ilike(f'%{search}%'),
                Device.manufacturer.ilike(f'%{search}%')
            )
        )

    if device_type:
        query = query.filter(Device.device_type == device_type)

    pagination = query.order_by(Device.updated_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    devices = pagination.items

    # 下架设备统计
    total_decommissioned = Device.query.filter(Device.is_decommissioned == True).count()

    # 按类型统计下架设备
    type_stats = db.session.query(
        Device.device_type, func.count(Device.id)
    ).filter(
        Device.is_decommissioned == True
    ).group_by(Device.device_type).all()

    # 按品牌统计下架设备
    brand_stats = db.session.query(
        Device.brand, func.count(Device.id)
    ).filter(
        Device.is_decommissioned == True
    ).group_by(Device.brand).all()

    return render_template(
        'device_decommissioned.html',
        devices=devices,
        pagination=pagination,
        total_decommissioned=total_decommissioned,
        type_stats=type_stats,
        brand_stats=brand_stats
    )
