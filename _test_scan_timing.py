"""验证 check_all_devices_status 的并发编排：925 台（含离线慢设备）能否在预算内跑完且不抛 TimeoutError。"""
import sys, time, random, contextlib
sys.path.insert(0, r"D:\asset")

import utils.tasks as T

# ---- 构造 925 台模拟设备：30% 离线(慢~8s)，70% 在线(快~0.5s) ----
class FakeDev:
    def __init__(self, i):
        self.id = i
        self.name = f"dev-{i}"
        self.management_ip = f"10.0.{(i//254)%254}.{i%254}"
        self.ip_address = None
        self.snmp_community = "public"
        self.snmp_version = "2c"

DEVS = [FakeDev(i) for i in range(925)]

class FakeQuery:
    def filter_by(self, **kw): return self
    def all(self): return DEVS

class FakeDevice:
    query = FakeQuery()

# patch Device
T.Device = FakeDevice

# patch check_device_status -> 模拟网络耗时
def fake_check(app, device_id, snap):
    offline = (device_id % 10) < 3          # 30% 离线
    dur = random.uniform(7.0, 8.5) if offline else random.uniform(0.2, 0.6)
    time.sleep(dur)
    return None

T.check_device_status = fake_check

# fake app：app_context 为 no-op
class FakeApp:
    @contextlib.contextmanager
    def app_context(self):
        yield

app = FakeApp()

start = time.time()
try:
    T.check_all_devices_status(app)
    print(f"[PASS] 未抛异常，总耗时 {time.time()-start:.1f}s")
except Exception as e:
    import traceback; traceback.print_exc()
    print(f"[FAIL] 抛出异常: {e}")
    sys.exit(1)
