"""安全防护：请求限流、口令爆破封禁、IP 黑白名单、客户端 IP 提取。

全部内存实现 + 落盘持久化封禁记录（重启不丢）。
"""

import json
import os
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
BAN_FILE = os.path.join(DATA_DIR, "security.json")


# ---------------------------------------------------------------- 客户端 IP

_TRUSTED_HEADERS = ("cf-connecting-ip", "x-real-ip", "x-forwarded-for", "x-client-ip")


def client_ip(handler):
    """拿到真实客户端 IP。

    走 Cloudflare 隧道时，socket 里看到的是 127.0.0.1，
    真实 IP 在 CF-Connecting-IP / X-Forwarded-For 里。
    这里优先信任这些头（因为服务只在本机/隧道后监听）。
    """
    headers = getattr(handler, "headers", None)
    if headers:
        for name in _TRUSTED_HEADERS:
            v = headers.get(name)
            if v:
                # X-Forwarded-For 可能是 "client, proxy1, proxy2"
                return v.split(",")[0].strip()[:64]
    try:
        return handler.client_address[0]
    except Exception:
        return "?"


# ---------------------------------------------------------------- 限流

class RateLimiter:
    """滑动窗口限流。

    按 IP 记录最近 window 秒内的请求时间戳；
    超过 per_minute 就拒绝，并给出 Retry-After。
    连续超限多次会被临时封禁。
    """

    def __init__(self, per_minute=180, window=60, hard_limit=600,
                 ban_after_violations=6, ban_seconds=600):
        self.per_minute = per_minute
        self.window = window
        self.hard_limit = hard_limit        # 单窗口绝对上限
        self.ban_after_violations = ban_after_violations
        self.ban_seconds = ban_seconds
        self._hits = {}                     # ip -> [timestamps]
        self._violations = {}               # ip -> [violation timestamps]
        self._lock = threading.Lock()

    def check(self, ip):
        """返回 (allowed, retry_after, reason)。"""
        now = time.time()
        with self._lock:
            hits = [t for t in self._hits.get(ip, []) if now - t < self.window]
            self._hits[ip] = hits

            if len(hits) >= self.hard_limit:
                self._note_violation(ip, now)
                return False, max(1, int(self.window - (now - hits[0]))), "请求过于频繁"

            if len(hits) >= self.per_minute:
                self._note_violation(ip, now)
                return False, max(1, int(self.window - (now - hits[0]))), "请求过于频繁"

            hits.append(now)
            # 顺手清理过期 IP，防止内存无限增长
            if len(self._hits) > 5000:
                self._gc(now)
            return True, 0, ""

    def _note_violation(self, ip, now):
        """记一次超限。返回是否已达到「该封禁」的程度。"""
        v = [t for t in self._violations.get(ip, []) if now - t < self.ban_seconds]
        v.append(now)
        self._violations[ip] = v
        return len(v) >= self.ban_after_violations

    def violations(self, ip):
        now = time.time()
        with self._lock:
            return len([t for t in self._violations.get(ip, []) if now - t < self.ban_seconds])

    def _gc(self, now):
        for k in list(self._hits.keys()):
            if not self._hits[k] or now - self._hits[k][-1] > self.window * 5:
                self._hits.pop(k, None)
        for k in list(self._violations.keys()):
            if not self._violations[k] or now - self._violations[k][-1] > self.ban_seconds * 2:
                self._violations.pop(k, None)


# ---------------------------------------------------------------- 口令防爆破

class AuthGuard:
    """访问口令错误次数统计 + 临时封禁。"""

    def __init__(self, max_fails=8, fail_window=600, ban_seconds=900):
        self.max_fails = max_fails
        self.fail_window = fail_window
        self.ban_seconds = ban_seconds
        self._fails = {}        # ip -> [timestamps]
        self._bans = {}         # ip -> until_ts
        self._lock = threading.Lock()
        self.load()

    # ---- 持久化 ----
    def load(self):
        try:
            with open(BAN_FILE, encoding="utf-8") as f:
                d = json.load(f)
            now = time.time()
            self._bans = {k: v for k, v in (d.get("bans") or {}).items() if v > now}
            self._fails = {k: [t for t in v if now - t < self.fail_window]
                           for k, v in (d.get("fails") or {}).items()}
        except Exception:
            pass

    def save(self):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            tmp = BAN_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"bans": self._bans, "fails": self._fails}, f,
                          ensure_ascii=False, indent=1)
            os.replace(tmp, BAN_FILE)
        except Exception:
            pass

    # ---- 接口 ----
    def is_banned(self, ip):
        with self._lock:
            until = self._bans.get(ip)
            if until and until > time.time():
                return True, int(until - time.time())
            if until:
                self._bans.pop(ip, None)
            return False, 0

    def note_fail(self, ip):
        """记一次口令错误。返回 (是否已封禁, 剩余秒数, 本窗口错误次数)。"""
        now = time.time()
        with self._lock:
            fs = [t for t in self._fails.get(ip, []) if now - t < self.fail_window]
            fs.append(now)
            self._fails[ip] = fs
            n = len(fs)
            banned = False
            if n >= self.max_fails:
                self._bans[ip] = now + self.ban_seconds
                self._fails[ip] = []
                banned = True
            self.save()
            return banned, self.ban_seconds if banned else 0, n

    def note_success(self, ip):
        with self._lock:
            if ip in self._fails:
                self._fails.pop(ip, None)

    def unban(self, ip):
        with self._lock:
            self._bans.pop(ip, None)
            self._fails.pop(ip, None)
            self.save()

    def ban(self, ip, seconds=3600):
        with self._lock:
            self._bans[ip] = time.time() + seconds
            self.save()

    def clear_all(self):
        """把所有封禁和失败计数清掉。后台「解除所有 IP 封禁」用。"""
        n = 0
        try:
            n = len(self.bans)
            self.bans = {}
            self.fails = {}
            self.save()
        except Exception:
            pass
        return n

    def list_bans(self):
        now = time.time()
        with self._lock:
            return [{"ip": k, "until": v, "remain": int(v - now)}
                    for k, v in sorted(self._bans.items(), key=lambda x: -x[1]) if v > now]

    def list_fails(self):
        now = time.time()
        with self._lock:
            out = []
            for ip, fs in self._fails.items():
                live = [t for t in fs if now - t < self.fail_window]
                if live:
                    out.append({"ip": ip, "count": len(live), "last": max(live)})
            out.sort(key=lambda x: -x["count"])
            return out


# ---------------------------------------------------------------- 黑白名单

class IPLists:
    def __init__(self, path=None):
        self.path = path or os.path.join(DATA_DIR, "iplists.json")
        self.allow = set()
        self.deny = set()
        self.load()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            self.allow = set(d.get("allow") or [])
            self.deny = set(d.get("deny") or [])
        except Exception:
            pass

    def save(self):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"allow": sorted(self.allow), "deny": sorted(self.deny)},
                          f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except Exception:
            pass

    def check(self, ip):
        """返回 (allowed, reason)。白名单优先级最高。"""
        if ip in self.allow:
            return True, "allowlisted"
        if ip in self.deny:
            return False, "denylisted"
        return True, ""

    def add_deny(self, ip):
        self.deny.add(ip); self.allow.discard(ip); self.save()

    def add_allow(self, ip):
        self.allow.add(ip); self.deny.discard(ip); self.save()

    def remove(self, ip):
        self.deny.discard(ip); self.allow.discard(ip); self.save()


# ---------------------------------------------------------------- 安全响应头

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "no-referrer",
    "X-XSS-Protection": "1; mode=block",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}
