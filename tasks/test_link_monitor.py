# test_link_monitor.py
import sys
import os
sys.path.append(os.path.dirname(__file__))

from flask import Flask
from extensions import db
from models.models import ConnectionPath, Device, Interface
from tasks.link_monitor import LinkMonitor
from datetime import datetime

def test_link_monitor():
    # 创建应用上下文
    app = Flask(__name__)
    # 配置数据库连接（根据您的实际配置修改）
    app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:tcst2026@localhost/asset'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    db.init_app(app)
    
    with app.app_context():
        # 创建监控器实例
        monitor = LinkMonitor(app)
        
        # 查询所有链路
        connections = ConnectionPath.query.all()
        print(f"共有 {len(connections)} 条链路")
        
        for conn in connections:
            print(f"\n链路 ID={conn.id}: {conn.source_port} -> {conn.target_port}")
            print(f"当前状态: {conn.link_status}")
            
            # 检测单条链路
            result = monitor.check_single_link(conn.id, db.session)
            print(f"检测结果: {result['status']}")
            print(f"原因: {result.get('reason', 'N/A')}")
            print(f"源端状态: {result['source_status']}")
            print(f"目标端状态: {result['target_status']}")
            
            # 更新状态
            monitor.update_connection_status(conn, result)
            
            # 验证更新后的状态
            db.session.refresh(conn)
            print(f"更新后状态: {conn.link_status}")

if __name__ == '__main__':
    test_link_monitor()