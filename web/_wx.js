
/* KT-WEATHER: 课表页注入天气卡片 */
(function(){
  var ICON = {
    "晴":"☀️","少云":"🌤","晴间多云":"⛅","多云":"⛅","阴":"☁️",
    "阵雨":"🌦","小雨":"🌧","中雨":"🌧","大雨":"🌧","暴雨":"⛈",
    "雷阵雨":"⛈","小雪":"🌨","中雪":"🌨","大雪":"❄️","雾":"🌫","霾":"🌫","浮尘":"🌫","沙尘":"🌫"
  };
  function icon(w){
    if (!w) return "☁️";
    for (var k in ICON) { if (w.indexOf(k) >= 0) return ICON[k]; }
    return "☁️";
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

  function boot(){
    mount();
    load();
    // 课表是异步渲染的，等它出来再挂
    var tries = 0;
    var t = setInterval(function(){
      if (mount()) { clearInterval(t); load(); }
      if (++tries > 40) clearInterval(t);
    }, 250);
  }
  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
