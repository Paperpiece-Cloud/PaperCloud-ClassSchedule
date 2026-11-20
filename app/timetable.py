"""生成 iCalendar (.ics) 课表，供手机自带日历订阅。

用 UTC 时间写出（北京时间 - 8 小时），这样不需要 VTIMEZONE 组件，
所有日历客户端都能正确解析。
"""

import datetime
import hashlib

# 默认节次时间表（如与学校不同，改 config 里的 section_times）
# 学校教务处的正式作息（2024-02-29 通知）
#   晨读 8:00-8:20，然后第 1~10 节如下。
#   注：实训课/机房课/体育课连堂时可提前 10 分钟结束 —— 这里按标准表算，
#   日历里写的是标准时间，连堂提前那 10 分钟不单独体现。
DEFAULT_SECTIONS = [
    ("08:30", "09:15"), ("09:25", "10:10"), ("10:30", "11:15"), ("11:25", "12:10"),
    ("14:10", "14:55"), ("15:05", "15:50"), ("16:10", "16:55"), ("17:05", "17:50"),
    ("19:00", "19:45"), ("19:55", "20:40"), ("20:50", "21:35"), ("21:45", "22:30"),
]

CN_TZ_OFFSET = datetime.timedelta(hours=8)


def _esc(text):
    """ICS 文本转义。"""
    if text is None:
        return ""
    s = str(text)
    s = s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    s = s.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")
    return s


def _fold(line):
    """按 RFC 5545 折行：每行不超过 75 个八位组。"""
    raw = line.encode("utf-8")
    if len(raw) <= 73:
        return line
    out, cur, n = [], [], 0
    for ch in line:
        b = len(ch.encode("utf-8"))
        if n + b > 73:
            out.append("".join(cur))
            cur, n = [], 0
        cur.append(ch)
        n += b
    if cur:
        out.append("".join(cur))
    # 续行前加一个空格
    return "\r\n ".join(out)


def _dt(date, hhmm):
    """本地时间 -> UTC 的 ICS 时间戳。"""
    h, m = int(hhmm[:2]), int(hhmm[3:5])
    local = datetime.datetime.combine(date, datetime.time(h, m))
    return (local - CN_TZ_OFFSET).strftime("%Y%m%dT%H%M%SZ")


def _sections(cfg_times):
    """拿到节次时间表，允许配置覆盖。"""
    if cfg_times:
        try:
            out = []
            for item in cfg_times:
                if isinstance(item, (list, tuple)) and len(item) == 2:
                    out.append((str(item[0]), str(item[1])))
                elif isinstance(item, str) and "-" in item:
                    a, b = item.split("-", 1)
                    out.append((a.strip(), b.strip()))
            if out:
                return out
        except Exception:
            pass
    return DEFAULT_SECTIONS


def build_ics(courses, term_start, max_week=20, section_times=None,
              calendar_name="班级课表"):
    """把课表转成 .ics 文本。term_start 是第 1 周的星期一 (YYYY-MM-DD)。"""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Class Timetable Mirror//CN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_esc(calendar_name)}",
        "X-WR-TIMEZONE:Asia/Shanghai",
        # 提示客户端多久回来刷新一次（并非所有客户端都支持，但无害）
        "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
        "X-PUBLISHED-TTL:PT1H",
    ]

    try:
        start_monday = datetime.datetime.strptime(term_start, "%Y-%m-%d").date()
    except Exception:
        start_monday = None

    secs = _sections(section_times)
    stamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    count = 0

    if start_monday is not None:
        start_monday -= datetime.timedelta(days=start_monday.weekday())  # 对齐到周一
        for c in courses or []:
            wd = int(c.get("weekday") or 0)
            s = int(c.get("startSection") or 0)
            e = int(c.get("endSection") or s)
            if not (1 <= wd <= 7) or s < 1 or s > len(secs):
                continue
            end_idx = min(max(e, s), len(secs))
            t0 = secs[s - 1][0]
            t1 = secs[end_idx - 1][1]

            for w in sorted(set(c.get("weeks") or [])):
                w = int(w)
                if w < 1 or w > max_week:
                    continue
                day = start_monday + datetime.timedelta(days=(w - 1) * 7 + (wd - 1))
                uid = hashlib.md5(
                    f"{c.get('name')}|{wd}|{s}|{w}|{day}".encode("utf-8")).hexdigest()
                summary = c.get("name") or "课程"
                desc_parts = []
                if c.get("teacher"):
                    desc_parts.append(f"教师：{c['teacher']}")
                if c.get("room"):
                    desc_parts.append(f"地点：{c['room']}")
                desc_parts.append(f"第 {w} 周 第 {s}-{end_idx} 节")
                if c.get("className"):
                    desc_parts.append(f"班级：{c['className']}")

                lines += [
                    "BEGIN:VEVENT",
                    f"UID:{uid}@class-timetable",
                    f"DTSTAMP:{stamp}",
                    f"DTSTART:{_dt(day, t0)}",
                    f"DTEND:{_dt(day, t1)}",
                    f"SUMMARY:{_esc(summary)}",
                    f"LOCATION:{_esc(c.get('room') or '')}",
                    f"DESCRIPTION:{_esc(chr(10).join(desc_parts))}",
                    # 提前 20 分钟提醒
                    "BEGIN:VALARM",
                    "TRIGGER:-PT20M",
                    "ACTION:DISPLAY",
                    f"DESCRIPTION:{_esc(summary)} 快上课了",
                    "END:VALARM",
                    "END:VEVENT",
                ]
                count += 1

    lines.append("END:VCALENDAR")
    body = "\r\n".join(_fold(l) for l in lines) + "\r\n"
    return body, count
