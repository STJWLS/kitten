package com.stjwls.kittenpuppy;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/** Minimal kp/1 HTTP client. Native app uses bearer tokens, not WebView cookies. */
final class Api {
    String base = "http://10.0.2.2:8772";
    String token = "";

    static final class HttpError extends Exception {
        final int status;
        HttpError(int status, String message) { super(message); this.status = status; }
    }

    static final class Unauthorized extends Exception {
        Unauthorized(String message) { super(message); }
    }

    private String url(String path) {
        String b = base == null ? "" : base.trim();
        while (b.endsWith("/")) b = b.substring(0, b.length() - 1);
        if (!path.startsWith("/")) path = "/" + path;
        return b + path;
    }

    JSONObject get(String path) throws Exception { return request("GET", path, null); }

    JSONObject post(String path, JSONObject body) throws Exception { return request("POST", path, body); }

    private JSONObject request(String method, String path, JSONObject body) throws Exception {
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL(url(path)).openConnection();
            c.setRequestMethod(method);
            c.setConnectTimeout(12000);
            c.setReadTimeout(25000);
            c.setRequestProperty("Accept", "application/json");
            if (token != null && token.length() > 0) c.setRequestProperty("Authorization", "Bearer " + token);
            if (body != null) {
                byte[] payload = body.toString().getBytes(StandardCharsets.UTF_8);
                c.setDoOutput(true);
                c.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                c.setFixedLengthStreamingMode(payload.length);
                OutputStream out = c.getOutputStream();
                out.write(payload);
                out.close();
            }
            int status = c.getResponseCode();
            InputStream in = status >= 200 && status < 300 ? c.getInputStream() : c.getErrorStream();
            String text = read(in);
            JSONObject json;
            try { json = new JSONObject(text); }
            catch (Exception e) { json = new JSONObject(); }
            if (status == 401) throw new Unauthorized("登录已过期，请重新登录");
            if (status < 200 || status >= 300) {
                String msg = json.optJSONObject("error") != null
                        ? json.optJSONObject("error").optString("message", "HTTP " + status)
                        : "HTTP " + status;
                throw new HttpError(status, msg);
            }
            if (!json.optBoolean("ok", false)) {
                String msg = json.optJSONObject("error") != null
                        ? json.optJSONObject("error").optString("message", "请求失败")
                        : "请求失败";
                throw new HttpError(status, msg);
            }
            return json;
        } finally {
            if (c != null) c.disconnect();
        }
    }

    private static String read(InputStream in) throws Exception {
        if (in == null) return "";
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        int n;
        while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
        in.close();
        return new String(out.toByteArray(), StandardCharsets.UTF_8);
    }
}
