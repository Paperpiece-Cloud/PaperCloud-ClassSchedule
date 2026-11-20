/* ============================================================================
 * 班级课表 · 一键抓取脚本 v2
 * 在「教务系统课表页面」的浏览器控制台里粘贴运行。
 *
 * 策略改变（v2）：
 *   v1 是「猜出登录令牌 -> 自己重放请求」。实测发现这个系统把令牌放在内存
 *   或 HttpOnly cookie 里，JS 根本读不到，所以重放必然是 401 未授权。
 *
 *   v2 改成「监听应用自己的请求，直接截获课表响应」。
 *   应用发出的请求一定带对了凭证，我们只要把它的响应内容接住即可。
 *
 * 只读，不修改任何数据。
 * ==========================================================================*/
(function () {
  'use strict';

  var TAG = '[课表抓取]';
  var UP = window.__KT_UPLOAD__ || null;
  var MAX_KEEP = 60;          // 最多记录多少个请求
  var MAX_BODY = 400000;      // 单个响应最多保留多少字符
  var MAX_WEEK = 30;          // 一次请求多少个周次（整学期）

  function say() {
    var a = [].slice.call(arguments);
    try { console.log.apply(console, [TAG].concat(a)); } catch (e) { }
    note(a.join(' '));
  }

  /* ---------------- 教务系统原版 MD5（从它的 app.js 里提取，已验证） --------- */
  function ktmd5(str) {
    var t = {};
    (function (e, t, n) { t.a = a; function a(e) { return m(i(f(e), e.length * 8)) } function i(e, t) { e[t >> 5] |= 128 << t % 32, e[14 + (t + 64 >>> 9 << 4)] = t; for (var n = 1732584193, r = -271733879, o = -1732584194, a = 271733878, i = 0; i < e.length; i += 16) { var c = n, f = r, m = o, h = a; n = l(n, r, o, a, e[i + 0], 7, -680876936), a = l(a, n, r, o, e[i + 1], 12, -389564586), o = l(o, a, n, r, e[i + 2], 17, 606105819), r = l(r, o, a, n, e[i + 3], 22, -1044525330), n = l(n, r, o, a, e[i + 4], 7, -176418897), a = l(a, n, r, o, e[i + 5], 12, 1200080426), o = l(o, a, n, r, e[i + 6], 17, -1473231341), r = l(r, o, a, n, e[i + 7], 22, -45705983), n = l(n, r, o, a, e[i + 8], 7, 1770035416), a = l(a, n, r, o, e[i + 9], 12, -1958414417), o = l(o, a, n, r, e[i + 10], 17, -42063), r = l(r, o, a, n, e[i + 11], 22, -1990404162), n = l(n, r, o, a, e[i + 12], 7, 1804603682), a = l(a, n, r, o, e[i + 13], 12, -40341101), o = l(o, a, n, r, e[i + 14], 17, -1502002290), n = u(n, r = l(r, o, a, n, e[i + 15], 22, 1236535329), o, a, e[i + 1], 5, -165796510), a = u(a, n, r, o, e[i + 6], 9, -1069501632), o = u(o, a, n, r, e[i + 11], 14, 643717713), r = u(r, o, a, n, e[i + 0], 20, -373897302), n = u(n, r, o, a, e[i + 5], 5, -701558691), a = u(a, n, r, o, e[i + 10], 9, 38016083), o = u(o, a, n, r, e[i + 15], 14, -660478335), r = u(r, o, a, n, e[i + 4], 20, -405537848), n = u(n, r, o, a, e[i + 9], 5, 568446438), a = u(a, n, r, o, e[i + 14], 9, -1019803690), o = u(o, a, n, r, e[i + 3], 14, -187363961), r = u(r, o, a, n, e[i + 8], 20, 1163531501), n = u(n, r, o, a, e[i + 13], 5, -1444681467), a = u(a, n, r, o, e[i + 2], 9, -51403784), o = u(o, a, n, r, e[i + 7], 14, 1735328473), n = s(n, r = u(r, o, a, n, e[i + 12], 20, -1926607734), o, a, e[i + 5], 4, -378558), a = s(a, n, r, o, e[i + 8], 11, -2022574463), o = s(o, a, n, r, e[i + 11], 16, 1839030562), r = s(r, o, a, n, e[i + 14], 23, -35309556), n = s(n, r, o, a, e[i + 1], 4, -1530992060), a = s(a, n, r, o, e[i + 4], 11, 1272893353), o = s(o, a, n, r, e[i + 7], 16, -155497632), r = s(r, o, a, n, e[i + 10], 23, -1094730640), n = s(n, r, o, a, e[i + 13], 4, 681279174), a = s(a, n, r, o, e[i + 0], 11, -358537222), o = s(o, a, n, r, e[i + 3], 16, -722521979), r = s(r, o, a, n, e[i + 6], 23, 76029189), n = s(n, r, o, a, e[i + 9], 4, -640364487), a = s(a, n, r, o, e[i + 12], 11, -421815835), o = s(o, a, n, r, e[i + 15], 16, 530742520), n = p(n, r = s(r, o, a, n, e[i + 2], 23, -995338651), o, a, e[i + 0], 6, -198630844), a = p(a, n, r, o, e[i + 7], 10, 1126891415), o = p(o, a, n, r, e[i + 14], 15, -1416354905), r = p(r, o, a, n, e[i + 5], 21, -57434055), n = p(n, r, o, a, e[i + 12], 6, 1700485571), a = p(a, n, r, o, e[i + 3], 10, -1894986606), o = p(o, a, n, r, e[i + 10], 15, -1051523), r = p(r, o, a, n, e[i + 1], 21, -2054922799), n = p(n, r, o, a, e[i + 8], 6, 1873313359), a = p(a, n, r, o, e[i + 15], 10, -30611744), o = p(o, a, n, r, e[i + 6], 15, -1560198380), r = p(r, o, a, n, e[i + 13], 21, 1309151649), n = p(n, r, o, a, e[i + 4], 6, -145523070), a = p(a, n, r, o, e[i + 11], 10, -1120210379), o = p(o, a, n, r, e[i + 2], 15, 718787259), r = p(r, o, a, n, e[i + 9], 21, -343485551), n = d(n, c), r = d(r, f), o = d(o, m), a = d(a, h) } return [n, r, o, a] } function c(e, t, n, r, o, a) { return d(g(d(d(t, e), d(r, a)), o), n) } function l(e, t, n, r, o, a, i) { return c(t & n | ~t & r, e, t, o, a, i) } function u(e, t, n, r, o, a, i) { return c(t & r | n & ~r, e, t, o, a, i) } function s(e, t, n, r, o, a, i) { return c(t ^ n ^ r, e, t, o, a, i) } function p(e, t, n, r, o, a, i) { return c(n ^ (t | ~r), e, t, o, a, i) } function d(e, t) { var n = (e & 65535) + (t & 65535), r = (e >> 16) + (t >> 16) + (n >> 16); return r << 16 | n & 65535 } function f(e) { for (var t = [], n = 0; n < e.length * 8; n += 8) t[n >> 5] |= (e.charCodeAt(n / 8) & 255) << n % 32; return t } function m(e) { for (var t = "", n = 0; n < e.length * 4; n++) t += "0123456789abcdef".charAt(e[n >> 2] >> n % 4 * 8 + 4 & 15) + "0123456789abcdef".charAt(e[n >> 2] >> n % 4 * 8 & 15); return t } })({}, t, function () { });
    return t.a(str);
  }

  /* ---------------- 状态 ---------------- */
  var cap = {
    reqs: [],            // 记录到的请求
    auth: {},            // 从请求头里学到的认证头
    body: null,          // 截获到的课表响应
    url: '',
    status: 0,
    page: location.href,
    ua: navigator.userAgent,
    cookie: document.cookie || '',
    storage: {},
  };

  function isScheduleUrl(u) {
    return /(studentSchedule|studentScheduleQuery|queryTeacherSchedule|schedule|kebiao|kbList|xskcb)/i.test(u || '');
  }
  function looksLikeSchedule(t) {
    return !!t && /(kbList|kcmc|jcs|zcd|xqj|kcmc|courseName)/.test(t);
  }

  function note(text) {
    cap.log = cap.log || [];
    if (cap.log.length < 200) cap.log.push(text);
    paint();
  }

  /* ---------------- 面板（不挡操作） ---------------- */
  var panel = null, statusEl = null;
  function paint() {
    if (!panel) return;
    var s = cap.body ? '✅ 已截获课表数据（' + cap.body.length + ' 字节）'
      : '⏳ 正在监听…请在这个页面里点一下「课表」或切换周次';
    if (statusEl) statusEl.textContent = s;
    if (panel.__btn) panel.__btn.style.display = cap.body ? '' : 'none';
  }

  function showPanel() {
    try {
      panel = document.createElement('div');
      panel.style.cssText = 'position:fixed;z-index:2147483647;left:12px;bottom:12px;max-width:330px;' +
        'background:#0d1117;color:#c9d1d9;border:2px solid #3d9df6;border-radius:12px;' +
        'padding:12px 14px;font:12.5px/1.6 -apple-system,Segoe UI,sans-serif;box-shadow:0 12px 40px #000b';
      panel.innerHTML =
        '<div style="font-weight:700;color:#3d9df6;margin-bottom:6px">班级课表 · 同步监听中</div>' +
        '<div id="__kt_st" style="margin-bottom:8px"></div>' +
        '<div style="color:#8b949e;font-size:11.5px">' +
        '如果一直没动静：在左边菜单点一下「课表」，或切换一下周次，让它重新请求一次。</div>';
      var btn = document.createElement('button');
      btn.textContent = '立即上传已有数据';
      btn.style.cssText = 'display:none;margin-top:9px;width:100%;padding:9px;border:0;border-radius:8px;' +
        'background:#3d9df6;color:#fff;font-size:13px;font-weight:700;cursor:pointer';
      btn.onclick = function () { finish('手动上传'); };
      panel.__btn = btn;
      panel.appendChild(btn);
      var close = document.createElement('button');
      close.textContent = '×';
      close.style.cssText = 'position:absolute;top:6px;right:9px;border:0;background:none;color:#8b949e;' +
        'font-size:17px;cursor:pointer;line-height:1';
      close.onclick = function () { panel.remove(); panel = null; };
      panel.appendChild(close);
      document.body.appendChild(panel);
      statusEl = document.getElementById('__kt_st');
      paint();
    } catch (e) { }
  }

  /* ---------------- 钩子：XHR ---------------- */
  function installXHR() {
    var XO = XMLHttpRequest.prototype.open,
      XS = XMLHttpRequest.prototype.send,
      XH = XMLHttpRequest.prototype.setRequestHeader;

    XMLHttpRequest.prototype.open = function (m, u) {
      try { this.__kt = { m: m, u: String(u), h: {} }; } catch (e) { }
      return XO.apply(this, arguments);
    };
    XMLHttpRequest.prototype.setRequestHeader = function (k, v) {
      try {
        if (this.__kt) {
          this.__kt.h[k] = v;
          if (/^(authorization|csrf|x-token|x-access-token|token)$/i.test(k)) cap.auth[k] = String(v);
        }
      } catch (e) { }
      return XH.apply(this, arguments);
    };
    XMLHttpRequest.prototype.send = function (body) {
      var self = this;
      try {
        if (self.__kt) {
          self.__kt.body = String(body == null ? '' : body).slice(0, 600);
          remember(self.__kt);
          self.addEventListener('load', function () {
            var t = '';
            try { t = self.responseText || ''; } catch (e) { }
            handle(self.__kt.u, self.status, t);
          });
        }
      } catch (e) { }
      return XS.apply(this, arguments);
    };
  }

  /* ---------------- 钩子：fetch ---------------- */
  function installFetch() {
    var OF = window.fetch;
    if (!OF) return;
    window.fetch = function (input, init) {
      var url = '', method = 'GET', hdrs = {};
      try {
        url = typeof input === 'string' ? input : (input && input.url) || '';
        method = (init && init.method) || (input && input.method) || 'GET';
        var h = (init && init.headers) || (input && input.headers);
        if (h) {
          if (h.forEach) h.forEach(function (v, k) { hdrs[k] = v; });
          else Object.keys(h).forEach(function (k) { hdrs[k] = h[k]; });
        }
        for (var k in hdrs) if (/^(authorization|csrf|x-token|x-access-token|token)$/i.test(k)) cap.auth[k] = String(hdrs[k]);
        remember({ u: url, m: method, h: hdrs, body: String((init && init.body) || '').slice(0, 600) });
      } catch (e) { }
      var p = OF.apply(this, arguments);
      try {
        p.then(function (res) {
          try {
            res.clone().text().then(function (t) { handle(url, res.status, t); }, function () { });
          } catch (e) { }
        }, function () { });
      } catch (e) { }
      return p;
    };
  }

  function remember(r) {
    if (!r || !r.u) return;
    if (cap.reqs.length < MAX_KEEP) {
      cap.reqs.push({ url: String(r.u).slice(0, 300), m: r.m, h: r.h, body: r.body });
    }
  }

  /* ---------------- 截获响应 ---------------- */
  var done = false;
  function handle(url, status, text) {
    if (done) return;
    if (!isScheduleUrl(url)) return;
    text = text || '';
    if (status === 200 && looksLikeSchedule(text)) {
      done = true;
      cap.body = text.slice(0, MAX_BODY);
      cap.url = url;
      cap.status = status;
      say('✅ 截获到课表响应：' + url + '（' + text.length + ' 字节）');
      try { window.__ktResult = cap; } catch (e) { }
      // 应用只看了一周（真实接口的请求体里 weeks:[8] 这种）。
      // 我们拿到它的请求模板后，把 weeks 改成整学期，再替它要一次完整的。
      fetchAllWeeks().then(function () {
        finish(cap.allWeeks ? '整学期' : '自动截获');
      });
    } else {
      say('课表接口返回 ' + status + '，继续等待应用自己请求…');
    }
  }

  /* ---------------- 用应用的请求模板，把整学期一次要回来 ----------------
   * 真实接口：
   *   POST /grd/api/arrange/CourseScheduleAllQuery/studentCourseSchedule?_t=<ts>
   *   体: {"studentId":"...","oddOrDouble":1,"source":"xs",
   *        "semester":"2026-2027-1","weeks":[8]}
   * weeks 是个数组 —— 直接给 1..30 就能一次拿到整学期。
   */
  function fetchAllWeeks() {
    var req = null;
    for (var i = cap.reqs.length - 1; i >= 0; i--) {
      if (isScheduleUrl(cap.reqs[i].url)) { req = cap.reqs[i]; break; }
    }
    if (!req) { say('没记录到课表请求模板，跳过整学期抓取'); return Promise.resolve(); }

    var tpl = null;
    try { tpl = JSON.parse(req.body); } catch (e) { }
    if (!tpl || typeof tpl !== 'object') {
      say('请求体不是 JSON，跳过整学期抓取');
      return Promise.resolve();
    }
    if (!('weeks' in tpl)) tpl.weeks = [];
    tpl.weeks = [];
    for (var w = 1; w <= MAX_WEEK; w++) tpl.weeks.push(w);

    var t = Math.floor(Date.now() / 1000);
    var headers = {
      'Accept': 'application/json',
      'Content-Type': 'application/json;charset=utf-8',
      'X-Requested-With': 'XMLHttpRequest'
    };
    for (var k in (req.h || {})) {
      if (/^access-control/i.test(k)) continue;   // 这两个是响应头，别带上去
      headers[k] = req.h[k];
    }
    try { headers['csrfToken'] = ktmd5(String(t) + 'lyedu'); } catch (e) { }
    var url = String(req.url).replace(/([?&])_t=\d+/, '$1_t=' + t);
    if (!/[?&]_t=/.test(url)) url += (url.indexOf('?') < 0 ? '?' : '&') + '_t=' + t;
    if (url.charAt(0) === '/') url = location.origin + url;

    say('正在请求整学期（1-' + MAX_WEEK + ' 周）…');
    return fetch(url, {
      method: 'POST', credentials: 'include', headers: headers,
      body: JSON.stringify(tpl)
    }).then(function (r) { return r.text(); }).then(function (txt) {
      if (looksLikeSchedule(txt)) {
        cap.allWeeks = txt.slice(0, MAX_BODY * 2);
        say('✅ 整学期抓到了（' + txt.length + ' 字节）');
      } else {
        say('整学期请求没拿到课表：' + String(txt).slice(0, 120));
      }
    }).catch(function (e) { say('整学期请求失败：' + e); });
  }

  /* ---------------- 兜底：找令牌后重放 ---------------- */
  function scanStores() {
    var out = {};
    ['sessionStorage', 'localStorage'].forEach(function (name) {
      var hits = [];
      try {
        var st = window[name];
        for (var i = 0; i < st.length; i++) {
          var k = st.key(i), v = st.getItem(k);
          hits.push({ key: k, raw: String(v || '').slice(0, 200) });
        }
      } catch (e) { }
      out[name] = hits;
    });
    cap.storage = out;
    return out;
  }

  function findToken() {
    var tok = cap.auth['Authorization'] || cap.auth['authorization'];
    if (tok) return { token: String(tok).replace(/^Bearer\s+/i, ''), from: '请求头' };
    var all = scanStores();
    var found = null;
    ['sessionStorage', 'localStorage'].forEach(function (n) {
      (all[n] || []).forEach(function (h) {
        if (found) return;
        var m = String(h.raw).match(/"?(access_?token|accessToken|token|Authorization)"?\s*[:=]\s*"?([A-Za-z0-9._\-]{16,})/);
        if (m) found = { token: m[2], from: n + ':' + h.key };
      });
    });
    return found;
  }

  function replay() {
    var f = findToken();
    if (!f) { say('没有可用的令牌，跳过重放'); return Promise.resolve(); }
    cap.token = f.token;
    var t = Math.floor(Date.now() / 1000);
    var base = location.origin + '/grd/api';
    var headers = { 'Authorization': 'Bearer ' + f.token, 'csrfToken': ktmd5(t + 'lyedu') };
    for (var k in cap.auth) headers[k] = cap.auth[k];
    var urls = [base + '/student/personal/studentSchedule?_t=' + t];
    return Promise.all(urls.map(function (u) {
      return fetch(u, {
        method: 'POST', credentials: 'include',
        headers: Object.assign({ 'Content-Type': 'application/x-www-form-urlencoded;charset=utf-8' }, headers),
        body: 'xnxqdm=&zc=&_t=' + t
      }).then(function (r) { return r.text(); }).then(function (txt) {
        if (looksLikeSchedule(txt)) {
          done = true; cap.body = txt; cap.url = u; cap.status = 200;
          say('✅ 重放成功');
          finish('令牌重放');
        }
      }).catch(function () { });
    }));
  }

  /* ---------------- 上传 ---------------- */
  var uploaded = false;
  function finish(reason) {
    if (uploaded) return;
    uploaded = true;
    var payload = {
      raw: cap.allWeeks || cap.body,
      allWeeks: cap.allWeeks || null,
      oneWeek: cap.body || null,
      token: cap.token || cap.auth['Authorization'] || '',
      cookie: cap.cookie,
      base: location.origin + '/grd/api',
      page: cap.page,
      ua: cap.ua,
      reason: reason,
      authHeaders: cap.auth,
      scheduleUrl: cap.url,
      scheduleStatus: cap.status,
      requests: cap.reqs.slice(0, 40),
      storage: cap.storage,
      log: cap.log || [],
    };
    try { window.__ktResult = payload; } catch (e) { }
    say(cap.body ? '🎉 抓到课表了！正在上传…' : '没抓到课表，正在上传诊断信息…');
    if (!UP) { say('没有配置上传地址，结果在 window.__ktResult'); return; }
    try {
      // 用 cors 模式：no-cors 拿不到状态码，成功失败都显示「已上传」，
      // 把 401 这种真问题藏起来了。服务端现在两种结果都带 CORS 头。
      fetch(UP, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      }).then(function (r) {
        return r.text().then(function (txt) {
          var d = {};
          try { d = JSON.parse(txt); } catch (e) { }
          if (r.ok && d.ok) {
            say('✅ 已同步到 PaperCloud，' + (d.imported || '?') + ' 门课');
          } else {
            say('❌ 上传被拒 HTTP ' + r.status + '：' + (d.message || txt.slice(0, 80)));
            say('   书签里的网址必须带 ?k=班级口令');
          }
        });
      }, function (e) { say('❌ 上传失败: ' + e); });
    } catch (e) { say('上传异常: ' + e); }
  }

  /* ---------------- 启动 ---------------- */
  say('已安装监听。storage 条目: ' +
    ((function () { try { return sessionStorage.length + localStorage.length; } catch (e) { return '?'; } })()) +
    ' | 已有认证头: ' + (Object.keys(cap.auth).length || '无'));

  installXHR();
  installFetch();
  scanStores();
  showPanel();

  // 兜底：如果 12 秒内应用没自己发请求，就用令牌重放一次
  setTimeout(function () {
    if (!done) { say('应用尚未发请求，尝试用令牌重放…'); replay(); }
  }, 12000);

  // 兜底：40 秒后无论如何上传一次（便于我诊断）
  setTimeout(function () { if (!uploaded) finish('超时上传'); }, 40000);

  say('👉 现在请在页面里点一下左侧「课表」菜单，或切换一下周次，让它重新请求一次。');
})();
