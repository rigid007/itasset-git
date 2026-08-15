修复总结

  在 E:\asset\blueprints\topology.py 中修复了 3 个问题，导致 LLDP 拓扑发现无法进行多级级联发现：

  问题 1（根因）：单次遍历导致新邻居不被处理

  位置：run_protocol_discovery() — 原第 1186-1243 行

  原代码只在线程池中提交了初始 scan_queue 中的种子 IP。邻居 IP 虽然被追加到 scan_queue（第 1243 行），但 for ip, depth
  in scan_queue 循环早已结束，新 IP 永远不会被提交。

  修复：将单次遍历改为 多轮 BFS 发现：
  - 每轮提交所有待处理的 IP
  - 等待本轮全部完成
  - 收集新发现的邻居 IP 加入队列
  - 如果发现新邻居且未超过 max_depth，继续下一轮
  - 直到没有新邻居或达到最大深度时结束

  问题 2：addr_map 键类型不匹配

  位置：resolve_neighbor_ip_enhanced() — 原第 2427-2431 行

  get_lldp_management_addresses() 返回的字典键是 (time_mark, remote_index) 元组，但查找时用的是单个字符串
  remote_idx。remote_idx in addr_map 永远为 False，导致 LLDP 管理地址解析静默失败。

  修复：遍历 addr_map 元组键，按 remote_idx 匹配元组中的第二个元素。

  问题 3：重复解析覆盖名称匹配结果

  位置：LLDP 邻居处理 — 原第 1073-1083 行

  代码在名称匹配兜底逻辑（第 1029-1071 行）之后，又重复调用了一次 resolve_neighbor_ip_enhanced() 和
  extract_mac_from_chassis()，会覆盖通过名称匹配找到的 IP/MAC。

  修复：删除重复的解析代码块。



> [协议发现] 192.168.200.20 使用数据库 community: public
  Traceback (most recent call last):
    File "e:\asset\blueprints\topology.py", line 1214, in run_protocol_discovery
      result = future.result(timeout=60)
               ^^^^^^^^^^^^^^^^^^^^^^^^^
    File "C:\Users\lenovo\AppData\Local\Programs\Python\Python311\Lib\concurrent\futures\_base.py", line 449, in result
      return self.__get_result()
             ^^^^^^^^^^^^^^^^^^^
    File "C:\Users\lenovo\AppData\Local\Programs\Python\Python311\Lib\concurrent\futures\_base.py", line 401, in
  __get_result
      raise self._exception
    File "C:\Users\lenovo\AppData\Local\Programs\Python\Python311\Lib\concurrent\futures\thread.py", line 58, in run
      result = self.fn(*self.args, **self.kwargs)
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    File "e:\asset\blueprints\topology.py", line 949, in discover_device
      if ip in discovered_ips or depth > task.max_depth:
                                         ^^^^^^^^^^^^^^

  Thought for 17s, read 1 file (ctrl+o to expand)

● The error traceback is incomplete — let me see what the actual exception is and check the current state of
  discover_device:

  Thought for 12s, read 1 file (ctrl+o to expand)

● The issue is at line 949 — task.max_depth can be None if the DB record has a NULL value, causing TypeError: '>' not
  supported between instances of 'int' and 'NoneType'. The new code at line 1183 already uses task.max_depth or 3 but
  the inner function still uses the raw attribute.

● Update(blueprints\topology.py)
  ⎿  Added 1 line, removed 1 line
      946          """单个设备的发现任务"""
      947          # ===== 使用传入的 app 创建上下文 =====
      948          with app.app_context():
      949 -            if ip in discovered_ips or depth > task.max_depth:
      949 +            if ip in discovered_ips or depth > (task.max_depth or 3):
      950                  return None
      951
      952              # 从数据库获取设备

  Thought for 6s (ctrl+o to expand)

● 现在让我也检查是否有其他地方直接使用 task.max_depth 而没有回退值：

  Thought for 2s, searched for 1 pattern (ctrl+o to expand)

● Line 940 could also fail if task.max_depth is None:

● Update(blueprints\topology.py)
  ⎿  Added 1 line, removed 1 line
      937      discovered_ips = set()
      938      all_interfaces = {}
      939      all_connections = []
      940 -    total_steps = max(len(scan_queue) * task.max_depth, 1)
      940 +    total_steps = max(len(scan_queue) * (task.max_depth or 3), 1)
      941      step = 0
      942
      943      # ========== 单个设备发现函数 ==========

  Thought for 3s (ctrl+o to expand)

● 已修复。错误原因是 task.max_depth 在数据库记录中为 NULL 时会被加载为 None，导致：

  - 第 949 行：depth > None → TypeError
  - 第 940 行：len(scan_queue) * None → TypeError

  两处都加了 or 3 兜底值。可以重新运行测试了。

✻ Sautéed for 50s




> [协议发现] 192.168.200.20 使用数据库 community: public
  Traceback (most recent call last):
    File "e:\asset\blueprints\topology.py", line 1214, in run_protocol_discovery
      result = future.result(timeout=60)
               ^^^^^^^^^^^^^^^^^^^^^^^^^
    File "C:\Users\lenovo\AppData\Local\Programs\Python\Python311\Lib\concurrent\futures\_base.py", line 449, in result
      return self.__get_result()
             ^^^^^^^^^^^^^^^^^^^
    File "C:\Users\lenovo\AppData\Local\Programs\Python\Python311\Lib\concurrent\futures\_base.py", line 401, in
  __get_result
      raise self._exception
    File "C:\Users\lenovo\AppData\Local\Programs\Python\Python311\Lib\concurrent\futures\thread.py", line 58, in run
      result = self.fn(*self.args, **self.kwargs)
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    File "e:\asset\blueprints\topology.py", line 949, in discover_device
      if ip in discovered_ips or depth > task.max_depth:
                                         ^^^^^^^^^^^^^^

  Thought for 17s, read 1 file (ctrl+o to expand)

● The error traceback is incomplete — let me see what the actual exception is and check the current state of
  discover_device:

  Thought for 12s, read 1 file (ctrl+o to expand)

● The issue is at line 949 — task.max_depth can be None if the DB record has a NULL value, causing TypeError: '>' not
  supported between instances of 'int' and 'NoneType'. The new code at line 1183 already uses task.max_depth or 3 but
  the inner function still uses the raw attribute.

● Update(blueprints\topology.py)
  ⎿  Added 1 line, removed 1 line
      946          """单个设备的发现任务"""
      947          # ===== 使用传入的 app 创建上下文 =====
      948          with app.app_context():
      949 -            if ip in discovered_ips or depth > task.max_depth:
      949 +            if ip in discovered_ips or depth > (task.max_depth or 3):
      950                  return None
      951
      952              # 从数据库获取设备

  Thought for 6s (ctrl+o to expand)

● 现在让我也检查是否有其他地方直接使用 task.max_depth 而没有回退值：

  Thought for 2s, searched for 1 pattern (ctrl+o to expand)

● Line 940 could also fail if task.max_depth is None:

● Update(blueprints\topology.py)
  ⎿  Added 1 line, removed 1 line
      937      discovered_ips = set()
      938      all_interfaces = {}
      939      all_connections = []
      940 -    total_steps = max(len(scan_queue) * task.max_depth, 1)
      940 +    total_steps = max(len(scan_queue) * (task.max_depth or 3), 1)
      941      step = 0
      942
      943      # ========== 单个设备发现函数 ==========

  Thought for 3s (ctrl+o to expand)

● 已修复。错误原因是 task.max_depth 在数据库记录中为 NULL 时会被加载为 None，导致：

  - 第 949 行：depth > None → TypeError
  - 第 940 行：len(scan_queue) * None → TypeError

  两处都加了 or 3 兜底值。可以重新运行测试了。

✻ Sautéed for 50s

────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
> Traceback (most recent call last):
    File "e:\asset\blueprints\topology.py", line 1214, in run_protocol_discovery
      result = future.result(timeout=60)
               ^^^^^^^^^^^^^^^^^^^^^^^^^
    File "C:\Users\lenovo\AppData\Local\Programs\Python\Python311\Lib\concurrent\futures\_base.py", line 449, in
  result
      return self.__get_result()
             ^^^^^^^^^^^^^^^^^^^
    File "C:\Users\lenovo\AppData\Local\Programs\Python\Python311\Lib\concurrent\futures\_base.py", line 401, in
  __get_result
      raise self._exception
    File "C:\Users\lenovo\AppData\Local\Programs\Python\Python311\Lib\concurrent\futures\thread.py", line 58, in run
      result = self.fn(*self.args, **self.kwargs)
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    File "e:\asset\blueprints\topology.py", line 949, in discover_device
      if ip in discovered_ips or depth > (task.max_depth or 3):
                                          ^^^^^^^^^^^^^^
    File "C:\Users\lenovo\AppData\Local\Programs\Python\Python311\Lib\site-packages\sqlalchemy\orm\attributes.py",
  line 569, in __get__
      return self.impl.get(state, dict_)  # type: ignore[no-any-return]
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^
    File "C:\Users\lenovo\AppData\Local\Programs\Python\Python311\Lib\site-packages\sqlalchemy\orm\attributes.py",
  line 1096, in get
      value = self._fire_loader_callables(state, key, passive)
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    File "C:\Users\lenovo\AppData\Local\Programs\Python\Python311\Lib\site-packages\sqlalchemy\orm\attributes.py",
  line 1126, in _fire_loader_callables
      return state._load_expired(state, passive)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    File "C:\Users\lenovo\AppData\Local\Programs\Python\Python311\Lib\site-packages\sqlalchemy\orm\state.py", line
  828, in _load_expired
      self.manager.expired_attribute_loader(self, toload, passive)
    File "C:\Users\lenovo\AppData\Local\Programs\Python\Python311\Lib\site-packages\sqlalchemy\orm\loading.py", line
  1674, in load_scalar_attributes
      result = load_on_ident(
               ^^^^^^^^^^^^^^
    File "C:\Users\lenovo\AppData\Local\Programs\Python\Python311\Lib\site-packages\sqlalchemy\orm\loading.py", line
  510, in load_on_ident
      return load_on_pk_identity(
  695, in load_on_pk_identity
      session.execute(
    File "C:\Users\lenovo\AppData\Local\Programs\Python\Python311\Lib\site-packages\sqlalchemy\orm\session.py", line
  2351, in execute
      return self._execute_internal(
             ^^^^^^^^^^^^^^^^^^^^^^^
    File "C:\Users\lenovo\AppData\Local\Programs\Python\Python311\Lib\site-packages\sqlalchemy\orm\session.py", line
  2239, in _execute_internal
      conn = self._connection_for_bind(bind)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    File "C:\Users\lenovo\AppData\Local\Programs\Python\Python311\Lib\site-packages\sqlalchemy\orm\session.py", line
  2108, in _connection_for_bind
      return trans._connection_for_bind(engine, execution_options)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    File "<string>", line 2, in _connection_for_bind
    File "C:\Users\lenovo\AppData\Local\Programs\Python\Python311\Lib\site-packages\sqlalchemy\orm\state_changes.py",
  line 101, in _go
      self._raise_for_prerequisite_state(fn.__name__, current_state)
    File "C:\Users\lenovo\AppData\Local\Programs\Python\Python311\Lib\site-packages\sqlalchemy\orm\session.py", line
  988, in _raise_for_prerequisite_state
      raise sa_exc.InvalidRequestError(
  sqlalchemy.exc.InvalidRequestError: This session is provisioning a new connection; concurrent operations are not
  permitted (Background on this error at: https://sqlalche.me/e/20/isce)
  [协议发现] 192.168.200.20 SNMP服务可用，开始发现
  127.0.0.1 - - [21/Jul/2026 10:21:28] "GET /topology/api/discovery/tasks HTTP/1.1" 200 -

  Thought for 25s, read 1 file (ctrl+o to expand)

● 这是 SQLAlchemy 多线程并发会话问题。task 对象在主线程加载，但工作线程访问 task.max_depth
  时会触发懒加载，而工作线程没有自己的数据库连接，导致并发冲突。

  修复方案：在进入线程池之前，先把 task 的属性提取为普通变量，避免跨线程访问 ORM 对象。

  Thought for 2s, read 1 file (ctrl+o to expand)

● The root cause is clear: task is an ORM object, and when worker threads access task.max_depth / task.snmp_community /
  task.use_lldp / task.use_cdp / task.auto_save / task.max_threads, they trigger cross-thread lazy loading on the
  expired session.

  The fix: extract all task attributes into local variables before defining discover_device and entering the thread
  pool.

● Update(blueprints\topology.py)
  ⎿  Added 11 lines, removed 1 line
      937      discovered_ips = set()
      938      all_interfaces = {}
      939      all_connections = []
      940 -    total_steps = max(len(scan_queue) * (task.max_depth or 3), 1)
      940 +
      941 +    # ========== 预先提取 task 属性（避免跨线程 ORM 懒加载） ==========
      942 +    max_depth = task.max_depth or 3
      943 +    snmp_community = task.snmp_community or 'public'
      944 +    use_lldp = task.use_lldp
      945 +    use_cdp = task.use_cdp
      946 +    use_snmp_mac = getattr(task, 'use_snmp_mac', True)
      947 +    max_threads = task.max_threads or 5
      948 +    auto_save = task.auto_save
      949 +
      950 +    total_steps = max(len(scan_queue) * max_depth, 1)
      951      step = 0
      952
      953      # ========== 单个设备发现函数 ==========

  Thought for 2s (ctrl+o to expand)

● 现在把 discover_device 里所有的 task.xxx 替换为局部变量：

● Update(blueprints\topology.py)
  ⎿  Added 1 line, removed 1 line
      956          """单个设备的发现任务"""
      957          # ===== 使用传入的 app 创建上下文 =====
      958          with app.app_context():
      959 -            if ip in discovered_ips or depth > (task.max_depth or 3):
      959 +            if ip in discovered_ips or depth > max_depth:
      960                  return None
      961
      962              # 从数据库获取设备

  Thought for 12s, searched for 1 pattern, read 1 file (ctrl+o to expand)

● Update(blueprints\topology.py)
  ⎿  Added 1 line, removed 1 line
      965              ).first()
      966
      967              # 优先使用数据库中存储的 community
      968 -            community = task.snmp_community
      968 +            community = snmp_community
      969              if device and device.snmp_community:
      970                  community = device.snmp_community
      971                  print(f"[协议发现] {ip} 使用数据库 community: {community}")

  Thought for 2s (ctrl+o to expand)

● Update(blueprints\topology.py)
  ⎿  Added 1 line, removed 1 line
      1005                  print(f"[协议发现] {ip} 接口发现失败: {e}")
      1006
      1007              # 2. LLDP 发现
      1008 -            if task.use_lldp:
      1008 +            if use_lldp:
      1009                  try:
      1010                      lldp_neighbors = discover_lldp_neighbors(ip, community)
      1011                      print(f"[LLDP] 从 {ip} 发现 {len(lldp_neighbors)} 个邻居")

● Update(blueprints\topology.py)
  ⎿  Added 1 line, removed 1 line
      1109                      print(f"[LLDP] {ip} 发现失败: {e}")
      1110
      1111              # 3. CDP 发现
      1112 -            if task.use_cdp:
      1112 +            if use_cdp:
      1113                  try:
      1114                      cdp_neighbors = discover_cdp_neighbors(ip, community)
      1115                      print(f"[CDP] 从 {ip} 发现 {len(cdp_neighbors)} 个邻居")

  Thought for 4s, searched for 1 pattern (ctrl+o to expand)

● Update(blueprints\topology.py)
  ⎿  Added 1 line, removed 1 line
      1142                      print(f"[CDP] {ip} 发现失败: {e}")
      1143
      1144              # 4. SNMP MAC 发现
      1145 -            if getattr(task, 'use_snmp_mac', True):
      1145 +            if use_snmp_mac:
      1146                  try:
      1147                      mac_neighbors = discover_neighbors_via_snmp_mac(ip, community, interface_map)
      1148                      print(f"[SNMP MAC] 从 {ip} 发现 {len(mac_neighbors)} 个邻居")

  Thought for 22s, searched for 2 patterns, read 1 file (ctrl+o to expand)

● Line 1242 and 1338 are in the background thread (same thread that loaded task), so they should be safe there. But for
  consistency let me also update them to use the local variable:

● Update(blueprints\topology.py)
  ⎿  Added 1 line, removed 1 line
      1239                          device = Device.query.filter(
      1240                              (Device.management_ip == ip) | (Device.ip_address == ip)
      1241                          ).first()
      1242 -                        if device and task.auto_save:
      1242 +                        if device and auto_save:
      1243                              for iface in result['interfaces']:
      1244                                  existing = Interface.query.filter_by(
      1245                                      device_id=device.id,

  Thought for 1s (ctrl+o to expand)

● Update(blueprints\topology.py)
  ⎿  Added 1 line, removed 1 line
      1335      db.session.commit()
      1336
      1337      # ========== 保存结果 ==========
      1338 -    if task.auto_save:
      1338 +    if auto_save:
      1339          valid_connections = []
      1340          for conn in all_connections:
      1341              has_ip = conn.get('target_ip') and is_valid_target_ip(conn['target_ip'])

  Thought for 4s, searched for 1 pattern (ctrl+o to expand)

● Update(blueprints\topology.py)
  ⎿  Added 1 line, removed 1 line
      1177      # ========== 使用线程池多轮并发发现（BFS） ==========
      1178      # 解决级联交换机多级发现问题：每轮发现一批设备的邻居，
      1179      # 将新发现的邻居IP加入队列，下一轮继续发现，直到没有新邻居或达到最大深度
      1180 -    max_workers = min(task.max_threads or 5, 10)
      1180 +    max_workers = min(max_threads, 10)
      1181      max_depth = task.max_depth or 3  # 默认最大深度3
      1182      print(f"[协议发现] 使用 {max_workers} 个并发线程，最大深度 {max_depth}")
      1183

  Thought for 1s, searched for 1 pattern (ctrl+o to expand)

● Now check for the duplicate max_depth that was introduced by the earlier BFS fix:

  Thought for 2s, searched for 1 pattern, read 1 file (ctrl+o to expand)

● Line 942 already extracted max_depth, and line 1181 is a duplicate that still references task.max_depth. Remove it:

  Read 1 file (ctrl+o to expand)

● Update(blueprints\topology.py)
  ⎿  Removed 1 line
      1178      # 解决级联交换机多级发现问题：每轮发现一批设备的邻居，
      1179      # 将新发现的邻居IP加入队列，下一轮继续发现，直到没有新邻居或达到最大深度
      1180      max_workers = min(max_threads, 10)
      1181 -    max_depth = task.max_depth or 3  # 默认最大深度3
      1181      print(f"[协议发现] 使用 {max_workers} 个并发线程，最大深度 {max_depth}")
      1182
      1183      with ThreadPoolExecutor(max_workers=max_workers) as executor:

  Thought for 2s, read 1 file (ctrl+o to expand)

● Now let me verify there are no more task. ORM attribute accesses left in the discovery thread:

  Thought for 2s, read 1 file (ctrl+o to expand)

● discover_device 内部已经完全没有 task.* 引用了。让我也确认 BFS 循环区域没问题：

  Thought for 5s, searched for 1 pattern, read 1 file (ctrl+o to expand)

● I see task.progress at line 1232 — this is in the background thread body (not a worker thread), so it's safe. Let me
  verify the function is completely clean now by checking for any remaining task. accesses between discover_device
  definition and the BFS loop end:

  Thought for 6s, searched for 2 patterns (ctrl+o to expand)

● 所有 task.* 引用都在安全的位置（要么在预提取代码中，要么在后台线程主体中）。discover_device 里已经完全没有 ORM
  属性访问了。

  修复总结：

  1. 第 941-948 行：进入线程池前预提取所有 task 属性到局部变量
  2. discover_device 内部：所有 task.max_depth、task.snmp_community、task.use_lldp、task.use_cdp、task.auto_save
  替换为对应的局部变量
  3. 第 1180 行：task.max_threads 替换为 max_threads
  4. 删除了重复的 max_depth = task.max_depth or 3

  可以重新运行测试了。