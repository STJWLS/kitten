/* 自定义地点（localStorage）+ 高德地理编码（key 复用大论文管线）
 * 依赖：assets/coord.js（CoordTrans，移植自大论文）
 * 约定：所有存储的地点坐标一律为 WGS84（与天地图底图一致）；
 *       高德接口出入参为 GCJ-02，进出前用 CoordTrans 转换。
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
      // 按距离排序，取最近几个
      pois.sort(function(a,b){ return (a.dist||1e9) - (b.dist||1e9); });
      return pois.slice(0, 8);
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

  /* WGS84 -> GCJ-02（用于把地图选点坐标转成高德接口入参） */
  function wgs2gcj(lat, lng){
    var g = CoordTrans.wgs84_to_gcj02(lng, lat);
    return {lng: g[0], lat: g[1]};
  }

  return {
    getVenues: getVenues, saveVenues: saveVenues,
    allVenues: allVenues, findVenue: findVenue, addVenue: addVenue,
    regeo: regeo, search: search, wgs2gcj: wgs2gcj
  };
})();
