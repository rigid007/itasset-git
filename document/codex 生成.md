                                                                                                                              raise BuildError(endpoint, values, method, self)                                                                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^                                                                                                                                                                                                werkzeug.routing.exceptions.BuildError: Could not build url for endpoint 'login'. Did you mean 'auth.login'         instead?                                                                                                              
● /login 路由现在在 auth 蓝图中，需要将所有 url_for('login') 改为 url_for('auth.login')。

  Searched for 2 patterns (ctrl+o to expand)

● Update(templates\base1.html)
  ⎿  File must be read first

● Update(templates\base.html)
  ⎿  File must be read first
                                                                                                                          Searched for 3 patterns, read 2 files (ctrl+o to expand)

● Update(templates\base1.html)
  ⎿  Added 1 line, removed 1 line
      649                              <li><hr class="dropdown-divider"></li>
      650                              <li><a class="dropdown-item" href="{{ url_for('logout') }}"><i class="fas
           fa-sign-out-alt"></i> 退出登录</a></li>
      651                              {% else %}
      652 -                            <li><a class="dropdown-item" href="{{ url_for('login') }}"><i class="fas f
          -a-sign-in-alt"></i> 登录</a></li>
      652 +                            <li><a class="dropdown-item" href="{{ url_for('auth.login') }}"><i class="
          +fas fa-sign-in-alt"></i> 登录</a></li>
      653                              <li><a class="dropdown-item" href="{{ url_for('register') }}"><i class="fa
           s fa-user-plus"></i> 注册</a></li>
      654                              {% endif %}
      655                          </ul>

● Update(templates\base1.html)
  ⎿  Added 1 line, removed 1 line
      647                              <li><a class="dropdown-item" href="{{ url_for('profile') }}"><i class="fas
            fa-user"></i> 个人资料</a></li>
      648                              <li><a class="dropdown-item" href="{{ url_for('change_password') }}"><i cl
           ass="fas fa-key"></i> 修改密码</a></li>
      649                              <li><hr class="dropdown-divider"></li>
      650 -                            <li><a class="dropdown-item" href="{{ url_for('logout') }}"><i class="fas
          -fa-sign-out-alt"></i> 退出登录</a></li>
      650 +                            <li><a class="dropdown-item" href="{{ url_for('auth.logout') }}"><i class=
          +"fas fa-sign-out-alt"></i> 退出登录</a></li>
      651                              {% else %}
      652                              <li><a class="dropdown-item" href="{{ url_for('auth.login') }}"><i class="
           fas fa-sign-in-alt"></i> 登录</a></li>
      653                              <li><a class="dropdown-item" href="{{ url_for('register') }}"><i class="fa
           s fa-user-plus"></i> 注册</a></li>

● Update(templates\base1.html)                                                                                            ⎿  Added 1 line, removed 1 line
      650                              <li><a class="dropdown-item" href="{{ url_for('auth.logout') }}"><i class=                  "fas fa-sign-out-alt"></i> 退出登录</a></li>
      651                              {% else %}
      652                              <li><a class="dropdown-item" href="{{ url_for('auth.login') }}"><i class="
           fas fa-sign-in-alt"></i> 登录</a></li>
      653 -                            <li><a class="dropdown-item" href="{{ url_for('register') }}"><i class="fa
          -s fa-user-plus"></i> 注册</a></li>
      653 +                            <li><a class="dropdown-item" href="{{ url_for('auth.register') }}"><i clas
          +s="fas fa-user-plus"></i> 注册</a></li>
      654                              {% endif %}
      655                          </ul>
      656                      </li>

● Update(templates\base1.html)                                                                                            ⎿  Added 1 line, removed 1 line
      645                          <ul class="dropdown-menu dropdown-menu-end" aria-labelledby="userDropdown">                646                              {% if current_user.is_authenticated %}
      647                              <li><a class="dropdown-item" href="{{ url_for('profile') }}"><i class="fas
            fa-user"></i> 个人资料</a></li>
      648 -                            <li><a class="dropdown-item" href="{{ url_for('change_password') }}"><i cl
          -ass="fas fa-key"></i> 修改密码</a></li>
      648 +                            <li><a class="dropdown-item" href="{{ url_for('auth.change_password') }}">
          +<i class="fas fa-key"></i> 修改密码</a></li>
      649                              <li><hr class="dropdown-divider"></li>
      650                              <li><a class="dropdown-item" href="{{ url_for('auth.logout') }}"><i class=
           "fas fa-sign-out-alt"></i> 退出登录</a></li>
      651                              {% else %}                                                                       
● Update(templates\base.html)                                                                                             ⎿  Added 1 line, removed 1 line
      515                              <li><hr class="dropdown-divider"></li>
      516                              <li><a class="dropdown-item" href="{{ url_for('logout') }}"><i class="fas
           fa-sign-out-alt"></i> 退出登录</a></li>
      517                              {% else %}
      518 -                            <li><a class="dropdown-item" href="{{ url_for('login') }}"><i class="fas f
          -a-sign-in-alt"></i> 登录</a></li>
      518 +                            <li><a class="dropdown-item" href="{{ url_for('auth.login') }}"><i class="
          +fas fa-sign-in-alt"></i> 登录</a></li>
      519                              <!-- <li><a class="dropdown-item" href="{{ url_for('register') }}"><i clas
           s="fas fa-user-plus"></i> 注册</a></li> -->
      520                              {% endif %}
      521                          </ul>

● Update(templates\base.html)
  ⎿  Added 1 line, removed 1 line
      513                                  <i class="fas fa-key"></i> 修改密码
      514                              </a></li>
      515                              <li><hr class="dropdown-divider"></li>
      516 -                            <li><a class="dropdown-item" href="{{ url_for('logout') }}"><i class="fas
          -fa-sign-out-alt"></i> 退出登录</a></li>
      516 +                            <li><a class="dropdown-item" href="{{ url_for('auth.logout') }}"><i class=
          +"fas fa-sign-out-alt"></i> 退出登录</a></li>
      517                              {% else %}                                                                             518                              <li><a class="dropdown-item" href="{{ url_for('auth.login') }}"><i class="
           fas fa-sign-in-alt"></i> 登录</a></li>                                                                             519                              <!-- <li><a class="dropdown-item" href="{{ url_for('register') }}"><i clas
           s="fas fa-user-plus"></i> 注册</a></li> -->

● Update(templates\base.html)
  ⎿  Added 1 line, removed 1 line
      516                              <li><a class="dropdown-item" href="{{ url_for('auth.logout') }}"><i class=
           "fas fa-sign-out-alt"></i> 退出登录</a></li>
      517                              {% else %}
      518                              <li><a class="dropdown-item" href="{{ url_for('auth.login') }}"><i class="
           fas fa-sign-in-alt"></i> 登录</a></li>
      519 -                            <!-- <li><a class="dropdown-item" href="{{ url_for('register') }}"><i clas                 -s="fas fa-user-plus"></i> 注册</a></li> -->
      519 +                            <!-- <li><a class="dropdown-item" href="{{ url_for('auth.register') }}"><i                 + class="fas fa-user-plus"></i> 注册</a></li> -->
      520                              {% endif %}
      521                          </ul>
      522                      </li>

● Update(templates\location\location_import.html)
  ⎿  File must be read first

  Read 1 file (ctrl+o to expand)

● Update(templates\location\location_import.html)
  ⎿  Added 1 line, removed 1 line
      108                              <li><a class="dropdown-item" href="{{ url_for('profile') }}">个人资料</a><
           /li>
      109                              <li><a class="dropdown-item" href="{{ url_for('settings.settings') }}">设                   置</a></li>
      110                              <li><hr class="dropdown-divider"></li>                                                 111 -                            <li><a class="dropdown-item" href="{{ url_for('logout') }}">退出登录</a></
          -li>
      111 +                            <li><a class="dropdown-item" href="{{ url_for('auth.logout') }}">退出登录<
          +/a></li>
      112                          </ul>
      113                      </li>
      114                  </ul>

● 所有模板中的 url_for 已更新。现在还需要在 auth 蓝图中添加 register 和 change_password 路由（这两个路由在旧 app.py
  中有但重构时被移除了）。

  Read 1 file (ctrl+o to expand)

● Update(blueprints\auth.py)
  ⎿  Added 57 lines
       64              db.session.rollback()
       65              flash(f'更新失败: {str(e)}', 'danger')
       66      return render_template('profile.html')
       67 +                                                                                                                    68 +
       69 +@auth_bp.route('/register', methods=['GET', 'POST'])                                                                70 +def register():
       71 +    if current_user.is_authenticated:
       72 +        return redirect(url_for('main.index'))
       73 +
       74 +    if request.method == 'POST':
       75 +        username = request.form.get('username')
       76 +        email = request.form.get('email')
       77 +        password = request.form.get('password')
       78 +        confirm_password = request.form.get('confirm_password')
       79 +
       80 +        if password != confirm_password:
       81 +            flash('两次输入的密码不一致', 'error')
       82 +            return render_template('register.html')
       83 +
       84 +        if db.session.query(User).filter_by(username=username).first():
       85 +            flash('用户名已存在', 'error')
       86 +            return render_template('register.html')
       87 +
       88 +        if db.session.query(User).filter_by(email=email).first():
       89 +            flash('邮箱已被注册', 'error')
       90 +            return render_template('register.html')
       91 +
       92 +        new_user = User(username=username, email=email, is_admin=False)
       93 +        new_user.set_password(password)
       94 +        db.session.add(new_user)
       95 +        db.session.commit()
       96 +
       97 +        flash('注册成功，请登录', 'success')
       98 +        return redirect(url_for('auth.login'))
       99 +
      100 +    return render_template('register.html')
      101 +
      102 +
      103 +@auth_bp.route('/change_password', methods=['GET', 'POST'])
      104 +@login_required
      105 +def change_password():
      106 +    if request.method == 'POST':
      107 +        current_password = request.form.get('current_password')
      108 +        new_password = request.form.get('new_password')
      109 +        confirm_password = request.form.get('confirm_password')
      110 +
      111 +        if not current_user.check_password(current_password):
      112 +            flash('当前密码不正确', 'danger')
      113 +        elif new_password != confirm_password:
      114 +            flash('两次输入的新密码不一致', 'danger')
      115 +        elif len(new_password) < 6:
      116 +            flash('新密码长度不能少于6位', 'danger')
      117 +        else:
      118 +            current_user.set_password(new_password)
      119 +            db.session.commit()
      120 +            flash('密码修改成功', 'success')
      121 +            return redirect(url_for('auth.profile'))
      122 +
      123 +    return render_template('change_password.html')

● Bash(cd "D:/asset" && python -m py_compile blueprints/auth.py && echo "OK")
  ⎿  OK

● 已修复。问题原因及修改：

  1. 模板中 url_for('login') 等旧引用 — 路由现属于 auth 蓝图，已将所有模板中的 url_for('login') →
  url_for('auth.login')，url_for('logout') → url_for('auth.logout')，共修改 3 个模板文件 8 处引用。                       2. 丢失的路由 — 旧 app.py 中的 /register 和 /change_password 路由在重构时被误删。已在 blueprints/auth.py
  中重新添加这两个路由。                                                                                                
✻ Cogitated for 53s

────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
> 以下是详细的架构缺陷分析与优化建议：
  一、架构缺陷分析                                                                                                        1. 任务功能冗余与冲突

  缺陷描述：系统中存在两个几乎功能重叠的定时任务，造成资源浪费和潜在的数据竞争。

  冗余 1：scheduler.py 中同时注册了 monitor_connections_job（来自 tasks.py，间隔120秒）和 link_monitor_job（来自
  link_monitor.py，间隔60秒）。
  tasks.py 中的 monitor_connections 检查 ConnectionPath 表。
  link_monitor.py 中的 check_all_links 也检查 ConnectionPath 表。
  两者逻辑相似（Ping + SNMP），但判定逻辑略有不同。如果它们同时运行，可能产生数据库锁冲突（都尝试更新同一行连
  接状态），或者导致告警日志重复生成。
  冗余 2：app.py 中启动了一个独立的 checker_thread 线程（check_topology_periodically），每隔3600秒检测拓扑。
  而 scheduler.py 中已经注册了 lldp_discovery_job（每1小时）和 link_health_check_job（每天3点）。
  这种“独立线程 +
  调度器”的混合架构，导致系统难以统一管理任务状态（如暂停、恢复、查看日志），且独立线程缺乏健壮的错误重试机制。

  2. 数据流转断层

  缺陷描述：tasks.py 中的接口流量采集任务是一个“生产者”，但系统缺少明确的“消费者”。

  poll_all_devices_interfaces 任务将采集的数据推送到 Redis 队列 (interface_monitor:queue)。
  但在提供的代码中，并未发现任何代码块从这个队列读取数据并进行持久化（保存到数据库）。
  后果：Redis 队列会无限膨胀，最终导致内存溢出，且采集的流量数据无法用于历史图表展示。

  3. SNMP 技术栈不一致

  缺陷描述：代码中存在两种截然不同的 SNMP 实现方式，风格混乱。

  方式 A：utils.py 中定义了基于系统命令（subprocess 调用 snmpget/snmpwalk）的工具函数。注释中明确说明是为了替代
  pysnmp。
  方式 B：tasks.py 中却依然引入了 from pysnmp.entity.rfc3413.oneliner import cmdgen，并在
  snmp_discover_interfaces_real 中使用纯 Python 库实现。
  后果：这导致代码库中存在两套 OID 解析逻辑、两套超时控制机制，维护成本极高。且 pysnmp
  在高并发下容易产生阻塞或性能问题，与 subprocess 方案的性能特征也不同。

  4. 数据库操作瓶颈

  缺陷描述：在循环中频繁进行数据库提交操作。

  在 tasks.py 和 link_monitor.py 的检测循环中，经常出现 db.session.commit() 直接写在循环内部。
  例如在 check_all_links 中，每次检查完一条连接就 commit。
  后果：当并发检测大量设备（如20线程）时，频繁的磁盘 I/O 会导致数据库性能急剧下降，甚至锁死整个表。
  风险：缺乏统一的事务管理。如果任务中途失败，可能导致部分数据更新成功，部分失败，数据状态不一致。

  5. 线程池管理隐患

  缺陷描述：在定时任务内部临时创建 ThreadPoolExecutor，并未妥善处理线程池关闭。

  tasks.py 的 check_all_devices_status 中：with ThreadPoolExecutor(max_workers=5) as executor: ...。
  APScheduler 的后台任务本身已经是线程执行的。如果在任务线程内再创建子线程池，且遇到任务超时被调度器强制终止，子线
  程池可能无法优雅关闭，导致僵尸线程或资源泄露。

  二、优化方案建议
  1. 整合调度任务架构

  优化目标：统一入口，消除冗余。

  移除独立线程：删除 app.py 中的 checker_thread，将其功能完全移交由 scheduler.py 管理。
  合并重叠任务：
  废弃 tasks.py 中的 monitor_connections_job。
  保留 link_monitor.py 中的 link_monitor_job（逻辑更完善，包含 LLDP 验证）。
  将 link_monitor.py 的检测间隔调整为 120秒，以平衡性能与实时性。

  2. 完善 Redis 数据消费机制

  优化目标：确保数据闭环，防止内存溢出。

  方案 A（推荐）：新增一个定时任务 save_interface_metrics_job，专门负责从 Redis 批量拉取数据并写入 MetricData
  表，写入成功后清理 Redis Key。
  方案 B：修改 poll_all_devices_interfaces，直接写入数据库（批量插入，如 db.session.bulk_save_objects），移除
  Redis。除非数据量极大（千台设备+高频采集），否则直接入库更可靠。

  3. 统一 SNMP 工具库

  优化目标：降低维护成本，统一性能表现。

  策略：全面清理 pysnmp 的残留导入。
  保留 utils.py 中基于 subprocess 的实现方案。该方案虽然每次调用有进程创建开销，但稳定性极高，且不会因某个 SNMP
  请求卡死而拖垮整个 Python 进程。
  或者引入异步 SNMP 库（如 asyncsnmp 或使用 asyncio 包装 subprocess），提升并发性能。

  4. 数据库批量操作优化

  优化目标：减少 I/O，提升吞吐量。

  修改逻辑：将循环内的 db.session.commit() 移除，改为在循环中只修改对象状态。
  批量提交：在循环结束后或每隔 N 条记录（如每 50 条），执行一次 db.session.commit()。
  示例代码改造：

  # 优化前
  for conn in connections:
  update_connection(conn)
  db.session.commit() # 每次提交

  # 优化后
  count = 0
  for conn in connections:
  update_connection(conn)
  count += 1
  if count % 50 == 0:
  db.session.commit() # 批量提交
  db.session.commit() # 最后提交剩余部分

  5. 代码结构重构

  优化目标：解耦，易维护。

  拆分 utils.py：该文件过于臃肿（1700+行）。
  snmp_utils.py：处理 SNMP 交互。
  network_utils.py：处理 Ping、IP解析。
  excel_utils.py：处理 Excel 导入导出。
  metric_utils.py：处理 OID 映射和指标采集。
  统一数据模型：
  检查并清理 InterfaceRelationship 与 ConnectionPath 的关系。建议统一使用 ConnectionPath
  作为核心拓扑模型，废弃或迁移 InterfaceRelationship，避免“双轨制”数据模型。

  6. 配置参数化

  优化目标：提升灵活性。

  将硬编码的参数移至数据库配置表 (SystemConfig)：
  Ping 超时时间 (timeout=2)。
  SNMP Community (public)。
  线程池大小 (max_workers=20)。
  任务检测间隔 (60秒)。
  使得管理员可以通过 Web UI 动态调整监控灵敏度，无需重启应用。



  2. 链路监控职责分裂（最严重）
  模块

  职责
  tasks.py::monitor_connections

  连接状态
  link_monitor.py::check_single_link

  链路状态
                                                                                                                          又一份链路判断逻辑                                                                                                      ✅ 现实问题：
                                                                                                                              两套链路判定逻辑                                                                                                        两套 SNMP 封装                                                                                                          告警可能重复                                                                                                            新人根本不知道该改哪一处                                                                                            优化如下：                                                                                                              ✅ 1. 合并链路监控（最重要）
  动作：                                                                                                                
      删除 tasks.py::monitor_connections
      删除 tasks.py::check_single_connection
      统一使用 monitoring/link/


  三、优化后的架构图示（文字版）

  调度核心

      BackgroundScheduler (单例模式)

  任务队列

      设备状态检测任务 (每5分钟)
          作用：Ping/SNMP 检测，更新 Device.status
          优化：批量提交数据库

      链路状态监控任务 (每120秒) - *合并后*
          作用：检测 ConnectionPath，生成告警
          逻辑：Ping + SNMP Port Status + LLDP Fallback

      指标采集任务 (每30秒)
          作用：采集 CPU/Memory
          存储：直接批量写入数据库

      拓扑发现任务 (每1小时)
          作用：LLDP Walk，更新拓扑结构

  数据流向
  设备 -> SNMP/Ping -> 定时任务 -> 数据库
  -> 告警系统

  通过以上优化，系统将具备更好的一致性、稳定性和扩展性，能够支撑更大规模的设备监控需求。

● 好的，我仔细阅读了你的架构分析。问题很清晰，按你的优先级，先从链路监控合并和调度器整合开始。

  Read 6 files (ctrl+o to expand)

● 全面了解了问题。根据你的优先级，逐步实施优化。

● 开始实施。先处理链路监控合并 + 调度器精简 + 批量提交优化。

● Update(utils\tasks.py)
  ⎿  Added 1 line, removed 368 lines
      254          return None
      255
      256
      257 -def get_neighbor_info_via_lldp(device, port_name):
      258 -    """
      259 -    通过 LLDP 获取邻居设备信息
      260 -    返回: (neighbor_ifindex, neighbor_port_name, neighbor_device_name)                                             261 -    """
      262 -    try:                                                                                                           263 -        ip = device.management_ip or device.ip_address
      264 -        if not ip:
      265 -            return None, None, None
      266 -
      267 -        community = getattr(device, 'snmp_community', 'public')
      268 -        version = getattr(device, 'snmp_version', '2c')
      269 -
      270 -        # LLDP MIB OIDs
      271 -        local_port_entries = snmp_walk(ip, '1.0.8802.1.1.2.1.4.1.1.3', community, version=version, tim
          -eout=3)
      272 -        port_id_entries = snmp_walk(ip, '1.0.8802.1.1.2.1.4.1.1.7', community, version=version, timeou
          -t=3)
      273 -        sys_name_entries = snmp_walk(ip, '1.0.8802.1.1.2.1.4.1.1.9', community, version=version, timeo
          -ut=3)
      274 -
      275 -        if not local_port_entries:
      276 -            logger.debug(f"设备 {ip} 未返回 LLDP 信息")
      277 -            return None, None, None
      278 -
      279 -        local_port_map = {}
      280 -        for oid, value in local_port_entries:
      281 -            idx = oid.split('.')[-1]
      282 -            local_port_map[idx] = str(value).strip('"')
      283 -
      284 -        port_id_map = {}
      285 -        for oid, value in port_id_entries:
      286 -            idx = oid.split('.')[-1]
      287 -            port_id_map[idx] = str(value).strip('"')
      288 -
      289 -        sys_name_map = {}
      290 -        for oid, value in sys_name_entries:
      291 -            idx = oid.split('.')[-1]
      292 -            sys_name_map[idx] = str(value).strip('"')
      293 -
      294 -        logger.debug(f"LLDP 邻居数量: {len(local_port_map)}")
      295 -
      296 -        for idx, local_port in local_port_map.items():
      297 -            if port_name in local_port or local_port in port_name:
      298 -                neighbor_port = port_id_map.get(idx)
      299 -                neighbor_device = sys_name_map.get(idx)
      300 -
      301 -                logger.debug(f"找到匹配的邻居: local_port={local_port}, neighbor_port={neighbor_port}"
          -)
      302 -
      303 -                if neighbor_port:
      304 -                    neighbor_ifindex = None
      305 -                    neighbor_dev = Device.query.filter(
      306 -                        Device.name.ilike(f'%{neighbor_device}%')
      307 -                    ).first()
      308 -
      309 -                    if neighbor_dev:
      310 -                        logger.debug(f"找到邻居设备: {neighbor_dev.name} (ID: {neighbor_dev.id})")
      311 -                        neighbor_ip = neighbor_dev.management_ip or neighbor_dev.ip_address
      312 -                        if neighbor_ip:
      313 -                            neighbor_ifindex = get_ifindex_via_snmp(neighbor_dev, neighbor_port)
      314 -                            if neighbor_ifindex:
      315 -                                logger.debug(f"通过 SNMP 获取邻居端口 ifindex: {neighbor_ifindex}")
      316 -                            else:
      317 -                                neighbor_interface = Interface.query.filter_by(
      318 -                                    device_id=neighbor_dev.id,
      319 -                                    name=neighbor_port
      320 -                                ).first()
      321 -                                if neighbor_interface and neighbor_interface.ifindex:
      322 -                                    neighbor_ifindex = neighbor_interface.ifindex
      323 -                                    logger.debug(f"通过数据库获取邻居端口 ifindex: {neighbor_ifindex}"
          -)
      324 -
      325 -                    return neighbor_ifindex, neighbor_port, neighbor_device
      326 -
      327 -        logger.debug("未找到匹配的 LLDP 邻居")
      328 -        return None, None, None
      329 -
      330 -    except Exception as e:
      331 -        logger.debug(f"LLDP 查询异常: {e}")
      332 -        return None, None, None
      257
      258 +# ==================== 连接状态更新 ====================
      259
      335 -# ==================== 连接状态检测 ====================
      260
      337 -def check_single_connection(connection) -> Tuple[str, Dict[str, Any]]:
      338 -    """
      339 -    检查单个连接的状态，综合 SNMP 和 ping 结果判定
      340 -
      341 -    状态判定逻辑：
      342 -    1. active: 两端设备可达，且端口状态确认 up
      343 -    2. degraded: 设备可达但端口状态无法确认（SNMP 失败或端口信息不完整）
      344 -    3. down: 设备不可达或端口确认 down
      345 -
      346 -    Returns:
      347 -        Tuple[str, Dict[str, Any]]: (状态字符串, 详情字典)
      348 -    """
      349 -    start_time = time.time()
      350 -    details = {
      351 -        'connection_id': connection.id,
      352 -        'snmp_checks': [],
      353 -        'errors': [],
      354 -        'timestamp': datetime.utcnow().isoformat(),
      355 -        'debug_info': []
      356 -    }
      357 -
      358 -    def debug(msg, data=None):
      359 -        log_msg = f"[DEBUG] {msg}"
      360 -        if data:
      361 -            log_msg += f" | data={data}"
      362 -        logger.info(log_msg)
      363 -        details['debug_info'].append({'msg': msg, 'data': data, 'time': datetime.utcnow().isoformat()}
          -)
      364 -
      365 -    def error(msg, data=None):
      366 -        log_msg = f"[ERROR] {msg}"
      367 -        if data:
      368 -            log_msg += f" | data={data}"
      369 -        logger.error(log_msg)
      370 -        details['errors'].append({'msg': msg, 'data': data, 'time': datetime.utcnow().isoformat()})
      371 -
      372 -    def warn(msg, data=None):
      373 -        log_msg = f"[WARN] {msg}"
      374 -        if data:
      375 -            log_msg += f" | data={data}"
      376 -        logger.warning(log_msg)
      377 -        details['errors'].append({'msg': msg, 'data': data, 'time': datetime.utcnow().isoformat()})
      378 -
      379 -    def parse_snmp_status(val):
      380 -        """解析 SNMP 状态值（支持整数或字符串）"""
      381 -        if val is None:
      382 -            return None
      383 -        if isinstance(val, int):
      384 -            return val
      385 -        if isinstance(val, str):
      386 -            lower_val = val.lower().strip()
      387 -            if lower_val in ('1', 'up'):
      388 -                return 1
      389 -            elif lower_val in ('2', 'down'):
      390 -                return 2
      391 -        return None
      392 -
      393 -    def is_valid_port(port_obj):
      394 -        """检查端口是否有效"""
      395 -        if not port_obj:
      396 -            return False
      397 -        name = port_obj.name.lower().strip()
      398 -        if name in ('unknown', '', 'null', 'none'):
      399 -            return False
      400 -        if ':' in name and len(name) > 10:
      401 -            return False
      402 -        return True
      403 -
      404 -    try:
      405 -        debug(f"开始检查连接 {connection.id}")
      406 -
      407 -        # ---------- 完整性校验 ----------
      408 -        if not connection.source_device_id or not connection.target_device_id:
      409 -            error("缺少设备ID")
      410 -            return 'unknown', details
      411 -
      412 -        if not connection.source_interface_id or not connection.target_interface_id:
      413 -            error("缺少接口ID")
      414 -            return 'unknown', details
      415 -
      416 -        # ---------- 获取设备和接口对象 ----------
      417 -        source_device = Device.query.get(connection.source_device_id)
      418 -        target_device = Device.query.get(connection.target_device_id)
      419 -        if not source_device or not target_device:
      420 -            error("设备不存在")
      421 -            return 'unknown', details
      422 -
      423 -        source_port = Interface.query.get(connection.source_interface_id)
      424 -        target_port = Interface.query.get(connection.target_interface_id)
      425 -        if not source_port or not target_port:
      426 -            error("端口不存在")
      427 -            return 'unknown', details
      428 -
      429 -        debug("设备与端口获取成功", {
      430 -            'source_device_name': source_device.name,
      431 -            'target_device_name': target_device.name,
      432 -            'source_port_name': source_port.name,
      433 -            'target_port_name': target_port.name
      434 -        })
      435 -
      436 -        # ---------- 获取管理IP ----------
      437 -        source_ip = source_device.management_ip or source_device.ip_address
      438 -        target_ip = target_device.management_ip or target_device.ip_address
      439 -
      440 -        if not source_ip:
      441 -            warn(f"设备 {source_device.id} 缺少可用IP")
      442 -        if not target_ip:
      443 -            warn(f"设备 {target_device.id} 缺少可用IP")
      444 -
      445 -        debug("获取设备IP", {'source_ip': source_ip, 'target_ip': target_ip})
      446 -
      447 -        # ---------- 补全缺失的 ifindex ----------
      448 -        if not source_port.ifindex and source_ip:
      449 -            debug(f"尝试补全源端口 ifindex: {source_port.name}")
      450 -            new_ifindex = get_ifindex_via_snmp(source_device, source_port.name)
      451 -            if new_ifindex:
      452 -                source_port.ifindex = new_ifindex
      453 -                db.session.add(source_port)
      454 -                db.session.commit()
      455 -                logger.info(f"为接口 {source_port.name} 补全 ifindex={new_ifindex}")
      456 -
      457 -        if not target_port.ifindex:
      458 -            debug(f"尝试补全目标端口 ifindex: {target_port.name}")
      459 -
      460 -            if target_ip:
      461 -                new_ifindex = get_ifindex_via_snmp(target_device, target_port.name)
      462 -                if new_ifindex:
      463 -                    target_port.ifindex = new_ifindex
      464 -                    db.session.add(target_port)
      465 -                    db.session.commit()
      466 -                    logger.info(f"为接口 {target_port.name} 补全 ifindex={new_ifindex}")
      467 -
      468 -            if not target_port.ifindex and source_ip:
      469 -                debug(f"尝试通过 LLDP 从源端获取目标端口信息")
      470 -                neighbor_ifindex, neighbor_port, neighbor_device = get_neighbor_info_via_lldp(
      471 -                    source_device, source_port.name
      472 -                )
      473 -
      474 -                if neighbor_ifindex and neighbor_port:
      475 -                    target_port.ifindex = neighbor_ifindex
      476 -                    target_port.name = neighbor_port
      477 -                    db.session.add(target_port)
      478 -                    db.session.commit()
      479 -                    logger.info(f"通过 LLDP 更新目标端口: ifindex={neighbor_ifindex}, name={neighbor_p
          -ort}")
      480 -
      481 -        # ---------- SNMP 端口状态获取 ----------
      482 -        source_status = None
      483 -        if source_port.ifindex and source_ip:
      484 -            source_oid = f'1.3.6.1.2.1.2.2.1.8.{source_port.ifindex}'
      485 -            try:
      486 -                raw = snmp_get_with_timeout(
      487 -                    ip=source_ip,
      488 -                    community=source_device.snmp_community or 'public',
      489 -                    version=source_device.snmp_version or '2c',
      490 -                    oid=source_oid,
      491 -                    timeout=3
      492 -                )
      493 -                source_status = parse_snmp_status(raw)
      494 -                debug(f"源端口状态: {source_status}")
      495 -            except Exception as e:
      496 -                warn(f"源端口 SNMP 查询失败: {e}")
      497 -
      498 -        target_status = None
      499 -        if target_port.ifindex and target_ip:
      500 -            target_oid = f'1.3.6.1.2.1.2.2.1.8.{target_port.ifindex}'
      501 -            try:
      502 -                raw = snmp_get_with_timeout(
      503 -                    ip=target_ip,
      504 -                    community=target_device.snmp_community or 'public',
      505 -                    version=target_device.snmp_version or '2c',
      506 -                    oid=target_oid,
      507 -                    timeout=3
      508 -                )
      509 -                target_status = parse_snmp_status(raw)
      510 -                debug(f"目标端口状态: {target_status}")
      511 -            except Exception as e:
      512 -                warn(f"目标端口 SNMP 查询失败: {e}")
      513 -
      514 -        # ---------- 端口有效性检查 ----------
      515 -        src_port_valid = is_valid_port(source_port)
      516 -        tgt_port_valid = is_valid_port(target_port)
      517 -        debug(f"端口有效性检查: source={src_port_valid}, target={tgt_port_valid}")
      518 -
      519 -        # ---------- 设备可达性检测 ----------
      520 -        debug("执行设备可达性检测...")
      521 -        src_reachable = False
      522 -        tgt_reachable = False
      523 -
      524 -        if source_ip:
      525 -            src_reachable = ping_device(source_ip, timeout=3, retries=2)
      526 -            debug(f"Ping source {source_ip}: {src_reachable}")
      527 -
      528 -        if target_ip:
      529 -            tgt_reachable = ping_device(target_ip, timeout=3, retries=2)
      530 -            debug(f"Ping target {target_ip}: {tgt_reachable}")
      531 -
      532 -        # ---------- 状态判定逻辑 ----------
      533 -        status = 'unknown'
      534 -
      535 -        if not src_reachable and not tgt_reachable:
      536 -            status = 'down'
      537 -            details['reason'] = 'both devices unreachable'
      538 -            debug("两端设备都不可达 → down")
      539 -
      540 -        elif not src_reachable or not tgt_reachable:
      541 -            if src_reachable and not tgt_reachable:
      542 -                if source_status == 1:
      543 -                    status = 'down'
      544 -                    details['reason'] = 'source reachable, target unreachable'
      545 -                else:
      546 -                    status = 'down'
      547 -                    details['reason'] = 'source reachable but port not confirmed up'
      548 -            elif tgt_reachable and not src_reachable:
      549 -                if target_status == 1:
      550 -                    status = 'down'
      551 -                    details['reason'] = 'target reachable, source unreachable'
      552 -                else:
      553 -                    status = 'down'
      554 -                    details['reason'] = 'target reachable but port not confirmed up'
      555 -            else:
      556 -                status = 'down'
      557 -                details['reason'] = 'one device unreachable'
      558 -            debug(f"一端设备不可达 → down")
      559 -
      560 -        else:
      561 -            debug("两端设备都可达，检查端口状态...")
      562 -
      563 -            if source_status is not None and target_status is not None:
      564 -                if source_status == 1 and target_status == 1:
      565 -                    status = 'active'
      566 -                    details['reason'] = 'both ports up via SNMP'
      567 -                    debug("两端端口都 up → active")
      568 -                elif source_status == 1 or target_status == 1:
      569 -                    if source_status == 1:
      570 -                        if target_status == 2:
      571 -                            status = 'down'
      572 -                            details['reason'] = 'source port up, target port down'
      573 -                        elif tgt_port_valid:
      574 -                            status = 'degraded'
      575 -                            details['reason'] = 'source port up, target status unknown'
      576 -                        else:
      577 -                            status = 'down'
      578 -                            details['reason'] = 'source port up, target invalid'
      579 -                    else:
      580 -                        if source_status == 2:
      581 -                            status = 'down'
      582 -                            details['reason'] = 'target port up, source port down'
      583 -                        elif src_port_valid:
      584 -                            status = 'degraded'
      585 -                            details['reason'] = 'target port up, source status unknown'
      586 -                        else:
      587 -                            status = 'down'
      588 -                            details['reason'] = 'target port up, source invalid'
      589 -                    debug(f"仅一端端口 up → {status}")
      590 -                else:
      591 -                    status = 'down'
      592 -                    details['reason'] = 'both ports down via SNMP'
      593 -                    debug("两端端口都 down → down")
      594 -
      595 -            elif source_status is not None or target_status is not None:
      596 -                if source_status == 1:
      597 -                    status = 'degraded' if tgt_port_valid else 'down'
      598 -                    details['reason'] = 'source port up, target SNMP failed'
      599 -                elif target_status == 1:
      600 -                    status = 'degraded' if src_port_valid else 'down'
      601 -                    details['reason'] = 'target port up, source SNMP failed'
      602 -                else:
      603 -                    status = 'down'
      604 -                    details['reason'] = 'port confirmed down via SNMP'
      605 -                debug(f"仅一端 SNMP 成功 → {status}")
      606 -
      607 -            else:
      608 -                if src_port_valid and tgt_port_valid:
      609 -                    status = 'degraded'
      610 -                    details['reason'] = 'both reachable, valid ports, SNMP failed'
      611 -                else:
      612 -                    status = 'down'
      613 -                    details['reason'] = 'invalid ports, SNMP failed'
      614 -                debug(f"两端 SNMP 都失败 → {status}")
      615 -
      616 -        elapsed_time = time.time() - start_time
      617 -        details['processing_time'] = f"{elapsed_time:.2f}s"
      618 -        details['final_status'] = status
      619 -        debug(f"检查完成，最终状态: {status}, 耗时: {elapsed_time:.2f}s")
      620 -
      621 -        return status, details
      622 -
      623 -    except Exception as e:
      624 -        error(f"检查连接 {connection.id} 未捕获异常: {e}")
      625 -        return 'unknown', details
      626 -
      627 -
      261  def update_connection_status(interface):
      262      """
      263      更新与该接口相关的所有连接的状态

  Searched for 1 pattern, read 1 file (ctrl+o to expand)

● Update(utils\tasks.py)
  ⎿  Added 9 lines, removed 5 lines
      263      更新与该接口相关的所有连接的状态
      264      当接口状态发生变化时调用
      265      """
      266 +    from tasks.link_monitor import LinkMonitor
      267 +    monitor = LinkMonitor()
      268 +                                                                                                                   269      connections = ConnectionPath.query.filter(
      270          (ConnectionPath.source_interface_id == interface.id) |                                                     271          (ConnectionPath.target_interface_id == interface.id)
      272      ).all()
      270 -
      273 +
      274      if not connections:
      275          connections = ConnectionPath.query.filter(
      276              (ConnectionPath.source_device_id == interface.device_id) &
     ...
      288      updated = 0
      289      for conn in connections:
      290          try:
      288 -            status, _ = check_single_connection(conn)
      289 -            if conn.link_status != status:
      291 +            result = monitor.check_single_link(conn)
      292 +            new_status = result['status']
      293 +            if conn.link_status != new_status:
      294                  old_status = conn.link_status
      291 -                conn.link_status = status
      295 +                conn.link_status = new_status
      296                  conn.updated_at = datetime.utcnow()
      293 -                logger.info(f"连接 {conn.id} 状态变更: {old_status} → {status}")
      297 +                logger.info(f"连接 {conn.id} 状态变更: {old_status} → {new_status}")
      298                  updated += 1
      299          except Exception as e:
      300              logger.error(f"更新连接 {conn.id} 状态失败: {e}")

  Read 1 file (ctrl+o to expand)

● Update(utils\tasks.py)
  ⎿  Removed 150 lines
      588          logger.info(f"总耗时: {task_elapsed:.2f}秒")
      589
      590
      591 -# ==================== 连接监控任务 ====================
      591
      593 -def monitor_connections(app):                                                                                      594 -    """
      595 -    监控所有连接的状态                                                                                             596 -    """
      597 -    logger.info(f"[Monitor] 监控任务开始执行")
      598 -    start_time = time.time()
      599 -
      600 -    with app.app_context():
      601 -        try:
      602 -            connections = ConnectionPath.query.filter(
      603 -                ConnectionPath.link_status.in_(['active', 'degraded', 'unknown', 'down'])
      604 -            ).all()
      605 -
      606 -            logger.info(f"[Monitor] 查询到 {len(connections)} 条连接")
      607 -
      608 -            if not connections:
      609 -                return
      610 -
      611 -            updated_count = 0
      612 -            failed_count = 0
      613 -            processed_count = 0
      614 -            incomplete_count = 0
      615 -
      616 -            for conn in connections:
      617 -                processed_count += 1
      618 -                src_dev = Device.query.get(conn.source_device_id)
      619 -                tgt_dev = Device.query.get(conn.target_device_id)
      620 -                src_name = src_dev.name if src_dev else f"设备{conn.source_device_id}"
      621 -                tgt_name = tgt_dev.name if tgt_dev else f"设备{conn.target_device_id}"
      622 -
      623 -                logger.debug(f"[Monitor] 处理连接 {conn.id}: {src_name} {conn.source_port} <-> {tgt_na
          -me} {conn.target_port} (当前状态: {conn.link_status})")
      624 -
      625 -                # 完整性检查
      626 -                if not conn.source_device_id or not conn.target_device_id:
      627 -                    logger.warning(f"[Monitor] 连接 {conn.id} 缺少设备ID，跳过")
      628 -                    incomplete_count += 1
      629 -                    continue
      630 -
      631 -                # 补全接口
      632 -                if not conn.source_interface_id:
      633 -                    src_iface = Interface.query.filter_by(
      634 -                        device_id=conn.source_device_id,
      635 -                        name=conn.source_port
      636 -                    ).first()
      637 -                    if not src_iface:
      638 -                        src_iface = Interface(
      639 -                            device_id=conn.source_device_id,
      640 -                            name=conn.source_port,
      641 -                            type='unknown',
      642 -                            oper_status='unknown'
      643 -                        )
      644 -                        db.session.add(src_iface)
      645 -                        db.session.flush()
      646 -                        logger.info(f"[Monitor] 为设备 {conn.source_device_id} 自动创建接口 {conn.sour
          -ce_port}")
      647 -                    conn.source_interface_id = src_iface.id
      648 -
      649 -                if not conn.target_interface_id:
      650 -                    tgt_iface = Interface.query.filter_by(
      651 -                        device_id=conn.target_device_id,
      652 -                        name=conn.target_port
      653 -                    ).first()
      654 -                    if not tgt_iface:
      655 -                        tgt_iface = Interface(
      656 -                            device_id=conn.target_device_id,
      657 -                            name=conn.target_port,
      658 -                            type='unknown',
      659 -                            oper_status='unknown'
      660 -                        )
      661 -                        db.session.add(tgt_iface)
      662 -                        db.session.flush()
      663 -                        logger.info(f"[Monitor] 为设备 {conn.target_device_id} 自动创建接口 {conn.targ
          -et_port}")
      664 -                    conn.target_interface_id = tgt_iface.id
      665 -
      666 -                try:
      667 -                    current_status, details = check_single_connection(conn)
      668 -                    logger.debug(f"[Monitor] 连接 {conn.id} 检测结果: {current_status}")
      669 -
      670 -                    if current_status is None:
      671 -                        logger.warning(f"[Monitor] 连接 {conn.id} 状态检查失败（返回None）")
      672 -                        failed_count += 1
      673 -                        continue
      674 -
      675 -                except Exception as e:
      676 -                    logger.error(f"[Monitor] 调用 check_single_connection 异常: {e}", exc_info=True)
      677 -                    failed_count += 1
      678 -                    continue
      679 -
      680 -                old_status = conn.link_status
      681 -                if current_status != old_status:
      682 -                    conn.link_status = current_status
      683 -                    conn.updated_at = datetime.utcnow()
      684 -
      685 -                    log_level = 'error' if current_status == 'down' else 'warning' if current_status i
          -n ['unknown', 'degraded'] else 'info'
      686 -                    log_message = f"{src_name} {conn.source_port} <-> {tgt_name} {conn.target_port} 状
          -态变更: {old_status} -> {current_status}"
      687 -                    details_data = {
      688 -                        'connection_id': conn.id,
      689 -                        'old_status': old_status,
      690 -                        'new_status': current_status,
      691 -                        'source_device_id': conn.source_device_id,
      692 -                        'target_device_id': conn.target_device_id,
      693 -                        'source_interface_id': conn.source_interface_id,
      694 -                        'target_interface_id': conn.target_interface_id,
      695 -                        'timestamp': datetime.utcnow().isoformat()
      696 -                    }
      697 -                    if details:
      698 -                        details_data['status_detail'] = str(details)
      699 -
      700 -                    try:
      701 -                        sys_log = SystemLog(
      702 -                            level=log_level,
      703 -                            module='monitor',
      704 -                            message=log_message,
      705 -                            user_id=None,
      706 -                            ip_address=None,
      707 -                            details=json.dumps(details_data, ensure_ascii=False)
      708 -                        )
      709 -                        db.session.add(sys_log)
      710 -                    except Exception as e:
      711 -                        logger.error(f"[Monitor] 记录系统日志失败: {e}")
      712 -
      713 -                    logger.info(f"[Monitor] {log_message}")
      714 -                    updated_count += 1
      715 -                else:
      716 -                    logger.debug(f"[Monitor] 连接 {conn.id} 状态未变: {current_status}")
      717 -
      718 -                if processed_count % 10 == 0:
      719 -                    try:
      720 -                        db.session.commit()
      721 -                        logger.debug(f"[Monitor] 已提交 {processed_count} 个连接")
╭─── Claude Code v2.1.126 ─────────────────────────────────────────────────────────────────────────────────────────────╮
│                                    │ Tips for getting started                                                        │
│            Welcome back!           │ Run /init to create a CLAUDE.md file with instructions for Claude               │
│                                    │ ─────────────────────────────────────────────────────────────────────────────── │
│               ▐▛███▜▌              │ What's new                                                                      │
│              ▝▜█████▛▘             │ The `/model` picker now lists models from your gateway's `/v1/models` endpoint… │
│                ▘▘ ▝▝               │ - Added `claude project purge [path]` to delete all Claude Code state for a pr… │
│                                    │ `--dangerously-skip-permissions` now bypasses prompts for writes to `.claude/`… │
│   Sonnet 4.6 · API Usage Billing   │ /release-notes for more                                                         │
│              D:\asset              │                                                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

✻ Conversation compacted (ctrl+o for history)

  ⎿  Read scheduler.py (324 lines)
  ⎿  Referenced file utils\tasks.py
  ⎿  Read blueprints\auth.py (124 lines)
  ⎿  Referenced file templates\location\location_import.html
  ⎿  Referenced file templates\base.html

  Read 1 file (ctrl+o to expand)

● Update(scheduler.py)
  ⎿  Removed 9 lines
       91      if scheduler.get_job(job_id):
       92          scheduler.remove_job(job_id)
       93
       94 -    scheduler.add_job(
       95 -        func=monitor_connections,
       96 -        args=[app],
       97 -        trigger=IntervalTrigger(seconds=120),
       98 -        id=job_id,
       99 -        replace_existing=True,                                                                                     100 -        max_instances=1
      101 -    )                                                                                                              102 -
       94      # =========== 监控指标采集任务 ===============
       95      job_id = 'collect_metrics_job'
       96      if scheduler.get_job(job_id):

● Update(scheduler.py)
  ⎿  Added 1 line, removed 1 line
      113      scheduler.add_job(
      114          func=run_link_monitor,
      115          args=[app],
      116 -        trigger=IntervalTrigger(seconds=60),  # 60秒检测一次链路状态
      116 +        trigger=IntervalTrigger(seconds=120),  # 120秒检测一次链路状态
      117          id=job_id,
      118          replace_existing=True,
      119          max_instances=1
                                                                                                                        ● Update(scheduler.py)
  ⎿  Removed 14 lines                                                                                                         133          max_instances=1
      134      )
      135
      136 -    # =========== 链路健康检查（每天凌晨3点） ===============
      137 -    job_id = 'link_health_check_job'
      138 -    if scheduler.get_job(job_id):
      139 -        scheduler.remove_job(job_id)
      140 -
      141 -    scheduler.add_job(
      142 -        func=run_link_monitor,
      143 -        args=[app],
      144 -        trigger=CronTrigger(hour=3, minute=0),  # 每天凌晨3点执行
      145 -        id=job_id,
      146 -        replace_existing=True,
      147 -        max_instances=1
      148 -    )
      149 -
      136      # 启动调度器
      137      scheduler.start()
      138      logger.info("APScheduler 已启动，所有定时任务已添加")

  Read 1 file (ctrl+o to expand)

● Update(scheduler.py)
  ⎿  Removed 5 lines
      86          max_instances=1
      87      )
      88
      89 -    # =========== 轮询检测设备接口连接状态 ===============
      90 -    job_id = 'monitor_connections_job'
      91 -    if scheduler.get_job(job_id):                                                                                   92 -        scheduler.remove_job(job_id)
      93 -                                                                                                                    89      # =========== 监控指标采集任务 ===============
      90      job_id = 'collect_metrics_job'
      91      if scheduler.get_job(job_id):

  Read 2 files (ctrl+o to expand)

● Now let me remove the independent checker_thread from app.py and the now-unused check_topology_periodically from
  app_init.py.

● Update(app.py)
  ⎿  Removed 1 line
      2  Application factory and entry point.
      3  """
      4  import os
      5 -import threading
      5  import atexit
      6  from datetime import datetime
      7

● Update(app.py)                                                                                                          ⎿  Added 1 line, removed 1 line
      14  from models.models import User                                                                                      15  from scheduler import configure_scheduler, shutdown_scheduler
      16  from tasks.link_monitor import init_link_monitor
      17 -from app_init import init_database, check_topology_periodically
      17 +from app_init import init_database
      18
      19  # 1. 应用初始化
      20  app = Flask(__name__)
                                                                                                                        ● Update(app.py)
  ⎿  Removed 9 lines                                                                                                          134  # 14. 应用启动入口
      135  if __name__ == '__main__':
      136      init_database(app)
      137 -
      138 -    checker_thread = threading.Thread(
      139 -        target=check_topology_periodically,
      140 -        args=(app, 3600),                                                                                          141 -        daemon=True
      142 -    )                                                                                                              143 -    checker_thread.start()
      144 -    app.logger.info("拓扑检测线程已启动")
      145 -
      137      init_link_monitor(app)
      138      configure_scheduler(app)
      139

  Searched for 1 pattern (ctrl+o to expand)

● No other code references it. Let me remove it from app_init.py.

● Update(app_init.py)
  ⎿  Removed 66 lines
       82              db.session.rollback()
       83
       84          print("✅ 数据库初始化完成")
       85 -
       86 -                                                                                                                    87 -def check_topology_periodically(app, interval=3600):
       88 -    """Background thread for periodic topology checking."""                                                         89 -    with app.app_context():
       90 -        while True:
       91 -            try:
       92 -                active_rels = db.session.query(InterfaceRelationship).filter_by(status='active').all()
       93 -                for rel in active_rels:
       94 -                    try:
       95 -                        local_device = db.session.get(Device, rel.local_device_id)
       96 -                        if not local_device:
       97 -                            continue
       98 -                        snmp_community = db.session.query(SystemConfig).filter_by(key='snmp_community'
          -).first()
       99 -                        if not snmp_community:
      100 -                            continue
      101 -                        scanner = SNMPScanner(local_device.management_ip, snmp_community.value)
      102 -
      103 -                        current_neighbors = []
      104 -                        if rel.discovery_protocol == 'LLDP':
      105 -                            current_neighbors = scanner.get_lldp_neighbors()
      106 -                        elif rel.discovery_protocol == 'CDP':
      107 -                            current_neighbors = scanner.get_cdp_neighbors()
      108 -
      109 -                        match = False
      110 -                        for neighbor in current_neighbors:
      111 -                            if (
      112 -                                neighbor['local_interface'] == rel.local_interface and
      113 -                                neighbor['remote_device_name'] == rel.remote_device_name and
      114 -                                neighbor['remote_interface'] == rel.remote_interface
      115 -                            ):
      116 -                                match = True
      117 -                                break
      118 -
      119 -                        if not match:
      120 -                            rel.status = 'inactive'
      121 -                            rel.updated_at = datetime.utcnow()
      122 -                            log = TopologyLog(
      123 -                                device_id=rel.local_device_id,
      124 -                                interface_relationship_id=rel.id,
      125 -                                log_type='error',
      126 -                                message=(
      127 -                                    f'接口{rel.local_interface}邻居关系异常：'
      128 -                                    f'原远端设备{rel.remote_device_name}({rel.remote_interface})，'
      129 -                                    f'当前无匹配邻居'
      130 -                                )
      131 -                            )
      132 -                            db.session.add(log)
      133 -                            log_operation(
      134 -                                'check', 'topology', rel.id,
      135 -                                f'{local_device.name}-{rel.local_interface}', '邻居关系异常'
      136 -                            )
      137 -                        else:
      138 -                            rel.status = 'active'
      139 -                    except Exception as e:
      140 -                        log = TopologyLog(
      141 -                            device_id=rel.local_device_id,
      142 -                            interface_relationship_id=rel.id,
      143 -                            log_type='warning',
      144 -                            message=f'检测接口{rel.local_interface}失败：{str(e)}'
      145 -                        )
      146 -                        db.session.add(log)
      147 -                db.session.commit()
      148 -            except Exception as e:
      149 -                app.logger.error(f"拓扑检测线程异常: {e}")
      150 -            time.sleep(interval)

  Read 1 file (ctrl+o to expand)

● Update(app_init.py)
  ⎿  Added 2 lines, removed 7 lines
       1 -import time
       2 -import threading
       3 -from datetime import datetime, timezone
       1  from sqlalchemy import text
       2
       3  from extensions import db                                                                                            7 -from models.models import User, Device, InterfaceRelationship, TopologyLog
       8 -from models.settings_models import  SystemConfig                                                                     9 -from utils.utils import log_operation
      10 -from snmp_scanner import SNMPScanner
       4 +from models.models import User
       5 +from models.settings_models import SystemConfig
       6
       7
       8  def init_database(app):

  Searched for 2 patterns, read 1 file (ctrl+o to expand)

● Let me refactor link_monitor.py for batch DB commits. The pattern: remove individual commits from
  update_connection_status, alert methods, and discover_links_via_lldp — commit once at the end of batch operations.

● Update(tasks\link_monitor.py)
  ⎿  Added 2 lines, removed 1 line
      413                      'target_status': 'unknown',
      414                      'elapsed': 0
      415                  })
      416 -
      416 +
      417 +        db.session.commit()
      418          return results
      419
      420      # ==================== 数据库更新 ====================

● Update(tasks\link_monitor.py)
  ⎿  Added 1 line, removed 4 lines
      443                  self.create_link_down_alert(connection, result)                                                    444              elif new_status == 'active' and old_status == 'down':
      445                  self.clear_link_down_alert(connection)                                                             446 -
      447 -            db.session.commit()
      448 -
      446 +
      447          connection.updated_at = datetime.now()
      450 -        db.session.commit()
      448
      449      def create_link_down_alert(self, connection: ConnectionPath, result: Dict):
      450          """创建链路断开告警"""

● Update(tasks\link_monitor.py)
  ⎿  Added 1 line, removed 3 lines
      460              existing.last_occurred = datetime.now()
      461              existing.occurrence_count += 1
      462              existing.message = f'链路 {connection.source_device.name}:{connection.source_port} -> {con
           nection.target_device.name}:{connection.target_port} 断开'
      463 -            db.session.commit()
      463              return
      465 -
      464 +
      465          alert = AlertEvent(
      466              device_id=connection.source_device_id,
      467              rule_id=None,
     ...
      475              notified=False
      476          )
      477          db.session.add(alert)
      479 -        db.session.commit()
      478
      479      def clear_link_down_alert(self, connection: ConnectionPath):
      480          """清除链路断开告警"""

● Update(tasks\link_monitor.py)
  ⎿  Removed 3 lines
      490              alert.status = 'resolved'
      491              alert.resolved_at = datetime.now()
      492              alert.resolved_note = '链路已恢复'
      493 -
      494 -        if alerts:
      495 -            db.session.commit()
      493
      494      # ==================== LLDP自动发现 ====================
      495

● Now the discover_links_via_lldp method — remove individual commits, add one at the end.

● Update(tasks\link_monitor.py)
  ⎿  Removed 2 lines
      560                          existing.discovery_protocol = 'LLDP'
      561                          existing.link_status = 'active'
      562                          existing.confidence = 100
      563 -                        db.session.commit()
      563                          result['updated_links'] += 1                                                               564                      else:
      565                          connection = ConnectionPath(                                                              ...
      577                              confidence=100
      578                          )
      579                          db.session.add(connection)
      581 -                        db.session.commit()
      580                          result['new_links'] += 1
      581
      582                      result['discovered_links'] += 1

  Read 1 file (ctrl+o to expand)

● Update(tasks\link_monitor.py)
  ⎿  Error editing file

  Read 1 file (ctrl+o to expand)

● Update(tasks\link_monitor.py)
  ⎿  Error editing file

● Bash(sed -n '589,594p' "D:/asset/tasks/link_monitor.py" | cat -A)
  ⎿              except Exception as e:$
                     result['errors'] += 1$
                     continue$
     … +3 lines (ctrl+o to expand)

● Update(tasks\link_monitor.py)
  ⎿  Error editing file

● Update(tasks\link_monitor.py)
  ⎿  Error editing file

● Bash(sed -n '589,593p' "D:/asset/tasks/link_monitor.py" | python -c "import sys; [print(repr(l)) for l in sys.stdin]")  ⎿  '            except Exception as e:\n'
     "                result['errors'] += 1\n"
     '                continue\n'
     … +2 lines (ctrl+o to expand)

● Bash(python -c "                                                                                                            with open('D:/asset/tasks/link_monitor.py', 'r') as f:…)
  ⎿  Error: Exit code 1
     Traceback (most recent call last):
       File "<string>", line 3, in <module>
     UnicodeDecodeError: 'gbk' codec can't decode byte 0x80 in position 40: illegal multibyte sequence

● Bash(python -c "                                                                                                            with open('D:/asset/tasks/link_monitor.py', 'r', encoding='utf-8') as f:…)
  ⎿  588: '                    \n'
     589: '            except Exception as e:\n'
     590: "                result['errors'] += 1\n"
     … +5 lines (ctrl+o to expand)

● Bash(python -c "                                                                                                            with open('D:/asset/tasks/link_monitor.py', 'r', encoding='utf-8') as f:…)
  ⎿  Old string count: 0
     Need more context

● Bash(python -c "                                                                                                            with open('D:/asset/tasks/link_monitor.py', 'r', encoding='utf-8') as f:…)
  ⎿  589: '            except Exception as e:'
     590: "                result['errors'] += 1"
     591: '                continue'
     … +3 lines (ctrl+o to expand)

● Update(tasks\link_monitor.py)
  ⎿  Error editing file

● Bash(python -c "                                                                                                            with open('D:/asset/tasks/link_monitor.py', 'r', encoding='utf-8') as f:…)
  ⎿  Target count: 1
     Done

  Searched for 3 patterns, read 2 files (ctrl+o to expand)

● Let me check what other files import from utils.py to understand the impact.

  Searched for 1 pattern, read 1 file (ctrl+o to expand)

● Now I have a complete picture of utils.py (1409 lines). I'll split it into three modules: snmp_utils.py,
  network_utils.py, excel_utils.py, then keep utils.py as a re-export shim.

● Write(utils\network_utils.py)
  ⎿  Wrote 300 lines to utils\network_utils.py
       1 # network_utils.py
       2 """Network utility functions: ping, IP validation, IP range parsing, device scanning."""
       3 import subprocess
       4 import socket
       5 import platform
       6 import select
       7 import time                                                                                                           8 import ipaddress
       9 import re                                                                                                            10 import concurrent.futures
     … +297 lines (ctrl+o to expand)

● Write(utils\snmp_utils.py)
  ⎿  Wrote 597 lines to utils\snmp_utils.py
      1 # snmp_utils.py
      2 """SNMP utility functions: get, walk, device info, interface discovery."""
      3 import subprocess
      4 import shutil
      5 import re
      6 import time
      7 import logging                                                                                                        8 from typing import List, Dict, Optional, Tuple
      9 from datetime import datetime                                                                                        … +598 lines (ctrl+o to expand)

● Write(utils\excel_utils.py)
  ⎿  Wrote 158 lines to utils\excel_utils.py
      1 # excel_utils.py
      2 """Excel import/export utilities for locations, devices, and templates."""
      3 import io
      4 import openpyxl
      5 import pandas as pd
      6 from datetime import datetime
      7 from openpyxl import Workbook                                                                                         8 from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
      9 from io import BytesIO                                                                                               … +150 lines (ctrl+o to expand)

  Read 1 file (ctrl+o to expand)

● Now let me convert utils.py to a re-export shim that imports from the new submodules.

● Let me fix the snmp_get return type in snmp_utils.py — I'd accidentally changed it to always return str. The original
  returned int/float when possible.

● Update(utils\snmp_utils.py)
  ⎿  Added 1 line, removed 1 line
      17
      18
      19  def snmp_get(ip: str, community: str, version: str, oid: str,
      20 -             timeout: int = SNMP_TIMEOUT) -> Optional[str]:
      20 +             timeout: int = SNMP_TIMEOUT):
      21      """通过系统 snmpget 命令执行 SNMP GET 返回: 值 (int/float/str) 或 None"""
      22      if community is None:
      23          community = 'public'
                                                                                                                        ● Update(utils\snmp_utils.py)
  ⎿  Added 2 lines, removed 2 lines                                                                                           40          if not output:
      41              return None
      42          try:
      43 -            return str(int(output))
      43 +            return int(output)
      44          except ValueError:
      45              try:
      46 -                return str(float(output))
      46 +                return float(output)
      47              except ValueError:
      48                  return output
      49      except subprocess.TimeoutExpired:

● Write(utils\utils.py)
  ⎿  Added 57 lines, removed 1344 lines
         1  # utils.py
         2 -# 完整版本，统一使用 snmpget 命令模式，并保留所有原有函数
         2 +"""
         3 +Unified re-export shim.
         4 +Functions have been split into specialized modules:
         5 +  - utils/network_utils.py  (ping, IP, network functions)
         6 +  - utils/snmp_utils.py     (SNMP get/walk, device info, interface discovery)
         7 +  - utils/excel_utils.py    (Excel import/export)
         8 +All imports from utils.utils continue to work.                                                                       9 +"""
        10                                                                                                                       4 -import subprocess
         5 -import shutil
         6 -import socket
         7 -import re
         8 -import struct
         9 -import pandas as pd
        10 -from datetime import datetime, timezone
        11 -import ipaddress
        12 -from typing import List, Dict, Any, Optional,Tuple
        13 -import re
        14 -from werkzeug.utils import secure_filename
        15 -from openpyxl import Workbook
        16 -from openpyxl.utils import get_column_letter
        17 -import json
        18 -from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        19 -from io import BytesIO
        20 -import platform
        21 -import select
        22 -import time
        23 -import openpyxl
        24 -import io
        25 -from pysnmp.entity.rfc3413.oneliner import cmdgen
        26 -from pysnmp.hlapi import nextCmd, SnmpEngine, CommunityData, UdpTransportTarget, ContextData, ObjectT
           -ype, ObjectIdentity
        27 -from flask import current_app
        11  import logging
        29 -import shutil
        12  import smtplib
        13  from email.mime.text import MIMEText
        32 -from datetime import datetime as dt
        14  from functools import wraps
        34 -# 本地模块导入
        35 -from auth import admin_required, log_operation
        36 -from extensions import db
        37 -from models import Device, Interface
        15
        39 -import concurrent.futures
        16 +from flask import current_app
        17 +from flask_login import current_user
        18
        41 -# ---------- 日志 ----------
        19 +from extensions import db
        20 +
        21  logger = logging.getLogger(__name__)
        43 -# APScheduler 的任务是独立线程执行的，默认没有进入 Flask 应用上下文，所以一用 current_app.logger 报错
        22
        23 +# ========== Re-exports from network_utils ==========
        24 +from utils.network_utils import (
        25 +    is_valid_ip, is_valid_mac, allowed_file,
        26 +    ping_device, ping_device_strict, ping_device_system,
        27 +    ping_device_socket, ping_device_tcp, batch_ping_devices,
        28 +    detect_device_reliable, calculate_checksum,
        29 +    parse_ip_range, scan_ip_range_worker, ip_range_import,
        30 +)
        31 +
        32 +# ========== Re-exports from snmp_utils ==========
        33 +from utils.snmp_utils import (
        34 +    SNMP_TIMEOUT, snmp_get, snmp_walk, walk_interfaces,
        35 +    snmp_get_device_info, scan_ip_with_snmp,
        36 +    OID_MAPPINGS, FALLBACK_OIDS,
        37 +    infer_device_type_from_snmp, update_device_snmp_info,
        38 +    snmp_discover_interfaces_real, save_discovered_interfaces,
        39 +    get_device_snmp_data, snmp_get_with_timeout,
        40 +)
        41 +
        42 +# ========== Re-exports from excel_utils ==========
        43 +from utils.excel_utils import (
        44 +    generate_location_template, export_locations_to_excel,
        45 +    import_locations_from_excel, export_devices_to_excel,
        46 +    generate_device_template, import_devices_from_excel,
        47 +)
        48 +
        49 +# ========== Functions that remain in utils.py ==========
        50 +
        51  def with_app_context(f):
        52      @wraps(f)
        53      def wrapper(*args, **kwargs):
        54          with current_app.app_context():
        55              return f(*args, **kwargs)
        56      return wrapper
        51 -# ---------- 常量 ----------
        52 -SNMP_TIMEOUT = 3          # 默认 SNMP 超时（秒）
        53 -DEFAULT_PING_TIMEOUT = 2
        57
        55 -# ---------- 通用工具 ----------
        56 -def is_valid_ip(ip_str):
        57 -    """验证IP地址格式"""
        58 -    try:
        59 -        ipaddress.ip_address(ip_str)
        60 -        return True
        61 -    except ValueError:
        62 -        return False
        58
        64 -def is_valid_mac(mac_str):
        65 -    """验证MAC地址格式"""
        66 -    mac_pattern = r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$'
        67 -    return re.match(mac_pattern, mac_str) is not None
        68 -
        69 -def allowed_file(filename, allowed_extensions=None):
        70 -    """检查文件扩展名是否允许"""
        71 -    if allowed_extensions is None:
        72 -        allowed_extensions = {'xlsx', 'xls', 'csv'}
        73 -    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions
        74 -
        75 -# ---------- Ping 检测 ----------
        76 -def ping_device(ip, timeout=2):
        77 -    """
        78 -    使用系统ping命令检测设备
        79 -    返回: (是否成功, 响应时间ms)
        80 -    """
        81 -    try:
        82 -        if platform.system().lower() == "windows":
        83 -            ping_cmd = ["ping", "-n", "1", "-w", str(timeout * 1000), ip]
        84 -        else:
        85 -            ping_cmd = ["ping", "-c", "1", "-W", str(timeout), ip]
        86 -        result = subprocess.run(ping_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_n
           -ewlines=True, timeout=timeout+1)
        87 -        if result.returncode == 0:
        88 -            output = result.stdout
        89 -            time_pattern = r"time[=<](\d+\.?\d*)\s*ms"
        90 -            match = re.search(time_pattern, output, re.IGNORECASE)
        91 -            if match:
        92 -                response_time = float(match.group(1))
        93 -                return True, response_time
        94 -            return True, 0
        95 -        return False, 0
        96 -    except Exception:
        97 -        return False, 0
        98 -
        99 -# utils/utils.py
       100 -
       101 -
       102 -def ping_device_strict(ip: str, timeout: float = 2.0, retries: int = 2) -> Tuple[bool, float]:
       103 -    """
       104 -    严格的Ping检测，使用多种方法并重试
       105 -    Returns: (success, response_time_ms)
       106 -    """
       107 -    # 尝试多种检测方法
       108 -    methods = [
       109 -        ('system_ping', ping_device_system),
       110 -        ('socket_ping', ping_device_socket),
       111 -        ('tcp_ping', ping_device_tcp)
       112 -    ]
       113 -
       114 -    best_response = float('inf')
       115 -
       116 -    for attempt in range(retries):
       117 -        for method_name, method_func in methods:
       118 -            try:
       119 -                success, response_time = method_func(ip, timeout)
       120 -                if success and response_time > 0:
       121 -                    if response_time < best_response:
       122 -                        best_response = response_time
       123 -                    return True, best_response
       124 -            except Exception:
       125 -                continue
       126 -
       127 -        # 重试前短暂等待
       128 -        if attempt < retries - 1:
       129 -            time.sleep(0.2)
       130 -
       131 -    return False, 0
       132 -
       133 -def ping_device_system(ip: str, timeout: float = 2.0) -> Tuple[bool, float]:
       134 -    """使用系统Ping命令"""
       135 -    try:
       136 -        # 根据操作系统选择参数
       137 -        param = '-n' if platform.system().lower() == 'windows' else '-c'
       138 -        timeout_param = '-w' if platform.system().lower() == 'windows' else '-W'
       139 -        timeout_value = str(int(timeout * 1000)) if platform.system().lower() == 'windows' else str(i
           -nt(timeout))
       140 -
       141 -        cmd = ['ping', param, '1', timeout_param, timeout_value, ip]
       142 -        result = subprocess.run(
       143 -            cmd,
       144 -            capture_output=True,
       145 -            text=True,
       146 -            timeout=timeout + 1
       147 -        )
       148 -
       149 -        if result.returncode == 0:
       150 -            # 解析响应时间
       151 -            output = result.stdout
       152 -            # Windows: 时间=1ms 或 时间=1ms
       153 -            # Linux: time=1.23 ms
       154 -            import re
       155 -            match = re.search(r'(?:时间|time)[=<](\d+\.?\d*)', output, re.IGNORECASE)
       156 -            if match:
       157 -                response_time = float(match.group(1))
       158 -                return True, response_time
       159 -            return True, 1.0
       160 -
       161 -        return False, 0
       162 -    except Exception:
       163 -        return False, 0
       164 -
       165 -def ping_device_socket(ip: str, timeout: float = 1.0) -> Tuple[bool, float]:
       166 -    """使用Socket连接检测（ICMP模拟）"""
       167 -    try:
       168 -        import socket
       169 -        import struct
       170 -        import time
       171 -
       172 -        # 创建原始套接字（需要root权限）
       173 -        # 简化为TCP连接检测
       174 -        return ping_device_tcp(ip, timeout)
       175 -    except Exception:
       176 -        return False, 0
       177 -
       178 -def ping_device_tcp(ip: str, timeout: float = 1.0, port: int = 80) -> Tuple[bool, float]:
       179 -    """TCP端口连通性检测"""
       180 -    try:
       181 -        start_time = time.time()
       182 -        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
       183 -        sock.settimeout(timeout)
       184 -        result = sock.connect_ex((ip, port))
       185 -        sock.close()
       186 -
       187 -        if result == 0:
       188 -            response_time = (time.time() - start_time) * 1000
       189 -            return True, response_time
       190 -        return False, 0
       191 -    except Exception:
       192 -        return False, 0
       193 -
       194 -def batch_ping_devices(ip_list: List[str], timeout: float = 1.0, max_workers: int = 20) -> Dict[str,
           -dict]:
       195 -    """
       196 -    批量并发Ping检测
       197 -    Returns: {ip: {'online': bool, 'response_time': float, 'method': str}}
       198 -    """
       199 -    results = {}
       200 -
       201 -    def ping_with_timeout(ip: str):
       202 -        try:
       203 -            # 使用多种方法
       204 -            success, response_time = ping_device_strict(ip, timeout, retries=1)
       205 -            return {
       206 -                'ip': ip,
       207 -                'online': success,
       208 -                'response_time': response_time,
       209 -                'method': 'strict_ping'
       210 -            }
       211 -        except Exception as e:
       212 -            return {
       213 -                'ip': ip,
       214 -                'online': False,
       215 -                'response_time': 0,
       216 -                'method': 'error',
       217 -                'error': str(e)
       218 -            }
       219 -
       220 -    # 使用更稳定的线程池
       221 -    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
       222 -        futures = {executor.submit(ping_with_timeout, ip): ip for ip in ip_list}
       223 -
       224 -        for future in concurrent.futures.as_completed(futures):
       225 -            ip = futures[future]
       226 -            try:
       227 -                result = future.result(timeout=timeout + 0.5)
       228 -                results[ip] = result
       229 -            except concurrent.futures.TimeoutError:
       230 -                results[ip] = {
       231 -                    'ip': ip,
       232 -                    'online': False,
       233 -                    'response_time': 0,
       234 -                    'method': 'timeout'
       235 -                }
       236 -            except Exception as e:
       237 -                results[ip] = {
       238 -                    'ip': ip,
       239 -                    'online': False,
       240 -                    'response_time': 0,
       241 -                    'method': 'error',
       242 -                    'error': str(e)
       243 -                }
       244 -
       245 -    return results
       246 -def calculate_checksum(data):
       247 -    """计算ICMP校验和（供ping_device_socket内部使用，也对外导出）"""
       248 -    # 与 ping_device_socket 内部 checksum 相同，单独导出供其他模块使用
       249 -    sum = 0
       250 -    count_to = (len(data) // 2) * 2
       251 -    for count in range(0, count_to, 2):
       252 -        this_val = data[count + 1] * 256 + data[count]
       253 -        sum = sum + this_val
       254 -        sum = sum & 0xffffffff
       255 -    if count_to < len(data):
       256 -        sum = sum + data[len(data) - 1]
       257 -        sum = sum & 0xffffffff
       258 -    sum = (sum >> 16) + (sum & 0xffff)
       259 -    sum = sum + (sum >> 16)
       260 -    answer = ~sum
       261 -    answer = answer & 0xffff
       262 -    answer = answer >> 8 | (answer << 8 & 0xff00)
       263 -    return answer
       264 -
       265 -def detect_device_reliable(ip, timeout=2, use_tcp_check=False):
       266 -    """简化的设备检测，主要依赖ping"""
       267 -    for attempt in range(2):
       268 -        success, response_time = ping_device(ip, timeout=1)
       269 -        if success:
       270 -            return True, response_time, 'ping'
       271 -        if use_tcp_check:
       272 -            success, rtt = ping_device_tcp(ip, timeout=1)
       273 -            if success:
       274 -                return True, rtt, 'tcp'
       275 -        time.sleep(0.1)
       276 -    return False, 0, 'ping_failed'
       277 -
       278 -# ---------- IP 段解析 ----------
       279 -def parse_ip_range(ip_range_str):
       280 -    """
       281 -    解析IP段字符串，返回IP地址列表
       282 -    支持格式: CIDR (192.168.1.0/24), 范围 (192.168.1.1-192.168.1.254 或 192.168.1.1-254)
       283 -    """
       284 -    ip_list = []
       285 -    if not ip_range_str:
       286 -        raise ValueError("IP段不能为空")
       287 -    if '/' in ip_range_str:
       288 -        network = ipaddress.ip_network(ip_range_str, strict=False)
       289 -        for ip in network.hosts():
       290 -            ip_list.append(str(ip))
       291 -        return ip_list
       292 -    elif '-' in ip_range_str:
       293 -        parts = ip_range_str.rsplit('-', 1)
       294 -        start_ip_str = parts[0].strip()
       295 -        end_part = parts[1].strip()
       296 -        if '.' not in end_part:
       297 -            base_parts = start_ip_str.split('.')
       298 -            if len(base_parts) != 4:
       299 -                raise ValueError("起始IP格式无效")
       300 -            base_parts[-1] = end_part
       301 -            end_ip_str = '.'.join(base_parts)
       302 -        else:
       303 -            end_ip_str = end_part
       304 -        if not (is_valid_ip(start_ip_str) and is_valid_ip(end_ip_str)):
       305 -            raise ValueError("无效的IP地址")
       306 -        start = ipaddress.IPv4Address(start_ip_str)
       307 -        end = ipaddress.IPv4Address(end_ip_str)
       308 -        if start > end:
       309 -            start, end = end, start
       310 -        current = start
       311 -        while current <= end:
       312 -            ip_list.append(str(current))
       313 -            current = ipaddress.IPv4Address(int(current) + 1)
       314 -        return ip_list
       315 -    elif is_valid_ip(ip_range_str):
       316 -        return [ip_range_str]
       317 -    else:
       318 -        raise ValueError(f"无效的IP段格式: {ip_range_str}")
       319 -
       320 -# ---------- SNMP GET (基于系统 snmpget 命令) ----------
       321 -
       322 -#!/usr/bin/env python3
       323 -# -*- coding: utf-8 -*-
       324 -
       325 -"""
       326 -SNMP 工具模块 (基于 net-snmp 命令行)
       327 -提供 snmp_get 和 snmp_walk 函数，完全替代 pysnmp
       328 -"""
       329 -
       330 -#!/usr/bin/env python3
       331 -# -*- coding: utf-8 -*-
       332 -
       333 -import subprocess
       334 -import shutil
       335 -import logging
       336 -from typing import Union, List, Tuple, Optional
       337 -
       338 -# 默认超时（秒）
       339 -SNMP_TIMEOUT = 5
       340 -logger = logging.getLogger(__name__)
       341 -
       342 -
       343 -def snmp_get(ip: str, community: str, version: str, oid: str,
       344 -             timeout: int = SNMP_TIMEOUT) -> Optional[Union[int, float, str]]:
       345 -    """
       346 -    通过系统 snmpget 命令执行 SNMP GET
       347 -    参数:
       348 -        ip: 设备IP
       349 -        community: community 字符串
       350 -        version: '1' 或 '2c'
       351 -        oid: 要查询的OID
       352 -        timeout: 超时秒数
       353 -    返回: 解析后的值 (int/float/str) 或 None
       354 -    """
       355 -    if community is None:
       356 -        community = 'public'
       357 -
       358 -    snmpget_cmd = shutil.which('snmpget')
       359 -    if not snmpget_cmd:
       360 -        logger.error("snmpget 命令不存在，请安装 net-snmp 工具")
       361 -        return None
       362 -
       363 -    # 根据 version 参数选择 SNMP 版本
       364 -    ver = '2c' if version == '2c' else '1'
       365 -
       366 -    cmd = [
       367 -        snmpget_cmd,
       368 -        '-v', ver,
       369 -        '-c', str(community),
       370 -        '-t', str(timeout),
       371 -        '-r', '1',
       372 -        '-O', 'qv',          # 只输出值，不带 OID 和类型
       373 -        str(ip),
       374 -        str(oid)
       375 -    ]
       376 -
       377 -    try:
       378 -        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 2)
       379 -        if result.returncode != 0:
       380 -            logger.warning(f"snmpget {ip} {oid} 失败 (code {result.returncode}): {result.stderr.strip
           -()}")
       381 -            return None
       382 -
       383 -        output = result.stdout.strip()
       384 -        if not output:
       385 -            return None
       386 -
       387 -        # 尝试转换为数字
       388 -        try:
       389 -            return int(output)
       390 -        except ValueError:
       391 -            try:
       392 -                return float(output)
       393 -            except ValueError:
       394 -                return output
       395 -    except subprocess.TimeoutExpired:
       396 -        logger.warning(f"snmpget {ip} {oid} 超时")
       397 -        return None
       398 -    except Exception as e:
       399 -        logger.error(f"snmpget {ip} {oid} 异常: {e}")
       400 -        return None
       401 -
       402 -
       403 -def snmp_walk(ip: str, oid: str, community: str = 'public',
       404 -              version: str = '2c', timeout: int = 5,
       405 -              retries: int = 2) -> List[Tuple[str, str]]:
       406 -    """
       407 -    通过系统 snmpwalk 命令执行 SNMP WALK
       408 -    参数:
       409 -        ip: 设备IP
       410 -        oid: 起始OID
       411 -        community: community 字符串
       412 -        version: '1' 或 '2c'
       413 -        timeout: 超时秒数（每个请求的超时）
       414 -        retries: 重试次数
       415 -    返回: [(oid, value), ...] 列表
       416 -    """
       417 -    snmpwalk_cmd = shutil.which('snmpwalk')
       418 -    if not snmpwalk_cmd:
       419 -        logger.error("snmpwalk 命令不存在，请安装 net-snmp 工具")
       420 -        return []
       421 -
       422 -    # 标准化 OID（去掉前导点）
       423 -    oid = oid.lstrip('.')
       424 -    ver = '2c' if version == '2c' else '1'
       425 -
       426 -    # 构建命令
       427 -    # -Cc: 允许继续即使部分节点出错
       428 -    # -On: 输出数字 OID，便于解析
       429 -    cmd = [
       430 -        snmpwalk_cmd,
       431 -        '-v', ver,
       432 -        '-c', str(community),
       433 -        '-t', str(timeout),
       434 -        '-r', str(retries),
       435 -        '-Cc',
       436 -        '-On',
       437 -        str(ip),
       438 -        oid
       439 -    ]
       440 -
       441 -    try:
       442 -        # 总超时适当放大（walk 可能返回大量数据）
       443 -        total_timeout = max(60, timeout * (retries + 1) * 5)
       444 -        result = subprocess.run(cmd, capture_output=True, text=True, timeout=total_timeout)
       445 -
       446 -        # 若完全无输出且返回码非0，则认为失败
       447 -        if result.returncode != 0 and not result.stdout.strip():
       448 -            logger.warning(f"snmpwalk {ip} {oid} 失败 (code {result.returncode}): {result.stderr.stri
           -p()}")
       449 -            return []
       450 -        results = []
       451 -        for line in result.stdout.splitlines():
       452 -            line = line.strip()
       453 -            if not line or '=' not in line:
       454 -                continue
       455 -
       456 -            # 关键：过滤掉 net-snmp 的错误信息行
       457 -            if "No Such Instance" in line or "No Such Object" in line or "No more variables" in line:
       458 -                logger.debug(f"跳过无效 SNMP 行: {line}")
       459 -                continue
       460 -
       461 -            oid_part, value_part = line.split('=', 1)
       462 -            oid_str = oid_part.strip()
       463 -            value_part = value_part.strip()
       464 -
       465 -            # 提取值（去掉类型前缀）
       466 -            if ': ' in value_part:
       467 -                value_str = value_part.split(': ', 1)[1]
       468 -            else:
       469 -                value_str = value_part
       470 -
       471 -            # 去除引号
       472 -            if value_str.startswith('"') and value_str.endswith('"'):
       473 -                value_str = value_str[1:-1]
       474 -
       475 -            # 确保在请求的 OID 子树内
       476 -            base_oid = '.' + oid if not oid.startswith('.') else oid
       477 -            if not oid_str.startswith(base_oid):
       478 -                continue
       479 -
       480 -            results.append((oid_str, value_str))
       481 -
       482 -        return results
       483 -
       484 -    except subprocess.TimeoutExpired:
       485 -        logger.warning(f"snmpwalk {ip} {oid} 总超时（{total_timeout}秒）")
       486 -        return []
       487 -    except Exception as e:
       488 -        logger.error(f"snmpwalk {ip} {oid} 异常: {e}")
       489 -        return []
       490 -
       491 -
       492 -def walk_interfaces(ip, community='public', timeout=5):
       493 -    """
       494 -    通过系统 snmpwalk 命令获取接口名称列表，返回 {ifIndex: ifName}
       495 -    使用数字 OID 1.3.6.1.2.1.31.1.1.1.1 (ifName)
       496 -    完全避免 pysnmp MIB 依赖
       497 -    """
       498 -    result = {}
       499 -    oid = '1.3.6.1.2.1.31.1.1.1.1'
       500 -    snmpwalk_cmd = shutil.which('snmpwalk')
       501 -    if not snmpwalk_cmd:
       502 -        logger.error("snmpwalk 命令不存在，请安装 net-snmp 工具")
       503 -        return result
       504 -    cmd = [
       505 -        snmpwalk_cmd,
       506 -        '-v', '2c',
       507 -        '-c', community,
       508 -        '-t', str(timeout),
       509 -        '-r', '1',
       510 -        '-O', 'v',   # 只输出值，不输出 OID 和类型前缀
       511 -        ip, oid
       512 -    ]
       513 -    try:
       514 -        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout+2, check=False)
       515 -        if proc.returncode != 0:
       516 -            logger.warning(f"snmpwalk {ip} {oid} 失败: {proc.stderr.strip()}")
       517 -            return result
       518 -        # 解析输出，每行格式类似: "1.3.6.1.2.1.31.1.1.1.1.1 = STRING: GigabitEthernet1/0/1"
       519 -        for line in proc.stdout.splitlines():
       520 -            line = line.strip()
       521 -            if not line or '=' not in line:
       522 -                continue
       523 -            left, right = line.split('=', 1)
       524 -            # 提取 OID 最后一段数字作为 ifindex
       525 -            oid_part = left.strip()
       526 -            match = re.search(r'\.(\d+)$', oid_part)
       527 -            if not match:
       528 -                continue
       529 -            ifindex = int(match.group(1))
       530 -            # 提取接口名称（去掉可能的 STRING: 和引号）
       531 -            value = right.strip()
       532 -            if value.startswith('STRING: '):
       533 -                value = value[8:]
       534 -            if value.startswith('"') and value.endswith('"'):
       535 -                value = value[1:-1]
       536 -            result[ifindex] = value
       537 -        return result
       538 -    except subprocess.TimeoutExpired:
       539 -        logger.warning(f"snmpwalk {ip} {oid} 超时")
       540 -        return result
       541 -    except Exception as e:
       542 -        logger.error(f"snmpwalk {ip} {oid} 异常: {e}")
       543 -        return result
       544 -
       545 -# ---------- SNMP 设备信息获取 (使用 snmp_get) ----------
       546 -def snmp_get_device_info(ip, community='public', version='2c', timeout=2, retries=1):
       547 -    """
       548 -    获取设备的 SNMP 基本信息 (sysDescr, sysName, sysLocation, sysObjectID)
       549 -    返回 (success, info_dict)
       550 -    """
       551 -    start = time.time()
       552 -    try:
       553 -        sys_name = snmp_get(ip, community, version, '1.3.6.1.2.1.1.5.0', timeout)
       554 -        if sys_name is None:
       555 -            logger.debug(f"SNMP 无响应 {ip}")
       556 -            return False, {}
       557 -        sys_descr = snmp_get(ip, community, version, '1.3.6.1.2.1.1.1.0', timeout) or ''
       558 -        sys_location = snmp_get(ip, community, version, '1.3.6.1.2.1.1.6.0', timeout) or ''
       559 -        sys_object_id = snmp_get(ip, community, version, '1.3.6.1.2.1.1.2.0', timeout) or ''
       560 -        info = {
       561 -            'ip': ip,
       562 -            'sys_name': str(sys_name).strip(),
       563 -            'sys_descr': str(sys_descr).strip(),
       564 -            'sys_location': str(sys_location).strip(),
       565 -            'sys_object_id': str(sys_object_id).strip(),
       566 -            'snmp_community': community,
       567 -            'snmp_version': version,
       568 -            'discovered_at': datetime.utcnow().isoformat()
       569 -        }
       570 -        logger.debug(f"SNMP 获取成功 {ip}: {info['sys_name']} 耗时 {time.time()-start:.2f}s")
       571 -        return True, info
       572 -    except Exception as e:
       573 -        logger.error(f"SNMP 获取异常 {ip}: {e}")
       574 -        return False, {}
       575 -
       576 -# def scan_ip_with_snmp(ip, community='public', version='2c', timeout=3, retries=1):
       577 -#     """
       578 -#     扫描单个IP的SNMP信息，返回设备信息字典或错误信息
       579 -#     兼容旧版接口
       580 -#     """
       581 -#     success, info = snmp_get_device_info(ip, community, version, timeout, retries)
       582 -#     if not success:
       583 -#         return {'success': False, 'error': 'SNMP查询失败', 'error_detail': '无响应'}
       584 -#     device_type, brand, model = infer_device_type_from_snmp(
       585 -#         sys_descr=info.get('sys_descr', ''),
       586 -#         sys_object_id=info.get('sys_object_id', ''),
       587 -#         sys_name=info.get('sys_name', '')
       588 -#     )
       589 -#     return {
       590 -#         'success': True,
       591 -#         'ip': ip,
       592 -#         'sys_name': info.get('sys_name', f'设备_{ip}'),
       593 -#         'sys_descr': info.get('sys_descr', ''),
       594 -#         'sys_object_id': info.get('sys_object_id', ''),
       595 -#         'manufacturer': brand,
       596 -#         'device_type': device_type,
       597 -#         'model': model,
       598 -#         'snmp_community': community,
       599 -#         'snmp_version': version
       600 -#     }
       601 -
       602 -#scan_and_save_device_from_snmp
       603 -def scan_ip_with_snmp(
       604 -    ip,
       605 -    community='public',
       606 -    version='2c',
       607 -    timeout=3,
       608 -    retries=1,
       609 -    on_conflict='update',   # 可选：'update', 'skip', 'error'
       610 -    update_fields=None       # 指定更新哪些字段，默认全部更新
       611 -):
       612 -    """
       613 -    通过 SNMP 扫描设备信息，并根据名称和 IP 的唯一性进行保存或更新。
       614 -
       615 -    Args:
       616 -        ip (str): 设备管理 IP
       617 -        community (str): SNMP 共同体
       618 -        version (str): SNMP 版本 '1', '2c', '3'
       619 -        timeout (int): 超时秒数
       620 -        retries (int): 重试次数
       621 -        on_conflict (str): 冲突处理策略
       622 -            - 'update': 如果名称或 IP 已存在（且不是同一设备），则更新该设备的信息
       623 -            - 'skip':   跳过，不保存也不更新
       624 -            - 'error':  抛出异常或返回错误信息
       625 -        update_fields (list): 需要更新的字段列表，如 ['name', 'model', 'manufacturer']，
       626 -                               为 None 表示更新所有非空字段
       627 -
       628 -    Returns:
       629 -        dict: {
       630 -            'success': bool,
       631 -            'device_id': int or None,
       632 -            'action': 'created' / 'updated' / 'skipped' / 'failed',
       633 -            'message': str,
       634 -            'device': Device object or None
       635 -        }
       636 -    """
       637 -    # 1. SNMP 扫描获取设备信息
       638 -    scan_result = scan_ip_with_snmp(ip, community, version, timeout, retries)
       639 -    if not scan_result['success']:
       640 -        return {
       641 -            'success': False,
       642 -            'device_id': None,
       643 -            'action': 'failed',
       644 -            'message': f"SNMP 扫描失败: {scan_result.get('error_detail', '无响应')}",
       645 -            'device': None
       646 -        }
       647 -
       648 -    # 提取扫描到的信息
       649 -    sys_name = scan_result.get('sys_name', f'设备_{ip}')
       650 -    manufacturer = scan_result.get('manufacturer', '')
       651 -    device_type = scan_result.get('device_type', '')
       652 -    model = scan_result.get('model', '')
       653 -    sys_descr = scan_result.get('sys_descr', '')
       654 -    sys_object_id = scan_result.get('sys_object_id', '')
       655 -
       656 -    # 2. 检查数据库中是否已存在相同名称或 IP 的设备
       657 -    #   注意：名称和 IP 都可能重复，只要有一个重复就算冲突
       658 -    existing_by_name = Device.query.filter_by(name=sys_name).first()
       659 -    existing_by_ip = Device.query.filter_by(management_ip=ip).first()
       660 -
       661 -    # 判断冲突情况
       662 -    conflict = None
       663 -    if existing_by_name and existing_by_ip:
       664 -        if existing_by_name.id == existing_by_ip.id:
       665 -            # 名称和 IP 对应同一台设备，无冲突（就是这台设备）
       666 -            existing_device = existing_by_name
       667 -        else:
       668 -            # 名称属于设备A，IP属于设备B，严重冲突
       669 -            conflict = 'both'
       670 -    elif existing_by_name:
       671 -        conflict = 'name'
       672 -        existing_device = existing_by_name
       673 -    elif existing_by_ip:
       674 -        conflict = 'ip'
       675 -        existing_device = existing_by_ip
       676 -    else:
       677 -        existing_device = None
       678 -
       679 -    # 3. 根据冲突类型和处理策略执行操作
       680 -    if existing_device:
       681 -        # 情况：已存在设备（名称或 IP 重复）
       682 -        if conflict == 'both':
       683 -            # 名称和 IP 分别属于不同设备，无法自动解决
       684 -            msg = (f"严重冲突：名称 '{sys_name}' 属于设备 ID {existing_by_name.id}，"
       685 -                   f"IP '{ip}' 属于设备 ID {existing_by_ip.id}，无法自动处理。")
       686 -            if on_conflict == 'error':
       687 -                return {'success': False, 'action': 'failed', 'message': msg, 'device': None}
       688 -            elif on_conflict == 'skip':
       689 -                return {'success': True, 'action': 'skipped', 'message': msg, 'device': None}
       690 -            else:  # 'update' 也无法处理，返回错误
       691 -                return {'success': False, 'action': 'failed', 'message': msg, 'device': None}
       692 -
       693 -        # 单一冲突：名称重复 或 IP 重复
       694 -        # 检查冲突的设备是否是当前扫描的设备本身（通过 IP 或名称匹配）
       695 -        # 如果是它自己，则视为更新；如果不是，则根据策略处理
       696 -        if (conflict == 'name' and existing_device.management_ip == ip) or \
       697 -           (conflict == 'ip' and existing_device.name == sys_name):
       698 -            # 实际上是同一台设备（名称或 IP 有一个匹配且另一个也匹配），允许更新
       699 -            action = 'update'
       700 -        else:
       701 -            # 不同设备，根据策略决定
       702 -            if on_conflict == 'skip':
       703 -                msg = f"设备名称 '{sys_name}' 或 IP '{ip}' 已被其他设备使用 (ID: {existing_device.id}
           -)，已跳过"
       704 -                return {'success': True, 'action': 'skipped', 'message': msg, 'device': existing_devi
           -ce}
       705 -            elif on_conflict == 'error':
       706 -                msg = f"设备名称 '{sys_name}' 或 IP '{ip}' 已被其他设备使用 (ID: {existing_device.id}
           -)"
       707 -                return {'success': False, 'action': 'failed', 'message': msg, 'device': existing_devi
           -ce}
       708 -            else:  # 'update' 模式：覆盖原有设备的信息（注意：这会修改现有设备的名称/IP）
       709 -                # 这里需要小心：如果名称重复但IP不同，更新后会把原有设备的名称改掉？不合理
       710 -                # 实际上 'update' 模式应当仅用于同一设备的重复扫描，对于不同设备不应强制覆盖。
       711 -                # 因此我们这里将不同设备的冲突也视为错误，除非调用者明确允许强制合并。
       712 -                msg = f"冲突且非同一设备，无法安全更新，请先手动处理重复数据 (ID: {existing_device.id
           -})"
       713 -                return {'success': False, 'action': 'failed', 'message': msg, 'device': existing_devi
           -ce}
       714 -    else:
       715 -        # 没有冲突，创建新设备
       716 -        action = 'create'
       717 -
       718 -    # 4. 执行创建或更新
       719 -    try:
       720 -        if action == 'create':
       721 -            device = Device(
       722 -                name=sys_name,
       723 -                management_ip=ip,
       724 -                device_type=device_type,
       725 -                manufacturer=manufacturer,
       726 -                model=model,
       727 -                snmp_community=community,
       728 -                snmp_version=version,
       729 -                description=sys_descr[:500] if sys_descr else None,  # 限制长度
       730 -                # 其他字段根据需要设置默认值
       731 -                status='unknown',
       732 -                created_at=dt.utcnow(),
       733 -                updated_at=dt.utcnow()
       734 -            )
       735 -            db.session.add(device)
       736 -            db.session.commit()
       737 -            msg = f"成功创建设备: {sys_name} ({ip})"
       738 -        else:  # update
       739 -            device = existing_device
       740 -            # 决定更新哪些字段
       741 -            if update_fields is None:
       742 -                # 默认更新所有非空字段
       743 -                device.name = sys_name
       744 -                device.management_ip = ip
       745 -                device.device_type = device_type
       746 -                device.manufacturer = manufacturer
       747 -                device.model = model
       748 -                device.snmp_community = community
       749 -                device.snmp_version = version
       750 -                device.description = sys_descr[:500] if sys_descr else None
       751 -            else:
       752 -                # 只更新指定字段
       753 -                if 'name' in update_fields:
       754 -                    device.name = sys_name
       755 -                if 'management_ip' in update_fields:
       756 -                    device.management_ip = ip
       757 -                if 'device_type' in update_fields:
       758 -                    device.device_type = device_type
       759 -                if 'manufacturer' in update_fields:
       760 -                    device.manufacturer = manufacturer
       761 -                if 'model' in update_fields:
       762 -                    device.model = model
       763 -                if 'snmp_community' in update_fields:
       764 -                    device.snmp_community = community
       765 -                if 'snmp_version' in update_fields:
       766 -                    device.snmp_version = version
       767 -                if 'description' in update_fields:
       768 -                    device.description = sys_descr[:500] if sys_descr else None
       769 -            device.updated_at = dt.utcnow()
       770 -            db.session.commit()
       771 -            msg = f"成功更新设备: {sys_name} ({ip})"
       772 -
       773 -        return {
       774 -            'success': True,
       775 -            'device_id': device.id,
       776 -            'action': action,
       777 -            'message': msg,
       778 -            'device': device
       779 -        }
       780 -    except Exception as e:
       781 -        db.session.rollback()
       782 -        return {
       783 -            'success': False,
       784 -            'device_id': None,
       785 -            'action': 'failed',
       786 -            'message': f"数据库操作失败: {str(e)}",
       787 -            'device': None
       788 -        }
       789 -
       790 -# ---------- 设备类型推断 ----------
       791 -def infer_device_type_from_snmp(sys_descr: str, sys_object_id: str = '', sys_name: str = '') -> tuple
           -:
       792 -    """根据 SNMP 信息推断设备类型、品牌、型号"""
       793 -    device_type = 'unknown'
       794 -    brand = ''
       795 -    model = ''
       796 -    sys_descr = (sys_descr or '').strip()
       797 -    sys_name = (sys_name or '').strip()
       798 -    sys_oid = (sys_object_id or '').strip()
       799 -    lower_desc = sys_descr.lower()
       800 -    lower_name = sys_name.lower()
       801 -
       802 -    # H3C
       803 -    if sys_oid.startswith('1.3.6.1.4.1.25506') or 'h3c' in lower_desc:
       804 -        brand = 'H3C'
       805 -        patterns = [
       806 -            r'H3C\s+(S\d{4}[A-Za-z0-9\-_/.]*)',
       807 -            r'H3C\s+(MSR\d+[A-Za-z0-9\-_/.]*)',
       808 -            r'H3C\s+([A-Z]{2,}\d+[A-Za-z0-9\-_/.]*)',
       809 -        ]
       810 -        for pat in patterns:
       811 -            match = re.search(pat, sys_descr, re.IGNORECASE)
       812 -            if match:
       813 -                model = match.group(1)
       814 -                break
       815 -        if not model:
       816 -            alt = re.search(r'\b([A-Z]\d+[A-Za-z0-9\-_/.]*)', sys_descr)
       817 -            if alt:
       818 -                model = alt.group(1)
       819 -        if any(kw in lower_desc or kw in lower_name for kw in ['switch', '交换机', 's5130', 's5700'])
           -:
       820 -            device_type = 'switch'
       821 -        elif any(kw in lower_desc or kw in lower_name for kw in ['router', '路由', 'msr']):
       822 -            device_type = 'router'
       823 -        elif any(kw in lower_desc or kw in lower_name for kw in ['firewall', '防火墙']):
       824 -            device_type = 'firewall'
       825 -    # Huawei
       826 -    elif sys_oid.startswith('1.3.6.1.4.1.2011') or 'huawei' in lower_desc or '华为' in lower_desc:
       827 -        brand = 'Huawei'
       828 -        full_match = re.search(r'\b([A-Z]{1,2}\d{3,4}[A-Za-z0-9\-_/.]*)', sys_descr)
       829 -        if full_match:
       830 -            model = full_match.group(1)
       831 -        else:
       832 -            lines = sys_descr.splitlines()
       833 -            for line in lines:
       834 -                if any(kw in line.lower() for kw in ['platform software', 'version', 'copyright']):
       835 -                    continue
       836 -                match = re.search(r'Huawei\s+([A-Za-z0-9\-_/.]+)', line, re.IGNORECASE)
       837 -                if match:
       838 -                    candidate = match.group(1)
       839 -                    if re.search(r'\d', candidate):
       840 -                        model = candidate
       841 -                        break
       842 -        if any(kw in lower_desc or kw in lower_name for kw in ['switch', '交换机', 's57', 'ce68']):
       843 -            device_type = 'switch'
       844 -        elif any(kw in lower_desc or kw in lower_name for kw in ['router', '路由', 'ar', 'ne']):
       845 -            device_type = 'router'
       846 -        elif any(kw in lower_desc or kw in lower_name for kw in ['firewall', '防火墙', 'usg']):
       847 -            device_type = 'firewall'
       848 -    # Cisco
       849 -    elif sys_oid.startswith('1.3.6.1.4.1.9') or 'cisco' in lower_desc:
       850 -        brand = 'Cisco'
       851 -        for line in sys_descr.splitlines():
       852 -            match = re.search(r'Cisco\s+([A-Za-z0-9\-_/.]+)', line, re.IGNORECASE)
       853 -            if match:
       854 -                model = match.group(1)
       855 -                break
       856 -        if not model:
       857 -            patterns = [r'\b(Catalyst\s+\d+[A-Za-z0-9\-_.]*)', r'\b(ISR\d+[A-Za-z0-9\-_.]*)']
       858 -            for pat in patterns:
       859 -                match = re.search(pat, sys_descr, re.IGNORECASE)
       860 -                if match:
       861 -                    model = match.group(1)
       862 -                    break
       863 -        if 'switch' in lower_desc or 'catalyst' in lower_desc:
       864 -            device_type = 'switch'
       865 -        elif 'router' in lower_desc or 'isr' in lower_desc:
       866 -            device_type = 'router'
       867 -    # 通用服务器
       868 -    if device_type == 'unknown':
       869 -        if any(kw in lower_desc for kw in ['linux', 'windows', 'server', 'ubuntu', 'centos']):
       870 -            device_type = 'server'
       871 -            brand = 'Generic'
       872 -            model = 'Server'
       873 -    if model:
       874 -        version_match = re.search(r'(.+?)\s+(?:Ver|Version|Release|Software|V|R)\s*\d+', model, re.IG
           -NORECASE)
       875 -        if version_match:
       876 -            model = version_match.group(1).strip()
       877 -        model = model.rstrip('.,-_ ')
       878 -    return device_type, brand, model
       879 -
       880 -def update_device_snmp_info(device: Device, snmp_community='public', snmp_version='2c'):
       881 -    """通过 SNMP 更新设备的 device_type, brand, model 等字段"""
       882 -    target_ip = device.management_ip or device.ip_address
       883 -    if not target_ip:
       884 -        return False
       885 -    success, info = snmp_get_device_info(target_ip, snmp_community, snmp_version, timeout=3, retries=
           -2)
       886 -    if not success:
       887 -        return False
       888 -    device_type, brand, model = infer_device_type_from_snmp(
       889 -        sys_descr=info.get('sys_descr', ''),
       890 -        sys_object_id=info.get('sys_object_id', ''),
       891 -        sys_name=info.get('sys_name', '')
       892 -    )
       893 -    device.device_type = device_type or 'unknown'
       894 -    device.brand = brand or ''
       895 -    device.model = model or ''
       896 -    device.os_version = (info.get('sys_descr', '') or '')[:128]
       897 -    device.last_scanned = datetime.utcnow()
       898 -    device.updated_at = datetime.utcnow()
       899 -    try:
       900 -        db.session.commit()
       901 -        return True
       902 -    except Exception:
       903 -        db.session.rollback()
       904 -        return False
       905 -
       906 -# ---------- SNMP 接口发现 ----------
       907 -def snmp_discover_interfaces_real(ip, community, version='2c', port=161):
       908 -    """通过 SNMP 获取设备的所有接口信息 (bulkCmd)"""
       909 -    from pysnmp.entity.rfc3413.oneliner import cmdgen
       910 -    cmd_gen = cmdgen.CommandGenerator()
       911 -    mp_model = 0 if version == '1' else 1
       912 -    oids = [
       913 -        '1.3.6.1.2.1.2.2.1.1',   # ifIndex
       914 -        '1.3.6.1.2.1.2.2.1.2',   # ifDescr
       915 -        '1.3.6.1.2.1.2.2.1.3',   # ifType
       916 -        '1.3.6.1.2.1.2.2.1.5',   # ifSpeed
       917 -        '1.3.6.1.2.1.2.2.1.7',   # ifAdminStatus
       918 -        '1.3.6.1.2.1.2.2.1.8',   # ifOperStatus
       919 -    ]
       920 -    errorIndication, errorStatus, errorIndex, varBindTable = cmd_gen.bulkCmd(
       921 -        cmdgen.CommunityData(community, mpModel=mp_model),
       922 -        cmdgen.UdpTransportTarget((ip, port), timeout=2, retries=2),
       923 -        0, 25,
       924 -        *[cmdgen.MibVariable(oid) for oid in oids],
       925 -        lookupMib=False
       926 -    )
       927 -    if errorIndication or errorStatus:
       928 -        logger.error(f"SNMP bulk 错误: {errorIndication or errorStatus}")
       929 -        return []
       930 -    interfaces = {}
       931 -    for varBinds in varBindTable:
       932 -        for oid, val in varBinds:
       933 -            if_index = oid[-1]
       934 -            if if_index not in interfaces:
       935 -                interfaces[if_index] = {'ifIndex': if_index}
       936 -            oid_str = '.'.join(str(x) for x in oid[:-1])
       937 -            if oid_str == '1.3.6.1.2.1.2.2.1.2':
       938 -                interfaces[if_index]['ifDescr'] = val.prettyPrint() if hasattr(val, 'prettyPrint') el
           -se str(val)
       939 -            elif oid_str == '1.3.6.1.2.1.2.2.1.3':
       940 -                interfaces[if_index]['ifType'] = int(val)
       941 -            elif oid_str == '1.3.6.1.2.1.2.2.1.5':
       942 -                interfaces[if_index]['ifSpeed'] = int(val)
       943 -            elif oid_str == '1.3.6.1.2.1.2.2.1.7':
       944 -                admin_val = int(val)
       945 -                interfaces[if_index]['ifAdminStatus'] = admin_val
       946 -                interfaces[if_index]['ifAdminStatusText'] = 'up' if admin_val == 1 else 'down' if adm
           -in_val == 2 else 'unknown'
       947 -            elif oid_str == '1.3.6.1.2.1.2.2.1.8':
       948 -                oper_val = int(val)
       949 -                interfaces[if_index]['ifOperStatus'] = oper_val
       950 -                interfaces[if_index]['ifOperStatusText'] = 'up' if oper_val == 1 else 'down' if oper_
           -val == 2 else 'unknown'
       951 -    return list(interfaces.values())
       952 -
       953 -def save_discovered_interfaces(device_id, discovered):
       954 -    """将发现的接口列表保存到数据库，如已存在则更新"""
       955 -    saved = []
       956 -    for intf in discovered:
       957 -        name = intf.get('ifDescr')
       958 -        if not name:
       959 -            continue
       960 -        existing = Interface.query.filter_by(device_id=device_id, name=name).first()
       961 -        if not existing:
       962 -            new_intf = Interface(
       963 -                device_id=device_id,
       964 -                name=name,
       965 -                ifindex=intf.get('ifIndex'),
       966 -                speed=intf.get('ifSpeed'),
       967 -                admin_status=intf.get('ifAdminStatusText'),
       968 -                oper_status=intf.get('ifOperStatusText'),
       969 -                description="Auto-discovered via SNMP",
       970 -                created_at=datetime.utcnow(),
       971 -                updated_at=datetime.utcnow()
       972 -            )
       973 -            db.session.add(new_intf)
       974 -            saved.append({'name': name, 'ifindex': intf.get('ifIndex')})
       975 -        else:
       976 -            existing.ifindex = intf.get('ifIndex') or existing.ifindex
       977 -            existing.speed = intf.get('ifSpeed') or existing.speed
       978 -            existing.admin_status = intf.get('ifAdminStatusText') or existing.admin_status
       979 -            existing.oper_status = intf.get('ifOperStatusText') or existing.oper_status
       980 -            existing.updated_at = datetime.utcnow()
       981 -            saved.append({'name': name, 'ifindex': existing.ifindex})
       982 -    db.session.commit()
       983 -    return saved
       984 -
       985 -# ---------- 扫描工作线程 ----------
       986 -def scan_ip_range_worker(ip, ping_timeout, ping_count,
       987 -                         snmp_community, snmp_version,
       988 -                         snmp_timeout, snmp_retries, check_snmp_flag):
       989 -    """
       990 -    扫描单个IP的工作线程函数
       991 -    返回结果字典，供 ip_range_import 使用
       992 -    """
       993 -    result = {
       994 -        'ip': ip,
       995 -        'online': False,
       996 -        'ping_time': 0,
       997 -        'snmp_support': False,
       998 -        'sysinfo': {},
       999 -        'existing': False
      1000 -    }
      1001 -    # 检查是否已存在
      1002 -    existing_device = Device.query.filter_by(management_ip=ip).first()
      1003 -    if existing_device:
      1004 -        result['existing'] = True
      1005 -        result['device_name'] = existing_device.name
      1006 -        result['existing_name'] = existing_device.name
      1007 -        return result
      1008 -    # Ping检测
      1009 -    online, ping_time = ping_device(ip, ping_timeout)
      1010 -    result['online'] = online
      1011 -    if online:
      1012 -        result['ping_time'] = ping_time
      1013 -        if check_snmp_flag:
      1014 -            success, sysinfo = snmp_get_device_info(ip, snmp_community, snmp_version, snmp_timeout, s
           -nmp_retries)
      1015 -            result['snmp_support'] = success
      1016 -            result['sysinfo'] = sysinfo
      1017 -            if sysinfo:
      1018 -                result['device_name'] = sysinfo.get('sys_name', f"设备_{ip}")
      1019 -                result['description'] = sysinfo.get('sys_descr', 'SNMP设备')
      1020 -        else:
      1021 -            result['device_name'] = f"设备_{ip}"
      1022 -            result['description'] = '通过IP扫描发现的设备'
      1023 -    return result
      1024 -
      1025 -# ---------- 以下为原有业务功能（Excel导入导出、位置管理、设备导入等）----------
      1026 -def generate_location_template():
      1027 -    """生成位置模板Excel文件"""
      1028 -    wb = Workbook()
      1029 -    ws = wb.active
      1030 -    ws.title = "位置模板"
      1031 -    headers = ['名称', '描述', '地址', '联系人', '联系电话', '备注']
      1032 -    for col, h in enumerate(headers, 1):
      1033 -        ws.cell(row=1, column=col, value=h)
      1034 -    example = ['核心机房', '主数据中心', '北京市海淀区中关村大街1号B1层', '张三', '13800138001', '24
           -小时监控']
      1035 -    for col, val in enumerate(example, 1):
      1036 -        ws.cell(row=2, column=col, value=val)
      1037 -    output = io.BytesIO()
      1038 -    wb.save(output)
      1039 -    output.seek(0)
      1040 -    return output
      1041 -
      1042 -def export_locations_to_excel(locations):
      1043 -    """导出位置数据到Excel"""
      1044 -    wb = Workbook()
      1045 -    ws = wb.active
      1046 -    ws.title = "位置列表"
      1047 -    headers = ["位置名称", "描述", "地址", "联系人", "联系电话", "备注"]
      1048 -    for col, h in enumerate(headers, 1):
      1049 -        ws.cell(row=1, column=col, value=h)
      1050 -    for row, loc in enumerate(locations, 2):
      1051 -        ws.cell(row=row, column=1, value=loc.name or "")
      1052 -        ws.cell(row=row, column=2, value=loc.description or "")
      1053 -        ws.cell(row=row, column=3, value=loc.address or "")
      1054 -        ws.cell(row=row, column=4, value=loc.contact_person or "")
      1055 -        ws.cell(row=row, column=5, value=loc.contact_phone or "")
      1056 -        ws.cell(row=row, column=6, value=loc.notes or "")
      1057 -    output = io.BytesIO()
      1058 -    wb.save(output)
      1059 -    output.seek(0)
      1060 -    return output
      1061 -
      1062 -def import_locations_from_excel(file_path, db, Location, log_operation):
      1063 -    """从Excel导入位置数据"""
      1064 -    df = pd.read_excel(file_path)
      1065 -    required = ['名称']
      1066 -    for col in required:
      1067 -        if col not in df.columns:
      1068 -            raise ValueError(f"缺少列: {col}")
      1069 -    success = 0
      1070 -    errors = []
      1071 -    for idx, row in df.iterrows():
      1072 -        name = str(row['名称']).strip()
      1073 -        if not name:
      1074 -            errors.append(f"第{idx+2}行: 名称为空")
      1075 -            continue
      1076 -        if Location.query.filter_by(name=name).first():
      1077 -            errors.append(f"第{idx+2}行: 位置已存在")
      1078 -            continue
      1079 -        loc = Location(
      1080 -            name=name,
      1081 -            description=str(row.get('描述', '')).strip() if pd.notna(row.get('描述')) else None,
      1082 -            address=str(row.get('地址', '')).strip() if pd.notna(row.get('地址')) else None,
      1083 -            contact_person=str(row.get('联系人', '')).strip() if pd.notna(row.get('联系人')) else Non
           -e,
      1084 -            contact_phone=str(row.get('联系电话', '')).strip() if pd.notna(row.get('联系电话')) else
           -None,
      1085 -            notes=str(row.get('备注', '')).strip() if pd.notna(row.get('备注')) else None
      1086 -        )
      1087 -        db.session.add(loc)
      1088 -        success += 1
      1089 -    db.session.commit()
      1090 -    return {'success': True, 'success_count': success, 'error_count': len(errors), 'error_messages':
           -errors[:10]}
      1091 -
      1092 -def export_devices_to_excel(devices):
      1093 -    """导出设备数据到Excel"""
      1094 -    wb = Workbook()
      1095 -    ws = wb.active
      1096 -    ws.title = '设备列表'
      1097 -    headers = ['设备名称', '设备类型', '型号', '序列号', '资产编号', '机柜名称', 'U位', 'U高度', 'IP
           -地址', 'MAC地址', '状态', '安装时间', '位置名称', '联系人', '联系电话']
      1098 -    ws.append(headers)
      1099 -    for dev in devices:
      1100 -        ws.append([
      1101 -            dev.name, dev.device_type, dev.model, dev.serial_number, dev.asset_number,
      1102 -            dev.cabinet.name if dev.cabinet else '', dev.u_position, dev.u_height,
      1103 -            dev.ip_address, dev.mac_address, dev.status,
      1104 -            dev.installed_at.strftime('%Y-%m-%d') if dev.installed_at else '',
      1105 -            dev.location.name if dev.location else '', dev.contact_person, dev.contact_phone
      1106 -        ])
      1107 -    output = BytesIO()
      1108 -    wb.save(output)
      1109 -    output.seek(0)
      1110 -    return output
      1111 -
      1112 -def generate_device_template():
      1113 -    """生成设备导入模板"""
      1114 -    wb = Workbook()
      1115 -    ws = wb.active
      1116 -    ws.title = '设备导入模板'
      1117 -    headers = ['设备名称（必填）', '设备类型', '型号', '序列号', '资产编号', '机柜名称（必填）', 'U位
           -', 'U高度', 'IP地址', '状态']
      1118 -    ws.append(headers)
      1119 -    ws.append(['服务器01', 'server', 'DELL R750', 'SN123456', 'ASSET789', '机柜A01', 1, 2, '192.168.1
           -.10', 'online'])
      1120 -    output = BytesIO()
      1121 -    wb.save(output)
      1122 -    output.seek(0)
      1123 -    return output
      1124 -
      1125 -def import_devices_from_excel(filepath, db, Device, Cabinet, Location, log_operation):
      1126 -    """从Excel导入设备数据"""
      1127 -    wb = openpyxl.load_workbook(filepath)
      1128 -    ws = wb.active
      1129 -    success = 0
      1130 -    errors = []
      1131 -    for row in ws.iter_rows(min_row=2, values_only=True):
      1132 -        name = row[0] if row[0] else None
      1133 -        device_type = row[1] if row[1] else None
      1134 -        model = row[2] if row[2] else None
      1135 -        serial_number = row[3] if row[3] else None
      1136 -        asset_number = row[4] if row[4] else None
      1137 -        cabinet_name = row[5] if row[5] else None
      1138 -        u_position = row[6] if row[6] else None
      1139 -        u_height = row[7] if row[7] else 1
      1140 -        ip_address = row[8] if row[8] else None
      1141 -        status = row[9] if row[9] else 'online'
      1142 -        if not name or not cabinet_name:
      1143 -            errors.append(f"第{row[0].row if hasattr(row, 'row') else '?'}行: 名称或机柜为空")
      1144 -            continue
      1145 -        cabinet = Cabinet.query.filter_by(name=cabinet_name).first()
      1146 -        if not cabinet:
      1147 -            errors.append(f"机柜不存在: {cabinet_name}")
      1148 -            continue
      1149 -        if u_position and Device.query.filter_by(cabinet_id=cabinet.id, u_position=u_position).first(
           -):
      1150 -            errors.append(f"U位冲突: {u_position}")
      1151 -            continue
      1152 -        dev = Device(
      1153 -            name=name, device_type=device_type, model=model, serial_number=serial_number,
      1154 -            asset_number=asset_number, cabinet_id=cabinet.id, location_id=cabinet.location_id,
      1155 -            u_position=u_position, u_height=u_height, ip_address=ip_address, status=status,
      1156 -            installed_at=datetime.utcnow(), created_at=datetime.utcnow(), updated_at=datetime.utcnow(
           -)
      1157 -        )
      1158 -        db.session.add(dev)
      1159 -        success += 1
      1160 -    db.session.commit()
      1161 -    return {'success': True, 'success_count': success, 'error_count': len(errors), 'errors': errors[:
           -10]}
      1162 -
      1163 -def ip_range_import(
      1164 -    ip_range_str: str,
      1165 -    device_type: str = 'unknown',
      1166 -    cabinet_id: Optional[int] = None,
      1167 -    manufacturer: Optional[str] = None,
      1168 -    auto_naming: bool = True,
      1169 -    skip_existing: bool = True,
      1170 -    use_ping: bool = True,
      1171 -    ping_timeout: int = 2,
      1172 -    concurrent: int = 10,
      1173 -    strict_check: bool = True,
      1174 -    verify_tcp: bool = False
      1175 -) -> Dict[str, Any]:
      1176 -    """批量导入IP段中的设备"""
      1177 -    from models.models import Device
      1178 -    results = {'total': 0, 'added': 0, 'skipped': 0, 'failed': 0, 'online_count': 0, 'offline_count':
           - 0, 'results': []}
      1179 -    try:
      1180 -        ip_list = parse_ip_range(ip_range_str)
      1181 -        results['total'] = len(ip_list)
      1182 -        for ip in ip_list:
      1183 -            if skip_existing and Device.query.filter_by(management_ip=ip).first():
      1184 -                results['skipped'] += 1
      1185 -                continue
      1186 -            if use_ping:
      1187 -                online, rtt, method = detect_device_reliable(ip, timeout=ping_timeout, use_tcp_check=
           -verify_tcp)
      1188 -                if not online:
      1189 -                    results['offline_count'] += 1
      1190 -                    results['skipped'] += 1
      1191 -                    continue
      1192 -                results['online_count'] += 1
      1193 -            dev_name = f"设备_{ip}" if auto_naming else ip
      1194 -            new_dev = Device(
      1195 -                name=dev_name, management_ip=ip, device_type=device_type,
      1196 -                manufacturer=manufacturer, cabinet_id=cabinet_id, status='online' if use_ping else 'u
           -nknown',
      1197 -                last_checked=datetime.utcnow(), last_seen=datetime.utcnow() if use_ping else None,
      1198 -                ping_time=rtt if use_ping else None, created_at=datetime.utcnow(), updated_at=datetim
           -e.utcnow()
      1199 -            )
      1200 -            db.session.add(new_dev)
      1201 -            results['added'] += 1
      1202 -        db.session.commit()
      1203 -        return results
      1204 -    except Exception as e:
      1205 -        db.session.rollback()
      1206 -        return {'success': False, 'message': str(e), **results}
      1207 -
        59  def get_device_status_color(status):
        60      status_colors = {'online': 'success', 'offline': 'danger', 'fault': 'warning', 'unknown': 'second
            ary'}
        61      return status_colors.get(status, 'secondary')
        62
        63 +
        64  def get_device_color(device_type, variant='light'):
        65      colors = {
      1214 -        'router': {'light': '#28a745', 'dark': '#1e7e34'},
      1215 -        'switch': {'light': '#007bff', 'dark': '#0056b3'},
      1216 -        'server': {'light': '#6610f2', 'dark': '#4a0fc2'},
      1217 -        'storage': {'light': '#e83e8c', 'dark': '#c2185b'},
      1218 -        'firewall': {'light': '#fd7e14', 'dark': '#e65100'},
      1219 -        'other': {'light': '#6c757d', 'dark': '#495057'}
        66 +        'router':    {'light': '#28a745', 'dark': '#1e7e34'},
        67 +        'switch':    {'light': '#007bff', 'dark': '#0056b3'},
        68 +        'server':    {'light': '#6610f2', 'dark': '#4a0fc2'},
        69 +        'storage':   {'light': '#e83e8c', 'dark': '#c2185b'},
        70 +        'firewall':  {'light': '#fd7e14', 'dark': '#e65100'},
        71 +        'other':     {'light': '#6c757d', 'dark': '#495057'},
        72      }
        73      return colors.get(device_type or 'other', colors['other']).get(variant, '#6c757d')
        74
      1223 -# ---------- 厂商 OID 映射和监控数据采集 ----------
      1224 -OID_MAPPINGS = {
      1225 -    'linux': {
      1226 -        'cpu_usage': ['1.3.6.1.4.1.2021.11.9.0', '1.3.6.1.4.1.2021.11.10.0', '1.3.6.1.4.1.2021.11.11.
           -0'],
      1227 -        'memory_usage': ['1.3.6.1.4.1.2021.4.6.0', '1.3.6.1.4.1.2021.4.5.0'],
      1228 -        'disk_usage': ['1.3.6.1.4.1.2021.9.1.9.1', '1.3.6.1.4.1.2021.9.1.8.1'],
      1229 -        'temperature': [], 'power_consumption': [], 'power_supply': [],
      1230 -    },
      1231 -    'cisco': {
      1232 -        'cpu_usage': ['1.3.6.1.4.1.9.9.109.1.1.1.1.3.1', '1.3.6.1.4.1.9.9.109.1.1.1.1.4.1'],
      1233 -        'memory_usage': ['1.3.6.1.4.1.9.9.48.1.1.1.5.1', '1.3.6.1.4.1.9.9.48.1.1.1.6.1', '1.3.6.1.4.1
           -.9.9.48.1.1.1.4.1'],
      1234 -        'disk_usage': ['1.3.6.1.4.1.9.9.10.1.1.4.1.4.1', '1.3.6.1.4.1.9.9.10.1.1.4.1.5.1'],
      1235 -        'temperature': ['1.3.6.1.4.1.9.9.13.1.3.1.3.1'],
      1236 -        'power_supply': ['1.3.6.1.4.1.9.9.13.1.4.1.3.1'],
      1237 -        'power_consumption': [],
      1238 -    },
      1239 -    'huawei': {
      1240 -        'cpu_usage': ['1.3.6.1.4.1.2011.6.3.4.1.2.1.3.1', '1.3.6.1.4.1.2011.6.3.4.1.2.1.4.1'],
      1241 -        'memory_usage': ['1.3.6.1.4.1.2011.6.3.5.1.1.2.1.6.1', '1.3.6.1.4.1.2011.6.3.5.1.1.2.1.7.1',
           -'1.3.6.1.4.1.2011.6.3.5.1.1.2.1.8.1'],
      1242 -        'temperature': ['1.3.6.1.4.1.2011.6.3.8.1.2.1.3.1'],
      1243 -        'power_supply': ['1.3.6.1.4.1.2011.6.3.9.1.1.3.1.4.1'],
      1244 -        'disk_usage': [], 'power_consumption': [],
      1245 -    },
      1246 -    'h3c': {
      1247 -        'cpu_usage': ['1.3.6.1.4.1.25506.2.6.1.1.1.1.6.1', '1.3.6.1.4.1.25506.2.13.1.1.2.1.8.1'],
      1248 -        'memory_usage': ['1.3.6.1.4.1.25506.2.6.1.1.1.1.8.1'],
      1249 -        'temperature': ['1.3.6.1.4.1.25506.2.6.1.1.1.1.12.1'],
      1250 -        'power_supply': ['1.3.6.1.4.1.25506.2.6.1.1.1.1.20.1'],
      1251 -        'disk_usage': [], 'power_consumption': [],
      1252 -    },
      1253 -    'ruijie': {
      1254 -        'cpu_usage': ['1.3.6.1.4.1.4881.1.1.10.2.10.1.1.1.2.1'],
      1255 -        'memory_usage': ['1.3.6.1.4.1.4881.1.1.10.2.10.1.1.1.4.1'],
      1256 -        'temperature': ['1.3.6.1.4.1.4881.1.1.10.2.10.1.1.1.6.1'],
      1257 -        'power_supply': ['1.3.6.1.4.1.4881.1.1.10.2.10.1.1.1.8.1'],
      1258 -        'disk_usage': [], 'power_consumption': [],
      1259 -    },
      1260 -}
      1261 -FALLBACK_OIDS = {
      1262 -    'cpu_usage': ['1.3.6.1.2.1.25.3.3.1.2.1'],
      1263 -    'memory_usage': ['1.3.6.1.2.1.25.2.3.1.5.1', '1.3.6.1.2.1.25.2.3.1.6.1'],
      1264 -    'disk_usage': ['1.3.6.1.2.1.25.2.3.1.5.2'],
      1265 -    'temperature': [], 'power_consumption': [], 'power_supply': [],
      1266 -}
        75
      1268 -def get_device_snmp_data(device):
      1269 -    """采集设备的 CPU、内存、磁盘、温度、电源等数据"""
      1270 -    ip = device.management_ip
      1271 -    # 修复：使用 device 对象的属性，而不是未定义的变量
      1272 -    community = getattr(device, 'snmp_community', 'public')
      1273 -    version = str(getattr(device, 'snmp_version', '2c'))
      1274 -
      1275 -    vendor = getattr(device, 'vendor', '').lower()
      1276 -    if not vendor and device.device_type:
      1277 -        dt = device.device_type.lower()
      1278 -        if 'h3c' in dt or 'hp' in dt:
      1279 -            vendor = 'h3c'
      1280 -        elif 'cisco' in dt:
      1281 -            vendor = 'cisco'
      1282 -        elif 'huawei' in dt:
      1283 -            vendor = 'huawei'
      1284 -        elif 'linux' in dt:
      1285 -            vendor = 'linux'
      1286 -        elif 'ruijie' in dt:
      1287 -            vendor = 'ruijie'
      1288 -    vendor_oids = OID_MAPPINGS.get(vendor, {})
      1289 -    def try_oids(metric):
      1290 -        for oid in vendor_oids.get(metric, []):
      1291 -            val = snmp_get(ip, community, version, oid, timeout=3)
      1292 -            if val is not None:
      1293 -                return val
      1294 -        for oid in FALLBACK_OIDS.get(metric, []):
      1295 -            val = snmp_get(ip, community, version, oid, timeout=3)
      1296 -            if val is not None:
      1297 -                return val
      1298 -        return None
      1299 -    def to_float(v):
      1300 -        try:
      1301 -            return float(v) if v is not None else None
      1302 -        except (ValueError, TypeError):
      1303 -            return None
      1304 -    result = {k: None for k in ['cpu_usage', 'memory_usage', 'disk_usage', 'temperature', 'power_cons
           -umption', 'power_supply']}
      1305 -    cpu = try_oids('cpu_usage')
      1306 -    result['cpu_usage'] = to_float(cpu)
      1307 -    mem = try_oids('memory_usage')
      1308 -    if mem is not None:
      1309 -        if vendor == 'linux':
      1310 -            total = snmp_get(ip, community, version, '1.3.6.1.4.1.2021.4.5.0', 3)
      1311 -            if total:
      1312 -                total_f = to_float(total)
      1313 -                mem_f = to_float(mem)
      1314 -                if total_f and mem_f is not None:
      1315 -                    result['memory_usage'] = ((total_f - mem_f) / total_f) * 100
      1316 -        elif vendor == 'cisco':
      1317 -            total = snmp_get(ip, community, version, '1.3.6.1.4.1.9.9.48.1.1.1.4.1', 3)
      1318 -            if total:
      1319 -                total_f = to_float(total)
      1320 -                mem_f = to_float(mem)
      1321 -                if total_f and mem_f is not None:
      1322 -                    result['memory_usage'] = (mem_f / total_f) * 100
      1323 -        else:
      1324 -            result['memory_usage'] = to_float(mem)
      1325 -    disk = try_oids('disk_usage')
      1326 -    if disk is not None:
      1327 -        if vendor == 'linux':
      1328 -            total = snmp_get(ip, community, version, '1.3.6.1.4.1.2021.9.1.8.1', 3)
      1329 -            if total:
      1330 -                total_f = to_float(total)
      1331 -                disk_f = to_float(disk)
      1332 -                if total_f and disk_f is not None:
      1333 -                    result['disk_usage'] = (disk_f / total_f) * 100
      1334 -        elif vendor == 'cisco':
      1335 -            total = snmp_get(ip, community, version, '1.3.6.1.4.1.9.9.10.1.1.4.1.4.1', 3)
      1336 -            if total:
      1337 -                total_f = to_float(total)
      1338 -                disk_f = to_float(disk)
      1339 -                if total_f and disk_f is not None:
      1340 -                    result['disk_usage'] = ((total_f - disk_f) / total_f) * 100
      1341 -        else:
      1342 -            result['disk_usage'] = to_float(disk)
      1343 -    temp = try_oids('temperature')
      1344 -    result['temperature'] = to_float(temp)
      1345 -    power = try_oids('power_consumption')
      1346 -    result['power_consumption'] = to_float(power)
      1347 -    ps = try_oids('power_supply')
      1348 -    if ps is not None:
      1349 -        ps_float = to_float(ps)
      1350 -        if ps_float == 1:
      1351 -            result['power_supply'] = '正常'
      1352 -        elif ps_float == 2:
      1353 -            result['power_supply'] = '故障'
      1354 -        else:
      1355 -            result['power_supply'] = str(ps)
      1356 -    return result
      1357 -
      1358 -# 为了兼容旧代码，保留一些别名或旧函数名
      1359 -def snmp_get_with_timeout(ip, community, version, oid, timeout=SNMP_TIMEOUT):
      1360 -    """兼容旧接口，直接调用 snmp_get"""
      1361 -    return snmp_get(ip, community, version, oid, timeout)
      1362 -
      1363 -# ---------- 结束 ----------
      1364 -
      1365 -# utils.py 新增
      1366 -
      1367 -
        76  def send_email(recipients, subject, body):
      1369 -    # 从配置读取 SMTP 信息
        77 +    """简单SMTP邮件发送"""
        78      smtp_server = current_app.config.get('SMTP_SERVER')
        79      smtp_port = current_app.config.get('SMTP_PORT')
        80      smtp_user = current_app.config.get('SMTP_USER')
     ...
        88          server.login(smtp_user, smtp_password)
        89          server.sendmail(smtp_user, recipients, msg.as_string())
        90
        91 +
        92  def send_dingtalk(webhook_url, message):
        93 +    """钉钉机器人消息推送"""
        94      import requests
        95      data = {"msgtype": "text", "text": {"content": message}}
        96      requests.post(webhook_url, json=data)
        97
      1388 -def log_activity(type, name, action, status='成功', status_color='success',
        98 +
        99 +def log_activity(type, name, action, status='成功', status_color='success',
       100                   user=None, detail='', device_type=None):
       101      """写入活动日志"""
       102 +    from models.models import ActivityLog
       103 +
       104      try:
       105          if not user and hasattr(current_user, 'username'):
       106              user = current_user.username
       107          else:
       108              user = user or '系统'
      1396 -    except:
       109 +    except Exception:
       110          user = user or '系统'
      1398 -
       111 +
       112      log = ActivityLog(
       113          type=type,
       114          device_type=device_type if type == 'device' else None,
     ...
       120          detail=detail
       121      )
       122      db.session.add(log)
      1410 -    db.session.commit()
       123   No newline at end of file
       124 +    db.session.commit()

● Let me verify the imports work by running a quick test.

● Bash(cd "D:/asset" && python -c "
      from utils.utils import (…)
  ⎿  models/models.py �е� db ʵ�� ID: 1942528280976
     models/models.py �е� db.Model ����: <class 'sqlalchemy.orm.decl_api.Model'>
     models/models.py �е� registry ID: 1942528204624
     … +4 lines (ctrl+o to expand)

● Bash(cd "D:/asset" && python -c "
      import os…)
  ⎿  models/models.py �е� db ʵ�� ID: 2641738072144
     models/models.py �е� db.Model ����: <class 'sqlalchemy.orm.decl_api.Model'>
     models/models.py �е� registry ID: 2641738043472
     … +6 lines (ctrl+o to expand)

● All done with this batch. Here's what was accomplished:

  Completed refactoring:
  1. Scheduler cleanup (scheduler.py) — Removed monitor_connections_job and link_health_check_job (redundant cron),
  changed link_monitor_job interval from 60s to 120s
  2. Removed independent checker_thread (app.py, app_init.py) — Deleted the standalone check_topology_periodically
  thread, now fully managed by APScheduler
  3. Batch DB commits (tasks/link_monitor.py) — Removed per-record db.session.commit() from update_connection_status,
  create_link_down_alert, clear_link_down_alert, and discover_links_via_lldp. Single commit at end of batch operations    instead
  4. Split utils/utils.py (1409 → split into 3 modules):                                                                    - utils/network_utils.py — ping, IP, network functions
    - utils/snmp_utils.py — SNMP get/walk, device info, interface discovery
    - utils/excel_utils.py — Excel import/export
    - utils/utils.py — re-exports from submodules + remaining utility functions

  App starts and imports verified working.