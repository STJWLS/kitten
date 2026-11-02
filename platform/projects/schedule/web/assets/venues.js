/* 自定义地点 + 新建地点编辑器（地图页与日程页共用）
 * 依赖：assets/coord.js（CoordTrans 移植自大论文）、Leaflet（页面自行引入）
 * 约定：所有存储坐标统一 WGS84（与天地图底图一致）；高德接口出入参为 GCJ-02
 */
var VenueStore = (function(){
  var VEN_KEY = "emf_venues_v1";
  var META_KEY = "emf_store_meta";
  // 高德 key：复用大论文 trial5_imagefetcher.py 的 API_KEY_AMAP
  var AMAP_KEY = "a59f78f6ee853bbd96875cc41b7e3b43";

  function getVenues(){
    try { return JSON.parse(localStorage.getItem(VEN_KEY) || "[]"); }
    catch(e){ return []; }
  }
  function saveVenues(arr){
    localStorage.setItem(VEN_KEY, JSON.stringify(arr));
    bumpMeta();
    if (typeof DATA !== "undefined" && DATA) DATA.venues = arr;
    fetch("/api/schedule/venues", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({venues: arr})})
      .catch(function(){});
  }

  function reloadVenues(){
    return fetch("/api/schedule/venues", {cache:"no-store"})
      .then(function(r){ if (!r.ok) throw new Error("venues " + r.status); return r.json(); })
      .then(function(d){
        var arr = Array.isArray(d.venues) ? d.venues : [];
        localStorage.setItem(VEN_KEY, JSON.stringify(arr));
        if (typeof DATA !== "undefined" && DATA) DATA.venues = arr;
        bumpMeta();
        return arr;
      });
  }

  /* 本地数据版本号（毫秒时间戳）：用于本机后端同步时判定「谁新」，
     避免加载时服务端旧数据覆盖本地新修改（例如刚删除的日程复活） */
  function metaT(){
    try { return (JSON.parse(localStorage.getItem(META_KEY) || "{}")).t || 0; }
    catch(e){ return 0; }
  }
  function bumpMeta(){
    localStorage.setItem(META_KEY, JSON.stringify({t: Date.now()}));
  }

  /* 内置地点 + 自定义地点（custom 标记） */
  function allVenues(){
    var base = (typeof DATA !== "undefined" && DATA && DATA.venues) ? DATA.venues : null;
    return base || getVenues();
  }

  function findVenue(codeOrName){
    return allVenues().find(function(v){
      return v.code === codeOrName || v.name === codeOrName || v.short === codeOrName;
    }) || null;
  }

  function addVenue(v){
    var arr = allVenues().slice();
    v.code = v.code || ("v" + Date.now().toString(36));
    arr.push(v);
    saveVenues(arr);
    return v;
  }

  /* 个人日程（与页面共用同一 localStorage key） */
  var EVT_KEY = "emf_schedule_events_v1";
  function getEvents(){
    try { return JSON.parse(localStorage.getItem(EVT_KEY) || "[]"); }
    catch(e){ return []; }
  }
  function saveEvents(arr){
    localStorage.setItem(EVT_KEY, JSON.stringify(arr));
    bumpMeta();
    if (typeof LocalBackend !== "undefined") LocalBackend.push();
  }

  /* 旧版事件迁移：s0/s1 时段索引 → startMin/endMin 分钟（10 分钟粒度），并补 tag */
  function migrateEvents(){
    if (typeof DATA === "undefined" || !DATA || !DATA.slots) return;
    var changed = false;
    var evts = getEvents();
    for (var i = 0; i < evts.length; i++){
      var e = evts[i];
      if (e.startMin === undefined && e.s0 !== undefined){
        var s0 = DATA.slots[e.s0];
        var s1 = DATA.slots[(e.s1 != null) ? e.s1 : e.s0];
        var toMin = function(t){
          var a = String(t).split(":").map(Number);
          return Math.round((a[0]*60 + a[1])/10)*10;
        };
        e.startMin = toMin(s0.label.split("-")[0]);
        e.endMin = toMin(s1.label.split("-")[1]);
        delete e.s0; delete e.s1;
        changed = true;
      }
      if (!e.tag){ e.tag = "个人"; changed = true; }
      if (!e.endDate && e.date){ e.endDate = e.date; changed = true; }
    }
    if (changed) saveEvents(evts);
  }

  /* 当前没有绑定地点的日程（place 为空或未匹配任何已有地点名） */
  function unboundEvents(){
    var names = allVenues().map(function(v){ return v.name; });
    return getEvents().filter(function(e){
      if (!e.place || !String(e.place).trim()) return true;
      return names.indexOf(e.place) < 0;
    });
  }

  /* ---- 高德地理编码（GCJ-02 出入参） ---- */
  function amapGet(url){
    return fetch(url, {cache:"no-store"}).then(function(r){ return r.json(); });
  }
  /* 高德不同接口的 address 格式不一致：regeo 是数组、place/text 是字符串 */
  function fmtAddr(p){
    if (typeof p.address === "string") return p.address;
    if (p.address && p.address.length) return p.address.join("");
    return [p.pname, p.cityname, p.adname].filter(Boolean).join("");
  }

  /* 逆地理编码：坐标(GCJ-02) -> 附近 POI 列表（距离最近的几个） */
  function regeo(gcjLng, gcjLat, radius){
    var url = "https://restapi.amap.com/v3/geocode/regeo?location=" +
      gcjLng.toFixed(6) + "," + gcjLat.toFixed(6) +
      "&key=" + AMAP_KEY + "&radius=" + (radius || 500) + "&extensions=all";
    return amapGet(url).then(function(d){
      if (d.status !== "1") throw new Error("逆地理编码失败: " + d.info);
      var pois = ((d.regeocode || {}).pois || []).map(function(p){
        var ll = String(p.location || "").split(",");
        var w = CoordTrans.gcj02_to_wgs84(parseFloat(ll[0]), parseFloat(ll[1]));
        return {
          name: p.name, address: fmtAddr(p),
          lat: w[1], lng: w[0],
          dist: (typeof p.distance === "number") ? Math.round(p.distance) : null
        };
      });
      pois.sort(function(a,b){ return (a.dist||1e9) - (b.dist||1e9); });
      return { pois: pois.slice(0, 8),
               addr: (d.regeocode && d.regeocode.formatted_address) || "" };
    });
  }

  /* 地点搜索：关键词 -> POI 列表 */
  function search(q, city, count){
    var url = "https://restapi.amap.com/v3/place/text?keywords=" + encodeURIComponent(q) +
      "&city=" + encodeURIComponent(city || "上海") +
      "&key=" + AMAP_KEY + "&offset=" + (count || 8);
    return amapGet(url).then(function(d){
      if (d.status !== "1") throw new Error("搜索失败: " + d.info);
      return (d.pois || []).map(function(p){
        var ll = String(p.location || "").split(",");
        var w = CoordTrans.gcj02_to_wgs84(parseFloat(ll[0]), parseFloat(ll[1]));
        return {
          name: p.name, address: fmtAddr(p),
          lat: w[1], lng: w[0], dist: null
        };
      }).slice(0, count || 8);
    });
  }

  /* WGS84 -> GCJ-02（地图选点坐标转高德接口入参） */
  function wgs2gcj(lat, lng){
    var g = CoordTrans.wgs84_to_gcj02(lng, lat);
    return {lng: g[0], lat: g[1]};
  }

  return {
    getVenues: getVenues, saveVenues: saveVenues, reloadVenues: reloadVenues,
    allVenues: allVenues, findVenue: findVenue, addVenue: addVenue,
    getEvents: getEvents, saveEvents: saveEvents, unboundEvents: unboundEvents,
    migrateEvents: migrateEvents, metaT: metaT,
    regeo: regeo, search: search, wgs2gcj: wgs2gcj
  };
})();

/* ============ 结构化课表派生：slots + courses.schedule + specials → 周网格 ============ */
/* 数据模型（schedule.json）：
   slots[i]   = 第几节课的起止时间（start/end 分钟）
   courses[].schedule[] = {weeks:[周id], day:0-6, slot:节号, span:跨节数, venue, note}
   specials[] = 不对齐课节的安排（考试/CARE EN 等），带明确 start/end 分钟 */
function deriveSchedule(D){
  var weeks = [];
  for (var n = 1; n <= D.meta.totalWeeks; n++){
    var ws = new Date(D.meta.termStart + "T00:00:00+08:00");
    var days = [];
    for (var di = 0; di < 7; di++){
      var t = new Date(ws.getTime() + ((n-1)*7 + di)*864e5);
      var iso = t.getFullYear() + "-" + String(t.getMonth()+1).padStart(2,"0") +
                "-" + String(t.getDate()).padStart(2,"0");
      days.push({date: iso, sessions: []});
    }
    weeks.push({no: n, start: days[0].date, end: days[6].date, days: days});
  }
  var byCode = {};
  D.courses.forEach(function(c){ byCode[c.code] = c; });
  // 课程常规安排
  D.courses.forEach(function(c){
    (c.schedule || []).forEach(function(e){
      var s0 = e.slot ? D.slots[e.slot - 1] : null;
      var s1 = e.slot ? D.slots[e.slot - 1 + (e.span || 1) - 1] : null;
      var st = (typeof e.start === "number") ? e.start : (s0 ? s0.start : 0);
      var en = (typeof e.end === "number") ? e.end : (s1 ? s1.end : st);
      e.weeks.forEach(function(wk){
        weeks[wk-1].days[e.day].sessions.push({
          c: c.code, v: e.venue || "", note: e.note || "",
          start: st, end: en, tag: c.code, isExam: false
        });
      });
    });
  });
  // 特殊安排（考试 / CARE EN / 调课等）
  (D.specials || []).forEach(function(sp){
    sp.weeks.forEach(function(wk){
      weeks[wk-1].days[sp.day].sessions.push({
        c: sp.code, v: sp.venue || "", note: sp.note || "",
        start: sp.start, end: sp.end,
        title: sp.title || sp.code || "特殊安排",
        tag: sp.tag || sp.code || "安排", isExam: !!sp.isExam || (sp.note || "").indexOf("Exam") === 0
      });
    });
  });
  return weeks;
}

/* ============ 新建地点编辑器（两阶段统一弹窗） ============ */
/* 阶段一：搜索栏 + 矢量小地图 + 备选结果（单击选中高亮；双击结果或点"确认"进入阶段二）
   阶段二：顶部返回键；名称/地址/经纬度 + 可选绑定日程 + 备注 + 保存 */
var VenueEditor = (function(){
  var vmap = null, vmarker = null, sel = null, opts = null;

  function el(id){ return document.getElementById(id); }

  function ensureModal(){
    if (el("venue-modal")) return;
    var host = document.createElement("div");
    host.innerHTML =
      '<div class="modal-back" id="venue-modal" style="display:none">' +
      '  <div class="modal modal-lg">' +
      '    <h3>新建地点</h3>' +
      '    <div id="vstage1">' +
      '      <div class="place-row">' +
      '        <input id="vq" placeholder="搜索地点，例如：复旦图书馆 / 五角场万达">' +
      '        <button class="btn-primary" id="vq-btn">搜索</button>' +
      '      </div>' +
      '      <div class="vmapbox"><div id="vmap"></div>' +
      '        <div class="vmap-tip">点击地图可直接选点（自动逆地理编码）</div></div>' +
      '      <div id="vq-results" class="vqres"></div>' +
      '      <div class="modal-btns">' +
      '        <span class="vconfirm-hint" id="vconfirm-hint">单击结果或点击地图选点，再点确认；双击结果直接确认</span>' +
      '        <button class="btn-ghost" id="vn-cancel">取消</button>' +
      '        <button class="btn-primary" id="vn-confirm" disabled>确认</button>' +
      '      </div>' +
      '    </div>' +
      '    <div id="vstage2" style="display:none">' +
      '      <button class="btn-back" id="vn-back">← 返回选点</button>' +
      '      <label>名称 <input id="vn-name" placeholder="地点名称"></label>' +
      '      <label>地址 <input id="vn-addr" placeholder="地址（自动填充，可修改）"></label>' +
      '      <div class="row2">' +
      '        <label>纬度 <input id="vn-lat" readonly></label>' +
      '        <label>经度 <input id="vn-lng" readonly></label>' +
      '      </div>' +
      '      <label class="vbind-lab">可选绑定日程（当前没有绑定地点的，可不选）</label>' +
      '      <div id="vbind" class="vbind"></div>' +
      '      <label>备注（可选） <input id="vn-note" placeholder="例如：常去自习"></label>' +
      '      <div class="modal-btns">' +
      '        <button class="btn-ghost" id="vn-cancel2">取消</button>' +
      '        <button class="btn-primary" id="vn-save">保存地点</button>' +
      '      </div>' +
      '    </div>' +
      '  </div>' +
      '</div>';
    document.body.appendChild(host);
    el("vq-btn").addEventListener("click", runSearch);
    el("vq").addEventListener("keydown", function(e){ if (e.key==="Enter") runSearch(); });
    el("vn-cancel").addEventListener("click", close);
    el("vn-cancel2").addEventListener("click", close);
    el("vn-confirm").addEventListener("click", confirm);
    el("vn-back").addEventListener("click", function(){ showStage(1); });
    el("vn-save").addEventListener("click", save);
    el("venue-modal").addEventListener("click", function(e){
      if (e.target === el("venue-modal")) close();
    });
  }

  function ensureMap(){
    if (vmap){ vmap.invalidateSize(); return; }
    vmap = L.map("vmap", {center:[31.2995, 121.5020], zoom: 15,
                          zoomControl: false, attributionControl: false});
    var key = (typeof DATA !== "undefined" && DATA.meta && DATA.meta.tdtKey) || "";
    if (key){
      L.tileLayer("https://t{s}.tianditu.gov.cn/DataServer?T=vec_w&x={x}&y={y}&l={z}&tk=" + key,
        {subdomains:["0","1","2","3","4","5","6","7"], maxZoom:18}).addTo(vmap);
      L.tileLayer("https://t{s}.tianditu.gov.cn/DataServer?T=cva_w&x={x}&y={y}&l={z}&tk=" + key,
        {subdomains:["0","1","2","3","4","5","6","7"], maxZoom:18}).addTo(vmap);
    }
    vmap.on("click", onMapClick);
  }

  /* 更新结果区内容，并在地图尺寸变化后触发重绘 */
  function setResults(html, bind){
    var box = el("vq-results");
    box.innerHTML = html;
    if (bind) bind(box);
    setTimeout(function(){ if (vmap) vmap.invalidateSize(); }, 60);
  }

  function showStage(n){
    el("vstage1").style.display = n === 1 ? "" : "none";
    el("vstage2").style.display = n === 2 ? "" : "none";
    if (n === 1 && vmap) setTimeout(function(){ vmap.invalidateSize(); }, 50);
  }

  function setMarker(lat, lng){
    if (vmarker) vmap.removeLayer(vmarker);
    // 主题风格 divIcon（不依赖 Leaflet 默认图标资源）
    vmarker = L.marker([lat, lng], {icon: L.divIcon({
      className: "tdt-pin pick",
      html: '<div class="pin"><em>📍</em></div>',
      iconSize: [30, 44], iconAnchor: [15, 42]
    })}).addTo(vmap);
  }

  /* 选中一个候选（结果单击 / 地图选点），确认按钮亮起 */
  function select(o){
    sel = o;
    el("vn-confirm").disabled = false;
    el("vconfirm-hint").textContent = "已选中：" + (o.name || "地图选点") + " · 点确认进入下一步（或双击结果）";
    el("vq-results").querySelectorAll(".vqitem").forEach(function(it){
      it.classList.toggle("selected",
        it.dataset.lat == String(o.lat) && it.dataset.lng == String(o.lng));
    });
  }

  function onMapClick(e){
    var lat = e.latlng.lat, lng = e.latlng.lng;
    var g = VenueStore.wgs2gcj(lat, lng);
    setMarker(lat, lng);
    select({name:"", address:"", lat:lat, lng:lng});   // 先确定坐标
    setResults('<div class="mylist-empty">正在逆地理编码…</div>');
    VenueStore.regeo(g.lng, g.lat).then(function(r){
      setResults(r.pois.length
        ? '<div class="vqtitle">距离最近的几个地点（单击选中 / 双击确认）：</div>' + renderItems(r.pois)
        : '<div class="mylist-empty">附近没有找到地点，可点确认后手动填写名称</div>', bindItems);
      if (r.addr && !sel.address) sel.address = r.addr;
    }).catch(function(err){
      setResults('<div class="mylist-empty">逆地理编码失败：' + (err.message||err) + '（可点确认后手动填写名称）</div>');
    });
  }

  function runSearch(){
    var q = el("vq").value.trim();
    if (!q) return;
    setResults('<div class="mylist-empty">搜索中…</div>');
    VenueStore.search(q, "上海").then(function(pois){
      setResults(pois.length ? renderItems(pois) : '<div class="mylist-empty">没有找到相关地点</div>', bindItems);
    }).catch(function(err){
      setResults('<div class="mylist-empty">搜索失败：' + (err.message||err) + '</div>');
    });
  }

  /* 备选结果：名称 + 经纬度 + 具体地址 */
  function renderItems(pois){
    return pois.map(function(p){
      return '<div class="vqitem" data-name="' + esc(p.name) + '" data-addr="' + esc(p.address) + '" data-lat="' + p.lat + '" data-lng="' + p.lng + '">' +
        '<div class="n">' + esc(p.name) + (p.dist!=null ? ' <i>' + p.dist + 'm</i>' : '') + '</div>' +
        '<div class="coords">' + p.lat.toFixed(6) + ', ' + p.lng.toFixed(6) + '</div>' +
        '<div class="a">' + esc(p.address || "") + '</div></div>';
    }).join("");
  }
  function esc(s){ return String(s == null ? "" : s).replace(/"/g, "&quot;"); }
  function bindItems(box){
    box.querySelectorAll(".vqitem").forEach(function(it){
      it.addEventListener("click", function(){
        var o = {name: it.dataset.name || "", address: it.dataset.addr || "",
                 lat: parseFloat(it.dataset.lat), lng: parseFloat(it.dataset.lng)};
        setMarker(o.lat, o.lng);
        vmap.setView([o.lat, o.lng], 15);
        select(o);
      });
      it.addEventListener("dblclick", function(){
        var o = {name: it.dataset.name || "", address: it.dataset.addr || "",
                 lat: parseFloat(it.dataset.lat), lng: parseFloat(it.dataset.lng)};
        setMarker(o.lat, o.lng);
        select(o);
        confirm();
      });
    });
  }

  /* 确认 → 二阶段：填表 + 未绑定日程勾选 */
  function confirm(){
    if (!sel){ alert("请先单击搜索结果或点击地图选点"); return; }
    el("vn-name").value = sel.name || "";
    el("vn-addr").value = sel.address || "";
    el("vn-lat").value = sel.lat.toFixed(6);
    el("vn-lng").value = sel.lng.toFixed(6);
    renderBind();
    showStage(2);
  }

  function renderBind(){
    var unbound = VenueStore.unboundEvents();
    var box = el("vbind");
    if (!unbound.length){
      box.innerHTML = '<div class="mylist-empty" style="padding:8px 0">没有未绑定地点的日程</div>';
      return;
    }
    box.innerHTML = unbound.map(function(e){
      return '<label class="vbind-item"><input type="checkbox" value="' + e.id + '"> ' +
             e.date.slice(5) + ' · 📌 ' + esc(e.title) + '</label>';
    }).join("");
  }

  function save(){
    var name = el("vn-name").value.trim();
    var lat = parseFloat(el("vn-lat").value);
    var lng = parseFloat(el("vn-lng").value);
    if (!name){ alert("请填写地点名称"); return; }
    if (!sel || isNaN(lat) || isNaN(lng)){ alert("位置坐标缺失，请返回选点"); return; }
    var v = VenueStore.addVenue({
      name: name, short: name,
      address: el("vn-addr").value.trim(),
      note: el("vn-note").value.trim(),
      lat: lat, lng: lng, custom: true
    });
    var evts = VenueStore.getEvents();
    var changed = false;
    el("vbind").querySelectorAll("input:checked").forEach(function(cb){
      var e = evts.find(function(x){ return x.id === cb.value; });
      if (e){ e.place = v.name; changed = true; }
    });
    if (changed) VenueStore.saveEvents(evts);
    close();
    if (opts && opts.onSaved) opts.onSaved(v);
  }

  function close(){
    el("venue-modal").style.display = "none";
    if (vmarker){ vmap.removeLayer(vmarker); vmarker = null; }
    sel = null;
    el("vn-confirm").disabled = true;
    showStage(1);
  }

  /* 打开：opts = {onSaved: function(venue)} */
  function open(o){
    opts = o || {};
    ensureModal();
    ensureMap();
    el("vq").value = "";
    el("vn-name").value = "";
    el("vn-addr").value = "";
    el("vn-note").value = "";
    el("vn-lat").value = "";
    el("vn-lng").value = "";
    setResults('<div class="mylist-empty">搜索地点，或直接点击上方地图选点</div>');
    el("vn-confirm").disabled = true;
    el("vconfirm-hint").textContent = "单击结果或点击地图选点，再点确认；双击结果直接确认";
    sel = null;
    showStage(1);
    el("venue-modal").style.display = "flex";
    setTimeout(function(){ vmap.invalidateSize(); }, 50);
  }

  return { open: open, close: close };
})();

/* ============ 本机存储后端（127.0.0.1:8767，数据落盘到这台机器） ============ */
var LocalBackend = (function(){
  var LOCAL = "http://127.0.0.1:8767";
  var baseRel = true;   // 优先相对路径（看板由本机服务 serve 时同源直连，隧道 iframe 内同样生效）
  var online = false;

  /* 页面打开瞬间的数据版本：必须在任何页面脚本改动本地数据之前捕获。
     许愿池/看板在首屏渲染时会补发每日币并 saveCoins，bump 出一个新的 t；
     若用这个新 t 与服务端比较，会把「刚补发的币」误判成本地更新，
     从而把旧的（甚至空的）日程/愿望/余额推上服务端，覆盖另一端的新数据。
     因此初始化仲裁只认页面加载时的 t，并且所有 push 都排在初始化完成之后。 */
  var startT = VenueStore.metaT ? VenueStore.metaT() : 0;
  var readyResolve, readyDone = false, pendingPush = false;
  var ready = new Promise(function(res){ readyResolve = res; });

  function apiUrl(p){
    return (baseRel ? "" : LOCAL) + p;
  }
  function readWishes(){
    try { return JSON.parse(localStorage.getItem("emf_wishes_v1") || "[]"); } catch(e){ return []; }
  }
  function readCoins(){
    try { return JSON.parse(localStorage.getItem("emf_coins_v1") || "{}"); } catch(e){ return {}; }
  }

  function wStamp(w){
    var s = (w && w.createdAt) || "";
    var hist = (w && w.history) || [];
    for (var i = 0; i < hist.length; i++){
      var at = hist[i] && hist[i].at;
      if (at && at > s) s = at;
    }
    return s;
  }
  /* 同一 id、同一时间戳时，字段更完整的一份优先（避免恢复出来的空字段覆盖真实详情） */
  function wRich(w){
    if (!w) return 0;
    var r = 0;
    if (w.wantDate) r++;
    if (w.wantTime) r++;
    if (w.venue) r++;
    if (w.detail) r++;
    r += (w.history ? w.history.length : 0);
    return r;
  }
  /* 愿望只增不删：按 id 求并集，同一 id 取流程日志更新的那一份。
     这样即使某一端是空数组/旧快照，也不会把另一端的愿望冲掉。 */
  function mergeWishes(a, b){
    var by = {}, order = [];
    var all = (Array.isArray(a) ? a : []).concat(Array.isArray(b) ? b : []);
    for (var i = 0; i < all.length; i++){
      var w = all[i];
      if (!w || !w.id) continue;
      if (!by[w.id]){ by[w.id] = w; order.push(w.id); }
      else if (wStamp(w) > wStamp(by[w.id]) ||
               (wStamp(w) === wStamp(by[w.id]) && wRich(w) > wRich(by[w.id]))) by[w.id] = w;
    }
    return order.map(function(id){ return by[id]; });
  }
  function needsWishPush(merged, server){
    var sm = {};
    (Array.isArray(server) ? server : []).forEach(function(w){ if (w && w.id) sm[w.id] = wStamp(w); });
    return (Array.isArray(merged) ? merged : []).some(function(w){
      return w && w.id && (!sm[w.id] || wStamp(w) > sm[w.id]);
    });
  }
  /* 「刚开户」的余额：没有任何投入/报酬/转账/罚款等经济行为。
     全新浏览器会从 START_DATE 空算出一份只含 grant/interest 的余额；
     它绝不能覆盖已有经济行为的服务端余额。 */
  function looksFreshCoins(c){
    if (!c || typeof c !== "object" || !Object.keys(c).length) return true;
    var keys = ["kittenSpent", "kittenSent", "kittenGift", "kittenWon", "puppyEarned"];
    for (var i = 0; i < keys.length; i++){
      if (Number(c[keys[i]] || 0) !== 0) return false;
    }
    var log = Array.isArray(c.coinLog) ? c.coinLog : [];
    for (var j = 0; j < log.length; j++){
      var k = log[j] && log[j].kind;
      if (k && k !== "grant" && k !== "interest") return false;
    }
    return true;
  }

  function probe(){
    return fetch(apiUrl("/api/health"), {cache:"no-store"})
      .then(function(r){ if (r.ok){ online = true; return true; } throw new Error("rel fail"); })
      .catch(function(){
        // 回退：绝对 127.0.0.1（页面不在本机服务上时，如历史 github.io 直连）
        return fetch(LOCAL + "/api/health", {cache:"no-store"})
          .then(function(r){
            if (r.ok){ baseRel = false; online = true; return true; }
            return false;
          })
          .catch(function(){ online = false; return false; });
      });
  }

  function push(){
    // 初始化完成前只记一个待推送标记；否则首屏补币会把空/旧数据推上服务端。
    if (!readyDone){ pendingPush = true; return; }
    var payload = {
      events: VenueStore.getEvents(),
      wishes: readWishes(),
      coins: readCoins(),
      t: VenueStore.metaT ? VenueStore.metaT() : 0
    };
    fetch(apiUrl("/api/save"), {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload)
    }).catch(function(){});
  }

  function setLocal(key, val){
    localStorage.setItem(key, JSON.stringify(val));
  }

  /* 一次性仲裁：返回是否还需要把本地数据推回服务端 */
  function adopt(d){
    var serverT = d.t || 0, localT = startT;
    var serverE = Array.isArray(d.events) ? d.events : [];
    var serverV = Array.isArray(d.venues) ? d.venues : [];
    var serverW = Array.isArray(d.wishes) ? d.wishes : [];
    var serverC = (d.coins && typeof d.coins === "object") ? d.coins : {};
    var localE = VenueStore.getEvents(), localV = VenueStore.getVenues();
    var localW = readWishes(), localC = readCoins();
    var needPush = false;

    // 愿望：任何情况下都并集（只增不删）
    var mergedW = mergeWishes(localW, serverW);
    if (needsWishPush(mergedW, serverW)) needPush = true;

    // 日程/地点：空列表不覆盖非空列表（防止新浏览器登录后把看板清空）
    var nextE, nextV;
    if (serverT > localT){
      nextE = (!serverE.length && localE.length) ? localE : serverE;
      nextV = (!serverV.length && localV.length) ? localV : serverV;
      if (nextE === localE && localE.length) needPush = true;
      if (nextV === localV && localV.length) needPush = true;
    } else if (localT > serverT){
      nextE = localE; nextV = localV; needPush = true;
    } else {
      nextE = localE.length ? localE : serverE;
      nextV = localV.length ? localV : serverV;
      if (localE.length > 0 && serverE.length === 0) needPush = true;
      if (localV.length > 0 && serverV.length === 0) needPush = true;
    }

    // 余额：全新开户的余额不覆盖有经济行为的余额
    var nextC;
    if (serverT > localT){
      if (looksFreshCoins(serverC) && !looksFreshCoins(localC)){ nextC = localC; needPush = true; }
      else nextC = serverC;
    } else if (localT > serverT){
      nextC = localC; needPush = true;
    } else {
      var sHas = serverC && Object.keys(serverC).length;
      var lHas = localC && Object.keys(localC).length;
      if (lHas && !sHas){ nextC = localC; needPush = true; }
      else if (looksFreshCoins(localC) && !looksFreshCoins(serverC)) nextC = serverC;
      else if (!looksFreshCoins(localC) && looksFreshCoins(serverC)){ nextC = localC; needPush = true; }
      else nextC = sHas ? serverC : localC;
    }

    setLocal("emf_schedule_events_v1", nextE);
    setLocal("emf_venues_v1", nextV);
    setLocal("emf_wishes_v1", mergedW);
    setLocal("emf_coins_v1", nextC);
    // 需要推送时把版本号推进到当前时刻；否则采纳服务端版本号
    localStorage.setItem("emf_store_meta", JSON.stringify({
      t: needPush ? Date.now() : Math.max(serverT, localT)
    }));
    return needPush;
  }

  function init(){
    return probe().then(function(ok){
      online = ok;
      if (!ok) return false;
      return fetch(apiUrl("/api/state"), {cache:"no-store"})
        .then(function(r){ return r.json(); })
        .then(function(d){ return adopt(d); })
        .catch(function(){ return false; });
    }).then(function(needPush){
      if (needPush) pendingPush = true;
      readyDone = true; readyResolve();
      if (pendingPush){ pendingPush = false; push(); }
    }).catch(function(){
      readyDone = true; readyResolve();
      if (pendingPush){ pendingPush = false; push(); }
    });
  }
  return {
    init: init, push: push, online: function(){ return online; },
    ready: ready, mergeWishes: mergeWishes, needsWishPush: needsWishPush
  };
})();
LocalBackend.init();

/* ============ 跨模块同步助手（许愿池等新数据域） ============ */
window.AppSync = {
  bump: function(){
    localStorage.setItem("emf_store_meta", JSON.stringify({t: Date.now()}));
  },
  push: function(){
    if (typeof LocalBackend !== "undefined") LocalBackend.push();
  },
  saveAll: function(){
    this.bump();
    this.push();
  },
  mergeWishes: function(a, b){
    return (typeof LocalBackend !== "undefined") ? LocalBackend.mergeWishes(a, b) : (b || []);
  },
  needsWishPush: function(merged, server){
    return (typeof LocalBackend !== "undefined") ? LocalBackend.needsWishPush(merged, server) : false;
  }
};

/* ============ 地点自定义下拉（与新建地点的搜索结果同格式：名称+经纬度+地址） ============ */
var PlacePicker = (function(){
  var attached = null, drop = null;

  function esc(s){ return String(s == null ? "" : s).replace(/"/g, "&quot;"); }

  function ensureDrop(){
    if (drop) return;
    drop = document.createElement("div");
    drop.className = "placedrop";
    drop.style.display = "none";
    document.body.appendChild(drop);
    document.addEventListener("click", function(e){
      if (drop.style.display !== "none" && !drop.contains(e.target) && e.target !== attached) hide();
    });
  }
  function render(q){
    var vs = VenueStore.allVenues();
    var list = q ? vs.filter(function(v){
      return (v.name||"").toLowerCase().indexOf(q.toLowerCase()) >= 0 ||
             (v.address||"").toLowerCase().indexOf(q.toLowerCase()) >= 0;
    }) : vs;
    drop.innerHTML = list.length ? list.map(function(v){
      return '<div class="vqitem pp-item" data-code="' + esc(v.code) + '" data-name="' + esc(v.name) + '">' +
        '<div class="n">' + esc(v.name) + (v.custom ? ' <i>自定义</i>' : '') + '</div>' +
        (v.lat !== undefined ? '<div class="coords">' + v.lat.toFixed(6) + ', ' + v.lng.toFixed(6) + '</div>' : '') +
        '<div class="a">' + esc(v.address || "") + '</div></div>';
    }).join("") : '<div class="mylist-empty" style="padding:8px">没有匹配的地点（可直接输入自由文本，或点「➕ 新建」）</div>';
    drop.querySelectorAll(".pp-item").forEach(function(it){
      it.addEventListener("click", function(){
        attached.value = it.dataset.name;
        attached.dataset.placeCode = it.dataset.code;
        hide();
      });
    });
  }
  function show(){
    if (!attached) return;
    var r = attached.getBoundingClientRect();
    drop.style.left = r.left + "px";
    drop.style.top = (r.bottom + 4) + "px";
    drop.style.width = Math.max(r.width, 320) + "px";
    drop.style.display = "";
    render(attached.value);
  }
  function hide(){ if (drop) drop.style.display = "none"; }

  function attach(input){
    if (input.dataset.pp) return;
    input.dataset.pp = "1";
    attached = input;
    ensureDrop();
    input.addEventListener("click", function(){
      if (drop.style.display === "none") show(); else hide();
    });
    input.addEventListener("input", function(){
      if (drop.style.display !== "none") render(input.value);
    });
    input.addEventListener("keydown", function(e){ if (e.key === "Escape") hide(); });
    input.addEventListener("blur", function(){
      setTimeout(hide, 150);   // 让点击下拉项先触发
    });
  }
  return { attach: attach, hide: hide };
})();
