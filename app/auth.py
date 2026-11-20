# -*- coding: utf-8 -*-
"""账号系统：注册、登录、会话、角色、邮件验证码。

设计
----
· 账号以邮箱为主键，同时绑定学号
· 密码用 pbkdf2-hmac-sha256 + 随机盐，标准库，不存明文
· 会话是一个 HMAC 签名的小令牌，放 cookie，默认 30 天
· 角色三档：student（学生）/ committe（班委）/ admin（管理员）
· 验证码 6 位，10 分钟有效，最多试 5 次
· 邮件走 SMTP；没配置 SMTP 时验证码写进「待发件箱」，后台能看到

数据文件
--------
data/users.json
  {
    "users": [ {...} ],
    "codes": { "邮箱": {"code": "...", "exp": 时间戳, "tries": 0} },
    "outbox": [ {"to": "...", "subject": "...", "body": "...", "time": ...} ]
  }
"""

import base64
import hashlib
import hmac
import json
import os
import random
import re
import smtplib
import ssl
import time
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
USERS_PATH = os.path.join(DATA_DIR, "users.json")
CFG_PATH = os.path.join(ROOT, "config", "secrets.json")

CODE_TTL = 600          # 验证码 10 分钟
CODE_TRIES = 5          # 最多试 5 次
SESS_DAYS = 30          # 会话 30 天

ROLES = {"student": "学生", "committe": "班委", "admin": "管理员"}


# ---------------------------------------------------------------- 配置
def _cfg():
    try:
        with open(CFG_PATH, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {}


def mail_from():
    return str(_cfg().get("mail_from") or "PaperCloud <noreply@your-domain.example>")


def smtp_ready():
    c = _cfg()
    return bool(c.get("smtp_host") and c.get("smtp_user"))


# ---------------------------------------------------------------- 存取
def load():
    try:
        with open(USERS_PATH, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        d = {}
    if not isinstance(d, dict):
        d = {}
    d.setdefault("users", [])
    d.setdefault("codes", {})
    d.setdefault("outbox", [])
    return d


def save(d):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = USERS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, USERS_PATH)


# ---------------------------------------------------------------- 密码
def hash_pass(pw):
    salt = os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, 120000)
    return "pbkdf2$%s$%s" % (base64.b64encode(salt).decode(),
                             base64.b64encode(h).decode())


def check_pass(pw, stored):
    try:
        algo, salt_b64, hash_b64 = str(stored).split("$")
        if algo != "pbkdf2":
            return False
        salt = base64.b64decode(salt_b64)
        want = base64.b64decode(hash_b64)
        got = hashlib.pbkdf2_hmac("sha256", str(pw).encode("utf-8"), salt, 120000)
        return hmac.compare_digest(got, want)
    except Exception:
        return False


# ---------------------------------------------------------------- 校验
def norm_email(s):
    return str(s or "").strip().lower()


def valid_email(s):
    return bool(re.match(r"^[^@\s]{1,64}@[^@\s]{1,64}\.[^@\s]{2,}$", norm_email(s)))


def norm_no(s):
    return re.sub(r"\D", "", str(s or ""))


# ---------------------------------------------------------------- 会话
def _secret():
    c = _cfg()
    s = str(c.get("session_secret") or "")
    if not s:
        s = "kt-sess-" + hashlib.sha256(
            (str(c.get("access_code") or "") + str(c.get("admin_password") or ""))
            .encode("utf-8")).hexdigest()[:24]
    return s.encode("utf-8")


def make_session(uid):
    exp = int(time.time()) + SESS_DAYS * 86400
    raw = "%s|%d" % (uid, exp)
    sig = hmac.new(_secret(), raw.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
    return base64.urlsafe_b64encode(("%s|%s" % (raw, sig)).encode()).decode()


def read_session(token):
    try:
        raw = base64.urlsafe_b64decode(str(token).encode()).decode()
        uid, exp, sig = raw.split("|")
        good = hmac.new(_secret(), ("%s|%s" % (uid, exp)).encode("utf-8"),
                        hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(sig, good):
            return None
        if int(exp) < int(time.time()):
            return None
        return uid
    except Exception:
        return None


# ---------------------------------------------------------------- 用户
def find_user(d, email=None, uid=None):
    e = norm_email(email)
    for u in d.get("users") or []:
        if uid is not None and u.get("id") == uid:
            return u
        if e and norm_email(u.get("email")) == e:
            return u
    return None


def public_user(u):
    if not u:
        return None
    return {
        "id": u.get("id"),
        "no": u.get("no"),
        "name": u.get("name"),
        "email": u.get("email"),
        "role": u.get("role") or "student",
        "roleName": ROLES.get(u.get("role") or "student", "学生"),
        "verified": bool(u.get("emailVerified")),
        "created": u.get("created"),
        "lastLogin": u.get("lastLogin"),
    }


# ---------------------------------------------------------------- 验证码
def new_code():
    return "%06d" % random.randint(0, 999999)


def put_code(d, email, code):
    d["codes"][norm_email(email)] = {
        "code": code,
        "exp": int(time.time()) + CODE_TTL,
        "tries": 0,
    }


def check_code(d, email, code):
    rec = (d.get("codes") or {}).get(norm_email(email))
    if not rec:
        return False, "没有待验证的记录，请重新获取验证码"
    if int(rec.get("exp") or 0) < time.time():
        d["codes"].pop(norm_email(email), None)
        return False, "验证码已过期，请重新获取"
    if int(rec.get("tries") or 0) >= CODE_TRIES:
        d["codes"].pop(norm_email(email), None)
        return False, "错误次数过多，请重新获取验证码"
    rec["tries"] = int(rec.get("tries") or 0) + 1
    if str(code).strip() != str(rec.get("code")):
        return False, "验证码不对"
    d["codes"].pop(norm_email(email), None)
    return True, ""


# ---------------------------------------------------------------- 邮件
def send_mail(to, subject, body):
    """发信。成功返回 True；没配 SMTP 就写进待发件箱，返回 False。"""
    c = _cfg()
    host = str(c.get("smtp_host") or "").strip()
    user = str(c.get("smtp_user") or "").strip()
    pwd = str(c.get("smtp_pass") or "").strip()
    port = int(c.get("smtp_port") or 465)
    if not (host and user):
        return False

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = mail_from()
    msg["To"] = to

    try:
        if port == 465:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, timeout=15, context=ctx) as s:
                s.login(user, pwd)
                s.sendmail(user, [to], msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=15) as s:
                s.ehlo()
                try:
                    s.starttls(context=ssl.create_default_context())
                    s.ehlo()
                except Exception:
                    pass
                s.login(user, pwd)
                s.sendmail(user, [to], msg.as_string())
        return True
    except Exception:
        return False


def queue_mail(d, to, subject, body):
    """待发件箱，最多留 50 封。"""
    d["outbox"].insert(0, {
        "to": to, "subject": subject, "body": body, "time": int(time.time()),
    })
    del d["outbox"][50:]
