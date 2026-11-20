"""班务系统 · 数据层。

三块内容都存在一个 JSON 文件里（data/class.json），读写都走原子替换 + 文件锁重试，
和课表数据一样的套路，避免云电脑上偶发的写入失败。

    students    学生名单
    attendance  考勤记录（按日期 -> 学生 -> 状态）
    duty        值日分组 + 每日排班

学生用 id 做主键。如果导入时没给学号，就用 name+序号 生成一个稳定 id，
这样以后改名字也不会把考勤记录对错人。
"""

import json
import os
import threading
import time

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
STORE = os.path.join(DATA_DIR, "class.json")

# 考勤状态。顺序就是界面上按钮的顺序。
STATUSES = [
    ("present", "出勤"),
    ("late", "迟到"),
    ("leave", "请假"),
    ("absent", "缺勤"),
]
STATUS_KEYS = [s[0] for s in STATUSES]
STATUS_NAMES = dict(STATUSES)


def _blank():
    return {"students": [], "attendance": {}, "duty": {"groups": [], "schedule": {}},
            "updatedAt": None}


class ClassStore:
    def __init__(self, path=STORE):
        self.path = path
        self._lock = threading.RLock()
        self._cache = None
        self._mtime = 0

    # ---------------------------------------------------------------- 读写

    def _load(self):
        """带 mtime 缓存：文件没变就不重复解析。"""
        try:
            mt = os.path.getmtime(self.path)
        except OSError:
            self._cache, self._mtime = _blank(), 0
            return self._cache
        with self._lock:
            if self._cache is not None and mt == self._mtime:
                return self._cache
            try:
                with open(self.path, encoding="utf-8") as f:
                    d = json.load(f)
                if not isinstance(d, dict):
                    d = _blank()
            except Exception:
                d = _blank()
            base = _blank()
            base.update({k: d.get(k) for k in base if d.get(k) is not None})
            self._cache, self._mtime = base, mt
            return base

    def _save(self, d):
        with self._lock:
            os.makedirs(DATA_DIR, exist_ok=True)
            d["updatedAt"] = time.time()
            tmp = self.path + ".tmp"
            last = None
            # 云电脑上杀毒/同步软件偶尔会锁住文件，重试几次
            for i in range(6):
                try:
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(d, f, ensure_ascii=False, indent=1)
                    os.replace(tmp, self.path)
                    self._cache, self._mtime = d, os.path.getmtime(self.path)
                    return True
                except Exception as e:
                    last = e
                    time.sleep(0.12 * (i + 1))
            raise last

    # ---------------------------------------------------------------- 学生

    def students(self):
        return self._load().get("students", [])

    def save_students(self, rows):
        """整表覆盖（导入用）。会自动补 id 和排序号。"""
        d = self._load()
        clean = []
        seen = set()
        for i, r in enumerate(rows or []):
            if not isinstance(r, dict):
                continue
            name = str(r.get("name") or "").strip()
            if not name:
                continue
            sid = str(r.get("id") or "").strip()
            if not sid or sid in seen:
                sid = "s%03d-%s" % (i + 1, name)
                while sid in seen:
                    sid += "_"
            seen.add(sid)
            clean.append({
                "id": sid,
                "no": str(r.get("no") or "").strip(),
                "name": name,
                "gender": str(r.get("gender") or "").strip(),
                "phone": str(r.get("phone") or "").strip(),
                "dorm": str(r.get("dorm") or "").strip(),
                "note": str(r.get("note") or "").strip(),
                "active": bool(r.get("active", True)),
                # 下面几个是班务页面要用的，别在保存时丢掉
                "title": str(r.get("title") or "").strip(),      # 班委头衔
                "political": str(r.get("political") or "").strip(),
                "group": str(r.get("group") or "").strip(),
                "leader": bool(r.get("leader", False)),
            })
        d["students"] = clean
        self._save(d)
        return clean

    def upsert_student(self, row):
        d = self._load()
        if not isinstance(row, dict):
            return None
        name = str(row.get("name") or "").strip()
        if not name:
            return None
        sid = str(row.get("id") or "").strip()
        cur = d.get("students", [])
        if not sid:
            sid = "s%d" % int(time.time() * 1000)
            cur.append({"id": sid})
        for s in cur:
            if s.get("id") == sid:
                s.update({
                    "no": str(row.get("no") or s.get("no") or "").strip(),
                    "name": name,
                    "gender": str(row.get("gender") or s.get("gender") or "").strip(),
                    "phone": str(row.get("phone") or s.get("phone") or "").strip(),
                    "dorm": str(row.get("dorm") or s.get("dorm") or "").strip(),
                    "note": str(row.get("note") or s.get("note") or "").strip(),
                    "active": bool(row.get("active", s.get("active", True))),
                })
                break
        else:
            cur.append({"id": sid, "no": str(row.get("no") or "").strip(), "name": name,
                        "gender": str(row.get("gender") or "").strip(),
                        "phone": str(row.get("phone") or "").strip(),
                        "dorm": str(row.get("dorm") or "").strip(),
                        "note": str(row.get("note") or "").strip(),
                        "active": bool(row.get("active", True))})
        d["students"] = cur
        self._save(d)
        return sid

    def remove_student(self, sid):
        d = self._load()
        before = len(d.get("students", []))
        d["students"] = [s for s in d.get("students", []) if s.get("id") != sid]
        self._save(d)
        return before != len(d["students"])

    # ---------------------------------------------------------------- 考勤

    def attendance(self, date):
        return self._load().get("attendance", {}).get(date, {})

    def attendance_range(self, days=None):
        a = self._load().get("attendance", {})
        keys = sorted(a.keys())
        if days:
            keys = keys[-days:]
        return {k: a[k] for k in keys}

    def set_attendance(self, date, sid, status):
        """把某个学生某天的考勤设成 status；传空则清除该条。"""
        if not date:
            return False
        d = self._load()
        att = d.setdefault("attendance", {})
        day = att.setdefault(date, {})
        if not status or status not in STATUS_KEYS:
            day.pop(sid, None)
            if not day:
                att.pop(date, None)
        else:
            day[sid] = status
        self._save(d)
        return True

    def set_attendance_bulk(self, date, mapping):
        """一次设置一整天的考勤，减少来回请求。"""
        if not date or not isinstance(mapping, dict):
            return False
        d = self._load()
        att = d.setdefault("attendance", {})
        day = {}
        for sid, st in mapping.items():
            if st in STATUS_KEYS:
                day[str(sid)] = st
        if day:
            att[date] = day
        else:
            att.pop(date, None)
        self._save(d)
        return True

    def attendance_stats(self, days=30):
        """最近 N 天的汇总：每个人各状态次数 + 全班每天的缺勤率。"""
        a = self._load().get("attendance", {})
        keys = sorted(a.keys())[-days:]
        per = {}
        daily = []
        for k in keys:
            day = a.get(k, {})
            counts = {s: 0 for s in STATUS_KEYS}
            for st in day.values():
                if st in counts:
                    counts[st] += 1
            daily.append({"date": k, "counts": counts,
                          "total": sum(counts.values())})
            for sid, st in day.items():
                p = per.setdefault(sid, {s: 0 for s in STATUS_KEYS})
                if st in p:
                    p[st] += 1
        return {"perStudent": per, "daily": daily, "days": keys}

    # ---------------------------------------------------------------- 值日

    def duty(self):
        return self._load().get("duty", {"groups": [], "schedule": {}})

    def save_duty(self, duty):
        d = self._load()
        if not isinstance(duty, dict):
            return False
        groups = []
        for i, g in enumerate(duty.get("groups") or []):
            if not isinstance(g, dict):
                continue
            groups.append({
                "id": str(g.get("id") or ("g%d" % (i + 1))),
                "name": str(g.get("name") or ("第%d组" % (i + 1))).strip(),
                "members": [str(m) for m in (g.get("members") or [])],
                "note": str(g.get("note") or "").strip(),
            })
        sched = {}
        for k, v in (duty.get("schedule") or {}).items():
            if isinstance(v, str) and v:
                sched[str(k)] = v
        d["duty"] = {"groups": groups, "schedule": sched}
        self._save(d)
        return True

    def generate_duty(self, start_date, days, group_ids=None, weekdays=None):
        """按顺序把组轮流排到日期上，只在 weekdays 指定的星期排。

        weekdays 是 0~6 的列表（0=周一 … 6=周日）。
        不传就用默认：周一~周五 + 周日，也就是只有周六不打扫。
        """
        import datetime as dt
        if weekdays is None:
            weekdays = [0, 1, 2, 3, 4, 6]
        try:
            weekdays = set(int(x) for x in weekdays if 0 <= int(x) <= 6)
        except Exception:
            weekdays = {0, 1, 2, 3, 4, 6}
        if not weekdays:
            return {}
        d = self._load()
        groups = d.get("duty", {}).get("groups", [])
        if group_ids:
            groups = [g for g in groups if g.get("id") in group_ids]
        if not groups:
            return {}
        try:
            cur = dt.date.fromisoformat(start_date)
        except Exception:
            return {}
        sched = dict(d.get("duty", {}).get("schedule", {}))

        # 先算一遍能排几天，一天都排不出来就直接返回，【绝不写文件】。
        # 否则「选错了星期 / 天数太小」会把已有的排班清空。
        plan = []
        for i in range(int(days)):
            day = cur + dt.timedelta(days=i)
            if day.weekday() in weekdays:
                plan.append(day)
        if not plan:
            return {}

        # 先把这个日期范围内【旧的排班清掉】再排 ——
        # 否则以前排过、但这次不排的星期（比如周日）会一直留在表里，
        # 看起来就像「新规则没生效」。
        days = int(days)
        for i in range(days):
            sched.pop((cur + dt.timedelta(days=i)).isoformat(), None)

        n = 0
        for day in plan:
            sched[day.isoformat()] = groups[n % len(groups)]["id"]
            n += 1
        d.setdefault("duty", {})["schedule"] = sched
        self._save(d)
        return sched


    # ---------------------------------------------------------------- 签到打卡

    def checkin(self):
        """当前签到任务 + 签到记录。

        结构：
            checkin.current   {id, title, start, end, created}  没有任务时为 None
            checkin.records   {taskId: {key: {name, at, no}}}
            checkin.history   [id, ...]  历次任务 id（倒序）
        """
        c = self._load().get("checkin")
        if not isinstance(c, dict):
            c = {}
        return {
            "current": c.get("current") or None,
            "records": c.get("records") or {},
            "history": c.get("history") or [],
        }

    @staticmethod
    def _now_ts():
        return time.time()

    def publish_checkin(self, title, start, end):
        """发布一个签到任务。start / end 是 ISO 本地时间字符串。"""
        d = self._load()
        c = d.get("checkin")
        if not isinstance(c, dict):
            c = {"current": None, "records": {}, "history": []}
        tid = "t%d" % int(time.time())
        task = {
            "id": tid,
            "title": (title or "签到").strip()[:40],
            "start": str(start or ""),
            "end": str(end or ""),
            "created": self._now_ts(),
        }
        # 上一个任务挪进历史
        old = c.get("current")
        if isinstance(old, dict) and old.get("id"):
            c.setdefault("history", [])
            if old["id"] not in c["history"]:
                c["history"].insert(0, old["id"])
            c["history"] = c["history"][:60]
        c["current"] = task
        c.setdefault("records", {})[tid] = {}
        d["checkin"] = c
        self._save(d)
        return task

    def close_checkin(self):
        d = self._load()
        c = d.get("checkin")
        if not isinstance(c, dict):
            return False
        old = c.get("current")
        if isinstance(old, dict) and old.get("id"):
            c.setdefault("history", [])
            if old["id"] not in c["history"]:
                c["history"].insert(0, old["id"])
        c["current"] = None
        d["checkin"] = c
        self._save(d)
        return True

    @staticmethod
    def checkin_state(task, now=None):
        """任务现在处于什么状态：pending（还没开始）/ open / closed。"""
        import datetime as dt
        if not isinstance(task, dict):
            return "none"
        now = now or dt.datetime.now()

        def parse(s):
            s = (s or "").strip()
            if not s:
                return None
            for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S",
                        "%Y-%m-%d %H:%M:%S"):
                try:
                    return dt.datetime.strptime(s, fmt)
                except Exception:
                    continue
            return None

        st, en = parse(task.get("start")), parse(task.get("end"))
        if st and now < st:
            return "pending"
        if en and now > en:
            return "closed"
        return "open"

    def sign_checkin(self, name, no=""):
        """同学签个到。同一个人重复签只更新时间，不刷人数。"""
        name = (name or "").strip()
        if not name:
            return None, "请填名字"
        d = self._load()
        c = d.get("checkin")
        if not isinstance(c, dict) or not isinstance(c.get("current"), dict):
            return None, "现在没有签到任务"
        task = c["current"]
        if self.checkin_state(task) != "open":
            return None, "不在签到时间内"
        tid = task["id"]
        recs = c.setdefault("records", {}).setdefault(tid, {})
        key = name
        old = recs.get(key)
        recs[key] = {
            "name": name,
            "no": str(no or (old or {}).get("no") or "").strip(),
            "at": self._now_ts(),
            "count": int((old or {}).get("count") or 0) + 1,
        }
        d["checkin"] = c
        self._save(d)
        return recs[key], None

    def checkin_stats(self, task_id=None):
        """签到统计。不传 task_id 就统计当前任务。"""
        c = self.checkin()
        task = c.get("current")
        if task_id:
            for hid in c.get("history", []):
                if hid == task_id:
                    break
        if not task_id and task:
            task_id = task["id"]
        recs = (c.get("records") or {}).get(task_id or "", {}) or {}
        people = sorted(recs.values(), key=lambda r: r.get("at") or 0)
        return {
            "task": task if (task and task.get("id") == task_id) else (
                None if task_id else task),
            "taskId": task_id,
            "count": len(people),
            "records": people,
            "state": self.checkin_state(task) if task else "none",
        }

    # ---------------------------------------------------------------- 导入

    @staticmethod
    def parse_roster(text):
        """把粘贴进来的名单文本解析成学生列表。

        容错几种常见写法（制表符 / 逗号 / 抖号 / 多个空格分隔）：
            01   张三   男
            张三
            20265103010028,张三,男
            张三 男
        会自动判断哪一列是学号、哪一列是姓名、哪一列是性别。
        """
        import re
        rows = []
        for raw in (text or "").replace("\r", "\n").split("\n"):
            line = raw.strip()
            if not line:
                continue
            # 跳过表头
            if re.match(r"^(序号|学号|姓名|性别|班级)\b", line) and len(line) < 24:
                continue
            parts = [p.strip() for p in re.split(r"[\t,，;；|]+|\s{2,}", line) if p.strip()]
            if len(parts) == 1:
                parts = [p for p in re.split(r"\s+", line) if p]
            if not parts:
                continue

            no = name = gender = ""
            rest = []
            for p in parts:
                if not no and re.fullmatch(r"\d+", p):   # 1 位序号到长学号都算编号
                    no = p
                elif not gender and p in ("男", "女", "M", "F", "male", "female"):
                    gender = "男" if p in ("男", "M", "male") else "女"
                elif not name:
                    name = p
                else:
                    rest.append(p)
            if not name:
                continue
            rows.append({"no": no, "name": name, "gender": gender,
                         "note": " ".join(rest)})
        return rows


# 全局单例（server.py 直接用）
store = ClassStore()
