"""教务系统认证客户端。

支持三种会话来源：
  1. 浏览器导出的 cURL（最可靠 —— 直接复用你已登录的会话）
  2. CAS 单点登录（gld 通路已验证可用）
  3. 本地缓存（data/session.json）

API 约定（从 app.js 逆向得出）：
  * 请求头 Authorization: "Bearer " + accessToken
  * 请求头 csrfToken:     md5( _t + "lyedu" )
  * 查询参数 _t:          时间戳（秒）
  * POST 体:              application/x-www-form-urlencoded
"""

import hashlib
import json
import os
import re
import time
import urllib.parse

from .http import Session

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SESSION_FILE = os.path.join(ROOT, "data", "session.json")

JW_ORIGIN = "https://jw.gzdzxy.cn"
TOKEN_KEY = "lyedu"
AUTH_PREFIX = "Bearer "
DEFAULT_BASE = JW_ORIGIN + "/grd/api"

# 未登录 / 未授权
CODE_NOT_LOGIN = 53000010
CODE_NO_PERM = 53000012
CODE_OK = 200


class AuthError(Exception):
    pass


class ApiError(Exception):
    pass


# ---------------------------------------------------------------- 会话持久化

class SessionState:
    """保存 cookie + accessToken，可落盘复用。"""

    def __init__(self, cookies=None, access_token="", base=DEFAULT_BASE, note=""):
        self.cookies = dict(cookies or {})      # name -> value
        self.access_token = access_token or ""
        self.base = base or DEFAULT_BASE
        self.note = note
        self.saved_at = time.time()

    def to_dict(self):
        return {"cookies": self.cookies, "access_token": self.access_token,
                "base": self.base, "note": self.note, "saved_at": self.saved_at}

    @classmethod
    def from_dict(cls, d):
        s = cls(d.get("cookies"), d.get("access_token"), d.get("base"), d.get("note", ""))
        s.saved_at = d.get("saved_at", time.time())
        return s

    def save(self):
        os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)
        tmp = SESSION_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=1)
        os.replace(tmp, SESSION_FILE)

    @classmethod
    def load(cls):
        if not os.path.exists(SESSION_FILE):
            return None
        try:
            with open(SESSION_FILE, encoding="utf-8") as f:
                return cls.from_dict(json.load(f))
        except Exception:
            return None

    @property
    def age(self):
        return time.time() - self.saved_at


# ---------------------------------------------------------------- cURL 解析

def parse_curl(text):
    """解析 Chrome 'Copy as cURL (bash)' 文本，返回可重放的请求描述。"""
    text = text.strip()
    # 续行
    text = re.sub(r"\\\r?\n\s*", " ", text)
    text = text.replace("^", "")

    url = None
    m = re.search(r"curl\s+(?:'([^']*)'|\"([^\"]*)\"|(\S+))", text)
    if m:
        url = m.group(1) or m.group(2) or m.group(3)

    headers = {}
    for hm in re.finditer(r"(?:-H|--header)\s+(?:'([^']*)'|\"([^\"]*)\")", text):
        raw = hm.group(1) or hm.group(2) or ""
        if ":" not in raw:
            continue
        k, v = raw.split(":", 1)
        headers[k.strip().lower()] = v.strip()

    body = None
    for bm in re.finditer(
            r"(?:--data-raw|--data-binary|--data|-d)\s+(?:'([^']*)'|\"([^\"]*)\")", text):
        body = bm.group(1) or bm.group(2)
        break

    method = "POST" if body is not None else "GET"
    mm = re.search(r"(?:-X|--request)\s+(\w+)", text)
    if mm:
        method = mm.group(1).upper()

    cookies = {}
    ck = headers.get("cookie", "")
    for part in ck.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            cookies[k.strip()] = v.strip()

    token = ""
    auth = headers.get("authorization", "")
    if auth.lower().startswith("bearer"):
        token = auth[6:].strip()

    return {
        "url": url,
        "method": method,
        "headers": headers,
        "cookies": cookies,
        "access_token": token,
        "body": body,
    }


def base_from_url(url):
    """从任意 API URL 推断出 API 基址。"""
    if not url:
        return DEFAULT_BASE
    p = urllib.parse.urlparse(url)
    path = p.path
    for marker in ("/api/", "/api"):
        i = path.find(marker)
        if i >= 0:
            return f"{p.scheme}://{p.netloc}{path[:i]}/api"
    return f"{p.scheme}://{p.netloc}/grd/api"


# ---------------------------------------------------------------- 客户端

class JwClient:
    def __init__(self, state=None):
        self.state = state or SessionState()
        self.s = Session()
        self._sync_cookies()

    def _sync_cookies(self):
        """把 cookie 注入会话。域名和 secure 由 API 基址推导，
        这样走域名、内网 IP、直连端口都能正确携带。"""
        u = urllib.parse.urlparse(self.state.base)
        host = u.hostname or "jw.gzdzxy.cn"
        secure = (u.scheme or "https") == "https"
        for k, v in self.state.cookies.items():
            self.s.load_cookies({k: v}, domain=host, secure=secure)

    # ------------------------------------------------ 头部

    def _headers(self, extra=None):
        h = {
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/plain, */*",
            "Origin": JW_ORIGIN,
            "Referer": JW_ORIGIN + "/grd/",
        }
        if self.state.access_token:
            h["Authorization"] = AUTH_PREFIX + self.state.access_token
        if extra:
            h.update(extra)
        return h

    # ------------------------------------------------ 请求

    def request(self, path, data=None, method="POST", params=None, timeout=25):
        ts = int(time.time())
        q = {"_t": ts}
        if params:
            q.update(params)
        h = self._headers({
            "csrfToken": hashlib.md5(f"{ts}{TOKEN_KEY}".encode()).hexdigest(),
        })
        url = self.state.base.rstrip("/") + "/" + path.lstrip("/")
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(q)

        if method == "GET":
            r = self.s.get(url, headers=h)
        else:
            r = self.s.post(url, form=(data or {}), headers={
                k: v for k, v in h.items() if k != "Content-Type"})
        return r

    def call(self, path, data=None, method="POST", params=None, retries=1):
        last = None
        for attempt in range(retries + 1):
            try:
                r = self.request(path, data=data, method=method, params=params)
            except ConnectionError as e:
                last = e
                time.sleep(1.5 * (attempt + 1))
                continue
            try:
                payload = r.json()
            except Exception:
                raise ApiError(f"{path} 返回非 JSON (HTTP {r.status}): {r.text[:200]!r}")
            code = payload.get("code")
            if code == CODE_OK:
                return payload.get("data")
            if code in (CODE_NOT_LOGIN, CODE_NO_PERM):
                raise AuthError(f"{path}: {payload.get('message')} (code={code})")
            if attempt < retries:
                last = ApiError(f"{path}: {payload.get('message')}")
                time.sleep(1.5)
                continue
            raise ApiError(f"{path} 失败 code={code} message={payload.get('message')}")
        raise ApiError(f"{path} 重试失败: {last}")

    # ------------------------------------------------ 业务

    def user_info(self):
        return self.call("system/user/getUserInfo", data={})

    def student_schedule(self, payload=None):
        return self.call("student/personal/studentSchedule", data=payload or {})

    def check(self):
        """验证会话是否有效。返回 (ok, 用户信息或错误)。"""
        try:
            info = self.user_info()
            return True, info
        except AuthError as e:
            return False, str(e)
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"

    # ------------------------------------------------ 来源 1：cURL

    @classmethod
    def from_curl(cls, curl_text):
        parsed = parse_curl(curl_text)
        base = base_from_url(parsed["url"])
        state = SessionState(cookies=parsed["cookies"], access_token=parsed["access_token"],
                             base=base, note="浏览器导出")
        return cls(state), parsed

    # ------------------------------------------------ 来源 2：CAS

    @classmethod
    def from_cas(cls, username, password, pattern="manager-login", base=None):
        from . import cas as cas_mod
        state = SessionState(base=base or DEFAULT_BASE, note="CAS 登录")
        client = cls(state)
        cas_mod.login(client.s, username, password, pattern)
        client.save()
        return client

    def _base_host(self):
        return urllib.parse.urlparse(self.state.base).hostname or "jw.gzdzxy.cn"

    def save(self):
        host = self._base_host()
        self.state.cookies = {c.name: c.value for c in self.s.jar
                              if host in (c.domain or "")}
        self.state.save()
