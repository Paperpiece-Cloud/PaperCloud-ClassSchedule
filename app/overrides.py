"""手动调整覆盖层。

为什么需要它：
    手改的调课 / 停课，只要跑一次「抓取课表」就会被学校那边的原始课表覆盖掉。
    所以把这些调整单独存在 data/overrides.json 里，
    每次导入之后自动重新套用一遍。

格式：
{
  "moves": [
    {"name": "C语言程序及应用", "weekday": 2,
     "from": [3, 4], "to": [5, 6], "weeks": [9, 10]}
  ],
  "cancels": [
    {"name": "电子技术与应用", "before": "2026-10-19"}
  ]
}

moves   : 把某个时间段的课，在指定周次挪到别的时间段
cancels : 取消某天之前的全部课（按学期起始日推算周次）
"""

import copy
import datetime
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "data", "overrides.json")


def load():
    try:
        with open(PATH, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            d.setdefault("moves", [])
            d.setdefault("cancels", [])
            return d
    except Exception:
        pass
    return {"moves": [], "cancels": []}


def save(d):
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, PATH)


def _courses(sched):
    if isinstance(sched, dict):
        return sched.get("courses")
    return getattr(sched, "courses", None)


def _term_start(sched):
    if isinstance(sched, dict):
        return sched.get("termStart") or sched.get("term_start")
    return getattr(sched, "term_start", None)


def apply(sched, term_start=None):
    """把覆盖层套到课表上。就地把 sched 里的课改掉，返回改了几处。"""
    ovr = load()
    cs = _courses(sched)
    if not cs:
        return 0

    ts = term_start or _term_start(sched)
    if isinstance(ts, str):
        try:
            ts = datetime.date.fromisoformat(ts[:10])
        except Exception:
            ts = None
    if not isinstance(ts, datetime.date):
        ts = None
    if ts is None:
        # 兜底：从 config/secrets.json / config.json 里读 term_start
        for fn in ("secrets.json", "config.json"):
            try:
                with open(os.path.join(ROOT, "config", fn), encoding="utf-8-sig") as f:
                    cfg = json.load(f)
                v = cfg.get("term_start")
                if v:
                    ts = datetime.date.fromisoformat(str(v)[:10])
                    break
            except Exception:
                continue

    n = 0

    # ---------------- 停课 ----------------
    for rule in ovr.get("cancels") or []:
        name = rule.get("name") or ""
        before = rule.get("before") or ""
        cut = None
        try:
            cut = datetime.date.fromisoformat(before[:10])
        except Exception:
            cut = None
        if not name or cut is None or ts is None:
            continue
        for c in cs:
            if name not in (c.get("name") or ""):
                continue
            wd = c.get("weekday") or 1
            keep = []
            for wk in (c.get("weeks") or []):
                day = ts + datetime.timedelta(days=(wk - 1) * 7 + (wd - 1))
                if day >= cut:
                    keep.append(wk)
            if keep != (c.get("weeks") or []):
                c["weeks"] = keep
                n += 1

    # 清掉周次空掉的课
    cs[:] = [c for c in cs if c.get("weeks")]

    # ---------------- 调课 ----------------
    def overlaps(weeks, target):
        return [w for w in (weeks or []) if w in (target or [])]

    for rule in ovr.get("moves") or []:
        name = rule.get("name") or ""
        wd = rule.get("weekday")
        frm = rule.get("from") or []
        to = rule.get("to") or []
        wks = rule.get("weeks") or []
        if not (name and wd and len(frm) >= 2 and len(to) >= 2 and wks):
            continue
        hit = None
        for c in cs:
            if (name in (c.get("name") or "") and c.get("weekday") == wd
                    and c.get("startSection") == frm[0] and c.get("endSection") == frm[1]
                    and overlaps(c.get("weeks"), wks)):
                hit = c
                break
        if hit is None:
            continue
        moved_weeks = overlaps(hit.get("weeks"), wks)
        hit["weeks"] = [w for w in hit["weeks"] if w not in moved_weeks]
        m = copy.deepcopy(hit)
        m["id"] = (hit.get("id") or "c") + "-moved"
        m["startSection"], m["endSection"] = to[0], to[1]
        m["weeks"] = moved_weeks
        m["note"] = "调课：原 %s %s" % (frm, to)
        raw = m.get("raw")
        if isinstance(raw, dict):
            raw["moved"] = m["note"]
        cs.append(m)
        n += 1

    cs[:] = [c for c in cs if c.get("weeks")]


    # ---------------- 改教室 ----------------
    # 只对规则里指定的周次生效：把那些周次从原课里摘出来，
    # 复制一份换成新教室，原课保留其余周次。
    for rule in ovr.get("rooms") or []:
        name = rule.get("name") or ""
        wd = rule.get("weekday")
        secs = rule.get("sections") or []
        wks = rule.get("weeks") or []
        room = rule.get("room") or ""
        if not (name and wd and len(secs) >= 2 and wks and room):
            continue
        hit = None
        for c in cs:
            if (name in (c.get("name") or "")
                    and c.get("weekday") == wd
                    and c.get("startSection") == secs[0]
                    and c.get("endSection") == secs[1]):
                hit = c
                break
        if hit is None:
            continue
        moved = [w for w in (hit.get("weeks") or []) if w in wks]
        if not moved:
            continue
        hit["weeks"] = [w for w in hit["weeks"] if w not in moved]
        m = copy.deepcopy(hit)
        m["id"] = (hit.get("id") or "c") + "-room"
        m["room"] = room
        m["weeks"] = moved
        m["note"] = "改教室：%s -> %s" % (hit.get("room") or "", room)
        raw = m.get("raw")
        if isinstance(raw, dict):
            raw["room"] = m["note"]
        cs.append(m)
        n += 1

    # ---------------- 新增课程（overrides.adds） ----------------
    # 注意：必须放在 return 之前，传的是同一个 cs 列表对象，
    # _apply_adds 直接往里 append。
    try:
        n += _apply_adds({"courses": cs}, ovr.get("adds"))
    except Exception:
        import traceback; traceback.print_exc()
    cs[:] = [c for c in cs if c.get("weeks")]

    if isinstance(sched, dict):
        sched["courses"] = cs
        if "count" in sched:
            sched["count"] = len(cs)
    return n



def _apply_adds(sched, adds):
    """把「新增课程」补进课表。

    adds 里每项：
        {"name": "电子技术与应用", "weekday": 3, "startSection": 5,
         "endSection": 6, "weeks": [9], "teacher": "杨其", "room": "201C_206",
         "tag": "调课", "hot": true}
    已经存在的（同 name+weekday+startSection+endSection）就跳过，避免重复。
    """
    courses = sched.get("courses") or []
    seen = set()
    for c in courses:
        seen.add((c.get("name"), c.get("weekday"),
                  c.get("startSection"), c.get("endSection")))
    n = 0
    for a in adds or []:
        if not isinstance(a, dict):
            continue
        key = (a.get("name"), a.get("weekday"),
               a.get("startSection"), a.get("endSection"))
        if key in seen:
            continue
        c = {
            "id": a.get("id") or ("add-%s-%s-%s" % (a.get("name"),
                                                    a.get("weekday"),
                                                    a.get("startSection"))),
            "name": a.get("name") or "",
            "teacher": a.get("teacher") or "",
            "room": a.get("room") or "",
            "className": a.get("className") or "",
            "campus": a.get("campus") or "",
            "credit": a.get("credit") or "",
            "type": a.get("type") or "",
            "weekday": int(a.get("weekday") or 0),
            "startSection": int(a.get("startSection") or 0),
            "endSection": int(a.get("endSection") or 0),
            "weeks": list(a.get("weeks") or []),
            "tag": a.get("tag") or "",
            "hot": bool(a.get("hot")),
            "raw": {"source": "override-add"},
        }
        courses.append(c)
        seen.add(key)
        n += 1
    sched["courses"] = courses
    sched["count"] = len(courses)
    return n
