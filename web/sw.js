/* ===========================================================================
   在线课表 · Service Worker
   ---------------------------------------------------------------------------
   目的只有一个：断网/隧道挂掉时，看板还能显示上次拿到的课表。

   策略：
     课表接口 (/api/schedule)  -> 网络优先，失败时回退到缓存（离线照常看）
     看板外壳 (dashboard/图标)  -> 缓存优先，后台顺便更新
     其它 /api/*               -> 直接走网络，不缓存（有口令、有实时性要求）

   注意：只缓存 GET，且不缓存任何带口令的响应到磁盘以外的地方。
   =========================================================================== */

var VERSION = 'kt-v2';
var SHELL = [
  '/dashboard',
  '/manifest.webmanifest',
  '/favicon.ico',
  '/favicon-192.png',
  '/favicon-512.png',
  '/apple-touch-icon.png'
];

self.addEventListener('install', function (e) {
  e.waitUntil(
    caches.open(VERSION).then(function (c) {
      // 逐个加，单个失败不影响整体安装
      return Promise.all(SHELL.map(function (u) {
        return c.add(new Request(u, { cache: 'reload' })).catch(function () { });
      }));
    }).then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener('activate', function (e) {
  e.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.map(function (k) {
        if (k !== VERSION) return caches.delete(k);
      }));
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener('fetch', function (e) {
  var req = e.request;
  if (req.method !== 'GET') return;

  var url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // ---- 课表接口：网络优先，离线回退缓存 ----
  if (url.pathname === '/api/schedule') {
    e.respondWith(
      fetch(req).then(function (res) {
        if (res && res.ok) {
          var copy = res.clone();
          caches.open(VERSION).then(function (c) { c.put('/api/schedule', copy); });
        }
        return res;
      }).catch(function () {
        return caches.match('/api/schedule').then(function (hit) {
          if (hit) return hit;
          return new Response(JSON.stringify({ ok: false, offline: true, courses: [] }),
            { status: 200, headers: { 'Content-Type': 'application/json' } });
        });
      })
    );
    return;
  }

  // ---- 其它接口：不缓存 ----
  if (url.pathname.indexOf('/api/') === 0 || url.pathname === '/events') return;

  // ---- 页面与静态资源：网络优先，断网回退缓存 ----
  //
  // 为什么不是「缓存优先」：
  //   看板还会继续改。缓存优先的话，改完 HTML 用户看到的仍是旧版，
  //   而且要等第二次打开才更新，排查起来很像「改了没生效」。
  //   网络优先 = 有网永远是最新的，没网才用缓存，两头都占。
  e.respondWith(
    fetch(req).then(function (res) {
      if (res && res.ok && res.type === 'basic') {
        var copy = res.clone();
        caches.open(VERSION).then(function (c) { c.put(req, copy); });
      }
      return res;
    }).catch(function () {
      return caches.match(req).then(function (hit) {
        if (hit) return hit;
        // 页面实在没有缓存时，给一个能看懂的提示，而不是浏览器默认的错误页
        if (req.mode === 'navigate') {
          return new Response(
            '<!doctype html><meta charset="utf-8">' +
            '<meta name="viewport" content="width=device-width,initial-scale=1">' +
            '<body style="font-family:-apple-system,sans-serif;background:#0e1520;color:#e9f0f7;' +
            'display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center">' +
            '<div><div style="font-size:17px;font-weight:700;margin-bottom:8px">暂时连不上服务器</div>' +
            '<div style="color:#93a7ba;font-size:13px">请检查网络，或稍后重试</div></div></body>',
            { status: 200, headers: { 'Content-Type': 'text/html; charset=utf-8' } });
        }
      });
    })
  );
});
