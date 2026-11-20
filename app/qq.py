# -*- coding: utf-8 -*-
"""QQ 群接入（OneBot v11 / NapCat 本地协议端）

原理
----
云电脑上跑一个 NapCat（基于 NTQQ 的协议端），它提供：
  1) HTTP API   —— 我们主动调它发消息      POST http://127.0.0.1:3000/send_group_msg
  2) HTTP 上报  —— 群里有人说话，它推给我们 POST <本站>/api/qq/webhook

本站只需要一个能收发 HTTP 的小模块，不需要任何第三方库。

配置（config/secrets.json）
--------------------------
  "qq_api"        : "http://127.0.0.1:3000",   # NapCat 的 HTTP API 地址
  "qq_token"      : "你在 NapCat 里设的 token",  # 可为空
  "qq_group"      : 123456789,                 # 默认推送的群号
  "qq_webhook_key": "随便一串随机字符",           # 防止别人乱调你的 webhook
  "qq_enabled"    : true

安全
----
  · 只允许白名单群号触发（qq_group + qq_groups）
  · webhook 必须带 ?key=<qq_webhook_key>
  · 发消息只发到配置里写的群，不接受外部指定群号
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG_PATH = os.path.join(ROOT, "config", "secrets.json")


# ---------------------------------------------------------------- 配置
def load_cfg():
    """每次现读配置文件，改完不用重启。"""
    try:
        with open(CFG_PATH, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {}


def cfg_of(app_cfg=None):
    """优先用内存里的 cfg，没有的键回落到磁盘。"""
    d = dict(app_cfg or {})
    disk = load_cfg()
    for k in ("qq_api", "qq_token", "qq_group", "qq_groups",
              "qq_webhook_key", "qq_enabled", "qq_push_time"):
        if k not in d or d.get(k) in (None, ""):
            if k in disk:
                d[k] = disk[k]
    return d


def enabled(cfg):
    v = cfg.get("qq_enabled")
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)


def base_url(cfg):
    return str(cfg.get("qq_api") or "http://127.0.0.1:3000").rstrip("/")


def allow_groups(cfg):
    """允许触发的群号集合。"""
    out = set()
    g = cfg.get("qq_group")
    if g not in (None, "", 0, "0"):
        try:
            out.add(int(g))
        except Exception:
            pass
    for x in (cfg.get("qq_groups") or []):
        try:
            out.add(int(x))
        except Exception:
            pass
    return out


# ---------------------------------------------------------------- 调用
def _post(cfg, path, payload, timeout=8):
    url = base_url(cfg) + path
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    tok = str(cfg.get("qq_token") or "").strip()
    if tok:
        req.add_header("Authorization", "Bearer " + tok)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return True, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        return False, {"http": e.code, "msg": e.read().decode("utf-8", "replace")[:200]}
    except Exception as e:
        return False, {"msg": "%s: %s" % (type(e).__name__, e)}


def send_group(cfg, text, group_id=None):
    """往群里发一条纯文本。返回 (ok, info)。"""
    g = group_id or cfg.get("qq_group")
    try:
        g = int(g)
    except Exception:
        return False, {"msg": "没配置群号 qq_group"}
    return _post(cfg, "/send_group_msg", {"group_id": g, "message": str(text)})


def send_group_segments(cfg, segments, group_id=None):
    """发一条「数组格式」的消息，可以夹 @。

    segments 例：
        [{"type": "text", "data": {"text": "【值日】1组"}},
         {"type": "at",   "data": {"qq": "123456"}},
         {"type": "text", "data": {"text": " "}}]
    """
    g = group_id or cfg.get("qq_group")
    try:
        g = int(g)
    except Exception:
        return False, {"msg": "没配置群号 qq_group"}
    return _post(cfg, "/send_group_msg", {"group_id": g, "message": segments})


# ---------------------------------------------------------------- 群成员
_MEMBERS_CACHE = {}      # group_id -> (时间, 列表)
_MEMBERS_TTL = 300       # 5 分钟


def get_group_members(cfg, group_id):
    """取群成员列表。返回 (ok, list)。

    每项：{'qq': '123', 'card': '群名片', 'nick': 'QQ昵称', 'name': '显示的称呼'}
    """
    try:
        gid = int(group_id)
    except Exception:
        return False, []

    import time as _t
    hit = _MEMBERS_CACHE.get(gid)
    if hit and _t.time() - hit[0] < _MEMBERS_TTL:
        return True, hit[1]

    ok, d = _post(cfg, "/get_group_member_list", {"group_id": gid}, timeout=15)
    if not ok or not isinstance(d, dict):
        return False, []
    raw = d.get("data")
    if not isinstance(raw, list):
        return False, []

    out = []
    for m in raw:
        if not isinstance(m, dict):
            continue
        uid = m.get("user_id")
        if uid is None:
            continue
        card = str(m.get("card") or "").strip()
        nick = str(m.get("nickname") or "").strip()
        out.append({
            "qq": str(uid),
            "card": card,
            "nick": nick,
            "name": card or nick,
        })
    _MEMBERS_CACHE[gid] = (_t.time(), out)
    return True, out


def _norm(s):
    """去掉空格、全角空格、-、_、+ 等，便于比对。"""
    s = str(s or "")
    for ch in (" ", "\u3000", "\t", "-", "_", "+", "(", ")", "（", "）"):
        s = s.replace(ch, "")
    return s


def _digits(s):
    """取出字符串里所有数字，拼成一串。"""
    return "".join(ch for ch in str(s or "") if ch.isdigit())


def _subseq(needle, hay):
    """needle 的字符是否按顺序出现在 hay 里。"""
    it = iter(hay)
    return all(ch in it for ch in needle)


def _name_score(name, card):
    """名字和群名片的契合度。0 表示不像。"""
    c = _norm(card)
    if not name or not c:
        return 0
    if c == name:
        return 100
    if c.startswith(name):
        return 90
    if c.endswith(name):
        return 80
    if name in c:
        return 70
    if len(name) >= 2 and _subseq(name, c):
        return 50
    return 0


def match_members(members, people):
    """把「值日小组的成员」匹配到「QQ 群成员」。

    people 每项可用字段：name / phone / no（学号）
    群名片千奇百怪，所以按四级兜底：
        ① 手机号后 8 位 或 学号 命中
        ② 姓名契合度（完全/开头/结尾/包含）>= 70
        ③ 姓名契合度 >= 50（字按顺序出现）
        ④ 模糊容错：允许错一个字（重合度 >= 姓名长度-1）
    返回 (匹配结果列表, 没匹配上的姓名列表)
    匹配结果每项 {"qq": "...", ...person 字段}
    """
    qqs = []
    missing = []
    used = set()
    avail = list(members)

    for p in people or []:
        name = _norm(p.get("name"))
        phone = _digits(p.get("phone"))
        sno = _digits(p.get("no"))
        if not name and not phone and not sno:
            continue

        hit = None

        # ① 号码类：手机号后 8 位 / 学号后 8 位
        tails = []
        if len(phone) >= 8:
            tails.append(phone[-8:])
        if len(sno) >= 8:
            tails.append(sno[-8:])
        for tail in tails:
            for m in avail:
                if m["qq"] in used:
                    continue
                if tail in _digits(m["card"]) or tail in _digits(m["nick"]):
                    hit = m
                    break
            if hit:
                break

        # ② / ③ 打分
        if hit is None and name:
            best = None
            best_sc = 0
            for m in avail:
                if m["qq"] in used:
                    continue
                sc = max(_name_score(name, m["card"]),
                         _name_score(name, m["nick"]) - 5)
                if sc > best_sc:
                    best_sc = sc
                    best = m
            if best is not None and best_sc >= 50:
                hit = best

        # ④ 模糊容错：允许一个错字
        if hit is None and len(name) >= 2:
            best = None
            best_sc = -1
            need = len(set(name)) - 1
            for m in avail:
                if m["qq"] in used:
                    continue
                c = _norm(m["card"]) + _norm(m["nick"])
                if not c:
                    continue
                common = len(set(name) & set(c))
                if common >= need:
                    sc = common * 10 - abs(len(_norm(m["card"])) - len(name))
                    if sc > best_sc:
                        best_sc = sc
                        best = m
            if best is not None:
                hit = best

        if hit is not None:
            used.add(hit["qq"])
            item = {"qq": hit["qq"]}
            item.update(p)
            qqs.append(item)
        else:
            missing.append(p.get("name") or "")
        avail = [m for m in avail if m["qq"] not in used]

    return qqs, missing

def send_private(cfg, text, user_id):
    try:
        uid = int(user_id)
    except Exception:
        return False, {"msg": "user_id 不对"}
    return _post(cfg, "/send_private_msg", {"user_id": uid, "message": str(text)})


def ping(cfg):
    """探一下协议端活着没。"""
    ok, d = _post(cfg, "/get_login_info", {})
    if ok and isinstance(d, dict):
        data = d.get("data") or {}
        return True, data.get("nickname") or data.get("user_id") or "已登录"
    return False, d


def parse_event(body):
    """从 OneBot 上报里取出消息信息，返回 dict 或 None。"""
    if not isinstance(body, dict):
        return None
    if body.get("post_type") != "message":
        return None
    mtype = body.get("message_type") or ""
    gid = body.get("group_id")
    uid = body.get("user_id")
    text = (body.get("raw_message") or "").strip()
    if not text:
        segs = body.get("message") or []
        if isinstance(segs, list):
            text = "".join(s.get("data", {}).get("text", "") for s in segs
                           if isinstance(s, dict)).strip()
    sender = body.get("sender") or {}
    if not isinstance(sender, dict):
        sender = {}
    return {
        "group_id": gid,
        "user_id": uid,
        "message_type": mtype,
        "text": text,
        "role": str(sender.get("role") or "").lower(),
        "nickname": sender.get("card") or sender.get("nickname") or "",
    }
