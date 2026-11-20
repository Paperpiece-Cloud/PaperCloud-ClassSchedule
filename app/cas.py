"""CAS 统一身份认证登录（gzdzxy 教务系统）。

流程（必须在同一个 cookie 会话里完成，因为 service 存在 CAS 的 session 中）：
    1. GET  jw.gzdzxy.cn/grd/api/cas/login?pattern=student-login&returnUrl=...
            → 302 → cas.gzdzxy.cn/sso/login   （拿到 lt / execution / JSESSIONID）
    2. POST cas.gzdzxy.cn/sso/login
            un=<账号> pd=<密码> rsa=strEnc(账号+密码+lt,'1','2','3')
            ul=<账号长度> pl=<密码长度> lt=<票据> execution=<e1s1> _eventId=submit
            → 302 回到教务系统并带 ticket
    3. 教务系统用 ticket 换取自己的会话 cookie
"""

import re
import urllib.parse

from .des import login_rsa_token
from .http import Session

CAS_ORIGIN = "https://cas.gzdzxy.cn"
JW_ORIGIN = "https://jw.gzdzxy.cn"
CAS_LOGIN_URL = CAS_ORIGIN + "/sso/login"

STUDENT_ENTRY = (JW_ORIGIN + "/grd/api/cas/login?pattern=student-login&returnUrl="
                 + urllib.parse.quote(JW_ORIGIN + "/grd/", safe=""))
TEACHER_ENTRY = (JW_ORIGIN + "/grd/api/cas/login?pattern=teacher-login&returnUrl="
                 + urllib.parse.quote(JW_ORIGIN + "/grd/", safe=""))

# 登录失败时 CAS 会把这些文案回显到页面上
_ERROR_PATTERNS = [
    (r"账号或密码错误", "账号或密码错误"),
    (r"用户名或密码错误", "账号或密码错误"),
    (r"密码错误", "密码错误"),
    (r"账号不存在", "账号不存在"),
    (r"用户不存在", "账号不存在"),
    (r"账号已锁定|账号被锁定|锁定", "账号被锁定"),
    (r"验证码错误", "验证码错误"),
    (r"认证失败|登录失败", "认证失败"),
]


class CasError(Exception):
    """带用户可读原因的登录失败。"""

    def __init__(self, message, kind="error"):
        super().__init__(message)
        self.message = message
        self.kind = kind          # error | captcha | network


def _hidden_inputs(html):
    """抓取 <input type="hidden" ...> 的 name/id -> value。"""
    out = {}
    for tag in re.findall(r"<input[^>]*>", html, re.I):
        if not re.search(r'type\s*=\s*["\']?hidden', tag, re.I):
            continue
        name = re.search(r'(?:name|id)\s*=\s*["\']([^"\']+)["\']', tag, re.I)
        value = re.search(r'value\s*=\s*["\']([^"\']*)["\']', tag, re.I)
        if name:
            out[name.group(1).strip()] = value.group(1) if value else ""
    return out


def _extract_error(html):
    """CAS 把错误文案放在 #errormsghide 里，优先读它。"""
    m = re.search(r'id\s*=\s*["\']errormsghide["\'][^>]*>([^<]{1,200})<', html, re.I)
    if m:
        txt = m.group(1).strip()
        txt = re.sub(r"\s+", " ", txt)
        if txt:
            return txt
    for pattern, msg in _ERROR_PATTERNS:
        if re.search(pattern, html):
            return msg
    return None


def _has_captcha(html):
    return bool(re.search(r'(?:id|name)\s*=\s*["\'](?:authCode|codeImage|code|checkCode|verifyCode)["\']',
                          html, re.I)
                or "jquery.captcha" in html and 'id="authCode"' in html)


def _detect_error(html):
    for pattern, msg in _ERROR_PATTERNS:
        if re.search(pattern, html):
            return msg
    return None


def fetch_login_ticket(session, pattern="student-login"):
    """第一步：进入教务系统入口，跟随跳转拿到 CAS 登录页。"""
    entry = STUDENT_ENTRY if pattern == "student-login" else TEACHER_ENTRY
    resp = session.get(entry, referer=JW_ORIGIN + "/grd/")
    html = resp.text

    if "sso/login" not in resp.url and "cas" not in resp.url:
        raise CasError(f"未跳转到统一认证页（最终地址 {resp.url}）", "network")
    if _has_captcha(html):
        raise CasError("统一认证要求输入图形验证码，自动登录无法继续", "captcha")

    fields = _hidden_inputs(html)
    if "lt" not in fields:
        raise CasError("登录页结构异常：未找到 lt 票据", "error")
    return resp, fields


def login(session, username, password, pattern="student-login"):
    """执行完整 CAS 登录。返回 (session, 登录页字段)。失败抛 CasError。"""
    resp, fields = fetch_login_ticket(session, pattern)

    lt = fields.get("lt", "")
    form = {
        "un": username,
        "pd": password,
        "rsa": login_rsa_token(username, password, lt),
        "ul": str(len(username)),
        "pl": str(len(password)),
        "lt": lt,
        "execution": fields.get("execution", "e1s1"),
        "_eventId": fields.get("_eventId", "submit"),
    }
    # 某些版本会把 service 放在隐藏域里
    for key in ("service", "service_id"):
        if fields.get(key):
            form[key] = fields[key]

    post = session.post(CAS_LOGIN_URL, form=form, referer=resp.url)
    html = post.text

    # 成功的话会 302 回到教务系统；失败则停在 CAS 页面并回显错误
    still_on_cas = "cas.gzdzxy.cn" in post.url and "/sso/login" in post.url
    if still_on_cas:
        if _has_captcha(html):
            err = CasError("统一认证要求输入图形验证码，自动登录无法继续", "captcha")
        else:
            err = CasError(_extract_error(html) or "登录失败，账号或密码可能有误", "error")
        err.html = html
        err.final_url = post.url
        raise err

    return session, {"lt": lt, "final_url": post.url, "html": post.text}
