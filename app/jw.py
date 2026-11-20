"""教务系统（强智新版 /grd）API 客户端。"""

import json
import time

from . import cas
from .http import Session

API_BASE = "https://jw.gzdzxy.cn/grd/api"
JW_ORIGIN = "https://jw.gzdzxy.cn"
GRD = JW_ORIGIN + "/grd/"

# 已知返回码
CODE_OK = 200
CODE_NOT_LOGIN = 53000010
CODE_SERVER_ERROR = 51000000


class JwError(Exception):
    pass


class NotLoggedIn(JwError):
    pass


class JwClient:
    def __init__(self, session=None):
        self.s = session or Session()
        self.username = None
        self.user = {}
        self.last_login_at = None

    # ---------------------------------------------------------------- 登录

    def login(self, username, password, pattern="student-login"):
        cas.login(self.s, username, password, pattern)
        self.username = username
        self.last_login_at = time.time()
        info = self.user_info()
        self.user = info
        return info

    def logged_in(self, probe=True):
        if not probe:
            return bool(self.username)
        try:
            self.user_info()
            return True
        except NotLoggedIn:
            return False
        except JwError:
            return False

    # ---------------------------------------------------------------- 请求

    def call(self, path, payload=None, method="POST", retries=2):
        url = API_BASE + "/" + path.lstrip("/")
        last = None
        for attempt in range(retries + 1):
            try:
                if method == "GET":
                    r = self.s.get(url, headers={"X-Requested-With": "XMLHttpRequest"})
                elif payload is None:
                    r = self.s.post(url, data=b"", headers={
                        "Content-Type": "application/json;charset=UTF-8",
                        "X-Requested-With": "XMLHttpRequest"})
                else:
                    r = self.s.post(url, json_body=payload)
            except ConnectionError as e:
                last = e
                time.sleep(1.5 * (attempt + 1))
                continue

            if r.status in (401, 403):
                raise NotLoggedIn(f"{path} 未登录 (HTTP {r.status})")
            try:
                data = r.json()
            except Exception:
                raise JwError(f"{path} 返回非 JSON (HTTP {r.status}): {r.text[:200]!r}")

            code = data.get("code")
            if code == CODE_OK:
                return data.get("data")
            if code == CODE_NOT_LOGIN:
                raise NotLoggedIn(f"{path}: {data.get('message')}")
            if code == CODE_SERVER_ERROR and attempt < retries:
                last = JwError(f"{path}: {data.get('message')}")
                time.sleep(1.5 * (attempt + 1))
                continue
            raise JwError(f"{path} 失败 code={code} message={data.get('message')}")
        raise JwError(f"{path} 重试{retries}次仍失败: {last}")

    # ---------------------------------------------------------------- 业务

    def user_info(self):
        return self.call("system/user/getUserInfo", payload={}, method="POST")

    def school_logo(self):
        r = self.s.get(API_BASE + "/querySchoolLogo")
        return r.body

    def current_term(self):
        """当前学年学期 + 当前周。"""
        try:
            return self.call("teacherSchedule/queryCurrentSemesterAndWeek", payload={})
        except JwError:
            return None

    def student_schedule(self, payload=None):
        """学生个人课表。payload 常见字段：semesterId / week / xnxqh 等。"""
        return self.call("student/personal/studentSchedule", payload=payload or {})

    def try_endpoint(self, path, payload=None, method="POST"):
        """探测用：不抛异常，返回 (ok, data_or_error)。"""
        try:
            return True, self.call(path, payload=payload, method=method, retries=0)
        except JwError as e:
            return False, f"{type(e).__name__}: {e}"
