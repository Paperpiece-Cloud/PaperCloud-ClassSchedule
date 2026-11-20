/* 课表录入页 —— 零依赖 */
(function () {
  'use strict';
  var K = new URLSearchParams(location.search).get('k') || '';
  var DAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];

  function $(id) { return document.getElementById(id); }
  function api(path, opts) {
    var u = path + (path.indexOf('?') >= 0 ? '&' : '?') + 'k=' + encodeURIComponent(K);
    return fetch(u, opts).then(function (r) { return r.json(); });
  }
  function msg(el, text, cls) {
    el.className = 'msg ' + (cls || '');
    el.textContent = text || '';
  }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }
  function weeksToText(w) {
    if (!w || !w.length) return '';
    w = w.slice().sort(function (a, b) { return a - b; });
    var out = [], s = w[0], p = w[0];
    for (var i = 1; i < w.length; i++) {
      if (w[i] === p + 1) { p = w[i]; continue; }
      out.push(s === p ? '' + s : s + '-' + p); s = p = w[i];
    }
    out.push(s === p ? '' + s : s + '-' + p);
    return out.join(',') + '周';
  }

  // 把前端的 K 带到所有链接
  if (K) {
    $('backLink').href = '/?k=' + encodeURIComponent(K);
    document.querySelectorAll('a[href]').forEach(function (a) {
      if (a.getAttribute('href').indexOf('k=') < 0 && a.getAttribute('href').indexOf('http') !== 0) {
        a.href += (a.href.indexOf('?') >= 0 ? '&' : '?') + 'k=' + encodeURIComponent(K);
      }
    });
  }

  // ---------------------------------------------------------------- ① 批量
  var parsed = null;

  var DEMO = [
    '课程, 教师, 教室, 星期, 节次, 周次',
    '高等数学A, 张伟, 教学楼1-101, 周一, 1-2节, 1-16周',
    '大学英语, 李娜, 教学楼2-305, 周一, 3-4节, 1-16周',
    '程序设计基础, 王强, 实训楼A-402, 周二, 5-6节, 1-8周',
    '程序设计基础, 王强, 实训楼A-402, 周四, 5-6节, 1-8周',
    '体育, 赵敏, 田径场, 周三, 7-8节, 1-16周',
    '思想道德与法治, 陈刚, 教学楼3-101, 周四, 1-2节, 1-16周',
    '大学物理, 刘洋, 实验楼B-201, 周五, 3-4节, 2-16周(双)'
  ].join('\n');

  $('btnDemo').onclick = function () { $('bulk').value = DEMO; msg($('bulkMsg'), '已填入示例，点「解析预览」试试', 'warn'); };
  $('btnClearBulk').onclick = function () {
    $('bulk').value = ''; parsed = null; $('btnBulkSave').disabled = true;
    $('bulkPrev').classList.remove('show'); $('bulkErr').classList.remove('show');
    msg($('bulkMsg'), '');
  };

  $('btnParse').onclick = function () {
    var text = $('bulk').value;
    if (!text.trim()) { msg($('bulkMsg'), '请先粘贴课表内容', 'err'); return; }
    msg($('bulkMsg'), '解析中…');
    $('btnParse').disabled = true;
    api('/api/parse', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text })
    }).then(function (r) {
      $('btnParse').disabled = false;
      if (!r.ok) { msg($('bulkMsg'), r.message || '解析失败', 'err'); return; }
      parsed = r.courses || [];

      if (r.errors && r.errors.length) {
        $('bulkErr').classList.add('show');
        $('bulkErr').textContent = '以下 ' + r.errors.length + ' 行没能解析（已被跳过）：\n' +
          r.errors.map(function (e) { return '  • ' + e; }).join('\n');
      } else {
        $('bulkErr').classList.remove('show');
      }

      if (!parsed.length) {
        msg($('bulkMsg'), '一门课都没解析出来，检查一下格式', 'err');
        $('bulkPrev').classList.remove('show');
        $('btnBulkSave').disabled = true;
        return;
      }

      var h = '<tr><th>课程</th><th>教师</th><th>教室</th><th>星期</th><th>节次</th><th>周次</th></tr>';
      parsed.forEach(function (c) {
        h += '<tr><td>' + esc(c.name) + '</td><td>' + esc(c.teacher) + '</td><td>' + esc(c.room) +
          '</td><td>' + DAYS[c.weekday - 1] + '</td><td>' + c.startSection + '-' + c.endSection +
          '节</td><td>' + esc(weeksToText(c.weeks)) + '</td></tr>';
      });
      $('previewTable').innerHTML = h;
      $('bulkPrev').classList.add('show');
      $('btnBulkSave').disabled = false;
      msg($('bulkMsg'), '解析出 ' + parsed.length + ' 门课' +
        (r.errors && r.errors.length ? '（' + r.errors.length + ' 行跳过）' : '') +
        '，确认无误后点右边保存', 'ok');
    }).catch(function (e) {
      $('btnParse').disabled = false;
      msg($('bulkMsg'), '请求失败：' + e, 'err');
    });
  };

  $('btnBulkSave').onclick = function () {
    if (!parsed || !parsed.length) return;
    var maxW = 0;
    parsed.forEach(function (c) { (c.weeks || []).forEach(function (w) { if (w > maxW) maxW = w; }); });
    $('btnBulkSave').disabled = true;
    msg($('bulkMsg'), '保存中…');
    api('/api/courses', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ courses: parsed, maxWeek: maxW })
    }).then(function (r) {
      $('btnBulkSave').disabled = false;
      if (!r.ok) { msg($('bulkMsg'), r.message || '保存失败', 'err'); return; }
      msg($('bulkMsg'), '✅ 已保存 ' + r.count + ' 门课（版本 ' + r.revision + '）。' +
        '打开课表页面就能看到了。', 'ok');
      loadTable();
    }).catch(function (e) {
      $('btnBulkSave').disabled = false;
      msg($('bulkMsg'), '请求失败：' + e, 'err');
    });
  };

  // ---------------------------------------------------------------- ② 表格
  var rows = [];

  function dayOptions(sel) {
    return DAYS.map(function (d, i) {
      return '<option value="' + (i + 1) + '"' + (i + 1 === sel ? ' selected' : '') + '>' + d + '</option>';
    }).join('');
  }
  function secOptions(sel) {
    var o = '';
    for (var i = 1; i <= 14; i++) o += '<option value="' + i + '"' + (i === sel ? ' selected' : '') + '>' + i + '</option>';
    return o;
  }

  function renderTable() {
    var h = '<tr><th>课程名</th><th>教师</th><th>教室</th><th>星期</th><th>开始节</th><th>结束节</th>' +
      '<th>周次</th><th></th></tr>';
    rows.forEach(function (c, i) {
      h += '<tr data-i="' + i + '">' +
        '<td class="w-name"><input data-f="name" value="' + esc(c.name) + '"></td>' +
        '<td class="w-teacher"><input data-f="teacher" value="' + esc(c.teacher) + '"></td>' +
        '<td class="w-room"><input data-f="room" value="' + esc(c.room) + '"></td>' +
        '<td class="w-daysel"><select data-f="weekday">' + dayOptions(c.weekday) + '</select></td>' +
        '<td class="w-sec"><select data-f="startSection">' + secOptions(c.startSection) + '</select></td>' +
        '<td class="w-sec"><select data-f="endSection">' + secOptions(c.endSection) + '</select></td>' +
        '<td class="w-weeks"><input data-f="weeks" value="' + esc(weeksToText(c.weeks)) + '" placeholder="1-16周"></td>' +
        '<td style="text-align:center"><span class="rowdel" data-del="' + i + '">✕</span></td>' +
        '</tr>';
    });
    $('editTable').innerHTML = h;
  }

  $('editTable').addEventListener('input', function (e) {
    var tr = e.target.closest('tr'); if (!tr) return;
    var i = +tr.dataset.i, f = e.target.dataset.f; if (f === undefined) return;
    if (f === 'weekday' || f === 'startSection' || f === 'endSection') rows[i][f] = +e.target.value;
    else if (f !== 'weeks') rows[i][f] = e.target.value;
  });
  $('editTable').addEventListener('change', function (e) {
    var tr = e.target.closest('tr'); if (!tr) return;
    var i = +tr.dataset.i, f = e.target.dataset.f; if (f === undefined) return;
    if (f === 'weekday' || f === 'startSection' || f === 'endSection') {
      rows[i][f] = +e.target.value;
      if (f === 'startSection' && rows[i].endSection < rows[i].startSection) {
        rows[i].endSection = rows[i].startSection;
      }
      renderTable();
    }
  });
  $('editTable').addEventListener('click', function (e) {
    var d = e.target.dataset.del;
    if (d === undefined) return;
    rows.splice(+d, 1);
    renderTable();
  });

  function parseWeeksLocal(s) {
    // 前端轻量解析，只用于表格保存；后端会再解析一次
    var out = [];
    if (!s) return out;
    s = s.replace(/[第周\s]/g, '');
    s.split(/[,，、;；]+/).forEach(function (part) {
      var m = part.match(/^(\d+)\s*[-~—到]\s*(\d+)$/);
      if (m) { for (var i = +m[1]; i <= +m[2]; i++) out.push(i); return; }
      var n = part.match(/^(\d+)$/);
      if (n) out.push(+n[1]);
    });
    return out.sort(function (a, b) { return a - b; });
  }

  $('btnAddRow').onclick = function () {
    rows.push({ name: '', teacher: '', room: '', weekday: 1, startSection: 1, endSection: 2, weeks: [] });
    renderTable();
    var tbl = $('editTable');
    tbl.scrollIntoView({ behavior: 'smooth', block: 'center' });
  };

  $('btnSaveTable').onclick = function () {
    // 从输入框收集最新的周次文本
    document.querySelectorAll('#editTable tr[data-i]').forEach(function (tr) {
      var i = +tr.dataset.i;
      var wk = tr.querySelector('input[data-f="weeks"]');
      if (wk) rows[i].weeks = parseWeeksLocal(wk.value);
    });
    var clean = rows.filter(function (c) { return (c.name || '').trim(); });
    if (!clean.length) { msg($('tableMsg'), '至少要有课程名', 'err'); return; }
    var maxW = 0;
    clean.forEach(function (c) { (c.weeks || []).forEach(function (w) { if (w > maxW) maxW = w; }); });
    $('btnSaveTable').disabled = true;
    msg($('tableMsg'), '保存中…');
    api('/api/courses', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ courses: clean, maxWeek: maxW || 16 })
    }).then(function (r) {
      $('btnSaveTable').disabled = false;
      if (!r.ok) { msg($('tableMsg'), r.message || '保存失败', 'err'); return; }
      msg($('tableMsg'), '✅ 已保存 ' + r.count + ' 门课（版本 ' + r.revision + '）。', 'ok');
      loadTable();
    }).catch(function (e) {
      $('btnSaveTable').disabled = false;
      msg($('tableMsg'), '请求失败：' + e, 'err');
    });
  };

  $('btnExport').onclick = function () {
    api('/api/schedule').then(function (d) {
      var blob = new Blob([JSON.stringify(d.courses, null, 2)], { type: 'application/json' });
      var a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'timetable.json';
      a.click();
    });
  };

  function loadTable() {
    return api('/api/schedule').then(function (d) {
      rows = (d.courses || []).map(function (c) {
        return {
          name: c.name, teacher: c.teacher, room: c.room,
          weekday: c.weekday, startSection: c.startSection,
          endSection: c.endSection, weeks: c.weeks || []
        };
      });
      renderTable();
      $('curTermStart').textContent = d.termStart || '（未设置）';
      if (d.termStart) $('termStart').value = d.termStart;
      return d;
    });
  }

  // ---------------------------------------------------------------- ③ 学期起始
  $('btnSaveTerm').onclick = function () {
    var v = $('termStart').value;
    if (!v) { msg($('termMsg'), '请先选一个日期', 'err'); return; }
    msg($('termMsg'), '保存中…');
    api('/api/term', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ term_start: v })
    }).then(function (r) {
      if (!r.ok) { msg($('termMsg'), r.message || '保存失败', 'err'); return; }
      msg($('termMsg'), '✅ 已保存。同学打开网站会自动跳到当前周。', 'ok');
      $('curTermStart').textContent = v;
    }).catch(function (e) { msg($('termMsg'), '请求失败：' + e, 'err'); });
  };

  loadTable();
})();
