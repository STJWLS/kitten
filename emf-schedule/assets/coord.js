/* CoordTrans —— 坐标系转换（JS 版）
 * 移植自大论文管线：D:/Seafile/P08-中期后深化/trial5_imagefetcher.py 中的 CoordTrans 类
 * （WGS84 / GCJ-02 / BD-09 / CGCS2000≈WGS84，算法与常量逐行对应）
 */
var CoordTrans = (function(){
  var x_pi = 3.14159265358979324 * 3000.0 / 180.0;
  var pi   = 3.1415926535897932384626;
  var a    = 6378245.0;              // 长半轴
  var ee   = 0.00669342162296594323; // 偏心率平方

  function transformlat(lng, lat){
    var ret = -100.0 + 2.0 * lng + 3.0 * lat + 0.2 * lat * lat +
              0.1 * lng * lat + 0.2 * Math.sqrt(Math.abs(lng));
    ret += (20.0 * Math.sin(6.0 * lng * pi) + 20.0 * Math.sin(2.0 * lng * pi)) * 2.0 / 3.0;
    ret += (20.0 * Math.sin(lat * pi) + 40.0 * Math.sin(lat / 3.0 * pi)) * 2.0 / 3.0;
    ret += (160.0 * Math.sin(lat / 12.0 * pi) + 320.0 * Math.sin(lat * pi / 30.0)) * 2.0 / 3.0;
    return ret;
  }
  function transformlng(lng, lat){
    var ret = 300.0 + lng + 2.0 * lat + 0.1 * lng * lng +
              0.1 * lng * lat + 0.1 * Math.sqrt(Math.abs(lng));
    ret += (20.0 * Math.sin(6.0 * lng * pi) + 20.0 * Math.sin(2.0 * lng * pi)) * 2.0 / 3.0;
    ret += (20.0 * Math.sin(lng * pi) + 40.0 * Math.sin(lng / 3.0 * pi)) * 2.0 / 3.0;
    ret += (150.0 * Math.sin(lng / 12.0 * pi) + 300.0 * Math.sin(lng / 30.0 * pi)) * 2.0 / 3.0;
    return ret;
  }
  function out_of_china(lng, lat){
    return (lng < 72.004 || lng > 137.8347) || (lat < 0.8293 || lat > 55.8271);
  }

  return {
    /* WGS84 -> GCJ-02（火星坐标） */
    wgs84_to_gcj02: function(lng, lat){
      if (out_of_china(lng, lat)) return [lng, lat];
      var dlat = transformlat(lng - 105.0, lat - 35.0);
      var dlng = transformlng(lng - 105.0, lat - 35.0);
      var radlat = lat / 180.0 * pi;
      var magic = Math.sin(radlat);
      magic = 1 - ee * magic * magic;
      var sqrtmagic = Math.sqrt(magic);
      dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrtmagic) * pi);
      dlng = (dlng * 180.0) / (a / sqrtmagic * Math.cos(radlat) * pi);
      return [lng + dlng, lat + dlat];
    },
    /* GCJ-02 -> WGS84（迭代求逆，与论文同款） */
    gcj02_to_wgs84: function(lng, lat, threshold, max_iter){
      threshold = threshold || 1e-6;
      max_iter = max_iter || 10;
      if (out_of_china(lng, lat)) return [lng, lat];
      var g = this.wgs84_to_gcj02(lng, lat);
      var w_lng = lng * 2 - g[0], w_lat = lat * 2 - g[1];
      if (Math.abs(w_lng - lng) < threshold && Math.abs(w_lat - lat) < threshold)
        return [w_lng, w_lat];
      for (var i = 0; i < max_iter; i++){
        var f = this.wgs84_to_gcj02(w_lng, w_lat);   // δ(w_k) = f(w_k) - w_k
        var d_lng = f[0] - w_lng;
        var d_lat = f[1] - w_lat;
        var n_lng = lng - d_lng;                     // w_{k+1} = g - δ(w_k)
        var n_lat = lat - d_lat;
        if (Math.abs(n_lng - w_lng) < threshold && Math.abs(n_lat - w_lat) < threshold)
          return [n_lng, n_lat];
        w_lng = n_lng; w_lat = n_lat;
      }
      return [w_lng, w_lat];
    },
    /* GCJ-02 -> BD-09 */
    gcj02_to_bd09: function(lng, lat){
      var z = Math.sqrt(lng * lng + lat * lat) + 0.00002 * Math.sin(lat * x_pi);
      var theta = Math.atan2(lat, lng) + 0.000003 * Math.cos(lng * x_pi);
      return [z * Math.cos(theta) + 0.0065, z * Math.sin(theta) + 0.006];
    },
    /* BD-09 -> GCJ-02 */
    bd09_to_gcj02: function(bd_lon, bd_lat){
      var x = bd_lon - 0.0065;
      var y = bd_lat - 0.006;
      var z = Math.sqrt(x * x + y * y) - 0.00002 * Math.sin(y * x_pi);
      var theta = Math.atan2(y, x) - 0.000003 * Math.cos(x * x_pi);
      return [z * Math.cos(theta), z * Math.sin(theta)];
    },
    out_of_china: out_of_china
  };
})();
