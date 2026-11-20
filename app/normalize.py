"""把教务系统五花八门的课表字段归一化成统一结构。

强智新版接口既有老式拼音段名（kcmc/xm/cdmc/xqj/jcs/zcd），
也可能返回驼峰英文名（courseName/teacherName/...），这里全部兼容。
真正拿到真实响应后，如果发现新字段，只要往 _PICK 里加候选名即可。
"""

import re

WEEKDAY_NAMES = ["", "周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# 每类信息的候选字段名（按优先级）
_PICK = {
    "id":        ["jxbid", "kbId", "id", "jxbmc", "kcbh", "courseId", "kcid", "kb_id"],
    "name":      ["kcmc", "courseName", "kcname", "kcmcShow", "name", "course_name"],
    "teacher":   ["xm", "teacherName", "jsxm", "teacher", "jsmc", "skjs", "teacher_name"],
    "room":      ["cdmc", "roomName", "classroomName", "jsmc", "place", "classroom",
                  "cdmcShow", "room"],
    "weekday":   ["xqj", "weekday", "weekDay", "xingqi", "week", "xq"],
    "sections":  ["jcs", "jc", "sections", "jcor", "jcsShow", "section", "jcs2", "time", "timeName"],
    "weeks":     ["zcd", "zcdShow", "weeks", "zhouci", "zc", "weekRange", "zcds"],
    "className": ["jxbmc", "bjmc", "className", "teachingClassName", "bj", "class_name",
                  "jxbmcShow"],
    "campus":    ["xqmc", "campusName", "campus", "xqmcShow"],
    "credit":    ["xf", "credit"],
    "type":      ["kclx", "courseType", "kcxzmc", "type"],
}


def pick(d, key, default=None):
    """按候选名顺序取值，兼容 None / 空串。"""
    for cand in _PICK.get(key, [key]):
        if cand in d and d[cand] not in (None, "", []):
            return d[cand]
    return default


def _text(v):
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        return " ".join(_text(x) for x in v)
    return str(v).strip()


# ---------------------------------------------------------------- 周次解析

_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8,
           "九": 9, "十": 10, "十一": 11, "十二": 12, "十三": 13, "十四": 14,
           "十五": 15, "十六": 16, "十七": 17, "十八": 18, "十九": 19, "二十": 20}


def parse_weeks(value, max_week=30):
    """'1-16周' / '1,3,5' / '1-8,10-16周' / '第1-16周' / [1,2,3] -> [1..16]"""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        out = set()
        for v in value:
            out.update(parse_weeks(v, max_week))
        return sorted(out)

    s = _text(value)
    if not s:
        return []
    s = s.replace("（", "(").replace("）", ")").replace("，", ",")

    # 单双周标记：'2-16周(双)' / '1-15周(单)' / '2-16双周'
    parity = None
    if re.search(r"[(]?\s*双\s*[)]?[周]?", s):
        parity = "even"
    elif re.search(r"[(]?\s*单\s*[)]?[周]?", s):
        parity = "odd"

    s = re.sub(r"第|[周周\(\)]|星期|\(.*?\)|单周|双周|单|双", "", s)

    out = set()
    for part in re.split(r"[,、;；\s]+", s):
        if not part:
            continue
        m = re.match(r"^(\d+)\s*[-~—到]\s*(\d+)$", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if a > b:
                a, b = b, a
            out.update(range(a, b + 1))
            continue
        m = re.match(r"^(\d+)$", part)
        if m:
            out.add(int(m.group(1)))
            continue
        # '单周' / '双周' 之类已经在上面的正则里被剥掉了，这里兜底扫数字
        for num in re.findall(r"\d+", part):
            out.add(int(num))

    if parity == "even":
        out = {w for w in out if w % 2 == 0}
    elif parity == "odd":
        out = {w for w in out if w % 2 == 1}
    return sorted(w for w in out if 1 <= w <= max_week)


# ---------------------------------------------------------------- 节次解析

def parse_sections(value):
    """'1-2节' / '1-2' / '3,4' / 3 -> (start, end)，从 1 开始。"""
    if value is None:
        return (0, 0)
    if isinstance(value, (list, tuple)):
        nums = [int(x) for x in value if _text(x).isdigit()]
        if nums:
            return (min(nums), max(nums))
    s = _text(value)
    if not s:
        return (0, 0)
    s = re.sub(r"[节次]|第|\s", "", s)
    m = re.search(r"(\d+)\s*[-~—到]\s*(\d+)", s)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return (min(a, b), max(a, b))
    nums = [int(x) for x in re.findall(r"\d+", s)]
    if not nums:
        return (0, 0)
    return (min(nums), max(nums))


def parse_weekday(value):
    """'星期一'/'1'/'周一'/1 -> 1..7；识别不了返回 0。"""
    if value is None:
        return 0
    if isinstance(value, int):
        return value if 1 <= value <= 7 else 0
    s = _text(value)
    if not s:
        return 0

    m = re.search(r"(\d+)", s)
    if m:
        n = int(m.group(1))
        return n if 1 <= n <= 7 else 0

    # 「星期天 / 周日」也算周日
    if "天" in s or s.endswith("日"):
        return 7

    # 中文数字：按「长优先」匹配，否则「周十一」会先命中「一」判成周一
    for ch in sorted(_CN_NUM, key=len, reverse=True):
        if ch in s:
            n = _CN_NUM[ch]
            return n if 1 <= n <= 7 else 0

    for i, nm in enumerate(WEEKDAY_NAMES):
        if nm and nm in s:
            return i
    return 0


# ---------------------------------------------------------------- 主入口

def normalize_course(item, max_week=30):
    if not isinstance(item, dict):
        return None
    wd = parse_weekday(pick(item, "weekday"))
    start, end = parse_sections(pick(item, "sections"))
    weeks = parse_weeks(pick(item, "weeks"), max_week)
    name = _text(pick(item, "name"))
    if not name and not weeks and not wd:
        return None
    return {
        "id": _text(pick(item, "id")) or f"{name}-{wd}-{start}-{end}",
        "name": name,
        "teacher": _text(pick(item, "teacher")),
        "room": _text(pick(item, "room")),
        "className": _text(pick(item, "className")),
        "campus": _text(pick(item, "campus")),
        "credit": _text(pick(item, "credit")),
        "type": _text(pick(item, "type")),
        "weekday": wd,
        "startSection": start,
        "endSection": end,
        "weeks": weeks,
        "raw": item,
    }


def _find_course_list(data):
    """在响应里找出课表数组。"""
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    # 常见容器名，按优先级
    for key in ("kbList", "courseList", "list", "rows", "data", "records",
                "studentSchedule", "scheduleList", "courses", "items", "result"):
        v = data.get(key)
        if isinstance(v, list) and v:
            return v
        if isinstance(v, dict):
            inner = _find_course_list(v)
            if inner:
                return inner
    # 兜底：找出第一个「看起来像课表条目」的 list
    for v in data.values():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            keys = set(v[0].keys())
            if keys & {"kcmc", "courseName", "zcd", "xqj", "jcs", "weeks", "weekday"}:
                return v
    for v in data.values():
        if isinstance(v, (dict, list)):
            inner = _find_course_list(v)
            if inner:
                return inner
    return []


def _grid_blocks(raw):
    """识别「时段块」结构。

    真实的 grd 课表接口
    （POST /grd/api/arrange/CourseScheduleAllQuery/studentCourseSchedule）
    返回的不是课程扁平数组，而是：

        {"code":200,"data":[
            {"time":{"timeCode":"1_2","timeName":"第1-2节"},
             "week":{"weekCode":"2","weekName":"星期一"},
             "courseList":[{"courseName":"C语言程序及应用",
                            "dayOfWeek":"2","time":"1,2",
                            "weeks":"8","teacherName":"韦静静",
                            "classroomName":"402_510", ...}]},
            ... 35 个块 = 5 时段 × 7 天 ...
        ]}

    老解析器会把每个「块」当成一门课，于是解析出一堆空课程。
    这里先把这种结构认出来。
    """
    data = raw.get("data") if isinstance(raw, dict) else raw
    if not isinstance(data, list) or not data:
        return None
    hits = 0
    for b in data:
        if isinstance(b, dict) and isinstance(b.get("courseList"), list) \
                and ("time" in b or "week" in b):
            hits += 1
    # 半数以上是这种块，就认定是块结构
    return data if hits and hits * 2 >= len(data) else None


def _normalize_grid(blocks, max_week=30):
    """把「时段块」结构摊平成课程列表，并把同一门课的多个周次合并。"""
    merged = {}      # (name, teacher, room, weekday, start, end) -> set(weeks)

    for blk in blocks:
        if not isinstance(blk, dict):
            continue
        tinfo = blk.get("time") if isinstance(blk.get("time"), dict) else {}
        winfo = blk.get("week") if isinstance(blk.get("week"), dict) else {}

        for c in (blk.get("courseList") or []):
            if not isinstance(c, dict):
                continue
            name = _text(pick(c, "name"))
            if not name:
                continue

            # 星期：优先用中文名，其次用数字（1=周日, 2=周一 ... 8=周日）
            weekday = parse_weekday(pick(c, "dayOfWeekName") or winfo.get("weekName"))
            if not weekday:
                dow = _text(pick(c, "dayOfWeek") or winfo.get("weekCode"))
                if dow.isdigit():
                    n = int(dow)
                    weekday = 7 if n in (1, 8) else max(1, min(7, n - 1))
            if not weekday:
                continue

            # 节次：time = "1,2"，或 timeName = "第1,2节"
            start, end = parse_sections(pick(c, "sections")
                                        or tinfo.get("timeName") or tinfo.get("timeCode"))
            if not start:
                continue

            # 周次：这一条是「哪一周」的课
            weeks = parse_weeks(pick(c, "weeks"), max_week)
            if not weeks:
                wk = _text(winfo.get("weekCode") or winfo.get("sort"))
                if wk.isdigit():
                    weeks = [int(wk)]
            # 接口没给周次时，按「整学期都有」处理更实用
            if not weeks:
                weeks = list(range(1, max_week + 1))

            key = (name, _text(pick(c, "teacher")),
                   _text(pick(c, "room")), weekday, start, end)
            slot = merged.setdefault(key, {"weeks": set(),
                                           "className": _text(pick(c, "className"))})
            slot["weeks"].update(w for w in weeks if 1 <= w <= max_week)
            if not slot["className"]:
                slot["className"] = _text(pick(c, "className"))

    out = []
    for (name, teacher, room, weekday, start, end), slot in merged.items():
        wset = slot["weeks"]
        out.append({
            "id": f"grid-{name}-{weekday}-{start}"[:80],
            "name": name,
            "teacher": teacher,
            "room": room,
            "className": slot["className"],
            "campus": "",
            "credit": "",
            "type": "",
            "weekday": weekday,
            "startSection": start,
            "endSection": end,
            "weeks": sorted(wset),
            "raw": {"source": "grid"},
        })
    out.sort(key=lambda c: (c["weekday"], c["startSection"], c["name"]))
    return out


def normalize_schedule(raw, max_week=30):
    """把课表接口的原始响应归一化。"""
    blocks = _grid_blocks(raw)
    if blocks is not None:
        courses = _normalize_grid(blocks, max_week)
        return {
            "courses": courses,
            "count": len(courses),
            "maxWeek": max(max_week, max((max(c["weeks"]) for c in courses if c["weeks"]),
                                         default=0)),
        }

    courses_raw = _find_course_list(raw)
    courses = [c for c in (normalize_course(x, max_week) for x in courses_raw) if c]

    # 去掉 weekday/sections 全空且没有周次的行（多为表头或统计行）
    courses = [c for c in courses if c["weekday"] or c["weeks"] or c["name"]]

    # 去重（同一门课同一时段可能重复返回）
    seen, uniq = set(), []
    for c in courses:
        key = (c["name"], c["weekday"], c["startSection"], c["endSection"],
               tuple(c["weeks"]), c["room"], c["teacher"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(c)

    max_w = max([max(c["weeks"]) for c in uniq if c["weeks"]] or [max_week])
    return {
        "courses": uniq,
        "maxWeek": min(max_w, max_week),
        "count": len(uniq),
    }


# ---------------------------------------------------------------- 手工录入解析

_HEADER_ALIASES = {
    "name":      ["课程名", "课程名称", "课程", "科目", "name"],
    "teacher":   ["任课教师", "教师", "老师", "teacher"],
    "room":      ["上课地点", "教室", "地点", "场地", "room"],
    "weekday":   ["上课星期", "星期", "周几", "weekday"],
    "sections":  ["上课节次", "节次", "节", "sections"],
    "weeks":     ["上课周次", "周次", "周数", "weeks"],
    "className": ["教学班", "班级", "class"],
}

_WEEKDAY_RE = re.compile(r"^(?:星期|周)\s*[一二三四五六日天1-7]$")


def _split_cells(line):
    # 支持英文/中文逗号、制表符、分号、竖线
    return [c.strip() for c in re.split(r"[,\uFF0C\t;；\|]+", line) if c.strip() != ""]


def _classify(cell):
    """猜这一格是什么字段。"""
    c = cell.strip()
    if _WEEKDAY_RE.match(c):
        return "weekday"
    has_digit = any(ch.isdigit() for ch in c)
    if "节" in c and has_digit:
        return "sections"
    if "周" in c and has_digit:
        return "weeks"
    return None


def parse_bulk_text(text, max_week=30):
    """把用户粘贴的文本解析成课表。

    支持两种写法（逗号/制表符/分号分隔，中英文标点都行）：

    带表头（推荐，列顺序随意）:
        课程, 教师, 教室, 星期, 节次, 周次
        高等数学A, 张伟, 教学楼1-101, 周一, 1-2节, 1-16周

    不带表头（自动识别星期/节次/周次三列，其余按 课程,教师,教室 顺序）:
        高等数学A, 张伟, 教学楼1-101, 周一, 1-2节, 1-16周

    返回 (courses, errors)。
    """
    lines = []
    for raw in (text or "").splitlines():
        s = raw.strip()
        if not s or s.startswith("#") or s.startswith("//"):
            continue
        lines.append(s)

    if not lines:
        return [], ["没有可解析的内容"]

    courses, errors = [], []

    # ---- 表头识别 ----
    header = None
    first = _split_cells(lines[0])
    mapped = []
    for cell in first:
        hit = None
        for field, aliases in _HEADER_ALIASES.items():
            if any(cell == a or cell.startswith(a) for a in aliases):
                hit = field
                break
        mapped.append(hit)
    if sum(1 for m in mapped if m) >= 3:
        header = mapped
        lines = lines[1:]

    for lineno, line in enumerate(lines, start=1):
        cells = _split_cells(line)
        if not cells:
            continue

        item = {}
        if header:
            for i, cell in enumerate(cells):
                field = header[i] if i < len(header) else None
                if field:
                    item[field] = cell
        else:
            leftovers = []
            for cell in cells:
                kind = _classify(cell)
                if kind and kind not in item:
                    item[kind] = cell
                else:
                    leftovers.append(cell)
            for key, val in zip(["name", "teacher", "room"], leftovers):
                item[key] = val

        name = _text(item.get("name"))
        if not name:
            errors.append(f"第 {lineno} 行：没找到课程名 —— {line[:60]}")
            continue

        wd = parse_weekday(item.get("weekday"))
        if not wd:
            errors.append(f"第 {lineno} 行：星期无法识别（写「周一」「星期一」或 1-7）—— {line[:60]}")
            continue

        start, end = parse_sections(item.get("sections"))
        if not start:
            errors.append(f"第 {lineno} 行：节次无法识别（写「1-2节」或「1-2」）—— {line[:60]}")
            continue

        weeks = parse_weeks(item.get("weeks"), max_week)
        if not weeks:
            errors.append(f"第 {lineno} 行：周次无法识别（写「1-16周」）—— {line[:60]}")
            continue

        courses.append({
            "id": f"manual-{len(courses)+1}-{name}-{wd}-{start}",
            "name": name,
            "teacher": _text(item.get("teacher")),
            "room": _text(item.get("room")),
            "className": _text(item.get("className")),
            "campus": "",
            "credit": "",
            "type": "",
            "weekday": wd,
            "startSection": start,
            "endSection": end,
            "weeks": weeks,
            "raw": {"source": "manual", "line": line},
        })

    max_w = max([max(c["weeks"]) for c in courses] or [max_week])
    return courses, errors, min(max_w, max_week)
