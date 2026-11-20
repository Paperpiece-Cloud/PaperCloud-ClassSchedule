/* ============================================================================
   管理后台 · 前端
   ==========================================================================*/
(function () {
  'use strict';

  var K = new URLSearchParams(location.search).get('k') || '';

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }
  function api(path, opts) {
    var u = path + (path.indexOf('?') >= 0 ? '&' : '?') + 'k=' + encodeURIComponent(K);
    return fetch(u, opts).then(function (r) { return r.json(); });
  }
  function post(path, body) {
    return api(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {})
    });
  }
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function ts(t) {
    if (!t) return '—';
    var d = new Date(t * 1000);
    return pad(d.getMonth() + 1) + '/' + pad(d.getDate()) + ' ' +
      pad(d.getHours()) + ':' + pad(d.getMinutes());
  }
  function tsFull(t) {
    if (!t) return '—';
    var d = new Date(t * 1000);
    return d.getFullYear() + '/' + pad(d.getMonth() + 1) + '/' + pad(d.getDate()) + ' ' +
      pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
  }
  function dur(sec) {
    if (!sec && sec !== 0) return '—';
    var d = Math.floor(sec / 86400), h = Math.floor((sec % 86400) / 3600),
      m = Math.floor((sec % 3600) / 60);
    if (d) return d + ' 天 ' + h + ' 小时';
    if (h) return h + ' 小时 ' + m + ' 分';
    return m + ' 分 ' + Math.floor(sec % 60) + ' 秒';
  }
  function toast(msg, bad) {
    var el = $('opMsg');
    el.textContent = msg;
    el.style.color = bad ? 'var(--danger)' : 'var(--ok)';
    setTimeout(function () { if (el.textContent === msg) el.textContent = ''; }, 4000);
  }

  /* ------------------------------------------------------------ 主题 */
  var themeMode = 'auto';
  try { themeMode = localStorage.getItem('kt-theme') || 'auto'; } catch (e) { }
  function applyTheme() {
    var dark = themeMode === 'dark' || (themeMode === 'auto' &&
      window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
    var b = $('themeBtn');
    if (b) { b.textContent = dark ? '☾' : '☀'; }
  }
  $('themeBtn').onclick = function () {
    if (themeMode === 'auto') {
      themeMode = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    } else if (themeMode === 'dark') { themeMode = 'light'; } else { themeMode = 'auto'; }
    try { localStorage.setItem('kt-theme', themeMode); } catch (e) { }
    applyTheme();
  };
  applyTheme();

  function withK(el, base) {
    if (el) el.href = base + (K ? (base.indexOf('?') >= 0 ? '&' : '?') + 'k=' + encodeURIComponent(K) : '');
  }
  withK($('backLink'), '/');
  withK($('lnkEdit'), '/edit');
  withK($('lnkGrab'), '/grab');

  /* ------------------------------------------------------------ 概览 */
  function renderCards(o) {
    var s = o.schedule, f = o.fetch, t = o.traffic, sec = o.security;
    var rt = o.ratings || {};
    var cards = [
      { k: '累计运行', v: dur(o.server.uptime), c: 'acc', i: 0 },
      {
        k: '副班评价',
        v: rt.total ? (rt.avg || 0).toFixed(1) : '—',
        u: rt.total ? ' 分 / ' + rt.total + ' 人' : ' 暂无',
        c: rt.total ? 'ok' : '', i: 9
      },
      { k: '课表版本', v: s.revision, u: ' / ' + s.count + ' 门课', c: '', i: 1 },
      { k: '今日请求', v: t.todayRequests, u: ' 次', c: '', i: 2 },
      { k: '今日访客', v: t.todayVisitors, u: ' 人', c: 'ok', i: 3 },
      { k: '独立 IP（24h）', v: t.uniqueIPs, u: ' 个', c: '', i: 4 },
      { k: '识别机型', v: t.uniqueDevices, u: ' 种', c: '', i: 5 },
      {
        k: '抓取状态',
        v: !f.enabled ? '未启用' : (f.hasSession ? '正常' : (f.noSession ? '无会话' : '异常')),
        c: !f.enabled ? 'warn' : (f.hasSession ? 'ok' : 'warn'), i: 6
      },
      {
        k: '安全',
        v: sec.banned ? sec.banned + ' 封禁' : '正常',
        u: sec.denied ? ' / ' + sec.denied + ' 黑名单' : '',
        c: sec.banned ? 'bad' : 'ok', i: 7
      }
    ];

    // 数据覆盖了哪些周 —— 没覆盖到当前周的话同学打开是空的，必须显眼
    var cw = s.coveredCount || 0;
    cards.push({
      k: '数据覆盖周次',
      v: cw,
      u: cw ? ' 周（第 ' + (s.coveredWeeks || []).join('、') + ' 周）' : ' 周（没有数据！）',
      c: cw === 0 ? 'bad' : (s.currentWeekHasData ? 'ok' : 'warn'),
      i: 8
    });

    $('cards').innerHTML = cards.map(function (c) {
      return '<div class="stat ' + c.c + '" style="--i:' + c.i + '">' +
        '<div class="k">' + esc(c.k) + '</div>' +
        '<div class="v">' + esc(c.v) + (c.u ? '<span class="u">' + esc(c.u) + '</span>' : '') +
        '</div></div>';
    }).join('');

    // 当前周没数据时给一条明显的提示
    if (cw && !s.currentWeekHasData) {
      var box = $('coverageWarn');
      if (!box) {
        box = document.createElement('div');
        box.id = 'coverageWarn';
        box.className = 'panel';
        box.style.cssText = 'border-color:color-mix(in srgb, var(--warn) 50%, var(--line))';
        var cardsEl = $('cards');
        cardsEl.parentNode.insertBefore(box, cardsEl.nextSibling);
      }
      box.innerHTML =
        '<h2>⚠️ 当前周（第 ' + s.currentWeek + ' 周）没有课表数据</h2>' +
        '<div style="font-size:13.5px;color:var(--text-dim);line-height:1.8">' +
        '服务器抓到的是 <b>第 ' + (s.coveredWeeks || []).join('、') + ' 周</b> 的课表，' +
        '一共 ' + cw + ' 周，还有 <b>' + (s.missingCount || 0) + ' 周</b> 是空的。<br>' +
        '同学现在打开网站会看到「这一周还没有课表数据」。<br><br>' +
        '<a class="btn-ghost primary" id="lnkGrab2" href="/grab' +
        (K ? '?k=' + encodeURIComponent(K) : '') + '">🔁 去重新抓取整学期课表</a>' +
        '</div>';
    } else {
      var old = $('coverageWarn');
      if (old) old.remove();
    }

    var extra = '数据来源：' + esc(s.source || '—') +
      ' · 课表更新于 ' + ts(s.updatedAt) +
      ' · 抓取间隔 ' + esc(f.pollSeconds) + ' 秒' +
      ' · 覆盖 ' + cw + ' 周' +
      (f.lastError ? '<br><span class="err" style="color:var(--danger)">最近错误：' +
        esc(f.lastError) + '</span>' : '') +
      (s.lastError ? '<br><span style="color:var(--danger)">存储错误：' +
        esc(s.lastError) + '</span>' : '');
    $('foot').innerHTML = extra + '<br>服务启动于 ' + esc(o.server.startedAt) +
      ' · 监听 ' + esc(o.server.bind);
  }

  /* ------------------------------------------------------------ 趋势图 */
  function renderHours(hourly) {
    var max = Math.max.apply(null, hourly.concat([1]));
    $('hours').innerHTML = hourly.map(function (n) {
      var h = Math.max(2, Math.round(n / max * 62));
      return '<i style="height:' + h + 'px" title="' + n + ' 次"></i>';
    }).join('');
    var labels = '';
    for (var i = 0; i < 24; i += 3) {
      labels += '<span>' + i + '</span>';
    }
    $('hourLabels').innerHTML = labels;
  }

  /* ------------------------------------------------------------ 分布条 */
  function renderBars(el, rows, total, colorize) {
    if (!rows || !rows.length) {
      el.innerHTML = '<div class="empty" style="padding:16px 0">暂无数据</div>';
      return;
    }
    var max = rows[0][1] || 1;
    el.innerHTML = rows.map(function (r) {
      var pct = Math.round(r[1] / max * 100);
      return '<div style="margin-bottom:11px">' +
        '<div style="display:flex;justify-content:space-between;font-size:13px;gap:10px">' +
        '<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' +
        esc(r[0]) + '</span>' +
        '<span class="mono" style="color:var(--text-dim);flex:none">' + r[1] + '</span></div>' +
        '<div class="bar"><i style="width:' + pct + '%' +
        (colorize ? ';background:' + colorize(r[0]) : '') + '"></i></div></div>';
    }).join('');
  }

  /* ------------------------------------------------------------ 访客表 */
  /* ------------------------------------------------------------ 在线访客 */
  function hm(sec) {
    if (!sec) return '—';
    var d = new Date(sec * 1000);
    var now = new Date();
    var pad = function (n) { return n < 10 ? '0' + n : '' + n; };
    var t = pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
    if (d.toDateString() !== now.toDateString()) {
      return (d.getMonth() + 1) + '-' + pad(d.getDate()) + ' ' +
             pad(d.getHours()) + ':' + pad(d.getMinutes());
    }
    return t;
  }

  function dur(sec) {
    sec = Math.max(0, Math.floor(sec || 0));
    var m = Math.floor(sec / 60), h = Math.floor(m / 60);
    if (h > 0) return h + ' 小时 ' + (m % 60) + ' 分';
    if (m > 0) return m + ' 分 ' + (sec % 60) + ' 秒';
    return sec + ' 秒';
  }

  function ago(sec) {
    sec = Math.max(0, Math.floor(sec || 0));
    if (sec < 10) return '刚刚';
    if (sec < 60) return sec + ' 秒前';
    if (sec < 3600) return Math.floor(sec / 60) + ' 分钟前';
    return Math.floor(sec / 3600) + ' 小时前';
  }

  function renderOnlineError(msg) {
    var tb = document.querySelector('#onlineTbl tbody');
    if (!tb) return;
    tb.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--danger);' +
      'padding:22px">' + esc(msg || '读取失败') + '</td></tr>';
    var tag = document.getElementById('onlineCount');
    if (tag) tag.textContent = '读取失败';
  }

  var onlineView = 'online';      // online | offline
  var onlineCache = { online: [], offline: [] };

  function pickOnlineList() {
    return onlineCache[onlineView] || [];
  }

  function paintOnlineTabs() {
    var a = document.getElementById('onlineTab');
    var b = document.getElementById('offlineTab');
    var an = document.getElementById('onlineNum');
    var bn = document.getElementById('offlineNum');
    if (an) an.textContent = (onlineCache.online || []).length;
    if (bn) bn.textContent = (onlineCache.offline || []).length;
    var onStyle = 'background:var(--accent);color:#fff;border-color:transparent';
    var offStyle = 'background:transparent;color:var(--text-dim);';
    if (a) a.style.cssText = a.style.cssText.split(';').slice(0, 3).join(';') +
      ';' + (onlineView === 'online' ? onStyle : offStyle);
    if (b) b.style.cssText = b.style.cssText.split(';').slice(0, 3).join(';') +
      ';' + (onlineView === 'offline' ? onStyle : offStyle);
  }

  function renderOnline(list) {
    var tb = document.querySelector('#onlineTbl tbody');
    if (!tb) return;
    var tag = document.getElementById('onlineCount');
    var isOff = (onlineView === 'offline');
    if (tag) tag.textContent = (list ? list.length : 0) + (isOff ? ' 人已离线' : ' 人在线');

    if (!list || !list.length) {
      tb.innerHTML = '<tr><td colspan="8" style="text-align:center;' +
        'color:var(--text-faint);padding:22px">' +
        (isOff ? '今天还没有已离线的访客' : '当前没有在线访客') + '</td></tr>';
      return;
    }
    tb.innerHTML = list.map(function (v) {
      var tags = '';
      if (v.isBot) tags += ' <span class="tag bot">机器人</span>';
      else if (v.mobile) tags += ' <span class="tag mob">手机</span>';
      var live = (onlineView === 'offline')
        ? '<span style="color:var(--text-faint);font-weight:700">○ 已离线</span>'
        : '<span style="color:var(--ok,#12a05a);font-weight:800">● 在线</span>';
      return '<tr>' +
        '<td class="mono">' + esc(v.ip) + tags + '</td>' +
        '<td>' + esc(v.device) + '</td>' +
        '<td>' + esc(v.os) + '</td>' +
        '<td>' + esc(v.browser) + '</td>' +
        '<td class="mono">' + hm(v.first) + '</td>' +
        '<td class="mono">' + dur(v.seconds) + '</td>' +
        '<td class="mono">' + live + ' <span style="color:var(--text-faint)">' +
          ago(v.idle) + '</span></td>' +
        '<td class="mono" style="color:var(--text-faint);max-width:160px;' +
          'overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' +
          esc(v.page || '—') + '</td>' +
        '</tr>';
    }).join('');
  }

  function renderVisitors(list) {
    var tb = document.querySelector('#visitors tbody');
    if (!list || !list.length) {
      tb.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--text-faint);padding:22px">' +
        '还没有访问记录</td></tr>';
      return;
    }
    tb.innerHTML = list.map(function (v) {
      var tags = '';
      if (v.isBot) tags += ' <span class="tag bot">机器人</span>';
      else if (v.mobile) tags += ' <span class="tag mob">手机</span>';
      if (v.errors) tags += ' <span class="tag bad">' + v.errors + ' 次错误</span>';
      return '<tr>' +
        '<td class="mono">' + esc(v.ip) + tags + '</td>' +
        '<td>' + esc(v.device) + '</td>' +
        '<td>' + esc(v.os) + '</td>' +
        '<td>' + esc(v.browser) + '</td>' +
        '<td class="mono">' + v.count + '</td>' +
        '<td class="mono" style="color:var(--text-faint)">' + ts(v.first) + '</td>' +
        '<td class="mono" style="color:var(--text-faint)">' + ts(v.last) + '</td>' +
        '<td><div class="rowbtns">' +
        '<button class="minibtn danger" data-act="ban" data-ip="' + esc(v.ip) + '">封禁</button>' +
        '<button class="minibtn danger" data-act="deny" data-ip="' + esc(v.ip) + '">拉黑</button>' +
        '<button class="minibtn" data-act="allow" data-ip="' + esc(v.ip) + '">白名单</button>' +
        '<button class="minibtn" data-act="forget" data-ip="' + esc(v.ip) + '">清除</button>' +
        '</div></td></tr>';
    }).join('');
  }

  /* ------------------------------------------------------------ 日志 */
  function renderLog(records) {
    $('logList').innerHTML = records.map(function (r) {
      var s = String(r.s || '');
      var cls = s.charAt(0) === '2' ? 's2xx' : s.charAt(0) === '3' ? 's3xx'
        : s.charAt(0) === '4' ? 's4xx' : 's5xx';
      return '<div class="logline">' +
        '<span class="lt">' + tsFull(r.t) + '</span>' +
        '<span class="lip" title="' + esc(r.ip) + '">' + esc(r.ip) + '</span>' +
        '<span class="ls ' + cls + '">' + esc(s) + '</span>' +
        '<span class="lp" title="' + esc(r.p) + '">' + esc((r.m || '') + ' ' + (r.p || '')) + '</span>' +
        '<span class="ld" title="' + esc(r.ua) + '">' + esc(r.dev || '') + '</span>' +
        '</div>';
    }).join('') || '<div class="empty" style="padding:18px 0">暂无记录</div>';
  }

  /* ------------------------------------------------------------ 安全 */
  function renderSecurity(sec) {
    $('banList').innerHTML = sec.bans.length
      ? sec.bans.map(function (b) {
        return '<div style="display:flex;justify-content:space-between;gap:8px;padding:5px 0;' +
          'border-bottom:1px solid var(--line-soft)"><span class="mono">' + esc(b.ip) +
          '</span><span style="color:var(--danger);font-size:12px">剩 ' +
          Math.ceil(b.remain / 60) + ' 分</span>' +
          '<button class="minibtn" data-act="unban" data-ip="' + esc(b.ip) + '">解封</button></div>';
      }).join('')
      : '<span style="color:var(--text-faint)">没有封禁</span>';

    $('failList').innerHTML = sec.fails.length
      ? sec.fails.map(function (f) {
        return '<div style="display:flex;justify-content:space-between;gap:8px;padding:5px 0;' +
          'border-bottom:1px solid var(--line-soft)"><span class="mono">' + esc(f.ip) +
          '</span><span style="color:var(--warn)">' + f.count + ' 次 · ' + ts(f.last) + '</span></div>';
      }).join('')
      : '<span style="color:var(--text-faint)">没有异常尝试</span>';

    var iphtml = '';
    if (sec.allow.length) iphtml += '<div style="margin-bottom:6px">白名单：' +
      sec.allow.map(function (i) {
        return '<span class="tag okk mono" style="margin:2px">' + esc(i) + '</span>';
      }).join('') + '</div>';
    if (sec.deny.length) iphtml += '<div>黑名单：' +
      sec.deny.map(function (i) {
        return '<span class="tag bad mono" style="margin:2px">' + esc(i) + '</span>';
      }).join('') + '</div>';
    $('ipList').innerHTML = iphtml || '<span style="color:var(--text-faint)">空</span>';

    var l = sec.limits;
    $('limList').innerHTML =
      '<div style="color:var(--text-dim);line-height:1.9">' +
      '限流：' + l.perMinute + ' 次/分钟<br>' +
      '硬上限：' + l.hardLimit + ' 次/分钟<br>' +
      '口令错误 ' + l.maxFails + ' 次 → 封禁 ' + l.banMinutes + ' 分钟<br>' +
      '访问口令：' + (sec.accessCodeSet
        ? '<span style="color:var(--ok)">已设置</span>'
        : '<span style="color:var(--danger)">未设置 ⚠️</span>') +
      '</div>';
  }

  /* ------------------------------------------------------------ 操作 */
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-act]');
    if (!b) return;
    var act = b.dataset.act, ip = b.dataset.ip;
    var labels = { ban: '封禁', deny: '加入黑名单', allow: '加入白名单', unban: '解封', forget: '清除记录' };
    if (act === 'deny' || act === 'ban') {
      if (!confirm('确定要' + labels[act] + ' ' + ip + ' 吗？')) return;
    }
    post('/api/admin/' + act, { ip: ip, minutes: 60 }).then(function (r) {
      toast(r.message || (r.ok ? '完成' : '失败'), !r.ok);
      refreshAll();
    });
  });

  $('btnRefresh').onclick = function () {
    var b = this;
    b.disabled = true; b.textContent = '抓取中…';
    post('/api/refresh').then(function (r) {
      b.disabled = false; b.textContent = '↻ 立即抓取一次';
      toast(r.message || (r.ok ? '抓取完成' : '抓取失败'), !r.ok);
      refreshAll();
    }).catch(function (e) {
      b.disabled = false; b.textContent = '↻ 立即抓取一次';
      toast('请求失败：' + e, true);
    });
  };

  $('btnClearTraffic').onclick = function () {
    if (!confirm('确定清空所有流量记录？此操作不可恢复。')) return;
    post('/api/admin/clear-traffic', { ip: '-' }).then(function (r) {
      toast(r.message || '已清空', !r.ok);
      refreshAll();
    });
  };

  $('btnClearSession').onclick = function () {
    if (!confirm('确定清除已保存的抓取会话？\n\n清除后服务会退回「手动维护」状态，' +
      '课表数据不会丢。想恢复自动抓取，再跑一次「一键同步」即可。')) return;
    post('/api/admin/clear-session', {}).then(function (r) {
      toast(r.message || '已清除', !r.ok);
      refreshAll();
    });
  };

  $('btnIcs').onclick = function () {
    window.open('/timetable.ics' + (K ? '?k=' + encodeURIComponent(K) : ''), '_blank');
  };

  /* ------------------------------------------------------------ 轮询 */
  function refreshAll() {
    api('/api/admin/overview').then(function (o) {
      renderCards(o);
      renderRateStats(o.ratings);
    }).catch(function () { });

    api('/api/admin/traffic?hours=24').then(function (t) {
      renderHours(t.hourly || []);
      renderBars($('devList'), t.topDevices, t.totalRecords);
      renderBars($('pageList'), t.topPages, t.totalRecords);
    }).catch(function () { });

    var rng = (document.getElementById('visitorRangeSel') || {}).value || 'today';
    api('/api/admin/visitors?range=' + encodeURIComponent(rng) + '&limit=80').then(function (v) {
      renderVisitors(v.visitors);
      var tag = document.getElementById('visitorRange');
      if (tag) {
        var names = { today: '今天', week: '本周', month: '本月', all: '全部' };
        tag.textContent = (names[v.range] || '今天') + ' · ' + (v.count || 0) + ' 人';
      }
    }).catch(function (e) {
      var tb = document.querySelector('#visitors tbody');
      if (tb) tb.innerHTML = '<tr><td colspan="8" style="text-align:center;' +
        'color:var(--danger);padding:22px">读取失败：' +
        esc(e && e.message ? e.message : e) + '</td></tr>';
    });

    api('/api/admin/online?minutes=1').then(function (o) {
      if (!o || o.ok === false) {
        renderOnlineError((o && o.message) || '接口返回异常');
        return;
      }
      onlineCache.online = o.online || [];
      onlineCache.offline = o.offline || [];
      paintOnlineTabs();
      renderOnline(pickOnlineList());
    }).catch(function (e) {
      renderOnlineError('请求失败：' + (e && e.message ? e.message : e));
    });

    api('/api/admin/security').then(renderSecurity).catch(function () { });

    api('/api/admin/log?limit=200').then(function (l) {
      renderLog(l.records || []);
    }).catch(function () { });
  }

  var tabA = document.getElementById('onlineTab');
  var tabB = document.getElementById('offlineTab');
  if (tabA) tabA.addEventListener('click', function () {
    onlineView = 'online'; paintOnlineTabs(); renderOnline(pickOnlineList());
  });
  if (tabB) tabB.addEventListener('click', function () {
    onlineView = 'offline'; paintOnlineTabs(); renderOnline(pickOnlineList());
  });

  var sel = document.getElementById('visitorRangeSel');
  if (sel) {
    try { sel.value = localStorage.getItem('kt_vrange') || 'today'; } catch (e) {}
    var onRange = function () {
      try { localStorage.setItem('kt_vrange', sel.value); } catch (e) {}
      refreshAll();
    };
    sel.addEventListener('change', onRange);
    sel.addEventListener('input', onRange);
  }

  refreshAll();
  setInterval(refreshAll, 3000);

/* ---------------------------------------------------------------- 副班评价
   放在「快捷操作」下面那块面板：平均分 + 星级 + 五星分布 + 投票人数。 */
function renderRateStats(r) {
  var box = $('rateStats');
  if (!box) return;
  r = r || { counts: {}, total: 0, avg: 0, today: 0 };
  var total = r.total || 0;
  if (!total) {
    box.innerHTML = '<div style="padding:14px 0;text-align:center;color:var(--text-faint)">还没有人评价</div>';
    return;
  }
  var counts = r.counts || {};
  var max = 1;
  for (var i = 1; i <= 5; i++) max = Math.max(max, counts[String(i)] || 0);

  var avg = r.avg || 0, stars = '';
  for (var s = 1; s <= 5; s++) stars += (s <= Math.round(avg) ? '★' : '☆');

  var head = '<div style="display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:14px">' +
    '<span style="font-size:32px;font-weight:850;font-family:var(--font-num,monospace);letter-spacing:-.03em;color:var(--text)">' +
    avg.toFixed(1) + '</span>' +
    '<span style="color:#ffc53d;font-size:18px;letter-spacing:1px">' + stars + '</span>' +
    '<span style="color:var(--text-faint);font-size:12.5px">共 <b style="color:var(--text)">' +
    total + '</b> 人评价 · 近 24 小时 <b style="color:var(--text)">' + (r.today || 0) + '</b> 人</span></div>';

  var rows = '';
  for (var k = 5; k >= 1; k--) {
    var c = counts[String(k)] || 0;
    var pct = Math.round(c / max * 100);
    rows += '<div style="display:flex;align-items:center;gap:10px;margin-bottom:7px;font-size:12.5px">' +
      '<span style="width:34px;color:var(--text-faint)">' + k + ' 星</span>' +
      '<span style="flex:1;height:8px;border-radius:99px;background:var(--surface-2);overflow:hidden">' +
      '<i style="display:block;height:100%;width:' + pct + '%;background:#ffc53d;border-radius:99px"></i></span>' +
      '<span style="width:42px;text-align:right;font-weight:700;color:var(--text)">' + c + '</span></div>';
  }
  box.innerHTML = head + rows;
}
})();
