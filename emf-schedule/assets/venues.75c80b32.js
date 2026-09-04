/* 自定义地点 + 新建地点编辑器（地图页与日程页共用）
 * 依赖：assets/coord.js（CoordTrans 移植自大论文）、Leaflet（页面自行引入）
 * 约定：所有存储坐标统一 WGS84（与天地图底图一致）；高德接口出入参为 GCJ-02
 */
var VenueStore = (function(){
  var VEN_KEY = "emf_venues_v1";
  // 高德 key：复用大论文 trial5_imagefetcher.py 的 API_KEY_AMAP
  var AMAP_KEY = "a59f78f6ee853bbd96875cc41b7e3b43";

  function getVenues(){
    try { return JSON.parse(localStorage.getItem(VEN_KEY) || "[]"); }
    catch(e){ return []; }
  }
  function saveVenues(arr){
    localStorage.setItem(VEN_KEY, JSON.stringify(arr));
    if (typeof LocalBackend !== "undefined") LocalBackend.push();
  }

  /* 内置地点 + 自定义地点（custom 标记） */
  function allVenues(){
    var base = (typeof DATA !== "undefined" && DATA && DATA.venues) ? DATA.venues : [];
    return base.concat(getVenues().map(function(v){
      var c = Object.assign({}, v);
      c.custom = true;
      return c;
    }));
  }

  function findVenue(codeOrName){
    return allVenues().find(function(v){
      return v.code === codeOrName || v.name === codeOrName || v.short === codeOrName;
    }) || null;
  }

  function addVenue(v){
    var arr = getVenues();
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
    getVenues: getVenues, saveVenues: saveVenues,
    allVenues: allVenues, findVenue: findVenue, addVenue: addVenue,
    getEvents: getEvents, saveEvents: saveEvents, unboundEvents: unboundEvents,
    migrateEvents: migrateEvents,
    regeo: regeo, search: search, wgs2gcj: wgs2gcj
  };
})();

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
  var BASE = "http://127.0.0.1:8767";
  var online = false;
  var timer = null;

  function probe(){
    return fetch(BASE + "/api/health", {cache:"no-store"})
      .then(function(r){ return r.ok; }).catch(function(){ return false; });
  }
  function push(){
    if (!online) return;
    if (timer) clearTimeout(timer);
    timer = setTimeout(function(){
      var payload = {
        events: VenueStore.getEvents(),
        venues: VenueStore.getVenues()
      };
      fetch(BASE + "/api/save", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload)
      }).catch(function(){});
    }, 400);
  }
  function init(){
    return probe().then(function(ok){
      online = ok;
      if (!ok) return;
      return fetch(BASE + "/api/state", {cache:"no-store"})
        .then(function(r){ return r.json(); })
        .then(function(d){
          var localE = VenueStore.getEvents(), localV = VenueStore.getVenues();
          var serverHas = (d.events && d.events.length) || (d.venues && d.venues.length);
          var localHas = localE.length || localV.length;
          if (!serverHas && localHas){
            push();   // 本机首次使用 → 迁移网页端已有数据
          } else if (serverHas){
            // 本机数据为准 → 覆盖网页端 localStorage
            localStorage.setItem("emf_schedule_events_v1", JSON.stringify(d.events || []));
            localStorage.setItem("emf_venues_v1", JSON.stringify(d.venues || []));
          }
        }).catch(function(){});
    });
  }
  return { init: init, push: push, online: function(){ return online; } };
})();
LocalBackend.init();

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
