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
  function saveVenues(arr){ localStorage.setItem(VEN_KEY, JSON.stringify(arr)); }

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
  function saveEvents(arr){ localStorage.setItem(EVT_KEY, JSON.stringify(arr)); }

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
    regeo: regeo, search: search, wgs2gcj: wgs2gcj
  };
})();

/* ============ 新建地点编辑器（统一弹窗：搜索栏 → 矢量小地图 → 备选结果 → 日程绑定/备注） ============ */
var VenueEditor = (function(){
  var vmap = null, vmarker = null, sel = null, opts = null;
  var DAY_CN = ["周一","周二","周三","周四","周五","周六","周日"];

  function el(id){ return document.getElementById(id); }

  /* 弹窗 DOM（首次使用时注入） */
  function ensureModal(){
    if (el("venue-modal")) return;
    var host = document.createElement("div");
    host.innerHTML =
      '<div class="modal-back" id="venue-modal" style="display:none">' +
      '  <div class="modal modal-lg">' +
      '    <h3>新建地点</h3>' +
      '    <div class="place-row">' +
      '      <input id="vq" placeholder="搜索地点，例如：复旦图书馆 / 五角场万达">' +
      '      <button class="btn-primary" id="vq-btn">搜索</button>' +
      '    </div>' +
      '    <div class="vmapbox"><div id="vmap"></div>' +
      '      <div class="vmap-tip">点击地图可直接选点（自动逆地理编码）</div></div>' +
      '    <div id="vq-results" class="vqres"></div>' +
      '    <div id="vpanel" style="display:none">' +
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
      '        <button class="btn-danger" id="vn-cancel">取消</button>' +
      '        <span style="flex:1"></span>' +
      '        <button class="btn-primary" id="vn-save">保存地点</button>' +
      '      </div>' +
      '    </div>' +
      '  </div>' +
      '</div>';
    document.body.appendChild(host);
    el("vq-btn").addEventListener("click", runSearch);
    el("vq").addEventListener("keydown", function(e){ if (e.key==="Enter") runSearch(); });
    el("vn-cancel").addEventListener("click", close);
    el("vn-save").addEventListener("click", save);
    el("venue-modal").addEventListener("click", function(e){
      if (e.target === el("venue-modal")) close();
    });
  }

  /* 矢量小地图（天地图浏览器端 key，直连；失败静默——仍可用搜索模式） */
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

  function onMapClick(e){
    var lat = e.latlng.lat, lng = e.latlng.lng;
    var g = VenueStore.wgs2gcj(lat, lng);
    if (vmarker) vmap.removeLayer(vmarker);
    vmarker = L.marker([lat, lng]).addTo(vmap);
    setSel({name:"", address:"", lat:lat, lng:lng});   // 先确定坐标
    var box = el("vq-results");
    box.innerHTML = '<div class="mylist-empty">正在逆地理编码…</div>';
    VenueStore.regeo(g.lng, g.lat).then(function(r){
      if (r.addr && !el("vn-addr").value) el("vn-addr").value = r.addr;
      box.innerHTML = r.pois.length
        ? '<div class="vqtitle">距离最近的几个地点（点击选用）：</div>' + renderItems(r.pois)
        : '<div class="mylist-empty">附近没有找到地点，可手动填写名称保存</div>';
      bindItems(box);
    }).catch(function(err){
      box.innerHTML = '<div class="mylist-empty">逆地理编码失败：' + (err.message||err) + '（可手动填写名称保存）</div>';
    });
  }

  function runSearch(){
    var q = el("vq").value.trim();
    if (!q) return;
    var box = el("vq-results");
    box.innerHTML = '<div class="mylist-empty">搜索中…</div>';
    VenueStore.search(q, "上海").then(function(pois){
      box.innerHTML = pois.length ? renderItems(pois) : '<div class="mylist-empty">没有找到相关地点</div>';
      bindItems(box);
    }).catch(function(err){
      box.innerHTML = '<div class="mylist-empty">搜索失败：' + (err.message||err) + '</div>';
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
        if (vmarker){
          vmap.removeLayer(vmarker); vmarker = null;
        }
        setSel({
          name: it.dataset.name || "",
          address: it.dataset.addr || "",
          lat: parseFloat(it.dataset.lat), lng: parseFloat(it.dataset.lng)
        });
        vmap.setView([it.dataset.lat, it.dataset.lng], 15);
      });
    });
  }

  /* 选定地点：填充表单 + 显示未绑定日程勾选 */
  function setSel(o){
    sel = o;
    el("vn-name").value = o.name || "";
    el("vn-addr").value = o.address || "";
    el("vn-lat").value = o.lat.toFixed(6);
    el("vn-lng").value = o.lng.toFixed(6);
    el("vpanel").style.display = "";
    renderBind();
  }

  function renderBind(){
    var unbound = VenueStore.unboundEvents();
    var box = el("vbind");
    if (!unbound.length){
      box.innerHTML = '<div class="mylist-empty" style="padding:8px 0">没有未绑定地点的日程</div>';
      return;
    }
    box.innerHTML = unbound.map(function(e){
      var t = e.date.slice(5) + " · 📌 " + esc(e.title);
      return '<label class="vbind-item"><input type="checkbox" value="' + e.id + '"> ' + t + '</label>';
    }).join("");
  }

  function save(){
    var name = el("vn-name").value.trim();
    var lat = parseFloat(el("vn-lat").value);
    var lng = parseFloat(el("vn-lng").value);
    if (!name){ alert("请填写地点名称"); return; }
    if (!sel || isNaN(lat) || isNaN(lng)){ alert("请先通过搜索或地图选点确定位置坐标"); return; }
    var v = VenueStore.addVenue({
      name: name, short: name,
      address: el("vn-addr").value.trim(),
      note: el("vn-note").value.trim(),
      lat: lat, lng: lng, custom: true
    });
    // 绑定勾选的未绑定日程
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
    el("vq-results").innerHTML = '<div class="mylist-empty">搜索地点，或直接点击上方地图选点</div>';
    el("vpanel").style.display = "none";
    sel = null;
    el("venue-modal").style.display = "flex";
    setTimeout(function(){ vmap.invalidateSize(); }, 50);
  }

  return { open: open, close: close };
})();
