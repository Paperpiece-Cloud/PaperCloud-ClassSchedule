"""系统状态采集（Windows）。

只依赖 Python 标准库 + ctypes 调 Win32 API，不引入 psutil 之类的第三方包 ——
这个项目从第一天起就是零依赖，方便拷到任何一台机器上直接跑。

采集内容：
    CPU 使用率      GetSystemTimes（两次采样求差值，累计值是没意义的）
    内存占用        GlobalMemoryStatusEx
    磁盘占用        shutil.disk_usage
    进程数          EnumProcesses
    开机时长        GetTickCount64
    本机负载        当前进程的 CPU / 内存 + 线程数

CPU 必须两次采样才能算出来，所以后台起一个线程每隔几秒采一次，
API 直接返回最近一次的结果，不给请求加延迟。
"""

import ctypes
import os
import re
import shutil
import threading
import time
from ctypes import wintypes

IS_WINDOWS = os.name == "nt"

# ---------------------------------------------------------------- Win32 结构

if IS_WINDOWS:
    class _FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", wintypes.DWORD),
                    ("dwHighDateTime", wintypes.DWORD)]

    class _MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", wintypes.DWORD),
                    ("dwMemoryLoad", wintypes.DWORD),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

    _k32 = ctypes.windll.kernel32
    _psapi = ctypes.windll.psapi


def _ft_int(ft):
    return (ft.dwHighDateTime << 32) | ft.dwLowDateTime


def _cpu_times():
    """返回 (idle, kernel, user) 的累计值；失败返回 None。"""
    if not IS_WINDOWS:
        return None
    try:
        idle, kern, user = _FILETIME(), _FILETIME(), _FILETIME()
        if not _k32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern),
                                   ctypes.byref(user)):
            return None
        return (_ft_int(idle), _ft_int(kern), _ft_int(user))
    except Exception:
        return None


def _memory():
    if not IS_WINDOWS:
        return None
    try:
        m = _MEMORYSTATUSEX()
        m.dwLength = ctypes.sizeof(m)
        if not _k32.GlobalMemoryStatusEx(ctypes.byref(m)):
            return None
        total = m.ullTotalPhys
        avail = m.ullAvailPhys
        used = total - avail
        return {
            "totalGB": round(total / 2 ** 30, 1),
            "usedGB": round(used / 2 ** 30, 1),
            "freeGB": round(avail / 2 ** 30, 1),
            "percent": int(m.dwMemoryLoad),
        }
    except Exception:
        return None


def _process_count():
    if not IS_WINDOWS:
        return None
    try:
        arr = (wintypes.DWORD * 2048)()
        need = wintypes.DWORD()
        if not _psapi.EnumProcesses(ctypes.byref(arr), ctypes.sizeof(arr),
                                    ctypes.byref(need)):
            return None
        n = need.value // ctypes.sizeof(wintypes.DWORD)
        # 空槽位的 PID 是 0，要减掉
        return sum(1 for i in range(n) if arr[i])
    except Exception:
        return None


def _boot_seconds():
    if not IS_WINDOWS:
        return None
    try:
        return int(_k32.GetTickCount64() / 1000)
    except Exception:
        return None


def _disks():
    out = []
    for letter in "CDEFGH":
        root = letter + ":\\"
        if not os.path.exists(root):
            continue
        try:
            t, u, f = shutil.disk_usage(root)
            if t <= 0:
                continue
            out.append({
                "drive": letter + ":",
                "totalGB": round(t / 2 ** 30, 1),
                "usedGB": round(u / 2 ** 30, 1),
                "freeGB": round(f / 2 ** 30, 1),
                "percent": int(round(u / t * 100)),
            })
        except Exception:
            pass
    return out


def _self_stats():
    """本进程自己的开销 —— 顺便看看这个服务占了多少资源。"""
    try:
        import ctypes as c
        pid = os.getpid()
        PROCESS_MEMORY_COUNTERS = type("PMC", (c.Structure,), {
            "_fields_": [("cb", wintypes.DWORD),
                         ("PageFaultCount", wintypes.DWORD),
                         ("PeakWorkingSetSize", c.c_size_t),
                         ("WorkingSetSize", c.c_size_t),
                         ("QuotaPeakPagedPoolUsage", c.c_size_t),
                         ("QuotaPagedPoolUsage", c.c_size_t),
                         ("QuotaPeakNonPagedPoolUsage", c.c_size_t),
                         ("QuotaNonPagedPoolUsage", c.c_size_t),
                         ("PagefileUsage", c.c_size_t),
                         ("PeakPagefileUsage", c.c_size_t)]})
        h = _k32.OpenProcess(0x0400 | 0x0010, False, pid)  # QUERY_INFO | VM_READ
        if not h:
            return None
        pmc = PROCESS_MEMORY_COUNTERS()
        pmc.cb = c.sizeof(pmc)
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(h, c.byref(pmc), pmc.cb)
        _k32.CloseHandle(h)
        if not ok:
            return None
        return {"pid": pid, "memMB": round(pmc.WorkingSetSize / 2 ** 20, 1)}
    except Exception:
        return None


# ---------------------------------------------------------------- GPU（PDH）

if IS_WINDOWS:
    class _PDH_FMT_COUNTERVALUE(ctypes.Structure):
        _fields_ = [("CStatus", wintypes.DWORD),
                    ("doubleValue", ctypes.c_double)]

    class _PDH_FMT_COUNTERVALUE_ITEM_W(ctypes.Structure):
        _fields_ = [("szName", ctypes.c_wchar_p),
                    ("FmtValue", _PDH_FMT_COUNTERVALUE)]

    _pdh = ctypes.windll.pdh

    # 必须显式声明返回值为无符号。
    # PDH_MORE_DATA 是 0x800007D2，按默认的有符号 int 返回会变成负数，
    # 于是 rc != PDH_MORE_DATA 永远成立，函数会一直返回空数组、GPU 永远是 None。
    for _fn in ("PdhOpenQueryW", "PdhAddEnglishCounterW",
                "PdhCollectQueryData", "PdhGetFormattedCounterArrayW",
                "PdhCloseQuery"):
        try:
            getattr(_pdh, _fn).restype = ctypes.c_ulong
        except Exception:
            pass

PDH_FMT_DOUBLE = 0x00000200
PDH_MORE_DATA = 0x800007D2


_LUID_RE = re.compile(r"luid_0x([0-9A-Fa-f]+)_0x([0-9A-Fa-f]+)")


def _luid_of(instance_name):
    """从 PDH 实例名里抽出 LUID。

    实例名长这样：
        pid_7888_luid_0x00000000_0x000110C0_phys_0_eng_0_engtype_3D
    返回 (high, low)。
    """
    m = _LUID_RE.search(instance_name or "")
    if not m:
        return (None, None)
    return (int(m.group(1), 16), int(m.group(2), 16))


def _registry_gpus():
    """注册表里的显卡列表（DXGI 失败时的兜底）。

    注意：这里会有虚拟适配器（MuMu、Remote Display 之类），
    所以只当兜底，正常走 DXGI。
    """
    out = []
    try:
        import winreg
        key = (r"SYSTEM\CurrentControlSet\Control\Class"
               r"\{4d36e968-e325-11ce-bfc1-08002be10318}")
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as k:
            for i in range(16):
                try:
                    with winreg.OpenKey(k, "%04d" % i) as sub:
                        v, _ = winreg.QueryValueEx(sub, "DriverDesc")
                        if v:
                            out.append({"name": str(v), "luidLow": None,
                                        "luidHigh": None, "vramMB": 0,
                                        "vendorId": 0, "software": False})
                except OSError:
                    continue
    except Exception:
        pass
    return out


if IS_WINDOWS:
    class _GUID_(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    class _LUID_(ctypes.Structure):
        _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

    class _DXGI_ADAPTER_DESC1(ctypes.Structure):
        _fields_ = [("Description", ctypes.c_wchar * 128),
                    ("VendorId", wintypes.UINT), ("DeviceId", wintypes.UINT),
                    ("SubSysId", wintypes.UINT), ("Revision", wintypes.UINT),
                    ("DedicatedVideoMemory", ctypes.c_size_t),
                    ("DedicatedSystemMemory", ctypes.c_size_t),
                    ("SharedSystemMemory", ctypes.c_size_t),
                    ("AdapterLuid", _LUID_),
                    ("Flags", wintypes.UINT)]


def _com(ptr, index, restype, *argtypes):
    """取 COM 对象的第 index 个虚函数。"""
    pp = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))
    vtbl = pp[0]
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtbl[index])


def _dxgi_adapters():
    """用 DXGI 枚举真实显卡：名字 + LUID + 显存。

    为什么要走 DXGI：
        PDH 的 GPU 计数器实例名里只有 luid_0x00000000_0x000110C0 这种，
        没有人类看得懂的名字。DXGI 能把 LUID 和显卡名对上，
        这样「核显 + 独显」才能分开显示，而不是只显示第一块。

    会自动跳过软件适配器和虚拟显示适配器（MuMu / Remote Display 之类）。
    """
    out = []
    if not IS_WINDOWS:
        return out
    try:
        dxgi = ctypes.windll.dxgi
        dxgi.CreateDXGIFactory1.restype = ctypes.c_long
        dxgi.CreateDXGIFactory1.argtypes = [ctypes.c_void_p,
                                            ctypes.POINTER(ctypes.c_void_p)]
        # IID_IDXGIFactory1
        iid = _GUID_(0x770aae78, 0xf26f, 0x4dba,
                     (ctypes.c_ubyte * 8)(0xa8, 0x29, 0x25, 0x3c,
                                          0x83, 0xd1, 0xb3, 0x87))
        factory = ctypes.c_void_p()
        if dxgi.CreateDXGIFactory1(ctypes.byref(iid), ctypes.byref(factory)) != 0:
            return out
        try:
            enum = _com(factory, 12, ctypes.c_long, wintypes.UINT,
                        ctypes.POINTER(ctypes.c_void_p))
            for i in range(8):
                ad = ctypes.c_void_p()
                if enum(factory, i, ctypes.byref(ad)) != 0 or not ad:
                    break
                try:
                    get_desc = _com(ad, 10, ctypes.c_long,
                                    ctypes.POINTER(_DXGI_ADAPTER_DESC1))
                    desc = _DXGI_ADAPTER_DESC1()
                    if get_desc(ad, ctypes.byref(desc)) == 0:
                        name = (desc.Description or "").strip()
                        out.append({
                            "name": name,
                            "luidLow": int(desc.AdapterLuid.LowPart),
                            "luidHigh": int(desc.AdapterLuid.HighPart),
                            "vramMB": int(desc.DedicatedVideoMemory / 2 ** 20),
                            "vendorId": int(desc.VendorId),
                            "software": bool(desc.Flags & 2),
                        })
                finally:
                    _com(ad, 2, ctypes.c_ulong)(ad)      # Release
        finally:
            _com(factory, 2, ctypes.c_ulong)(factory)
    except Exception:
        pass
    return out


# 虚拟显示适配器：显存为 0 或者名字带这些字样，都不该当成显卡展示
_FAKE_HINTS = ("remote", "basic", "virtual", "mumu", "indirect", "mirror")


def _real_gpus():
    """DXGI 列表过滤掉虚拟适配器，并按名字合并。"""
    ads = _dxgi_adapters()
    real = [a for a in ads
            if not a["software"]
            and a["vramMB"] > 0
            and not any(h in a["name"].lower() for h in _FAKE_HINTS)]

    if not real:
        # 兜底：注册表（没有 LUID，占比只能走「全部求和」那条路）
        reg = [a for a in _registry_gpus()
               if not any(h in a["name"].lower() for h in _FAKE_HINTS)]
        return [{"name": a["name"], "vramMB": a.get("vramMB") or 0,
                 "luids": [(a.get("luidHigh"), a.get("luidLow"))]} for a in reg]

    # 同一个名字会重复出现：模拟器（MuMu 之类）会造出共用同一块物理 GPU 的
    # 虚拟适配器，结果 RTX 5050 被报了 3 次。这里按名字合并、把 LUID 收集起来，
    # 读占用时再把这些 LUID 的值加总 —— 每块卡只显示一行。
    merged, order = {}, []
    for a in real:
        n = a["name"]
        if n not in merged:
            merged[n] = {"name": n, "vramMB": a["vramMB"], "luids": []}
            order.append(n)
        merged[n]["luids"].append((a["luidHigh"], a["luidLow"]))
        merged[n]["vramMB"] = max(merged[n]["vramMB"], a["vramMB"])
    return [merged[n] for n in order]


class _GpuCounters:
    """读 Windows 的 GPU 性能计数器（PDH）。

        \\GPU Engine(*)\\Utilization Percentage     各引擎占用
        \\GPU Adapter Memory(*)\\Dedicated Usage    显存占用

    GPU Engine 实例很多（3D / Copy / VideoDecode …），一般只关心 3D 引擎，
    所以优先只统计 engtype_3D；老驱动没有 3D 实例时退回统计全部并封顶 100%。
    """

    def __init__(self):
        self.ok = False
        self.adapters = _real_gpus()
        self._q = None
        self._c_engine = None
        self._c_mem = None
        if not IS_WINDOWS:
            return
        try:
            h = wintypes.HANDLE()
            if _pdh.PdhOpenQueryW(None, 0, ctypes.byref(h)) != 0:
                return
            self._q = h
            ce, cm = wintypes.HANDLE(), wintypes.HANDLE()
            r1 = _pdh.PdhAddEnglishCounterW(
                h, r"\GPU Engine(*)\Utilization Percentage", 0, ctypes.byref(ce))
            r2 = _pdh.PdhAddEnglishCounterW(
                h, r"\GPU Adapter Memory(*)\Dedicated Usage", 0, ctypes.byref(cm))
            if r1 != 0 and r2 != 0:
                return
            self._c_engine = ce if r1 == 0 else None
            self._c_mem = cm if r2 == 0 else None
            _pdh.PdhCollectQueryData(h)      # 第一次只是建立基准
            self.ok = True
        except Exception:
            self.ok = False

    def _read_array(self, counter):
        """读通配符计数器，返回 [(实例名, 值), ...]。"""
        if not counter:
            return []
        size = wintypes.DWORD(0)
        count = wintypes.DWORD(0)
        rc = _pdh.PdhGetFormattedCounterArrayW(
            counter, PDH_FMT_DOUBLE, ctypes.byref(size), ctypes.byref(count), None)
        if rc != PDH_MORE_DATA or size.value == 0:
            return []
        buf = ctypes.create_string_buffer(size.value)
        rc = _pdh.PdhGetFormattedCounterArrayW(
            counter, PDH_FMT_DOUBLE, ctypes.byref(size), ctypes.byref(count), buf)
        if rc != 0:
            return []
        items = ctypes.cast(buf, ctypes.POINTER(_PDH_FMT_COUNTERVALUE_ITEM_W))
        out = []
        for i in range(count.value):
            it = items[i]
            if it.FmtValue.CStatus == 0:
                out.append((it.szName or "", it.FmtValue.doubleValue))
        return out

    def read(self):
        """返回每块显卡的占用 [{name, percent, memMB, vramMB}, ...]。

        关键：PDH 实例名里带着 luid_0x<high>_0x<low>，
        按 LUID 把实例归到对应显卡上，核显和独显才能分开显示。
        """
        if not self.ok:
            return None
        try:
            if _pdh.PdhCollectQueryData(self._q) != 0:
                return None

            by_luid = {}
            for inst, v in self._read_array(self._c_engine):
                if "engtype_3D" not in inst:
                    continue
                key = _luid_of(inst)
                by_luid[key] = by_luid.get(key, 0.0) + v

            mem_by_luid = {}
            for inst, v in self._read_array(self._c_mem):
                key = _luid_of(inst)
                mem_by_luid[key] = mem_by_luid.get(key, 0.0) + v

            out = []
            for a in self.adapters:
                pct = mem = 0.0
                hit_p = hit_m = False
                for (hi, lo) in (a.get("luids") or []):
                    if hi is None:
                        continue
                    # 实例名里 high/low 的顺序各驱动不一定一样，两种都试
                    for key in ((hi, lo), (lo, hi)):
                        if key in by_luid:
                            pct += by_luid[key]
                            hit_p = True
                            break
                    for key in ((hi, lo), (lo, hi)):
                        if key in mem_by_luid:
                            mem += mem_by_luid[key]
                            hit_m = True
                            break
                out.append({
                    "name": a.get("name") or "GPU",
                    "percent": round(min(100.0, pct), 1) if hit_p else None,
                    "memMB": round(mem / 2 ** 20) if hit_m else None,
                    "vramMB": a.get("vramMB") or None,
                })

            # 一个都没对上（老驱动 / LUID 格式不同）：
            # 退回「全部 3D 实例求和」，至少还有一个总利用率可看
            if by_luid and all(x["percent"] is None for x in out):
                total = round(min(100.0, sum(by_luid.values())), 1)
                if out:
                    out[0]["percent"] = total
                else:
                    out.append({"name": "GPU", "percent": total,
                                "memMB": None, "vramMB": None})
            return out or None
        except Exception:
            return None


# ---------------------------------------------------------------- 采样器

class Sampler:
    """后台定期采样，避免每个请求都去算 CPU（要等几百毫秒才有意义）。"""

    def __init__(self, interval=3.0):
        self.interval = interval
        self._lock = threading.Lock()
        self._last = None          # 上一次的 CPU 累计值
        self._cpu = None
        self._samples = 0
        self._peak_cpu = 0.0
        self._peak_mem = 0
        self._peak_gpu = 0.0
        self._gpu_val = None
        self._stop = False
        self._gpu = _GpuCounters()

    def _sample_once(self):
        cur = _cpu_times()
        if cur and self._last:
            di = cur[0] - self._last[0]
            dk = cur[1] - self._last[1]
            du = cur[2] - self._last[2]
            total = dk + du
            if total > 0:
                pct = (1.0 - di / total) * 100.0
                pct = max(0.0, min(100.0, pct))
                with self._lock:
                    # 做一点平滑，否则数字跳得很厉害不好看
                    self._cpu = pct if self._cpu is None else self._cpu * 0.55 + pct * 0.45
                    self._peak_cpu = max(self._peak_cpu, self._cpu)
                    self._samples += 1
        self._last = cur

        m = _memory()
        if m:
            with self._lock:
                self._peak_mem = max(self._peak_mem, m["percent"])

        g = self._gpu.read() if self._gpu else None
        if g:
            with self._lock:
                self._gpu_val = g
                for a in g:
                    if a.get("percent") is not None:
                        self._peak_gpu = max(self._peak_gpu, a["percent"])

    def _loop(self):
        while not self._stop:
            try:
                self._sample_once()
            except Exception:
                pass
            time.sleep(self.interval)

    def start(self):
        self._sample_once()          # 先采一次，建立基准
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._stop = True

    def snapshot(self):
        with self._lock:
            cpu = round(self._cpu, 1) if self._cpu is not None else None
            peak_cpu = round(self._peak_cpu, 1)
            peak_mem = self._peak_mem
            peak_gpu = round(self._peak_gpu, 1)
            samples = self._samples
            gpus = [dict(a) for a in self._gpu_val] if self._gpu_val else []
        for a in gpus:
            a["peak"] = peak_gpu
        return {
            "cpu": {"percent": cpu, "peak": peak_cpu,
                    "cores": os.cpu_count()},
            "gpus": gpus,                 # 每块显卡一项（核显 + 独显）
            "gpu": gpus[0] if gpus else None,   # 兼容旧字段
            "gpuPeak": peak_gpu,
            "mem": _memory(),
            "memPeak": peak_mem,
            "disk": _disks(),
            "processes": _process_count(),
            "bootSeconds": _boot_seconds(),
            "self": _self_stats(),
            "samples": samples,
            "sampledAt": time.time(),
        }
