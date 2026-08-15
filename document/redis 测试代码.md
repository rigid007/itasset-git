import redis
import json
from datetime import datetime, timezone
from config import Config
from models.models import Interface

# 1. 获取一个真实接口
interface = Interface.query.first()
if not interface:
    print("错误：没有接口记录，请先创建设备和接口")
else:
    # 2. 连接到 Redis
    r = redis.Redis(
        host=Config.REDIS_HOST,
        port=Config.REDIS_PORT,
        db=Config.REDIS_DB,
        password=Config.REDIS_PASSWORD,
        decode_responses=True
    )
    
    # 3. 使用真实 ID 构造数据
    test_record = {
        'interface_id': interface.id,          # 使用真实接口ID
        'device_id': interface.device_id,      # 使用该接口所属的设备ID
        'bytes_in': 1000,
        'bytes_out': 2000,
        'packets_in': 10,
        'packets_out': 20,
        'errors_in': 0,
        'errors_out': 0,
        'drops_in': 0,
        'drops_out': 0,
        'speed_in': None,
        'speed_out': None,
        'bandwidth_usage': None,
        'admin_status': 'up',
        'oper_status': 'up',
        'speed': 1000000000,
        'collected_at': datetime.now(timezone.utc).isoformat(),
        'created_at': datetime.now(timezone.utc).isoformat()
    }
    
    # 4. 推送到 Redis
    r.rpush(Config.REDIS_QUEUE_KEY, json.dumps(test_record))
    print(f"测试数据已推送，接口ID={interface.id}, 设备ID={interface.device_id}")
