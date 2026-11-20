"""极简 HTTP 会话（纯标准库）：cookie 持久化 + 重定向链记录 + 表单提交。"""

import gzip
import io
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import http.cookiejar

DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


class Response:
    __slots__ = ("status", "headers", "body", "url", "chain")

    def __init__(self, status, headers, body, url, chain):
        self.status = status
        self.headers = headers
        self.body = body
        self.url = url
        self.chain = chain

    @property
    def text(self):
        enc = "utf-8"
        ct = self.headers.get("Content-Type", "") or ""
        if "charset=" in ct.lower():
            enc = ct.lower().split("charset=")[-1].split(";")[0].strip()
        try:
            return self.body.decode(enc, "replace")
        except LookupError:
            return self.body.decode("utf-8", "replace")

    def json(self):
        txt = self.text.strip()
        # 有些接口会带 BOM 或前置空白
        if txt.startswith("\ufeff"):
            txt = txt[1:]
        return json.loads(txt)

    def __repr__(self):
        return f"<Response {self.status} {self.url} {len(self.body)}B>"


class _Recorder(urllib.request.HTTPRedirectHandler):
    """记录重定向链，并允许跨域跳转。"""

    def __init__(self):
        self.chain = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.chain.append((code, req.full_url, newurl))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Session:
    def __init__(self, ua=DEFAULT_UA, timeout=25, verify_ssl=True, proxy=None):
        self.ua = ua
        self.timeout = timeout
        self.jar = http.cookiejar.CookieJar()
        ctx = ssl.create_default_context()
        if not verify_ssl:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        handlers = [
            urllib.request.HTTPCookieProcessor(self.jar),
            urllib.request.HTTPSHandler(context=ctx),
        ]
        self._rec = _Recorder()
        handlers.append(self._rec)
        if proxy:
            handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        self._opener = urllib.request.build_opener(*handlers)

    # ---------------------------------------------------------------- 核心

    def request(self, url, method="GET", data=None, headers=None,
                form=None, json_body=None, referer=None):
        hdrs = {
            "User-Agent": self.ua,
            "Accept": "*/*",
            "Accept-Encoding": "identity",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Connection": "keep-alive",
        }
        if referer:
            hdrs["Referer"] = referer
        body = data
        if form is not None:
            body = urllib.parse.urlencode(form, doseq=True).encode("utf-8")
            hdrs["Content-Type"] = "application/x-www-form-urlencoded"
        if json_body is not None:
            body = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            hdrs["Content-Type"] = "application/json;charset=UTF-8"
            hdrs["X-Requested-With"] = "XMLHttpRequest"
        if headers:
            hdrs.update(headers)

        req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
        self._rec.chain = []
        opener = self._opener

        try:
            with opener.open(req, timeout=self.timeout) as resp:
                raw, status, hdrs_out, final = resp.read(), resp.status, dict(resp.headers), resp.geturl()
        except urllib.error.HTTPError as e:
            raw, status, hdrs_out, final = e.read(), e.code, dict(e.headers), url
        except Exception as e:
            raise ConnectionError(f"{method} {url} -> {type(e).__name__}: {e}") from e

        return Response(status, hdrs_out, raw, final, list(self._rec.chain))

    def get(self, url, **kw):
        return self.request(url, "GET", **kw)

    def post(self, url, **kw):
        return self.request(url, "POST", **kw)

    # ---------------------------------------------------------------- cookie

    def cookie_header(self, domain=None):
        parts = []
        for c in self.jar:
            if domain and domain not in (c.domain or ""):
                continue
            parts.append(f"{c.name}={c.value}")
        return "; ".join(parts)

    def cookies(self):
        return {c.name: c.value for c in self.jar}

    def load_cookies(self, mapping, domain, path="/", secure=True):
        for k, v in mapping.items():
            c = http.cookiejar.Cookie(
                version=0, name=k, value=v, port=None, port_specified=False,
                domain=domain, domain_specified=True, domain_initial_dot=False,
                path=path, path_specified=True, secure=secure, expires=None,
                discard=False, comment=None, comment_url=None, rest={}, rfc2109=False)
            self.jar.set_cookie(c)
