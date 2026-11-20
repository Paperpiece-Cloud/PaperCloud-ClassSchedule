"""抓取调度器：维持会话、定时拉课表、检测变更并推送。"""

import threading
import time
import traceback

from . import client as client_mod
from . import normalize
from .store import Store


class Fetcher:
    def __init__(self, cfg, store: Store, hub=None):
        self.cfg = cfg
        self.store = store
        self.hub = hub
        self.client = None
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._thread = None
        self.running = False
        self._last_login_attempt = 0.0
        self._login_attempts = 0
        self.stats = {"attempts": 0, "ok": 0, "fail": 0, "lastAttempt": None,
                      "lastOk": None, "lastError": None, "consecutiveFail": 0,
                      "lastChanged": False, "lastRevision": None, "lastCount": None,
                      "loginAttempts": 0, "lastLoginError": None, "noSession": False}

    # ---------------------------------------------------------------- 会话

    def has_session(self):
        return self.client is not None

    def ensure_session(self, force=False):
        """优先复用磁盘会话；没有就（按节流）尝试一次 CAS 登录。

        节流很重要：学校 grd 单点登录有故障时，如果每一轮都去试，
        会反复骚扰学校服务器。这里限制两次登录尝试之间至少隔 retry_minutes。
        """
        if self.client is not None and not force:
            return True

        state = None if force else client_mod.SessionState.load()
        if state and state.cookies:
            cli = client_mod.JwClient(state)
            ok, _ = cli.check()
            if ok:
                self.client = cli
                return True
            self.stats["lastError"] = "磁盘会话已失效"

        user = (self.cfg.get("username") or "").strip()
        pwd = self.cfg.get("password") or ""
        if not (user and pwd) or not self.cfg.get("auto_login", True):
            return False

        # ---- 登录节流 ----
        gap = max(60, int(self.cfg.get("retry_minutes", 15)) * 60)
        since = time.time() - self._last_login_attempt
        if not force and self._last_login_attempt and since < gap:
            wait = int((gap - since) / 60) + 1
            self.stats["lastLoginError"] = f"上次登录尝试未成功，{wait} 分钟后再试"
            return False

        self._last_login_attempt = time.time()
        self._login_attempts += 1
        self.stats["loginAttempts"] = self._login_attempts
        try:
            self.client = client_mod.JwClient.from_cas(
                user, pwd,
                pattern=self.cfg.get("pattern", "student-login"),
                base=self.cfg.get("base") or None)
            # 登录完立刻验一下是否真的能调 API
            ok, info = self.client.check()
            if not ok:
                self.client = None
                self.stats["lastLoginError"] = f"CAS 登录后仍无法访问 API：{info}"
                return False
            self.stats["lastLoginError"] = None
            return True
        except Exception as e:
            self.stats["lastError"] = f"登录失败: {e}"
            self.stats["lastLoginError"] = f"{type(e).__name__}: {e}"
            self.client = None
            return False

    # ---------------------------------------------------------------- 抓取

    def fetch_once(self):
        """抓一次课表并入库。返回 (ok, message)；是否有变更看 stats['lastChanged']。"""
        with self._lock:
            self.stats["attempts"] += 1
            self.stats["lastAttempt"] = time.time()
            try:
                if not self.ensure_session():
                    # 「没有会话」不是故障，只是还没配置自动抓取。
                    # 这种情况不写进 store.lastError，首页也就不会报红，
                    # 而是显示「手动录入模式」。
                    self.stats["noSession"] = True
                    manual = self.store.get().get("schedule", {}).get("count", 0)
                    msg = self.stats.get("lastLoginError") or "尚未配置抓取会话"
                    self.stats["lastError"] = msg
                    self.store.clear_error()   # 清掉历史报错，首页不显示红色告警
                    return False, f"{msg}（当前显示手动录入的 {manual} 门课）"

                raw = self.client.student_schedule({})
                sched = normalize.normalize_schedule(raw, self.cfg.get("max_week", 30))
                if sched["count"] == 0:
                    raise ValueError("课表为空，字段映射可能需要调整")

                term = self.store.get().get("term")
                changed, rev, changes = self.store.commit(
                    sched, term=term, raw_sample=(raw if isinstance(raw, (dict, list)) else None),
                    source="自动抓取")

                self.stats["ok"] += 1
                self.stats["lastOk"] = time.time()
                self.stats["lastError"] = None
                self.stats["consecutiveFail"] = 0
                self.stats["noSession"] = False
                self.stats["lastChanged"] = bool(changed)
                self.stats["lastRevision"] = rev
                self.stats["lastCount"] = sched["count"]

                if changed and self.hub:
                    self.hub.publish("update", {"revision": rev, "changes": changes})
                # 注意：这里返回的是「抓取是否成功」，不是「是否有变更」
                return True, f"{sched['count']} 门课" + ("，有变更" if changed else "，无变化")
            except client_mod.AuthError as e:
                self.client = None
                self.stats["fail"] += 1
                self.stats["consecutiveFail"] += 1
                self.stats["lastError"] = f"会话失效: {e}"
                self.store.set_error(self.stats["lastError"])
                return False, self.stats["lastError"]
            except Exception as e:
                self.stats["fail"] += 1
                self.stats["consecutiveFail"] += 1
                self.stats["lastError"] = f"{type(e).__name__}: {e}"
                self.store.set_error(self.stats["lastError"])
                return False, self.stats["lastError"]

    def refresh_now(self):
        ok, msg = self.fetch_once()
        return ok, msg

    # ---------------------------------------------------------------- 循环

    def _loop(self):
        self.running = True
        interval = max(60, int(self.cfg.get("poll_seconds", 600)))
        # 启动后先抓一次
        self.fetch_once()
        while self.running:
            # 失败时退避：连续失败越多，间隔越长，但不超过 1 小时
            base = interval
            if self.stats["consecutiveFail"]:
                base = min(3600, interval * (2 ** min(self.stats["consecutiveFail"], 4)))
            self._wake.wait(base)
            self._wake.clear()
            if not self.running:
                break
            self.fetch_once()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="fetcher")
        self._thread.start()

    def stop(self):
        self.running = False
        self._wake.set()

    def kick(self):
        """立即唤醒一次抓取。"""
        self._wake.set()
