# task_scheduler.py
import json
import logging
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR
from flask import current_app
import time

logger = logging.getLogger(__name__)

class DeviceMonitorScheduler:
    """设备监控调度器"""
    
    def __init__(self, app=None):
        self.app = app
        self.scheduler = None
        self.jobs = {}
        
    def init_app(self, app):
        """初始化调度器"""
        self.app = app
        
        # 创建调度器
        self.scheduler = BackgroundScheduler(
            daemon=True,
            timezone='Asia/Shanghai'
        )
        
        # 添加事件监听
        self.scheduler.add_listener(self.on_job_executed, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)
        
        # 启动调度器
        self.scheduler.start()
        
        # 应用退出时关闭调度器
        import atexit
        atexit.register(lambda: self.scheduler.shutdown())
        
        logger.info("设备监控调度器已启动")
        
    def on_job_executed(self, event):
        """任务执行事件处理"""
        with self.app.app_context():
            from models import TaskSchedule, db
            
            task = TaskSchedule.query.filter_by(task_name=event.job_id).first()
            if task:
                task.last_run = datetime.utcnow()
                task.run_count += 1
                
                if event.exception:
                    task.last_status = 'error'
                    logger.error(f"任务 {event.job_id} 执行失败: {event.exception}")
                else:
                    task.last_status = 'success'
                
                db.session.commit()
    
    def add_device_monitor_job(self, interval_minutes=5, concurrent_workers=10):
        """添加设备监控任务"""
        from models import TaskSchedule, db
        
        task_name = 'device_auto_monitor'
        
        # 检查任务是否已存在
        existing_task = TaskSchedule.query.filter_by(task_name=task_name).first()
        if not existing_task:
            # 创建任务记录
            task = TaskSchedule(
                task_name=task_name,
                task_description='设备自动监控任务',
                is_active=True,
                schedule_type='interval',
                schedule_value=json.dumps({
                    'interval_minutes': interval_minutes,
                    'concurrent_workers': concurrent_workers
                }),
                last_status='idle'
            )
            db.session.add(task)
            db.session.commit()
            existing_task = task
        
        # 移除现有任务（如果存在）
        self.remove_job(task_name)
        
        # 添加新任务
        if existing_task.is_active:
            job = self.scheduler.add_job(
                func=self.run_device_monitor,
                trigger=IntervalTrigger(minutes=interval_minutes),
                id=task_name,
                replace_existing=True,
                kwargs={
                    'concurrent_workers': concurrent_workers,
                    'task_id': existing_task.id
                }
            )
            
            # 更新下次运行时间
            existing_task.next_run = job.next_run_time
            db.session.commit()
            
            self.jobs[task_name] = job
            logger.info(f"设备监控任务已添加，间隔: {interval_minutes}分钟")
            
            return job
    
    def remove_job(self, job_id):
        """移除任务"""
        if job_id in self.jobs:
            self.scheduler.remove_job(job_id)
            del self.jobs[job_id]
            logger.info(f"任务 {job_id} 已移除")
    
    def update_schedule(self, task_name, interval_minutes=None, is_active=None):
        """更新任务调度"""
        with self.app.app_context():
            from models import TaskSchedule, db
            
            task = TaskSchedule.query.filter_by(task_name=task_name).first()
            if not task:
                return False
            
            # 更新配置
            if interval_minutes is not None:
                schedule_value = json.loads(task.schedule_value) if task.schedule_value else {}
                schedule_value['interval_minutes'] = interval_minutes
                task.schedule_value = json.dumps(schedule_value)
            
            if is_active is not None:
                task.is_active = is_active
            
            task.updated_at = datetime.utcnow()
            db.session.commit()
            
            # 重新调度任务
            if task.is_active:
                schedule_value = json.loads(task.schedule_value) if task.schedule_value else {}
                interval_minutes = schedule_value.get('interval_minutes', 5)
                concurrent_workers = schedule_value.get('concurrent_workers', 10)
                
                self.add_device_monitor_job(interval_minutes, concurrent_workers)
            else:
                self.remove_job(task_name)
            
            return True
    
    def run_device_monitor(self, concurrent_workers=10, task_id=None):
        """运行设备监控"""
        with self.app.app_context():
            logger.info("开始执行设备自动监控...")
            
            try:
                from models import Device, DeviceMonitorLog, db
                from utils import check_device_status
                
                start_time = time.time()
                
                # 获取所有需要监控的设备
                devices = Device.query.filter(
                    Device.management_ip.isnot(None),
                    Device.management_ip != ''
                ).all()
                
                total_devices = len(devices)
                logger.info(f"需要监控的设备数量: {total_devices}")
                
                if total_devices == 0:
                    logger.info("没有需要监控的设备")
                    return
                
                # 导入并发模块
                from concurrent.futures import ThreadPoolExecutor, as_completed
                
                monitored_count = 0
                status_changed_count = 0
                
                # 使用线程池并发检测
                with ThreadPoolExecutor(max_workers=concurrent_workers) as executor:
                    # 提交所有设备检测任务
                    future_to_device = {
                        executor.submit(self.monitor_single_device, device): device 
                        for device in devices
                    }
                    
                    # 处理结果
                    for future in as_completed(future_to_device):
                        device = future_to_device[future]
                        try:
                            result = future.result()
                            if result:
                                monitored_count += 1
                                if result.get('status_changed'):
                                    status_changed_count += 1
                                    
                        except Exception as e:
                            logger.error(f"监控设备 {device.name} 时出错: {str(e)}")
                
                # 更新任务记录
                if task_id:
                    task = TaskSchedule.query.get(task_id)
                    if task:
                        task.last_run = datetime.utcnow()
                        db.session.commit()
                
                elapsed_time = time.time() - start_time
                logger.info(f"设备监控完成! 总共: {total_devices}, 已监控: {monitored_count}, 状态变化: {status_changed_count}, 耗时: {elapsed_time:.2f}秒")
                
            except Exception as e:
                logger.error(f"设备监控任务执行失败: {str(e)}")
                import traceback
                traceback.print_exc()
    
    def monitor_single_device(self, device):
        """监控单个设备"""
        try:
            from models import DeviceMonitorLog, db
            from utils import check_device_status
            
            old_status = device.status
            
            # 检测设备状态
            is_online, response_time = check_device_status(device)
            
            new_status = 'online' if is_online else 'offline'
            status_changed = (old_status != new_status)
            
            # 更新设备状态
            device.status = new_status
            device.ping_time = response_time if is_online else 0
            device.last_checked = datetime.utcnow()
            
            # 记录监控日志
            log = DeviceMonitorLog(
                device_id=device.id,
                device_ip=device.management_ip,
                old_status=old_status,
                new_status=new_status,
                ping_time=response_time if is_online else 0,
                is_online=is_online,
                monitor_type='auto_ping',
                error_message=None
            )
            db.session.add(log)
            
            # 提交更改
            db.session.commit()
            
            # 记录状态变化
            if status_changed:
                logger.info(f"设备状态变化: {device.name} ({device.management_ip}) {old_status} -> {new_status}")
            
            return {
                'device_id': device.id,
                'device_name': device.name,
                'ip': device.management_ip,
                'old_status': old_status,
                'new_status': new_status,
                'is_online': is_online,
                'response_time': response_time,
                'status_changed': status_changed
            }
            
        except Exception as e:
            logger.error(f"监控设备 {device.name} 时出错: {str(e)}")
            
            # 记录错误日志
            try:
                log = DeviceMonitorLog(
                    device_id=device.id,
                    device_ip=device.management_ip,
                    old_status=device.status,
                    new_status='unknown',
                    is_online=False,
                    monitor_type='auto_ping',
                    error_message=str(e)
                )
                db.session.add(log)
                db.session.commit()
            except:
                db.session.rollback()
            
            return None
    
    def get_scheduler_status(self):
        """获取调度器状态"""
        status = {
            'running': self.scheduler.running if self.scheduler else False,
            'job_count': len(self.scheduler.get_jobs()) if self.scheduler else 0,
            'jobs': []
        }
        
        for job in self.scheduler.get_jobs() if self.scheduler else []:
            status['jobs'].append({
                'id': job.id,
                'next_run': job.next_run_time.isoformat() if job.next_run_time else None,
                'trigger': str(job.trigger)
            })
        
        return status

# 全局调度器实例
device_scheduler = DeviceMonitorScheduler()
