# -*- coding: utf-8 -*-
"""QQ 定时推送：每天晚上 9 点推「明天的课 + 值日」。

规则（按用户要求）：
  · 每天 21:00 推送
  · 周五晚上、周六晚上不推

实现：
  一个 daemon 线程，每 30 秒醒一次，到点就调本地
  POST /api/qq/push?key=<webhook_key>&offset=1
  只用标准库。
"""

import datetime as dt
import json
import os
import threading
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG_PATH = os.path.join(ROOT, "config", "secrets.json")

DEFAULT_TIME = "21:00"
SKIP_WEEKDAYS = (4, 5)      # Python: 周一=0 … 周五=4 周六=5


def _cfg():
    try:
        with open(CFG_PATH, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {}


def _enabled(d):
    v = d.get("qq_enabled")
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)


def _hhmm(d):
    t = str(d.get("qq_push_time") or DEFAULT_TIME).strip()
    parts = t.split(":")
    try:
        h, m = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    except Exception:
        h, m = 21, 0
    return max(0, min(23, h)), max(0, min(59, m))


MORNING_TIME = (8, 0)
CHECKIN_TIME = (22, 0)
CHECKIN_SKIP = (4, 5)      # 周五、周六晚上不推
MORNING_WEEKDAYS = (0, 1, 2, 3, 4)     # 周一~周五


class QQScheduler(threading.Thread):
    def __init__(self, port):
        super().__init__(name="qq-scheduler", daemon=True)
        self.port = int(port or 8787)
        self._stop = threading.Event()
        self._last_day = None       # 晚上推送已完成的日期
        self._last_morning = None   # 早课提醒已完成的日期
        self._last_checkin = None   # 签到提醒已完成的日期
        self._last_daily = None     # 每日清零已完成的日期

    def stop(self):
        self._stop.set()

    def _push(self, key):
        url = "http://127.0.0.1:%d/api/qq/push?%s" % (
            self.port, urllib.parse.urlencode({"key": key, "offset": 1}))
        try:
            req = urllib.request.Request(url, data=b"", method="POST",
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read().decode("utf-8", "replace")
            print("[qq] 定时推送:", body[:200], flush=True)
        except Exception as e:
            print("[qq] 定时推送失败:", e, flush=True)

    def _morning(self, key):
        url = "http://127.0.0.1:%d/api/qq/morning?%s" % (
            self.port, urllib.parse.urlencode({"key": key}))
        try:
            req = urllib.request.Request(url, data=b"", method="POST",
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read().decode("utf-8", "replace")
            print("[qq] 早课提醒:", body[:200], flush=True)
        except Exception as e:
            print("[qq] 早课提醒失败:", e, flush=True)

    def _checkin(self, key):
        url = "http://127.0.0.1:%d/api/qq/checkin?%s" % (
            self.port, urllib.parse.urlencode({"key": key}))
        try:
            req = urllib.request.Request(url, data=b"", method="POST",
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read().decode("utf-8", "replace")
            print("[qq] 签到提醒:", body[:200], flush=True)
        except Exception as e:
            print("[qq] 签到提醒失败:", e, flush=True)

    def _daily(self, key):
        url = "http://127.0.0.1:%d/api/cron/daily?%s" % (
            self.port, urllib.parse.urlencode({"key": key}))
        try:
            req = urllib.request.Request(url, data=b"", method="POST",
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as r:
                print("[qq] 每日清零:", r.read().decode("utf-8", "replace")[:120], flush=True)
        except Exception as e:
            print("[qq] 每日清零失败:", e, flush=True)

    def run(self):
        print("[qq] 定时线程已启动（早 8:00 早课 / 晚 21:00 日报 / 晚 22:00 签到；周五周六晚跳过）", flush=True)
        while not self._stop.is_set():
            try:
                d = _cfg()
                if not _enabled(d):
                    self._stop.wait(60)
                    continue

                now = dt.datetime.now()
                hh, mm = _hhmm(d)
                today = now.date()

                # 每天只在目标分钟附近触发一次，且当天没推过
                same_minute = (now.hour == hh and now.minute == mm)
                skip = today.weekday() in SKIP_WEEKDAYS

                # ---- 早上 8:00 早课提醒（周一~周五）----
                mhh, mmm = MORNING_TIME
                if (now.hour == mhh and now.minute == mmm
                        and today.weekday() in MORNING_WEEKDAYS
                        and self._last_morning != today):
                    _k = str(d.get("qq_webhook_key") or "")
                    if _k:
                        self._last_morning = today
                        self._morning(_k)

                # ---- 晚上 22:00 签到提醒（周五、周六不推）----
                chh, cmm = CHECKIN_TIME
                if (now.hour == chh and now.minute == cmm
                        and today.weekday() not in CHECKIN_SKIP
                        and self._last_checkin != today):
                    _k2 = str(d.get("qq_webhook_key") or "")
                    if _k2:
                        self._last_checkin = today
                        self._checkin(_k2)

                # ---- 每天 0 点：清掉访问记录 ----
                if (now.hour == 0 and now.minute == 0
                        and self._last_daily != today):
                    _k3 = str(d.get("qq_webhook_key") or "")
                    if _k3:
                        self._last_daily = today
                        self._daily(_k3)

                if same_minute and not skip and self._last_day != today:
                    key = str(d.get("qq_webhook_key") or "")
                    if key:
                        self._last_day = today
                        self._push(key)
                    else:
                        print("[qq] 没配置 qq_webhook_key，跳过定时推送", flush=True)
            except Exception as e:
                print("[qq] 调度异常:", e, flush=True)

            # 30 秒醒一次，保证在同一分钟内能命中
            self._stop.wait(20)


def start(port):
    """启动调度线程。重复调用不会起第二个。"""
    global _INSTANCE
    try:
        if _INSTANCE and _INSTANCE.is_alive():
            return _INSTANCE
    except NameError:
        pass
    th = QQScheduler(port)
    th.start()
    _INSTANCE = th
    return th
