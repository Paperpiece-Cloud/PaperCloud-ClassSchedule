"""访问流量记录：客户端 IP、设备/浏览器/系统识别、访问统计。

纯标准库实现，不依赖任何第三方 UA 库。
"""

import json
import os
import re
import threading
import time
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
TRAFFIC_FILE = os.path.join(DATA_DIR, "traffic.jsonl")
MAX_BYTES = 4 * 1024 * 1024      # 单个日志文件上限
KEEP_FILES = 4                   # 保留 archive 份数


# ---------------------------------------------------------------- UA 识别

_BOTS = re.compile(
    r"(bot|crawler|spider|slurp|bingpreview|facebookexternalhit|curl/|wget/|"
    r"python-requests|go-http-client|okhttp|java/|postman)", re.I)

_OS_RULES = [
    (r"iphone os ([\d_]+)", "iOS"),
    (r"cpu os ([\d_]+)", "iOS"),
    (r"ipad; cpu os ([\d_]+)", "iOS"),
    (r"android[\s/]([\d.]+)", "Android"),
    (r"harmonyos[\s/]?([\d.]*)", "HarmonyOS"),
    (r"windows nt 10\.0", "Windows 10/11"),
    (r"windows nt 6\.3", "Windows 8.1"),
    (r"windows nt 6\.1", "Windows 7"),
    (r"windows", "Windows"),
    (r"mac os x ([\d_]+)", "macOS"),
    (r"cros", "ChromeOS"),
    (r"ubuntu|debian|fedora|linux", "Linux"),
]

_BROWSER_RULES = [
    (r"micromessenger", "微信"),
    (r"wxwork", "企业微信"),
    (r"qqbrowser", "QQ浏览器"),
    (r"\bqq/", "QQ"),
    (r"quark", "夸克"),
    (r"ucbrowser|ucweb", "UC浏览器"),
    (r"edg/", "Edge"),
    (r"edga/", "Edge"),
    (r"opr/|opera", "Opera"),
    (r"firefox/", "Firefox"),
    (r"samsungbrowser", "三星浏览器"),
    (r"miuibrowser", "小米浏览器"),
    (r"huaweibrowser", "华为浏览器"),
    (r"crios", "Chrome"),
    (r"chrome/", "Chrome"),
    (r"safari/", "Safari"),
    (r"msie|trident", "IE"),
]


def parse_ua(ua):
    """把 User-Agent 解析成人类可读的设备信息。"""
    ua = ua or ""
    out = {
        "raw": ua[:400],
        "os": "未知",
        "osVer": "",
        "browser": "未知",
        "browserVer": "",
        "device": "未知",
        "isMobile": False,
        "isBot": False,
    }

    if not ua:
        out["device"] = "无 UA"
        return out
    if _BOTS.search(ua):
        out["isBot"] = True
        out["device"] = "爬虫/脚本"
        return out

    low = ua.lower()

    # 系统
    for pattern, name in _OS_RULES:
        m = re.search(pattern, low)
        if m:
            out["os"] = name
            if m.groups() and m.group(1):
                out["osVer"] = m.group(1).replace("_", ".")
            break

    # 浏览器
    for pattern, name in _BROWSER_RULES:
        if not re.search(pattern, low):
            continue
        out["browser"] = name
        if name == "Safari":
            # Safari 的真实版本号在 Version/x.y 里；Safari/604.1 是 WebKit 版本，不是浏览器版本
            mv = re.search(r"version\s*/\s*([\d.]+)", low)
            if mv:
                out["browserVer"] = mv.group(1).split(".")[0]
        else:
            # 注意：必须把原 pattern 包成非捕获组，
            # 否则 "a|b" + "([\d.]+)" 会被解析成 "a" 或 "b([\d.]+)"，group(1) 就是 None
            m = re.search(r"(?:" + pattern + r")\s*/?\s*([\d.]+)", low)
            if m and m.group(1):
                out["browserVer"] = m.group(1).split(".")[0]
        break

    # 设备形态
    if "ipad" in low or ("macintosh" in low and "mobile" in low):
        out["device"] = "iPad"
    elif "iphone" in low:
        out["device"] = "iPhone"
    elif "ipod" in low:
        out["device"] = "iPod"
    elif "android" in low:
        if "mobile" in low:
            m = re.search(r";\s*([^;()]{2,40}?)\s+build", ua, re.I)
            out["device"] = (m.group(1).strip() if m else "安卓手机")
        else:
            out["device"] = "安卓平板"
    elif "windows" in low:
        out["device"] = "Windows 电脑"
    elif "macintosh" in low or "mac os x" in low:
        out["device"] = "Mac"
    elif "linux" in low or "x11" in low:
        out["device"] = "Linux 设备"
    else:
        out["device"] = "其它"

    out["isMobile"] = ("mobile" in low or "iphone" in low or "android" in low)

    # 微信内置浏览器单独标出来
    if out["browser"] in ("微信", "企业微信"):
        out["device"] = out["device"] + " · 微信内"

    return out


def short_device(info):
    """一行式设备描述，用于列表展示。"""
    if not info:
        return "—"
    if info.get("isBot"):
        return "爬虫"
    parts = [info.get("device") or "", ]
    b = info.get("browser") or ""
    if info.get("browserVer"):
        b += " " + info["browserVer"]
    if b and b != "未知":
        parts.append(b)
    o = info.get("os") or ""
    if info.get("osVer"):
        o += " " + info["osVer"]
    if o and o != "未知":
        parts.append(o)
    return " · ".join(p for p in parts if p and p != "未知") or "未知设备"


# ---------------------------------------------------------------- 日志

class TrafficLog:
    def __init__(self, path=TRAFFIC_FILE, max_bytes=MAX_BYTES, keep=KEEP_FILES):
        self.path = path
        self.max_bytes = max_bytes
        self.keep = keep
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(path), exist_ok=True)

    # ------------------------------------------------ 写入

    def record(self, ip, method, path, status, ua, referer="", ms=0, size=0,
               country="", extra=None, fp=""):
        ua_info = parse_ua(ua)
        rec = {
            "t": time.time(),
            "ip": ip or "?",
            "m": method,
            "p": (path or "")[:300],
            "s": status,
            "ms": int(ms),
            "sz": int(size),
            "ua": ua_info["raw"][:200],
            "dev": short_device(ua_info),
            "os": ua_info["os"],
            "br": ua_info["browser"],
            "mob": 1 if ua_info["isMobile"] else 0,
            "bot": 1 if ua_info["isBot"] else 0,
            "ref": (referer or "")[:200],
        }
        if country:
            rec["cc"] = country
        if fp:
            rec["fp"] = str(fp)[:32]
        if extra:
            rec.update(extra)

        line = json.dumps(rec, ensure_ascii=False)
        with self._lock:
            try:
                self._rotate_if_needed()
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except Exception:
                pass
        return rec

    def _rotate_if_needed(self):
        try:
            if os.path.getsize(self.path) < self.max_bytes:
                return
        except OSError:
            return
        # traffic.jsonl -> traffic.1.jsonl -> traffic.2.jsonl ...
        for i in range(self.keep - 1, 0, -1):
            src = self.path if i == 1 else self.path.replace(".jsonl", f".{i-1}.jsonl")
            dst = self.path.replace(".jsonl", f".{i}.jsonl")
            if os.path.exists(src):
                try:
                    os.replace(src, dst)
                except OSError:
                    pass

    # ------------------------------------------------ 读取

    def _files(self):
        out = [self.path]
        for i in range(1, self.keep):
            p = self.path.replace(".jsonl", f".{i}.jsonl")
            if os.path.exists(p):
                out.append(p)
        return out

    def recent(self, limit=200):
        """最近 N 条（新的在前）。"""
        out = []
        for p in self._files():
            if not os.path.exists(p):
                continue
            try:
                with open(p, encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            out.append(json.loads(line))
                        except Exception:
                            continue
            except OSError:
                continue
        out.sort(key=lambda r: r.get("t", 0), reverse=True)
        return out[:limit]

    def stats(self, hours=24):
        """统计概览。"""
        now = time.time()
        since = now - hours * 3600
        recs = [r for r in self.recent(limit=200000) if r.get("t", 0) >= since]

        today0 = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
        today = [r for r in recs if r.get("t", 0) >= today0]

        ips = Counter(r.get("ip", "?") for r in recs)
        devs = Counter(r.get("dev", "?") for r in recs)
        pages = Counter(r.get("p", "?").split("?")[0] for r in recs)
        status = Counter(str(r.get("s", "?")) for r in recs)
        bots = sum(1 for r in recs if r.get("bot"))

        # 按小时分布
        hourly = [0] * 24
        for r in recs:
            try:
                hourly[time.localtime(r["t"]).tm_hour] += 1
            except Exception:
                pass

        # 每人访问次数（只看真实访客）
        per_ip_today = Counter(r.get("ip", "?") for r in today if not r.get("bot"))

        return {
            "totalRecords": len(recs),
            "windowHours": hours,
            "todayRequests": len(today),
            "todayVisitors": len(per_ip_today),
            "uniqueIPs": len(ips),
            "uniqueDevices": len(devs),
            "botRequests": bots,
            "topIPs": ips.most_common(10),
            "topDevices": devs.most_common(10),
            "topPages": pages.most_common(12),
            "statusCodes": status.most_common(),
            "hourly": hourly,
            "visitorsToday": per_ip_today.most_common(20),
        }

    def top_visitors(self, hours=24, limit=30):
        """按 IP 聚合的访客画像。"""
        now = time.time()
        since = now - hours * 3600
        recs = [r for r in self.recent(limit=200000) if r.get("t", 0) >= since]

        agg = defaultdict(lambda: {
            "ip": "", "count": 0, "first": None, "last": None,
            "dev": Counter(), "os": Counter(), "br": Counter(),
            "pages": Counter(), "mob": 0, "bot": 0, "status": Counter(),
        })
        for r in recs:
            ip = r.get("ip", "?")
            a = agg[ip]
            a["ip"] = ip
            a["count"] += 1
            t = r.get("t", 0)
            if a["first"] is None or t < a["first"]:
                a["first"] = t
            if a["last"] is None or t > a["last"]:
                a["last"] = t
            a["dev"][r.get("dev", "?")] += 1
            a["os"][r.get("os", "?")] += 1
            a["br"][r.get("br", "?")] += 1
            a["pages"][r.get("p", "?").split("?")[0]] += 1
            a["mob"] += r.get("mob", 0)
            a["bot"] += r.get("bot", 0)
            a["status"][str(r.get("s", "?"))] += 1

        out = []
        for key, a in agg.items():
            out.append({
                "ip": a.get("ip") or "?",
                "fp": a.get("fp") or "",
                "count": a["count"],
                "first": a["first"],
                "last": a["last"],
                "device": a["dev"].most_common(1)[0][0] if a["dev"] else "?",
                "os": a["os"].most_common(1)[0][0] if a["os"] else "?",
                "browser": a["br"].most_common(1)[0][0] if a["br"] else "?",
                "mobile": a["mob"] > a["count"] / 2,
                "isBot": a["bot"] > 0,
                "pages": a["pages"].most_common(4),
                "errors": sum(v for k, v in a["status"].items() if k.startswith(("4", "5"))),
            })
        out.sort(key=lambda x: -x["count"])
        return out[:limit]

    def clear(self):
        with self._lock:
            for p in self._files():
                try:
                    os.remove(p)
                except OSError:
                    pass

    # ------------------------------------------------ 在线访客

    def online(self, minutes=5):
        """最近 N 分钟还在活动的访客（按 IP 聚合）。"""
        now = time.time()
        since = now - max(1, int(minutes)) * 60
        allrecs = self.recent(limit=200000)
        recs = [r for r in allrecs if r.get("t", 0) >= since]

        # 今天的零点：用来算「上线时间」
        lt = time.localtime(now)
        day0 = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))

        # 今天每个 IP 最早的一次访问 = 上线时间
        first_today = {}
        for r in allrecs:
            tt = r.get("t", 0)
            if tt < day0:
                continue
            k2 = r.get("fp") or ("ip:" + str(r.get("ip", "?")))
            if k2 not in first_today or tt < first_today[k2]:
                first_today[k2] = tt

        agg = {}
        for r in recs:
            key = r.get("fp") or ("ip:" + str(r.get("ip", "?")))
            a = agg.get(key)
            if a is None:
                a = agg[key] = {
                    "ip": r.get("ip", "?"), "fp": r.get("fp", ""),
                    "count": 0, "first": r.get("t", 0),
                    "last": r.get("t", 0),
                    "dev": Counter(), "os": Counter(), "br": Counter(),
                    "mob": 0, "bot": 0, "page": r.get("p", "").split("?")[0],
                }
            a["count"] += 1
            tt = r.get("t", 0)
            if tt < a["first"]:
                a["first"] = tt
            if tt > a["last"]:
                a["last"] = tt
                a["page"] = r.get("p", "").split("?")[0]
            a["dev"][r.get("dev", "?")] += 1
            a["os"][r.get("os", "?")] += 1
            a["br"][r.get("br", "?")] += 1
            a["mob"] += r.get("mob", 0)
            a["bot"] += r.get("bot", 0)

        out = []
        for key, a in agg.items():
            out.append({
                "ip": a.get("ip") or "?",
                "fp": a.get("fp") or "",
                "device": a["dev"].most_common(1)[0][0] if a["dev"] else "?",
                "os": a["os"].most_common(1)[0][0] if a["os"] else "?",
                "browser": a["br"].most_common(1)[0][0] if a["br"] else "?",
                "first": first_today.get(key, a["first"]),
                "last": a["last"],
                "seconds": int(max(0, a["last"] - first_today.get(key, a["first"]))),
                "count": a["count"],
                "idle": int(max(0, now - a["last"])),
                "page": a["page"],
                "mobile": a["mob"] > a["count"] / 2,
                "isBot": a["bot"] > 0,
            })
        # 先按最近活跃，再按在线时长
        out.sort(key=lambda x: (-x["last"], -x["seconds"]))
        return out

    # ------------------------------------------------ 按范围取访客

    def visitors_in_range(self, rng="today", limit=80):
        """rng: today / week / month / all"""
        now = time.time()
        lt = time.localtime(now)
        if rng == "today":
            since = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday,
                                 0, 0, 0, 0, 0, -1))
        elif rng == "week":
            # 本周从周一算起
            since = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday,
                                 0, 0, 0, 0, 0, -1)) - (lt.tm_wday * 86400)
        elif rng == "month":
            since = time.mktime((lt.tm_year, lt.tm_mon, 1, 0, 0, 0, 0, 0, -1))
        else:
            since = 0
        hours = max(1, int((now - since) / 3600)) if since else 24 * 365
        if since == 0:
            recs = self.recent(limit=200000)
            hours = 24 * 365
        else:
            recs = [r for r in self.recent(limit=200000) if r.get("t", 0) >= since]
            hours = max(1, int((now - since) / 3600))

        # 复用聚合逻辑：按 IP
        agg = {}
        for r in recs:
            key = r.get("fp") or ("ip:" + str(r.get("ip", "?")))
            a = agg.get(key)
            if a is None:
                a = agg[key] = {
                    "ip": r.get("ip", "?"), "fp": r.get("fp", ""),
                    "count": 0, "first": r.get("t", 0),
                    "last": r.get("t", 0), "dev": Counter(), "os": Counter(),
                    "br": Counter(), "mob": 0, "bot": 0, "status": Counter(),
                    "pages": Counter(),
                }
            a["count"] += 1
            tt = r.get("t", 0)
            a["first"] = min(a["first"], tt)
            a["last"] = max(a["last"], tt)
            a["dev"][r.get("dev", "?")] += 1
            a["os"][r.get("os", "?")] += 1
            a["br"][r.get("br", "?")] += 1
            a["pages"][r.get("p", "?").split("?")[0]] += 1
            a["mob"] += r.get("mob", 0)
            a["bot"] += r.get("bot", 0)
            a["status"][str(r.get("s", "?"))] += 1

        out = []
        for key, a in agg.items():
            out.append({
                "ip": a.get("ip") or "?",
                "fp": a.get("fp") or "",
                "count": a["count"],
                "first": a["first"],
                "last": a["last"],
                "device": a["dev"].most_common(1)[0][0] if a["dev"] else "?",
                "os": a["os"].most_common(1)[0][0] if a["os"] else "?",
                "browser": a["br"].most_common(1)[0][0] if a["br"] else "?",
                "mobile": a["mob"] > a["count"] / 2,
                "isBot": a["bot"] > 0,
                "pages": a["pages"].most_common(4),
                "errors": sum(v for k, v in a["status"].items()
                              if k.startswith(("4", "5"))),
            })
        out.sort(key=lambda x: (-x["count"], -(x["last"] or 0)))
        return out[:limit]

    # ------------------------------------------------ 在线 / 已离线

    def online_and_offline(self, minutes=5):
        """今天的访客拆成「在线」和「已离线」，都按最近活跃从新到旧。"""
        online = self.online(minutes=minutes)

        def kof(v):
            """统一的聚合键：有指纹用指纹，否则 ip:地址"""
            fp = v.get("fp") or ""
            if fp:
                return fp
            return "ip:" + str(v.get("ip") or "?")

        ekeys = set(kof(v) for v in online)

        # 今天所有有记录的人（不设上限，避免漏人）
        today = self.visitors_in_range("today", limit=5000)
        offline = []
        for v in today:
            if kof(v) in ekeys:
                continue
            last = v.get("last") or 0
            first = v.get("first") or 0
            offline.append({
                "ip": v.get("ip"),
                "fp": v.get("fp") or "",
                "device": v.get("device"),
                "os": v.get("os"),
                "browser": v.get("browser"),
                "first": first,
                "last": last,
                "seconds": int(max(0, last - first)),
                "count": v.get("count") or 0,
                "idle": int(max(0, time.time() - last)),
                "page": (v.get("pages") or [["", 0]])[0][0],
                "mobile": v.get("mobile"),
                "isBot": v.get("isBot"),
            })

        # 最近活跃的排前面（新 → 旧）
        offline.sort(key=lambda x: (x.get("last") or 0), reverse=True)

        # 在线也统一按最近活跃排
        online.sort(key=lambda x: (x.get("last") or 0), reverse=True)
        return online, offline

    # ------------------------------------------------ 清空

    def clear_all(self):
        """删掉所有流量日志文件（每天 0 点调用）。"""
        n = 0
        try:
            for p in self._files():
                if os.path.exists(p):
                    try:
                        os.remove(p)
                        n += 1
                    except OSError:
                        pass
        except Exception:
            pass
        return n

