# utils/device_import.py

import pandas as pd
import os
import tempfile
from datetime import datetime
from models import Device, Cabinet, Location
from extensions import db
import re


def generate_import_template():
    """生成设备导入模板Excel文件"""
    temp_dir = tempfile.mkdtemp()
    filepath = os.path.join(temp_dir, '设备导入模板.xlsx')
    
    # 列名 - 与 Device 模型字段对应
    columns = [
        '设备名称',
        '管理IP',
        '设备类型',
        '品牌',
        '型号',
        '序列号',
        '资产编号',
        'MAC地址',
        '厂商',
        '所属位置',
        '所属机柜',
        '高度(U)',
        '起始U位',
        '操作系统',
        '负责人',
        '部门',
        '采购日期',
        '保修到期',
        'SNMP社区',
        'SSH用户名',
        '描述/备注'
    ]
    
    # 示例数据
    sample_data = [
        [
            '核心交换机-01',      # 设备名称
            '192.168.1.1',        # 管理IP
            'switch',             # 设备类型
            'Cisco',              # 品牌
            'WS-C3750X-48T-S',    # 型号
            'FOC1234A1B2',        # 序列号
            'ASSET-001',          # 资产编号
            'AA:BB:CC:DD:EE:01',  # MAC地址
            'Cisco Systems',      # 厂商
            '数据中心-1楼',       # 所属位置
            '机柜-A01',           # 所属机柜
            '2',                  # 高度(U)
            '10',                 # 起始U位
            'IOS 15.2(2)E',       # 操作系统
            '张三',               # 负责人
            '网络部',             # 部门
            '2024-01-15',         # 采购日期
            '2027-01-14',         # 保修到期
            'public',             # SNMP社区
            'admin',              # SSH用户名
            '核心网络设备，用于连接各楼层交换机'  # 描述/备注
        ],
        [
            '数据库服务器-01',    # 设备名称
            '192.168.2.10',       # 管理IP
            'server',             # 设备类型
            'Dell',               # 品牌
            'PowerEdge R740',     # 型号
            'SN87654321',         # 序列号
            'ASSET-002',          # 资产编号
            'AA:BB:CC:DD:EE:02',  # MAC地址
            'Dell Inc.',          # 厂商
            '数据中心-2楼',       # 所属位置
            '机柜-B03',           # 所属机柜
            '2',                  # 高度(U)
            '5',                  # 起始U位
            'Ubuntu 22.04 LTS',   # 操作系统
            '李四',               # 负责人
            'IT部',               # 部门
            '2024-03-20',         # 采购日期
            '2027-03-19',         # 保修到期
            'public',             # SNMP社区
            'root',               # SSH用户名
            '主数据库服务器，运行MySQL'  # 描述/备注
        ],
        [
            '防火墙-01',          # 设备名称
            '192.168.1.254',      # 管理IP
            'firewall',           # 设备类型
            'Huawei',             # 品牌
            'USG6300',            # 型号
            'SN11223344',         # 序列号
            'ASSET-003',          # 资产编号
            'AA:BB:CC:DD:EE:03',  # MAC地址
            'Huawei Technologies',# 厂商
            '数据中心-1楼',       # 所属位置
            '机柜-A02',           # 所属机柜
            '1',                  # 高度(U)
            '15',                 # 起始U位
            'VRP 8.1.0',          # 操作系统
            '王五',               # 负责人
            '安全部',             # 部门
            '2024-02-10',         # 采购日期
            '2027-02-09',         # 保修到期
            'public',             # SNMP社区
            'admin',              # SSH用户名
            '边界防火墙，保护内网安全'  # 描述/备注
        ]
    ]
    
    device_type_desc = {
        'router': '路由器',
        'switch': '交换机',
        'firewall': '防火墙',
        'server': '服务器',
        'pc': '计算机',
        'ap': '无线AP',
        'unknown': '未知设备'
    }
    
    df = pd.DataFrame(sample_data, columns=columns)
    
    with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
        # 主数据表
        df.to_excel(writer, sheet_name='设备列表', index=False)
        
        # 说明sheet
        instruction_data = [
            ['📋 导入说明', ''],
            ['', ''],
            ['【必填字段】', ''],
            ['设备名称', '设备的显示名称，不能重复'],
            ['管理IP', '有效的IPv4地址，不能重复'],
            ['设备类型', 'router/switch/firewall/server/pc/ap/unknown'],
            ['', ''],
            ['【字段说明】', ''],
            ['品牌', '设备品牌名称'],
            ['型号', '设备具体型号'],
            ['序列号', '设备序列号，不能重复'],
            ['资产编号', '内部资产编号，不能重复'],
            ['MAC地址', '格式: AA:BB:CC:DD:EE:FF 或 AA-BB-CC-DD-EE-FF'],
            ['所属位置', '需要在系统中已创建，否则导入时忽略'],
            ['所属机柜', '需要在系统中已创建，否则导入时忽略'],
            ['高度(U)', '数字，默认为1'],
            ['起始U位', '在机柜中的起始位置，数字'],
            ['操作系统', '操作系统版本信息'],
            ['负责人', '设备负责人姓名'],
            ['部门', '所属部门'],
            ['采购日期', '格式: YYYY-MM-DD'],
            ['保修到期', '格式: YYYY-MM-DD'],
            ['SNMP社区', 'SNMP社区字符串，默认public'],
            ['SSH用户名', 'SSH登录用户名'],
            ['描述/备注', '其他备注信息'],
            ['', ''],
            ['【状态值说明】', ''],
            ['设备状态由系统自动检测', 'online/offline/fault/unknown'],
            ['导入时状态字段会被忽略', '系统会根据检测结果自动更新'],
            ['', ''],
            ['【注意事项】', ''],
            ['1. 设备名称和管理IP不能重复', '重复的记录会被跳过'],
            ['2. 序列号和资产编号也不能重复', '重复的记录会被跳过'],
            ['3. 所属位置和机柜需要先在系统中创建', '否则关联失败'],
            ['4. 日期格式必须为 YYYY-MM-DD', '如: 2024-01-15'],
            ['5. 管理IP必须是有效的IPv4地址', '如: 192.168.1.1'],
            ['6. 示例数据仅供参考，导入前请删除或修改', ''],
            ['', ''],
            ['✅ 导入成功后会刷新页面显示新设备', '']
        ]
        df_instruction = pd.DataFrame(instruction_data)
        df_instruction.to_excel(writer, sheet_name='说明', index=False, header=False)
        
        # 设备类型说明sheet
        type_data = [
            ['类型代码', '中文名称', '说明'],
            ['router', '路由器', '网络路由器设备'],
            ['switch', '交换机', '网络交换机设备'],
            ['firewall', '防火墙', '防火墙安全设备'],
            ['server', '服务器', '物理服务器设备'],
            ['pc', '计算机', '台式机/工作站'],
            ['ap', '无线AP', '无线接入点'],
            ['unknown', '未知设备', '无法确定类型的设备']
        ]
        df_types = pd.DataFrame(type_data)
        df_types.to_excel(writer, sheet_name='设备类型说明', index=False)
    
    return filepath


# utils/device_import.py - 更新导入逻辑（使用ID关联）

def import_devices_from_file(filepath, user_id):
    """从文件导入设备 - 使用位置ID和机柜ID关联"""
    try:
        import pandas as pd
        import re
        from datetime import datetime
        from models import Device, Cabinet, Location
        from extensions import db
        
        ext = os.path.splitext(filepath)[1].lower()
        
        if ext == '.csv':
            df = pd.read_csv(filepath, encoding='utf-8-sig')
        else:
            try:
                df = pd.read_excel(filepath, sheet_name='设备导入模板', engine='openpyxl')
            except:
                df = pd.read_excel(filepath, sheet_name=0, engine='openpyxl')
        
        # 检查必要的列
        required_columns = ['设备名称', '管理IP', '设备类型']
        missing_columns = [col for col in required_columns if col not in df.columns]
        
        if missing_columns:
            return {
                'success': False,
                'message': f'缺少必要的列: {", ".join(missing_columns)}',
                'errors': [f'缺少列: {col}' for col in missing_columns]
            }
        
        # 获取已存在的设备
        existing_devices = Device.query.all()
        existing_ips = set()
        existing_names = set()
        existing_serial = set()
        existing_asset = set()
        for dev in existing_devices:
            if dev.management_ip:
                existing_ips.add(dev.management_ip)
            if dev.name:
                existing_names.add(dev.name)
            if dev.serial_number:
                existing_serial.add(dev.serial_number)
            if dev.asset_number:
                existing_asset.add(dev.asset_number)
        
        imported_count = 0
        skipped_count = 0
        errors = []
        
        # 设备类型映射
        type_map = {
            '路由器': 'router', '交换机': 'switch', '防火墙': 'firewall',
            '服务器': 'server', '计算机': 'pc', '无线AP': 'ap',
            '未知设备': 'unknown',
            'router': 'router', 'switch': 'switch', 'firewall': 'firewall',
            'server': 'server', 'pc': 'pc', 'ap': 'ap', 'unknown': 'unknown'
        }
        
        for idx, row in df.iterrows():
            try:
                # 获取字段值
                name = str(row.get('设备名称', '')).strip()
                ip = str(row.get('管理IP', '')).strip()
                device_type_raw = str(row.get('设备类型', 'unknown')).strip().lower()
                
                # 可选字段
                brand = str(row.get('品牌', '')).strip() if pd.notna(row.get('品牌', '')) else ''
                model = str(row.get('型号', '')).strip() if pd.notna(row.get('型号', '')) else ''
                serial_number = str(row.get('序列号', '')).strip() if pd.notna(row.get('序列号', '')) else ''
                asset_number = str(row.get('资产编号', '')).strip() if pd.notna(row.get('资产编号', '')) else ''
                mac_address = str(row.get('MAC地址', '')).strip() if pd.notna(row.get('MAC地址', '')) else ''
                manufacturer = str(row.get('厂商', '')).strip() if pd.notna(row.get('厂商', '')) else ''
                
                # ========== 使用ID关联 ==========
                location_id_raw = str(row.get('位置ID', '')).strip() if pd.notna(row.get('位置ID', '')) else ''
                cabinet_id_raw = str(row.get('机柜ID', '')).strip() if pd.notna(row.get('机柜ID', '')) else ''
                
                height_u = str(row.get('高度(U)', '1')).strip() if pd.notna(row.get('高度(U)', '')) else '1'
                position_u = str(row.get('起始U位', '')).strip() if pd.notna(row.get('起始U位', '')) else ''
                os_version = str(row.get('操作系统', '')).strip() if pd.notna(row.get('操作系统', '')) else ''
                owner = str(row.get('负责人', '')).strip() if pd.notna(row.get('负责人', '')) else ''
                department = str(row.get('部门', '')).strip() if pd.notna(row.get('部门', '')) else ''
                purchase_date = str(row.get('采购日期', '')).strip() if pd.notna(row.get('采购日期', '')) else ''
                warranty_expiry = str(row.get('保修到期', '')).strip() if pd.notna(row.get('保修到期', '')) else ''
                snmp_community = str(row.get('SNMP社区', '')).strip() if pd.notna(row.get('SNMP社区', '')) else ''
                ssh_username = str(row.get('SSH用户名', '')).strip() if pd.notna(row.get('SSH用户名', '')) else ''
                description = str(row.get('描述/备注', '')).strip() if pd.notna(row.get('描述/备注', '')) else ''
                
                # 验证必填字段
                if not name:
                    errors.append(f'第{idx+2}行: 设备名称不能为空')
                    continue
                if not ip:
                    errors.append(f'第{idx+2}行: 管理IP不能为空')
                    continue
                
                # 验证IP格式
                if not is_valid_ip(ip):
                    errors.append(f'第{idx+2}行: IP格式无效: {ip}')
                    continue
                
                # 检查重复
                if ip in existing_ips:
                    errors.append(f'第{idx+2}行: IP {ip} 已存在，跳过')
                    skipped_count += 1
                    continue
                if name in existing_names:
                    errors.append(f'第{idx+2}行: 设备名称 {name} 已存在，跳过')
                    skipped_count += 1
                    continue
                if serial_number and serial_number in existing_serial:
                    errors.append(f'第{idx+2}行: 序列号 {serial_number} 已存在，跳过')
                    skipped_count += 1
                    continue
                if asset_number and asset_number in existing_asset:
                    errors.append(f'第{idx+2}行: 资产编号 {asset_number} 已存在，跳过')
                    skipped_count += 1
                    continue
                
                # 解析设备类型
                device_type = type_map.get(device_type_raw, 'unknown')
                if device_type == 'unknown' and device_type_raw not in type_map:
                    for cn, en in type_map.items():
                        if device_type_raw in cn or cn in device_type_raw:
                            device_type = en
                            break
                
                # ========== 通过ID查找位置 ==========
                location_id = None
                if location_id_raw:
                    try:
                        loc_id_int = int(location_id_raw)
                        loc = Location.query.get(loc_id_int)
                        if loc:
                            location_id = loc.id
                        else:
                            errors.append(f'第{idx+2}行: 位置ID {location_id_raw} 不存在')
                    except ValueError:
                        errors.append(f'第{idx+2}行: 位置ID格式无效: {location_id_raw}，应为数字')
                
                # ========== 通过ID查找机柜 ==========
                cabinet_id = None
                if cabinet_id_raw:
                    try:
                        cab_id_int = int(cabinet_id_raw)
                        cab = Cabinet.query.get(cab_id_int)
                        if cab:
                            cabinet_id = cab.id
                        else:
                            errors.append(f'第{idx+2}行: 机柜ID {cabinet_id_raw} 不存在')
                    except ValueError:
                        errors.append(f'第{idx+2}行: 机柜ID格式无效: {cabinet_id_raw}，应为数字')
                
                # 解析高度
                try:
                    height_u_int = int(float(height_u)) if height_u else 1
                    if height_u_int < 1:
                        height_u_int = 1
                except ValueError:
                    height_u_int = 1
                
                # 解析起始U位
                position_u_int = None
                if position_u:
                    try:
                        position_u_int = int(float(position_u))
                    except ValueError:
                        pass
                
                # 解析日期
                purchase_date_obj = None
                if purchase_date:
                    try:
                        purchase_date_obj = datetime.strptime(purchase_date, '%Y-%m-%d').date()
                    except ValueError:
                        errors.append(f'第{idx+2}行: 采购日期格式无效: {purchase_date}，应为 YYYY-MM-DD')
                
                warranty_expiry_obj = None
                if warranty_expiry:
                    try:
                        warranty_expiry_obj = datetime.strptime(warranty_expiry, '%Y-%m-%d').date()
                    except ValueError:
                        errors.append(f'第{idx+2}行: 保修到期格式无效: {warranty_expiry}，应为 YYYY-MM-DD')
                
                # 标准化MAC地址
                mac = mac_address if mac_address else None
                if mac:
                    mac = mac.upper().replace('-', ':')
                    if not re.match(r'^([0-9A-F]{2}:){5}[0-9A-F]{2}$', mac):
                        errors.append(f'第{idx+2}行: MAC地址格式无效: {mac_address}')
                        mac = None
                
                # 创建设备
                device = Device(
                    name=name,
                    management_ip=ip,
                    device_type=device_type,
                    brand=brand or None,
                    model=model or None,
                    serial_number=serial_number or None,
                    asset_number=asset_number or None,
                    mac_address=mac,
                    manufacturer=manufacturer or None,
                    cabinet_id=cabinet_id,
                    location_id=location_id,
                    height_u=height_u_int,
                    position_u=position_u_int,
                    os_version=os_version or None,
                    owner=owner or None,
                    department=department or None,
                    purchase_date=purchase_date_obj,
                    warranty_expiry=warranty_expiry_obj,
                    snmp_community=snmp_community or None,
                    ssh_username=ssh_username or None,
                    description=description or None,
                    status='unknown',
                    created_at=datetime.now(),
                    updated_at=datetime.now()
                )
                
                db.session.add(device)
                imported_count += 1
                existing_ips.add(ip)
                existing_names.add(name)
                if serial_number:
                    existing_serial.add(serial_number)
                if asset_number:
                    existing_asset.add(asset_number)
                
            except Exception as e:
                errors.append(f'第{idx+2}行: {str(e)}')
                continue
        
        db.session.commit()
        
        return {
            'success': True,
            'imported_count': imported_count,
            'skipped_count': skipped_count,
            'errors': errors
        }
        
    except Exception as e:
        db.session.rollback()
        return {
            'success': False,
            'message': f'导入失败: {str(e)}',
            'errors': [str(e)]
        }


def is_valid_ip(ip):
    """验证IP地址格式"""
    if not ip or ip == '':
        return False
    pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
    if not re.match(pattern, ip):
        return False
    parts = ip.split('.')
    for part in parts:
        if int(part) < 0 or int(part) > 255:
            return False
    return True