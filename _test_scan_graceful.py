"""确定性验证 check_all_devices_status 的优雅降级：as_completed 立即抛 TimeoutError 时，
函数必须吞掉异常、不阻塞、正常返回（不拖垮调度器）。"""
import sys, contextlib
sys.path.insert(0, r"D:\asset")

import utils.tasks as T

class FakeDev:
    def __init__(self, i):
        self.id = i; self.name = f"d{i}"
        self.management_ip = f"10.0.0.{i}"; self.ip_address = None
        self.snmp_community = "public"; self.snmp_version = "2c"
DEVS = [FakeDev(i) for i in range(925)]

class FakeQuery:
    def filter_by(self, **kw): return self
    def all(self): return DEVS
class FakeDevice: query = FakeQuery()
T.Device = FakeDevice

# fake executor/future
class FakeFuture:
    def done(self): return False
    def result(self, timeout=None): return None
class FakeExecutor:
    def submit(self, fn, *a, **k): return FakeFuture()
    def shutdown(self, wait=False): FakeExecutor.shutdown_called = wait
T.ThreadPoolExecutor = lambda max_workers: FakeExecutor()

# as_completed 立即抛 TimeoutError，模拟全局预算耗尽
def boom(*a, **k):
    raise T.TimeoutError("simulated global timeout")
T.as_completed = boom

# check_device_status 不会被调用（as_completed 先抛）
T.check_device_status = lambda *a, **k: None

class FakeApp:
    @contextlib.contextmanager
    def app_context(self): yield

import time
t0 = time.time()
try:
    T.check_all_devices_status(FakeApp())
    print(f"[PASS] 优雅降级：未向上抛异常，返回耗时 {time.time()-t0:.2f}s")
    print(f"       shutdown(wait=False) 生效: {getattr(FakeExecutor,'shutdown_called', 'NOT CALLED')}")
except Exception as e:
    import traceback; traceback.print_exc()
    print(f"[FAIL] 异常外泄: {e}"); sys.exit(1)
