# add_vlan_to_interface.py
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from app import app, db

def add_vlan_column():
    """向interfaces表添加vlan列"""
    with app.app_context():
        try:
            from sqlalchemy import text
            
            # 检查vlan列是否存在
            result = db.session.execute(text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'interfaces' AND column_name = 'vlan'
            """))
            
            if result.fetchone():
                print("vlan列已存在")
                return
            
            print("正在添加vlan列到interfaces表...")
            # 添加vlan列
            db.session.execute(text("""
                ALTER TABLE interfaces 
                ADD COLUMN vlan VARCHAR(20)
            """))
            db.session.commit()
            print("成功添加vlan列")
            
        except Exception as e:
            db.session.rollback()
            print(f"添加vlan列失败: {str(e)}")
            import traceback
            traceback.print_exc()

def add_type_column():
    """向interfaces表添加type列（如果还没有）"""
    with app.app_context():
        try:
            from sqlalchemy import text
            
            # 检查type列是否存在
            result = db.session.execute(text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'interfaces' AND column_name = 'type'
            """))
            
            if result.fetchone():
                print("type列已存在")
                return
            
            print("正在添加type列到interfaces表...")
            # 添加type列
            db.session.execute(text("""
                ALTER TABLE interfaces 
                ADD COLUMN type VARCHAR(50) DEFAULT 'Ethernet'
            """))
            db.session.commit()
            print("成功添加type列")
            
        except Exception as e:
            db.session.rollback()
            print(f"添加type列失败: {str(e)}")
            import traceback
            traceback.print_exc()

if __name__ == '__main__':
    add_type_column()
    add_vlan_column()
