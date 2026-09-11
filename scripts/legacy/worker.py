# worker.py
import os
import sys
import json
import time
import logging
import signal
from datetime import datetime
from typing import List, Dict, Any

# 添加项目根目录到 Python 路径，以便导入项目模块
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import redis
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session

# 导入你的配置和模型（假设 config.py 和 models 在项目根目录）
from config import Config
from models.models import InterfaceMonitorData
from extensions import db  # 仅用于获取模型元数据，不依赖 Flask

# 配置日志
# 大小轮转：worker.log 单文件 > 5MB 时生成 worker.log.1 / .2 ...
# 过期备份由 logging_config.cleanup_old_log_files（保留 180 天）统一清理
from logging.handlers import RotatingFileHandler
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler(
            "worker.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=1000,
            encoding='utf-8'
        ),
        logging.StreamHandler()             # 同时输出到控制台
    ]
)
logger = logging.getLogger("worker")

from config import Config
from sqlalchemy import create_engine

# 创建数据库引擎
engine = create_engine(
    Config.SQLALCHEMY_DATABASE_URI,
    **Config.SQLALCHEMY_ENGINE_OPTIONS
)

def _counter_bits(last_value, current_value):
    """Guess counter width for delta wrap-around.

    With 64-bit HC counters normal values quickly exceed 2^32-1; legacy 32-bit
    counters stay below it until wrap. Using the larger of the two samples gives
    a cheap and reliable width for rate calculation.
    """
    return 64 if max(int(last_value or 0), int(current_value or 0)) >= (1 << 32) else 32


class MonitorDataWorker:
    def __init__(self):
        self.config = Config()
        print("=== Worker 配置 ===")
        print(f"REDIS_HOST: {self.config.REDIS_HOST}")
        print(f"REDIS_PORT: {self.config.REDIS_PORT}")
        print(f"REDIS_DB: {self.config.REDIS_DB}")
        print(f"REDIS_QUEUE_KEY: {self.config.REDIS_QUEUE_KEY}")
        print(f"REDIS_PASSWORD: {'[SET]' if self.config.REDIS_PASSWORD else '[MISSING]'}")
        print("====================")

        self.redis_client = redis.Redis(
            host=self.config.REDIS_HOST,
            port=self.config.REDIS_PORT,
            db=self.config.REDIS_DB,
            password=self.config.REDIS_PASSWORD,
            username=getattr(self.config, 'REDIS_USERNAME', None),
            decode_responses=True,
            socket_keepalive=True
        )

        self.queue_key = self.config.REDIS_QUEUE_KEY
        
        # 2. 数据库引擎配置
        # db_url = self.config.SQLALCHEMY_DATABASE_URI
        #db_url = 'mysql+pymysql://root:tcst2026@localhost/asset'
        # worker.py 中
        db_url = self.config.SQLALCHEMY_DATABASE_URI   # 从配置读取，而不是硬编码
        # SQLite 需要设置 check_same_thread=False
        connect_args = {'check_same_thread': False} if 'sqlite' in db_url else {}
        self.engine = create_engine(
            db_url,
            connect_args=connect_args,
            pool_pre_ping=True,      # 检测连接有效性
            echo=False               # 生产环境建议关闭 SQL 日志
        )

        # 创建会话工厂（线程安全）
        self.Session = scoped_session(sessionmaker(bind=self.engine))
        
        # 3. 批量处理参数
        self.batch_size = 50          # 每批次写入的记录数
        self.poll_interval = 1         # 无数据时休眠秒数（使用 blpop 时此参数不生效）
        self.running = True            # 运行标志
        
        # 4. 注册信号处理（用于优雅退出）
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)

    def stop(self, signum=None, frame=None):
        """停止 Worker"""
        logger.info("收到停止信号，正在优雅退出...")
        self.running = False

    def run(self):
        """主循环：从 Redis 获取数据，批量写入数据库"""
        logger.info("Worker 启动，等待数据...")
        buffer: List[Dict[str, Any]] = []
        
        while self.running:
            try:
                # 阻塞弹出单条数据，超时 1 秒（用于检测 self.running 变化）
                data = self.redis_client.blpop(self.queue_key, timeout=1)
                if data:
                    # data 格式: (queue_name, value)
                    record = json.loads(data[1])
                    buffer.append(record)
                    
                    # 达到批量大小，立即写入
                    if len(buffer) >= self.batch_size:
                        self._flush(buffer)
                        buffer = []
                else:
                    # 超时无数据，若有积压则写入剩余数据
                    if buffer:
                        self._flush(buffer)
                        buffer = []
            except Exception as e:
                logger.exception("处理数据时发生异常，等待后继续")
                time.sleep(5)
        
        # 退出前将剩余数据写入
        if buffer:
            self._flush(buffer)
        logger.info("Worker 已停止")

    def _flush(self, records: List[Dict]):
        if not records:
            return

        if records:
            logger.info(f"记录样本字段: {list(records[0].keys())}")

        # 日期字段转换
        date_fields = ['collected_at', 'created_at']
        for rec in records:
            for field in date_fields:
                if field in rec and isinstance(rec[field], str):
                    try:
                        dt_aware = datetime.fromisoformat(rec[field])
                        rec[field] = dt_aware.replace(tzinfo=None)
                    except ValueError:
                        rec[field] = datetime.utcnow()

        # ====== 速率计算 ======
        # 使用独立的会话查询历史数据
        session_calc = self.Session()
        try:
            for rec in records:
                interface_id = rec.get('interface_id')
                collected_at = rec.get('collected_at')
                if not interface_id or not collected_at:
                    continue

                # 查询上一条记录
                last_record = session_calc.query(InterfaceMonitorData).filter(
                    InterfaceMonitorData.interface_id == interface_id,
                    InterfaceMonitorData.collected_at < collected_at
                ).order_by(InterfaceMonitorData.collected_at.desc()).first()

                if last_record:
                    delta_t = (collected_at - last_record.collected_at).total_seconds()
                    if delta_t > 0:
                        if last_record.bytes_in in (0, None):
                            delta_in = 0
                        else:
                            delta_in = rec['bytes_in'] - last_record.bytes_in
                            if delta_in < 0:
                                delta_in += 2 ** _counter_bits(last_record.bytes_in, rec['bytes_in'])
                        if last_record.bytes_out in (0, None):
                            delta_out = 0
                        else:
                            delta_out = rec['bytes_out'] - last_record.bytes_out
                            if delta_out < 0:
                                delta_out += 2 ** _counter_bits(last_record.bytes_out, rec['bytes_out'])

                        rec['speed_in'] = delta_in * 8 / delta_t
                        rec['speed_out'] = delta_out * 8 / delta_t

                        speed = rec.get('speed') or last_record.speed
                        if speed and speed > 0:
                            rec['bandwidth_usage'] = max(rec['speed_in'], rec['speed_out']) / speed * 100

                        # 调试日志
                        logger.debug(f"接口 {interface_id} 速率计算: in={rec['speed_in']:.2f} bps, out={rec['speed_out']:.2f} bps")
                        print((f"接口 {interface_id} 速率计算: in={rec['speed_in']:.2f} bps, out={rec['speed_out']:.2f} bps"))
        except Exception as e:
            logger.error(f"速率计算失败: {e}")
        finally:
            session_calc.close()

        # ====== 批量插入 ======
        session = self.Session()
        try:
            session.bulk_insert_mappings(InterfaceMonitorData, records)
            session.commit()
            logger.info(f"成功写入 {len(records)} 条监控数据")
        except Exception as e:
            session.rollback()
            logger.error(f"批量写入失败: {e}")
        finally:
            session.close()
            self.Session.remove()  # 清理线程局部存储

if __name__ == '__main__':
    worker = MonitorDataWorker()
    worker.run()