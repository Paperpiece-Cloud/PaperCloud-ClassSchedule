"""课表状态存储：当前快照 + 历史版本 + 变更对比。"""

import json
import os
import threading
import time

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
HISTORY_DIR = os.path.join(DATA_DIR, "history")
STATE_FILE = os.path.join(DATA_DIR, "state.json")
MAX_HISTORY = 60


def _sig(course):
    return (course.get("name", ""), course.get("weekday", 0),
            course.get("startSection", 0), course.get("endSection", 0),
            tuple(course.get("weeks", [])), course.get("room", ""),
            course.get("teacher", ""))


def _key(course):
    """跨版本追踪同一门课的稳定键。

    只用 (课程名, 教师) —— 不含时间和地点，
    这样「换教室」或「调课」会被识别成 changed 而不是 added+removed。
    """
    return (course.get("name", ""), course.get("teacher", ""))


def diff_schedules(old_courses, new_courses):
    """对比两次课表，返回人类可读的变更列表。"""
    old_map = {}
    for c in old_courses or []:
        old_map.setdefault(_key(c), []).append(c)
    new_map = {}
    for c in new_courses or []:
        new_map.setdefault(_key(c), []).append(c)

    changes = []

    # 新出现的
    for k, items in new_map.items():
        if k not in old_map:
            for c in items:
                changes.append({"kind": "added", "course": c,
                                "text": f"新增 {c['name']}（{_when(c)}）"})

    # 消失的
    for k, items in old_map.items():
        if k not in new_map:
            for c in items:
                changes.append({"kind": "removed", "course": c,
                                "text": f"取消 {c['name']}（原 {_when(c)}）"})

    # 同名课的时间/地点变化
    for k, new_items in new_map.items():
        old_items = old_map.get(k)
        if not old_items:
            continue
        old_sigs = {_sig(c) for c in old_items}
        new_sigs = {_sig(c) for c in new_items}
        if old_sigs == new_sigs:
            continue
        for c in [x for x in new_items if _sig(x) not in old_sigs]:
            same_room = [o for o in old_items if o.get("room") == c.get("room")]
            base = same_room[0] if same_room else (old_items[0] if old_items else None)
            changes.append({
                "kind": "changed", "course": c, "from": base,
                "text": (f"{c['name']} 调整：{_when(base)} → {_when(c)}"
                         if base else f"{c['name']} 时间调整"),
            })
    return changes


def _when(c):
    if not c:
        return "?"
    from .normalize import WEEKDAY_NAMES
    wd = c.get("weekday") or 0
    name = WEEKDAY_NAMES[wd] if 1 <= wd <= 7 else "?"
    sec = f"{c.get('startSection', '?')}-{c.get('endSection', '?')}节"
    weeks = c.get("weeks") or []
    wk = f"第{_ranges(weeks)}周" if weeks else ""
    room = f" @{c['room']}" if c.get("room") else ""
    return " ".join(x for x in [name, sec, wk] if x) + room


def _ranges(weeks):
    """[1,2,3,5] -> '1-3,5'"""
    if not weeks:
        return ""
    weeks = sorted(set(weeks))
    out, start, prev = [], weeks[0], weeks[0]
    for w in weeks[1:]:
        if w == prev + 1:
            prev = w
            continue
        out.append(str(start) if start == prev else f"{start}-{prev}")
        start = prev = w
    out.append(str(start) if start == prev else f"{start}-{prev}")
    return ",".join(out)


class Store:
    def __init__(self, base_dir=None):
        # base_dir 允许测试用临时目录，避免污染正式数据
        self.base = base_dir or DATA_DIR
        self.history_dir = os.path.join(self.base, "history")
        self.state_file = os.path.join(self.base, "state.json")
        os.makedirs(self.history_dir, exist_ok=True)
        self._lock = threading.RLock()
        self._mtime = self._disk_mtime()
        self.state = self._load()

    # ---------------------------------------------------------------- 读写

    def _disk_mtime(self):
        try:
            return os.path.getmtime(self.state_file)
        except OSError:
            return 0.0

    def _maybe_reload(self):
        """别的进程（如导入工具）改了状态文件时自动重载。"""
        m = self._disk_mtime()
        if m and m != self._mtime:
            self.state = self._load()
            self._mtime = m

    def _load(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "revision": 0,
            "updatedAt": None,
            "lastOkAt": None,
            "lastError": None,
            "term": None,
            "schedule": {"courses": [], "maxWeek": 20, "count": 0},
            "changes": [],
            "history": [],
            "rawSample": None,
            "source": "初始状态",
        }

    def _dump(self):
        """原子写入，并对 OneDrive / 杀毒软件的瞬时文件锁做重试。"""
        os.makedirs(self.base, exist_ok=True)
        data = json.dumps(self.state, ensure_ascii=False, indent=1)
        tmp = f"{self.state_file}.{os.getpid()}.tmp"
        last = None
        for attempt in range(6):
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    f.write(data)
                os.replace(tmp, self.state_file)
                self._mtime = self._disk_mtime()
                return
            except OSError as e:
                last = e
                time.sleep(0.15 * (attempt + 1))
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        # 兜底：直接覆写（非原子，但好过写不进去）
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                f.write(data)
            self._mtime = self._disk_mtime()
        except OSError:
            raise last

    # ---------------------------------------------------------------- 接口

    def get(self):
        with self._lock:
            self._maybe_reload()
            return json.loads(json.dumps(self.state, ensure_ascii=False))

    def set_term(self, term):
        with self._lock:
            self.state["term"] = term
            self._dump()

    def set_error(self, message):
        with self._lock:
            self.state["lastError"] = message
            self.state["updatedAt"] = time.time()
            self._dump()

    def clear_error(self):
        """只清错误，不动 updatedAt（避免让旧数据看起来像刚更新过）。"""
        with self._lock:
            if self.state.get("lastError"):
                self.state["lastError"] = None
                self._dump()

    def commit(self, schedule, term=None, raw_sample=None, source="定时抓取"):
        """提交一份新抓取的课表。返回 (changed, revision, changes)。"""
        with self._lock:
            self._maybe_reload()
            old = self.state.get("schedule", {}).get("courses", [])
            new = schedule.get("courses", [])
            changed = json.dumps([_sig(c) for c in old], ensure_ascii=False) != \
                      json.dumps([_sig(c) for c in new], ensure_ascii=False)

            now = time.time()
            if changed:
                self.state["revision"] = self.state.get("revision", 0) + 1
                changes = diff_schedules(old, new)
            else:
                changes = []

            self.state["schedule"] = schedule
            self.state["updatedAt"] = now
            self.state["lastOkAt"] = now
            self.state["lastError"] = None
            self.state["source"] = source
            if term:
                self.state["term"] = term
            if raw_sample is not None:
                self.state["rawSample"] = raw_sample
            if changed:
                self.state["changes"] = changes
                self._archive(changes)

            self._dump()
            return changed, self.state["revision"], changes

    def _archive(self, changes):
        rev = self.state["revision"]
        snap = {
            "revision": rev,
            "at": self.state["updatedAt"],
            "term": self.state.get("term"),
            "changes": changes,
            "schedule": self.state["schedule"],
        }
        path = os.path.join(self.history_dir, f"rev-{rev:05d}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, indent=1)

        hist = self.state.setdefault("history", [])
        hist.append({"revision": rev, "at": self.state["updatedAt"],
                     "changeCount": len(changes),
                     "summary": [c["text"] for c in changes[:6]]})
        self.state["history"] = hist[-MAX_HISTORY:]

        # 清理过老的文件
        files = sorted(f for f in os.listdir(self.history_dir) if f.startswith("rev-"))
        for old in files[:-MAX_HISTORY]:
            try:
                os.remove(os.path.join(self.history_dir, old))
            except OSError:
                pass

    def history(self):
        with self._lock:
            self._maybe_reload()
            return list(self.state.get("history", []))

    def revision_snapshot(self, rev):
        path = os.path.join(self.history_dir, f"rev-{int(rev):05d}.json")
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def diff_between(self, rev_a, rev_b):
        a = self.revision_snapshot(rev_a)
        b = self.revision_snapshot(rev_b)
        if not a or not b:
            return None
        return diff_schedules(a["schedule"]["courses"], b["schedule"]["courses"])
