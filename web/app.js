/* ============================================================================
   班级课表 · 前端
   零依赖。桌面/平板走 7 列网格，手机自动切成「日视图」。
   ==========================================================================*/
(function () {
  'use strict';

  /* 节次时间表（如与学校不同，改这里） */
  var SECTIONS = [
    ['08:30', '09:15'],   // 第 1 节
    ['09:25', '10:10'],   // 第 2 节
    ['10:30', '11:15'],   // 第 3 节
    ['11:25', '12:10'],   // 第 4 节
    ['14:10', '14:55'],   // 第 5 节
    ['15:05', '15:50'],   // 第 6 节
    ['16:10', '16:55'],   // 第 7 节
    ['17:05', '17:50'],   // 第 8 节
    ['19:00', '19:45'],   // 第 9 节
    ['19:55', '20:40'],   // 第 10 节
    ['20:50', '21:35'],   // 备用
    ['21:45', '22:30']    // 备用
  ];
  var DAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];
  var SHORT = ['一', '二', '三', '四', '五', '六', '日'];

  var COLORS = ['#4d9dff', '#8b7cff', '#34d399', '#fbbf24', '#fb7185',
    '#22d3ee', '#fb923c', '#a78bfa', '#4ade80', '#f472b6'];

  var state = {
    data: null, view: 'week', week: 1, weekTouched: false,
    markChanged: {}, mobileDay: 0, ready: false
  };

  var K = new URLSearchParams(location.search).get('k');

  function $(id) { return document.getElementById(id); }
  function api(path, opts) {
    var u = path + (path.indexOf('?') >= 0 ? '&' : '?') + 'k=' + encodeURIComponent(K || '');
    return fetch(u, opts).then(function (r) { return r.json(); });
  }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function toMin(s) { if (!s) return 0; var p = s.split(':'); return (+p[0]) * 60 + (+p[1]); }
  function fmtTime(ts) {
    if (!ts) return '—';
    var d = new Date(ts * 1000);
    return (d.getMonth() + 1) + '月' + d.getDate() + '日 ' +
      pad(d.getHours()) + ':' + pad(d.getMinutes());
  }
  function ranges(w) {
    if (!w || !w.length) return '—';
    w = w.slice().sort(function (a, b) { return a - b; });
    var out = [], s = w[0], p = w[0];
    for (var i = 1; i < w.length; i++) {
      if (w[i] === p + 1) { p = w[i]; continue; }
      out.push(s === p ? '' + s : s + '-' + p); s = p = w[i];
    }
    out.push(s === p ? '' + s : s + '-' + p);
    return out.join(',');
  }
  function colorOf(name) {
    var h = 0;
    for (var i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) % 9973;
    return COLORS[h % COLORS.length];
  }

  /* ------------------------------------------------------------ 主题 */
  var themeMode = 'auto';
  try { themeMode = localStorage.getItem('kt-theme') || 'auto'; } catch (e) { }

  function applyTheme() {
    var dark = themeMode === 'dark' || (themeMode === 'auto' &&
      window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
    var btn = $('themeBtn');
    if (btn) {
      btn.textContent = dark ? '☾' : '☀';
      btn.title = '主题：' +
        (themeMode === 'auto' ? '跟随系统' : (dark ? '深色' : '浅色')) + '（点击切换）';
    }
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', dark ? '#080c12' : '#f4f6f9');
  }
  $('themeBtn').onclick = function () {
    if (themeMode === 'auto') {
      themeMode = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    } else if (themeMode === 'dark') {
      themeMode = 'light';
    } else {
      themeMode = 'auto';
    }
    try { localStorage.setItem('kt-theme', themeMode); } catch (e) { }
    applyTheme();
  };
  if (window.matchMedia) {
    var mq = window.matchMedia('(prefers-color-scheme: dark)');
    var onSys = function () { if (themeMode === 'auto') applyTheme(); };
    if (mq.addEventListener) mq.addEventListener('change', onSys); else mq.addListener(onSys);
  }
  applyTheme();

  /* ------------------------------------------------------------ 入口说明
     右上角只保留主题切换。
     这些入口都不在页面上显示，只能手动输网址：
       管理后台  /admin      （独立口令）
       录入课表  /edit?k=xxx
       重新抓取  /grab?k=xxx
     */

  /* ------------------------------------------------------------ 分段控件滑块 */
  function moveThumb() {
    var box = $('viewTabs'), thumb = $('segThumb');
    if (!box || !thumb) return;
    var on = box.querySelector('button.on');
    if (!on) return;
    thumb.style.width = on.offsetWidth + 'px';
    thumb.style.transform = 'translateX(' + (on.offsetLeft - 3) + 'px)';
  }
  document.querySelectorAll('#viewTabs button').forEach(function (b) {
    b.onclick = function () {
      document.querySelectorAll('#viewTabs button').forEach(function (x) { x.classList.remove('on'); });
      b.classList.add('on');
      moveThumb();
      state.view = b.dataset.view;
      ['week', 'today', 'term'].forEach(function (v) {
        var sec = $('view-' + v);
        if (!sec) return;
        if (v === state.view) {
          sec.style.display = '';
          sec.classList.remove('view');
          void sec.offsetWidth;
          sec.classList.add('view');
        } else {
          sec.style.display = 'none';
        }
      });
      if (state.view === 'today') renderToday();
      if (state.view === 'week') { renderGrid(); renderDayView(); }
    };
  });

  /* ------------------------------------------------------------ 数据查询 */
  function coursesOn(week, day, sec) {
    return (state.data.courses || []).filter(function (c) {
      return c.weekday === day && (c.weeks || []).indexOf(week) >= 0 &&
        sec >= c.startSection && sec <= c.endSection;
    });
  }
  function maxSection() {
    var m = 0;
    (state.data.courses || []).forEach(function (c) { if (c.endSection > m) m = c.endSection; });
    return m;
  }
  function idx(c) { return (state.data.courses || []).indexOf(c); }

  function weekMonday(week) {
    var d = state.data; if (!d) return null;
    var base = null, anchor = 1;
    if (d.weekMonday) { base = new Date(d.weekMonday + 'T00:00:00'); anchor = d.currentWeek || 1; }
    else if (d.termStart) { base = new Date(d.termStart + 'T00:00:00'); anchor = 1; }
    if (!base || isNaN(base.getTime())) return null;
    return new Date(base.getTime() + (week - anchor) * 7 * 86400000);
  }

  /* ------------------------------------------------------------ 网格 */

  /* 第9周临时加的三节课：按「课程名 + 星期 + 起始节」硬判断，
     不依赖后端字段（normalize 会把多余字段过滤掉）。 */
  function isHot(c) {
    if (!c || c.name !== '电子技术与应用') return false;
    var wd = c.weekday, s = c.startSection;
    return (wd === 3 && (s === 5 || s === 9)) || (wd === 4 && s === 9);
  }

  function courseClass(c) {
    var key = c.name + '|' + c.weekday + '|' + c.startSection;
    if (isHot(c)) return ' hot';                // 临时加课：粉色发光
    if (state.markChanged[key] === 'added') return ' added';
    if (state.markChanged[key] === 'changed') return ' changed';
    return '';
  }

  function renderGrid() {
    var g = $('grid');
    if (!state.data) return;
    var nSec = Math.max(10, maxSection());
    var today = new Date().getDay(); today = today === 0 ? 7 : today;
    var isThisWeek = (state.week === (state.data.currentWeek || 1));
    var mon = weekMonday(state.week);
    var h = '', n = 0;

    h += '<div class="cell head-cell corner" style="grid-column:1;grid-row:1">' +
      '<span class="dname">节次</span><span class="ddate">时间</span></div>';
    for (var d = 1; d <= 7; d++) {
      var ds = '';
      if (mon) {
        var dt = new Date(mon.getTime() + (d - 1) * 86400000);
        ds = (dt.getMonth() + 1) + '/' + dt.getDate();
      }
      var hot = (isThisWeek && d === today) ? ' today' : '';
      h += '<div class="cell head-cell' + hot + '" style="grid-column:' + (d + 1) + ';grid-row:1">' +
        '<span class="dname">' + DAYS[d - 1] + '</span>' +
        (ds ? '<span class="ddate">' + ds + '</span>' : '') + '</div>';
    }

    for (var s = 1; s <= nSec; s++) {
      var t = SECTIONS[s - 1] || ['', ''];
      h += '<div class="cell timecol" data-row="' + s + '" style="grid-column:1;grid-row:' + (s + 1) + '">' +
        '<b>' + s + '</b>' + (t[0] ? '<span>' + t[0] + '</span><span>' + t[1] + '</span>' : '') + '</div>';
      for (var dd = 1; dd <= 7; dd++) {
        var list = coursesOn(state.week, dd, s);
        var starts = list.filter(function (x) { return x.startSection === s; });
        if (starts.length) {
          var c = starts[0];
          var span = Math.max(1, c.endSection - c.startSection + 1);
          h += '<div class="course' + courseClass(c) + '" data-i="' + idx(c) + '" ' +
            'style="grid-column:' + (dd + 1) + ';grid-row:' + (s + 1) + ' / span ' + span +
            ';--course-color:' + colorOf(c.name) + ';--i:' + (n++) + '">' +
            '<div class="cn">' + esc(c.name) +
            (isHot(c) ? ' <span class="hotbadge">调课</span>' : '') + '</div>' +
            (c.room ? '<div class="room">' + esc(c.room) + '</div>' : '') +
            (c.teacher ? '<div class="meta">' + esc(c.teacher) + '</div>' : '') +
            '</div>';
        } else if (!list.some(function (x) { return x.startSection < s && x.endSection >= s; })) {
          h += '<div class="cell" style="grid-column:' + (dd + 1) + ';grid-row:' + (s + 1) + '"></div>';
        }
      }
    }

    h += '<div class="nowline" id="nowline" style="display:none"></div>';
    g.innerHTML = h;

    g.onclick = function (e) {
      var elx = e.target.closest('.course');
      if (!elx) return;
      showDetail((state.data.courses || [])[+elx.dataset.i]);
    };

    requestAnimationFrame(positionNowLine);
    scrollTodayToLeft();       // 打开就把今天对齐到节次列右边
  }

  /* ------------------------------------------------------------ 今天对齐到最左边
     目标：打开网页后，今天是星期几那一列紧贴在冻结的「节次」列右边。

     做法（重写过一次，这次刻意绕开所有坑）：
       不查 .today 类，直接用星期几算列号；
       不用 getBoundingClientRect，改用两个单元格 offsetLeft 的**差值**——
       它们共享同一个 offsetParent，所以不管 offsetParent 是谁、sticky 怎么算，
       相减之后都是「今天列距离网格左边多远」，这个值一定是准的。
       也不查 scrollWidth 判断能不能滚，直接赋值，浏览器自己会夹住。

     就是一次 scrollLeft 赋值，没有动画、没有定时器、没有 requestAnimationFrame。 */
  function scrollTodayToLeft() {
    if (!document.body.classList.contains('force-grid')) return;

    var wrap = document.querySelector('.gridwrap');
    var grid = document.getElementById('grid');
    if (!wrap || !grid) return;

    // 1 = 周一 … 7 = 周日
    var dow = new Date().getDay();
    if (dow === 0) dow = 7;

    // .head-cell 一共 8 个：第 0 个是左上角「节次」，第 1..7 个是周一到周日
    var cells = grid.querySelectorAll('.head-cell');
    if (cells.length < 8) return;
    var corner = cells[0];
    var cell = cells[dow];
    if (!cell || !corner) return;

    // 相对差值 = 今天列左边缘到网格原点的距离 = 需要滚动的距离
    // （节次列是 sticky 冻结的，宽度正好就是 corner 的宽度）
    var want = cell.offsetLeft - corner.offsetLeft;

    var max = wrap.scrollWidth - wrap.clientWidth;
    if (max <= 0) return;              // 屏幕够宽，7 天都放得下，不用对齐
    if (want > max) want = max;
    if (want < 0) want = 0;

    if (Math.abs(wrap.scrollLeft - want) < 2) return;
    wrap.scrollLeft = want;
  }
  /* ------------------------------------------------------------ 当前时刻线 */
  function positionNowLine() {
    var line = $('nowline');
    if (!line || !state.data) return;
    var grid = $('grid');
    if (!grid) return;
    if (state.week !== (state.data.currentWeek || 1)) { line.style.display = 'none'; return; }

    /* 关键改法：不再用「网格顶部 + 像素偏移」推算，
       而是把红线直接塞进「当前节次那一格」里，
       让它用 position:absolute 相对那个格子定位。
       格子本身就在正确的位置上 —— 线在物理上不可能错位。 */
    function cellOf(s) {
      return grid.querySelector('.timecol[data-row="' + s + '"]');
    }

    var now = new Date();
    var mins = now.getHours() * 60 + now.getMinutes() + now.getSeconds() / 60;
    var label = pad(now.getHours()) + ':' + pad(now.getMinutes());
    var nSec = (SECTIONS && SECTIONS.length) || 12;

    function put(cell, frac) {
      if (!cell) { line.style.display = 'none'; return; }
      if (line.parentNode !== cell) cell.appendChild(line);
      var h = cell.offsetHeight || 0;
      line.style.top = Math.round(frac * h) + 'px';
      line.style.left = '0';
      line.style.right = '0';
      line.dataset.time = label;
      line.style.display = '';
    }

    for (var s = 1; s <= nSec; s++) {
      var t = SECTIONS[s - 1];
      if (!t) break;
      var st = toMin(t[0]), en = toMin(t[1]);
      if (mins >= st && mins <= en) {
        put(cellOf(s), (mins - st) / Math.max(1, en - st));
        return;
      }
      if (mins < st) {
        put(cellOf(s), 0);          // 还没到这一节，线贴在这一节的顶上
        return;
      }
    }
    line.style.display = 'none';
  }

  window.addEventListener('resize', function () { moveThumb(); positionNowLine(); });
  setInterval(positionNowLine, 60000);

  /* ------------------------------------------------------------ 手机日视图 */
  function renderDayView() {
    if (!state.data) return;
    var d = state.data;
    var mon = weekMonday(state.week);
    var td = new Date(); td = td.getDay(); td = td === 0 ? 7 : td;
    var isThisWeek = (state.week === (d.currentWeek || 1));

    if (!state.mobileDay) state.mobileDay = isThisWeek ? td : 1;

    var strip = '';
    for (var i = 1; i <= 7; i++) {
      var cnt = (d.courses || []).filter(function (c) {
        return c.weekday === i && (c.weeks || []).indexOf(state.week) >= 0;
      }).length;
      var dtxt = '';
      if (mon) { var dt = new Date(mon.getTime() + (i - 1) * 86400000); dtxt = dt.getDate(); }
      strip += '<div class="daychip' + (i === state.mobileDay ? ' on' : '') +
        (isThisWeek && i === td ? ' today' : '') + '" data-day="' + i + '">' +
        '<div class="dn">' + DAYS[i - 1] + '</div>' +
        '<div class="dd">' + (dtxt || SHORT[i - 1]) + '</div>' +
        '<div class="cnt">' + (cnt ? cnt + ' 节' : '没课') + '</div></div>';
    }
    $('dayStrip').innerHTML = strip;
    $('dayStrip').onclick = function (e) {
      var ch = e.target.closest('.daychip'); if (!ch) return;
      state.mobileDay = +ch.dataset.day;
      renderDayView();
    };

    var day = state.mobileDay;
    var list = (d.courses || []).filter(function (c) {
      return c.weekday === day && (c.weeks || []).indexOf(state.week) >= 0;
    }).sort(function (a, b) { return a.startSection - b.startSection; });

    var now = new Date();
    var curMins = now.getHours() * 60 + now.getMinutes();
    var html = '';
    list.forEach(function (c, i) {
      var t0 = SECTIONS[c.startSection - 1] || ['', ''];
      var t1 = SECTIONS[c.endSection - 1] || t0;
      var cls = 'slot';
      if (isThisWeek && day === td) {
        if (toMin(t0[0]) <= curMins && curMins <= toMin(t1[1])) cls += ' now';
        else if (toMin(t1[1]) < curMins) cls += ' past';
      }
      html += '<div class="' + cls + '" data-i="' + idx(c) + '" style="--course-color:' +
        colorOf(c.name) + ';--i:' + i + '">' +
        '<div class="stime"><b>' + t0[0] + '</b>' + t1[1] + '</div>' +
        '<div class="sbody"><div class="sname">' + esc(c.name) + '</div>' +
        '<div class="smeta">' +
        (c.room ? '<span class="sroom">' + esc(c.room) + '</span>' : '') +
        (c.teacher ? '<span>' + esc(c.teacher) + '</span>' : '') +
        '<span>第' + c.startSection + '-' + c.endSection + '节</span>' +
        '</div></div></div>';
    });
    $('dayList').innerHTML = html ||
      '<div class="empty"><span class="big-emoji">🌤</span>这天没有课</div>';
    $('dayList').onclick = function (e) {
      var elx = e.target.closest('.slot'); if (!elx) return;
      showDetail((d.courses || [])[+elx.dataset.i]);
    };
  }

  /* ------------------------------------------------------------ 今天 */
  var cdTimer = null;
  function renderToday() {
    if (!state.data) return;
    var now = new Date();
    var dow = now.getDay(); dow = dow === 0 ? 7 : dow;
    var mins = now.getHours() * 60 + now.getMinutes();
    var week = state.data.currentWeek || state.week;

    var list = (state.data.courses || []).filter(function (c) {
      return c.weekday === dow && (c.weeks || []).indexOf(week) >= 0;
    }).sort(function (a, b) { return a.startSection - b.startSection; });

    var box = $('todayList');
    if (!list.length) {
      box.innerHTML = '<div class="empty"><span class="big-emoji">🎉</span>今天没有课</div>';
    } else {
      box.innerHTML = list.map(function (c, i) {
        var t = SECTIONS[c.startSection - 1] || ['', ''];
        var t2 = SECTIONS[c.endSection - 1] || t;
        var st = toMin(t[0]), en = toMin(t2[1] || t[1]);
        var cls = 'titem';
        if (st <= mins && mins <= en) cls += ' now';
        else if (en < mins) cls += ' past';
        return '<div class="' + cls + '" style="--i:' + i + '">' +
          '<div class="t">' + t[0] + '<br>' + (t2[1] || '') + '</div>' +
          '<div><div class="n">' + esc(c.name) + '</div>' +
          '<div style="text-align:left;margin:0;color:var(--text-dim);font-size:12px">' +
          [c.room, c.teacher].filter(Boolean).map(esc).join(' · ') + '</div></div>' +
          '<div class="r">第' + c.startSection + '-' + c.endSection + '节</div></div>';
      }).join('');
    }

    var next = null;
    for (var i = 0; i < list.length; i++) {
      var tt = SECTIONS[list[i].startSection - 1] || ['', ''];
      if (toMin(tt[0]) > mins) { next = list[i]; break; }
    }
    var nb = $('nextBox');
    if (!next) {
      nb.innerHTML = '<span class="label">' +
        (list.length ? '今天的课都上完啦 🎉' : '今天没有课 🎉') + '</span>';
    } else {
      var nt = SECTIONS[next.startSection - 1];
      nb.innerHTML = '<span class="big" id="cd">--:--:--</span>' +
        '<span class="label">后开始 · <b>' + esc(next.name) + '</b> ' +
        esc(next.room || '') + '</span>';
      startCountdown(nt[0]);
    }
    $('todayTitle').textContent = '今天（' + DAYS[dow - 1] +
      '）的课 · 第 ' + week + ' 周';
  }

  function startCountdown(hhmm) {
    if (cdTimer) clearInterval(cdTimer);
    var target = new Date();
    var p = hhmm.split(':');
    target.setHours(+p[0], +p[1], 0, 0);
    function tick() {
      var el = $('cd');
      if (!el) { clearInterval(cdTimer); return; }
      var diff = Math.floor((target - new Date()) / 1000);
      if (diff < 0) diff = 0;
      el.textContent = pad(Math.floor(diff / 3600)) + ':' +
        pad(Math.floor((diff % 3600) / 60)) + ':' + pad(diff % 60);
    }
    tick();
    cdTimer = setInterval(tick, 1000);
  }

  /* ------------------------------------------------------------ 全学期 */
  function renderTerm() {
    if (!state.data) return;
    var max = state.data.maxWeek || 20;
    var courses = (state.data.courses || []).filter(function (c) {
      /* 全学期表里不显示临时调课（overrides 里加的 adhoc 课） */
      var id = String(c.id || '');
      if (id.indexOf('adhoc') === 0) return false;
      if ((c.note || '').indexOf('调课') >= 0) return false;
      return true;
    }).slice().sort(function (a, b) {
      return a.weekday - b.weekday || a.startSection - b.startSection;
    });
    var h = '<thead><tr><th>课程</th><th>星期</th><th>节次</th><th>地点</th><th>教师</th>';
    for (var w = 1; w <= max; w++) h += '<th>' + w + '</th>';
    h += '</tr></thead><tbody>';
    courses.forEach(function (c) {
      h += '<tr><td class="name">' + esc(c.name) + '</td><td>' + DAYS[c.weekday - 1] + '</td>' +
        '<td>' + c.startSection + '-' + c.endSection + '</td><td>' + esc(c.room || '') +
        '</td><td>' + esc(c.teacher || '') + '</td>';
      for (var w2 = 1; w2 <= max; w2++) {
        var on = (c.weeks || []).indexOf(w2) >= 0;
        h += '<td class="' + (on ? 'on' : 'off') + '">' + (on ? '●' : '') + '</td>';
      }
      h += '</tr>';
    });
    $('termTable').innerHTML = h + '</tbody>';
  }

  /* ------------------------------------------------------------ 详情 */
  function showDetail(c) {
    if (!c) return;
    $('modalCard').innerHTML =
      '<h3>' + esc(c.name) + '</h3>' +
      '<div class="sub">' + esc(c.className || '') + '</div>' +
      '<div class="row"><span>时间</span><span>' + DAYS[c.weekday - 1] + ' 第' +
      c.startSection + '-' + c.endSection + '节</span></div>' +
      '<div class="row"><span>周次</span><span>第 ' + ranges(c.weeks) + ' 周</span></div>' +
      '<div class="row"><span>地点</span><span>' + esc(c.room || '—') + '</span></div>' +
      '<div class="row"><span>教师</span><span>' + esc(c.teacher || '—') + '</span></div>' +
      (c.credit ? '<div class="row"><span>学分</span><span>' + esc(c.credit) + '</span></div>' : '') +
      '<button class="btn-ghost close" id="mdClose">关闭</button>';
    $('modal').classList.add('show');
    $('mdClose').onclick = function () { $('modal').classList.remove('show'); };
  }
  $('modal').onclick = function (e) { if (e.target === $('modal')) $('modal').classList.remove('show'); };

  /* ------------------------------------------------------------ 分享 */
  function bindCopy(id, text) {
    var b = $(id); if (!b) return;
    var label = b.textContent;
    b.onclick = function () {
      var done = function () {
        b.textContent = '✓ 已复制';
        setTimeout(function () { b.textContent = label; }, 1600);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, function () { fbCopy(text, done); });
      } else fbCopy(text, done);
    };
  }
  function fbCopy(text, done) {
    var ta = document.createElement('textarea');
    ta.value = text; ta.style.cssText = 'position:fixed;opacity:0;left:-9999px';
    document.body.appendChild(ta); ta.select();
    try { document.execCommand('copy'); done(); } catch (e) { alert('复制失败'); }
    document.body.removeChild(ta);
  }

  /* 分享面板：入口挪到页脚（右上角只留主题切换） */
  function openShare() {
    var base = location.origin;
    var q = K ? '?k=' + encodeURIComponent(K) : '';
    var page = base + '/' + q, ics = base + '/timetable.ics' + q;
    var text = '班级课表已上线：\n' + page +
      (K ? '\n访问口令：' + K : '\n（无需口令）') +
      '\n\n手机电脑都能打开，课表有变动页面会自动刷新。' +
      '\n\n想加进手机日历？在日历 App 里选「订阅日历」，粘贴：\n' + ics;
    var hasTerm = !!(state.data && state.data.termStart);
    $('modalCard').innerHTML =
      '<h3>分享给同学</h3><div class="sub">把下面这段发到班级群</div>' +
      '<div class="row" style="display:block"><span style="font-size:13px">网址</span>' +
      '<div style="margin-top:6px;word-break:break-all;color:var(--accent)">' + esc(page) + '</div></div>' +
      (K ? '<div class="row"><span>访问口令</span><span style="font-size:17px;font-weight:800;' +
        'letter-spacing:1px">' + esc(K) + '</span></div>' : '') +
      '<div class="row" style="display:block"><span style="font-size:13px">📅 日历订阅地址</span>' +
      '<div style="margin-top:6px;word-break:break-all;color:var(--accent);font-size:12.5px">' +
      esc(ics) + '</div>' +
      (hasTerm ? '<div style="font-size:12px;color:var(--text-faint);margin-top:6px">' +
        '在手机日历里「订阅日历」粘贴这个地址，课表和课前提醒会自动进日历。</div>'
        : '<div style="font-size:12px;color:var(--warn);margin-top:6px">' +
        '⚠️ 还没设第 1 周起始日，日历暂时生成不了。</div>') +
      '</div>' +
      '<button class="btn-ghost primary close" id="copyAll">复制整段文字</button>' +
      '<button class="btn-ghost close" id="copyIcs">只复制日历地址</button>' +
      '<button class="btn-ghost close" id="shareClose">关闭</button>';
    $('modal').classList.add('show');
    $('shareClose').onclick = function () { $('modal').classList.remove('show'); };
    bindCopy('copyAll', text);
    bindCopy('copyIcs', ics);
  }

  var shareLinkEl = $('shareLink');
  if (shareLinkEl) shareLinkEl.onclick = openShare;

  /* ------------------------------------------------------------ 交互 */
  $('weekSel').onchange = function () {
    state.week = +this.value;
    state.weekTouched = true;
    state.mobileDay = 0;
    renderAll();
  };
  $('backWeekBtn').onclick = function () {
    state.weekTouched = false;
    state.week = (state.data && state.data.currentWeek) || 1;
    state.mobileDay = 0;
    renderAll();
  };
  $('refreshBtn').onclick = function () {
    var b = this;
    b.classList.add('spin');
    api('/api/refresh', { method: 'POST' }).then(function (r) {
      b.classList.remove('spin');
      if (!r.ok) toast(r.message || '刷新失败');
      return load();
    }).catch(function () { b.classList.remove('spin'); });
  };

  function toast(msg) {
    var d = document.createElement('div');
    d.textContent = msg;
    d.style.cssText = 'position:fixed;left:50%;bottom:30px;transform:translateX(-50%);' +
      'background:var(--surface);border:1px solid var(--line);color:var(--text);' +
      'padding:11px 18px;border-radius:12px;box-shadow:var(--shadow-3);z-index:300;' +
      'font-size:13.5px;max-width:86vw;text-align:center';
    document.body.appendChild(d);
    setTimeout(function () { d.style.transition = 'opacity .3s'; d.style.opacity = '0'; }, 2200);
    setTimeout(function () { d.remove(); }, 2600);
  }

  /* ------------------------------------------------------------ 主渲染 */

  /* 运行时长：把秒数说成人话 */
  function fmtUptime(sec) {
    sec = Math.max(0, Math.floor(sec || 0));
    var d = Math.floor(sec / 86400), h = Math.floor((sec % 86400) / 3600),
      m = Math.floor((sec % 3600) / 60);
    if (d) return d + '<span class="u">天</span>' + h + '<span class="u">小时</span>';
    if (h) return h + '<span class="u">小时</span>' + m + '<span class="u">分</span>';
    if (m) return m + '<span class="u">分钟</span>';
    return sec + '<span class="u">秒</span>';
  }

  /* 首页顶部的两个小模块 */
  function renderMinis(d) {
    var s = d.stats || {};
    var up = $('statUptime');
    if (up) up.innerHTML = (s.uptime != null) ? fmtUptime(s.uptime) : '—';
    var vis = $('statVisitors');
    if (vis) {
      vis.innerHTML = (s.todayVisitors != null)
        ? s.todayVisitors + '<span class="u">人次</span>' : '—';
    }
  }

  function renderAll() {
    if (!state.data) return;
    var d = state.data;
    var max = d.maxWeek || 20;
    var cur = d.currentWeek || 1;

    renderMinis(d);

    if (!state.weekTouched) state.week = cur;
    if (!state.week || state.week < 1 || state.week > max) state.week = cur;

    /* 当前周没有数据、但别的周有 —— 自动跳到离当前周最近的那个有数据的周。
       不这么做的话，同学一打开看到的是空课表，会以为网站坏了。
       提示横幅会把真实情况写清楚。 */
    state.fellBackFrom = null;
    if (!state.weekTouched) {
      var coveredSet = {};
      (d.courses || []).forEach(function (c) {
        (c.weeks || []).forEach(function (w) { coveredSet[w] = 1; });
      });
      var hasCur = !!coveredSet[cur];
      if (!hasCur) {
        var ws = Object.keys(coveredSet).map(Number);
        if (ws.length) {
          ws.sort(function (a, b) { return Math.abs(a - cur) - Math.abs(b - cur); });
          state.week = ws[0];
          state.fellBackFrom = cur;
        }
      }
    }

    // 品牌区只放站名，不再塞「第几周」（周次在下拉框里已经有了）
    var wsel = $('weekSel');
    if (wsel) wsel.title = '当前查看：第 ' + state.week + ' 周';

    var sel = $('weekSel');
    sel.innerHTML = '';
    for (var i = 1; i <= max; i++) {
      var o = document.createElement('option');
      o.value = i;
      o.textContent = '第 ' + i + ' 周' + (i === cur ? '（本周）' : '');
      sel.appendChild(o);
    }
    sel.value = state.week;
    $('backWeekBtn').style.display = (state.week === cur) ? 'none' : '';

    renderGrid();
    renderDayView();
    if (state.view === 'today') renderToday();
    renderTerm();

    /* 同步状态不再放右上角（右上角只留主题切换），改成页脚里的一行小字 */
    var age = d.updatedAt ? (Date.now() / 1000 - d.updatedAt) : 1e9;
    var syncText, syncColor = 'var(--text-faint)';
    if (d.lastError) {
      syncText = '抓取异常';
      syncColor = 'var(--danger)';
    } else if (d.autoFetchOff || d.noSession) {
      syncText = '手动维护中';
    } else if (age < 1800) {
      syncText = '已同步';
      syncColor = 'var(--ok)';
    } else {
      syncText = '数据偏旧';
      syncColor = 'var(--warn)';
    }

    /* 页脚：同步状态 + 数据信息 + 分享入口（右上角已经清空，只留主题切换） */
    $('foot').innerHTML =
      '<span style="color:' + syncColor + '">● ' + syncText + '</span>' +
      ' · 数据来源：' + esc(d.source || '—') +
      ' · ' + d.count + ' 门课 · 更新于 ' + fmtTime(d.updatedAt) +
      ' · 版本 ' + d.revision +
      (d.termStart ? '<br>第 1 周始于 ' + esc(d.termStart) : '') +
      (d.lastError ? '<br><span class="err">' + esc(d.lastError) + '</span>' : '') +
      '';   /* 订阅入口已挪到上方卡片，底部蓝字删掉 */

    var sl = $('shareLink');
    if (sl) sl.onclick = function (e) { e.preventDefault(); openShare(); };

    /* 「课表有更新」横幅已按要求去掉。
       变更记录仍然留在后台（管理后台里的「最近变更」和 /api/diff 都能看），
       只是不再在同学页面上弹提示了。 */

    renderWeekHint(d);
    moveThumb();
  }

  /* 显示的这周没课，但别的周有 —— 说明是「数据没覆盖到」，不是真的没课。
     不加提示的话，同学打开会以为网站坏了。 */
  function renderWeekHint(d) {
    var box = $('weekHint');
    if (!box) return;

    var covered = {};
    (d.courses || []).forEach(function (c) {
      (c.weeks || []).forEach(function (w) { covered[w] = 1; });
    });
    var weeks = Object.keys(covered).map(Number).sort(function (a, b) { return a - b; });

    var thisWeek = (d.courses || []).filter(function (c) {
      return (c.weeks || []).indexOf(state.week) >= 0;
    }).length;

    if (thisWeek > 0 || !weeks.length) {
      // 这周有数据 —— 但如果是「本周没数据才自动跳过来的」，得说明白
      if (thisWeek > 0 && state.fellBackFrom) {
        box.style.display = '';
        $('weekHintTitle').textContent =
          '⚠️ 本周（第 ' + state.fellBackFrom + ' 周）还没有课表数据';
        $('weekHintBody').innerHTML =
          '现在显示的是 <b>第 ' + state.week + ' 周</b> —— 离本周最近的一个有数据的周。<br>' +
          '服务器只抓到 <b>第 ' + weeks.join('、') + ' 周</b> 的课表，其它周是空的，' +
          '不代表本周真的没课。<br><br>' +
          (K
            ? '<a href="/grab?k=' + encodeURIComponent(K) +
            '" style="color:var(--accent)">👉 点这里重新抓取完整课表（推荐）</a>'
            : '请联系管理员重新抓取课表。');
        return;
      }
      box.style.display = 'none';
      return;
    }

    box.style.display = '';
    $('weekHintTitle').textContent = '⚠️ 第 ' + state.week + ' 周还没有课表数据';

    // 把「有数据的周次」做成可点的按钮，一键跳过去
    var chips = weeks.map(function (w) {
      return '<button class="btn-ghost" data-goweek="' + w +
        '" style="padding:4px 12px;font-size:12.5px;margin:2px 4px 2px 0">第 ' + w + ' 周</button>';
    }).join('');

    $('weekHintBody').innerHTML =
      '服务器目前只抓到 <b>第 ' + weeks.join('、') + ' 周</b> 的课表，其它周是空的。' +
      '这不代表这周真的没课，多半是还没抓全。<br>' +
      '<div style="margin:10px 0 2px;color:var(--text)">先看有数据的周：</div>' +
      '<div style="margin-bottom:10px">' + chips + '</div>' +
      (K
        ? '<a href="/grab?k=' + encodeURIComponent(K) +
        '" style="color:var(--accent)">👉 点这里重新抓取完整课表（推荐）</a>'
        : '请联系管理员重新抓取课表。');

    $('weekHintBody').onclick = function (e) {
      var b = e.target.closest('[data-goweek]');
      if (!b) return;
      state.week = +b.dataset.goweek;
      state.weekTouched = true;
      state.mobileDay = 0;
      renderAll();
    };
  }

  /* ------------------------------------------------------------ 加载 & 实时 */

  /* 带重试的请求。
     为什么要重试：课表服务在国内家里，公网要经 Cloudflare 海外节点绕一圈，
     偶尔会有一两次请求超时。以前只试一次，一旦失败整页就停在骨架屏上 ——
     同学看到的就是「网站打开了但课表空白」。 */
  function apiRetry(path, opts, tries) {
    tries = tries || 4;
    var delay = 500;
    function attempt(n) {
      return api(path, opts).catch(function (e) {
        if (n <= 1) throw e;
        return new Promise(function (res) { setTimeout(res, delay); })
          .then(function () { delay = Math.min(delay * 2, 4000); return attempt(n - 1); });
      });
    }
    return attempt(tries);
  }

  function showLoadError(e) {
    var g = $('grid');
    if (g) {
      g.innerHTML = '<div style="grid-column:1/-1;min-width:100%;padding:48px 16px;text-align:center">' +
        '<div style="font-size:15px;font-weight:700;margin-bottom:8px">课表没加载出来</div>' +
        '<div style="color:var(--text-dim);font-size:13px;line-height:1.7;margin-bottom:16px">' +
        '学校服务器到家里这条线偶尔会抖一下，通常再试一次就好。<br>' +
        '<span style="color:var(--text-faint);font-size:12px">' + esc(String((e && e.message) || e)) +
        '</span></div>' +
        '<button class="btn-ghost primary" id="retryBtn" style="padding:10px 22px">重试</button>' +
        '</div>';
      var b = $('retryBtn');
      if (b) b.onclick = function () { b.textContent = '正在重试…'; load(); };
    }
    $('foot').innerHTML = '<span class="err">连接服务器失败</span>';
    // 5 秒后自己再试一次，用户不用管
    if (!state.data) setTimeout(function () { if (!state.data) load(); }, 5000);
  }

  function load() {
    return apiRetry('/api/schedule', null, 4).then(function (d) {
      if (d && d.courses) {
        state.data = d;
        state.ready = true;
        renderAll();
        setTimeout(positionNowLine, 60);
      }
      return d;
    }).catch(function (e) {
      showLoadError(e);
    });
  }

  /* 以前这里是一个 EventSource 长连接，浏览器会一直显示「加载中」。
     改成每 20 秒轻量轮询一次，行为一样，但标签页不再转圈。 */
  function startPolling() {
    state.rev = null;
    function tick() {
      if (document.hidden) return;          /* 页面在后台就不打扰 */
      fetch('/api/schedule?k=' + encodeURIComponent(K || ''),
            { cache: 'no-store' })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (!d || typeof d !== 'object') return;
          if (state.rev === null) { state.rev = d.revision; return; }
          if (d.revision === state.rev) return;
          state.rev = d.revision;
          state.markChanged = {};
          var ch = d.changes;
          if (Array.isArray(ch)) {
            ch.forEach(function (c) {
              if (c && c.course) {
                state.markChanged[c.course.name + '|' + c.course.weekday + '|' +
                  c.course.startSection] = (c.kind === 'added' ? 'added' : 'changed');
              }
            });
          }
          load().then(function () {
            setTimeout(function () { state.markChanged = {}; }, 14000);
          });
        })
        .catch(function () {});
    }
    setTimeout(tick, 3000);
    setInterval(tick, 20000);
  }

  /* ------------------------------------------------------------ 小屏也能看表格
     手机上默认是「日视图」（一列一列往下排），但有人就是习惯看整周网格。
     这里给个 ▦ 按钮，点了就切到表格（横向可滑动），选择记在本地。 */
  var NARROW = '(max-width: 760px)';
  function isNarrow() {
    return !!(window.matchMedia && window.matchMedia(NARROW).matches);
  }
  function applyGridMode() {
    // 默认进【旧视图】（手机上是日视图，宽屏本来就是表格）。
    // 用户点了切换按钮、并且确实选了网格，才记住用网格。
    // 用新键 kt_gridv。
    // 换键是故意的：之前测试时浏览器里存过 'grid'，
    // 不换键的话你打开还是网格，看起来就像"改了没用"。
    var on = false;
    try {
      if (localStorage.getItem('kt_gridv') === '1') on = true;
    } catch (e) { }
    document.body.classList.toggle('force-grid', on);
    var b = $('gridToggleBtn');
    if (b) {
      b.textContent = on ? '☰' : '▦';
      b.title = on ? '切换成列表视图' : '切换成表格视图（可左右滑动）';
    }
  }
  (function () {
    var b = $('gridToggleBtn');
    if (!b) return;
    // 只有窄屏才需要这个按钮，宽屏本来就是表格
    if (isNarrow()) b.style.display = '';
    b.onclick = function () {
      var on = document.body.classList.contains('force-grid');
      try { localStorage.setItem('kt_gridv', on ? '0' : '1'); } catch (e) { }
      applyGridMode();
      hideTip();
      if (state.data) setTimeout(function () { renderGrid(); positionNowLine(); }, 40);
    };
    window.addEventListener('resize', function () {
      setTimeout(function () {
        if (isNarrow()) b.style.display = '';
        else { b.style.display = 'none'; hideTip(); }
      }, 200);
    });
    applyGridMode();

    /* 气泡提示：页面加载完成后出现，指向这个切换按钮，3 秒后自动关 */
    function hideTip() {
      var t = $('gridTip');
      if (t && t.classList.contains('show')) t.classList.remove('show');
    }
    window.showGridTip = function () {
      var t = $('gridTip');
      if (!t) return;
      var b2 = $('gridToggleBtn');
      // 宽屏没有这个按钮，气泡就贴在工具栏右侧
      var r = (b2 && b2.style.display !== 'none')
        ? b2.getBoundingClientRect()
        : { left: window.innerWidth - 60, right: window.innerWidth - 24, bottom: 120, width: 36 };
      var w = Math.min(272, window.innerWidth - 24);
      var left = Math.max(12, Math.min(r.right - w, window.innerWidth - w - 12));
      t.style.width = w + 'px';
      t.style.left = left + 'px';
      t.style.top = (r.bottom + 12) + 'px';
      t.style.setProperty('--arrow-x', (r.left + r.width / 2 - left) + 'px');
      t.classList.remove('show');
      setTimeout(function () { t.classList.add('show'); }, 60);
      setTimeout(hideTip, 3000 + 460);
    };
  })();

  /* ------------------------------------------------------------ 评分
     打开 3 秒后浮出；点任意一颗星 = 提交；提交成功后原位显示感谢语，3 秒后收起。
     同一个人只评一次（本地记着），避免刷新页面就重复计。 */
  (function () {
    var box = $('rateBox');
    if (!box || !K) return;

    // 每次都展示（不再记「已经评过」），所以不做任何本地去重判断
    setTimeout(function () {
      box.style.display = '';
      box.classList.remove('gone', 'done');
      $('rateStars').style.display = '';
      $('rateThanks').style.display = 'none';
      $('rateTitle').textContent = '评价一下副班的课表网站';
      for (var q = 0; q < 5; q++) box.querySelectorAll('.star')[q].classList.remove('lit');
      box.setAttribute('aria-hidden', 'false');
      box.classList.add('show');
    }, 3000);

    function finish(star) {
      box.classList.add('done');
      $('rateStars').style.display = 'none';
      $('rateThanks').style.display = '';
      box.classList.remove('show');
      box.classList.add('show');
      $('rateTitle').textContent = '已收到你的评价';
      setTimeout(function () {
        box.classList.remove('show');
        box.classList.add('gone');
        setTimeout(function () { box.style.display = 'none'; }, 500);
      }, 3000);
    }

    var stars = box.querySelectorAll('.star');
    for (var i = 0; i < stars.length; i++) {
      (function (el) {
        var v = +el.getAttribute('data-v');
        el.onmouseenter = function () {
          for (var j = 0; j < stars.length; j++) {
            stars[j].classList.toggle('lit', +stars[j].getAttribute('data-v') <= v);
          }
        };
        el.onmouseleave = function () {
          for (var j = 0; j < stars.length; j++) stars[j].classList.remove('lit');
        };
        el.onclick = function () {
          for (var j = 0; j < stars.length; j++) {
            stars[j].classList.toggle('lit', +stars[j].getAttribute('data-v') <= v);
          }
          // 提交：失败也不打扰用户，直接走感谢流程
          try {
            fetch('/api/rate?k=' + encodeURIComponent(K), {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ score: v })
            }).catch(function () { });
          } catch (e) { }
          setTimeout(function () { finish(v); }, 260);   // 让星星先亮一下
        };
      })(stars[i]);
    }
  })();

  var rt = null;
  window.addEventListener('resize', function () {
    clearTimeout(rt);
    rt = setTimeout(function () {
      if (state.data) { renderGrid(); renderDayView(); }
      scrollTodayToLeft();       // 转屏直接跳，不播动画
    }, 180);
  });

  load().then(function () {
    startPolling();
    setInterval(load, 60000);

    // 整页加载完成（课表已渲染）之后再播入场动画和气泡
    // 对齐重试：字体/图标加载完、屏幕旋转、布局抖动都可能改变列宽，
    // 所以多打几个时间点，反正就是一次 scrollLeft 赋值，很便宜。
    [120, 400, 900, 1600].forEach(function (ms) {
      setTimeout(scrollTodayToLeft, ms);
    });
    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(function () { scrollTodayToLeft(); });
    }
    window.addEventListener('load', function () {
      setTimeout(scrollTodayToLeft, 60);
    });
    // 每次进入都弹气泡
    setTimeout(function () {
      if (window.showGridTip) window.showGridTip();
    }, 700);
  });
})();
