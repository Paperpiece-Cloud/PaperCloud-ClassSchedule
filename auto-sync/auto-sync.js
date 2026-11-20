/**
 * PaperCloud 课表自动同步 · 无头浏览器版
 *
 * 为什么不用纯 HTTP：
 *   教务系统不认 CAS 发的票据，纯 HTTP 会 CAS↔教务 无限打转。
 *   但真浏览器能进得去，所以这里开一个真 Edge，用它自己的登录态抓。
 *
 * 原理：
 *   1. 启动 Edge（固定用户目录，登录态保存在里面）
 *   2. 通过 CDP 打开教务系统页面
 *   3. 在页面里执行 JS：读 sessionStorage 里的 accessToken，
 *      调课表接口，把结果丢回来
 *   4. Node 侧 POST 给 PaperCloud
 *   5. 关掉 Edge
 *
 * 零依赖：只用 Node 内置的 http / child_process / 全局 WebSocket(Node 22+)。
 */

const { spawn } = require('child_process');
const http = require('http');
const fs = require('fs');
const path = require('path');
const os = require('os');

// ---------------------------------------------------------------- 配置
const UPLOAD = 'https://your-domain.example/api/import-session?k=YOUR_ACCESS_CODE';
const JW = 'https://jw.gzdzxy.cn';
const PORTAL = 'https://one.gzdzxy.cn/up/';
const DEBUG_PORT = 9223;
const PROFILE = path.join(os.homedir(), 'PaperCloudProfile');
const LOG = path.join(__dirname, 'auto-sync.log');
// 默认用【可见】窗口跑 —— 无头模式容易被学校那边识破，
// 导致门户能登进去但教务系统拿不到会话。
// 想用无头就在命令行加 --headless。
const HEADLESS = process.argv.indexOf('--headless') >= 0;

function log() {
  const line = new Date().toLocaleString('zh-CN') + '  ' +
    [].slice.call(arguments).join(' ');
  console.log(line);
  try { fs.appendFileSync(LOG, line + '\n'); } catch (e) { }
}

function findEdge() {
  const cands = [
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
    path.join(process.env.LOCALAPPDATA || '', 'Microsoft\\Edge\\Application\\msedge.exe'),
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe'
  ];
  for (const p of cands) if (p && fs.existsSync(p)) return p;
  throw new Error('找不到 Edge / Chrome');
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

/* ---------------- 账号密码 ----------------
 * 从脚本旁边的 login.txt 读，格式：
 *     user=20265103010028
 *     pass=你的密码
 * 有它就能在登录过期时自动重登，真正做到无人值守。
 * 没有也能跑，只是过期了需要手动跑一次 1-first-login.bat。
 */
function readLogin() {
  const f = path.join(__dirname, 'login.txt');
  if (!fs.existsSync(f)) return null;
  const txt = fs.readFileSync(f, 'utf8');
  const u = (txt.match(/^\s*user\s*=\s*(.+)$/m) || [])[1];
  const p = (txt.match(/^\s*pass\s*=\s*(.+)$/m) || [])[1];
  if (!u || !p) return null;
  return { user: u.trim(), pass: p.trim() };
}

/* 在 CAS 登录页上填表并提交（页面自己的 JS 会算 rsa 签名） */
async function autoLogin(cdp, cred) {
  log('尝试自动登录…');
  const r = await cdp.send('Runtime.evaluate', {
    expression: `
      (function () {
        function pick(names) {
          for (var i = 0; i < names.length; i++) {
            var el = document.querySelector(names[i]);
            if (el) return el;
          }
          return null;
        }
        var u = pick(['#un', 'input[name=un]', '#username', 'input[name=username]']);
        var p = pick(['#pd', 'input[name=pd]', '#password', 'input[name=password]']);
        if (!u || !p) return 'no-form';
        u.focus();
        u.value = ${JSON.stringify(cred.user)};
        u.dispatchEvent(new Event('input', {bubbles:true}));
        u.dispatchEvent(new Event('change', {bubbles:true}));
        p.focus();
        p.value = ${JSON.stringify(cred.pass)};
        p.dispatchEvent(new Event('input', {bubbles:true}));
        p.dispatchEvent(new Event('change', {bubbles:true}));

        // 关键：必须点页面上的登录按钮。
        // 直接 form.submit() 会绕过它自己的 JS —— 那样算不出 rsa 签名，
        // 学校那边会当成密码错误直接把请求打回来。
        var btn = pick([
          '.login_box_landing_btn',
          '#loginBtn', '#login-btn', '#login',
          'button[type=submit]', 'input[type=submit]',
          '.login-btn', '.btn-login'
        ]);
        if (btn) {
          btn.click();
          return 'clicked:' + (btn.className || btn.id || btn.tagName);
        }
        return 'no-button';
      })()
    `,
    returnByValue: true
  });
  log('  填表结果:', r.result.value);

  // JS 里找不到按钮 -> 用 CDP 真鼠标点一下兜底
  if (String(r.result.value).indexOf('no-button') === 0) {
    log('  找不到按钮，改用真实鼠标点击…');
    const box = await cdp.send('Runtime.evaluate', {
      expression: `(function(){
        var b = document.querySelector('.login_box_landing_btn')
             || document.querySelector('input[type=button]');
        if (!b) return '';
        b.scrollIntoView({block:'center'});
        var r = b.getBoundingClientRect();
        return JSON.stringify({x: r.left + r.width/2, y: r.top + r.height/2});
      })()`,
      returnByValue: true
    });
    let pt = null;
    try { pt = JSON.parse(box.result.value); } catch (e) { }
    if (pt) {
      for (const type of ['mousePressed', 'mouseReleased']) {
        await cdp.send('Input.dispatchMouseEvent', {
          type, x: pt.x, y: pt.y, button: 'left', clickCount: 1
        });
      }
      log('  已点击', Math.round(pt.x), Math.round(pt.y));
    }
  }
  return true;
}

function httpGet(url) {
  return new Promise((resolve, reject) => {
    http.get(url, res => {
      let b = '';
      res.on('data', c => b += c);
      res.on('end', () => resolve(b));
    }).on('error', reject);
  });
}

// ---------------------------------------------------------------- CDP 极简客户端
class CDP {
  constructor(ws) { this.ws = ws; this.id = 0; this.waiting = new Map(); this.events = []; }

  static async attach(wsUrl) {
    const ws = new WebSocket(wsUrl);
    await new Promise((res, rej) => {
      ws.addEventListener('open', res, { once: true });
      ws.addEventListener('error', rej, { once: true });
    });
    const c = new CDP(ws);
    ws.addEventListener('message', ev => {
      let m;
      try { m = JSON.parse(ev.data); } catch (e) { return; }
      if (m.id && c.waiting.has(m.id)) {
        const { resolve, reject } = c.waiting.get(m.id);
        c.waiting.delete(m.id);
        m.error ? reject(new Error(JSON.stringify(m.error))) : resolve(m.result);
      } else if (m.method) {
        c.events.push(m);
      }
    });
    return c;
  }

  send(method, params) {
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      this.waiting.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params: params || {} }));
      setTimeout(() => {
        if (this.waiting.has(id)) {
          this.waiting.delete(id);
          reject(new Error('CDP 超时: ' + method));
        }
      }, 60000);
    });
  }

  close() { try { this.ws.close(); } catch (e) { } }
}

// ---------------------------------------------------------------- 主流程
(async function main() {
  const t0 = Date.now();
  log('=== 开始同步 ===' + (HEADLESS ? '（无头）' : '（可见）'));

  const edge = findEdge();
  log('浏览器:', path.basename(edge));

  const args = [
    '--user-data-dir=' + PROFILE,
    '--remote-debugging-port=' + DEBUG_PORT,
    '--no-first-run', '--no-default-browser-check',
    '--disable-popup-blocking', '--disable-features=Translate',
    '--remote-allow-origins=*'
  ];
  if (HEADLESS) args.push('--headless=new', '--disable-gpu');
  args.push('about:blank');

  const child = spawn(edge, args, { stdio: 'ignore', detached: false });
  let cdp = null;

  try {
    // 等调试端口起来
    let targets = null;
    for (let i = 0; i < 40; i++) {
      await sleep(500);
      try {
        const raw = await httpGet('http://127.0.0.1:' + DEBUG_PORT + '/json/list');
        targets = JSON.parse(raw);
        if (targets && targets.length) break;
      } catch (e) { }
    }
    if (!targets || !targets.length) throw new Error('浏览器调试端口没起来');
    const page = targets.find(t => t.type === 'page') || targets[0];
    cdp = await CDP.attach(page.webSocketDebuggerUrl);
    await cdp.send('Page.enable');
    await cdp.send('Runtime.enable');

    // ---------------- 1. 打开教务系统 ----------------
    log('打开教务系统…');
    await cdp.send('Page.navigate', { url: JW + '/grd/' });
    await sleep(6000);

    const info = await cdp.send('Runtime.evaluate', {
      expression: 'JSON.stringify({url:location.href, hasUser:!!sessionStorage.getItem("user")})',
      returnByValue: true
    });
    let st = {};
    try { st = JSON.parse(info.result.value); } catch (e) { }
    log('当前页面:', (st.url || '').slice(0, 80), ' 已登录:', st.hasUser);

    // 没登录 -> 走门户
    if (!st.hasUser) {
      log('没有教务会话，先开门户…');
      await cdp.send('Page.navigate', { url: PORTAL });
      await sleep(6000);

      let here = (await cdp.send('Runtime.evaluate', {
        expression: 'location.href', returnByValue: true
      })).result.value || '';
      log('门户页面:', here.slice(0, 90));

      // 落在 CAS 登录页 -> 有账号密码就自动登
      if (/cas\.gzdzxy\.cn\/sso\/login/.test(here)) {
        const cred = readLogin();
        if (cred) {
          await autoLogin(cdp, cred);
          await sleep(8000);
          here = (await cdp.send('Runtime.evaluate', {
            expression: 'location.href', returnByValue: true
          })).result.value || '';
          log('登录后地址:', here.slice(0, 90));
        } else {
          log('  没有 login.txt，跳过自动登录');
        }
      }

      // 回到教务系统
      await cdp.send('Page.navigate', { url: JW + '/grd/' });
      await sleep(7000);
      const again = await cdp.send('Runtime.evaluate', {
        expression: '!!sessionStorage.getItem("user")', returnByValue: true
      });
      if (!again.result.value) {
        log('!! 教务系统仍无会话。');
        log('   要么在 login.txt 里填上账号密码，');
        log('   要么手动跑一次 1-first-login.bat。');
        throw new Error('未登录');
      }
      log('已拿到教务会话');
    }

    // ---------------- 2. 在页面里抓课表 ----------------
    log('调用课表接口…');
    const expr = `
      (async function () {
        try {
          var u = {};
          try { u = JSON.parse(sessionStorage.getItem('user') || '{}'); } catch (e) {}
          var tok = u.accessToken || '';
          function md5(s){ return ''; }
          // 用页面自带的接口层：直接 fetch 带 Authorization
          var ts = Math.floor(Date.now() / 1000);
          var url = '/grd/api/arrange/CourseScheduleAllQuery/studentCourseSchedule?_t=' + ts;
          var r = await fetch(url, {
            method: 'POST',
            credentials: 'include',
            headers: {
              'Content-Type': 'application/json',
              'Authorization': tok ? ('Bearer ' + tok) : undefined,
              'X-Requested-With': 'XMLHttpRequest'
            },
            body: JSON.stringify({
              studentId: '', oddOrDouble: 1, source: 'xs',
              semester: '', weeks: [1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20]
            })
          });
          var t = await r.text();
          return JSON.stringify({ status: r.status, body: t.slice(0, 400000) });
        } catch (e) {
          return JSON.stringify({ error: String(e) });
        }
      })()
    `;
    const got = await cdp.send('Runtime.evaluate', {
      expression: expr, awaitPromise: true, returnByValue: true
    });
    let out = {};
    try { out = JSON.parse(got.result.value); } catch (e) { out = { error: '解析失败' }; }

    if (out.error) throw new Error('页面里抓取失败: ' + out.error);
    log('接口返回 HTTP', out.status, ' 长度', (out.body || '').length);

    let parsed = null;
    try { parsed = JSON.parse(out.body); } catch (e) { }
    const dataPart = parsed && parsed.data ? parsed.data : parsed;
    const n = Array.isArray(dataPart) ? dataPart.length : (dataPart ? Object.keys(dataPart).length : 0);
    log('数据条目:', n);

    if (!n) throw new Error('课表是空的，可能没登录或接口变了');

    // ---------------- 3. 回传 ----------------
    log('回传给 PaperCloud…');
    const payload = JSON.stringify({ raw: parsed, source: '云电脑自动抓取' });
    const up = await fetch(UPLOAD, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: payload
    });
    const upText = await up.text();
    log('回传结果: HTTP', up.status, upText.slice(0, 200));

    log('=== 完成，用时 ' + ((Date.now() - t0) / 1000).toFixed(1) + 's ===');
    process.exitCode = 0;

  } catch (e) {
    log('!! 失败:', e.message);
    process.exitCode = 1;
  } finally {
    if (cdp) cdp.close();
    try { child.kill(); } catch (e) { }
    await sleep(1500);
    try {
      if (process.platform === 'win32') {
        spawn('taskkill', ['/F', '/IM', path.basename(edge)], { stdio: 'ignore' });
      }
    } catch (e) { }
    setTimeout(() => process.exit(process.exitCode || 0), 1500);
  }
})();
