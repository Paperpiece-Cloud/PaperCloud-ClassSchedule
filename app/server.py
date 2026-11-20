"""课表站点服务器：静态页面 + JSON API + SSE 实时推送 + 访问口令。"""

import atexit
from . import essay
try:
    from . import auth
except Exception:      # 缺文件 / 依赖问题时，整站照常跑，只是没有登录
    auth = None
from . import qq
from . import overrides
import hashlib
import hmac
import json
import mimetypes
import os
import subprocess
import queue
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import classmgmt, normalize, security, sysinfo, timetable, traffic
from . import toolbox
from . import musicunlock
from .store import Store


PAGE_ZOOM = 0.85          # 全站显示比例（像浏览器缩放一样）
BUILD_TAG = "2026-10-17-ai3"
KT_SKELETON = r"""
<!-- KT-SKELETON：首帧骨架（服务端直出，先于任何内容绘制） -->
<style id="ktSkelCss">
#ktSkel{
  position: fixed; inset: 0; z-index: 2147482000;
  pointer-events: none; overflow: hidden;
  background: #f7fbff;
  transition: opacity .30s ease;
}
html[data-theme="dark"] #ktSkel{ background: #0e151d; }
#ktSkel.gone{ opacity: 0; }

/* 主页：只在卡片矩形内 */
body:has(.phone) #ktSkel{
  inset: auto;
  left: 50%; top: 8vh;
  width: min(360px, 92vw); height: 84vh;
  transform: translateX(-50%);
  border-radius: 26px;
}

#ktSkel .sk{
  position: absolute;
  background: rgba(124,153,188,.24);
  border-radius: 10px;
}
html[data-theme="dark"] #ktSkel .sk{ background: rgba(255,255,255,.10); }
#ktSkel .sk.round{ border-radius: 50%; }
#ktSkel .sk.pill{ border-radius: 99px; }

#ktSkel .band{
  position: absolute; left: 0; top: -30%; bottom: -30%; width: 62%;
  background: linear-gradient(105deg,
    rgba(160,200,255,0) 0%,
    rgba(168,206,255,.42) 30%,
    rgba(240,248,255,.85) 50%,
    rgba(168,206,255,.42) 70%,
    rgba(160,200,255,0) 100%);
  animation: ktBand .72s linear .12s 1 both;
  will-change: transform, opacity;
}
html[data-theme="dark"] #ktSkel .band{
  background: linear-gradient(105deg,
    rgba(120,170,255,0) 0%,
    rgba(120,170,255,.20) 30%,
    rgba(200,225,255,.34) 50%,
    rgba(120,170,255,.20) 70%,
    rgba(120,170,255,0) 100%);
}
@keyframes ktBand{
  0%   { transform: translate(-100%, 58%) rotate(-22deg); opacity: 0; }
  8%   { opacity: 1; }
  92%  { opacity: 1; }
  100% { transform: translate(235%, -68%) rotate(-22deg); opacity: 0; }
}

.kt-reveal{ animation: ktRevealUp .40s cubic-bezier(.22,1,.36,1) both; }
@keyframes ktRevealUp{
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: none; }
}
@media (prefers-reduced-motion: reduce){
  #ktSkel .band{ animation: none; opacity: 0; }
  .kt-reveal{ animation-duration: .01ms; }
}
</style>

<div id="ktSkel" aria-hidden="true">
  <div class="sk round" style="left:6%;top:5%;width:44px;height:44px"></div>
  <div class="sk pill" style="left:calc(6% + 56px);top:6%;width:38%;height:12px"></div>
  <div class="sk pill" style="left:calc(6% + 56px);top:calc(6% + 20px);width:24%;height:10px"></div>
  <div class="sk" style="left:6%;top:16%;width:88%;height:10%"></div>
  <div class="sk" style="left:6%;top:28%;width:88%;height:11%"></div>
  <div class="sk pill" style="left:6%;top:42%;width:34%;height:12px"></div>
  <div class="sk" style="left:6%;top:46%;width:88%;height:11%"></div>
  <div class="sk" style="left:6%;top:60%;width:88%;height:11%"></div>
  <div class="sk" style="left:6%;top:74%;width:88%;height:9%"></div>
  <div class="band"></div>
</div>

<script>
/* KT-SKELETON：只负责计时与退场；骨架本身由 HTML 直出 */
(function () {
  if (window.__ktSkel) return;
  window.__ktSkel = 1;

  /* 主页不加骨架：内容本来就秒出，避免隐藏后不恢复 */
  if (document.querySelector('.phone')) {
    var _e = document.getElementById('ktSkel');
    if (_e && _e.parentNode) _e.parentNode.removeChild(_e);
    return;
  }

  var el = document.getElementById('ktSkel');
  var t0 = Date.now();
  var isHome = !!document.querySelector('.phone');
  var minMs = isHome ? 1500 : 1000;
  var done = false;

  function reveal() {
    if (done) return;
    done = true;
    if (el && el.parentNode) {
      el.classList.add('gone');
      setTimeout(function () {
        if (el.parentNode) el.parentNode.removeChild(el);
      }, 320);
    }
    /* 内容逐块浮现 */
    var host = document.querySelector('.phone') ||
               document.querySelector('.wrap') ||
               document.body;
    var list = Array.prototype.slice.call(host.children).slice(0, 12);
    for (var i = 0; i < list.length; i++) {
      var e2 = list[i];
      if (!e2 || !e2.classList || e2.id === 'ktSkel') continue;
      e2.style.animationDelay = (i * 60) + 'ms';
      e2.classList.add('kt-reveal');
    }
  }

  function later() {
    var left = minMs - (Date.now() - t0);
    if (left > 0) setTimeout(reveal, left);
    else reveal();
  }

  /* 等首屏资源就绪，再按最短时长放行 */
  if (document.readyState === 'complete') later();
  else window.addEventListener('load', later);
  /* 兜底 */
  setTimeout(reveal, minMs + 1500);
})();
</script>
"""

SPLASH_SNIPPET = r"""
<!-- KT-SPLASH 启动动画 -->
<style id="ktSplashCss">
#ktSplash{position:fixed;inset:0;z-index:2147483600;display:flex;flex-direction:column;
  align-items:center;justify-content:center;gap:0;
  background:linear-gradient(125deg,#c9e3ff 0%,#ded0ff 26%,#bff2dd 52%,#ffe4b8 76%,#c9e3ff 100%);
  background-size:400% 400%;animation:ktBg 18s ease-in-out infinite;
  transition:opacity .45s ease,visibility .45s}
html[data-theme="dark"] #ktSplash{
  background:linear-gradient(125deg,#16283d 0%,#24203c 26%,#10312a 52%,#3a2c14 76%,#16283d 100%);
  background-size:400% 400%}
#ktSplash.gone{opacity:0;visibility:hidden;pointer-events:none}
@keyframes ktBg{0%{background-position:0% 50%}50%{background-position:100% 50%}100%{background-position:0% 50%}}
@media (prefers-reduced-motion:reduce){#ktSplash{animation:none}}

/* ---- 形变转圈 ---- */
.ktSpinBox{width:92px;height:92px;display:flex;align-items:center;justify-content:center;
  margin-bottom:28px}
/* 经典边框转圈：一圈浅色轨道 + 一段高亮弧
   颜色跟着站点主色走（浅色 #2a72dc / 深色 #7cc4ff） */
.ktSpin{
  width:54px;height:54px;
  border:5px solid rgba(42,114,220,.16);
  border-left-color:#2a72dc;
  border-radius:50%;
  animation:ktSpin .8s linear infinite;
  box-sizing:border-box;
  filter:drop-shadow(0 3px 10px rgba(42,114,220,.28));
}
html[data-theme="dark"] .ktSpin{
  border-color:rgba(255,255,255,.13);
  border-left-color:#7cc4ff;
  filter:drop-shadow(0 3px 12px rgba(90,170,255,.34));
}
@keyframes ktSpin{
  0%  {transform:rotate(0deg)}
  100%{transform:rotate(360deg)}
}
@media (prefers-reduced-motion:reduce){
  .ktSpin{animation-duration:1.6s}
}

/* ---- 进度条 ---- */
.ktBarWrap{width:min(260px,62vw);height:4px;border-radius:3px;overflow:hidden;
  background:rgba(120,160,210,.28)}
html[data-theme="dark"] .ktBarWrap{background:rgba(255,255,255,.14)}
.ktBarWrap i{display:block;height:100%;width:0;border-radius:3px;
  background:linear-gradient(90deg,#6cb8ff,#2a72dc);
  transition:width .35s cubic-bezier(.4,0,.2,1)}
html[data-theme="dark"] .ktBarWrap i{background:linear-gradient(90deg,#7cc4ff,#3b86f0)}

.ktPct{margin-top:11px;font-family:ui-monospace,Menlo,Consolas,monospace;
  font-size:12px;font-weight:700;color:rgba(30,60,100,.62);letter-spacing:.05em}
html[data-theme="dark"] .ktPct{color:rgba(190,215,240,.66)}

.ktTip{margin-top:20px;font-size:13.5px;font-weight:700;letter-spacing:.02em;
  color:rgba(26,52,88,.82);min-height:20px;text-align:center;padding:0 20px}
html[data-theme="dark"] .ktTip{color:rgba(210,228,246,.9)}
.ktTip span{display:inline-block;animation:ktFade .42s ease both}
@keyframes ktFade{from{opacity:0;transform:translateY(5px)}to{opacity:1;transform:none}}

.ktLogo{margin-top:26px;font-size:15px;font-weight:850;letter-spacing:-.01em;
  color:rgba(26,52,88,.5)}
html[data-theme="dark"] .ktLogo{color:rgba(190,215,240,.42)}
</style>

<div id="ktSplash">
  <div class="ktSpinBox"><div class="ktSpin"></div></div>
  <div class="ktBarWrap"><i id="ktBar"></i></div>
  <div class="ktPct" id="ktPct">0%</div>
  <div class="ktTip"><span id="ktTip"></span></div>
  <div class="ktLogo">PaperCloud</div>
</div>

<script id="ktSplashJs">
(function () {
  var el = document.getElementById('ktSplash');
  if (!el) return;

  // 只在首页显示。其它页面立刻摘掉，免得每次跳转都闪一下。
  var p = location.pathname;
  var isHome = (p === '/' || p === '/index.html' || p === '/home' || p === '/home.html');
  if (!isHome) { el.parentNode.removeChild(el); return; }

  var bar = document.getElementById('ktBar');
  var pct = document.getElementById('ktPct');
  var tip = document.getElementById('ktTip');

  var TIPS = [
    [0,  '正在建立安全连接'],
    [10, '正在验证安全性'],
    [22, '正在写入 cookies'],
    [34, '正在校验访问口令'],
    [46, '正在获取课表数据'],
    [58, '正在整理班级信息'],
    [70, '正在渲染界面'],
    [82, '正在优化显示效果'],
    [92, '马上就好']
  ];
  var shown = -1;

  var v = 0, target = 0, timer = null, done = false;

  function setTip() {
    var t = TIPS[0][1];
    for (var i = 0; i < TIPS.length; i++) if (v >= TIPS[i][0]) t = TIPS[i][1];
    if (t !== shown && tip) {
      shown = t;
      tip.innerHTML = '<span>' + t + '</span>';
    }
  }
  function paint() {
    if (bar) bar.style.width = v + '%';
    if (pct) pct.textContent = Math.round(v) + '%';
    setTip();
  }

  /* 进度：不靠猜，尽量贴着真实加载走。
     资源计数 + 阶段里程碑，两者取大值。 */
  function realPct() {
    try {
      var res = performance.getEntriesByType('resource') || [];
      var n = res.length;
      // 一个页面大概 5~15 个资源，按这个估个粗的
      var est = Math.min(88, 8 + n * 7);
      return est;
    } catch (e) { return 0; }
  }

  function tick() {
    if (done) return;
    var rp = realPct();
    if (rp > target) target = rp;
    // 慢慢往 target 靠，别跳
    v += Math.max(0.6, (target - v) * 0.18);
    if (v > 96) v = 96;
    paint();
  }
  timer = setInterval(tick, 120);

  function finish() {
    if (done) return;
    done = true;
    clearInterval(timer);
    v = 100; paint();
    setTimeout(function () {
      el.classList.add('gone');
      setTimeout(function () {
        if (el && el.parentNode) el.parentNode.removeChild(el);
      }, 500);
    }, 260);
  }

  // DOM 好了先推到 55%，视觉上有个台阶
  function onDom() { if (target < 55) target = 55; }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', onDom);
  } else { onDom(); }

  window.addEventListener('load', function () { target = 100; setTimeout(finish, 520); });

  // 兜底：8 秒还没好也放人
  setTimeout(finish, 8000);
  paint();
})();
</script>
<!-- /KT-SPLASH -->
"""

TOPBAR_SNIPPET = r"""<style>
/* ---------------- 全站 85% 等比缩放 ----------------
   zoom 在 iOS Safari 上会让 html 变成 85% 宽、右边留白，
   所以改用 transform: scale —— 它不影响布局尺寸，只缩放绘制，
   再把宽度反向放大 1/0.85，缩放后正好铺满，左右都不留白。
-------------------------------------------------- */
html{ overflow-x:hidden; background:inherit; --kt-zoom: __KT_ZOOM__; }
body{
  transform:scale(__KT_ZOOM__);
  transform-origin:top left;
  width:calc(100% / __KT_ZOOM__);
  min-height:calc(100vh / __KT_ZOOM__);
}
</style>

<style>
/* ===== 第9周临时加课：粉色动态发光 ===== */
@keyframes ktHotGlow {
  0%,100% { box-shadow: 0 0 0 1px rgba(255,105,180,.55),
                        0 0 10px rgba(255,105,180,.32),
                        0 0 22px rgba(255,105,180,.16); }
  50%     { box-shadow: 0 0 0 1.5px rgba(255,105,180,.95),
                        0 0 18px rgba(255,105,180,.62),
                        0 0 40px rgba(255,105,180,.36); }
}
.course.kt-hot {
  animation: ktHotGlow 2.2s ease-in-out infinite !important;
  border-color: rgba(255,105,180,.85) !important;
}
.course.kt-hot .cn { color:#ff4f9a !important; font-weight:800 !important; }
html[data-theme="dark"] .course.kt-hot .cn { color:#ff86b8 !important; }
tr.kt-hot-row > td{
  background:rgba(255,105,180,.07);
  color:#ff4f9a !important;
  font-weight:700 !important;
}
tr.kt-hot-row > td:first-child{
  box-shadow:inset 3px 0 0 rgba(255,105,180,.95);
}
html[data-theme="dark"] tr.kt-hot-row > td{
  background:rgba(255,105,180,.11); color:#ff86b8 !important;
}
.kt-hotbadge{
  display:inline-block; margin-left:4px; padding:0 5px;
  font-size:9px; font-weight:800; line-height:1.5;
  border-radius:5px; vertical-align:1px; color:#fff;
  background:linear-gradient(135deg,#ff5fa2,#ff2d7e);
  box-shadow:0 0 8px rgba(255,70,150,.6);
}
@media (prefers-reduced-motion: reduce){
  .course.kt-hot{ animation:none !important;
    box-shadow:0 0 0 1.5px rgba(255,105,180,.85) !important; }
}
</style>
<script>
/* KT-HOTWEEK: 直接按 grid-column / grid-row 判断，不依赖任何业务字段 */
(function(){
  function mark(){
    var nodes = document.querySelectorAll('.course');
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      var gc = parseInt(el.style.gridColumn, 10);
      var gr = parseInt(el.style.gridRow, 10);
      if (!gc || !gr) continue;
      var wd = gc - 1, sec = gr - 1;
      var hit = (wd === 3 && (sec === 5 || sec === 9)) || (wd === 4 && sec === 9);
      // 只认坐标，不做文本兜底（否则会把同名的其它节次也标上）
      if (!hit) { if (el.classList.contains('kt-hot')) el.classList.remove('kt-hot'); continue; }
      if (!el.classList.contains('kt-hot')) el.classList.add('kt-hot');
      var cn = el.querySelector('.cn');
      if (cn && !cn.querySelector('.kt-hotbadge')) {
        var b = document.createElement('span');
        b.className = 'kt-hotbadge';
        b.textContent = '调课';
        cn.appendChild(b);
      }
    }
  }
  /* 列表视图：先找到「节次」那个单元格（纯数字-数字），再看是不是 5-6 / 9-10。
     不靠整行文本，避免被教室号、周次里的数字干扰。 */
  var SEC_RE = /^\s*第?\s*(\d{1,2})\s*[-–—,，~至]\s*(\d{1,2})\s*节?\s*$/;
  function rowHit(tr, txt){
    if (txt.indexOf('电子技术与应用') < 0) return false;
    if (txt.indexOf('周三') < 0 && txt.indexOf('周四') < 0) return false;
    var tds = tr.querySelectorAll('td, .cell, .col');
    for (var k = 0; k < tds.length; k++) {
      var m = (tds[k].textContent || '').trim().match(SEC_RE);
      if (!m) continue;
      var a = +m[1], b = +m[2];
      if (a === 5 && b === 6) return true;
      if (a === 9 && b === 10) return true;
      if (a === 5 && b === 5) return true;
      if (a === 9 && b === 9) return true;
      return false;
    }
    // 没有独立节次单元格：退回到整行正则
    return /(^|\D)5\s*[-–—,，~至]\s*6|(^|\D)9\s*[-–—,，~至]\s*10/.test(txt);
  }

  function markRows(){
    var rows = document.querySelectorAll('tr, li, .row-item');
    for (var i = 0; i < rows.length; i++) {
      var tr = rows[i];
      if (tr.querySelector && tr.querySelector('tr')) continue;   // 跳过 table 外壳
      var txt = tr.textContent || '';
      var hit = rowHit(tr, txt);
      if (hit) {
        if (!tr.classList.contains('kt-hot-row')) tr.classList.add('kt-hot-row');
        // 行内也补一个角标
        if (!tr.querySelector('.kt-hotbadge')) {
          var nm = tr.querySelector('.name, .cn, td');
          if (nm) {
            var b = document.createElement('span');
            b.className = 'kt-hotbadge';
            b.textContent = '调课';
            nm.appendChild(b);
          }
        }
      } else if (tr.classList.contains('kt-hot-row')) {
        tr.classList.remove('kt-hot-row');
      }
    }
  }

  mark();
  markRows();
  // 降频：iPhone 7 上 300ms 扫全表会卡死，改成 2 秒一次，
  // 并且去掉 MutationObserver（每次 DOM 变动都触发，滚动时狂跑）
  setInterval(function(){ mark(); markRows(); }, 2000);
  // 自检标记，方便在 Elements 里确认脚本跑过了
  document.documentElement.setAttribute('data-kt-hot', 'on');
  try { console.log('[KT-HOTWEEK] 已启动'); } catch (e) {}
})();
</script>

<style>
/* ===== 全站页脚状态条 ===== */
#ktFoot{
  position:fixed; left:0; right:0; bottom:0; z-index:35;
  padding:6px 12px calc(6px + env(safe-area-inset-bottom, 0px));
  text-align:center; font-size:10.5px; line-height:1.5;
  color:#7b8896; font-weight:600; white-space:nowrap;
  overflow:hidden; text-overflow:ellipsis;
  font-variant-numeric:tabular-nums;
  background:rgba(238,244,249,.95);
  -webkit-backdrop-filter:blur(10px); backdrop-filter:blur(10px);
  border-top:1px solid rgba(0,0,0,.05);
  pointer-events:none;
}
html[data-theme="dark"] #ktFoot{
  color:#6b7c8e; background:rgba(12,18,26,.94);
  border-top-color:rgba(255,255,255,.06);
}
html[data-theme="dark"] #ktFoot{
  background:linear-gradient(to top, rgba(10,16,24,.92), rgba(10,16,24,0));
}
/* 给页面底部留出空间，别让内容被页脚挡住 */
body{ padding-bottom:78px; }
#ktFoot .r{ display:block; }
#ktFoot b{ font-weight:750; color:#6d7c8d; }
html[data-theme="dark"] #ktFoot{ color:#6b7c8e; }
html[data-theme="dark"] #ktFoot b{ color:#8ea3b8; }
</style>

<!-- /KT-SPLASH -->
"""

TOPBAR_SNIPPET = r"""<style>
/* ---------------- 全站 85% 等比缩放 ----------------
   zoom 在 iOS Safari 上会让 html 变成 85% 宽、右边留白，
   所以改用 transform: scale —— 它不影响布局尺寸，只缩放绘制，
   再把宽度反向放大 1/0.85，缩放后正好铺满，左右都不留白。
-------------------------------------------------- */
html{ overflow-x:hidden; background:inherit; --kt-zoom: __KT_ZOOM__; }
body{
  transform:scale(__KT_ZOOM__);
  transform-origin:top left;
  width:calc(100% / __KT_ZOOM__);
  min-height:calc(100vh / __KT_ZOOM__);
}
</style>

<style>
/* ===== 第9周临时加课：粉色动态发光 ===== */
@keyframes ktHotGlow {
  0%,100% { box-shadow: 0 0 0 1px rgba(255,105,180,.55),
                        0 0 10px rgba(255,105,180,.32),
                        0 0 22px rgba(255,105,180,.16); }
  50%     { box-shadow: 0 0 0 1.5px rgba(255,105,180,.95),
                        0 0 18px rgba(255,105,180,.62),
                        0 0 40px rgba(255,105,180,.36); }
}
.course.kt-hot {
  animation: ktHotGlow 2.2s ease-in-out infinite !important;
  border-color: rgba(255,105,180,.85) !important;
}
.course.kt-hot .cn { color:#ff4f9a !important; font-weight:800 !important; }
html[data-theme="dark"] .course.kt-hot .cn { color:#ff86b8 !important; }
tr.kt-hot-row > td{
  background:rgba(255,105,180,.07);
  color:#ff4f9a !important;
  font-weight:700 !important;
}
tr.kt-hot-row > td:first-child{
  box-shadow:inset 3px 0 0 rgba(255,105,180,.95);
}
html[data-theme="dark"] tr.kt-hot-row > td{
  background:rgba(255,105,180,.11); color:#ff86b8 !important;
}
.kt-hotbadge{
  display:inline-block; margin-left:4px; padding:0 5px;
  font-size:9px; font-weight:800; line-height:1.5;
  border-radius:5px; vertical-align:1px; color:#fff;
  background:linear-gradient(135deg,#ff5fa2,#ff2d7e);
  box-shadow:0 0 8px rgba(255,70,150,.6);
}
@media (prefers-reduced-motion: reduce){
  .course.kt-hot{ animation:none !important;
    box-shadow:0 0 0 1.5px rgba(255,105,180,.85) !important; }
}
</style>
<script>
/* KT-HOTWEEK: 直接按 grid-column / grid-row 判断，不依赖任何业务字段 */
(function(){
  function mark(){
    var nodes = document.querySelectorAll('.course');
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      var gc = parseInt(el.style.gridColumn, 10);
      var gr = parseInt(el.style.gridRow, 10);
      if (!gc || !gr) continue;
      var wd = gc - 1, sec = gr - 1;
      var hit = (wd === 3 && (sec === 5 || sec === 9)) || (wd === 4 && sec === 9);
      // 只认坐标，不做文本兜底（否则会把同名的其它节次也标上）
      if (!hit) { if (el.classList.contains('kt-hot')) el.classList.remove('kt-hot'); continue; }
      if (!el.classList.contains('kt-hot')) el.classList.add('kt-hot');
      var cn = el.querySelector('.cn');
      if (cn && !cn.querySelector('.kt-hotbadge')) {
        var b = document.createElement('span');
        b.className = 'kt-hotbadge';
        b.textContent = '调课';
        cn.appendChild(b);
      }
    }
  }
  /* 列表视图：先找到「节次」那个单元格（纯数字-数字），再看是不是 5-6 / 9-10。
     不靠整行文本，避免被教室号、周次里的数字干扰。 */
  var SEC_RE = /^\s*第?\s*(\d{1,2})\s*[-–—,，~至]\s*(\d{1,2})\s*节?\s*$/;
  function rowHit(tr, txt){
    if (txt.indexOf('电子技术与应用') < 0) return false;
    if (txt.indexOf('周三') < 0 && txt.indexOf('周四') < 0) return false;
    var tds = tr.querySelectorAll('td, .cell, .col');
    for (var k = 0; k < tds.length; k++) {
      var m = (tds[k].textContent || '').trim().match(SEC_RE);
      if (!m) continue;
      var a = +m[1], b = +m[2];
      if (a === 5 && b === 6) return true;
      if (a === 9 && b === 10) return true;
      if (a === 5 && b === 5) return true;
      if (a === 9 && b === 9) return true;
      return false;
    }
    // 没有独立节次单元格：退回到整行正则
    return /(^|\D)5\s*[-–—,，~至]\s*6|(^|\D)9\s*[-–—,，~至]\s*10/.test(txt);
  }

  function markRows(){
    var rows = document.querySelectorAll('tr, li, .row-item');
    for (var i = 0; i < rows.length; i++) {
      var tr = rows[i];
      if (tr.querySelector && tr.querySelector('tr')) continue;   // 跳过 table 外壳
      var txt = tr.textContent || '';
      var hit = rowHit(tr, txt);
      if (hit) {
        if (!tr.classList.contains('kt-hot-row')) tr.classList.add('kt-hot-row');
        // 行内也补一个角标
        if (!tr.querySelector('.kt-hotbadge')) {
          var nm = tr.querySelector('.name, .cn, td');
          if (nm) {
            var b = document.createElement('span');
            b.className = 'kt-hotbadge';
            b.textContent = '调课';
            nm.appendChild(b);
          }
        }
      } else if (tr.classList.contains('kt-hot-row')) {
        tr.classList.remove('kt-hot-row');
      }
    }
  }

  mark();
  markRows();
  // 降频：iPhone 7 上 300ms 扫全表会卡死，改成 2 秒一次，
  // 并且去掉 MutationObserver（每次 DOM 变动都触发，滚动时狂跑）
  setInterval(function(){ mark(); markRows(); }, 2000);
  // 自检标记，方便在 Elements 里确认脚本跑过了
  document.documentElement.setAttribute('data-kt-hot', 'on');
  try { console.log('[KT-HOTWEEK] 已启动'); } catch (e) {}
})();
</script>

<style>
/* ===== 全站页脚状态条 ===== */
#ktFoot{
  position:fixed; left:0; right:0; bottom:0; z-index:35;
  padding:6px 12px calc(6px + env(safe-area-inset-bottom, 0px));
  text-align:center; font-size:10.5px; line-height:1.5;
  color:#7b8896; font-weight:600; white-space:nowrap;
  overflow:hidden; text-overflow:ellipsis;
  font-variant-numeric:tabular-nums;
  background:rgba(238,244,249,.95);
  -webkit-backdrop-filter:blur(10px); backdrop-filter:blur(10px);
  border-top:1px solid rgba(0,0,0,.05);
  pointer-events:none;
}
html[data-theme="dark"] #ktFoot{
  color:#6b7c8e; background:rgba(12,18,26,.94);
  border-top-color:rgba(255,255,255,.06);
}
html[data-theme="dark"] #ktFoot{
  background:linear-gradient(to top, rgba(10,16,24,.92), rgba(10,16,24,0));
}
/* 给页面底部留出空间，别让内容被页脚挡住 */
body{ padding-bottom:78px; }
#ktFoot .r{ display:block; }
#ktFoot b{ font-weight:750; color:#6d7c8d; }
html[data-theme="dark"] #ktFoot{ color:#6b7c8e; }
html[data-theme="dark"] #ktFoot b{ color:#8ea3b8; }
</style>
<style>
/* ===== 最底部：IPv6 支持声明 ===== */
#ktV6{
  position:fixed; left:0; right:0; bottom:0; z-index:36;
  padding:5px 12px calc(5px + env(safe-area-inset-bottom, 0px));
  display:flex; align-items:center; justify-content:center;
  gap:6px; flex-wrap:nowrap;
  font-size:10px; line-height:1.35; font-weight:600;
  color:#8593a3; white-space:nowrap; overflow:hidden;
  background:rgba(238,244,249,.92);
  -webkit-backdrop-filter:blur(10px); backdrop-filter:blur(10px);
  border-top:1px solid rgba(0,0,0,.05);
  pointer-events:none;
}
html[data-theme="dark"] #ktV6{
  color:#63758a; background:rgba(12,18,26,.92);
  border-top-color:rgba(255,255,255,.05);
}
#ktV6 b{ font-weight:750; color:#6d7c8d; }
html[data-theme="dark"] #ktV6 b{ color:#8ea3b8; }

/* 蓝色胶囊 */
#ktV6 .v6{
  display:inline-flex; align-items:center; justify-content:center;
  padding:1.5px 8px; border-radius:99px;
  font-size:9.5px; font-weight:850; letter-spacing:.04em;
  color:#fff;
  background:linear-gradient(180deg,#4aa8ff,#1e6fd9);
  box-shadow:
    0 0 7px rgba(70,150,255,.55),
    0 0 16px rgba(70,150,255,.28),
    inset 0 1px 0 rgba(255,255,255,.45);
}
html[data-theme="dark"] #ktV6 .v6{
  background:linear-gradient(180deg,#5cb4ff,#2b7fff);
  box-shadow:
    0 0 9px rgba(90,170,255,.7),
    0 0 20px rgba(90,170,255,.4),
    inset 0 1px 0 rgba(255,255,255,.4);
}

/* 三条栏一起上移，别互相压 */
#ktFoot{ bottom:calc(24px + env(safe-area-inset-bottom, 0px)) !important; }
#ktCompat{ bottom:calc(52px + env(safe-area-inset-bottom, 0px)) !important; }

@media (max-width: 520px){
  #ktV6{ font-size:9px; }
  #ktV6 .v6{ font-size:9px; padding:1px 7px; }
}
</style>

<div id="ktV6" aria-hidden="true">
  <span><b>PaperCloud</b> 支持</span>
  <span class="v6">IPv6</span>
</div>

<style>
/* ===== 全站环境检测条（页脚状态条之上） ===== */
#ktCompat{
  position:fixed; left:0; right:0; z-index:34;
  bottom:calc(28px + env(safe-area-inset-bottom, 0px));
  padding:5px 12px;
  display:flex; align-items:center; justify-content:center;
  gap:8px; flex-wrap:nowrap;
  font-size:10px; line-height:1.4; font-weight:650;
  white-space:nowrap; overflow:hidden;
  background:transparent;
  border-top:0;
  -webkit-backdrop-filter:none; backdrop-filter:none;
  pointer-events:none;
  font-variant-numeric:tabular-nums;
  color:#8593a3;
}
html[data-theme="dark"] #ktCompat{ color:#7d8fa3; }

/* ---------- 状态标签：三色底 + 发光 ---------- */
#ktCompat .badge{
  flex:none;
  display:inline-flex; align-items:center; justify-content:center;
  min-width:58px; padding:2px 10px;
  border-radius:99px;
  font-size:9.5px; font-weight:850; letter-spacing:.03em;
  color:#fff;
  transition: background-color .5s ease, box-shadow .5s ease;
}
/* 完美：绿 */
#ktCompat.lv-perfect .badge{
  background:linear-gradient(180deg,#2fd07a,#12a05a);
  box-shadow:0 0 8px rgba(24,190,105,.65),
             0 0 18px rgba(24,190,105,.35),
             inset 0 1px 0 rgba(255,255,255,.45);
}
/* 兼容：琥珀 */
#ktCompat.lv-compat .badge{
  background:linear-gradient(180deg,#ffc44d,#d99400);
  color:#4a3000;
  box-shadow:0 0 8px rgba(250,180,20,.65),
             0 0 18px rgba(250,180,20,.35),
             inset 0 1px 0 rgba(255,255,255,.55);
}
/* 不支持：红 */
#ktCompat.lv-bad .badge{
  background:linear-gradient(180deg,#ff6b70,#d92c33);
  box-shadow:0 0 8px rgba(255,80,85,.65),
             0 0 18px rgba(255,80,85,.35),
             inset 0 1px 0 rgba(255,255,255,.4);
}
/* 未检测 */
#ktCompat.lv-none .badge{
  background:rgba(140,155,170,.35);
  box-shadow:none;
}

/* 深色下发光更明显一点 */
html[data-theme="dark"] #ktCompat.lv-perfect .badge{
  box-shadow:0 0 10px rgba(46,210,127,.75),
             0 0 24px rgba(46,210,127,.45),
             inset 0 1px 0 rgba(255,255,255,.4);
}
html[data-theme="dark"] #ktCompat.lv-compat .badge{
  box-shadow:0 0 10px rgba(255,196,77,.75),
             0 0 24px rgba(255,196,77,.45),
             inset 0 1px 0 rgba(255,255,255,.5);
}
html[data-theme="dark"] #ktCompat.lv-bad .badge{
  box-shadow:0 0 10px rgba(255,107,112,.75),
             0 0 24px rgba(255,107,112,.45),
             inset 0 1px 0 rgba(255,255,255,.35);
}

#ktCompat .dev{ opacity:.92; }
#ktCompat .sep{ opacity:.3; }

@media (max-width: 520px){
  #ktCompat{ font-size:9px; gap:6px; }
  #ktCompat .badge{ min-width:52px; padding:1.5px 8px; font-size:8.5px; }
}
</style>

<div id="ktCompat" class="lv-none" aria-hidden="true">
  <span class="badge" id="ktcBadge">检测中</span>
  <span class="dev" id="ktcDev">正在识别设备…</span>
</div>

<script>
/* KT-COMPAT：品牌 + 系统版本 + 内核 + 三色状态 */
(function(){
  if (window.__ktCompat) return;
  window.__ktCompat = 1;

  var ANDROID_BRANDS = [
    [/xiaomi|redmi|poco|mi \d|mi mix|2[2-3][0-9]{4,}/i, 'Xiaomi'],
    [/sm-|samsung|galaxy/i, 'Samsung'],
    [/huawei|ane-|els-|lya-|hmw-/i, 'HUAWEI'],
    [/honor|hih-|bvl-/i, 'HONOR'],
    [/oppo|pe[rc][mt]\d|p[a-z]{2}m\d/i, 'OPPO'],
    [/vivo|v2\d{3}|pd\d{4}/i, 'vivo'],
    [/oneplus|pjd\d|hd\d{4}|in2\d{3}/i, 'OnePlus'],
    [/realme|rmx\d/i, 'realme'],
    [/meizu|m[zs]\d/i, 'Meizu'],
    [/nubia|nx\d{3}/i, 'nubia'],
    [/zte|axon/i, 'ZTE']
  ];

  function androidBrand(model) {
    for (var i = 0; i < ANDROID_BRANDS.length; i++) {
      if (ANDROID_BRANDS[i][0].test(model || '')) return ANDROID_BRANDS[i][1];
    }
    return 'Android';
  }

  function boot() {
    var bar = document.getElementById('ktCompat');
    var dev = document.getElementById('ktcDev');
    var bdg = document.getElementById('ktcBadge');
    if (!bar || !dev || !bdg) return;

    var ua = navigator.userAgent || '';
    var m, brand = '', os = '', eng = '';

    if ((m = ua.match(/iPhone OS (\d+)[_.](\d+)/))) {
      brand = 'iPhone'; os = 'iOS ' + m[1] + '.' + m[2]; eng = 'WebKit';
    } else if (/iPad/.test(ua) && (m = ua.match(/OS (\d+)[_.](\d+)/))) {
      brand = 'iPad'; os = 'iPadOS ' + m[1] + '.' + m[2]; eng = 'WebKit';
    } else if ((m = ua.match(/Android (\d+)(?:\.(\d+))?/))) {
      var mm = ua.match(/;\s*([^;()]{2,30}?)\s+Build/);
      brand = androidBrand(mm ? mm[1] : '');
      os = 'Android ' + m[1] + (m[2] ? '.' + m[2] : '');
    } else if (/Windows NT 10\.0/.test(ua)) {
      brand = 'Windows'; os = 'Windows 10/11';
    } else if (/Windows NT 6\.3/.test(ua)) {
      brand = 'Windows'; os = 'Windows 8.1';
    } else if (/Windows NT 6\.1/.test(ua)) {
      brand = 'Windows'; os = 'Windows 7';
    } else if ((m = ua.match(/Mac OS X (\d+)[_.](\d+)/))) {
      brand = 'Mac'; os = 'macOS ' + m[1] + '.' + m[2];
    } else if (/Linux/.test(ua)) {
      brand = 'Linux'; os = 'Linux';
    } else {
      brand = '未知设备'; os = '';
    }

    var br = '', bv = '';
    if ((m = ua.match(/MicroMessenger\/([\d.]+)/))) { br = '微信'; bv = m[1].split('.')[0]; }
    else if ((m = ua.match(/Edg(?:iOS|A)?\/(\d+)/))) { br = 'Edge'; bv = m[1]; }
    else if ((m = ua.match(/CriOS\/(\d+)/))) { br = 'Chrome'; bv = m[1]; }
    else if ((m = ua.match(/FxiOS\/(\d+)/))) { br = 'Firefox'; bv = m[1]; }
    else if ((m = ua.match(/Chrome\/(\d+)/))) { br = 'Chrome'; bv = m[1]; }
    else if ((m = ua.match(/Firefox\/(\d+)/))) { br = 'Firefox'; bv = m[1]; }
    else if ((m = ua.match(/Version\/(\d+)[\d.]*.*Safari/))) { br = 'Safari'; bv = m[1]; }
    else if ((m = ua.match(/Safari\/(\d+)/))) { br = 'Safari'; bv = m[1]; }

    if (/Firefox\/|FxiOS\//.test(ua)) {
      eng = 'Gecko';
    } else if (/Chrome\/|CriOS\/|Edg\/|EdgA\/|EdgiOS\//.test(ua)) {
      eng = /iPhone|iPad|iPod/.test(ua) ? 'WebKit' : 'Blink';
    } else if (/Safari\/|AppleWebKit\//.test(ua)) {
      eng = 'WebKit';
    }

    function sup(prop, val) {
      try { return CSS.supports(prop, val); } catch (e) { return false; }
    }
    var colorMix = sup('color', 'color-mix(in srgb, red, blue)');
    var backdrop = sup('backdrop-filter', 'blur(1px)') ||
                   sup('-webkit-backdrop-filter', 'blur(1px)');
    var grid = sup('display', 'grid');

    var lv, label;
    if (colorMix && backdrop) { lv = 'perfect'; label = '完美显示'; }
    else if (backdrop || grid) { lv = 'compat'; label = '兼容显示'; }
    else { lv = 'bad'; label = '不支持'; }

    var txt = [];
    if (brand) txt.push(brand);
    if (os) txt.push(os);
    if (eng) txt.push(eng);
    dev.textContent = txt.join(' · ');
    dev.title = (br && bv ? br + ' ' + bv + ' · ' : '') +
                '屏幕 ' + screen.width + '×' + screen.height +
                ' @' + (window.devicePixelRatio || 1) + 'x';

    bdg.textContent = label;
    bar.className = 'lv-' + lv;
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else { boot(); }
  window.addEventListener('load', boot);
})();
</script>

<div id="ktFoot"></div>
<script>
/* KT-FOOT: 全站页脚状态条 */
(function(){
  var t0 = (window.performance && performance.now) ? performance.now() : 0;
  function fmtMs(ms){
    if (!ms && ms !== 0) return '—';
    if (ms < 1000) return (ms/1000).toFixed(4) + 's';
    return (ms/1000).toFixed(2) + 's';
  }
  function render(){
    var el = document.getElementById('ktFoot');
    if (!el) return;
    var now = new Date();
    var hh = String(now.getHours()).padStart(2,'0');
    var mm = String(now.getMinutes()).padStart(2,'0');
    var loaded = (window.performance && performance.timing && performance.timing.loadEventEnd
                  && performance.timing.navigationStart)
                 ? (performance.timing.loadEventEnd - performance.timing.navigationStart)
                 : (t0 ? performance.now() : 0);
    var reqs = (window.performance && performance.getEntriesByType)
               ? performance.getEntriesByType('resource').length : 0;
    // 内存：Chrome/Edge 有 performance.memory；Safari 没有，
    // 用「本次加载传输的字节数」当近似值，保证任何平台都有数看。
    var mem;
    var heap = (window.performance && performance.memory)
               ? performance.memory.usedJSHeapSize : 0;
    // 有些浏览器/环境里 usedJSHeapSize 是 0，不能当成真的 0MB
    if (heap > 16384) {
      mem = (heap / 1048576).toFixed(2) + 'MB';
    } else {
      var bytes = 0;
      try {
        var rs = performance.getEntriesByType('resource') || [];
        for (var i = 0; i < rs.length; i++) {
          bytes += (rs[i].decodedBodySize || rs[i].transferSize || 0);
        }
      } catch (e) {}
      try {
        var nav = performance.getEntriesByType('navigation')[0];
        if (nav) bytes += (nav.decodedBodySize || nav.transferSize || 0);
      } catch (e2) {}
      if (!bytes) {
        /* 拿不到资源大小时，用 DOM 的 UTF-8 字节数兜底（中文按 3 字节估） */
        var html = document.documentElement.outerHTML || '';
        var n = 0;
        for (var q = 0; q < html.length; q++) {
          var cp = html.charCodeAt(q);
          n += cp < 0x80 ? 1 : (cp < 0x800 ? 2 : 3);
        }
        bytes = n;
      }
      mem = (bytes / 1048576).toFixed(2) + 'MB';
    }
    /* 体积：本次实际传输的字节数（各平台都真实） */
    var sizeTxt = mem;
    var sizeTip = '本次加载实际传输的字节数';

    /* 内存：Chrome/Edge 有真实堆；Safari 没有 API，用 DOM 规模估算 */
    var real = heap > 16384;
    var memTxt, memTip;
    if (real) {
      memTxt = (heap / 1048576).toFixed(2) + 'MB';
      memTip = 'JavaScript 堆实际占用';
    } else {
      var nodes = 0;
      try { nodes = document.getElementsByTagName('*').length; } catch (e) {}
      var bytes2 = 0;
      try {
        var rs2 = performance.getEntriesByType('resource') || [];
        for (var j2 = 0; j2 < rs2.length; j2++) {
          bytes2 += (rs2[j2].decodedBodySize || rs2[j2].transferSize || 0);
        }
      } catch (e2) {}
      /* 每个节点约 2KB（样式对象 + 监听器 + 文本节点），再加资源体积 */
      var est = nodes * 2048 + bytes2 * 2;
      if (!est) est = (document.documentElement.outerHTML || '').length * 2;
      memTxt = '≈' + (est / 1048576).toFixed(2) + 'MB';
      memTip = 'iOS 不提供真实堆内存，按 ' + nodes + ' 个 DOM 节点与资源体积估算';
    }

    el.innerHTML =
      '访问 <b>' + hh + ':' + mm + '</b>' +
      ' &middot; 加载 <b>' + fmtMs(loaded) + '</b>' +
      ' &middot; 查询 <b>' + reqs + '</b>' +
      ' &middot; 体积 <b title="' + sizeTip + '">' + sizeTxt + '</b>' +
      ' &middot; 内存 <b title="' + memTip + '">' + memTxt + '</b>';
  }
  function boot(){
    render();
    // 页面完全加载后再算一次精确值
    if (document.readyState === 'complete') { render(); }
    else window.addEventListener('load', function(){ setTimeout(render, 30); });
    setInterval(render, 30000);   // 每分钟校正一次时间
  }
  if (document.readyState === 'loading')
    document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
</script>

<style>
/* ================= 天气卡片 · 液态玻璃 ================= */
#ktWx{
  --wx-glass-a: rgba(255,255,255,.62);
  --wx-glass-b: rgba(255,255,255,.30);
  --wx-line: rgba(255,255,255,.75);
  --wx-hi: rgba(255,255,255,.9);
  --wx-ink: #1a2c3e;
  --wx-dim: rgba(26,44,62,.55);
  display:flex; gap:12px; margin:0 0 14px;
  font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
}
html[data-theme="dark"] #ktWx{
  --wx-glass-a: rgba(38,46,58,.60);
  --wx-glass-b: rgba(24,30,40,.42);
  --wx-line: rgba(255,255,255,.13);
  --wx-hi: rgba(255,255,255,.20);
  --wx-ink: #e8f0f8;
  --wx-dim: rgba(200,215,230,.55);
}
#ktWx .wx-glass{
  position:relative; border-radius:22px; overflow:hidden;
  background:linear-gradient(160deg, var(--wx-glass-a), var(--wx-glass-b));
  border:1px solid var(--wx-line);
  -webkit-backdrop-filter:blur(28px) saturate(180%);
  backdrop-filter:blur(28px) saturate(180%);
  box-shadow:
    inset 0 1px 0 var(--wx-hi),
    inset 0 -1px 0 rgba(255,255,255,.06),
    0 10px 34px rgba(20,50,85,.14);
  color:var(--wx-ink);
}
#ktWx .wx-glass::after{           /* 高光扫过，液态感 */
  content:""; position:absolute; inset:0; pointer-events:none;
  background:linear-gradient(115deg, rgba(255,255,255,.42) 0%,
             rgba(255,255,255,.06) 26%, transparent 48%, transparent 100%);
  mix-blend-mode:screen;
}
html[data-theme="dark"] #ktWx .wx-glass::after{
  background:linear-gradient(115deg, rgba(255,255,255,.14) 0%,
             rgba(255,255,255,.03) 30%, transparent 55%);
}

/* 大板块 */
#ktWxBig{ flex:1 1 auto; min-width:0; padding:16px 18px; display:flex; gap:18px; align-items:center; }
#ktWxBig .ico{ font-size:44px; line-height:1; flex:none; filter:drop-shadow(0 3px 8px rgba(30,60,90,.18)); }
#ktWxBig .main{ flex:none; }
#ktWxBig .t{ font-size:40px; font-weight:300; letter-spacing:-2px; line-height:1; }
#ktWxBig .t sup{ font-size:16px; font-weight:500; vertical-align:top; letter-spacing:0; }
#ktWxBig .c{ font-size:13.5px; font-weight:700; margin-top:3px; }
#ktWxBig .r{ font-size:11.5px; color:var(--wx-dim); margin-top:2px; font-weight:600; }
#ktWxBig .fc{ display:flex; gap:6px; flex:1 1 auto; min-width:0; overflow:hidden; }
#ktWxBig .fc .d{
  flex:1 1 0; min-width:0; text-align:center; padding:7px 2px;
  border-radius:13px; background:rgba(255,255,255,.20);
  border:1px solid rgba(255,255,255,.30);
}
html[data-theme="dark"] #ktWxBig .fc .d{
  background:rgba(255,255,255,.06); border-color:rgba(255,255,255,.08);
}
#ktWxBig .fc .w{ font-size:10px; color:var(--wx-dim); font-weight:700; }
#ktWxBig .fc .i{ font-size:16px; margin:2px 0; }
#ktWxBig .fc .h{ font-size:11px; font-weight:800; }
#ktWxBig .fc .l{ font-size:10px; color:var(--wx-dim); font-weight:600; }

/* 小板块 */
#ktWxSmall{ flex:0 0 218px; display:grid; grid-template-columns:1fr 1fr; gap:8px; }
#ktWxSmall .s{
  padding:10px 11px; border-radius:16px; cursor:pointer;
  background:linear-gradient(160deg, var(--wx-glass-a), var(--wx-glass-b));
  border:1px solid var(--wx-line);
  -webkit-backdrop-filter:blur(24px) saturate(170%);
  backdrop-filter:blur(24px) saturate(170%);
  box-shadow:inset 0 1px 0 var(--wx-hi), 0 6px 20px rgba(20,50,85,.10);
  color:var(--wx-ink);
  transition:transform .18s cubic-bezier(.3,1.2,.4,1), box-shadow .2s;
  position:relative; overflow:hidden;
}
#ktWxSmall .s:active{ transform:scale(.96); }
#ktWxSmall .s .k{ font-size:10px; color:var(--wx-dim); font-weight:700; }
#ktWxSmall .s .v{ font-size:16px; font-weight:800; letter-spacing:-.5px; margin-top:2px; }
#ktWxSmall .s .u{ font-size:9.5px; color:var(--wx-dim); font-weight:600; margin-left:2px; }
#ktWxSmall .s .x{
  max-height:0; overflow:hidden; opacity:0;
  font-size:10.5px; color:var(--wx-dim); font-weight:600;
  transition:max-height .26s ease, opacity .2s, margin-top .2s;
}
#ktWxSmall .s.on{ transform:translateY(-2px); box-shadow:inset 0 1px 0 var(--wx-hi), 0 12px 30px rgba(20,50,85,.20); }
#ktWxSmall .s.on .x{ max-height:52px; opacity:1; margin-top:5px; }

@media (max-width:900px){
  #ktWx{ flex-direction:column; }
  #ktWxSmall{ flex:1 1 auto; grid-template-columns:repeat(4,1fr); }
  #ktWxBig{ flex-wrap:wrap; }
  #ktWxBig .fc{ order:3; flex-basis:100%; margin-top:8px; }
}
@media (prefers-reduced-motion: reduce){
  #ktWxSmall .s{ transition:none; }
}
</style>

<script>
/* KT-WEATHER: 课表页注入天气卡片 */
(function(){
  var ICON = {
    "晴":"","少云":"","晴间多云":"","多云":"","阴":"",
    "阵雨":"","小雨":"","中雨":"","大雨":"","暴雨":"",
    "雷阵雨":"","小雪":"","中雪":"","大雪":"","雾":"","霾":"","浮尘":"","沙尘":""
  };
  function icon(w){
    if (!w) return "";
    for (var k in ICON) { if (w.indexOf(k) >= 0) return ICON[k]; }
    return "";
  }
  var DOW = ["周日","周一","周二","周三","周四","周五","周六"];

  function el(tag, cls, html){
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  }

  function build(d){
    var wrap = el("div", "", "");
    wrap.id = "ktWx";

    // 大板块
    var big = el("div", "wx-glass", "");
    big.id = "ktWxBig";
    var fc = (d.casts || []).slice(0, 5).map(function(c){
      var dt = new Date((c.date || "").replace(/-/g, "/"));
      var lbl = isNaN(dt) ? "" : (DOW[dt.getDay()] === DOW[new Date().getDay()] ? "今天" : DOW[dt.getDay()]);
      return '<div class="d"><div class="w">' + lbl + '</div>' +
             '<div class="i">' + icon(c.day) + '</div>' +
             '<div class="h">' + (c.high || "-") + '°</div>' +
             '<div class="l">' + (c.low || "-") + '°</div></div>';
    }).join("");

    big.innerHTML =
      '<div class="ico">' + icon(d.weather) + '</div>' +
      '<div class="main">' +
        '<div class="t">' + (d.temp || "-") + '<sup>°C</sup></div>' +
        '<div class="c">' + (d.weather || "") + '　' + (d.city || "") + '</div>' +
        '<div class="r">' + (d.casts && d.casts[0] ? ('高 ' + d.casts[0].high + '° 低 ' + d.casts[0].low + '°') : '') + '</div>' +
      '</div>' +
      '<div class="fc">' + fc + '</div>';

    // 小板块
    var sm = el("div", "", "");
    sm.id = "ktWxSmall";
    // 只放有数据的格子 —— 拿不到的就不显示，不留空白占位
    var tiles = [];
    if (d.humidity && d.humidity !== "-") {
      tiles.push({ k: "湿度", v: d.humidity, u: "%", x: "相对湿度，越高越闷" });
    }
    if (d.windpower && d.windpower !== "-") {
      tiles.push({ k: "风力", v: d.windpower, u: "级",
                   x: "风向：" + (d.winddir || "—") });
    }
    if (d.temp && d.casts && d.casts[0]) {
      var hi = parseInt(d.casts[0].high, 10), lo = parseInt(d.casts[0].low, 10);
      if (!isNaN(hi) && !isNaN(lo)) {
        tiles.push({ k: "温差", v: (hi - lo), u: "°", x: "白天与夜间温差" });
      }
    }
    if (d.reporttime) {
      tiles.push({ k: "更新", v: (d.reporttime || "").slice(11, 16), u: "",
                   x: (d.reporttime || "").slice(0, 10) });
    }
    tiles.forEach(function(t){
      var e = el("div", "s",
        '<div class="k">' + t.k + '</div>' +
        '<div class="v">' + t.v + (t.u ? '<span class="u">' + t.u + '</span>' : '') + '</div>' +
        '<div class="x">' + t.x + '</div>');
      e.onclick = function(){ e.classList.toggle("on"); };
      sm.appendChild(e);
    });

    // 格子少的时候让它们占满整行，不留空心
    if (tiles.length <= 2) sm.style.gridTemplateColumns = '1fr';
    else if (tiles.length === 3) { sm.style.gridTemplateColumns = '1fr 1fr'; }
    if (tiles.length === 0) sm.style.display = 'none';

    wrap.appendChild(big);
    wrap.appendChild(sm);
    return wrap;
  }

  /* 找「课表区域的上一层」：.gridwrap 在滚动容器外面，
     插在它前面才是真正「在课表上面」。 */
  function anchor(){
    return document.querySelector(".gridwrap") ||
           document.getElementById("grid") ||
           document.querySelector(".grid") ||
           document.querySelector(".view.on .panel") ||
           document.querySelector(".wrap");
  }
  function place(node){
    var a = anchor();
    if (!a || !a.parentNode) return false;
    a.parentNode.insertBefore(node, a);
    return true;
  }
  function mount(){
    if (document.getElementById("ktWx")) return true;
    return place(build({}));              // 先占位
  }

  function load(){
    fetch("/api/weather").then(function(r){ return r.json(); }).then(function(res){
      if (!res || !res.ok) return;
      var old = document.getElementById("ktWx");
      var fresh = build(res.data);
      if (old) old.parentNode.replaceChild(fresh, old);
      else place(fresh);
    }).catch(function(){});
  }

  function fail(msg){
    document.documentElement.setAttribute("data-kt-wx", "err:" + msg);
    try { console.error("[KT-WEATHER]", msg); } catch(e){}
    var d = document.createElement("div");
    d.style.cssText = "padding:10px 14px;margin:0 0 12px;border-radius:12px;" +
      "background:#ffe2e6;color:#b3182c;font:600 12px/1.6 sans-serif;";
    d.textContent = "天气模块出错：" + msg;
    var a = anchor();
    if (a && a.parentNode) a.parentNode.insertBefore(d, a);
  }

  function boot(){
    try {
      document.documentElement.setAttribute("data-kt-wx", "boot");
      if (!mount()) fail("找不到 .gridwrap");
      else {
        document.documentElement.setAttribute("data-kt-wx", "mounted");
    // 课表是异步渲染的，等它出来再挂
    var tries = 0;
    var t = setInterval(function(){
      if (!document.getElementById("ktWx") && mount()) { load(); }
      if (++tries > 40) clearInterval(t);
    }, 250);
  }
  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
</script>
<script>
/* KT-PASSK-GLOBAL：地址栏有 ?k= 就自动带到站内所有链接，
   首页 / 课表 / 班务 / 工具 页的「返回」「入口」都不会再要口令。 */
(function () {
  var k = new URLSearchParams(location.search).get('k');
  if (!k) return;
  function fix() {
    var as = document.querySelectorAll('a[href]');
    for (var i = 0; i < as.length; i++) {
      var a = as[i], href = a.getAttribute('href') || '';
      if (!href || href.charAt(0) === '#' || href.indexOf('k=') >= 0) continue;
      if (/^(https?:)?\/\//.test(href) || href.indexOf('mailto:') === 0) continue;
      a.setAttribute('href', href + (href.indexOf('?') >= 0 ? '&' : '?') +
                     'k=' + encodeURIComponent(k));
    }
  }
  if (document.readyState === 'loading')
    document.addEventListener('DOMContentLoaded', fix);
  else fix();
  // 有些按钮是 JS 跳转，这里兜一层
  document.addEventListener('click', function (e) {
    var a = e.target && e.target.closest ? e.target.closest('a[href]') : null;
    if (!a) return;
    var href = a.getAttribute('href') || '';
    if (href && href.charAt(0) === '/' && href.indexOf('k=') < 0) {
      a.setAttribute('href', href + (href.indexOf('?') >= 0 ? '&' : '?') +
                     'k=' + encodeURIComponent(k));
    }
  }, true);
})();
</script>
<script>
/* KT-FP：设备指纹写进 cookie，同一出口也能分开统计 */
(function () {
  try { if (document.cookie.indexOf('kt_fp=') >= 0) return; } catch (e) {}
  try {
    var p = [
      navigator.userAgent || '',
      screen.width + 'x' + screen.height,
      screen.colorDepth || 0,
      navigator.language || '',
      (new Date()).getTimezoneOffset(),
      navigator.hardwareConcurrency || 0,
      navigator.platform || ''
    ].join('|');
    var h = 2166136261;
    for (var i = 0; i < p.length; i++) {
      h ^= p.charCodeAt(i);
      h = (h * 16777619) >>> 0;
    }
    var fp = ('00000000' + h.toString(16)).slice(-8);
    document.cookie = 'kt_fp=' + fp + '; path=/; max-age=31536000; SameSite=Lax';
  } catch (e) {}
})();
</script>
<script>
/* KT-HEARTBEAT：页面开着就每 30 秒报一次，关掉就停 */
(function () {
  function beat() {
    try {
      var q = location.search.indexOf('k=') >= 0 ? location.search : '';
      var u = '/api/ping' + q + (q ? '&' : '?') + 't=' + Date.now();
      if (window.fetch) {
        /* fetch 不会在标签页上留下加载动画 */
        fetch(u, { method: 'POST', keepalive: true, cache: 'no-store' })
          .catch(function () {});
      } else {
        var x = new XMLHttpRequest();
        x.open('POST', u);
        x.send();
      }
    } catch (e) {}
  }
  beat();
  setInterval(beat, 30000);
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) beat();
  });
})();
</script>
<style id="ktLoveCss">
/* 点击反馈气泡：直接出现 → 上浮渐隐 */
.kt-love{
  position:fixed; z-index:2147483002; pointer-events:none;
  font:900 15px/1 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
  letter-spacing:.01em;
  /* 每次点击由 JS 指定颜色 */
  color:var(--ktc, #ff4d6d);
  text-shadow:0 1px 2px rgba(255,255,255,.85);
  filter:drop-shadow(0 2px 9px var(--ktc, #ff4d6d));
  white-space:nowrap;
  transform:translate(-50%,-50%);
  animation:ktLoveUp .72s cubic-bezier(.22,.6,.36,1) forwards;
  will-change:transform,opacity;
}
html[data-theme="dark"] .kt-love{
  color:var(--ktd, #ff7d97);
  text-shadow:0 1px 2px rgba(0,0,0,.5);
  filter:drop-shadow(0 2px 11px var(--ktd, #ff7d97));
}
@keyframes ktLoveUp{
  0%   { opacity:1; transform:translate(-50%,-50%)   scale(.92); }
  14%  { opacity:1; transform:translate(-50%,-62%)   scale(1.08); }
  100% { opacity:0; transform:translate(-50%,-165%)  scale(1); }
}
@media (prefers-reduced-motion: reduce){
  .kt-love{ animation-duration:.45s; }
}
</style>

<script>
/* KT-LOVE：每次点击按顺序显示一个核心价值观词 */
(function () {
  if (window.__ktLove) return;
  window.__ktLove = 1;

  var WORDS = ['富强','民主','文明','和谐','自由','平等',
               '公正','法治','爱国','敬业','诚信','友善'];
  var KEY = 'kt_love_i';

  /* 浅色 / 深色各一套配色，按点击顺序轮换 */
  var COLORS = [
    ['#ff4d6d', '#ff8fa5'],   // 玫红
    ['#e8590c', '#ffab70'],   // 橙
    ['#f08c00', '#ffd43b'],   // 琥珀
    ['#2f9e44', '#69db7c'],   // 绿
    ['#0c8599', '#3bc9db'],   // 青
    ['#1c7ed6', '#74c0fc'],   // 蓝
    ['#5f3dc4', '#9775fa'],   // 紫
    ['#c2255c', '#f06595']    // 洋红
  ];

  function nextWord() {
    var i = 0;
    try { i = parseInt(localStorage.getItem(KEY) || '0', 10) || 0; } catch (e) {}
    if (i < 0 || i >= WORDS.length) i = 0;
    try { localStorage.setItem(KEY, String((i + 1) % WORDS.length)); } catch (e) {}
    return { word: WORDS[i], color: COLORS[i % COLORS.length] };
  }

  /* 全站有 85% 缩放，固定定位元素会被再缩放一次，坐标要除掉 */
  function zoomOf() {
    try {
      var z = parseFloat(getComputedStyle(document.documentElement)
                .getPropertyValue('--kt-zoom'));
      return (z > 0 && z < 3) ? z : 1;
    } catch (e) { return 1; }
  }

  function show(x, y, info) {
    var z = zoomOf();
    var el = document.createElement('div');
    el.className = 'kt-love';
    el.textContent = '💗' + info.word + '💗';
    el.style.setProperty('--ktc', info.color[0]);
    el.style.setProperty('--ktd', info.color[1]);
    el.style.left = (x / z) + 'px';
    el.style.top  = (y / z) + 'px';
    document.body.appendChild(el);
    setTimeout(function () {
      if (el.parentNode) el.parentNode.removeChild(el);
    }, 760);
  }

  function onDown(e) {
    /* 只响应鼠标左键；触屏/手写笔都算 */
    if (e.pointerType === 'mouse' && e.button !== 0) return;
    show(e.clientX, e.clientY, nextWord());
  }

  if (window.PointerEvent) {
    document.addEventListener('pointerdown', onDown, { passive: true });
  } else {
    document.addEventListener('mousedown', function (e) {
      if (e.button === 0) show(e.clientX, e.clientY, nextWord());
    }, true);
    document.addEventListener('touchstart', function (e) {
      var t = e.touches && e.touches[0];
      if (t) show(t.clientX, t.clientY, nextWord());
    }, { passive: true });
  }
})();
</script>
<style id="ktFooterFlow">
/* KT-FOOTER-FLOW
   三条栏是页面最后一块内容（普通文档流）：
   不悬浮、不遮挡、页面底部不留空白。 */
#ktV6, #ktFoot, #ktCompat{
  position: static !important;
  left: auto !important; right: auto !important; bottom: auto !important;
  display: flex !important;
  justify-content: center !important;
  align-items: center !important;
  text-align: center !important;
  width: 100% !important;
  max-width: none !important;
  margin: 0 !important;
  z-index: auto !important;
  border-radius: 0 !important;
  flex: 0 0 auto !important;
  align-self: stretch !important;
  box-sizing: border-box !important;
}
#ktFoot{ border-top: 1px solid rgba(0,0,0,.05); }

/* 这些页面 body 是 flex 居中，必须改成竖排，否则页脚会被摆到卡片右边 */
/* 主页 .phone 保持它自己的布局（上一版），只修登录页这种 .box/.card */
body:has(> .box),
body:has(> .card){
  flex-direction: column !important;
  align-items: center !important;
  justify-content: center !important;
}
body{ padding-bottom: 0 !important; }
</style>

<script>
/* KT-BARS-ORDER：把 IPv6 那行放到三条页脚的最后 */
(function () {
  function go() {
    var v6 = document.getElementById('ktV6');
    if (!v6 || !v6.parentNode) return;
    var p = v6.parentNode;
    if (p.lastElementChild !== v6) p.appendChild(v6);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', go);
  } else { go(); }
  setTimeout(go, 500);
})();
</script>

<style id="ktBarsInCard">
/* KT-BARS-IN-CARD：主页三条页脚放进卡片内部最底部 */
.phone.kt-has-bars{
  overflow: hidden !important;      /* 跟随卡片圆角裁切 */
  padding-bottom: 12px !important;  /* 三条栏下面留一点，露出卡片圆角 */
}
.phone.kt-has-bars > #ktFoot,
.phone.kt-has-bars > #ktCompat,
.phone.kt-has-bars > #ktV6{
  display: flex !important;
  justify-content: center !important;
  align-items: center !important;
  width: 100% !important;
  margin: 0 !important;
  border-radius: 0 !important;
  flex: 0 0 auto !important;
}
</style>

<script>
/* KT-BARS-IN-CARD：只在主页把三条页脚搬进卡片 */
(function () {
  function go() {
    var card = document.querySelector('.phone');
    if (!card) return;
    var moved = false;
    ['ktFoot', 'ktCompat', 'ktV6'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el && el.parentNode !== card) {
        card.appendChild(el);
        moved = true;
      }
    });
    if (moved) card.classList.add('kt-has-bars');
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', go);
  } else { go(); }
  setTimeout(go, 400);
  setTimeout(go, 1200);
  window.addEventListener('load', go);
})();
</script>



<style id="ktMorphCss">
/* ============ KT-MORPH · 按钮收缩成圆 + 转圈 ============ */
a.btn[href]{
  position: relative;
  overflow: hidden;
  transform-origin: center center;
  transition:
    width .30s ease-in-out,
    height .30s ease-in-out,
    min-width .30s ease-in-out,
    max-width .30s ease-in-out,
    border-radius .30s ease-in-out,
    padding-left .30s ease-in-out,
    padding-right .30s ease-in-out;
}
a.btn[href] .kt-lbl{
  display: inline-block;
  transition: opacity .16s ease-out, transform .16s ease-out;
}
a.btn.kt-morph .kt-lbl{
  opacity: 0;
  position: absolute; left: 50%; top: 50%;
  transform: translate(-50%,-50%) scale(.94);
  white-space: nowrap;
  pointer-events: none;
}

a.btn.kt-morph{
  pointer-events: none;
  flex: 0 0 auto !important;
  align-self: center !important;
  margin-left: auto !important;
  margin-right: auto !important;
  padding-left: 0 !important;
  padding-right: 0 !important;
  border-radius: 50% !important;
}

.kt-spin{
  position: absolute; left: 50%; top: 50%;
  width: 18px; height: 18px; margin: -9px 0 0 -9px;
  border-radius: 50%;
  border: 2px solid color-mix(in srgb, currentColor 26%, transparent);
  border-top-color: currentColor;
  opacity: 0;
  animation: ktSpinA .68s linear infinite;
  transition: opacity .16s ease-out;
  pointer-events: none;
}
a.btn.kt-morph .kt-spin{ opacity: 1; }
@keyframes ktSpinA{ to { transform: rotate(360deg); } }

@media (prefers-reduced-motion: reduce){
  a.btn[href]{ transition: none; }
  .kt-spin{ animation-duration: 1.6s; }
}
</style>

<script>
/* KT-MORPH：点击「在线课表 / 班务系统 …」这类按钮时收缩成圆并转圈 */
(function () {
  if (window.__ktMorph) return;
  window.__ktMorph = 1;

  var reduce = false;
  try {
    reduce = window.matchMedia &&
             window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  } catch (e) {}

  function setup() {
    var list = document.querySelectorAll('a.btn[href]');
    Array.prototype.forEach.call(list, function (a) {
      if (a.__ktMorphDone) return;
      a.__ktMorphDone = 1;

      /* 文字单独包一层 */
      if (!a.querySelector('.kt-lbl')) {
        var frag = document.createDocumentFragment();
        var label = document.createElement('span');
        label.className = 'kt-lbl';
        Array.prototype.slice.call(a.childNodes).forEach(function (n) {
          if (n.nodeType === 3) {
            if (n.textContent.trim()) label.appendChild(n);
            else n.parentNode.removeChild(n);
          } else if (n.nodeType === 1 && !n.classList.contains('kt-spin')) {
            label.appendChild(n);
          }
        });
        if (label.textContent.trim()) {
          frag.appendChild(label);
          a.appendChild(frag);
        }
      }
      if (!a.querySelector('.kt-spin')) {
        var ring = document.createElement('span');
        ring.className = 'kt-spin';
        a.appendChild(ring);
      }

      a.addEventListener('click', function (e) {
        var href = a.getAttribute('href') || '';
        if (!href || href.charAt(0) === '#') return;
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button) return;
        if (a.classList.contains('kt-morph')) { e.preventDefault(); return; }

        e.preventDefault();
        if (reduce) { location.href = href; return; }

        var hgt = Math.round(a.offsetHeight);
        var wid = Math.round(a.offsetWidth);

        /* 1) 先把当前宽高写成固定 px，保证有「起始值」可过渡 */
        a.style.width = wid + 'px';
        a.style.minWidth = wid + 'px';
        a.style.maxWidth = wid + 'px';
        a.style.height = hgt + 'px';

        /* 2) 强制一次回流，让上面的值生效 */
        void a.offsetWidth;

        /* 3) 再切到圆形尺寸 —— 浏览器这次一定会插值 */
        a.classList.add('kt-morph');
        setTimeout(function () {
          a.style.width = hgt + 'px';
          a.style.minWidth = hgt + 'px';
          a.style.maxWidth = hgt + 'px';
          a.style.borderRadius = '50%';
          a.style.paddingLeft = '0';
          a.style.paddingRight = '0';
        }, 30);
        /* 调试：URL 带 #morphdemo 时不跳转，方便看动画 */
        if (location.hash !== '#morphdemo') {
          setTimeout(function () { location.href = href; }, 640);
        }
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', setup);
  } else { setup(); }
  setTimeout(setup, 600);

  /* 演示模式：打开 xxx#morphdemo 自动播放一次 */
  if (location.hash === '#morphdemo') {
    setTimeout(function () {
      var a = document.querySelector('a.btn[href]');
      if (a) a.click();
    }, 900);
  }
})();
</script>

<script>window.__KT_BUILD="" + "2026-10-17-ai3";</script>

<style id="ktPolish">
/* ============ KT-IOS-POLISH · 全站视觉对齐 ============
   只调对齐、字重、间距节奏、描边与阴影，不改元素尺寸和布局结构。
   --------------------------------------------------- */
html {
  -webkit-text-size-adjust: 100%;
  text-size-adjust: 100%;
}

body {
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  letter-spacing: -0.006em;
  font-synthesis-weight: none;
  text-rendering: optimizeLegibility;
}

/* ---------- 标题层级：iOS 习惯的紧字距 ---------- */
h1, h2, h3, h4, .bname, .brand h1 {
  letter-spacing: -0.022em;
  font-weight: 700;
}
h1, .brand h1 { letter-spacing: -0.028em; }
h3, h4, h2 { letter-spacing: -0.018em; }

/* 正文里的强调别太重 */
b, strong { font-weight: 650; }

/* ---------- 数字：等宽对齐，表格不抖 ---------- */
.mv, .timecol b, .timecol span, td.mono, .mono,
table, .stat, .num {
  font-variant-numeric: tabular-nums;
  font-feature-settings: "tnum" 1;
}

/* ---------- 图标与文字的光学对齐 ---------- */
.icon-btn, .minibtn, .btn-ghost, button, .tag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.icon-btn, .mi, .btn .ico {
  line-height: 1;
}
.mi { transform: translateY(-0.02em); }
.btn .ico { transform: translateY(-0.01em); }

/* 徽标 / 标签：垂直居中且不吃行高 */
.tag, .pill {
  display: inline-flex;
  align-items: center;
  line-height: 1;
  padding-top: 0.32em;
  padding-bottom: 0.32em;
}

/* ---------- 描边：细一档，浅一档，更接近发丝线 ---------- */
.card, .panel, .scard, .mini, .scard, .banner, .gridwrap, .dlg {
  border-color: color-mix(in srgb, currentColor 9%, transparent);
}
html[data-theme="ligh"] .card { border-color: rgba(13, 27, 42, .075); }

/* ---------- 阴影：更散、更淡 ---------- */
.card, .panel, .scard, .mini, .gridwrap {
  box-shadow:
    0 1px 1px rgba(13, 27, 42, .035),
    0 6px 20px -10px rgba(13, 27, 42, .16);
}
html[data-theme="dark"] .card,
html[data-theme="dark"] .panel,
html[data-theme="dark"] .scard,
html[data-theme="dark"] .mini,
html[data-theme="dark"] .gridwrap {
  box-shadow:
    0 1px 1px rgba(0, 0, 0, .35),
    0 8px 24px -12px rgba(0, 0, 0, .7);
}

/* ---------- 控件：统一触点高度与圆角 ---------- */
button, .btn-ghost, select, input[type="text"], input[type="password"],
input[type="number"], input[type="search"], textarea {
  border-radius: 11px;
  transition: background-color .18s var(--ease, ease),
              border-color .18s var(--ease, ease),
              box-shadow .18s var(--ease, ease),
              transform .14s var(--ease, ease);
}
button, .btn-ghost, select { min-height: 34px; }
.icon-btn { border-radius: 10px; }

/* 按下时轻微缩放，别弹 */
button:not(:disabled):active,
.btn-ghost:not(:disabled):active,
select:active {
  transform: scale(.975);
}

/* ---------- 焦点：只给键盘用户看，鼠标点不闪 ---------- */
:focus { outline: none; }
:focus-visible {
  outline: none;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent, #2b7fff) 30%, transparent);
}
button:focus-visible, .btn-ghost:focus-visible,
input:focus-visible, select:focus-visible, textarea:focus-visible {
  border-color: color-mix(in srgb, var(--accent, #2b7fff) 55%, transparent);
}

/* ---------- 分区标题：和内容左对齐 ---------- */
.panel > h2, .card > h2, .scard > h2 {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: .55em;
}

/* ---------- 列表 / 表格：行高节奏统一 ---------- */
table.adm td, table.adm th {
  vertical-align: middle;
}
table.adm td.mono { letter-spacing: -0.01em; }

/* ---------- 头像 / 小圆点：光学居中 ---------- */
.status, .st { display: inline-flex; align-items: center; gap: 8px; }
.status .dot, .st .dot { flex: none; }

/* ---------- 滚动条：细、淡、不抢眼 ---------- */
* {
  scrollbar-width: thin;
  scrollbar-color: color-mix(in srgb, currentColor 22%, transparent) transparent;
}
*::-webkit-scrollbar { width: 8px; height: 8px; }
*::-webkit-scrollbar-thumb {
  background: color-mix(in srgb, currentColor 20%, transparent);
  border-radius: 99px;
}
*::-webkit-scrollbar-thumb:hover {
  background: color-mix(in srgb, currentColor 34%, transparent);
}
*::-webkit-scrollbar-track { background: transparent; }

/* ---------- 选中文字 ---------- */
::selection {
  background: color-mix(in srgb, var(--accent, #2b7fff) 26%, transparent);
}

/* ---------- 动效：尊重系统设置 ---------- */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: .001ms !important;
    transition-duration: .001ms !important;
  }
}
</style>
<style id="ktLiquid">
/* ============ KT-LIQUID · 液态玻璃 + 按压交互 ============ */

* { -webkit-tap-highlight-color: transparent; }

/* ---------- 玻璃基材：多层高光 + 边缘厚度 ---------- */
.card, .panel, .scard, .mini, .gridwrap, .segmented, .dlg,
.sbox, .gcard, .arow, .tduty, .view-tabs {
  -webkit-backdrop-filter: blur(26px) saturate(190%) brightness(1.05);
  backdrop-filter: blur(26px) saturate(190%) brightness(1.05);
  border: 1px solid rgba(255, 255, 255, .62);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, .90),
    inset 0 -1px 0 rgba(255, 255, 255, .16),
    inset 0 0 0 1px rgba(255, 255, 255, .10),
    0 1px 2px rgba(13, 27, 42, .05),
    0 12px 34px -14px rgba(13, 27, 42, .26);
}
html[data-theme="dark"] .card,
html[data-theme="dark"] .panel,
html[data-theme="dark"] .scard,
html[data-theme="dark"] .mini,
html[data-theme="dark"] .gridwrap,
html[data-theme="dark"] .segmented,
html[data-theme="dark"] .dlg,
html[data-theme="dark"] .sbox,
html[data-theme="dark"] .gcard,
html[data-theme="dark"] .arow,
html[data-theme="dark"] .tduty,
html[data-theme="dark"] .view-tabs {
  border-color: rgba(255, 255, 255, .13);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, .16),
    inset 0 -1px 0 rgba(0, 0, 0, .40),
    inset 0 0 0 1px rgba(255, 255, 255, .05),
    0 1px 2px rgba(0, 0, 0, .40),
    0 14px 40px -16px rgba(0, 0, 0, .80);
}

/* ---------- 控件玻璃 ---------- */
.icon-btn, .btn-ghost, .minibtn, .btn, .callbtn, .st, .chip, .pill {
  -webkit-backdrop-filter: blur(18px) saturate(180%) brightness(1.04);
  backdrop-filter: blur(18px) saturate(180%) brightness(1.04);
  border: 1px solid rgba(255, 255, 255, .58);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, .80),
    inset 0 -1px 0 rgba(255, 255, 255, .12),
    0 2px 8px -3px rgba(13, 27, 42, .20);
}
html[data-theme="dark"] .icon-btn,
html[data-theme="dark"] .btn-ghost,
html[data-theme="dark"] .minibtn,
html[data-theme="dark"] .btn,
html[data-theme="dark"] .callbtn,
html[data-theme="dark"] .st,
html[data-theme="dark"] .chip,
html[data-theme="dark"] .pill {
  border-color: rgba(255, 255, 255, .15);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, .14),
    inset 0 -1px 0 rgba(0, 0, 0, .35),
    0 2px 10px -4px rgba(0, 0, 0, .60);
}

/* ---------- 弹簧过渡：松手回弹 ---------- */
button, .icon-btn, .btn-ghost, .minibtn, .btn, .callbtn,
.segmented button, .mini, .course, .tab, .chip, .pill,
a.card, tr.mrow {
  /* 抬起：慢慢回弹，带一点点过冲 */
  transition:
    transform .58s cubic-bezier(.22, 1.18, .36, 1),
    filter .34s cubic-bezier(.33, 1, .68, 1),
    box-shadow .38s cubic-bezier(.33, 1, .68, 1),
    background-color .28s cubic-bezier(.33, 1, .68, 1),
    border-color .28s cubic-bezier(.33, 1, .68, 1);
  will-change: transform;
  backface-visibility: hidden;
}

/* ---------- 按下：缩一点 + 压暗 + 内凹阴影（iOS 手感） ---------- */
.kt-press {
  /* 按下：入场稍快（.16s），但幅度更小 */
  transform: scale(.986) translateY(.5px) !important;
  filter: brightness(.982) saturate(1.03);
  box-shadow:
    inset 0 1px 5px rgba(13, 27, 42, .10),
    inset 0 -1px 0 rgba(255, 255, 255, .20) !important;
  transition:
    transform .16s cubic-bezier(.32, .72, .3, 1),
    filter .18s ease,
    box-shadow .18s ease !important;
}
html[data-theme="dark"] .kt-press {
  filter: brightness(1.035) saturate(1.03);
  box-shadow:
    inset 0 1px 6px rgba(0, 0, 0, .45),
    inset 0 -1px 0 rgba(255, 255, 255, .10) !important;
}
/* ---------- 触点高光：玻璃被按下去时的那圈亮 ---------- */
.kt-spec {
  position: fixed;
  pointer-events: none;
  z-index: 2147483001;
  mix-blend-mode: screen;
  background: radial-gradient(
    150px circle at var(--kx, 50%) var(--ky, 50%),
    rgba(255, 255, 255, .62),
    rgba(255, 255, 255, .18) 38%,
    rgba(255, 255, 255, 0) 72%);
  animation: ktSpec .62s cubic-bezier(.22, 1, .36, 1) forwards;
}
html[data-theme="dark"] .kt-spec {
  mix-blend-mode: soft-light;
  background: radial-gradient(
    150px circle at var(--kx, 50%) var(--ky, 50%),
    rgba(255, 255, 255, .40),
    rgba(255, 255, 255, .10) 40%,
    rgba(255, 255, 255, 0) 72%);
}
@keyframes ktSpec {
  0%   { opacity: 0;   transform: scale(.985); }
  16%  { opacity: 1; }
  100% { opacity: 0;   transform: scale(1.01); }
}
@media (prefers-reduced-motion: reduce) { .kt-spec { display: none; } }

/* 分组里的小按钮缩得更少，避免抖动 */
.minibtn.kt-press, .icon-btn.kt-press, .tag.kt-press {
  transform: scale(.955) translateY(.5px) !important;
}

/* ---------- 悬停：只给有鼠标的设备 ---------- */
@media (hover: hover) and (pointer: fine) {
  .icon-btn:hover, .btn-ghost:hover, .minibtn:hover, .btn:hover {
    transform: translateY(-1.5px);
    box-shadow:
      inset 0 1px 0 rgba(255, 255, 255, .92),
      0 8px 22px -10px rgba(13, 27, 42, .32);
  }
  .mini:hover, .course:hover, tr.mrow:hover td {
    filter: brightness(1.015);
  }
}

/* ---------- 键盘可达性 ---------- */
button:focus-visible, a:focus-visible,
input:focus-visible, select:focus-visible, textarea:focus-visible {
  outline: none;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, .80),
    0 0 0 3px color-mix(in srgb, var(--accent, #2b7fff) 32%, transparent) !important;
}

/* ---------- 分段控件：滑块玻璃 ---------- */
.segmented .thumb {
  -webkit-backdrop-filter: blur(14px) saturate(200%);
  backdrop-filter: blur(14px) saturate(200%);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, .85),
    0 2px 8px -2px rgba(13, 27, 42, .22);
  transition: transform .56s cubic-bezier(.22, 1.18, .36, 1),
              width .56s cubic-bezier(.22, 1.18, .36, 1);
}

/* ---------- 下拉 / 输入：玻璃底 ---------- */
select, input[type="text"], input[type="password"],
input[type="number"], input[type="search"], textarea {
  -webkit-backdrop-filter: blur(16px) saturate(170%);
  backdrop-filter: blur(16px) saturate(170%);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, .70);
}
html[data-theme="dark"] select,
html[data-theme="dark"] input[type="text"],
html[data-theme="dark"] input[type="password"],
html[data-theme="dark"] input[type="number"],
html[data-theme="dark"] input[type="search"],
html[data-theme="dark"] textarea {
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, .10);
}

@media (prefers-reduced-motion: reduce) {
  .kt-press { transition-duration: .01ms !important; }
}
</style>
<script>
/* KT-PRESS：iOS 触感 —— 触点高光 + 轻微收缩 + 慢回弹 */
(function () {
  if (window.__ktPress) return;
  window.__ktPress = 1;

  var SEL = 'button,a.card,.mini,.course,.icon-btn,.btn-ghost,.minibtn,' +
            '.segmented button,.tab,.chip,.pill,.btn,.callbtn,tr.mrow';

  function hit(el) {
    while (el && el !== document.body) {
      try { if (el.matches && el.matches(SEL)) return el; } catch (e) {}
      el = el.parentNode;
    }
    return null;
  }

  function spec(el, cx, cy) {
    try {
      var r = el.getBoundingClientRect();
      if (!r.width || !r.height) return;
      var cs = getComputedStyle(el);
      /* 全站 body 上有 transform:scale(0.85)，
         getBoundingClientRect 给的是缩放后的视觉坐标，
         而固定定位元素又会被再缩放一次 —— 必须除以缩放比才对齐。 */
      var z = 1;
      try {
        var raw = getComputedStyle(document.documentElement)
          .getPropertyValue('--kt-zoom');
        z = parseFloat(raw) || 1;
        if (z <= 0) z = 1;
      } catch (e) { z = 1; }

      var d = document.createElement('div');
      d.className = 'kt-spec';
      d.style.left = (r.left / z) + 'px';
      d.style.top = (r.top / z) + 'px';
      d.style.width = (r.width / z) + 'px';
      d.style.height = (r.height / z) + 'px';
      d.style.borderRadius = (parseFloat(cs.borderTopLeftRadius) / z || 14) + 'px';
      d.style.setProperty('--kx', ((cx - r.left) / z) + 'px');
      d.style.setProperty('--ky', ((cy - r.top) / z) + 'px');
      document.body.appendChild(d);
      setTimeout(function () { if (d.parentNode) d.parentNode.removeChild(d); }, 620);
    } catch (e) {}
  }

  document.addEventListener('pointerdown', function (e) {
    if (e.button && e.button !== 0) return;
    var t = hit(e.target);
    if (!t || t.disabled || t.getAttribute('aria-disabled') === 'true') return;

    t.classList.add('kt-press');
    spec(t, e.clientX, e.clientY);

    var done = function () {
      t.classList.remove('kt-press');
      document.removeEventListener('pointerup', done);
      document.removeEventListener('pointercancel', done);
      document.removeEventListener('pointerleave', done);
    };
    document.addEventListener('pointerup', done);
    document.addEventListener('pointercancel', done);
    document.addEventListener('pointerleave', done);
    setTimeout(done, 1600);
  }, { passive: true });
})();
</script>
<style id="ktMotion">
/* ============ KT-MOTION · 视图切换 / 弹窗 / 天气展开 ============ */

/* 视图切换：淡入 + 轻微上移 */
@keyframes ktViewIn {
  from { opacity: 0; transform: translateY(10px); }
  to   { opacity: 1; transform: none; }
}
.view.on {
  animation: ktViewIn .52s cubic-bezier(.22, 1, .36, 1) both;
}

/* 弹窗：从下方浮起并放大 */
@keyframes ktDlgIn {
  from { opacity: 0; transform: translateY(22px) scale(.962); }
  to   { opacity: 1; transform: none; }
}
.dlg, .modal-card, #modalCard {
  animation: ktDlgIn .56s cubic-bezier(.22, 1, .36, 1) both;
}
/* 遮罩淡入 */
@keyframes ktScrimIn { from { opacity: 0; } to { opacity: 1; } }
.modal, .modal-mask, .mask, #modal {
  animation: ktScrimIn .4s ease both;
}

/* 天气数据展开：左右展开 + 淡入 */
#ktWxSide {
  transition:
    max-width .58s cubic-bezier(.22, 1, .36, 1),
    opacity .46s ease,
    margin .56s cubic-bezier(.22, 1, .36, 1),
    transform .56s cubic-bezier(.22, 1, .36, 1);
}
#ktWxSide .x {
  transition:
    max-height .52s cubic-bezier(.22, 1, .36, 1),
    opacity .4s ease,
    margin-top .44s ease;
}
#ktWxMore, #ktWxMore * {
  transition: transform .48s cubic-bezier(.22, 1, .36, 1),
              background-color .3s ease, color .3s ease;
}

/* 页签：颜色渐变 + 按下微缩 */
.tab, .segmented button {
  transition:
    background-color .32s ease,
    color .32s ease,
    box-shadow .32s ease,
    transform .34s cubic-bezier(.22, 1.18, .36, 1);
}
.tab:active, .segmented button:active {
  transform: scale(.97);
}

/* 展开类容器统一慢一点 */
.collapse, .accordion-body, .expand {
  transition: max-height .55s cubic-bezier(.22, 1, .36, 1),
              opacity .42s ease;
}

@media (prefers-reduced-motion: reduce) {
  .view.on, .dlg, .modal-card, #modalCard, .modal, .modal-mask, .mask, #modal {
    animation-duration: .01ms !important;
  }
  #ktWxSide, #ktWxSide .x, #ktWxMore, .collapse, .expand {
    transition-duration: .01ms !important;
  }
}
</style>
<!-- KT-TOPBAR 全站顶部加载条 -->
<style id="ktTopCss">
#ktTop{position:fixed;top:0;left:0;right:0;height:3px;z-index:2147483000;
  pointer-events:none;opacity:0;transition:opacity .32s ease}
#ktTop.on{opacity:1}
#ktTop i{display:block;height:100%;width:0;border-radius:0 2px 2px 0;
  background:linear-gradient(90deg,#4aa8ff,#7ee0a8,#ffd84d,#ff8bc2,#4aa8ff);
  background-size:300% 100%;animation:ktFlow 2s linear infinite;
  box-shadow:0 0 12px rgba(74,168,255,.85),0 1px 4px rgba(30,110,210,.5);
  transition:width .3s cubic-bezier(.3,0,.2,1)}
@keyframes ktFlow{to{background-position:-300% 0}}
#ktTop.done i{animation:none;background:#34c072;
  box-shadow:0 0 12px rgba(52,192,114,.8)}
#ktTop.err i{animation:none;background:#f2555a;
  box-shadow:0 0 12px rgba(242,85,90,.8)}
@media (prefers-reduced-motion:reduce){#ktTop i{animation:none}}
</style>
<div id="ktTop" aria-hidden="true"><i></i></div>
<script id="ktTopJs">
(function () {
  if (window.__ktTop) return; window.__ktTop = 1;

  var el, bar, h = 0, tick = null, closing = null;
  var inflight = 0;          // 真正在飞的网络请求数
  var clickHold = false;     // 刚点了东西，先亮一会儿
  var holdTimer = null;

  function pick() {
    el = document.getElementById('ktTop');
    bar = el ? el.querySelector('i') : null;
  }

  function grow() {
    var step = h < 20 ? 9 : h < 50 ? 5 : h < 75 ? 2 : h < 90 ? 0.5 : 0;
    h = Math.min(90, h + step);
    if (bar) bar.style.width = h + '%';
  }

  /* 轮询类请求不要亮条：后台每 3 秒拉一次，会让条永远跑 */
  function skip(url) {
    var u = String(url || '');
    if (!u) return false;
    if (u.indexOf('/api/ping') >= 0) return true;
    if (u.indexOf('/api/events') >= 0) return true;
    if (u.indexOf('/api/auth/me') >= 0) return true;
    if (u.indexOf('/api/admin/') >= 0) return true;
    if (u.indexOf('/api/qq/status') >= 0) return true;
    return false;
  }

  function want() { return inflight > 0 || clickHold; }

  /* 唯一的显示/隐藏决策点。之前点击只加计数不收尾，
     导致普通点击（展开分类之类）把 n 越加越大、条永远走不完。 */
  function sync() {
    if (!el) pick();
    if (!el) return;
    if (want()) {
      clearTimeout(closing); closing = null;
      el.className = 'on';
      if (h >= 95) h = 15;
      if (bar) bar.style.width = h + '%';
      if (!tick) tick = setInterval(grow, 220);
    } else {
      if (tick) { clearInterval(tick); tick = null; }
      if (bar) bar.style.width = '100%';
      el.className = 'on done';
      closing = setTimeout(function () {
        if (want()) return;              // 又开始了就别收
        el.className = '';
        if (bar) bar.style.width = '0%';
        h = 0;
      }, 300);
    }
  }

  function fail() {
    inflight = 0; clickHold = false;
    if (tick) { clearInterval(tick); tick = null; }
    if (!el) pick();
    if (bar) bar.style.width = '100%';
    if (el) el.className = 'on err';
    closing = setTimeout(function () {
      if (el) el.className = '';
      if (bar) bar.style.width = '0%';
      h = 0;
    }, 500);
  }

  function ready(fn) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn);
    else fn();
  }

  ready(function () {
    pick();
    if (!el) {
      el = document.createElement('div');
      el.id = 'ktTop';
      el.innerHTML = '<i></i>';
      document.body.appendChild(el);
      bar = el.querySelector('i');
    }

    /* ---- fetch ---- */
    if (window.fetch) {
      var of = window.fetch;
      window.fetch = function (input) {
        var u = (typeof input === 'string') ? input
              : (input && input.url ? input.url : '');
        if (skip(u)) return of.apply(this, arguments);
        inflight++;
        sync();
        var p = of.apply(this, arguments);
        p.then(function (r) { inflight = Math.max(0, inflight - 1); sync(); return r; },
               function (e) { inflight = Math.max(0, inflight - 1); fail(); throw e; });
        return p;
      };
    }

    /* ---- XHR ---- */
    var XO = XMLHttpRequest.prototype.open, XS = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function (m, u) { this.__kt = u; return XO.apply(this, arguments); };
    XMLHttpRequest.prototype.send = function () {
      var self = this;
      if (skip(this.__kt)) return XS.apply(this, arguments);
      inflight++; sync();
      this.addEventListener('loadend', function () {
        inflight = Math.max(0, inflight - 1);
        if (self.status >= 400) fail(); else sync();
      });
      return XS.apply(this, arguments);
    };

    /* ---- 点击：亮一下就走，不再永久累加 ---- */
    document.addEventListener('click', function (e) {
      var t = e.target;
      while (t && t !== document) {
        var tag = (t.tagName || '').toLowerCase();
        if (tag === 'a' || tag === 'button' ||
            (t.getAttribute && (t.getAttribute('role') === 'button' || t.hasAttribute('onclick')))) {
          var href = t.getAttribute && t.getAttribute('href');
          if (href && (href.charAt(0) === '#' || href.indexOf('javascript:') === 0)) return;
          clickHold = true;
          sync();
          clearTimeout(holdTimer);
          // 900ms 内没有真实请求就先收掉；有请求的话 inflight 会顶住
          holdTimer = setTimeout(function () {
            clickHold = false;
            sync();
          }, 900);
          return;
        }
        t = t.parentNode;
      }
    }, true);

    /* 兜底：有请求卡住时，8 秒后强制收条 */
    setInterval(function () {
      if (inflight > 0) {
        var t = Date.now();
        if (!window.__ktTopT) window.__ktTopT = t;
        if (t - window.__ktTopT > 8000) {
          window.__ktTopT = 0; inflight = 0; clickHold = false; sync();
        }
      } else {
        window.__ktTopT = 0;
      }
    }, 2000);

    document.addEventListener('submit', function () {
      clickHold = true; sync();
      clearTimeout(holdTimer);
      holdTimer = setTimeout(function () { clickHold = false; sync(); }, 4000);
    }, true);

    /* ---- 回到页面时重置，避免上一页留下的状态卡住 ---- */
    window.addEventListener('pageshow', function () {
      inflight = 0; clickHold = false; h = 0;
      if (tick) { clearInterval(tick); tick = null; }
      clearTimeout(closing); clearTimeout(holdTimer);
      if (el) el.className = '';
      if (bar) bar.style.width = '0%';
    });

    window.ktBar = {
      start: function () { clickHold = true; sync(); },
      done: function () { inflight = 0; clickHold = false; sync(); },
      error: fail
    };
  });
})();
</script>
<!-- /KT-TOPBAR -->
"""

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
ROSTER_COOKIE = "kt_roster"
ROSTER_TTL = 3600          # 1 小时内同设备免再验证
PASS_COOKIE = "kt_pass"

# QQ 管理菜单的「等待回复」状态：(群号, QQ号) -> {expire, ...}
_PROCESS_START = time.time()

SESS_COOKIE = "kt_sess"

_QQ_PENDING = {}
_QQ_PENDING_LOCK = threading.Lock()

ADMIN_COOKIE = "kt_admin"


class Hub:
    """SSE 订阅中心。"""

    def __init__(self):
        self._subs = set()
        self._lock = threading.Lock()

    def subscribe(self):
        q = queue.Queue(maxsize=32)
        with self._lock:
            self._subs.add(q)
        return q

    def unsubscribe(self, q):
        with self._lock:
            self._subs.discard(q)

    def publish(self, event, data):
        payload = (event, data)
        with self._lock:
            dead = []
            for q in self._subs:
                try:
                    q.put_nowait(payload)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                self._subs.discard(q)


class App:
    def __init__(self, cfg, store=None, hub=None, fetcher=None):
        self.cfg = cfg
        self.store = store or Store()
        self.hub = hub or Hub()
        self.fetcher = fetcher

        # 「运行时长」要跨重启累计，不然每次重启都从 0 开始，只有几分钟没意义
        self._load_uptime()

        # 流量记录与安全防护
        self.traffic = traffic.TrafficLog()
        self.ratelimit = security.RateLimiter(
            per_minute=int(cfg.get("rate_per_minute", 180)),
            hard_limit=int(cfg.get("rate_hard_limit", 600)))
        self.authguard = security.AuthGuard(
            max_fails=int(cfg.get("auth_max_fails", 8)),
            ban_seconds=int(cfg.get("auth_ban_minutes", 15)) * 60)

        # STARTUP_UNBAN ------------------------------------------------
        # 进程一启动就清空封禁。
        # 封禁只为挡「正在跑的爆破脚本」，重启一次足以自证清白；
        # 而被封的人往往连后台都进不去，没法自救。
        # 有了这段，「重启服务」永远是可靠的兜底手段。
        try:
            self.authguard.clear_all()
        except Exception:
            pass
        self.iplists = security.IPLists()
        self._hb_last = 0.0

        # 系统状态采样器（看板的「系统监测」页用）
        self.sysinfo = sysinfo.Sampler(interval=3.0)
        self.sysinfo.start()

        # 后台心跳线程：不管有没有人访问网站，每 30 秒都把累计秒数写盘。
        #
        # 之前心跳只在有请求时才写，结果「没人访问的那段时间」没被记下来，
        # 重启后还会被当成停机而丢掉 —— 昨天整整 7 小时的运行时间就是这么没的。
        threading.Thread(target=self._heartbeat_loop, daemon=True).start()
        atexit.register(self._write_heartbeat)

    def _heartbeat_loop(self):
        while True:
            time.sleep(30)
            try:
                self._write_heartbeat()
            except Exception:
                pass

    # ---------------------------------------------------------------- 运行时长

    HEARTBEAT = os.path.join(DATA_DIR, "heartbeat.json")

    def _load_uptime(self):
        """读「累计运行时长」。

        运行时长的语义（所有页面统一）：
            累计运行 = 之前所有会话累计下来的秒数 + 本次会话已经运行的秒数

            只增不减 —— 重启、断电、关机都不会让它归零，也不会倒退。

        为什么要这样：
            以前这个数就是「本次进程启动了多久」，重启一次就清零，
            页面上永远显示几分钟，没有任何参考价值。

        实现：
            data/heartbeat.json 里存累计秒数和上次心跳时间。
            启动时把「上次心跳到现在」这段空缺补上（快速重启的那几秒），
            然后本次会话从 0 开始重新计时，两部分相加就是页面看到的数。
        """
        now = time.time()
        total = 0.0
        last_beat = 0.0
        try:
            with open(self.HEARTBEAT, encoding="utf-8") as f:
                d = json.load(f)
            total = float(d.get("total") or 0)
            last_beat = float(d.get("lastBeat") or 0)

            # 兼容旧格式：老版本存的是 firstStart/lastBeat，没有 total。
            # 不迁移的话，升级那一刻之前的累计值会全部丢掉。
            if not total and d.get("firstStart"):
                fs = float(d.get("firstStart") or 0)
                lb = float(d.get("lastBeat") or 0)
                if fs and lb and lb >= fs:
                    total = lb - fs
        except Exception:
            total = 0.0

        # 把重启的空档也算进去，但最多补 10 分钟 —— 关机一整晚不该算成运行时间
        if last_beat:
            gap = now - last_beat
            if 0 < gap <= 600:
                total += gap

        self.uptime_base = max(0.0, total)
        self.session_start = now
        self.started_at = now
        self.started_at_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
        self._hb_last = 0.0
        self._write_heartbeat()

    def uptime(self):
        """累计运行秒数（只增不减）。所有界面都该用这个。"""
        return int(self.uptime_base + (time.time() - self.session_start))

    def _write_heartbeat(self):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            tmp = self.HEARTBEAT + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({
                    "total": self.uptime_base + (time.time() - self.session_start),
                    "lastBeat": time.time(),
                }, f)
            os.replace(tmp, self.HEARTBEAT)
        except Exception:
            pass

    def beat(self):
        """每分钟把累计秒数写盘一次，供下次启动接着累加。"""
        now = time.time()
        if now - self._hb_last < 60:
            return
        self._hb_last = now
        self._write_heartbeat()

    # ---------------------------------------------------------------- 评分

    RATINGS = os.path.join(DATA_DIR, "ratings.json")

    def _load_ratings(self):
        try:
            with open(self.RATINGS, encoding="utf-8") as f:
                d = json.load(f)
            if not isinstance(d, dict):
                d = {}
        except Exception:
            d = {}
        counts = {}
        for i in range(1, 6):
            try:
                counts[str(i)] = int((d.get("counts") or {}).get(str(i), 0))
            except Exception:
                counts[str(i)] = 0
        return {
            "counts": counts,
            "total": int(d.get("total") or 0),
            "sum": float(d.get("sum") or 0),
            "recent": d.get("recent") or [],
        }

    def add_rating(self, score):
        """记一票。score 是 1~5。"""
        try:
            score = max(1, min(5, int(score)))
        except Exception:
            return None
        d = self._load_ratings()
        d["counts"][str(score)] += 1
        d["total"] += 1
        d["sum"] += score
        d["recent"].append({"score": score, "at": time.time()})
        d["recent"] = d["recent"][-300:]
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            tmp = self.RATINGS + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False)
            os.replace(tmp, self.RATINGS)
        except Exception:
            pass
        return self.ratings()

    def ratings(self):
        d = self._load_ratings()
        d["avg"] = round(d["sum"] / d["total"], 2) if d["total"] else 0.0
        # 最近 24 小时投了几票
        cutoff = time.time() - 86400
        d["today"] = sum(1 for r in d["recent"]
                         if isinstance(r, dict) and (r.get("at") or 0) >= cutoff)
        return d

    # ---------------------------------------------------------------- 数据

    def current_week(self, max_week):
        """算出现在是第几周。

        优先用 config.term_start（第 1 周的星期一）；
        没设就尝试从抓取到的学期信息里推断；都不行返回 1。
        """
        import datetime as _dt

        start = None
        raw = (self.cfg.get("term_start") or "").strip()
        if raw:
            for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
                try:
                    start = _dt.datetime.strptime(raw, fmt).date()
                    break
                except ValueError:
                    continue

        if start is None:
            info = self.store.get().get("term") or {}
            if isinstance(info, dict):
                for key in ("startDate", "start_date", "kxrq", "termStart", "beginDate"):
                    v = (info.get(key) or "")
                    if isinstance(v, str) and len(v) >= 8:
                        try:
                            s = v.replace("/", "-").replace(".", "-")[:10]
                            start = _dt.datetime.strptime(s, "%Y-%m-%d").date()
                            break
                        except ValueError:
                            continue

        if start is None:
            return 1, None

        # 把 start 对齐到那一周的周一
        start = start - _dt.timedelta(days=start.weekday())
        today = _dt.date.today()
        week = (today - start).days // 7 + 1
        if week < 1:
            week = 1
        if max_week and week > max_week:
            week = max_week
        return week, start.isoformat()

    def public_stats(self):
        """首页那两个小模块的数据：运行时长 + 今日访客。

        访客数要读整个流量日志，比较重，而 /api/schedule 是每个同学都会请求的，
        所以这里缓存 30 秒，避免每次都去扫日志。
        """
        now = time.time()
        cached = getattr(self, "_pubstats", None)
        if cached and now - cached[0] < 30:
            return cached[1]
        try:
            visitors = self.traffic.stats(hours=24).get("todayVisitors", 0)
        except Exception:
            visitors = 0
        val = {
            "uptime": self.uptime(),        # 累计运行，只增不减
            "todayVisitors": int(visitors),
        }
        self._pubstats = (now, val)
        self.beat()          # 顺便写心跳，供下次启动判断是「快速重启」还是「久停」
        return val

    def state_payload(self):
        st = self.store.get()
        sched = st.get("schedule", {})
        max_week = sched.get("maxWeek", 20) or 20
        week, term_start = self.current_week(max_week)
        import datetime as _dt
        today = _dt.date.today()
        return {
            "revision": st.get("revision", 0),
            "updatedAt": st.get("updatedAt"),
            "lastOkAt": st.get("lastOkAt"),
            "lastError": st.get("lastError"),
            "term": st.get("term"),
            "maxWeek": max_week,
            "count": sched.get("count", 0),
            "courses": sched.get("courses", []),
            "changes": st.get("changes", []),
            "history": st.get("history", []),
            "source": st.get("source", ""),
            "serverTime": time.time(),
            "hasSession": bool(self.fetcher and self.fetcher.has_session()),
            "autoFetchOff": bool(self.fetcher is None),
            "noSession": bool(self.fetcher and self.fetcher.stats.get("noSession")),
            "currentWeek": week,
            "termStart": term_start,
            "todayISO": today.isoformat(),
            "weekMonday": (today - _dt.timedelta(days=today.weekday())).isoformat(),
            # 首页顶部两个小模块
            "stats": self.public_stats(),
            # 副班评价（看板 / 后台都要看）
            "ratings": self.ratings(),
        }

    def pass_ok(self, code):
        want = (self.cfg.get("access_code") or "").strip()
        if not want:
            return True
        return code == want


class Handler(BaseHTTPRequestHandler):
    server_version = "KbMirror/0.1"
    app: App = None

    # HTTP/1.1 = 支持长连接（keep-alive）。
    # 默认的 HTTP/1.0 每个请求都要新建一条 TCP 连接 ——
    # 一个课表页要加载 html + css + js + 图标 = 5~6 条连接，
    # 经 Cloudflare 隧道来回时这个开销会被放大好几倍。
    # 注意：开了 HTTP/1.1 后每个响应都必须有准确的 Content-Length，
    # 或者显式声明要关闭连接（SSE 就是后者）。
    protocol_version = "HTTP/1.1"
    # 空闲长连接最多挂 30 秒，避免线程堆积
    timeout = 30

    def handle_one_request(self):
        """每个请求开始前，清掉上一个请求留下的鉴权缓存。

        这是个真踩过的坑：开了 keep-alive 之后，BaseHTTPRequestHandler 会
        **复用同一个 Handler 实例**处理同一条连接上的多个请求，而
        _authed / _admin_authed 把结果缓存在 self 上，于是：

            GET  /admin            -> 未登录，缓存 _admin_cache = False
            POST /api/admin-login  -> 登录成功，下发 cookie（同一条连接）
            GET  /admin            -> 直接返回缓存的 False，又弹登录页

        表现就是"口令明明对，输完又回到登录页"，刷新几次偶尔能进
        （因为浏览器有时会另开一条连接）。这里每个请求开头清一次最干净。
        """
        self._authed_cache = None
        self._admin_cache = None
        return BaseHTTPRequestHandler.handle_one_request(self)

    # ---------------------------------------------------------------- 工具

    def log_message(self, fmt, *args):
        if os.environ.get("KT_VERBOSE"):
            super().log_message(fmt, *args)

    def _gzip_ok(self, body, ctype):
        """判断这次响应要不要 gzip。"""
        if len(body) < 1024:
            return False
        if "gzip" not in (self.headers.get("Accept-Encoding") or ""):
            return False
        c0 = ctype.split(";")[0].strip().lower()
        if c0 in ("text/html", "text/css", "text/javascript",
                  "application/javascript", "application/json",
                  "application/xml", "text/xml", "image/svg+xml",
                  "text/plain", "application/manifest+json"):
            return True
        return c0.startswith("text/")

    def _send(self, status, body, ctype="application/json; charset=utf-8", extra=None,
              cors=False, log=True):
        if isinstance(body, str):
            body = body.encode("utf-8")
        # 全站顶部加载条：任何 HTML 响应都自动注入（含两个登录页）
        if ctype.startswith("text/html"):
            body = self._kt_topbar(body)
            body = self._kt_splash(body)
        extra = extra or {}
        # 文本类响应走 gzip（体积能降到 1/3 左右）
        try:
            if self._gzip_ok(body, ctype):
                import gzip as _gz
                body = _gz.compress(body, 6)
                extra = dict(extra)
                extra["Content-Encoding"] = "gzip"
                extra.setdefault("Vary", "Accept-Encoding")
        except Exception:
            pass
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # extra 里自己带了 Cache-Control 就别再发一遍（否则发两个头，浏览器行为不定）
        if "Cache-Control" not in extra:
            self.send_header("Cache-Control", "no-store")
        for k, v in security.SECURITY_HEADERS.items():
            if k not in extra:
                self.send_header(k, v)
        if cors:
            # 允许从教务系统页面（别的源）取这个脚本 / 回传数据
            self.send_header("Access-Control-Allow-Origin", "*")
        for k, v in extra.items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass
        if log:
            self._log_traffic(status, len(body))

    # ---------------------------------------------------------------- 流量记录

    def _fp(self):
        """客户端指纹（JS 写进 cookie），同一出口也能区分不同设备。"""
        try:
            v = self._cookies().get("kt_fp", "")
            return urllib.parse.unquote(v)[:32] if v else ""
        except Exception:
            return ""

    def _log_traffic(self, status, size):
        if getattr(self, "_logged", False):
            return
        self._logged = True
        try:
            parsed = urllib.parse.urlparse(self.path)
            self.app.traffic.record(
                ip=getattr(self, "_ip", None) or security.client_ip(self),
                method=self.command or "?",
                path=parsed.path,
                status=status,
                ua=self.headers.get("User-Agent", ""),
                referer=self.headers.get("Referer", ""),
                ms=int((time.time() - getattr(self, "_t0", time.time())) * 1000),
                size=size,
                country=self.headers.get("CF-IPCountry", "") or "",
                fp=self._fp(),
                extra={"q": (parsed.query or "")[:160]} if parsed.query else None,
            )
        except Exception:
            pass

    # ---------------------------------------------------------------- 前置防护

    # ------------------------------ 管理菜单 ------------------------------
    _QQ_MENU = [
        ("1", "推送次日课表与值日安排"),
        ("2", "推送当日值日安排并通知组员"),
        ("3", "查询本周课表"),
        ("4", "发送早课提醒"),
        ("0", "取消当前操作"),
    ]

    def _qq_is_admin(self, role):
        return str(role or "").lower() in ("owner", "admin")

    def _qq_menu_text(self):
        L = ["【 管理菜单 】", "请在 60 秒内回复编号：", ""]
        for k, v in self._QQ_MENU:
            L.append("  %s · %s" % (k, v))
        L.extend(self._qq_foot("PaperCloud · Q群机器人"))
        return "\n".join(L)

    def _qq_menu_take(self, gid, uid):
        """取出待办并清掉。返回 False 表示已过期。"""
        with _QQ_PENDING_LOCK:
            item = _QQ_PENDING.get((gid, uid))
            if not item:
                return False
            _QQ_PENDING.pop((gid, uid), None)
            return True

    def _qq_menu_open(self, gid, uid):
        with _QQ_PENDING_LOCK:
            _QQ_PENDING[(gid, uid)] = {"expire": time.time() + 60}
        return self._qq_menu_text()

    @staticmethod
    def _fmt_dur(sec):
        sec = int(max(0, sec or 0))
        d, rem = divmod(sec, 86400)
        h, rem = divmod(rem, 3600)
        m, sec2 = divmod(rem, 60)
        if d:
            return "%d 天 %02d:%02d:%02d" % (d, h, m, sec2)
        return "%02d:%02d:%02d" % (h, m, sec2)

    def _sys_stats(self):
        """采集硬件与运行状态（纯标准库）。"""
        import platform
        import shutil
        out = {
            "host": "", "os": "", "py": "", "cores": 0,
            "cpu": None, "mem_total": 0, "mem_used": 0,
            "disk_total": 0, "disk_free": 0, "disk_path": "",
            "boot_uptime": None,
        }
        try:
            out["host"] = platform.node()
            out["os"] = "%s %s" % (platform.system(), platform.release())
            out["py"] = platform.python_version()
            out["cores"] = os.cpu_count() or 0
        except Exception:
            pass

        # 磁盘
        try:
            base = os.path.abspath(os.path.join(DATA_DIR, ".."))
            drive = os.path.splitdrive(base)[0] or "/"
            u = shutil.disk_usage(drive)
            out["disk_total"] = u.total
            out["disk_free"] = u.free
            out["disk_path"] = drive
        except Exception:
            pass

        # 主机运行时长
        try:
            m = time.monotonic()
            if m > 3600:            # Windows 上 monotonic 从开机算
                out["boot_uptime"] = m
        except Exception:
            pass

        # 内存 + CPU（Windows API）
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            st = MEMORYSTATUSEX()
            st.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
                out["mem_total"] = int(st.ullTotalPhys)
                out["mem_used"] = int(st.ullTotalPhys - st.ullAvailPhys)

            class FILETIME(ctypes.Structure):
                _fields_ = [("low", ctypes.c_ulong), ("high", ctypes.c_ulong)]

            def _ft(f):
                return (f.high << 32) | f.low

            idle1, kern1, user1 = FILETIME(), FILETIME(), FILETIME()
            ctypes.windll.kernel32.GetSystemTimes(
                ctypes.byref(idle1), ctypes.byref(kern1), ctypes.byref(user1))
            time.sleep(0.25)
            idle2, kern2, user2 = FILETIME(), FILETIME(), FILETIME()
            ctypes.windll.kernel32.GetSystemTimes(
                ctypes.byref(idle2), ctypes.byref(kern2), ctypes.byref(user2))
            di = _ft(idle2) - _ft(idle1)
            dk = _ft(kern2) - _ft(kern1)
            du = _ft(user2) - _ft(user1)
            total = dk + du
            if total > 0:
                out["cpu"] = round((1.0 - di / float(total)) * 100.0, 1)
        except Exception:
            pass

        return out

    def _qq_status_text(self):
        """系统运行状态（专业术语版）。"""
        cfg = self._qq_cfg()
        ok, who = (False, "")
        try:
            ok, who = qq.ping(cfg)
        except Exception:
            pass
        groups = sorted(qq.allow_groups(cfg))
        st = self._sys_stats()

        def gb(n):
            return "%.1f GB" % (n / 1073741824.0) if n else "—"

        L = ["【 系统运行状态 】", ""]
        L.append("▍服务实例")
        L.append("  实例运行时长   " + self._fmt_dur(time.time() - _PROCESS_START))
        if st["boot_uptime"]:
            L.append("  主机运行时长   " + self._fmt_dur(st["boot_uptime"]))
        L.append("  协议端连接     " + ("已连接" if ok else "未连接"))
        if isinstance(who, str) and who:
            L.append("  登录账号       " + who)
        L.append("  监听群组       " + ("、".join(str(g) for g in groups) or "未配置"))
        L.append("  定时任务       早课 08:00 / 日报 21:00")
        L.append("")
        L.append("▍系统状态")
        L.append("  主机名称       PaperCloud-Server")
        if st["os"]:
            L.append("  操作系统       " + st["os"] + ("（%d 逻辑核心）" % st["cores"] if st["cores"] else ""))
        if st["cpu"] is not None:
            L.append("  CPU 占用率     %.1f%%" % st["cpu"])
        if st["mem_total"]:
            pct = st["mem_used"] * 100.0 / st["mem_total"]
            L.append("  物理内存       %s / %s（%.0f%%）" % (gb(st["mem_used"]), gb(st["mem_total"]), pct))
        if st["disk_total"]:
            used = st["disk_total"] - st["disk_free"]
            pct = used * 100.0 / st["disk_total"]
            L.append("  磁盘占用       %s / %s（%.0f%%）" % (
                gb(used), gb(st["disk_total"]), pct))
            L.append("  可用空间       " + gb(st["disk_free"]))
        if st["py"]:
            L.append("  运行时版本     Python " + st["py"])
        L.append("")
        L.append("PaperCloud · Q群机器人")
        return "\n".join(L)

    def _qq_menu_run(self, choice, gid):
        if choice == "0":
            return "操作已取消"

        if choice == "1":
            seg = list(self._qq_day_text(1, gid) or [])
            try:
                d = self._qq_duty_text(1, gid)
                dseg = d[0] if isinstance(d, tuple) else d
                if isinstance(dseg, list):
                    seg.append({"type": "text", "data": {"text": "\n\n"}})
                    seg.extend(dseg)
                elif dseg:
                    seg.append({"type": "text", "data": {"text": "\n\n" + str(dseg)}})
            except Exception:
                pass
            return seg

        if choice == "2":
            d = self._qq_duty_text(0, gid)
            return d[0] if isinstance(d, tuple) else d

        if choice == "3":
            return self._qq_week_text()

        if choice == "4":
            seg = self._qq_morning_seg(gid)
            if not seg:
                return "【 早课提醒 】\n当日无课程安排，不发送提醒\n\nPaperCloud · Q群机器人"
            return seg

        return "指令编号无效，请重新发送「管理」"


    def _is_local(self):
        """请求是不是来自本机回环地址。"""
        ip = str(getattr(self, "_ip", "") or "")
        if ip in ("127.0.0.1", "::1", "localhost", "0:0:0:0:0:0:0:1"):
            return True
        # 反向代理场景：看 X-Forwarded-For 的最后一跳
        try:
            xff = (self.headers.get("X-Forwarded-For") or "").strip()
            if xff:
                last = xff.split(",")[-1].strip()
                if last in ("127.0.0.1", "::1"):
                    return True
        except Exception:
            pass
        return False

    def _pre(self):
        """每个请求进来先过一遍安全检查。返回 True 才继续处理。"""
        self._t0 = time.time()
        self._logged = False
        self._authed_cache = None
        self._ip = security.client_ip(self)
        path = urllib.parse.urlparse(self.path).path

        # 静态资源不参与限流，避免一个页面几十个资源被误伤
        is_static = path.startswith("/static/")

        # QQ 机器人上报：NapCat 和站点在同一台机器，是本机回环地址。
        # 它既没有班级口令也没有 Cookie，还可能被限流误伤，
        # 所以直接跳过前置检查（webhook 自己会校验 key）。
        if path in ("/api/qq/webhook", "/api/qq/push") and self._is_local():
            return True

        ok, reason = self.app.iplists.check(self._ip)
        if not ok:
            self._send(403, json.dumps({"ok": False, "message": "访问被拒绝"},
                                       ensure_ascii=False),
                       extra={"Access-Control-Allow-Origin": "*"})
            return False

        banned, remain = self.app.authguard.is_banned(self._ip)
        if banned:
            # 后台必须永远进得去 —— 否则被封之后连「解除封禁」的按钮都点不到，
            # 就成死锁了（用户碰到过：点解封毫无反应）。
            # 抓取上传也放行：那是正常业务请求，不是爆破。
            exempt = (path in ("/admin", "/admin/", "/admin.html")
                      or path.startswith("/api/admin/")
                      or path == "/api/admin-login"
                      or path == "/api/import-session")
            if not exempt:
                # 响应必须带 CORS —— 书签是在教务系统页面上跑的（跨域），
                # 不带的话浏览器只会报「CORS 错误」，用户根本看不到
                # 「你被封了，还有几分钟」这句真正有用的话。
                self._send(429, json.dumps({
                    "ok": False,
                    "message": f"访问口令错误次数过多，请 {remain // 60 + 1} 分钟后再试",
                }, ensure_ascii=False),
                    extra={"Retry-After": str(remain), "Access-Control-Allow-Origin": "*"})
                return False

        if not is_static:
            allowed, retry, why = self.app.ratelimit.check(self._ip)
            if not allowed:
                self._send(429, json.dumps({"ok": False, "message": why},
                                           ensure_ascii=False),
                           extra={"Retry-After": str(retry)})
                return False
        return True

    def _json(self, obj, status=200, cors=False):
        self._send(status, json.dumps(obj, ensure_ascii=False), cors=cors)

    def _cookies(self):
        out = {}
        raw = self.headers.get("Cookie", "")
        for part in raw.split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                out[k.strip()] = v.strip()
        return out

    def _query(self):
        return urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

    def _authed(self):
        """校验访问口令。同一请求内结果缓存，避免重复计数。"""
        if getattr(self, "_authed_cache", None) is not None:
            return self._authed_cache

        # 有有效账号会话也算已登录
        if self._sess_user():
            self._authed_cache = True
            return True

        q = self._query()
        raw = (q.get("k") or [""])[0] or self._cookies().get(PASS_COOKIE, "")
        # 写 cookie 时做了 URL 编码，读回来要解码（口令里可能有 @ # 之类）
        code = urllib.parse.unquote(raw) if raw else ""

        if self.app.pass_ok(code):
            if code:
                self.app.authguard.note_success(getattr(self, "_ip", ""))
            self._authed_cache = True
            return True

        # 没带口令：只是没登录，不算爆破
        # 带了口令但不对：记账，够次数就封
        if code:
            ip = getattr(self, "_ip", "")
            banned, remain, n = self.app.authguard.note_fail(ip)
            self._fail_count = n
            if banned:
                self._ban_triggered = True

        self._authed_cache = False
        return False

    # ---------------------------------------------------------------- 管理后台门禁

    def _admin_password(self):
        """读管理口令 —— 每次从 secrets.json 现读，实现热更新。

        改了 config/secrets.json 里的 admin_password，**不用重启服务**就生效。
        为了不每个请求都读盘，做了 2 秒缓存。
        """
        key = "_admin_pw_cache"
        cached = getattr(self.app, key, None)
        now = time.time()
        if cached and now - cached[0] < 2.0:
            return cached[1]

        val = ""
        try:
            p = os.path.join(os.path.dirname(DATA_DIR), "config", "secrets.json")
            with open(p, encoding="utf-8") as f:
                val = str(json.load(f).get("admin_password") or "")
        except Exception:
            val = str(self.app.cfg.get("admin_password") or "")

        setattr(self.app, key, (now, val))
        return val

    def _admin_authed(self):
        """管理后台单独的口令 —— 和给同学的班级口令分开。

        这样同学拿到 ?k=YOUR_ACCESS_CODE 也进不了 /admin 和 /api/admin/*。
        口令每次现读（见 _admin_password），改了不用重启。
        """
        if getattr(self, "_admin_cache", None) is not None:
            return self._admin_cache

        want = (self._admin_password() or "").strip()
        if not want:
            # 没单独设管理口令 -> 退回班级口令，避免把自己锁在门外
            self._admin_cache = self._authed()
            return self._admin_cache

        q = self._query()
        # 写 cookie 时做了 URL 编码（口令里可能有 @ # 之类），读回来必须解码
        raw = (q.get("a") or [""])[0] or self._cookies().get(ADMIN_COOKIE, "")
        code = urllib.parse.unquote(raw) if raw else ""
        ok = bool(code) and hmac.compare_digest(str(code), want)

        if ok:
            self.app.authguard.note_success(getattr(self, "_ip", ""))
        elif code:
            self.app.authguard.note_fail(getattr(self, "_ip", ""))

        self._admin_cache = ok
        return ok

    def _admin_login(self, body):
        """管理后台登录。校验成功就下发一个独立的 cookie。"""
        want = (self._admin_password() or "").strip()
        if not want:
            return self._json({"ok": False, "message": "还没设置管理口令"}, 400)

        code = str(body.get("code") or "")
        if code and hmac.compare_digest(code, want):
            self.app.authguard.note_success(getattr(self, "_ip", ""))
            # 立刻把本连接的鉴权缓存刷成已通过，
            # 免得同一条 keep-alive 连接上的下一个请求还看到旧的 False。
            self._authed_cache = True
            self._admin_cache = True
            return self._send(200, json.dumps({"ok": True}, ensure_ascii=False), extra={
                "Set-Cookie": f"{ADMIN_COOKIE}={urllib.parse.quote(code)}; Path=/; "
                              f"Max-Age=2592000; SameSite=Lax; HttpOnly",
            })

        banned, remain, n = self.app.authguard.note_fail(getattr(self, "_ip", ""))
        if banned:
            msg = f"错误次数过多，已暂时拒绝访问（{remain // 60 + 1} 分钟）"
        elif n >= 3:
            msg = f"管理口令不正确（第 {n} 次，再错 {self.app.authguard.max_fails - n} 次将被暂时封禁）"
        else:
            msg = "管理口令不正确"
        return self._json({"ok": False, "message": msg}, 403)

    # ---------------------------------------------------------------- 路由

    def do_GET(self):
        if not self._pre():
            return
        path = urllib.parse.urlparse(self.path).path

        # 后台的「快捷操作」里有 /grab 和 /edit 两个入口。
        # 后台是用【管理口令】登录的，不带班级口令 ——
        # 必须在班级口令门禁【之前】放行，否则管理员点进去会被弹去
        # 班级口令登录页，生成的抓取代码里就没有 ?k=，上传必然 401。
        if path in ("/grab", "/grab/", "/grab.html", "/edit", "/edit.html", "/edit/"):
            if self._admin_authed():
                rel = "grab.html" if "grab" in path else "edit.html"
                return self._serve_file(rel, public=True)

        if path == "/api/weather":
            return self._weather()      # 公开，不需要口令

        if path == "/api/ping":
            # 页面心跳：只为了让「在线访客」知道页面还开着
            return self._send(200, '{"ok":true}', "application/json; charset=utf-8",
                              extra={"Cache-Control": "no-store"})

        if path == "/api/auth/me":
            return self._api_auth_me()

        if path == "/api/auth/outbox":
            if not self._admin_authed():
                return self._json({"ok": False, "message": "需要管理口令"}, 401)
            return self._api_auth_outbox()

        if path == "/api/qq/raw":
            q0 = self._query()
            kk0 = (q0.get("k") or [""])[0]
            want0 = (self._admin_password() or "").strip()
            if not (self._admin_authed() or (want0 and kk0 == want0) or self._is_local()):
                return self._json({"ok": False, "message": "需要管理口令"}, 401)
            return self._qq_raw()

        if path == "/api/qq/debug":
            # 允许 ?k=<管理口令> 直接查看，方便手机上排查
            q = self._query()
            kk = (q.get("k") or [""])[0]
            want = (self._admin_password() or "").strip()
            if not (self._admin_authed() or (want and kk == want)):
                return self._json({"ok": False, "message": "需要管理口令"}, 401)
            return self._qq_debug()

        if path == "/api/qq/status":
            if not self._authed():
                return self._json({"ok": False, "message": "需要口令"}, 401)
            return self._qq_status()

        if path == "/events":
            return self._sse()

        if path == "/api/health":
            return self._health()

        if path in ("/timetable.ics", "/timetable.ical", "/kb.ics"):
            return self._ics()

        if path.startswith("/api/admin/adjust/"):
            return self._api_adjust(path)
        if path.startswith("/api/admin/"):
            return self._api_admin(path)

        # 班务系统：学生 / 考勤 / 值日，走班级口令
        if path.startswith("/api/class"):
            if path == "/api/class/roster-state":
                return self._roster_state()
            return self._api_class(path)

        if path.startswith("/api/"):
            return self._api_get(path)

        # 首页改成导航页：一个大圆图标 + PaperCloud + 三个入口。
        # 它不需要口令 —— 本身不含任何数据，只是三个按钮，
        # 地址栏带的 ?k= 会被透传给「在线课表」和「班务系统」。
        # ---- 百度站长平台：文件校验（文件名即以 baidu_verify_ 开头）----
        if path.startswith("/baidu_verify_") and path.endswith(".html"):
            fn = os.path.basename(path)
            full = os.path.join(WEB_DIR, fn)
            txt = ""
            try:
                if os.path.isfile(full):
                    # utf-8-sig：去掉记事本/PowerShell 写入的 BOM，
                    # 百度是逐字节比对，BOM 会让它判失败
                    with open(full, encoding="utf-8-sig", errors="replace") as f:
                        txt = f.read().strip().lstrip(chr(0xfeff)).strip()
            except Exception:
                txt = ""
            if not txt:
                txt = fn[len("baidu_verify_"):-len(".html")]
            # 纯文本返回：不加任何脚本/状态栏，百度只认原始内容
            return self._send(200, txt, "text/plain; charset=utf-8")

        if path == "/sitemap.xml":
            host = "https://your-domain.example"
            # lastmod 取课表最后更新时间，让百度知道站点是活的
            lastmod = ""
            try:
                import datetime as _dt0
                st0 = self.app.store.get()
                ts0 = st0.get("updatedAt") or st0.get("lastOkAt") or ""
                day = ""
                if isinstance(ts0, (int, float)) or str(ts0).isdigit():
                    day = _dt0.date.fromtimestamp(float(ts0)).isoformat()
                elif ts0:
                    day = str(ts0)[:10]
                if day and len(day) == 10:
                    lastmod = "<lastmod>" + day + "</lastmod>"
            except Exception:
                lastmod = ""

            pages = [
                ("/", "1.0", "daily"),
                ("/timetable", "0.9", "daily"),
                ("/class", "0.8", "weekly"),
                ("/tools", "0.6", "weekly"),
                ("/login", "0.5", "monthly"),
            ]
            items = "".join(
                "  <url><loc>%s%s</loc>%s<changefreq>%s</changefreq>"
                "<priority>%s</priority></url>\n" % (host, p, lastmod, cf, pr)
                for p, pr, cf in pages)
            xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                   '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                   + items + '</urlset>\n')
            return self._send(200, xml, "application/xml; charset=utf-8")

        if path == "/robots.txt":
            txt = ("User-agent: *\nAllow: /\nDisallow: /adjust\n"
                   "Sitemap: https://your-domain.example/sitemap.xml\n"
                   "\n# PaperCloud - 26 现代通信技术1班 班务系统\n")
            return self._send(200, txt, "text/plain; charset=utf-8")
        if path in ("/", "/index.html", "/home", "/home.html"):
            return self._serve_file("home.html", public=True)

        # 课表从 / 挪到 /timetable，权限不变（还是要班级口令）
        if path in ("/timetable", "/timetable/", "/kb", "/kb/"):
            return self._serve_file("index.html")

        # 班务系统：目前是占位页，权限和课表一致
        if path in ("/class", "/class/", "/class.html", "/banwu"):
            return self._serve_file("class.html")

        # PWA 的两个文件必须无条件放行：
        #   · 浏览器在还没登录时就会取 manifest 和 sw.js，带不上 ?k=
        #   · Service Worker 必须挂在根路径 /sw.js 才能管到整个站点
        # 它们里面没有任何秘密。
        if path in ("/manifest.webmanifest", "/manifest.json"):
            return self._serve_file("manifest.webmanifest", cache="asset", public=True,
                                    force_ctype="application/manifest+json; charset=utf-8")
        if path == "/sw.js":
            return self._serve_file("sw.js", public=True,
                                    force_ctype="text/javascript; charset=utf-8")

        # 网页图标：浏览器在还没登录时就会请求，所以必须无条件放行
        if path in ("/favicon.ico", "/favicon.png", "/favicon-192.png",
                    "/favicon-512.png", "/apple-touch-icon.png",
                    "/apple-touch-icon-precomposed.png"):
            return self._icon(path)

        # 抓取脚本会被「教务系统页面」（另一个源）加载，所以：
        #   1. 不能要求口令（否则返回登录页 HTML，脚本拿不到）
        #   2. 必须带 Access-Control-Allow-Origin
        if path in ("/static/grab.js", "/grab.js", "/static/grab-page.js"):
            return self._serve_file("grab.js")

        # 油猴脚本：需要按当前访问地址动态注入回传地址，所以单独处理。
        # 走 ?k= 校验口令，避免把口令泄露给不知道口令的人。
        if path in ("/kb-sync.user.js", "/kb-sync.user"):
            return self._userscript()

        #  静态资源必须放在口令校验「之前」。
        # 浏览器加载 <link href="/static/style.css"> 和 <script src="/static/app.js">
        # 时，请求里是不带 ?k= 的 —— 如果这里先做 _authed() 检查，
        # 返回的就是登录页 HTML，浏览器拿到 HTML 当 CSS/JS 用，
        # 页面就变成「能打开但完全没样式、课表也不显示」。
        # 这些文件里没有任何秘密（秘密都在 /api/* 后面），所以放行。
        if path.startswith("/static/"):
            return self._serve_file(path[len("/static/"):], cache="asset", public=True)

        # 管理后台：独立口令，放在班级口令校验之前 ——
        # 同学就算有 ?k= 也不该看到管理页。
        if path in ("/adjust", "/adjust/", "/adjust.html"):
            return self._serve_file("adjust.html", public=True, cache="no-store")
        if path in ("/admin", "/admin/", "/admin.html"):
            if not self._admin_authed():
                return self._admin_login_page()
            # public=True：上面已经用「管理口令」验过了，
            # 这里不能再要求班级口令，否则管理员还得额外带 ?k= 才能进。
            return self._serve_file("admin.html", public=True)

        # 班务【编辑】页：也只有管理员能进。
        # 前台 /class 是纯只读的（名单、考勤、值日、打电话），
        # 增删改一律在这个页面做，它没有公开入口，只能从后台点进来。
        if path in ("/class-admin", "/class-admin/", "/class-admin.html"):
            if not self._admin_authed():
                return self._admin_login_page()
            return self._serve_file("class-admin.html", public=True)


        if path in ("/login", "/login/", "/login.html"):
            return self._serve_file("login.html", public=True)

        if path in ("/qq-admin", "/qq-admin/", "/qq-admin.html"):
            if not self._admin_authed():
                return self._admin_login_page()
            return self._serve_file("qq-admin.html", public=True)

        # 课表看板（iPhone 上「添加到主屏幕」的那个页面）
        # 权限和主页一致：用班级口令，支持 cookie ——
        # 所以装成 App 之后直接打开也不用再输口令。
        if path in ("/dashboard", "/dashboard/", "/dash"):
            return self._serve_file("dashboard.html")

        # ---------------------------------------------------- 工具箱
        # ---- 自建 720 全景（web/tour2）----
        if path in ("/tour2", "/tour2/", "/tour2/index.html"):
            return self._serve_file("tour2/index.html", public=True, cache="no-store")
        if path.startswith("/tour2/"):
            return self._serve_file(path[1:], public=True, cache="asset")

        # ---- 校园 720 全景：走轻量自建版（web/tour2），不依赖 70MB 播放器 ----
        if path in ("/tour", "/tour/", "/tour/index.html"):
            return self._serve_file("tour2/index.html",
                                    public=True, cache="no-store")
        if path.startswith("/tour/"):
            rel = "tour2/" + path[len("/tour/"):]
            return self._serve_file(rel, public=True, cache="no-store")

        if path in ("/tools", "/tools/", "/tools.html"):
            return self._serve_file("tools.html", public=True)

        if path == "/tools/file":
            return self._tools_file()

        if path == "/tools/mine":
            return self._tools_mine()

        if path == "/tools/disk":
            return self._tools_disk()

        if path == "/tools/lookup":
            return self._tools_lookup()

        if path == "/tools/diag":
            return self._tools_diag()

        if path == "/tools/grades":
            try:
                caps = toolbox.capabilities()
            except Exception:
                caps = {}
            return self._json({"ok": True, "grades": essay.GRADES,
                               "ready": bool(essay._api_key(self.app.cfg)),
                               "caps": caps.get("missing") or {},
                               "caps_ok": {k: v for k, v in caps.items() if isinstance(v, bool)}})

        if not self._authed():
            return self._login_page()
        if path in ("/edit", "/edit.html", "/edit/"):
            return self._serve_file("edit.html")
        if path in ("/grab", "/grab/", "/grab.html"):
            # 大坑：后台的「手动重新抓取课表」链接指向这里，
            # 但后台是用【管理口令】登录的，不带班级口令。
            # 之前一律要求班级口令 -> 管理员点进来会被弹去登录页 ->
            # 生成的抓取代码里就没有 ?k= -> 上传 401。
            if self._admin_authed():
                return self._serve_file("grab.html", public=True)
            return self._serve_file("grab.html")

        if path in ("/edit", "/edit.html", "/edit/"):
            # 同上：手动改课表也在后台的快捷操作里
            if self._admin_authed():
                return self._serve_file("edit.html", public=True)
        return self._serve_file(path.lstrip("/"))

    def do_OPTIONS(self):
        """跨源预检：允许教务系统页面读取抓取脚本。"""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _read_raw(self, length=0):
        """读请求体。支持 Content-Length 和 Transfer-Encoding: chunked。"""
        te = (self.headers.get("Transfer-Encoding") or "").lower()
        try:
            if "chunked" in te:
                chunks = []
                while True:
                    line = self.rfile.readline(65536).strip()
                    if not line:
                        break
                    try:
                        size = int(line.split(b";")[0], 16)
                    except Exception:
                        break
                    if size == 0:
                        self.rfile.readline(65536)
                        break
                    chunks.append(self.rfile.read(size))
                    self.rfile.readline(65536)
                return b"".join(chunks)
        except Exception:
            pass
        if length:
            try:
                return self.rfile.read(length)
            except Exception:
                return b""
        return b""

    def do_POST(self):
        if not self._pre():
            return
        path = urllib.parse.urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)

        # 工具箱上传要流式落盘（最大 100MB，不该整个读进内存），
        # 所以必须在下面 self.rfile.read() 之前拦下来。
        if path == "/tools/upload":
            return self._tools_upload(length)

        raw = self._read_raw(length)
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            body = {}

        if path == "/api/ping":
            return self._send(200, '{"ok":true}', "application/json; charset=utf-8",
                              extra={"Cache-Control": "no-store"})

        # ---- 账号系统（公开接口，门禁之前）----
        if path == "/api/auth/register":
            return self._api_auth_register(body)
        if path == "/api/auth/verify":
            return self._api_auth_verify(body)
        if path == "/api/auth/login":
            return self._api_auth_login(body)
        if path == "/api/auth/logout":
            return self._api_auth_logout()
        if path == "/api/auth/me":
            return self._api_auth_me()

        # QQ 群机器人上报（NapCat -> 本站）。
        # 必须放在口令门禁之前：NapCat 不会带 ?k=，用 qq_webhook_key 鉴权。
        if path == "/api/qq/webhook":
            return self._qq_webhook(body)

        # 定时推送入口：由进程内的调度线程调用（同样用 key 鉴权）
        if path == "/api/qq/push":
            return self._qq_push_route()

        # 早课提醒入口（每天 8:00，周一~周五）
        if path == "/api/qq/morning":
            return self._qq_morning_route()

        # 每天 0 点：清掉昨天的访问记录
        if path == "/api/cron/daily":
            cfg = self._qq_cfg()
            want = str(cfg.get("qq_webhook_key") or "")
            key = (self._query().get("key") or [""])[0]
            if want and key != want and not self._is_local():
                return self._json({"ok": False, "message": "key 不对"}, 403)
            try:
                n = self.app.traffic.clear_all()
            except Exception as e:
                return self._json({"ok": False, "message": "清空失败：%s" % e}, 500)
            self._qq_log("每日清零：删除 %d 个流量文件" % n)
            return self._json({"ok": True, "removed": n})

        # 签到提醒入口（每天 22:00，周五周六不推）
        if path == "/api/qq/checkin":
            return self._qq_checkin_route()

        # 工具箱的这几个接口用「取件码」当凭证，不走班级口令门禁。
        # 必须放在 body 解析【之后】、口令门禁【之前】：
        #   放在前面 -> body 还没解析，UnboundLocalError
        #   放在后面 -> 上传完图片再点批改就 401
        if path == "/tools/essay":
            return self._tools_essay(body)

        if path == "/tools/convert":
            return self._tools_convert(body)

        # 管理后台登录：独立口令，走自己的 cookie。
        # 必须放在 /api/admin/* 和班级口令校验之前。
        if path.startswith("/api/admin/adjust/"):
            return self._api_adjust(path, body)

        if path == "/api/admin-login":
            return self._admin_login(body)

        # ------------------------------------------------------------ 远程编辑通道
        # 由 AI 助手用来远程改这个项目。默认关闭，见 config/secrets.json:
        #     "agent_enabled": true
        #     "agent_token":   "<一长串随机字符>"
        # 班务系统：学生 / 考勤 / 值日，走班级口令
        if path.startswith("/api/class"):
            # 班级成员的锁：校验和开锁不参与口令门禁，走自己的 cookie
            if path == "/api/class/roster-unlock":
                return self._roster_unlock(body)
            return self._api_class(path, body)

        if path.startswith("/api/agent/"):
            return self._api_agent(path)
        # 评分提交：只需要班级口令，允许匿名同学随手点一下
        if path == "/api/rate":
            if not self._authed():
                return self._json({"ok": False, "message": "需要访问口令"}, 401)
            r = self.app.add_rating((body or {}).get("score"))
            if r is None:
                return self._json({"ok": False, "message": "分数不合法"}, 400)
            return self._json({"ok": True, "avg": r.get("avg"), "total": r.get("total")})

        if path == "/api/unlock":
            code = str(body.get("code") or "")
            if self.app.pass_ok(code):
                self.app.authguard.note_success(getattr(self, "_ip", ""))
                # 同一条 keep-alive 连接上的后续请求要用到新状态，先刷掉旧缓存
                self._authed_cache = True
                # 下发口令 cookie。
                # 这一步很关键：把看板「添加到主屏幕」后，启动的是 /dashboard，
                # 没有 cookie 就会每次都被弹回登录页。有了它才能真正当 App 用。
                return self._send(200, json.dumps({"ok": True}, ensure_ascii=False), extra={
                    "Set-Cookie": f"{PASS_COOKIE}={urllib.parse.quote(code)}; Path=/; "
                                  f"Max-Age=2592000; SameSite=Lax; HttpOnly",
                })
            banned, remain, n = self.app.authguard.note_fail(getattr(self, "_ip", ""))
            msg = "口令不正确"
            if banned:
                msg = f"错误次数过多，已暂时拒绝访问（{remain // 60 + 1} 分钟）"
            elif n >= 3:
                msg = f"口令不正确（第 {n} 次，再错 {self.app.authguard.max_fails - n} 次将被暂时封禁）"
            return self._json({"ok": False, "message": msg}, 403)

        # 书签是在【教务系统页面】上跑的，属于跨域请求。
        # 必须放在口令门禁【之前】—— 否则被 401 拦下时响应不带 CORS 头，
        # 浏览器只会报一个看不懂的 CORS 错误，用户根本不知道是口令没带上。
        # 后台的「让服务自己抓一次」按钮打这里。
        # 和 grab 一样，必须在班级口令门禁之前 —— 后台是管理口令登录的。
        if path == "/api/refresh":
            if not (self._admin_authed() or self._authed()):
                return self._json({"ok": False, "message": "需要管理口令"}, 401)
            if not self.app.fetcher:
                return self._json({"ok": False, "message": "未启用自动抓取"}, 400)
            ok, msg = self.app.fetcher.refresh_now()
            return self._json({"ok": ok, "message": msg})

        if path == "/api/import-session":
            # 抓取上传是工具型接口，口令不对只是配置问题，
            # 【绝不能】走 self._authed() —— 那会被 authguard 记成一次爆破，
            # 连着抓几次就把自己的 IP 封了（之前就是这么把用户坑了）。
            #
            # 口令来源按优先级：?k= > cookie > 两者都不对就报错。
            # 班级口令和管理口令都认，免得两台机器 secrets.json 不一致时卡住。
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            code = (qs.get("k") or [""])[0]
            if not code:
                ck = self._cookies().get(PASS_COOKIE, "")
                code = urllib.parse.unquote(ck) if ck else ""

            want_class = (self.app.cfg.get("access_code") or "").strip()
            want_admin = ""
            try:
                want_admin = (self._admin_password() or "").strip()
            except Exception:
                want_admin = ""

            git = bool(code) and (
                (want_class and code == want_class) or
                (want_admin and code == want_admin))

            if not git:
                return self._json({
                    "ok": False,
                    "message": "口令不对（?k= 用班级口令或管理口令）",
                }, 401, cors=True)

            return self._import_session(body)

        # 管理接口只认管理口令：管理员登录后台时通常没有班级口令，
        # 这里必须放行，否则「后台点任何按钮都 401」。
        if path.startswith("/api/admin/"):
            return self._api_admin_post(path, body)

        if not self._authed():
            return self._json({"ok": False, "message": "需要访问口令"}, 401)

        if path == "/api/refresh":
            if not self.app.fetcher:
                return self._json({"ok": False, "message": "未启用自动抓取"}, 400)
            ok, msg = self.app.fetcher.refresh_now()
            return self._json({"ok": ok, "message": msg})

        if path == "/api/import":
            return self._import(body)

        if path == "/api/parse":
            return self._parse_bulk(body)

        if path == "/api/courses":
            return self._save_courses(body)

        if path == "/api/term":
            return self._save_term(body)

        return self._json({"ok": False, "message": "未知接口"}, 404)

    # ---------------------------------------------------------------- API

    def _health(self):
        """健康检查。未带口令只返回最小信息；带口令返回详细状态。"""
        st = self.app.store.get()
        base = {
            "ok": True,
            "uptime": self.app.uptime(),
            "revision": st.get("revision", 0),
            "count": st.get("schedule", {}).get("count", 0),
            "updatedAt": st.get("updatedAt"),
        }
        if self._authed():
            fetcher = self.app.fetcher
            base["detail"] = {
                "hasSession": bool(fetcher and fetcher.has_session()),
                "lastError": st.get("lastError"),
                "lastOkAt": st.get("lastOkAt"),
                "source": st.get("source"),
                "stats": (fetcher.stats if fetcher else None),
                "config": {
                    "auto_login": bool(self.app.cfg.get("auto_login")),
                    "poll_seconds": self.app.cfg.get("poll_seconds"),
                    "term_start": self.app.cfg.get("term_start"),
                    "access_code_set": bool((self.app.cfg.get("access_code") or "").strip()),
                },
            }
        return self._json(base)

    def _ics(self):
        """导出 iCalendar 课表，供手机自带日历订阅。"""
        if not self._authed():
            return self._login_page()
        st = self.app.store.get()
        sched = st.get("schedule", {})

        # 生成前实时套一次覆盖层（调课/停课/加课），
        # 这样改了 overrides.json 之后，订阅端下次拉取就能看到变化，
        # 不必等课表重新导入。
        try:
            import copy as _copy
            sched = _copy.deepcopy(sched)
            overrides.apply(sched, getattr(self.app, "term_start", None))
        except Exception:
            pass

        week, term_start = self.app.current_week(sched.get("maxWeek", 20) or 20)
        if not term_start:
            return self._send(
                400,
                "还没设置「第 1 周起始日」，无法生成日历。\n"
                "请到 /edit 页面填上第 1 周的星期一日期后重试。\n",
                "text/plain; charset=utf-8")

        term = st.get("term") or {}
        name = term.get("name") if isinstance(term, dict) else None
        body, count = timetable.build_ics(
            sched.get("courses", []), term_start,
            max_week=sched.get("maxWeek", 20) or 20,
            section_times=self.app.cfg.get("section_times"),
            calendar_name=name or "班级课表")
        return self._send(200, body, "text/calendar; charset=utf-8", extra={
            "Content-Disposition": 'inline; filename="timetable.ics"',
            "Cache-Control": "no-cache, must-revalidate",
            "X-Event-Count": str(count),
        })

    # ---------------------------------------------------------------- 管理后台 API

    def _api_admin(self, path):
        if not self._admin_authed():
            return self._json({"ok": False, "message": "需要管理口令"}, 401)

        q = self._query()

        def num(key, default):
            try:
                return int((q.get(key) or [default])[0])
            except Exception:
                return default

        if path == "/api/admin/overview":
            return self._json(self._admin_overview())

        if path == "/api/admin/traffic":
            return self._json(self.app.traffic.stats(hours=num("hours", 24)))

        if path == "/api/admin/online":
            mins = num("minutes", 1)
            on, off = self.app.traffic.online_and_offline(minutes=mins)
            return self._json({
                "minutes": mins,
                "count": len(on),
                "online": on,
                "offlineCount": len(off),
                "offline": off,
            })

        if path == "/api/admin/visitors":
            rng = (q.get("range") or ["today"])[0]
            if rng not in ("today", "week", "month", "all"):
                rng = "today"
            lst = self.app.traffic.visitors_in_range(rng, limit=num("limit", 80))
            return self._json({
                "range": rng,
                "count": len(lst),
                "visitors": lst,
            })

        if path == "/api/admin/log":
            return self._json({"records": self.app.traffic.recent(limit=num("limit", 200))})

        if path == "/api/admin/qq/status":
            return self._api_admin_qq_status()

        if path == "/api/admin/security":
            return self._json({
                "bans": self.app.authguard.list_bans(),
                "fails": self.app.authguard.list_fails(),
                "deny": sorted(self.app.iplists.deny),
                "allow": sorted(self.app.iplists.allow),
                "limits": {
                    "perMinute": self.app.ratelimit.per_minute,
                    "hardLimit": self.app.ratelimit.hard_limit,
                    "maxFails": self.app.authguard.max_fails,
                    "banMinutes": self.app.authguard.ban_seconds // 60,
                },
                "accessCodeSet": bool((self.app.cfg.get("access_code") or "").strip()),
            })

        return self._json({"ok": False, "message": "未知的管理接口"}, 404)

    def _schedule_admin_info(self, st):
        """课表信息 + 数据覆盖了哪些周。

        教务系统一次只返回「被请求的那几周」的课表，
        所以很容易出现「只有第 8 周有数据、第 6 周打开是空的」这种情况。
        这里把覆盖情况明确报出来，一眼就能看出要不要重新抓。
        """
        sched = st.get("schedule", {}) or {}
        courses = sched.get("courses", []) or []

        per_week = {}
        for c in courses:
            for w in (c.get("weeks") or []):
                per_week[w] = per_week.get(w, 0) + 1

        covered = sorted(per_week)
        max_week = sched.get("maxWeek", 0) or 0
        week, term_start = self.app.current_week(max_week or 30)
        missing = [w for w in range(1, max_week + 1) if w not in per_week] if max_week else []

        return {
            "revision": st.get("revision", 0),
            "count": sched.get("count", 0),
            "maxWeek": max_week,
            "source": st.get("source"),
            "updatedAt": st.get("updatedAt"),
            "lastError": st.get("lastError"),
            "termStart": term_start,
            "changes": len(st.get("changes") or []),
            "history": len(st.get("history") or []),
            # 数据覆盖情况
            "coveredWeeks": covered,
            "coveredCount": len(covered),
            "missingCount": len(missing),
            "perWeek": [{"week": w, "count": per_week[w]} for w in covered],
            "currentWeek": week,
            "currentWeekHasData": week in per_week,
        }

    def _admin_overview(self):
        st = self.app.store.get()
        f = self.app.fetcher
        stats = f.stats if f else {}
        sec = self.app.traffic.stats(hours=24)
        return {
            "server": {
                "uptime": self.app.uptime(),          # 累计运行，只增不减
                "startedAt": self.app.started_at_str,  # 本次会话启动时刻
                "bind": f"{self.app.cfg.get('bind')}:{self.app.cfg.get('port')}",
                "version": "0.2.0",
            },
            "schedule": self._schedule_admin_info(st),
            "fetch": {
                "enabled": bool(f),
                "hasSession": bool(f and f.has_session()),
                "noSession": bool(f and f.stats.get("noSession")),
                "pollSeconds": self.app.cfg.get("poll_seconds"),
                "autoLogin": bool(self.app.cfg.get("auto_login")),
                "attempts": stats.get("attempts"),
                "ok": stats.get("ok"),
                "fail": stats.get("fail"),
                "consecutiveFail": stats.get("consecutiveFail"),
                "lastOk": stats.get("lastOk"),
                "lastError": stats.get("lastError"),
                "loginAttempts": stats.get("loginAttempts"),
            },
            "traffic": {
                "todayRequests": sec["todayRequests"],
                "todayVisitors": sec["todayVisitors"],
                "uniqueIPs": sec["uniqueIPs"],
                "uniqueDevices": sec["uniqueDevices"],
                "botRequests": sec["botRequests"],
            },
            "security": {
                "banned": len(self.app.authguard.list_bans()),
                "failing": len(self.app.authguard.list_fails()),
                "denied": len(self.app.iplists.deny),
                "allowed": len(self.app.iplists.allow),
                "accessCodeSet": bool((self.app.cfg.get("access_code") or "").strip()),
            },
            "ratings": self.app.ratings(),
        }

    def _api_admin_post(self, path, body):
        if not self._admin_authed():
            return self._json({"ok": False, "message": "需要管理口令"}, 401)

        # ---- QQ 管理 ----
        if path == "/api/admin/qq/save":
            return self._api_admin_qq_save(body)
        if path == "/api/admin/qq/start":
            return self._api_admin_qq_start(body)
        if path == "/api/admin/qq/stop":
            return self._api_admin_qq_stop(body)
        if path == "/api/admin/qq/simulate":
            return self._api_admin_qq_simulate(body)
        if path == "/api/admin/qq/test":
            return self._api_admin_qq_test(body)
        if path == "/api/admin/qq/push":
            try:
                off = int((body or {}).get("offset", 1))
            except Exception:
                off = 1
            ok, msg = self._qq_do_push(off)
            return self._json({"ok": ok, "message": msg})

        # 下面这两个不需要 ip 参数
        if path == "/api/admin/clear-session":
            return self._admin_clear_session()
        if path == "/api/admin/clear-traffic":
            self.app.traffic.clear()
            return self._json({"ok": True, "message": "流量记录已清空"})

        ip = str(body.get("ip") or "").strip()
        if not ip:
            return self._json({"ok": False, "message": "缺少 ip"}, 400)

        if path == "/api/admin/ban":
            minutes = int(body.get("minutes") or 60)
            self.app.authguard.ban(ip, seconds=minutes * 60)
            return self._json({"ok": True, "message": f"已封禁 {ip} {minutes} 分钟"})
        if path == "/api/admin/unban-all":
            if not self._admin_authed():
                return self._json({"ok": False, "message": "需要管理口令"}, 403)
            try:
                cleared = self.app.authguard.clear_all()
            except Exception:
                cleared = 0
            return self._json({"ok": True, "cleared": cleared})

        if path == "/api/admin/unban":
            self.app.authguard.unban(ip)
            return self._json({"ok": True, "message": f"已解封 {ip}"})
        if path == "/api/admin/deny":
            self.app.iplists.add_deny(ip)
            return self._json({"ok": True, "message": f"已加入黑名单：{ip}"})
        if path == "/api/admin/allow":
            self.app.iplists.add_allow(ip)
            return self._json({"ok": True, "message": f"已加入白名单：{ip}"})
        if path == "/api/admin/forget":
            self.app.iplists.remove(ip)
            self.app.authguard.unban(ip)
            return self._json({"ok": True, "message": f"已清除 {ip} 的所有记录"})
        if path == "/api/admin/clear-traffic":
            self.app.traffic.clear()
            return self._json({"ok": True, "message": "流量记录已清空"})
        return self._json({"ok": False, "message": "未知操作"}, 404)

    def _admin_clear_session(self):
        """删掉保存的抓取会话，让服务回到「手动维护」状态。"""
        from . import client as client_mod
        removed = []
        for p in (client_mod.SESSION_FILE, client_mod.SESSION_FILE + ".tmp",
                  os.path.join(DATA_DIR, "last-import.json")):
            if os.path.exists(p):
                try:
                    os.remove(p)
                    removed.append(os.path.basename(p))
                except OSError:
                    pass
        if self.app.fetcher:
            self.app.fetcher.client = None
            self.app.fetcher.stats["noSession"] = True
            self.app.fetcher.stats["lastError"] = "尚未配置抓取会话"
        msg = ("已清除 " + "、".join(removed)) if removed else "没有可清除的会话"
        return self._json({"ok": True, "message": msg})

    def _api_get(self, path):
        if not self._authed():
            return self._json({"ok": False, "message": "需要访问口令"}, 401)
        if path == "/api/state":
            return self._json(self.app.state_payload())
        if path == "/api/schedule":
            return self._json(self.app.state_payload())
        if path == "/api/history":
            return self._json({"history": self.app.store.history()})
        if path == "/api/diff":
            q = self._query()
            a = int((q.get("from") or ["0"])[0])
            b = int((q.get("to") or ["0"])[0])
            return self._json({"diff": self.app.store.diff_between(a, b)})
        if path == "/api/raw":
            st = self.app.store.get()
            return self._json(st.get("rawSample"))

        # 看板「系统监测」页的数据：CPU / 内存 / 磁盘 / 进程 / 运行时长 等
        if path in ("/api/sysinfo", "/api/system"):
            return self._api_sysinfo()

        return self._json({"ok": False, "message": "未知接口"}, 404)

    # ---------------------------------------------------------------- 远程编辑通道

    # 只允许碰这些后缀，别的（.exe/.dll/.sys…）一律拒绝
    AGENT_EXT = (".py", ".js", ".css", ".html", ".json", ".md", ".bat", ".ps1",
                 ".txt", ".webmanifest", ".yml", ".yaml", ".log")
    # 这些目录即使在里面也不给写（凭据 / 密钥）
    AGENT_DENY = ("config", "data" + os.sep + "probe")

    def _agent_root(self):
        """项目根目录：data 的上一级。"""
        return os.path.dirname(DATA_DIR)

    def _agent_path(self, rel, for_write=False):
        """把相对路径解析成安全的绝对路径；不合法返回 None。

        防的是路径穿越（../../windows/system32）和乱写可执行文件。
        """
        rel = (rel or "").replace("\\", "/").strip().lstrip("/")
        if not rel or ".." in rel.split("/"):
            return None
        root = self._agent_root()
        full = os.path.normpath(os.path.join(root, rel.replace("/", os.sep)))
        if full != root and not full.startswith(root + os.sep):
            return None
        ext = os.path.splitext(full)[1].lower()
        if ext not in self.AGENT_EXT:
            return None
        low = full[len(root) + 1:].lower()
        for d in self.AGENT_DENY:
            if low.startswith(d.replace("\\", "/").lower()):
                return None
        return full

    def _agent_authed(self, body):
        """校验远程编辑口令。

        三个前提，缺一不可：
          1. config 里 agent_enabled 必须是 true（默认关，随时能一键关掉）
          2. 请求头 X-Agent-Token 必须和 agent_token 完全一致
          3. 口令长度必须 >= 24，避免有人设个 "123" 就等于没设
        口令只从请求头读，不走 URL —— 避免泄漏进访问日志和 Referer。
        """
        cfg = self.app.cfg
        try:
            with open(os.path.join(os.path.dirname(DATA_DIR), "config",
                                   "secrets.json"), encoding="utf-8") as f:
                s = json.load(f)
        except Exception:
            s = {}
        if not s.get("agent_enabled"):
            return False
        want = str(s.get("agent_token") or "")
        if len(want) < 24:
            return False
        got = self.headers.get("X-Agent-Token") or ""
        return bool(got) and hmac.compare_digest(got, want)

    def _api_adjust(self, path, body=None):
        """快捷调课：查当周课程 / 提交调整。"""
        import copy as _copy
        import datetime as _dt

        # do_POST 已经读过 body，这里不能再读（会阻塞）
        if body is None:
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
            except Exception:
                body = {}
        if not isinstance(body, dict):
            body = {}

        q = self._query()

        def pick(k, default=None):
            v = body.get(k)
            if v is None:
                v = (q.get(k) or [None])[0]
            return default if v is None else v

        import json as _json
        import os as _os

        BASE = _os.path.join(_os.path.dirname(_os.path.dirname(
            _os.path.abspath(__file__))), "data", "schedule_base.json")

        def _load_base(st_now):
            """原始课表：第一次调课时把当前课表存一份做基底。"""
            try:
                with open(BASE, encoding="utf-8") as f:
                    return _json.load(f)
            except Exception:
                pass
            base = _copy.deepcopy(st_now.get("schedule", {}) or {})
            try:
                _os.makedirs(_os.path.dirname(BASE), exist_ok=True)
                tmp = BASE + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    _json.dump(base, f, ensure_ascii=False)
                _os.replace(tmp, BASE)
            except Exception:
                pass
            return base

        def _rebuild(st_now):
            """基底 + 当前 overrides = 新课表"""
            base = _copy.deepcopy(_load_base(st_now))
            try:
                overrides.apply(base, getattr(self.app, "term_start", None))
            except Exception:
                pass
            return base

        def _new_id():
            import uuid
            return uuid.uuid4().hex[:10]

        def _now_iso():
            return _dt.datetime.now().strftime("%Y-%m-%d %H:%M")

        def _who():
            try:
                u = self._sess_user()
                if u:
                    return u.get("name") or u.get("email") or "已登录用户"
            except Exception:
                pass
            try:
                if self._authed():
                    return "管理员"
            except Exception:
                pass
            return "未知"

        st = self.app.store.get()
        sched = _copy.deepcopy(st.get("schedule", {}) or {})
        try:
            overrides.apply(sched, getattr(self.app, "term_start", None))
        except Exception:
            pass
        courses = sched.get("courses") or []

        # ---------------- 列出某周的课 ----------------
        if path.endswith("/list"):
            try:
                week = int(pick("week", 0) or 0)
            except Exception:
                week = 0
            if not week:
                week, _ = self.app.current_week(sched.get("maxWeek", 20) or 20)

            rows = []
            rooms = {}
            for c in courses:
                wks = c.get("weeks") or []
                if week not in wks and wks:
                    continue
                room = str(c.get("room") or "")
                if room:
                    rooms[room] = rooms.get(room, 0) + 1
                rows.append({
                    "name": c.get("name") or "",
                    "weekday": c.get("weekday") or 1,
                    "start": c.get("startSection") or 1,
                    "end": c.get("endSection") or 1,
                    "room": room,
                    "teacher": c.get("teacher") or "",
                    "weeks": wks,
                })
            rows.sort(key=lambda x: (x["weekday"], x["start"]))
            room_list = sorted(rooms.keys(),
                               key=lambda r: (-rooms[r], r))
            return self._json({"ok": True, "week": week,
                               "courses": rows, "rooms": room_list})

        # ---------------- 历史记录 ----------------
        if path.endswith("/history"):
            ovr = overrides.load()
            names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
            out = []
            for r in ovr.get("rooms") or []:
                wd = int(r.get("weekday") or 1)
                sec = r.get("sections") or [0, 0]
                out.append({
                    "id": r.get("id") or "",
                    "at": r.get("at") or "",
                    "by": r.get("by") or "",
                    "kind": "room",
                    "title": "改教室 · %s" % (r.get("name") or ""),
                    "detail": "%s %s-%s 节 · 第 %s 周 → %s" % (
                        names[wd - 1] if 1 <= wd <= 7 else "",
                        sec[0], sec[1],
                        "/".join(str(w) for w in (r.get("weeks") or [])[:6]),
                        r.get("room") or ""),
                })
            for r in ovr.get("moves") or []:
                wd = int(r.get("weekday") or 1)
                frm = r.get("from") or [0, 0]
                to = r.get("to") or [0, 0]
                out.append({
                    "id": r.get("id") or "",
                    "at": r.get("at") or "",
                    "by": r.get("by") or "",
                    "kind": "time",
                    "title": "调课时 · %s" % (r.get("name") or ""),
                    "detail": "%s %s-%s 节 → %s-%s 节 · 第 %s 周" % (
                        names[wd - 1] if 1 <= wd <= 7 else "",
                        frm[0], frm[1], to[0], to[1],
                        "/".join(str(w) for w in (r.get("weeks") or [])[:6])),
                })
            out.sort(key=lambda x: x.get("at") or "", reverse=True)
            return self._json({"ok": True, "items": out})

        # ---------------- 删除某条 ----------------
        if path.endswith("/delete"):
            rid = str(pick("id") or "")
            if not rid:
                return self._json({"ok": False, "message": "缺 id"}, 400)
            ovr = overrides.load()
            before = len(ovr.get("rooms") or []) + len(ovr.get("moves") or [])
            ovr["rooms"] = [r for r in (ovr.get("rooms") or [])
                            if r.get("id") != rid]
            rule_removed = None
            for r in (ovr.get("rooms") or []):
                if r.get("id") == rid:
                    rule_removed = {"kind": "room", "rule": r}
                    break
            if rule_removed is None:
                for r in (ovr.get("moves") or []):
                    if r.get("id") == rid:
                        rule_removed = {"kind": "time", "rule": r}
                        break
            ovr["rooms"] = [r for r in (ovr.get("rooms") or [])
                            if r.get("id") != rid]
            ovr["moves"] = [r for r in (ovr.get("moves") or [])
                            if r.get("id") != rid]
            after = len(ovr.get("rooms") or []) + len(ovr.get("moves") or [])
            if after == before:
                return self._json({"ok": False, "message": "没找到这条记录"}, 404)
            overrides.save(ovr)

            # 只删记录，不动课表（当前改动保留）
            return self._json({"ok": True, "message": "已撤销"})

        # ---------------- 提交调整 ----------------
        if path.endswith("/apply"):
            kind = str(pick("kind") or "time")
            name = str(pick("name") or "")
            try:
                wd = int(pick("weekday") or 0)
                s1 = int(pick("start") or 0)
                e1 = int(pick("end") or 0)
                week = int(pick("week") or 0)
                wd2 = int(pick("toWeekday") or 0)
                s2 = int(pick("toStart") or 0)
                e2 = int(pick("toEnd") or 0)
            except Exception:
                return self._json({"ok": False, "message": "参数不对"}, 400)
            if not name or not wd or not s1:
                return self._json({"ok": False, "message": "没选课"}, 400)

            # 生效周次
            scope = str(pick("scope") or "single")
            hit = None
            for c in courses:
                if (c.get("name") == name and c.get("weekday") == wd
                        and c.get("startSection") == s1
                        and c.get("endSection") == e1
                        and week in (c.get("weeks") or [])):
                    hit = c
                    break
            all_weeks = list((hit or {}).get("weeks") or [week])

            if scope == "single":
                weeks = [week]
            elif scope == "forever":
                weeks = all_weeks
            else:
                weeks = list(pick("weeks") or [])
                until = str(pick("until") or "")
                ts = getattr(self.app, "term_start", None)
                if until and ts:
                    try:
                        if isinstance(ts, str):
                            ts = _dt.date.fromisoformat(ts[:10])
                        cut = _dt.date.fromisoformat(until[:10])
                        endw = (cut - ts).days // 7 + 1
                        weeks = [w for w in all_weeks if week <= w <= endw]
                    except Exception:
                        weeks = [week]
                if not weeks:
                    weeks = [week]
            weeks = [int(w) for w in weeks if str(w).strip()]

            ovr = overrides.load()
            if kind == "room":
                room = str(pick("room") or "").strip()
                if not room:
                    return self._json({"ok": False, "message": "没填教室"}, 400)
                ovr.setdefault("rooms", []).append({
                    "id": _new_id(), "at": _now_iso(), "by": _who(),
                    "name": name, "weekday": wd, "sections": [s1, e1],
                    "weeks": weeks, "room": room,
                    "old": str((hit or {}).get("room") or ""),
                })
            else:
                if not (wd2 and s2):
                    return self._json({"ok": False, "message": "没选目标节次"}, 400)
                ovr.setdefault("moves", []).append({
                    "id": _new_id(), "at": _now_iso(), "by": _who(),
                    "name": name, "weekday": wd, "from": [s1, e1],
                    "to": [s2, e2], "weeks": weeks,
                    "toWeekday": wd2,
                })
                # 对调：把对方也挪回来
                if str(pick("mode") or "") == "swap":
                    other = None
                    for c in courses:
                        if (c.get("weekday") == wd2
                                and c.get("startSection") == s2
                                and c.get("endSection") == e2
                                and week in (c.get("weeks") or [])):
                            other = c
                            break
                    if other:
                        ovr.setdefault("moves", []).append({
                            "id": _new_id(), "at": _now_iso(), "by": _who(),
                            "name": other.get("name") or "",
                            "weekday": wd2, "from": [s2, e2],
                            "to": [s1, e1], "weeks": weeks,
                        })
            overrides.save(ovr)

            # 立即重建课表并提交（revision 变化 → 前台和机器人都会拿到）
            sched2 = _copy.deepcopy(st.get("schedule", {}) or {})
            try:
                overrides.apply(sched2, getattr(self.app, "term_start", None))
            except Exception:
                pass
            try:
                self.app.store.commit(sched2, source="快捷调课")
            except Exception as ex:
                return self._json({"ok": False, "message": "已保存规则，但重建失败：%s" % ex}, 500)

            return self._json({"ok": True, "message": "已生效",
                               "weeks": weeks})

        return self._json({"ok": False, "message": "未知接口"}, 404)

    def _api_agent(self, path):
        """AI 助手用的读写接口。只在这个项目目录内、只碰白名单后缀。"""
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
        except Exception:
            body = {}

        if not self._agent_authed(body):
            self.app.authguard.note_fail(getattr(self, "_ip", ""))
            return self._json({"ok": False, "message": "未授权"}, 403)

        action = path[len("/api/agent/"):].strip("/")

        # ---- 列目录 ----
        if action == "list":
            rel = body.get("path") or ""
            root = self._agent_root()
            full = os.path.normpath(os.path.join(root, rel.replace("/", os.sep))) if rel else root
            if full != root and not full.startswith(root + os.sep):
                return self._json({"ok": False, "message": "路径不合法"}, 400)
            if not os.path.isdir(full):
                return self._json({"ok": False, "message": "不是目录"}, 400)
            out = []
            for name in sorted(os.listdir(full)):
                fp = os.path.join(full, name)
                out.append({
                    "name": name,
                    "dir": os.path.isdir(fp),
                    "size": os.path.getsize(fp) if os.path.isfile(fp) else 0,
                })
            return self._json({"ok": True, "path": rel, "entries": out})

        # ---- 读文件 ----
        if action == "read":
            full = self._agent_path(body.get("path"))
            if not full or not os.path.isfile(full):
                return self._json({"ok": False, "message": "文件不存在或不允许"}, 400)
            if os.path.getsize(full) > 2 * 1024 * 1024:
                return self._json({"ok": False, "message": "文件太大"}, 400)
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                return self._json({"ok": True, "content": f.read()})

        # ---- 写文件 ----
        if action == "write":
            full = self._agent_path(body.get("path"), for_write=True)
            if not full:
                return self._json({"ok": False, "message": "路径或后缀不允许"}, 400)
            content = body.get("content")
            if not isinstance(content, str):
                return self._json({"ok": False, "message": "content 必须是字符串"}, 400)
            if len(content) > 2 * 1024 * 1024:
                return self._json({"ok": False, "message": "内容太大"}, 400)
            d = os.path.dirname(full)
            if not os.path.isdir(d):
                os.makedirs(d, exist_ok=True)
            # 写之前留一份 .bak，改坏了能立刻回滚
            if os.path.isfile(full):
                try:
                    with open(full, "rb") as src, open(full + ".bak", "wb") as dst:
                        dst.write(src.read())
                except Exception:
                    pass
            tmp = full + ".tmp"
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                f.write(content)
            os.replace(tmp, full)
            self._agent_log("write", full)
            return self._json({"ok": True, "path": body.get("path"),
                               "bytes": len(content.encode("utf-8"))})

        # ---- 重启服务（只重启课表服务本身，不执行任意命令）----
        if action == "restart":
            self._agent_log("restart", "")
            # 交给 run.bat 的重试循环：退出码非 0 它就会 5 秒后重新拉起
            def _die():
                time.sleep(0.4)
                os._exit(3)
            threading.Thread(target=_die, daemon=True).start()
            return self._json({"ok": True, "message": "正在重启，约 5 秒后恢复"})

        return self._json({"ok": False, "message": "未知操作"}, 404)

    def _agent_log(self, action, target):
        """所有远程改动都记一笔，回头能查是谁什么时候改的。"""
        try:
            p = os.path.join(DATA_DIR, "agent.log")
            line = "%s\t%s\t%s\t%s\n" % (
                time.strftime("%Y-%m-%d %H:%M:%S"),
                getattr(self, "_ip", "?"), action, target)
            with open(p, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            pass
    # ---------------------------------------------------------------- 班务系统

    def _api_class(self, path, body=None):
        # 班级成员名单要单独验证（cookie 1 小时有效）
        try:
            _act = ""
            _qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            _act = (_qs.get("action") or [""])[0]
            if not _act:
                _b = body if isinstance(body, dict) else {}
                _act = str(_b.get("action") or "")
            if _act in ("students", "students/save", "students/remove",
                        "students/import", "students/upsert") or _act.startswith("students"):
                if not self._roster_ok():
                    return self._json({"ok": False, "locked": True,
                                       "message": "班级成员未解锁"}, 403)
        except Exception:
            pass

        """班务系统的接口。GET 用来读，POST 用来写。

        权限用班级口令 —— 这是给班级自己用的工具，
        名单、考勤、值日都在这一个 JSON 里。
        """
        # 两种身份都放行：
        #   · 同学带班级口令（?k= 或 cookie）—— 只能看 + 签到
        #   · 管理员带管理口令 —— 全部操作
        # 管理后台是用管理口令登录的，不带班级口令，
        # 所以这里必须放行管理员，否则后台发起签到会被 401 拦住。
        if not self._authed() and not self._admin_authed():
            return self._json({"ok": False, "message": "需要访问口令"}, 401)

        cs = classmgmt.store
        action = path[len("/api/class"):].strip("/")

        # 谁能改？只有管理后台。
        # 班务系统页面是给全班看的（查名单、看值日、打电话），
        # 增删改一律要管理口令，免得同学手滑把考勤改了。
        READ_ONLY_ACTIONS = ("", "all", "students", "attendance", "attendance/stats",
                             "duty", "whoami")
        if action == "whoami":
            return self._json({"ok": True, "admin": bool(self._admin_authed())})
        # 签到是同学要做的动作，所以「checkin/sign」对班级口令开放；
        # 发布/关闭/看统计依然只有管理员能动。
        STUDENT_ACTIONS = READ_ONLY_ACTIONS + ("checkin", "checkin/sign")
        if action not in STUDENT_ACTIONS and not self._admin_authed():
            return self._json({"ok": False, "message": "这个操作只有管理员能做"}, 403)
        # 请求体由 do_POST 读完再传进来。
        # 之前这里又去 self.rfile.read()，可 body 已经被消费掉了，
        # 于是读操作一直阻塞 -> 请求超时 -> 前端看到的就是「HTTP None」。
        body = body if isinstance(body, dict) else {}
        q = self._query()

        def arg(k, default=""):
            return (body.get(k) if k in body else (q.get(k) or [default])[0])

        # ---- 一次性拿全部（前端首屏用，减少来回） ----
        if action in ("", "all"):
            st = cs.students()
            return self._json({
                "ok": True,
                "students": st,
                "statuses": [{"key": k, "name": n} for k, n in classmgmt.STATUSES],
                "attendance": cs.attendance_range(60),
                "duty": cs.duty(),
                "stats": cs.attendance_stats(30),
                "count": len(st),
            })

        # ---- 签到打卡 ----
        if action == "checkin":
            c = cs.checkin()
            task = c.get("current")
            st = classmgmt.ClassStore.checkin_state(task) if task else "none"
            recs = (c.get("records") or {}).get((task or {}).get("id") or "", {}) or {}
            return self._json({
                "ok": True,
                "task": task,
                "state": st,
                "count": len(recs),
                "records": sorted(recs.values(), key=lambda r: r.get("at") or 0),
            })

        if action == "checkin/sign":
            rec, err = cs.sign_checkin(str(body.get("name") or ""), str(body.get("no") or ""))
            if err:
                return self._json({"ok": False, "message": err}, 400)
            return self._json({"ok": True, "record": rec})

        if action == "checkin/publish":
            task = cs.publish_checkin(str(body.get("title") or "签到"),
                                      str(body.get("start") or ""),
                                      str(body.get("end") or ""))
            return self._json({"ok": True, "task": task})

        if action == "checkin/close":
            cs.close_checkin()
            return self._json({"ok": True})

        if action == "checkin/stats":
            return self._json({"ok": True, "stats": cs.checkin_stats(arg("task") or None)})

        if action == "checkin/history":
            c = cs.checkin()
            out = []
            for tid in (c.get("history") or [])[:40]:
                recs = (c.get("records") or {}).get(tid, {}) or {}
                out.append({"id": tid, "count": len(recs)})
            return self._json({"ok": True, "history": out})
        # ---- 学生 ----
        if action == "students":
            return self._json({"ok": True, "students": cs.students()})

        if action == "students/save":
            rows = body.get("rows")
            if rows is None:
                rows = classmgmt.ClassStore.parse_roster(body.get("text") or "")
            saved = cs.save_students(rows)
            return self._json({"ok": True, "count": len(saved), "students": saved})

        if action == "students/import":
            rows = classmgmt.ClassStore.parse_roster(body.get("text") or "")
            if not rows:
                return self._json({"ok": False, "message": "没解析出任何学生"}, 400)
            cur = cs.students()
            exist = {s["name"]: s for s in cur}
            added = 0
            for r in rows:
                if r["name"] in exist:
                    continue
                cur.append({"id": "s%d" % int(time.time() * 1000 + added),
                            "no": r.get("no", ""), "name": r["name"],
                            "gender": r.get("gender", ""), "phone": "",
                            "dorm": "", "note": r.get("note", ""), "active": True})
                added += 1
            cs.save_students(cur)
            return self._json({"ok": True, "parsed": len(rows), "added": added})

        if action == "students/upsert":
            sid = cs.upsert_student(body.get("student") or body)
            if not sid:
                return self._json({"ok": False, "message": "缺少姓名"}, 400)
            return self._json({"ok": True, "id": sid, "students": cs.students()})

        if action == "students/remove":
            ok = cs.remove_student(str(arg("id")))
            return self._json({"ok": ok, "students": cs.students()})

        # ---- 考勤 ----
        if action == "attendance":
            date = str(arg("date"))
            if date:
                return self._json({"ok": True, "date": date, "day": cs.attendance(date)})
            return self._json({"ok": True, "attendance": cs.attendance_range(60)})

        if action == "attendance/set":
            ok = cs.set_attendance(str(arg("date")), str(arg("id")), str(arg("status")))
            return self._json({"ok": ok})

        if action == "attendance/bulk":
            ok = cs.set_attendance_bulk(str(body.get("date")), body.get("mapping") or {})
            return self._json({"ok": ok})

        if action == "attendance/stats":
            return self._json({"ok": True, "stats": cs.attendance_stats(int(arg("days") or 30))})

        # ---- 值日 ----
        if action == "duty":
            return self._json({"ok": True, "duty": cs.duty()})

        if action == "duty/save":
            ok = cs.save_duty(body)
            return self._json({"ok": ok, "duty": cs.duty()})

        if action == "duty/generate":
            # 排班范围固定：周一~周五 + 周日，只有周六不打扫。
            # 前端就算传了 skipWeekend 也不认，免得旧页面把周日也跳过。
            sched = cs.generate_duty(str(body.get("start") or ""),
                                     int(body.get("days") or 30),
                                     group_ids=body.get("groups"),
                                     weekdays=body.get("weekdays"))
            return self._json({"ok": True, "schedule": sched, "duty": cs.duty()})

        return self._json({"ok": False, "message": "未知操作"}, 404)
    def _api_sysinfo(self):
        """系统监测数据。

        权限跟课表一样用班级口令 —— 里面只是 CPU/内存这类健康指标，
        没有敏感内容，同学看到了也无所谓。
        """
        snap = self.app.sysinfo.snapshot()
        try:
            t = self.app.traffic.stats(hours=24)
        except Exception:
            t = {}
        cfg = self.app.cfg
        snap["service"] = {
            "uptime": self.app.uptime(),          # 累计运行（只增不减）
            "revision": self.app.store.get().get("revision", 0),
            "port": cfg.get("port"),
            "bind": cfg.get("bind"),
            "python": "%d.%d.%d" % tuple(__import__("sys").version_info[:3]),
            "pid": os.getpid(),
            "threads": threading.active_count(),
            "pollSeconds": cfg.get("poll_seconds"),
        }
        snap["traffic"] = {
            "todayRequests": t.get("todayRequests", 0),
            "todayVisitors": t.get("todayVisitors", 0),
            "uniqueIPs": t.get("uniqueIPs", 0),
            "botRequests": t.get("botRequests", 0),
        }
        try:
            snap["security"] = {
                "banned": len(self.app.authguard.banned()),
                "denied": len(self.app.iplists.denied()),
                "allowed": len(self.app.iplists.allowed()),
            }
        except Exception:
            snap["security"] = {}
        snap["ok"] = True
        return self._json(snap)

    def _import(self, body):
        """手工导入课表：接受原始接口响应或已归一化数据。"""
        raw = body.get("raw")
        if raw is None and body.get("courses"):
            sched = {"courses": body["courses"],
                     "maxWeek": body.get("maxWeek", 20),
                     "count": len(body["courses"])}
            raw = None
        elif raw is not None:
            sched = normalize.normalize_schedule(raw)
        else:
            return self._json({"ok": False, "message": "缺少 raw 或 courses"}, 400)

        changed, rev, changes = self.app.store.commit(
            sched, term=body.get("term"), raw_sample=raw, source=body.get("source") or "手工导入")
        if changed:
            self.app.hub.publish("update", {"revision": rev, "changes": changes})
        return self._json({"ok": True, "count": sched["count"], "changed": changed,
                           "revision": rev, "changes": changes})

    def _parse_bulk(self, body):
        """解析用户粘贴的批量文本，只预览不入库。"""
        text = body.get("text") or ""
        courses, errors, max_week = normalize.parse_bulk_text(
            text, int(self.app.cfg.get("max_week", 30)))
        return self._json({"ok": True, "courses": courses, "errors": errors,
                           "count": len(courses), "maxWeek": max_week})

    def _save_courses(self, body):
        """保存编辑器提交的课程列表（替换式）。"""
        courses = body.get("courses")
        if not isinstance(courses, list):
            return self._json({"ok": False, "message": "缺少 courses"}, 400)

        clean = []
        for c in courses:
            if not isinstance(c, dict) or not (c.get("name") or "").strip():
                continue
            wd = int(c.get("weekday") or 0)
            s = int(c.get("startSection") or 0)
            e = int(c.get("endSection") or s)
            weeks = [int(w) for w in (c.get("weeks") or []) if str(w).isdigit() or isinstance(w, int)]
            if not (1 <= wd <= 7) or s < 1 or e < s:
                continue
            clean.append({
                "id": c.get("id") or f"edit-{len(clean)+1}",
                "name": str(c.get("name")).strip(),
                "teacher": str(c.get("teacher") or "").strip(),
                "room": str(c.get("room") or "").strip(),
                "className": str(c.get("className") or "").strip(),
                "campus": "", "credit": "", "type": "",
                "weekday": wd, "startSection": s, "endSection": e,
                "weeks": sorted(set(weeks)) or list(range(1, 17)),
                "raw": {"source": "editor"},
            })

        if not clean:
            return self._json({"ok": False, "message": "没有有效课程"}, 400)

        max_week = int(body.get("maxWeek") or 0)
        if max_week < 1:
            max_week = max(max(c["weeks"]) for c in clean)
        sched = {"courses": clean, "maxWeek": max_week, "count": len(clean)}

        changed, rev, changes = self.app.store.commit(
            sched, term=body.get("term"), raw_sample=None, source="手动录入")
        if changed:
            self.app.hub.publish("update", {"revision": rev, "changes": changes})
        return self._json({"ok": True, "count": len(clean), "changed": changed,
                           "revision": rev, "changes": changes})

    def _save_term(self, body):
        """保存学期起始日（用于自动定位当前周）。"""
        from . import config as config_mod
        import re as _re

        v = str(body.get("term_start") or "").strip()
        if v and not _re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            return self._json({"ok": False, "message": "日期格式应为 YYYY-MM-DD"}, 400)
        try:
            config_mod.update_file({"term_start": v})
        except Exception as e:
            return self._json({"ok": False, "message": f"写入配置失败：{e}"}, 500)
        self.app.cfg["term_start"] = v
        return self._json({"ok": True, "term_start": v})

    def _import_session(self, body):
        """接收浏览器书签上传的「会话 + 课表」，之后就能自动抓取了。"""
        from . import client as client_mod

        raw = body.get("raw")
        token = str(body.get("token") or "")
        cookie_str = str(body.get("cookie") or "")
        base = str(body.get("base") or "") or client_mod.DEFAULT_BASE

        cookies = {}
        for part in cookie_str.split(";"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                cookies[k.strip()] = v.strip()

        # 浏览器那边可能同时给了「整学期」和「单周」两份数据，优先用整学期
        all_weeks = body.get("allWeeks")
        one_week = body.get("oneWeek")
        if not raw:
            raw = all_weeks or one_week

        parsed_raw = None
        for cand in (all_weeks, one_week, raw):
            if isinstance(cand, (dict, list)):
                parsed_raw = cand
                break
            if isinstance(cand, str) and cand.strip():
                try:
                    parsed_raw = json.loads(cand)
                    break
                except Exception:
                    continue

        imported = 0
        if parsed_raw is not None:
            data = parsed_raw.get("data") if isinstance(parsed_raw, dict) else parsed_raw
            sched = normalize.normalize_schedule(data)
            # 手改的调课/停课重新套一遍，免得被学校原始课表冲掉
            try:
                overrides.apply(sched, getattr(self.app, "term_start", None))
            except Exception:
                pass
            if sched["count"]:
                changed, rev, changes = self.app.store.commit(
                    sched, term=self.app.store.get().get("term"),
                    raw_sample=parsed_raw, source="浏览器一键导入")
                imported = sched["count"]
                if changed:
                    self.app.hub.publish("update", {"revision": rev, "changes": changes})

        # 把浏览器那边上报的完整诊断信息存下来，方便排查
        # （不含课程原始数据的完整副本，避免文件过大）
        try:
            diag = {k: v for k, v in body.items()
                    if k not in ("raw", "allWeeks", "oneWeek")}
            diag["rawLength"] = len(raw) if isinstance(raw, str) else 0
            diag["rawHead"] = (raw[:600] if isinstance(raw, str) else "")
            diag["allWeeksLength"] = len(all_weeks) if isinstance(all_weeks, str) else 0
            diag["oneWeekLength"] = len(one_week) if isinstance(one_week, str) else 0
            diag["receivedAt"] = time.time()
            diag["fromIP"] = getattr(self, "_ip", "")
            path = os.path.join(DATA_DIR, "last-import.json")
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(diag, f, ensure_ascii=False, indent=1)
            os.replace(tmp, path)
        except Exception:
            pass

        # 保存会话，供后续定时抓取复用
        kicked = False
        if token or cookies:
            try:
                state = client_mod.SessionState(cookies=cookies, access_token=token,
                                                base=base, note="浏览器一键导入")
                state.save()
                if self.app.fetcher:
                    self.app.fetcher.client = None      # 让它重新载入新会话
                    self.app.fetcher._last_login_attempt = 0
                    self.app.fetcher.stats["noSession"] = False
                    self.app.fetcher.kick()             # 别等下一轮，立刻抓一次
                    kicked = True
            except Exception:
                pass

        msg = f"已导入 {imported} 门课"
        if token:
            msg += "，会话已保存" + ("，正在立刻抓取…" if kicked else "，自动抓取下次轮询生效")
        return self._send(200, json.dumps({
            "ok": True, "imported": imported, "kicked": kicked,
            "hasToken": bool(token), "cookies": sorted(cookies.keys()),
            "message": msg,
        }, ensure_ascii=False), cors=True)

    # ---------------------------------------------------------------- SSE

    def _sse(self):
        if not self._authed():
            return self._json({"ok": False, "message": "需要访问口令"}, 401)
        # SSE 是「无限长」的响应，没有 Content-Length。
        # HTTP/1.1 下必须明确告诉对端：这条连接不会复用，读完就关，
        # 否则客户端会一直等 Content-Length 而卡住。
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        q = self.app.hub.subscribe()
        try:
            st = self.app.state_payload()
            self.wfile.write(f"event: hello\ndata: {json.dumps({'revision': st['revision']})}\n\n"
                             .encode())
            self.wfile.flush()
            last_ping = time.time()
            while True:
                try:
                    event, data = q.get(timeout=20)
                    self.wfile.write(f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                                     .encode())
                    self.wfile.flush()
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                if time.time() - last_ping > 3600:
                    break
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.app.hub.unsubscribe(q)

    # ---------------------------------------------------------------- 静态

    def _login_page(self, next_path="/"):
        html = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PaperCloud · 26 现代通信技术1班 班务系统</title>
<meta name="description" content="PaperCloud 是 26 现代通信技术1班的内部班务系统，提供课程表、值日与考勤查询，仅供本班同学使用。">
<meta property="og:title" content="PaperCloud 班务系统">
<meta property="og:description" content="26 现代通信技术1班内部使用的课程表与班务页面，非商业站点。">
<meta name="robots" content="index,follow">
<style>
 body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
      background:#0f1720;color:#e8eef5;display:flex;align-items:center;justify-content:center;height:100vh}
 .box{background:#182533;padding:32px 28px;border-radius:16px;width:min(92vw,340px);box-shadow:0 12px 40px #0006}
 h1{font-size:19px;margin:0 0 6px}p{color:#8ba0b6;font-size:13px;margin:0 0 20px}
 input{width:100%;box-sizing:border-box;padding:12px 14px;border-radius:10px;border:1px solid #2c3f52;
       background:#0f1a24;color:#e8eef5;font-size:16px;outline:none}
 input:focus{border-color:#3d9df6}
 button{margin-top:14px;width:100%;padding:12px;border:0;border-radius:10px;background:#3d9df6;
        color:#fff;font-size:16px;font-weight:600;cursor:pointer}
 .err{color:#ff7b72;font-size:13px;margin-top:10px;min-height:18px}
 .note{margin-top:18px;padding:12px 13px;border-radius:11px;background:#0e1a26;
       border:1px solid #22344a;color:#7f93a8;font-size:11.5px;line-height:1.75;text-align:left}
 .note b{color:#b7c8da;font-weight:700}
</style></head><body><div class="box">
<h1>PaperCloud · 班级课表</h1>
<p>26 现代通信技术1班 内部班务系统<br>请输入班级共享口令</p>
<input id="c" type="password" inputmode="text" placeholder="班级口令" autocomplete="off">
<button onclick="go()">进入</button><div class="err" id="e"></div>
<div class="note" id="ktSiteNote">
  <b>关于本站</b><br>
  本站为高校班级自建的课程表与班务页面，仅供本班 49 名同学使用。<br>
  口令是全班共享的访问密码，<b>不收集任何个人账号、密码或身份信息</b>，
  也不含广告、支付与诱导分享。<br>
  联系：paperapple0311@icloud.com
</div>
</div><script>
async function go(){
  const c=document.getElementById('c').value.trim(), e=document.getElementById('e');
  e.textContent='';
  const r=await fetch('/api/unlock',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({code:c})});
  const d=await r.json();
  if(d.ok){location.href=NEXT+'?k='+encodeURIComponent(c);}else{e.textContent=d.message||'口令不正确';}
}
document.getElementById('c').addEventListener('keydown',ev=>{if(ev.key==='Enter')go()});
document.getElementById('c').focus();
</script></body></html>"""

        # 登录成功后回到用户原本想去的页面（例如 /dashboard）。
        # 只允许站内绝对路径，避免被构造成跳去外部站点的开放重定向。
        safe_next = next_path if (next_path.startswith("/") and not next_path.startswith("//")) else "/"
        html = html.replace("async function go(){",
                            "const NEXT=" + json.dumps(safe_next) + ";\nasync function go(){")
        self._send(200, html, "text/html; charset=utf-8")

    def _admin_login_page(self):
        """管理后台的独立登录页。

        和班级登录页分开：口令不同、cookie 不同，
        而且这个页面在网站上没有任何入口，只能手动输 /admin 才会遇到。
        """
        html = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>管理后台</title>
<link rel="icon" href="/favicon.ico" sizes="any">
<style>
 body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
      background:#0a0f16;color:#e8eef5;display:flex;align-items:center;justify-content:center;height:100vh}
 .box{background:#141f2c;padding:34px 30px;border-radius:18px;width:min(92vw,340px);
      box-shadow:0 18px 50px #0008;border:1px solid #22303f}
 .mark{width:38px;height:38px;border-radius:11px;margin-bottom:14px;
       background:url('/favicon-192.png') center/cover;border:1px solid #2c3f52}
 h1{font-size:18px;margin:0 0 6px;letter-spacing:-.02em}
 p{color:#7f93a8;font-size:13px;margin:0 0 20px;line-height:1.6}
 input{width:100%;box-sizing:border-box;padding:12px 14px;border-radius:10px;border:1px solid #2c3f52;
       background:#0c1620;color:#e8eef5;font-size:16px;outline:none}
 input:focus{border-color:#3d9df6}
 button{margin-top:14px;width:100%;padding:12px;border:0;border-radius:10px;background:#3d9df6;
        color:#fff;font-size:16px;font-weight:700;cursor:pointer}
 button:disabled{opacity:.6;cursor:default}
 .err{color:#ff7b72;font-size:13px;margin-top:10px;min-height:18px}
 .hint{color:#4f6274;font-size:11.5px;margin-top:16px;line-height:1.6}
</style></head><body><div class="box">
<div class="mark"></div>
<h1>管理后台</h1><p>这里需要管理口令，和班级口令不一样。</p>
<input id="c" type="password" placeholder="管理口令" autocomplete="off">
<button id="b" onclick="go()">进入</button><div class="err" id="e"></div>
<div class="hint">此页面不在网站任何地方显示入口。</div>
</div><script>
async function go(){
  const c=document.getElementById('c').value.trim(), e=document.getElementById('e'), b=document.getElementById('b');
  e.textContent=''; b.disabled=true; b.textContent='验证中…';
  try{
    const r=await fetch('/api/admin-login',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({code:c})});
    const d=await r.json();
    if(d.ok){location.href='/admin';}else{e.textContent=d.message||'口令不正确';}
  }catch(x){e.textContent='网络错误，请重试';}
  b.disabled=false; b.textContent='进入';
}
document.getElementById('c').addEventListener('keydown',ev=>{if(ev.key==='Enter')go()});
document.getElementById('c').focus();
</script></body></html>"""
        self._send(200, html, "text/html; charset=utf-8")

    def _icon(self, path):
        """网页图标：无需口令，且允许浏览器缓存。

        apple-touch-icon-precomposed 是旧 iOS 的写法，指向同一张图。
        """
        name = "apple-touch-icon.png" if path.startswith("/apple-touch") \
            else path.lstrip("/")
        full = os.path.join(WEB_DIR, name)
        if not os.path.isfile(full):
            # 没有图标就返回一个空 204，别让浏览器拿到登录页 HTML
            return self._send(204, b"", "image/x-icon")

        ctype = mimetypes.guess_type(full)[0] or "image/x-icon"
        if ctype == "image/vnd.microsoft.icon":
            ctype = "image/x-icon"
        try:
            with open(full, "rb") as f:
                data = f.read()
        except OSError:
            return self._send(204, b"", "image/x-icon")

        self._send(200, data, ctype, extra={
            "Cache-Control": "public, max-age=86400",
        }, log=False)

    def _userscript(self):
        """按当前访问地址生成油猴脚本（注入回传地址、口令、轮询间隔）。"""
        if not self._authed():
            return self._send(403, (
                "// 需要访问口令\n"
                "// 请从课表服务的「一键同步」页面获取正确的安装链接：\n"
                "//   <你的地址>/grab?k=你的口令\n"), "text/javascript; charset=utf-8")

        tpl_path = os.path.join(os.path.dirname(WEB_DIR), "web-tools", "kb-sync.user.js")
        try:
            with open(tpl_path, encoding="utf-8") as f:
                tpl = f.read()
        except OSError:
            return self._send(404, "not found", "text/plain")

        host = self.headers.get("Host") or f"127.0.0.1:{self.app.cfg.get('port')}"
        proto = self.headers.get("X-Forwarded-Proto") or (
            "https" if ("trycloudflare" in host or "papercloud" in host) else "http")
        base = f"{proto}://{host}"

        q = self._query()
        code = (q.get("k") or [""])[0] or self.app.cfg.get("access_code") or ""
        upload = base + "/api/import-session"
        if code:
            upload += "?k=" + urllib.parse.quote(code)

        try:
            poll_min = max(2, int(self.app.cfg.get("poll_seconds", 600)) // 60)
        except Exception:
            poll_min = 10

        body = tpl.replace("__UPLOAD__", upload).replace("__POLL_MIN__", str(poll_min))
        self._send(200, body, "text/javascript; charset=utf-8", cors=True)


    # ================================================================
    #                           工具箱
    # ================================================================

    def _tools_upload(self, length):
        """流式接收上传：文件名走 X-File-Name 头（URL 编码），正文是原始字节。

        带 ?code= 表示往已有任务里追加文件（PDF 合并要用）。
        """
        import base64
        if not toolbox.ffmpeg_ready():
            pass  # 图片和文档用不着 ffmpeg，不拦

        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        code = (qs.get("code") or [""])[0].upper()
        raw_name = self.headers.get("X-File-Name") or "file.bin"
        try:
            name = urllib.parse.unquote(raw_name)
        except Exception:
            name = "file.bin"
        name = os.path.basename(name) or "file.bin"

        ip, ck = self._who()
        tmp = None
        try:
            if code:
                dd = toolbox.job_dir(code)
                if not os.path.isdir(dd):
                    return self._json({"ok": False, "message": "提取码不存在"}, 404)
            else:
                dd = None

            # 流式读到临时文件
            os.makedirs(toolbox.BOX_DIR, exist_ok=True)
            tmp = os.path.join(toolbox.BOX_DIR, "_up_%d.tmp" % (time.time_ns() % 10 ** 12))
            got = 0
            with open(tmp, "wb") as f:
                left = length
                while left > 0:
                    chunk = self.rfile.read(min(1 << 20, left))
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    left -= len(chunk)
                    if got > toolbox.MAX_BYTES:
                        f.close()
                        os.remove(tmp)
                        return self._json({"ok": False,
                                           "message": "文件超过 100MB，不给转"}, 413)

            blob = open(tmp, "rb").read()
            os.remove(tmp)
            tmp = None
            if not blob:
                return self._json({"ok": False, "message": "空文件"}, 400)

            if code:
                job = toolbox.add_file(code, name, blob)
                return self._json({"ok": True, "code": code, "name": name,
                                   "size": len(blob),
                                   "kind": toolbox.kind_of(name)})
            code2, job = toolbox.save_upload(name, blob, ip=ip, cookie=ck)
            return self._json({"ok": True, "code": code2, "name": name,
                               "size": len(blob),
                               "kind": toolbox.kind_of(name),
                               "expire": job.get("expire")})
        except ValueError as e:
            return self._json({"ok": False, "message": str(e)}, 400)
        except Exception as e:
            return self._json({"ok": False, "message": "%s: %s" % (type(e).__name__, e)}, 500)
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except Exception:
                    pass

    def _who(self):
        """认人：IP + cookie。3 天内凭这个能找回自己的文件。"""
        ip = getattr(self, "_ip", "") or ""
        ck = ""
        try:
            ck = self._cookies().get(PASS_COOKIE, "") or ""
        except Exception:
            pass
        return ip, ck

    def _tools_convert(self, body):
        """按 op 分派到 toolbox 里的实现。"""
        B = body or {}
        code = str(B.get("code") or "").upper()
        fname = str(B.get("file") or "")
        op = str(B.get("op") or "")
        if not code or not op:
            return self._json({"ok": False, "message": "缺少参数"}, 400)
        job = toolbox.get_job(code)
        if not job:
            return self._json({"ok": False, "message": "提取码不存在或已过期"}, 404)

        dd = toolbox.job_dir(code)
        src = os.path.join(dd, os.path.basename(fname))
        if not os.path.isfile(src):
            return self._json({"ok": False, "message": "文件不在服务器上了"}, 404)

        base = os.path.splitext(os.path.basename(fname))[0]
        outs = []

        def out(nm):
            p = os.path.join(dd, nm)
            # 输出名和源文件撞了（比如 wav 转 wav）-> ffmpeg 拒绝覆盖输入，
            # 加个后缀避开。这种情况本来没意义，但用户点了就该给个结果。
            if os.path.abspath(p) == os.path.abspath(src):
                stem, ext = os.path.splitext(nm)
                p = os.path.join(dd, stem + '_out' + ext)
            return p

        toolbox._slot()
        try:
            ok, info = False, ""
            fmt = str(B.get("fmt") or "").lower()

            if op in ("audio", "extract"):
                ext = fmt or "mp3"
                dst = out("%s.%s" % (base, ext))
                ok, info = toolbox.audio_convert(
                    src, dst, fmt=ext, bitrate=str(B.get("bitrate") or "192k"))
                if ok:
                    outs.append(dst)

            elif op == "video":
                ext = fmt or "mp4"
                dst = out("%s.%s" % (base, ext))
                ok, info = toolbox.video_convert(
                    src, dst, fmt=ext, scale=(B.get("scale") or None),
                    crf=int(B.get("crf") or 23))
                if ok:
                    outs.append(dst)

            elif op == "compress":
                if toolbox.kind_of(fname) == "image":
                    dst = out("%s_small.jpg" % base)
                    ok, info = toolbox.image_convert(
                        src, dst, fmt="jpg", quality=int(B.get("quality") or 75))
                else:
                    dst = out("%s_small.mp4" % base)
                    ok, info = toolbox.video_convert(
                        src, dst, fmt="mp4", crf=int(B.get("crf") or 28))
                if ok:
                    outs.append(dst)

            elif op == "cut":
                ext = os.path.splitext(src)[1].lstrip(".").lower() or "mp4"
                dst = out("%s_cut.%s" % (base, ext))
                ok, info = toolbox.cut(
                    src, dst, start=float(B.get("start") or 0),
                    duration=float(B.get("duration") or 30))
                if ok:
                    outs.append(dst)

            elif op == "volume":
                v = float(B.get("volume") or 1.5)
                if toolbox.kind_of(fname) == "video":
                    dst = out("%s_vol.mp4" % base)
                    ok, info = toolbox.video_convert(src, dst, fmt="mp4", volume=v)
                else:
                    dst = out("%s_vol.mp3" % base)
                    ok, info = toolbox.audio_convert(src, dst, fmt="mp3", volume=v)
                if ok:
                    outs.append(dst)

            elif op == "mute":
                dst = out("%s_mute.mp4" % base)
                ok, info = toolbox.video_convert(src, dst, fmt="mp4", mute=True)
                if ok:
                    outs.append(dst)

            elif op == "frames":
                sub = os.path.join(dd, "%s_frames" % base)
                ok, info = toolbox.extract_frames(
                    src, sub, fps=float(B.get("fps") or 1),
                    max_frames=int(B.get("max_frames") or 20))
                if ok:
                    outs = sorted(os.path.join(sub, x) for x in os.listdir(sub))

            elif op == "image":
                ext = fmt or "jpg"
                dst = out("%s.%s" % (base, ext))
                ok, info = toolbox.image_convert(src, dst, fmt=ext, quality=88)
                if ok:
                    outs.append(dst)

            elif op == "resize":
                ms = str(B.get("max_side") or "").strip()
                ext = os.path.splitext(src)[1].lstrip(".").lower() or "jpg"
                dst = out("%s_%s.%s" % (base, ms or "small", ext))
                ok, info = toolbox.image_convert(src, dst, fmt=ext, max_side=ms or None)
                if ok:
                    outs.append(dst)

            elif op == "watermark":
                ext = os.path.splitext(src)[1].lstrip(".").lower() or "jpg"
                dst = out("%s_wm.%s" % (base, ext))
                ok, info = toolbox.image_convert(
                    src, dst, fmt=ext, watermark=str(B.get("watermark") or "PaperCloud"))
                if ok:
                    outs.append(dst)

            elif op == "topdf":
                dst = out("%s.pdf" % base)
                if toolbox.kind_of(fname) == "image":
                    ok, info = toolbox.images_to_pdf([src], dst)
                else:
                    ok, info = False, "只能把图片转成 PDF"
                if ok:
                    outs.append(dst)

            elif op == "doc2pdf":
                dst = out("%s.pdf" % base)
                ok, info = toolbox.doc_to_pdf(src, dst)
                if ok:
                    outs.append(dst)

            elif op == "pdf2img":
                sub = os.path.join(dd, "%s_img" % base)
                ok, info = toolbox.pdf_to_images(
                    src, sub, dpi=int(B.get("dpi") or 120))
                if ok:
                    outs = sorted(info)

            elif op == "pdfsplit":
                sub = os.path.join(dd, "%s_split" % base)
                ok, info = toolbox.pdf_split(src, sub, each=True)
                if ok:
                    outs = sorted(info)

            elif op in ("merge", "speed", "snapshot", "rot", "gray", "square",
                        "longimg", "pdftext", "pdfenc", "pdfdec"):
                if op == "merge":
                    dst = out("%s_merged.mp3" % base)
                    ok, info = toolbox.audio_merge([src], dst)
                    if ok:
                        outs.append(dst)
                elif op == "speed":
                    sp = float(B.get("speed") or 1.5)
                    is_v = toolbox.kind_of(fname) == "video"
                    dst = out("%s_%.1fx.%s" % (base, sp, "mp4" if is_v else "mp3"))
                    ok, info = toolbox.change_speed(src, dst, sp, video=is_v)
                    if ok:
                        outs.append(dst)
                elif op == "snapshot":
                    dst = out("%s_shot.jpg" % base)
                    ok, info = toolbox.snapshot(src, dst, float(B.get("at") or 1))
                    if ok:
                        outs.append(dst)
                elif op == "rot":
                    ang = int(B.get("angle") or 90)
                    ext = os.path.splitext(src)[1].lstrip(".").lower() or "jpg"
                    dst = out("%s_rot%d.%s" % (base, ang, ext))
                    ok, info = toolbox.image_rot(src, dst, ang, bool(B.get("flip")))
                    if ok:
                        outs.append(dst)
                elif op == "gray":
                    dst = out("%s_gray.png" % base)
                    ok, info = toolbox.image_gray(src, dst)
                    if ok:
                        outs.append(dst)
                elif op == "square":
                    dst = out("%s_square.jpg" % base)
                    ok, info = toolbox.image_square(src, dst, int(B.get("size") or 1080))
                    if ok:
                        outs.append(dst)
                elif op == "longimg":
                    dst = out("%s_long.jpg" % base)
                    ok, info = toolbox.image_long([src], dst, int(B.get("gap") or 0))
                    if ok:
                        outs.append(dst)
                elif op == "pdftext":
                    dst = out("%s.txt" % base)
                    ok, info = toolbox.pdf_text(src, dst)
                    if ok:
                        outs.append(dst)
                elif op == "pdfenc":
                    dst = out("%s_locked.pdf" % base)
                    ok, info = toolbox.pdf_encrypt(src, dst, str(B.get("pwd") or "1234"))
                    if ok:
                        outs.append(dst)
                elif op == "pdfdec":
                    dst = out("%s_unlocked.pdf" % base)
                    ok, info = toolbox.pdf_decrypt(src, dst, str(B.get("pwd") or ""))
                    if ok:
                        outs.append(dst)

            elif op == "unlock":
                blob = open(src, "rb").read()
                try:
                    o2, rext, note = musicunlock.unlock(os.path.basename(src), blob)
                except Exception as exc:
                    o2, rext, note = None, "", "解锁出错：%s: %s" % (type(exc).__name__, exc)
                if o2 is None:
                    ok, info = False, (note or "解锁失败")
                elif not o2:
                    # 解出来是空的 —— 说明文件结构能认，但音频段没解出东西
                    ok, info = False, ("解出来的音频是空的（原文件 %d 字节，%s）。" % (len(blob), note or "") +
                                       "可能这个文件本身就是坏的，或者上传时被截断了")
                elif len(o2) < 512:
                    ok, info = False, ("解出来只有 %d 字节（%s），不像正常音频" % (len(o2), note or ""))
                else:
                    dst = out("%s.%s" % (base, rext))
                    with open(dst, "wb") as f:
                        f.write(o2)
                    ok, info = True, note
                    outs.append(dst)

            elif op == "pdfmerge":
                second = os.path.join(dd, os.path.basename(str(B.get("file2") or "")))
                if not os.path.isfile(second):
                    ok, info = False, "第二个 PDF 不在"
                else:
                    dst = out("%s_merged.pdf" % base)
                    ok, info = toolbox.pdf_merge([src, second], dst)
                    if ok:
                        outs.append(dst)
            else:
                ok, info = False, "不认识的操作：%s" % op

            if not ok:
                return self._json({"ok": False, "message": str(info)[:400]}, 400)

            listing = []
            for p in outs:
                if os.path.isfile(p):
                    listing.append({"name": os.path.basename(p),
                                    "size": os.path.getsize(p)})
            if not listing:
                return self._json({"ok": False, "message": "转换没产出文件"}, 400)

            # 记一笔，方便「我的文件」里看到
            try:
                d = toolbox._load()
                if code in d:
                    d[code].setdefault("ops", []).append(
                        {"op": op, "at": time.time(), "out": [x["name"] for x in listing]})
                    toolbox._save(d)
            except Exception:
                pass

            return self._json({"ok": True, "outputs": listing})
        finally:
            toolbox._release()


    # ---------------- 天气（高德） ----------------
    _WEATHER_CACHE = {"t": 0.0, "d": None}
    AMAP_KEY = "29087fb658eb37a12b8866fff871763b"
    AMAP_ADCODE = "520403"          # 贵州省安顺市平坝区

    def _weather_data(self):
        """取天气数据（10 分钟缓存）。返回 (ok, data 或 错误信息)。"""
        now = time.time()
        c = Handler._WEATHER_CACHE
        if c["d"] is not None and now - c["t"] < 600:
            return True, c["d"]

        import urllib.request as _u
        import urllib.parse as _p

        def _call(ext):
            qs = _p.urlencode({
                "city": Handler.AMAP_ADCODE,
                "key": Handler.AMAP_KEY,
                "extensions": ext,
                "output": "JSON",
            })
            url = "https://restapi.amap.com/v3/weather/weatherInfo?" + qs
            req = _u.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with _u.urlopen(req, timeout=12) as r:
                return json.loads(r.read().decode("utf-8"))

        try:
            raw = _call("all")
            raw_live = _call("base")
        except Exception as e:
            return False, "取天气失败：%s" % e

        if str(raw.get("status")) != "1":
            return False, "高德返回：%s" % (raw.get("info") or "未知")

        live = (raw_live.get("lives") or raw.get("lives") or [{}])[0]
        casts = []
        for f in (raw.get("forecasts") or [])[:1]:
            for x in (f.get("casts") or [])[:5]:
                casts.append({
                    "date": x.get("date"),
                    "day": x.get("dayweather"),
                    "night": x.get("nightweather"),
                    "high": x.get("daytemp"),
                    "low": x.get("nighttemp"),
                    "daywind": x.get("daywind"),
                    "daypower": x.get("daypower"),
                })
        data = {
            "city": live.get("city") or "平坝区",
            "weather": live.get("weather") or "",
            "temp": live.get("temperature") or "",
            "humidity": live.get("humidity") or "",
            "winddir": live.get("winddirection") or "",
            "windpower": live.get("windpower") or "",
            "reporttime": live.get("reporttime") or "",
            "casts": casts,
        }
        c["t"], c["d"] = now, data
        return True, data

    def _weather(self):
        """对外接口：/api/weather"""
        hit = (Handler._WEATHER_CACHE["d"] is not None
               and time.time() - Handler._WEATHER_CACHE["t"] < 600)
        ok, d = self._weather_data()
        if not ok:
            return self._json({"ok": False, "message": d}, 502)
        return self._json({"ok": True, "data": d, "cached": hit})

    # ------------------------------ 温馨提醒 ------------------------------
    _QQ_TIPS = {
        "rain": [
            "出门记得带伞，路上别跑太快",
            "雨天地滑，进楼前抖抖伞再走",
            "书包里备个塑料袋，湿伞别弄湿课本",
            "雨天路堵，今天可以早五分钟出门",
            "鞋湿了记得换一双，别穿一上午",
            "雨天司机视线差，过马路多看一眼",
            "伞别落在教室，走的时候看一眼桌肚",
        ],
        "cold": [
            "今天偏冷，出门加件外套",
            "早晚温差大，围巾手套可以备上",
            "手凉就揣兜里，别硬扛",
            "先喝口热的再出门，胃里暖和",
            "教室不一定开暖气，多穿一件不亏",
            "风大的话把领口拉紧一点",
        ],
        "hot": [
            "今天热，记得带水杯",
            "太阳晒，路上尽量走阴凉那侧",
            "别一次灌太多冰水，容易闹肚子",
            "备张纸巾，进教室擦擦汗",
            "防晒涂一点，别晒脱皮",
            "中午别在太阳底下站着聊天",
        ],
        "humid": [
            "湿度大，衣服不容易干，别穿潮的",
            "闷热天气多喝水，别硬扛",
            "教室容易返潮，课本别放地上",
            "头发湿着吹风容易头疼，擦干再出门",
        ],
        "fog": [
            "外面起雾了，路上注意能见度，骑车慢一点",
            "雾天看不远，过路口多看一眼",
            "雾里空气不太好，口罩可以戴一下",
            "雾天别骑太快，留够刹车距离",
            "能见度低，出门早几分钟不慌",
        ],
        "snow": [
            "下雪了，走路踩实一点别打滑",
            "手冷戴手套，别碰铁栏杆",
            "雪天路滑，提前出门慢慢走",
        ],
        "normal": [
            "新的一天，加油",
            "出门前检查一下校园卡带没带",
            "早饭别省，上午四节课很耗神",
            "上课前把手机调成静音",
            "今天也要好好吃饭",
            "路上慢一点，安全第一",
            "保持好心情，今天会很顺",
            "课间起来走两步，别一直坐着",
            "晚上早点睡，别熬夜刷手机",
            "记得给家里回个消息",
        ],
    }
    _QQ_TIP_LAST = {}

    def _qq_tip(self, data=None):
        """按天气挑一句温馨提醒，尽量不跟上次重复。"""
        import random
        cat = "normal"
        try:
            if isinstance(data, dict):
                w = str(data.get("weather") or "")
                t = 0
                try:
                    t = int(float(data.get("temp") or 0))
                except Exception:
                    t = 0
                h = 0
                try:
                    h = int(float(data.get("humidity") or 0))
                except Exception:
                    h = 0
                if "雪" in w:
                    cat = "snow"
                elif "雨" in w or "雷" in w:
                    cat = "rain"
                elif "雾" in w or "霾" in w or "沙" in w or "尘" in w:
                    cat = "fog"
                elif t <= 10:
                    cat = "cold"
                elif t >= 30:
                    cat = "hot"
                elif h >= 85 and t >= 20:
                    cat = "humid"
        except Exception:
            cat = "normal"

        pool = list(self._QQ_TIPS.get(cat) or self._QQ_TIPS["normal"])
        last = self._QQ_TIP_LAST.get(cat)
        if len(pool) > 1 and last in pool:
            try:
                pool.remove(last)
            except Exception:
                pass
        pick = random.choice(pool)
        self._QQ_TIP_LAST[cat] = pick
        return pick

    def _qq_weather_line(self):
        """一行天气摘要，取不到就返回空串。"""
        try:
            ok, d = self._weather_data()
            if not ok or not isinstance(d, dict):
                return ""
            parts = [d.get("weather") or "", (d.get("temp") or "") + "℃"]
            line = "今日天气  " + " ".join([p for p in parts if p.strip()])
            casts = d.get("casts") or []
            if casts:
                c0 = casts[0]
                lo, hi = c0.get("low"), c0.get("high")
                if lo and hi:
                    line += "（%s~%s℃）" % (lo, hi)
            if d.get("humidity"):
                line += " · 湿度 %s%%" % d["humidity"]
            if d.get("winddir"):
                line += " · %s%s级" % (d["winddir"], d.get("windpower") or "")
            return line
        except Exception:
            return ""


    def _qq_secrets_path(self):
        return os.path.join(DATA_DIR, "..", "config", "secrets.json")

    def _qq_read_secrets(self):
        p = self._qq_secrets_path()
        try:
            with open(p, encoding="utf-8-sig") as f:
                return json.load(f), p
        except Exception:
            return {}, p

    def _qq_write_secrets(self, d, p):
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)

    @staticmethod
    def _mask(v):
        s = str(v or "")
        if not s:
            return ""
        if len(s) <= 6:
            return "••••"
        return s[:3] + "••••" + s[-3:]

    def _qq_proc_name(self, cfg):
        """要杀的进程名。优先配置，否则从启动路径推断。"""
        name = str(cfg.get("qq_napcat_proc") or "").strip()
        if name:
            return name
        path = str(cfg.get("qq_napcat_path") or "").strip()
        if not path:
            return ""
        base = os.path.basename(path)
        # .bat 只是壳，真正的进程通常是 NapCatWinBootMain.exe
        if base.lower().endswith((".bat", ".cmd")):
            return "NapCatWinBootMain.exe"
        return base

    def _qq_proc_running(self, name):
        if not name:
            return False
        try:
            out = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq " + name, "/NH"],
                capture_output=True, text=True, timeout=6,
                encoding="mbcs", errors="replace").stdout or ""
            return name.lower() in out.lower()
        except Exception:
            return False

    def _api_admin_qq_status(self):
        cfg = qq.cfg_of(getattr(self.app, "cfg", {}) or {})
        online, who = (False, "")
        if qq.enabled(cfg):
            try:
                online, who = qq.ping(cfg)
            except Exception:
                online, who = False, ""
        proc = self._qq_proc_name(cfg)
        groups = sorted(qq.allow_groups(cfg))
        return self._json({
            "ok": True,
            "enabled": qq.enabled(cfg),
            "api": qq.base_url(cfg),
            "groups": groups,
            "online": bool(online),
            "account": who if isinstance(who, str) else str(who)[:80],
            "webhook_key_set": bool(cfg.get("qq_webhook_key")),
            "webhook_key_masked": self._mask(cfg.get("qq_webhook_key")),
            "token_masked": self._mask(cfg.get("qq_token")),
            "napcat_path": str(cfg.get("qq_napcat_path") or ""),
            "napcat_proc": str(cfg.get("qq_napcat_proc") or ""),
            "process": proc or "",
            "process_running": self._qq_proc_running(proc),
            "push_time": str(cfg.get("qq_push_time") or "21:00"),
            "push_skip_weekdays": [4, 5],      # 周五、周六晚不推
        })

    def _api_admin_qq_save(self, body):
        B = body or {}
        d, p = self._qq_read_secrets()
        if not d:
            return self._json({"ok": False, "message": "读不到 config/secrets.json"}, 500)

        def put(key, val):
            d[key] = val

        if "enabled" in B:
            put("qq_enabled", bool(B.get("enabled")))
        if "api" in B:
            put("qq_api", str(B.get("api") or "").strip() or "http://127.0.0.1:3000")
        if "group" in B:
            g = str(B.get("group") or "").strip()
            try:
                put("qq_group", int(g) if g else 0)
            except Exception:
                return self._json({"ok": False, "message": "群号必须是数字"}, 400)
        if "webhook_key" in B:
            put("qq_webhook_key", str(B.get("webhook_key") or "").strip())
        if "napcat_path" in B:
            put("qq_napcat_path", str(B.get("napcat_path") or "").strip())
        if "napcat_proc" in B:
            put("qq_napcat_proc", str(B.get("napcat_proc") or "").strip())
        if "push_time" in B:
            pt = str(B.get("push_time") or "").strip() or "21:00"
            put("qq_push_time", pt)
        # token 传上来的不是掩码才覆盖
        tok = B.get("token")
        if isinstance(tok, str) and tok.strip() and "••" not in tok:
            put("qq_token", tok.strip())

        try:
            self._qq_write_secrets(d, p)
        except Exception as e:
            return self._json({"ok": False, "message": "写入失败：%s" % e}, 500)

        # 让内存里的 cfg 也跟上，不用重启
        try:
            getattr(self.app, "cfg", {})["qq_enabled"] = d.get("qq_enabled")
            getattr(self.app, "cfg", {})["qq_api"] = d.get("qq_api")
            getattr(self.app, "cfg", {})["qq_group"] = d.get("qq_group")
            getattr(self.app, "cfg", {})["qq_token"] = d.get("qq_token")
            getattr(self.app, "cfg", {})["qq_webhook_key"] = d.get("qq_webhook_key")
            getattr(self.app, "cfg", {})["qq_napcat_path"] = d.get("qq_napcat_path")
            getattr(self.app, "cfg", {})["qq_napcat_proc"] = d.get("qq_napcat_proc")
            getattr(self.app, "cfg", {})["qq_push_time"] = d.get("qq_push_time")
        except Exception:
            pass

        return self._json({"ok": True, "message": "已保存"})

    def _api_admin_qq_start(self, body):
        cfg = qq.cfg_of(getattr(self.app, "cfg", {}) or {})
        path = str(cfg.get("qq_napcat_path") or "").strip()
        if not path:
            return self._json({"ok": False,
                               "message": "还没配置 NapCat 启动路径"}, 400)
        if not os.path.isfile(path):
            return self._json({"ok": False,
                               "message": "路径不存在：%s" % path}, 400)
        proc = self._qq_proc_name(cfg)
        if proc and self._qq_proc_running(proc):
            return self._json({"ok": True, "message": "已经在运行了"})
        try:
            cwd = os.path.dirname(path) or None
            if path.lower().endswith((".bat", ".cmd")):
                cmd = ["cmd", "/c", path]
            elif path.lower().endswith(".exe"):
                cmd = [path]
            else:
                cmd = ["cmd", "/c", "start", "", path]
            flags = 0
            if os.name == "nt":
                flags = 0x00000008 | 0x00000200      # DETACHED_PROCESS | NEW_PROCESS_GROUP
            subprocess.Popen(cmd, cwd=cwd, creationflags=flags,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             stdin=subprocess.DEVNULL)
            return self._json({"ok": True, "message": "已发出启动命令，等它自己连上"})
        except Exception as e:
            return self._json({"ok": False, "message": "启动失败：%s" % e}, 500)

    def _api_admin_qq_stop(self, body):
        cfg = qq.cfg_of(getattr(self.app, "cfg", {}) or {})
        proc = self._qq_proc_name(cfg)
        if not proc:
            return self._json({"ok": False, "message": "不知道要停哪个进程（配置进程名）"}, 400)
        if not self._qq_proc_running(proc):
            return self._json({"ok": True, "message": "本来就没在运行"})
        try:
            subprocess.run(["taskkill", "/F", "/IM", proc, "/T"],
                           capture_output=True, timeout=10)
            ok = not self._qq_proc_running(proc)
            return self._json({"ok": ok,
                               "message": "已停止" if ok else "停止失败，可能还在退出中"})
        except Exception as e:
            return self._json({"ok": False, "message": "停止失败：%s" % e}, 500)

    def _api_admin_qq_simulate(self, body):
        """模拟「群里收到一条消息」，用来验证收消息之后的链路。"""
        cfg = self._qq_cfg()
        groups = sorted(qq.allow_groups(cfg))
        if not groups:
            return self._json({"ok": False, "message": "还没配置群号"}, 400)
        text = str((body or {}).get("text") or "课表")
        ev = {
            "post_type": "message",
            "message_type": "group",
            "group_id": groups[0],
            "user_id": 0,
            "raw_message": text,
            "sender": {"nickname": "模拟", "role": "admin"},
        }
        self._qq_log("【模拟】本地注入一条消息：%r" % text)
        return self._qq_webhook(ev)

    def _api_admin_qq_test(self, body):
        cfg = qq.cfg_of(getattr(self.app, "cfg", {}) or {})
        if not qq.enabled(cfg):
            return self._json({"ok": False, "message": "QQ 功能未启用"}, 400)
        if not qq.allow_groups(cfg):
            return self._json({"ok": False, "message": "还没配置群号"}, 400)
        ok, info = qq.send_group(cfg, "【PaperCloud】测试消息，收到说明 QQ 群接入正常。")
        if ok:
            return self._json({"ok": True, "message": "已发送"})
        return self._json({"ok": False, "message": "发送失败：%s" % (info,)}, 502)

    # ================================ 账号系统 ================================
    def _sess_user(self):
        """从 cookie 里取出登录用户（没有就返回 None）。"""
        if getattr(self, "_sess_cache", "unset") != "unset":
            return self._sess_cache
        self._sess_cache = None
        if auth is None:
            return None
        try:
            tok = self._cookies().get(SESS_COOKIE, "")
            if tok:
                tok = urllib.parse.unquote(tok)
            uid = auth.read_session(tok) if tok else None
            if uid:
                d = auth.load()
                u = auth.find_user(d, uid=uid)
                if u and u.get("emailVerified"):
                    self._sess_cache = u
        except Exception:
            pass
        return self._sess_cache

    def _sess_cookie(self, uid):
        tok = auth.make_session(uid)
        sec = ""
        try:
            if self.headers.get("X-Forwarded-Proto") == "https":
                sec = "; Secure"
        except Exception:
            pass
        return {
            "Set-Cookie": "%s=%s; Path=/; Max-Age=%d; SameSite=Lax%s" % (
                SESS_COOKIE, urllib.parse.quote(tok), auth.SESS_DAYS * 86400, sec),
        }

    def _auth_next(self):
        q = self._query()
        nxt = (q.get("next") or [""])[0]
        if not nxt or not nxt.startswith("/") or nxt.startswith("//"):
            nxt = "/?k=" + str(self.app.cfg.get("access_code") or "")
        return nxt

    def _auth_guard(self):
        """账号模块没装好时给个明确提示，而不是 500。"""
        if auth is None:
            self._json({"ok": False, "message": "账号系统未安装（缺 app/auth.py）"}, 503)
            return False
        return True

    def _api_auth_register(self, body):
        if auth is None:
            return self._json({"ok": False, "message": "账号系统未安装（缺 app/auth.py）"}, 503)
        no = auth.norm_no(body.get("no"))
        name = str(body.get("name") or "").strip()
        email = auth.norm_email(body.get("email"))
        if not no or not name:
            return self._json({"ok": False, "message": "学号和姓名都要填"}, 400)
        if not auth.valid_email(email):
            return self._json({"ok": False, "message": "邮箱格式不对"}, 400)

        std = None
        try:
            from . import classmgmt
            cs = classmgmt.ClassStore()
            for x in (cs.students() or []):
                if auth.norm_no(x.get("no")) == no:
                    std = x
                    break
        except Exception as e:
            return self._json({"ok": False, "message": "读取名单失败：%s" % e}, 500)

        if std is None:
            return self._json({"ok": False, "message": "学号不在班级名单里"}, 400)
        if str(std.get("name") or "").strip() != name:
            return self._json({"ok": False, "message": "姓名和学号对不上"}, 400)

        d = auth.load()

        ex = auth.find_user(d, email=email)
        if ex and auth.norm_no(ex.get("no")) != no:
            return self._json({"ok": False, "message": "这个邮箱已经注册过了"}, 400)

        for u in d["users"]:
            if auth.norm_no(u.get("no")) == no:
                return self._json({"ok": False, "message": "这个学号已经注册过了，请直接登录"}, 400)

        code = auth.new_code()
        auth.put_code(d, email, code)

        title = str(std.get("title") or "").strip()
        role = "committe" if title else "student"

        subject = "PaperCloud 注册验证码"
        mail_body = (
            "你好，%s！\n\n"
            "你正在注册 PaperCloud 班务系统账号。\n\n"
            "验证码：%s\n"
            "10 分钟内有效，请勿转发给他人。\n\n"
            "如果这不是你本人操作，忽略这封邮件即可。\n\n"
            "-- PaperCloud"
        ) % (name, code)

        mailed = auth.send_mail(email, subject, mail_body)
        if not mailed:
            auth.queue_mail(d, email, subject, mail_body)

        d["users"].append({
            "id": "u" + no,
            "no": no,
            "name": name,
            "email": email,
            "role": role,
            "title": title,
            "emailVerified": False,
            "pass": "",
            "created": int(time.time()),
            "lastLogin": 0,
        })
        auth.save(d)

        msg = "验证码已发送" if mailed else "验证码已生成（邮件未配置，请向管理员索取）"
        out = {"ok": True, "message": msg, "mailed": bool(mailed)}
        if not mailed:
            q = self._query()
            kk = (q.get("k") or [""])[0]
            want = (self._admin_password() or "").strip()
            if self._admin_authed() or self._is_local() or (want and kk == want):
                out["code"] = code
        return self._json(out)

    def _api_auth_verify(self, body):
        if auth is None:
            return self._json({"ok": False, "message": "账号系统未安装（缺 app/auth.py）"}, 503)
        email = auth.norm_email(body.get("email"))
        code = str(body.get("code") or "").strip()
        pw = str(body.get("password") or "")
        if len(pw) < 6:
            return self._json({"ok": False, "message": "密码至少 6 位"}, 400)

        d = auth.load()
        ok, why = auth.check_code(d, email, code)
        if not ok:
            auth.save(d)
            return self._json({"ok": False, "message": why}, 400)

        rec = None
        for u in d["users"]:
            if auth.norm_email(u.get("email")) == email and not u.get("emailVerified"):
                rec = u
                break
        if rec is None:
            return self._json({"ok": False, "message": "没有待验证的账号，请重新注册"}, 400)

        rec["pass"] = auth.hash_pass(pw)
        rec["emailVerified"] = True
        rec["lastLogin"] = int(time.time())
        auth.save(d)

        return self._send(200, json.dumps({
            "ok": True, "message": "注册成功", "next": self._auth_next(),
            "user": auth.public_user(rec),
        }, ensure_ascii=False), extra=self._sess_cookie(rec["id"]))

    def _api_auth_login(self, body):
        if auth is None:
            return self._json({"ok": False, "message": "账号系统未安装（缺 app/auth.py）"}, 503)
        email = auth.norm_email(body.get("email"))
        pw = str(body.get("password") or "")
        if not email or not pw:
            return self._json({"ok": False, "message": "邮箱和密码都要填"}, 400)

        d = auth.load()
        u = auth.find_user(d, email=email)
        if not u:
            return self._json({"ok": False, "message": "这个邮箱没注册过"}, 401)
        if not u.get("emailVerified"):
            return self._json({"ok": False, "message": "账号还没完成验证"}, 401)
        if not auth.check_pass(pw, u.get("pass")):
            return self._json({"ok": False, "message": "密码不对"}, 401)

        u["lastLogin"] = int(time.time())
        auth.save(d)

        return self._send(200, json.dumps({
            "ok": True, "message": "登录成功", "next": self._auth_next(),
            "user": auth.public_user(u),
        }, ensure_ascii=False), extra=self._sess_cookie(u["id"]))

    def _api_auth_logout(self):
        return self._send(200, json.dumps({"ok": True}, ensure_ascii=False), extra={
            "Set-Cookie": "%s=; Path=/; Max-Age=0" % SESS_COOKIE,
        })

    def _api_auth_me(self):
        u = self._sess_user()
        return self._json({"ok": True, "user": auth.public_user(u), "login": bool(u)})

    def _api_auth_outbox(self):
        d = auth.load()
        return self._json({"ok": True, "outbox": d.get("outbox") or [],
                           "smtp": auth.smtp_ready()})

    def _qq_cfg(self):
        try:
            return qq.cfg_of(getattr(self.app, "cfg", {}) or {})
        except Exception:
            return {}

    def _qq_allowed(self, gid):
        cfg = self._qq_cfg()
        if not qq.enabled(cfg):
            return False
        ok = qq.allow_groups(cfg)
        if not ok:
            return False
        try:
            return int(gid) in ok
        except Exception:
            return False

    # ------------------------------ QQ 排版 ------------------------------
    QQ_BAR = "━━━━━━━━━━━━━━━━━━"
    _QQ_SITE = "更多信息请访问：https://your-domain.example/?k=YOUR_ACCESS_CODE"

    @staticmethod
    def _qq_w(txt):
        """按终端显示宽度算（中文和 emoji 算 2 格）。"""
        import unicodedata as _u
        w = 0
        for ch in str(txt or ""):
            w += 2 if _u.east_asian_width(ch) in ("W", "F") else 1
        return w

    def _qq_card(self, title, extra="", inner=17):
        """标题用【 】括起来，正文不框。"""
        out = ["\u3010 " + str(title) + " \u3011"]
        if extra:
            out.append(str(extra))
        return out

    def _qq_foot(self, tail="PaperCloud · Q群机器人"):
        """统一页脚：署名 → 分隔线 → 帮助提示 → 站点链接"""
        return ["", str(tail), self.QQ_BAR,
                "发送帮助来获取指令列表", self._QQ_SITE]


    def _qq_week_text(self):
        """本周课表（卡片式）。"""
        st = self.app.store.get()
        sched = st.get("schedule", {})
        try:
            import copy as _copy
            sched = _copy.deepcopy(sched)
            overrides.apply(sched, getattr(self.app, "term_start", None))
        except Exception:
            pass
        week, _ts = self.app.current_week(sched.get("maxWeek", 20) or 20)

        days = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        by = {}
        for c in (sched.get("courses") or []):
            if week not in (c.get("weeks") or []):
                continue
            wd = int(c.get("weekday") or 0)
            if 1 <= wd <= 7:
                by.setdefault(wd, []).append(c)

        L = self._qq_card("本周课表", "第 %d 周" % week)
        if not by:
            L.append("")
            L.append("  这周没有课，好好休息")
        else:
            for wd in range(1, 8):
                lst = by.get(wd)
                if not lst:
                    continue
                L.append("")
                L.append("▍" + days[wd - 1])
                lst.sort(key=lambda x: int(x.get("startSection") or 0))
                for c in lst:
                    s0 = int(c.get("startSection") or 0)
                    e0 = int(c.get("endSection") or 0)
                    room = c.get("room") or ""
                    line = "   %02d-%02d  %s" % (s0, e0, c.get("name") or "")
                    if room:
                        line += "  ·  " + room
                    L.append(line)
        L.extend(self._qq_foot("PaperCloud · Q群机器人"))
        return "\n".join(L)


    def _qq_duty_text(self, offset=0, group_id=None):
        """值日：第几组 + @ 组员 + 打扫内容。返回消息段数组。"""
        import datetime as _dt
        try:
            from . import classmgmt
            cs = classmgmt.ClassStore()
            duty = cs.duty()
            students = {s.get("id"): s for s in (cs.students() or [])}
        except Exception:
            return "值日表还没配好", None

        day = _dt.date.today() + _dt.timedelta(days=offset)
        when = "今天" if offset == 0 else ("明天" if offset == 1 else
                                          ("后天" if offset == 2 else "那天"))
        head = "%s %s" % (when, day.strftime("%m月%d日"))

        if day.weekday() == 5:
            return [{"type": "text", "data": {"text": "\n".join(
                self._qq_card("%s值日" % when, day.strftime("%m月%d日") + " 周六")
                + ["", "  %s休息，不用打扫" % when, ""]
                + self._qq_foot("PaperCloud · Q群机器人"))}}], None

        sched = duty.get("schedule") or {}
        gid = sched.get(day.isoformat())
        if not gid:
            return [{"type": "text", "data": {"text": "\n".join(
                self._qq_card("%s值日" % when, day.strftime("%m月%d日"))
                + ["", "  这天没有排值日", ""]
                + self._qq_foot("PaperCloud · Q群机器人"))}}], None

        groups = {g.get("id"): g for g in (duty.get("groups") or [])}
        g = groups.get(gid) or {}
        gname = g.get("name") or gid

        ids = []
        if g.get("leader"):
            ids.append(g["leader"])
        for k2 in ("male", "female", "members"):
            for x in (g.get(k2) or []):
                if x not in ids:
                    ids.append(x)

        people = []
        for sid in ids:
            st = students.get(sid) or {}
            people.append({
                "name": st.get("name") or "",
                "phone": st.get("phone") or "",
                "title": st.get("title") or "",
                "no": st.get("no") or "",
                "leader": sid == g.get("leader"),
            })

        qqs, missing = [], []
        try:
            cfg = self._qq_cfg()
            gnum = group_id or cfg.get("qq_group")
            okm, members = qq.get_group_members(cfg, gnum)
            if okm and members:
                qqs, missing = qq.match_members(members, people)
            else:
                missing = [p["name"] for p in people if p["name"]]
        except Exception:
            missing = [p["name"] for p in people if p["name"]]

        leader = next((p for p in people if p["leader"]), None)

        seg = []
        def add_text(t):
            if seg and seg[-1]["type"] == "text":
                seg[-1]["data"]["text"] += t
            else:
                seg.append({"type": "text", "data": {"text": t}})

        L = self._qq_card("%s值日" % when, day.strftime("%m月%d日") + " · 第 %d 周" %
                          self.app.current_week(20)[0])
        L.append("")
        L.append("  今天是  " + gname)
        if leader and leader["name"]:
            L.append("  组  长  " + leader["name"])
        if g.get("task"):
            L.append("")
            L.append("  任务  " + str(g.get("task")))
        add_text("\n".join(L))

        if qqs:
            add_text("\n\n今天打扫：\n")
            for it in qqs:
                uid = it.get("qq") if isinstance(it, dict) else it
                seg.append({"type": "at", "data": {"qq": uid}})
                add_text("\n")
        elif people:
            parts = [p.get("name") or "" for p in people]
            add_text("\n\n成员：" + "、".join([x for x in parts if x]))
        # 群里找不到的人，直接用文字 @ 名字（真 @ 发不出去）
        if missing:
            if not qqs:
                add_text("\n\n今天打扫：\n")
            for nm in missing:
                if nm:
                    add_text("@%s\n" % nm)

        add_text("\n\nPaperCloud · Q群机器人\n" + self.QQ_BAR +
                 "\n发送帮助来获取指令列表\n" + self._QQ_SITE)
        return seg, None


    def _qq_help(self):
        L = self._qq_card("可用命令", "在群里直接发下面的字就行")
        L.append("")
        L.append("  课表 ······ 今天的课")
        L.append("  明天 ······ 明天的课")
        L.append("  后天 ······ 后天的课")
        L.append("  本周 ······ 整周课表")
        L.append("  值日 ······ 今天哪一组值日，@ 组员")
        L.append("  状态 ······ 系统运行状态")
        L.append("  管理 ······ 管理菜单（仅群主、管理员）")
        L.append("  帮助 ······ 看这个")
        L.extend(self._qq_foot("PaperCloud · Q群机器人"))
        return "\n".join(L)

    def _qq_first_class(self):
        """今天第一节的课（没有就返回 None）。"""
        import datetime as _dt
        st = self.app.store.get()
        sched = st.get("schedule", {})
        try:
            import copy as _copy
            sched = _copy.deepcopy(sched)
            overrides.apply(sched, getattr(self.app, "term_start", None))
        except Exception:
            pass
        week, _ts = self.app.current_week(sched.get("maxWeek", 20) or 20)
        wd = _dt.date.today().isoweekday()
        lst = []
        for c in (sched.get("courses") or []):
            try:
                if int(c.get("weekday") or 0) != wd:
                    continue
            except Exception:
                continue
            if week not in (c.get("weeks") or []):
                continue
            lst.append(c)
        if not lst:
            return None
        lst.sort(key=lambda x: int(x.get("startSection") or 0))
        return lst[0]

    def _qq_first_time(self, sec_no):
        """第几节的开始时间。配置里没有就用课表模块的默认作息。"""
        try:
            times = self.app.cfg.get("section_times") or []
            if not times:
                from . import timetable as _tt
                times = _tt._sections(None)
            row = times[int(sec_no) - 1]
            return str(row[0])
        except Exception:
            return ""

    def _qq_morning_seg(self, gid):
        """早课提醒卡片。返回消息段数组；今天没课返回 None。"""
        import datetime as _dt
        c = self._qq_first_class()
        if not c:
            return None

        day = _dt.date.today()
        names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        s0 = int(c.get("startSection") or 1)
        e0 = int(c.get("endSection") or s0)
        t0 = self._qq_first_time(s0)
        t1 = self._qq_first_time(e0 + 1) if False else ""

        L = ["【 早课提醒 】",
             "%s %s" % (day.strftime("%m月%d日"), names[day.isoweekday() - 1]),
             ""]
        head = "%02d-%02d 节" % (s0, e0)
        if t0:
            head += "  " + t0
        L.append("  " + head)
        L.append("  " + str(c.get("name") or ""))
        sub = []
        if c.get("room"):
            sub.append(str(c["room"]))
        if c.get("teacher"):
            sub.append(str(c["teacher"]))
        if sub:
            L.append("  " + " · ".join(sub))

        # 不在 201C-206、也不是体育课 → 提醒带书
        _room = "".join(ch for ch in str(c.get("room") or "") if ch.isalnum()).upper()
        _name = str(c.get("name") or "")
        _is_pe = ("体育" in _name)
        _in_201 = ("201C206" in _room) or _room.endswith("201C")
        if not _is_pe and not _in_201:
            L.append("")
            L.append("记得带书！！！")

        seg = [{"type": "text", "data": {"text": "\n".join(L) + "\n\n"}}]
        seg.append({"type": "at", "data": {"qq": "all"}})

        # 换行附上今日天气 + 一句温馨提醒（取不到天气就跳过）
        try:
            okw, wd = self._weather_data()
            wd = wd if (okw and isinstance(wd, dict)) else {}
        except Exception:
            wd = {}
        w = self._qq_weather_line()
        if w:
            seg.append({"type": "text", "data": {"text": "\n\n" + w}})
        try:
            tip = self._qq_tip(wd)
        except Exception:
            tip = ""
        if tip:
            seg.append({"type": "text", "data": {"text": "\n" + tip}})

        # 分隔线 + 帮助提示放最下面
        seg.append({"type": "text", "data": {"text":
            "\n\nPaperCloud · Q群机器人\n" + self.QQ_BAR +
            "\n发送帮助来获取指令列表\n" + self._QQ_SITE}})
        return seg

    def _qq_do_checkin(self):
        """签到提醒：@全体成员，一句话，不寒暄。"""
        cfg = self._qq_cfg()
        if not qq.enabled(cfg):
            return False, "QQ 功能未启用"
        groups = sorted(qq.allow_groups(cfg))
        if not groups:
            return False, "还没配置群号"
        gid = groups[0]

        import datetime as _dt
        day = _dt.date.today()
        names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

        L = ["【 签到提醒 】",
             "%s %s" % (day.strftime("%m月%d日"), names[day.isoweekday() - 1]),
             ""]

        seg = [{"type": "text", "data": {"text": "\n".join(L) + "\n"}}]
        seg.append({"type": "at", "data": {"qq": "all"}})
        seg.append({"type": "text", "data": {"text":
            "\n\nWeLink 签到\n\nPaperCloud · Q群机器人\n" +
            self.QQ_BAR + "\n发送帮助来获取指令列表\n" + self._QQ_SITE}})

        ok, info = qq.send_group_segments(cfg, seg, gid)
        self._qq_log("签到提醒 -> %s %s" % ("成功" if ok else "失败",
                                           "" if ok else str(info)[:150]))
        return (True, "已推送") if ok else (False, "推送失败：%s" % (info,))

    def _qq_checkin_route(self):
        cfg = self._qq_cfg()
        q = self._query()
        want = str(cfg.get("qq_webhook_key") or "")
        key = (q.get("key") or [""])[0]
        if want and key != want and not self._is_local():
            return self._json({"ok": False, "message": "key 不对"}, 403)
        ok, msg = self._qq_do_checkin()
        return self._json({"ok": ok, "message": msg})

    def _qq_do_morning(self):
        cfg = self._qq_cfg()
        if not qq.enabled(cfg):
            return False, "QQ 功能未启用"
        groups = sorted(qq.allow_groups(cfg))
        if not groups:
            return False, "还没配置群号"
        gid = groups[0]
        seg = self._qq_morning_seg(gid)
        if not seg:
            self._qq_log("早课提醒：今天没课，跳过")
            return False, "今天没课，不推送"
        ok, info = qq.send_group_segments(cfg, seg, gid)
        self._qq_log("早课提醒 -> %s %s" % ("成功" if ok else "失败",
                                           "" if ok else str(info)[:150]))
        return (True, "已推送") if ok else (False, "推送失败：%s" % (info,))

    def _qq_morning_route(self):
        cfg = self._qq_cfg()
        q = self._query()
        want = str(cfg.get("qq_webhook_key") or "")
        key = (q.get("key") or [""])[0]
        if want and key != want and not self._is_local():
            return self._json({"ok": False, "message": "key 不对"}, 403)
        ok, msg = self._qq_do_morning()
        return self._json({"ok": ok, "message": msg})

    def _qq_do_push(self, offset=1):
        """把「某一天的课 + 值日」推到群里。返回 (ok, message)。"""
        cfg = self._qq_cfg()
        if not qq.enabled(cfg):
            return False, "QQ 功能未启用"
        groups = sorted(qq.allow_groups(cfg))
        if not groups:
            return False, "还没配置群号"
        gid = groups[0]
        # 日报只发课表，不带值日
        seg = list(self._qq_day_text(offset, gid) or [])
        if not seg:
            return False, "没生成出内容"
        ok, info = qq.send_group_segments(cfg, seg, gid)
        self._qq_log("推送(offset=%d) -> %s %s" % (
            offset, "成功" if ok else "失败", "" if ok else str(info)[:150]))
        if ok:
            return True, "已推送"
        return False, "推送失败：%s" % (info,)

    def _qq_push_route(self):
        """定时任务调的入口：/api/qq/push?key=...&offset=1"""
        cfg = self._qq_cfg()
        q = self._query()
        want = str(cfg.get("qq_webhook_key") or "")
        key = (q.get("key") or [""])[0]
        if want and key != want and not self._is_local():
            return self._json({"ok": False, "message": "key 不对"}, 403)
        try:
            off = int((q.get("offset") or ["1"])[0])
        except Exception:
            off = 1
        ok, msg = self._qq_do_push(off)
        return self._json({"ok": ok, "message": msg})

    def _qq_day_text(self, offset=0, group_id=None):
        """某一天的课（卡片式）。返回消息段数组。"""
        import datetime as _dt

        st = self.app.store.get()
        sched = st.get("schedule", {})
        try:
            import copy as _copy
            sched = _copy.deepcopy(sched)
            overrides.apply(sched, getattr(self.app, "term_start", None))
        except Exception:
            pass

        week, _ts = self.app.current_week(sched.get("maxWeek", 20) or 20)
        day = _dt.date.today() + _dt.timedelta(days=offset)
        wd = day.isoweekday()
        week_of_day = week + (1 if (offset > 0 and day.isocalendar()[1] !=
                                    _dt.date.today().isocalendar()[1]) else 0)

        names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        when = "今天" if offset == 0 else ("明天" if offset == 1 else
                                          ("后天" if offset == 2 else "那天"))

        lst = []
        for c in (sched.get("courses") or []):
            try:
                if int(c.get("weekday") or 0) != wd:
                    continue
            except Exception:
                continue
            if week_of_day not in (c.get("weeks") or []):
                continue
            lst.append(c)
        lst.sort(key=lambda x: int(x.get("startSection") or 0))

        L = self._qq_card("%s课表" % when, "%s %s · 第 %d 周" % (
            day.strftime("%m月%d日"), names[wd - 1], week_of_day))
        L.append("")
        if not lst:
            L.append("  这天没课")
        else:
            for c in lst:
                s0 = int(c.get("startSection") or 0)
                e0 = int(c.get("endSection") or 0)
                L.append("%02d-%02d 节   %s" % (s0, e0, c.get("name") or ""))
                sub = []
                if c.get("room"):
                    sub.append(c["room"])
                if c.get("teacher"):
                    sub.append(c["teacher"])
                if sub:
                    L.append("            " + " · ".join(sub))
                L.append("")
        L.extend(self._qq_foot("PaperCloud · Q群机器人"))
        return [{"type": "text", "data": {"text": "\n".join(L)}}]


    def _qq_reply_text(self, text, gid=None, uid=None, role=""):
        t = (text or "").strip()
        # 去掉 @机器人 那部分
        t = t.replace("\u2005", " ").strip()
        key = t.lstrip("@/／.。 ")
        low = key.lower()

        if not key:
            return None
        if low in ("帮助", "help", "?", "？", "菜单"):
            return self._qq_help()
        # ---- 系统状态（所有人可查）----
        if key in ("状态", "系统状态", "运行状态", "机器状态") or low == "status":
            return self._qq_status_text()

        # ---- 管理菜单 ----
        admin_words = ("管理", "管理员", "menu", "admin", "菜单", "管理菜单")
        if low in admin_words:
            if not self._qq_is_admin(role):
                return ("【 无权限 】\n"
                        "这个菜单只有群主和管理员能用。\n\n"
                        "PaperCloud · Q群机器人")
            return self._qq_menu_open(gid, uid)

        # 菜单等待期：只认单个数字，60 秒内有效
        if gid is not None and uid is not None:
            pend = None
            with _QQ_PENDING_LOCK:
                pend = _QQ_PENDING.get((gid, uid))
            if pend:
                if time.time() > pend.get("expire", 0):
                    with _QQ_PENDING_LOCK:
                        _QQ_PENDING.pop((gid, uid), None)
                    if key.isdigit():
                        return "【 菜单已过期 】\n请重新发送「管理」\n\nPaperCloud · Q群机器人"
                elif key.isdigit():
                    self._qq_menu_take(gid, uid)
                    return self._qq_menu_run(key, gid)

        # 课表 → 白天看今天，晚上 9 点以后看明天（全班一样，不查人）
        if key in ("课表", "今课", "查课表", "有什么课"):
            return self._qq_day_text(self._qq_default_offset(), gid)
        if key in ("今天", "今日"):
            return self._qq_day_text(0, gid)
        if key in ("明天", "明日", "明课"):
            return self._qq_day_text(1, gid)
        if key in ("后天", "後天"):
            return self._qq_day_text(2, gid)

        # 整周
        if key in ("本周", "本周课表", "周课表", "全周", "整周"):
            return self._qq_week_text()

        # 值日
        if key in ("值日", "谁值日", "今天值日", "打扫"):
            return self._qq_duty_text(0, gid)[0]
        if key in ("明天值日", "明日值日"):
            return self._qq_duty_text(1, gid)[0]
        return None

    def _qq_log(self, text):
        """把 QQ 事件写进日志，排查用。只保留最近 300 行。"""
        try:
            p = os.path.join(DATA_DIR, "qq_events.log")
            line = "%s  %s\n" % (time.strftime("%m-%d %H:%M:%S"), text)
            lines = []
            if os.path.isfile(p):
                with open(p, encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()[-299:]
            lines.append(line)
            with open(p, "w", encoding="utf-8") as f:
                f.writelines(lines)
        except Exception:
            pass

    def _qq_raw(self):
        """极简诊断：有没有收到过 webhook、最后一次长什么样。"""
        p = os.path.join(DATA_DIR, "qq_events.log")
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except Exception:
            lines = []
        cfg = self._qq_cfg()
        return self._json({
            "ok": True,
            "enabled": qq.enabled(cfg),
            "groups": sorted(qq.allow_groups(cfg)),
            "events": len(lines),
            "tail": "".join(lines[-12:]),
        })

    def _qq_debug(self):
        p = os.path.join(DATA_DIR, "qq_events.log")
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                txt = f.read()
        except Exception:
            txt = "（还没有事件。说明 NapCat 的上报没打到本站）"
        cfg = self._qq_cfg()
        return self._json({
            "ok": True,
            "enabled": qq.enabled(cfg),
            "api": qq.base_url(cfg),
            "allow_groups": sorted(qq.allow_groups(cfg)),
            "webhook_key_set": bool(cfg.get("qq_webhook_key")),
            "log": txt[-6000:],
        })

    def _qq_default_offset(self):
        """晚上 9 点以后，问课表就默认看明天。"""
        import datetime as _dt
        return 1 if _dt.datetime.now().hour >= 21 else 0

    def _qq_known(self, text):
        """这条命令认不认识（不生成内容，只做判断）。"""
        t = (text or "").strip().replace("\u2005", " ")
        key = t.lstrip("@/／.。 ")
        if not key:
            return False
        words = ("帮助", "help", "?", "？", "菜单",
                 "课表", "今天", "今日", "今课", "查课表", "有什么课",
                 "明天", "明日", "明课", "后天", "後天",
                 "本周", "本周课表", "周课表", "全周", "整周",
                 "值日", "谁值日", "今天值日", "打扫",
                 "明天值日", "明日值日",
                 "状态", "系统状态", "运行状态", "机器状态", "status")
        return key in words or key.lower() in words

    def _qq_webhook(self, body=None):
        cfg = self._qq_cfg()
        q = self._query()
        key = (q.get("key") or [""])[0]
        want = str(cfg.get("qq_webhook_key") or "")
        local = self._is_local()
        if want and key != want and not local:
            self._qq_log("key 不匹配（收到=%r 期望=%r 来自=%s）"
                         % (key[:24], want[:8] + "…", getattr(self, "_ip", "")))
            return self._json({"ok": False, "message": "key 不对"}, 403)

        if not isinstance(body, dict):
            return self._json({"ok": False, "message": "body 不是 JSON"}, 400)

        try:
            raw_txt = json.dumps(body, ensure_ascii=False)[:400]
        except Exception:
            raw_txt = "（无法序列化）"
        self._qq_log("原始报文: %s" % raw_txt)

        ev = qq.parse_event(body)
        if not ev:
            self._qq_log("收到非消息事件: post_type=%s" % (body.get("post_type"),))
            return self._json({"ok": True, "ignored": True, "why": "not_message"})

        gid = ev.get("group_id")
        uid = ev.get("user_id")
        mtype = ev.get("message_type") or ""
        text = ev.get("text") or ""
        role = ev.get("role") or ""
        self._qq_log("消息 群=%s 用户=%s 类型=%s 内容=%r" % (gid, uid, mtype, text[:60]))

        if mtype != "group":
            self._qq_log("  -> 不是群消息，忽略")
            return self._json({"ok": True, "ignored": True, "why": "not_group"})

        allow = sorted(qq.allow_groups(cfg))
        if not self._qq_allowed(gid):
            self._qq_log("  -> 群号不在白名单，忽略（当前白名单=%s）" % (allow,))
            return self._json({"ok": True, "ignored": True,
                               "why": "group_not_allowed", "allow": allow})

        # 先把命令认掉，认不出就直接回，不用开线程
        if not self._qq_known(text):
            self._qq_log("  -> 不认识这条命令，忽略")
            return self._json({"ok": True, "ignored": True, "why": "no_command"})

        # 认得出就把活儿丢到后台：查群成员 + 发消息可能要好几秒，
        # NapCat 的 HTTP 上报等不了这么久，同步做会被它当成超时。
        def _work(gid=gid, text=text, cfg=cfg, uid=uid, role=role):
            try:
                reply = self._qq_reply_text(text, gid, uid, role)
                if not reply:
                    self._qq_log("  -> 后台：没生成出内容")
                    return
                if isinstance(reply, list):
                    ok, info = qq.send_group_segments(cfg, reply, gid)
                    if not ok:
                        # 数组发不出去就退回 CQ 码字符串
                        self._qq_log("  -> 数组发送失败，改试文本: %s" % str(info)[:100])
                        ok, info = qq.send_group(cfg, qq.segments_to_cq(reply), gid)
                else:
                    ok, info = qq.send_group(cfg, reply, gid)
                self._qq_log("  -> 发送%s %s" % ("成功" if ok else "失败",
                                                 "" if ok else str(info)[:200]))
            except Exception as e:
                self._qq_log("  -> 后台异常: %s: %s" % (type(e).__name__, e))

        try:
            threading.Thread(target=_work, daemon=True).start()
        except Exception as e:
            self._qq_log("  -> 起线程失败，改成同步: %s" % e)
            _work()

        return self._json({"ok": True, "accepted": True})

    def _qq_status(self):
        cfg = self._qq_cfg()
        ok, who = qq.ping(cfg) if qq.enabled(cfg) else (False, "未启用")
        return self._json({
            "ok": True,
            "enabled": qq.enabled(cfg),
            "api": qq.base_url(cfg),
            "groups": sorted(qq.allow_groups(cfg)),
            "online": bool(ok),
            "account": who if isinstance(who, str) else str(who)[:120],
            "webhook_key_set": bool(cfg.get("qq_webhook_key")),
        })

    def _tools_diag(self):
        """自检页：用浏览器打开 /tools/diag 就能看懂哪里不对。"""
        import os as _os
        k = str(self.app.cfg.get("deepseek_key") or "")
        if not k:
            try:
                import json as _j
                for fn in ("secrets.json", "config.json"):
                    p = _os.path.join(DATA_DIR, "..", "config", fn)
                    if _os.path.isfile(p):
                        v = str(_j.load(open(p, encoding="utf-8-sig")).get("deepseek_key") or "")
                        if v:
                            k = v; break
            except Exception:
                pass
        rows = [
            ("服务器代码版本", BUILD_TAG, True),
            ("DeepSeek Key", ("已配置 …" + k[-4:]) if k else " 没读到", bool(k)),
            ("班级成员密码", "已配置", bool(self.app.cfg.get("roster_password"))),
            ("年级选项", "%d 个" % len(essay.GRADES), len(essay.GRADES) > 0),
            ("OCR 脚本 ocr.ps1", "在" if _os.path.isfile(essay.OCR_PS1) else " 缺失", _os.path.isfile(essay.OCR_PS1)),
            ("PowerShell", "在" if _os.path.isfile(essay.PS) else " 缺失", _os.path.isfile(essay.PS)),
        ]
        try:
            caps = toolbox.capabilities()
        except Exception:
            caps = {}
        LAB = {"ffmpeg": "ffmpeg（音视频）", "pillow": "Pillow（图片）",
               "aes": "音乐解锁 AES", "pypdf": "pypdf（PDF 操作）",
               "pypdfium2": "pypdfium2（PDF 转图）", "docx": "python-docx",
               "pptx": "python-pptx", "openpyxl": "openpyxl"}
        for k, nm in LAB.items():
            if k in caps:
                v = "正常" if caps[k] else " 缺失"
                if k == "aes" and caps.get("aes_backend"):
                    v = "正常（" + caps["aes_backend"] + "）"
                rows.append((nm, v, bool(caps[k])))

        ok_all = all(r[2] for r in rows)
        color = "#12a05a" if ok_all else "#f2555a"
        head = " 全部正常，AI 批改可以用" if ok_all else " 还有问题，看下面标红的那行"
        body = "".join(
            '<tr><td style="padding:9px 14px;color:#5a6b7d">%s</td>'
            '<td style="padding:9px 14px;font-weight:700;color:%s">%s</td></tr>'
            % (n, ("#12a05a" if good else "#f2555a"), val)
            for n, val, good in rows)
        html = (
            '<!doctype html><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>自检</title>'
            '<body style="margin:0;padding:22px;background:#0e1520;color:#e9f1fa;'
            'font:15px/1.6 -apple-system,BlinkMacSystemFont,PingFang SC,Microsoft YaHei,sans-serif">'
            '<div style="max-width:520px;margin:0 auto">'
            '<h2 style="font-size:19px;margin:0 0 4px">PaperCloud 自检</h2>'
            '<p style="margin:0 0 18px;color:%s;font-weight:800;font-size:16px">%s</p>'
            '<table style="width:100%%;border-collapse:collapse;background:#18212e;'
            'border-radius:12px;overflow:hidden;font-size:14px">%s</table>'
            '<p style="margin:16px 0 0;color:#7d8fa3;font-size:12.5px;line-height:1.8">'
            '如果 Key 那行是红的：<br>'
            '1. 确认项目里 config\\secrets.json 有 "deepseek_key"<br>'
            '2. 改完必须重启服务（杀掉所有 python.exe 再启动）<br>'
            '3. 版本那行不是 %s 就是 server.py 没生效</p>'
            '</div></body>') % (color, head, body, BUILD_TAG)
        return self._send(200, html, "text/html; charset=utf-8")


    def _tools_lookup(self):
        """凭取件码查回文件。取件码本身就是凭证，所以不额外校验口令。"""
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        code = (qs.get("code") or [""])[0].strip().upper()
        if not code:
            return self._json({"ok": False, "message": "请输入取件码"}, 400)
        job = toolbox.get_job(code)
        if not job:
            return self._json({"ok": False, "message": "取件码不存在，或者文件已经过期删掉了"}, 404)
        dd = toolbox.job_dir(code)
        files = []
        for f in (job.get("files") or []):
            p = os.path.join(dd, f.get("name") or "")
            if os.path.isfile(p):
                files.append({"name": f.get("name"), "size": os.path.getsize(p),
                              "kind": toolbox.kind_of(f.get("name") or "")})
        # 转换产出的文件也一起列出来（从 ops 里翻）
        seen = set(x["name"] for x in files)
        try:
            for root, _dirs, fs in os.walk(dd):
                for fn in fs:
                    if fn in seen:
                        continue
                    p = os.path.join(root, fn)
                    rel = os.path.relpath(p, dd).replace("\\", "/")
                    seen.add(fn)
                    files.append({"name": rel, "size": os.path.getsize(p),
                                  "kind": toolbox.kind_of(fn)})
        except Exception:
            pass
        return self._json({
            "ok": True, "code": code, "files": files,
            "expire": job.get("expire"),
            "created": job.get("created"),
        })


    def _tools_essay(self, body):
        """ai 批改。分两段：
             stage=ocr   逐张识别，返回每张的文字（前端能显示一张一张的进度）
             stage=grade 拿到文字后直接批改（DeepSeek）
        """
        B = body or {}
        stage = str(B.get("stage") or "grade")

        # ---------------- 逐张识别 ----------------
        if stage == "ocr":
            code = str(B.get("code") or "").upper()
            names = B.get("files") or []
            job = toolbox.get_job(code)
            if not job:
                return self._json({"ok": False, "message": "提取码不存在"}, 404)
            dd = toolbox.job_dir(code)
            out = []
            for n in names[:10]:
                p = os.path.join(dd, os.path.basename(str(n)))
                if not os.path.isfile(p):
                    continue
                t = essay.ocr_image(p)
                # 隐私：识别完立刻删图，不在服务器留痕
                try:
                    os.remove(p)
                except Exception:
                    pass
                out.append({"name": n, "text": t, "chars": len(t)})
            if not out:
                return self._json({"ok": False, "message": "没有找到图片"}, 400)
            return self._json({"ok": True, "items": out})

        # ---------------- 批改 ----------------
        grade = str(B.get("grade") or "").strip()
        if not grade or grade not in essay.GRADES:
            return self._json({"ok": False, "message": "请先选择年级"}, 400)

        text = str(B.get("text") or "")
        if not text.strip():
            # 没传文字就自己 OCR 一遍（兼容旧调用）
            code = str(B.get("code") or "").upper()
            names = B.get("files") or []
            job = toolbox.get_job(code)
            if not job:
                return self._json({"ok": False, "message": "提取码不存在"}, 404)
            dd = toolbox.job_dir(code)
            paths = []
            for n in names[:10]:
                p = os.path.join(dd, os.path.basename(str(n)))
                if os.path.isfile(p):
                    paths.append(p)
            if not paths:
                return self._json({"ok": False, "message": "没有找到图片"}, 400)
            toolbox._slot()
            try:
                ok, txt, info = essay.grade_essay(self.app.cfg, paths, grade)
            finally:
                toolbox._release()
            for p in paths:
                try:
                    os.remove(p)
                except Exception:
                    pass
            if not ok:
                return self._json({"ok": False, "message": txt}, 400)
            return self._json({"ok": True, "result": txt, "info": info, "grade": grade})

        toolbox._slot()
        try:
            ok, txt, info = essay.grade_text(self.app.cfg, text, grade)
        finally:
            toolbox._release()
        if not ok:
            return self._json({"ok": False, "message": txt}, 400)
        return self._json({"ok": True, "result": txt, "info": info, "grade": grade})


    def _tools_disk(self):
        """返回磁盘剩余量。工具箱的文件放 3 天，看看还剩多少地方。"""
        import shutil as _sh
        try:
            u = _sh.disk_usage(toolbox.BOX_DIR if os.path.isdir(toolbox.BOX_DIR) else DATA_DIR)
            used_by_box = 0
            try:
                for root, _dirs, files in os.walk(toolbox.BOX_DIR):
                    for fn in files:
                        try:
                            used_by_box += os.path.getsize(os.path.join(root, fn))
                        except Exception:
                            pass
            except Exception:
                pass
            jobs = len(toolbox._load())
            return self._json({
                "ok": True,
                "total": u.total,
                "used": u.used,
                "free": u.free,
                "percent": round(u.used * 100.0 / u.total, 1) if u.total else 0,
                "box_bytes": used_by_box,
                "jobs": jobs,
            })
        except Exception as e:
            return self._json({"ok": False, "message": "%s: %s" % (type(e).__name__, e)}, 500)


    def _tools_file(self):
        """下载。带 ?code= 和 ?name=。"""
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        code = (qs.get("code") or [""])[0].upper()
        name = os.path.basename((qs.get("name") or [""])[0])
        job = toolbox.get_job(code)
        if not job or not name:
            return self._send(404, "找不到文件", "text/plain; charset=utf-8")
        path = os.path.join(toolbox.job_dir(code), name)
        if not os.path.isfile(path):
            return self._send(404, "文件已过期或被删", "text/plain; charset=utf-8")
        try:
            with open(path, "rb") as f:
                blob = f.read()
        except Exception:
            return self._send(500, "读取失败", "text/plain; charset=utf-8")
        quoted = urllib.parse.quote(name)
        return self._send(200, blob, "application/octet-stream", extra={
            "Content-Disposition": "attachment; filename*=UTF-8''" + quoted,
        })

    def _tools_mine(self):
        ip, ck = self._who()
        jobs = toolbox.list_jobs(ip=ip, cookie=ck)
        return self._json({"ok": True, "jobs": jobs})

    # ------------------------------------------------ 班级成员锁
    def _roster_secret(self):
        return str(self.app.cfg.get("secret_key")
                   or self.app.cfg.get("agent_token") or "kt-roster").encode()

    def _roster_sign(self, exp):
        return hmac.new(self._roster_secret(), str(exp).encode(), hashlib.sha256).hexdigest()[:32]

    def _roster_ok(self):
        """班级成员是否已解锁。管理员永远算解锁。"""
        try:
            if self._admin_authed():
                return True
        except Exception:
            pass
        raw = (self._cookies().get(ROSTER_COOKIE) or "").strip()
        if not raw or "." not in raw:
            return False
        exp, sig = raw.rsplit(".", 1)
        try:
            if int(exp) < time.time():
                return False
        except Exception:
            return False
        return hmac.compare_digest(sig, self._roster_sign(exp))

    def _roster_password(self):
        return str(self.app.cfg.get("roster_password")
                   or self.app.cfg.get("admin_password") or "")

    def _roster_unlock(self, body):
        code = str((body or {}).get("code") or "")
        want = self._roster_password()
        if not want:
            return self._json({"ok": False, "message": "没设置查看密码"}, 400)
        if not hmac.compare_digest(code, want):
            return self._json({"ok": False, "message": "密码不对"}, 403)
        exp = int(time.time()) + ROSTER_TTL
        val = "%d.%s" % (exp, self._roster_sign(exp))
        # 注意：_json() 不接受 extra，必须用 _send
        return self._send(200, json.dumps({
            "ok": True, "minutes": ROSTER_TTL // 60,
        }, ensure_ascii=False), extra={
            "Set-Cookie": "%s=%s; Path=/; Max-Age=%d; SameSite=Lax; HttpOnly"
                          % (ROSTER_COOKIE, val, ROSTER_TTL),
        })

    def _roster_state(self):
        return self._json({"ok": True, "unlocked": self._roster_ok()})


    def _kt_splash(self, data):
        """在 <body> 之后直出骨架层，保证首帧就是骨架。"""
        try:
            # 720 全景是独立播放器，不能被全站注入干扰
            if self.path.startswith("/tour"):
                return data
            if b"KT-SKELETON" in data or b"KT-NO-INJECT" in data:
                return data
            snip = KT_SKELETON.encode("utf-8")
            k = data.find(b"<body")
            if k >= 0:
                gt = data.find(b">", k)
                if gt >= 0:
                    return data[:gt + 1] + snip + data[gt + 1:]
            return snip + data
        except Exception:
            return data


    def _kt_topbar(self, data):
        """给任意 HTML 注入全站顶部加载条。已经注过的原样返回。"""
        try:
            if self.path.startswith("/tour"):
                return data
            if b"KT-TOPBAR" in data or b"KT-NO-INJECT" in data:
                return data
            # 缩放比例由 PAGE_ZOOM 常量统一控制，改一处全站生效
            # 百度 HTML 标签验证：把 codeva-xxx 写进 data/baidu_verify.txt 即可
            _bv = ""
            try:
                with open(os.path.join(os.path.dirname(os.path.dirname(
                        os.path.abspath(__file__))), "data",
                        "baidu_verify.txt"), encoding="utf-8-sig") as _f:
                    _bv = _f.read().strip()
            except Exception:
                _bv = ""
            if _bv:
                _meta = ('<meta name="baidu-site-verification" content="'
                         + _bv + '" />')
            else:
                _meta = ""

            _z = ("%.2f" % PAGE_ZOOM).rstrip("0").rstrip(".") or "1"
            snip = TOPBAR_SNIPPET.replace("__KT_ZOOM__", _z).encode("utf-8")
            if _meta:
                snip = _meta.encode("utf-8") + snip
            if b"</body>" in data:
                return data.replace(b"</body>", snip + b"</body>", 1)
            return data + snip
        except Exception:
            return data


    def _serve_file(self, rel, cache="", public=False, force_ctype=None):
        safe = os.path.normpath(rel).replace("\\", "/").lstrip("/")
        if safe.startswith(".."):
            return self._send(403, "forbidden", "text/plain")

        # 抓取脚本要能被「教务系统页面」这个别的源加载，所以放行 CORS 且不要求口令
        is_grab = safe in ("grab.js", "web-tools/grab.js")
        # public：/static/ 下的 CSS/JS 不需要口令。
        # 浏览器加载 <link>/<script> 时不会带 ?k=，这里若仍校验口令，
        # 返回的会是登录页 HTML —— 现象就是「页面能打开但完全没样式、课表空白」。
        if not public and not self._authed() and not is_grab:
            # 登录后回到原来想去的页面（比如 /dashboard）
            return self._login_page(next_path=self.path.split("?")[0])

        if safe == "grab.js":
            # 唯一来源在 web-tools/，避免 web/ 下留一份不同步的副本
            full = os.path.join(os.path.dirname(WEB_DIR), "web-tools", "grab.js")
        else:
            full = os.path.join(WEB_DIR, safe)
        if not os.path.isfile(full):
            return self._send(404, "not found", "text/plain")
        ctype = force_ctype or mimetypes.guess_type(full)[0] or "application/octet-stream"
        if "charset" not in ctype and (ctype.startswith("text/") or ctype in ("application/javascript",)):
            ctype += "; charset=utf-8"
        with open(full, "rb") as f:
            data = f.read()



        extra = None
        if cache == "asset":
            # 静态资源：让 Cloudflare 边缘和浏览器都能长期缓存。
            #
            # 为什么现在敢这么设了：
            #   index.html 里的引用带了版本号（/static/app.js?v=20261013d）。
            #   改了文件就同时改版本号，URL 一变就是全新的资源，
            #   不会被旧缓存粘住 —— 这正是之前 max-age=300 踩过的坑。
            #
            # 好处：50 人同时打开时，CSS/JS 直接从 Cloudflare 边缘拿，
            #       不穿隧道回源到家里，家里宽带压力几乎为零。
            #
            # 注意：Cloudflare 免费版默认只对常见静态扩展名（.css/.js/.png…）
            #       做边缘缓存，正好覆盖这些文件。
            import hashlib
            extra = {
                "Cache-Control": "public, max-age=604800, immutable",
                "ETag": '"' + hashlib.md5(data).hexdigest()[:16] + '"',
                # 显式告诉 Cloudflare 可以缓存（免费版也认这个头）
                "Cloudflare-CDN-Cache-Control": "public, max-age=604800",
            }

        self._send(200, data, ctype, cors=is_grab, extra=extra)


class _Server(ThreadingHTTPServer):
    """关掉 SO_REUSEADDR。

    为什么：在 Windows 上 SO_REUSEADDR 的语义和 Linux 不同 ——
    它允许第二个进程绑到同一个端口，而不是报错。后果是
    「同一个端口上悄悄跑着两个服务」，两个都在写心跳、都在处理请求，
    出问题极难排查（曾经真的出现过：累计运行时长被两倍速累加）。

    关掉之后，第二个实例会在绑定时直接失败退出，run.bat 的重试循环
    会等第一个死掉再接上 —— 这才是想要的行为。
    """
    allow_reuse_address = False


class Server:
    def __init__(self, cfg, app):
        self.cfg = cfg
        self.app = app
        bind = cfg.get("bind", "127.0.0.1")
        port = int(cfg.get("port", 8787))
        handler = type("BoundHandler", (Handler,), {"app": app})
        self.httpd = _Server((bind, port), handler)
        self.httpd.daemon_threads = True
        self.bind, self.port = bind, port

    def serve_forever(self):
        self.httpd.serve_forever()

    def start_background(self):
        t = threading.Thread(target=self.serve_forever, daemon=True)
        t.start()
        return t
