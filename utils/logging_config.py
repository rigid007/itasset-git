import os
import sys
import json
import time
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
from flask import request, has_request_context
from flask_login import current_user
from extensions import db


class DatabaseLogHandler(logging.Handler):
    def __init__(self, app, system_log_model):
        super().__init__()
        self.app = app
        self.SystemLog = system_log_model

    def emit(self, record):
        try:
            with self.app.app_context():
                log_entry = self.SystemLog(
                    level=record.levelname.lower(),
                    module=record.name,
                    message=self.format(record),
                    details=json.dumps(record.__dict__, default=str, ensure_ascii=False) if hasattr(record, '__dict__') else None,
                    timestamp=datetime.utcnow(),
                    created_at=datetime.utcnow()
                )
                if has_request_context():
                    log_entry.ip_address = request.remote_addr
                    log_entry.request_id = request.headers.get('X-Request-ID', None)
                    if current_user.is_authenticated:
                        log_entry.user_id = current_user.id
                if hasattr(record, 'source'):
                    log_entry.source = record.source
                db.session.add(log_entry)
                db.session.commit()
        except Exception:
            import traceback
            traceback.print_exc()


# 日志保留天数：超过该天数的轮转备份文件将被自动删除
LOG_RETENTION_DAYS = 180

_log_cleanup_logger = logging.getLogger('log_cleanup')


def cleanup_old_log_files(logs_dir=None, retention_days=LOG_RETENTION_DAYS, dry_run=False):
    """
    删除 logs 目录下修改时间超过 retention_days 天的日志轮转备份文件。

    仅匹配带后缀的轮转备份（如 app.log.1、app.log.2、worker.log.1 等），
    不会删除当前正在写入的基础日志文件（app.log / worker.log），因为：
      1) 基础文件名不含 '.log.'（末尾 .log 后无额外点），不在匹配范围；
      2) 正在写入的文件 mtime 会被持续刷新，本就远未超期。

    :param logs_dir: 日志目录，默认取项目 logs/ 目录
    :param retention_days: 保留天数，默认 LOG_RETENTION_DAYS
    :param dry_run: 仅统计/打印，不真正删除
    :return: 删除（或待删除）的文件数量
    """
    if logs_dir is None:
        logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'logs')
    if not os.path.isdir(logs_dir):
        return 0

    cutoff = time.time() - retention_days * 86400
    removed = 0
    for name in os.listdir(logs_dir):
        # 仅处理轮转备份：文件名中须含 '.log.'（如 app.log.1 / worker.log.3）
        if '.log.' not in name:
            continue
        path = os.path.join(logs_dir, name)
        try:
            if os.path.getmtime(path) < cutoff:
                if dry_run:
                    _log_cleanup_logger.info(f"[dry_run] 将删除过期日志: {path}")
                else:
                    os.remove(path)
                removed += 1
        except OSError as e:
            _log_cleanup_logger.warning(f"删除日志文件失败 {path}: {e}")
            continue
    return removed


def setup_logging(app):
    logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'logs')
    os.makedirs(logs_dir, exist_ok=True)
    log_file_path = os.path.join(logs_dir, 'app.log')

    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    # 大小轮转：单文件 > 5MB 即生成新文件（app.log.1, app.log.2 ...）
    # 保留时长由 cleanup_old_log_files（默认 180 天）控制；此处 backupCount 仅作安全上限，
    # 设为较大值避免与时间保留策略冲突（真正的过期删除由每日定时清理按修改时间执行）。
    file_handler = RotatingFileHandler(
        log_file_path,
        maxBytes=5 * 1024 * 1024,
        backupCount=1000,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    from models.config_models import SystemLog
    db_handler = DatabaseLogHandler(app, SystemLog)
    db_handler.setLevel(logging.INFO)

    app.logger.handlers.clear()
    app.logger.addHandler(console_handler)
    app.logger.addHandler(file_handler)
    app.logger.addHandler(db_handler)
    app.logger.setLevel(logging.INFO)

    # 启动时按保留策略清理过期日志文件（默认 180 天）
    try:
        removed = cleanup_old_log_files()
        if removed:
            _log_cleanup_logger.info(f"启动清理过期日志文件 {removed} 个（保留 {LOG_RETENTION_DAYS} 天）")
    except Exception as e:
        _log_cleanup_logger.warning(f"启动清理过期日志失败: {e}")
