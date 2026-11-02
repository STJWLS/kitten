package com.stjwls.kittenpuppy;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.LinearGradient;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.PointF;
import android.graphics.RectF;
import android.graphics.Shader;
import android.view.MotionEvent;
import android.view.View;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/** Native Canvas sea for the time-bottle module. No WebView. */
final class BottleView extends View {
    interface Listener {
        void onTap(JSONObject bottle);
        void onMoved(Map<String, PointF> positions);
    }

    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final List<JSONObject> bottles = new ArrayList<>();
    private final Map<String, PointF> positions = new HashMap<>();
    private Listener listener;
    private float downX, downY;
    private String dragId = "";
    private boolean moved = false;

    BottleView(Context c) { super(c); setLayerType(View.LAYER_TYPE_SOFTWARE, null); }
    void setListener(Listener l) { listener = l; }

    void setData(JSONArray arr, JSONObject layout) {
        bottles.clear(); positions.clear();
        if (arr != null) for (int i = 0; i < arr.length(); i++) {
            JSONObject b = arr.optJSONObject(i);
            if (b != null) bottles.add(b);
        }
        int i = 0;
        for (JSONObject b : bottles) {
            String id = b.optString("id");
            PointF p = new PointF(0.16f + (i % 4) * 0.22f, 0.24f + (i / 4) * 0.21f);
            if (layout != null) {
                JSONObject o = layout.optJSONObject(id);
                if (o != null) p = new PointF((float) o.optDouble("x", p.x), (float) o.optDouble("y", p.y));
            }
            positions.put(id, p);
            i++;
        }
        invalidate();
    }

    @Override protected void onDraw(Canvas c) {
        super.onDraw(c);
        float w = getWidth(), h = getHeight();
        if (w == 0 || h == 0) return;
        paint.setShader(new LinearGradient(0, 0, 0, h, 0xffeef8f7, 0xffb9d9df, Shader.TileMode.CLAMP));
        c.drawRect(0, 0, w, h, paint);
        paint.setShader(null);

        paint.setStyle(Paint.Style.FILL);
        paint.setColor(0x33ffffff);
        Path wave = new Path();
        wave.moveTo(0, h * 0.72f);
        for (int i = 0; i <= 8; i++) {
            wave.quadTo(w * (i + 0.5f) / 8f, h * (i % 2 == 0 ? 0.68f : 0.76f), w * (i + 1) / 8f, h * 0.72f);
        }
        wave.lineTo(w, h); wave.lineTo(0, h); wave.close();
        c.drawPath(wave, paint);
        paint.setColor(0x26ffffff);
        c.drawCircle(w * 0.2f, h * 0.18f, w * 0.16f, paint);
        c.drawCircle(w * 0.78f, h * 0.12f, w * 0.1f, paint);

        for (JSONObject b : bottles) {
            PointF p = positions.get(b.optString("id"));
            if (p == null) continue;
            drawBottle(c, b, lx(p.x, w), ly(p.y, h), b.optString("id").equals(dragId) && moved);
        }
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(0x88495c63);
        paint.setTextAlign(Paint.Align.CENTER);
        paint.setTextSize(dp(11));
        c.drawText("拖动瓶子换个位置 · 点一下看看它", w / 2, h - dp(14), paint);
    }

    private float lx(float x, float w) { return dp(36) + x * (w - dp(72)); }
    private float ly(float y, float h) { return dp(54) + y * (h - dp(150)); }

    private void drawBottle(Canvas c, JSONObject b, float x, float y, boolean active) {
        int color;
        try { color = Color.parseColor(b.optString("color", "#7fa6cf")); } catch (Exception e) { color = 0xff7fa6cf; }
        boolean glow = b.optBoolean("canOpen");
        if (glow) {
            paint.setColor(0x33ffffff);
            c.drawCircle(x, y, dp(42), paint);
        }
        c.save();
        c.translate(x, y);
        c.rotate(active ? -8 : -14);
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(0x33000000);
        c.drawOval(new RectF(-dp(19), dp(25), dp(19), dp(33)), paint);
        paint.setColor(color);
        c.drawRoundRect(new RectF(-dp(20), -dp(22), dp(20), dp(25)), dp(14), dp(14), paint);
        paint.setColor(0xffd9b77d);
        c.drawRect(-dp(7), -dp(35), dp(7), -dp(21), paint);
        paint.setColor(0xffa77b4d);
        c.drawRoundRect(new RectF(-dp(9), -dp(40), dp(9), -dp(34)), dp(3), dp(3), paint);
        paint.setColor(0x66ffffff);
        c.drawRoundRect(new RectF(-dp(13), -dp(12), -dp(7), dp(18)), dp(3), dp(3), paint);
        paint.setColor(0xddffffff);
        paint.setTextAlign(Paint.Align.CENTER);
        paint.setTextSize(dp(10));
        String label = b.optBoolean("opened") ? "已开启" : (b.optBoolean("canOpen") ? "可开启" : "漂流瓶");
        c.drawText(label, 0, dp(6), paint);
        c.restore();
        paint.setTextAlign(Paint.Align.CENTER);
        paint.setTextSize(dp(10));
        paint.setColor(0xcc5b6b70);
        c.drawText(b.optString("from") + " → " + b.optString("to"), x, y + dp(48), paint);
    }

    @Override public boolean onTouchEvent(MotionEvent e) {
        float x = e.getX(), y = e.getY();
        switch (e.getActionMasked()) {
            case MotionEvent.ACTION_DOWN:
                downX = x; downY = y; moved = false;
                dragId = nearest(x, y);
                if (dragId.length() > 0) { invalidate(); return true; }
                return true;
            case MotionEvent.ACTION_MOVE:
                if (dragId.length() > 0 && (Math.abs(x - downX) > dp(4) || Math.abs(y - downY) > dp(4))) {
                    moved = true;
                    PointF p = positions.get(dragId);
                    if (p != null) {
                        p.x = clamp((x - dp(36)) / (getWidth() - dp(72)));
                        p.y = clamp((y - dp(54)) / (getHeight() - dp(150)));
                        invalidate();
                    }
                }
                return true;
            case MotionEvent.ACTION_UP:
                if (dragId.length() > 0) {
                    String id = dragId;
                    if (moved) {
                        Map<String, PointF> copy = new HashMap<>();
                        for (Map.Entry<String, PointF> en : positions.entrySet()) copy.put(en.getKey(), new PointF(en.getValue().x, en.getValue().y));
                        if (listener != null) listener.onMoved(copy);
                    } else {
                        JSONObject hit = null;
                        for (JSONObject b : bottles) if (b.optString("id").equals(id)) hit = b;
                        if (hit != null && listener != null) listener.onTap(hit);
                    }
                    dragId = ""; moved = false; invalidate();
                }
                return true;
        }
        return true;
    }

    private String nearest(float x, float y) {
        String best = ""; float bestD = dp(54);
        for (JSONObject b : bottles) {
            PointF p = positions.get(b.optString("id"));
            if (p == null) continue;
            float dx = x - lx(p.x, getWidth()), dy = y - ly(p.y, getHeight());
            float d = (float) Math.sqrt(dx * dx + dy * dy);
            if (d < bestD) { bestD = d; best = b.optString("id"); }
        }
        return best;
    }
    private static float clamp(float v) { return Math.max(0.06f, Math.min(0.94f, v)); }
    private float dp(float v) { return v * getResources().getDisplayMetrics().density; }
}
