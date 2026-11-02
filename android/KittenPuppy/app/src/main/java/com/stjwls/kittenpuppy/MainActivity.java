package com.stjwls.kittenpuppy;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.DatePickerDialog;
import android.content.Context;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.view.WindowManager;
import android.view.inputmethod.InputMethodManager;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Calendar;
import java.util.Collections;
import java.util.Comparator;
import java.util.Date;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** KittenPuppy4Ever native Android client — phase 1 (native shell, no WebView). */
public class MainActivity extends Activity {
    private static final String PREFS = "kp_native";
    private static final String DEFAULT_BASE = "https://02f5c6734009.tail4ba04e.ts.net";
    private static final int RED = 0xffd92b45;

    private final Api api = new Api();
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final ExecutorService pool = Executors.newFixedThreadPool(4);
    private SharedPreferences prefs;

    private int bg, card, ink, muted, line, accent, soft, deep;
    private JSONObject session, theme, tree;
    private JSONObject currentProject;
    private String screen = "login";
    private String messagesPeer = "";
    private int messagesTab = 0;
    private TextView homeMailBadge;
    private BottleView bottleView;
    private int bottleRev = 0;
    private String loginUser = "kitten";

    @Override protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        api.base = prefs.getString("base", DEFAULT_BASE);
        api.token = prefs.getString("token", "");
        applyTheme(null);
        if (api.token != null && api.token.length() > 0) loadBootstrap(); else showLogin();
    }

    @Override public void onBackPressed() {
        if ("bottle".equals(screen)) { showHome(); return; }
        if ("project".equals(screen) || "settings".equals(screen)) { showHome(); return; }
        if ("thread".equals(screen)) { showMessages(); return; }
        if ("messages".equals(screen)) { showHome(); return; }
        if (!"login".equals(screen)) { showHome(); return; }
        super.onBackPressed();
    }

    @Override protected void onDestroy() { pool.shutdownNow(); super.onDestroy(); }

    // ---------------- theme / small UI helpers ----------------
    private int c(String value, int fallback) {
        try { return Color.parseColor(value); } catch (Exception e) { return fallback; }
    }
    private void applyTheme(JSONObject t) {
        theme = t;
        bg = c(t == null ? "" : t.optString("bg"), 0xfff8f4ec);
        card = c(t == null ? "" : t.optString("card"), 0xfffffdf8);
        ink = c(t == null ? "" : t.optString("ink"), 0xff42392b);
        muted = c(t == null ? "" : t.optString("muted"), 0xff8a7f6d);
        line = c(t == null ? "" : t.optString("line"), 0xffe8dfd2);
        accent = c(t == null ? "" : t.optString("accent"), 0xffec9fbe);
        soft = c(t == null ? "" : t.optString("soft"), 0xfff6dce5);
        deep = c(t == null ? "" : t.optString("deep"), 0xffb84b72);
        try {
            getWindow().setStatusBarColor(bg);
            getWindow().setNavigationBarColor(bg);
            int flags = View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR;
            if (android.os.Build.VERSION.SDK_INT >= 26) flags |= View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR;
            getWindow().getDecorView().setSystemUiVisibility(flags);
        } catch (Exception ignored) {}
    }
    private int dp(float v) { return Math.round(v * getResources().getDisplayMetrics().density); }
    private GradientDrawable rounded(int color, float radius, int strokeColor) {
        GradientDrawable d = new GradientDrawable();
        d.setColor(color);
        d.setCornerRadius(dp(radius));
        if (strokeColor != 0) d.setStroke(dp(1), strokeColor);
        return d;
    }
    private TextView tv(String text, float size, int color, boolean bold) {
        TextView v = new TextView(this);
        v.setText(text == null ? "" : text);
        v.setTextSize(size);
        v.setTextColor(color);
        if (bold) v.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        v.setLineSpacing(0, 1.16f);
        return v;
    }
    private TextView action(String icon, Runnable click) {
        TextView v = tv(icon, 19, ink, false);
        v.setGravity(Gravity.CENTER);
        v.setBackground(rounded(card, 22, line));
        v.setClickable(true);
        v.setOnClickListener(x -> click.run());
        return v;
    }
    private LinearLayout.LayoutParams lp(int w, int h, int margin) {
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(w, h);
        p.setMargins(margin, margin, margin, margin);
        return p;
    }
    private int mix(int a, int b, float t) {
        t = Math.max(0f, Math.min(1f, t));
        return Color.argb(
                Math.round(Color.alpha(a) + (Color.alpha(b) - Color.alpha(a)) * t),
                Math.round(Color.red(a) + (Color.red(b) - Color.red(a)) * t),
                Math.round(Color.green(a) + (Color.green(b) - Color.green(a)) * t),
                Math.round(Color.blue(a) + (Color.blue(b) - Color.blue(a)) * t));
    }
    private GradientDrawable screenBackground() {
        GradientDrawable g = new GradientDrawable(GradientDrawable.Orientation.TL_BR,
                new int[]{mix(bg, Color.WHITE, .42f), bg, mix(bg, soft, .22f)});
        return g;
    }
    private GradientDrawable accentButton() {
        return new GradientDrawable(GradientDrawable.Orientation.LEFT_RIGHT,
                new int[]{accent, mix(accent, soft, .35f)});
    }
    private void setRoot(View view) {
        setContentView(view);
        view.setBackground(screenBackground());
    }
    private void showLoading(String text) {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER);
        root.setBackgroundColor(bg);
        ProgressBar bar = new ProgressBar(this);
        bar.getIndeterminateDrawable().setColorFilter(accent, android.graphics.PorterDuff.Mode.SRC_IN);
        root.addView(bar, new LinearLayout.LayoutParams(dp(40), dp(40)));
        TextView label = tv(text, 13, muted, false);
        label.setGravity(Gravity.CENTER);
        root.addView(label, lp(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT, 12));
        setRoot(root);
    }
    private void err(String message) { Toast.makeText(this, message == null ? "请求失败" : message, Toast.LENGTH_LONG).show(); }
    private void hideKeyboard() {
        try {
            InputMethodManager imm = (InputMethodManager) getSystemService(Context.INPUT_METHOD_SERVICE);
            if (imm != null && getCurrentFocus() != null) imm.hideSoftInputFromWindow(getCurrentFocus().getWindowToken(), 0);
        } catch (Exception ignored) {}
    }

    // ---------------- async ----------------
    interface JsonCb { void ok(JSONObject j); void fail(String message); }
    private void getAsync(String path, JsonCb cb) {
        pool.execute(() -> {
            try { JSONObject j = api.get(path); ui.post(() -> cb.ok(j)); }
            catch (Api.Unauthorized u) { ui.post(() -> { clearSession(); showLogin(); err(u.getMessage()); }); }
            catch (Exception e) { ui.post(() -> cb.fail(e.getMessage())); }
        });
    }
    private void postAsync(String path, JSONObject body, JsonCb cb) {
        pool.execute(() -> {
            try { JSONObject j = api.post(path, body); ui.post(() -> cb.ok(j)); }
            catch (Api.Unauthorized u) { ui.post(() -> { clearSession(); showLogin(); err(u.getMessage()); }); }
            catch (Exception e) { ui.post(() -> cb.fail(e.getMessage())); }
        });
    }
    private void clearSession() {
        api.token = ""; session = null; tree = null; theme = null;
        prefs.edit().remove("token").apply();
    }

    // ---------------- login ----------------
    private void showLogin() {
        screen = "login";
        FrameLayout root = new FrameLayout(this);
        root.setBackground(screenBackground());
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        LinearLayout center = new LinearLayout(this);
        center.setOrientation(LinearLayout.VERTICAL);
        center.setGravity(Gravity.CENTER_HORIZONTAL);
        center.setPadding(dp(18), dp(28), dp(18), dp(28));
        int cardW = Math.min(dp(360), getResources().getDisplayMetrics().widthPixels - dp(36));
        LinearLayout cardBox = new LinearLayout(this);
        cardBox.setOrientation(LinearLayout.VERTICAL);
        cardBox.setPadding(dp(24), dp(24), dp(24), dp(20));
        cardBox.setBackground(rounded(mix(card, Color.WHITE, .35f), 20, line));
        cardBox.setElevation(dp(10));
        LinearLayout.LayoutParams cp = new LinearLayout.LayoutParams(cardW, ViewGroup.LayoutParams.WRAP_CONTENT);
        center.addView(cardBox, cp);

        TextView logo = tv("🐱🐶", 30, ink, false);
        logo.setGravity(Gravity.CENTER_HORIZONTAL);
        cardBox.addView(logo);
        TextView title = tv("KittenPuppy4Ever", 19, ink, true);
        title.setGravity(Gravity.CENTER_HORIZONTAL);
        title.setPadding(0, dp(8), 0, dp(2));
        cardBox.addView(title);
        TextView sub = tv("选择角色，进入私人工作台", 12, muted, false);
        sub.setGravity(Gravity.CENTER_HORIZONTAL);
        sub.setPadding(0, 0, 0, dp(16));
        cardBox.addView(sub);

        loginUser = prefs.getString("user", "kitten");
        final LinearLayout roles = new LinearLayout(this);
        roles.setOrientation(LinearLayout.HORIZONTAL);
        final LinearLayout[] roleViews = new LinearLayout[2];
        String[][] roleMeta = {{"🐱", "kitten", "主要使用者"}, {"🐶", "puppy", "主要维护者"}};
        for (int i = 0; i < 2; i++) {
            final String ru = roleMeta[i][1];
            LinearLayout role = new LinearLayout(this);
            role.setOrientation(LinearLayout.VERTICAL);
            role.setGravity(Gravity.CENTER);
            role.setPadding(dp(8), dp(10), dp(8), dp(9));
            TextView em = tv(roleMeta[i][0], 20, ink, false);
            em.setGravity(Gravity.CENTER);
            role.addView(em);
            TextView nm = tv(ru, 13, ink, true);
            nm.setGravity(Gravity.CENTER);
            role.addView(nm);
            TextView sm = tv(roleMeta[i][2], 10, muted, false);
            sm.setGravity(Gravity.CENTER);
            role.addView(sm);
            role.setOnClickListener(v -> { loginUser = ru; refreshRoleCards(roleViews); });
            roleViews[i] = role;
            LinearLayout.LayoutParams rlp = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
            if (i == 1) rlp.leftMargin = dp(10);
            roles.addView(role, rlp);
        }
        cardBox.addView(roles, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        EditText user = field("用户名", false);
        user.setText(loginUser);
        user.setPadding(dp(12), 0, dp(12), 0);
        LinearLayout.LayoutParams up = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(46));
        up.topMargin = dp(12);
        cardBox.addView(user, up);
        EditText pwd = field("凭据", true);
        cardBox.addView(pwd, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(46)));

        TextView serverLabel = tv("服务器", 10, muted, false);
        serverLabel.setPadding(0, dp(10), 0, dp(3));
        cardBox.addView(serverLabel);
        EditText server = field("https://…", false);
        server.setText(prefs.getString("base", DEFAULT_BASE));
        server.setInputType(InputType.TYPE_TEXT_VARIATION_URI);
        server.setTextSize(11);
        cardBox.addView(server, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(40)));

        TextView status = tv("登录由服务器校验，会话保存在本机。", 10, muted, false);
        status.setPadding(0, dp(9), 0, dp(6));
        cardBox.addView(status);

        Button go = new Button(this);
        go.setText("登 录");
        go.setTextColor(Color.WHITE);
        go.setTextSize(14);
        go.setAllCaps(false);
        go.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        go.setBackground(accentButton());
        cardBox.addView(go, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(46)));

        user.setOnFocusChangeListener((v, has) -> { if (has) loginUser = user.getText().toString().trim(); });
        go.setOnClickListener(v -> {
            String b = server.getText().toString().trim();
            String u = user.getText().toString().trim();
            String p = pwd.getText().toString();
            if (b.length() == 0 || u.length() == 0 || p.length() == 0) { status.setText("请填写服务器、账号和凭据"); return; }
            hideKeyboard();
            go.setEnabled(false); go.setText("登录中…"); status.setText("正在连接服务器…");
            api.base = b; loginUser = u;
            JSONObject body = new JSONObject();
            try { body.put("user", u); body.put("password", p); } catch (Exception ignored) {}
            postAsync("/api/login", body, new JsonCb() {
                @Override public void ok(JSONObject j) {
                    String token = j.optString("token", "");
                    if (token.length() == 0) { go.setEnabled(true); go.setText("登 录"); status.setText("服务器未返回 token"); return; }
                    api.token = token;
                    prefs.edit().putString("base", b).putString("user", u).putString("token", token).apply();
                    loadBootstrap();
                }
                @Override public void fail(String m) {
                    go.setEnabled(true); go.setText("登 录"); status.setText("登录失败：" + m);
                }
            });
        });

        scroll.addView(center);
        root.addView(scroll, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        setRoot(root);
        refreshRoleCards(roleViews);
        pwd.requestFocus();
    }
    private void refreshRoleCards(LinearLayout[] views) {
        for (LinearLayout v : views) {
            if (v == null) continue;
            boolean on = v.getChildAt(1) != null && loginUser.equals(((TextView) v.getChildAt(1)).getText().toString());
            v.setBackground(rounded(on ? mix(accent, Color.WHITE, .86f) : mix(card, Color.WHITE, .45f), 14, on ? accent : line));
            if (on) v.setElevation(dp(3)); else v.setElevation(0);
        }
    }
    private EditText field(String hint, boolean password) {
        EditText e = new EditText(this);
        e.setHint(hint);
        e.setTextSize(13);
        e.setTextColor(ink);
        e.setHintTextColor(muted);
        e.setSingleLine(true);
        e.setPadding(dp(13), 0, dp(13), 0);
        e.setBackground(rounded(card, 13, line));
        if (password) e.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        return e;
    }
    private TextView chip(String label, boolean active) {
        TextView v = tv(label, 12, active ? Color.WHITE : ink, true);
        v.setGravity(Gravity.CENTER);
        v.setBackground(rounded(active ? accent : card, 19, active ? accent : line));
        v.setClickable(true);
        v.setOnClickListener(x -> {
            for (int i = 0; i < ((ViewGroup) v.getParent()).getChildCount(); i++) {
                View c = ((ViewGroup) v.getParent()).getChildAt(i);
                if (c instanceof TextView) {
                    TextView t = (TextView) c;
                    boolean on = t == v;
                    t.setTextColor(on ? Color.WHITE : ink);
                    t.setBackground(rounded(on ? accent : card, 19, on ? accent : line));
                }
            }
        });
        return v;
    }
    private void loadBootstrap() {
        showLoading("正在读取工作台…");
        getAsync("/api/bootstrap", new JsonCb() {
            @Override public void ok(JSONObject j) {
                session = j.optJSONObject("session");
                theme = j.optJSONObject("theme");
                JSONObject tr = j.optJSONObject("tree");
                tree = tr == null ? null : tr.optJSONObject("root");
                applyTheme(theme);
                showHome();
            }
            @Override public void fail(String m) { err("读取失败：" + m); showLogin(); }
        });
    }

    // ---------------- home ----------------
    private void showHome() {
        screen = "home";
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(bg);

        LinearLayout header = new LinearLayout(this);
        header.setOrientation(LinearLayout.HORIZONTAL);
        header.setGravity(Gravity.CENTER_VERTICAL);
        header.setPadding(dp(20), dp(12), dp(14), dp(10));
        header.setBackgroundColor(mix(card, bg, .45f));

        LinearLayout brandBox = new LinearLayout(this);
        brandBox.setOrientation(LinearLayout.VERTICAL);
        TextView brand = tv("🐱🐶 KittenPuppy4Ever", 17, ink, true);
        TextView who = tv("私人工作台", 10, muted, false);
        brandBox.addView(brand);
        brandBox.addView(who);
        header.addView(brandBox, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));

        final TextView mail = action("✉", () -> { hideKeyboard(); showMessages(); });
        FrameLayout mailWrap = new FrameLayout(this);
        mailWrap.addView(mail, new FrameLayout.LayoutParams(dp(44), dp(44)));
        homeMailBadge = tv("0", 8.5f, Color.WHITE, true);
        homeMailBadge.setGravity(Gravity.CENTER);
        homeMailBadge.setBackground(rounded(RED, 8, 0));
        homeMailBadge.setVisibility(View.GONE);
        FrameLayout.LayoutParams bp = new FrameLayout.LayoutParams(dp(16), dp(16));
        bp.gravity = Gravity.TOP | Gravity.RIGHT;
        mailWrap.addView(homeMailBadge, bp);
        LinearLayout.LayoutParams mw = new LinearLayout.LayoutParams(dp(48), dp(44));
        mw.leftMargin = dp(6);
        header.addView(mailWrap, mw);

        TextView settings = action("⚙", this::showSettings);
        LinearLayout.LayoutParams sw = new LinearLayout.LayoutParams(dp(44), dp(44));
        sw.leftMargin = dp(6);
        header.addView(settings, sw);
        root.addView(header);

        ScrollView scroll = new ScrollView(this);
        LinearLayout body = new LinearLayout(this);
        body.setOrientation(LinearLayout.VERTICAL);
        body.setPadding(dp(20), dp(16), dp(20), dp(36));

        String user = session == null ? "" : session.optString("user", "");
        String emoji = session == null ? "" : session.optString("emoji", "");
        TextView hello = tv("你好，" + emoji + " " + user, 14, muted, false);
        hello.setPadding(dp(2), dp(4), 0, dp(18));
        body.addView(hello);

        List<JSONObject> nodes = new ArrayList<>();
        JSONArray children = tree == null ? null : tree.optJSONArray("children");
        if (children != null) {
            for (int i = 0; i < children.length(); i++) {
                JSONObject o = children.optJSONObject(i);
                if (o != null && !o.optBoolean("hidden", false)) nodes.add(o);
            }
        }
        Collections.sort(nodes, new Comparator<JSONObject>() {
            @Override public int compare(JSONObject a, JSONObject b) { return a.optInt("order", 0) - b.optInt("order", 0); }
        });
        for (JSONObject node : nodes) body.addView(projectCard(node));
        TextView foot = tv("原生客户端 0.1.0 · phase 1", 10, muted, false);
        foot.setPadding(0, dp(18), 0, 0);
        body.addView(foot);
        scroll.addView(body);
        root.addView(scroll, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
        setRoot(root);
        refreshBadge();
    }
    private View projectCard(JSONObject node) {
        LinearLayout cardBox = new LinearLayout(this);
        cardBox.setOrientation(LinearLayout.VERTICAL);
        cardBox.setPadding(dp(18), dp(18), dp(18), dp(15));
        cardBox.setBackground(rounded(card, 18, line));
        cardBox.setElevation(dp(3));
        cardBox.setClickable(true);
        cardBox.setOnClickListener(v -> showProject(node));

        TextView icon = tv(node.optString("icon", "📄"), 24, ink, false);
        icon.setGravity(Gravity.CENTER);
        icon.setBackground(rounded(mix(accent, Color.WHITE, .78f), 14, 0));
        cardBox.addView(icon, new LinearLayout.LayoutParams(dp(44), dp(44)));
        TextView title = tv(node.optString("title", "未命名"), 16, ink, true);
        title.setPadding(0, dp(10), 0, 0);
        cardBox.addView(title);
        TextView desc = tv(node.optString("desc", ""), 12, muted, false);
        desc.setMaxLines(3);
        desc.setLineSpacing(0, 1.45f);
        desc.setMinHeight(dp(38));
        desc.setPadding(0, dp(4), 0, dp(10));
        cardBox.addView(desc);

        LinearLayout foot = new LinearLayout(this);
        foot.setOrientation(LinearLayout.HORIZONTAL);
        foot.setGravity(Gravity.CENTER_VERTICAL);
        StringBuilder tags = new StringBuilder();
        JSONArray ta = node.optJSONArray("tags");
        if (ta != null) for (int i = 0; i < Math.min(3, ta.length()); i++) {
            if (tags.length() > 0) tags.append("   ");
            tags.append("#").append(ta.optString(i));
        }
        TextView tag = tv(tags.toString(), 10, muted, false);
        foot.addView(tag, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        TextView go = tv("进入 ›", 12, accent, true);
        foot.addView(go);
        cardBox.addView(foot);
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        p.bottomMargin = dp(16);
        cardBox.setLayoutParams(p);
        return cardBox;
    }
    private void refreshBadge() {
        final TextView badge = homeMailBadge;
        pool.execute(() -> {
            int total = 0;
            try { JSONObject n = api.get("/api/notifications?limit=200"); total += n.optInt("unread", 0); } catch (Exception ignored) {}
            try { JSONObject t = api.get("/api/messages/threads"); total += t.optInt("unread", 0); } catch (Exception ignored) {}
            final int value = total;
            ui.post(() -> {
                if (badge != null) {
                    badge.setText(value > 99 ? "99+" : String.valueOf(value));
                    badge.setVisibility(value > 0 ? View.VISIBLE : View.GONE);
                }
            });
        });
    }

    // ---------------- project ----------------
    private void showProject(JSONObject node) {
        screen = "project"; currentProject = node;
        if ("bottle".equals(node.optString("id"))) { showBottle(node); return; }
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(bg);
        root.addView(topBar(node.optString("title", "模块"), true, this::showHome));

        ScrollView scroll = new ScrollView(this);
        LinearLayout body = new LinearLayout(this);
        body.setOrientation(LinearLayout.VERTICAL);
        body.setPadding(dp(20), dp(12), dp(20), dp(28));
        TextView icon = tv(node.optString("icon", "📄"), 42, ink, false);
        body.addView(icon);
        TextView title = tv(node.optString("title", "模块"), 26, ink, true);
        title.setPadding(0, dp(8), 0, 0);
        body.addView(title);
        TextView desc = tv(node.optString("desc", ""), 12, muted, false);
        desc.setPadding(0, dp(8), 0, dp(18));
        body.addView(desc);

        LinearLayout note = new LinearLayout(this);
        note.setOrientation(LinearLayout.VERTICAL);
        note.setPadding(dp(14), dp(14), dp(14), dp(14));
        note.setBackground(rounded(card, 16, line));
        TextView nt = tv("原生页面骨架", 13, ink, true);
        note.addView(nt);
        TextView nb = tv("第一阶段已完成账号、主题、工作台卡片、原生路由和消息/设置基础页。该模块的业务交互将在下一阶段原生实现，不使用 WebView。", 11, muted, false);
        nb.setPadding(0, dp(5), 0, 0);
        note.addView(nb);
        body.addView(note);

        TextView stateText = tv("尚未读取模块状态", 11, muted, false);
        stateText.setPadding(0, dp(14), 0, 0);
        body.addView(stateText);
        Button state = new Button(this);
        state.setText("读取模块状态");
        state.setTextColor(Color.WHITE); state.setAllCaps(false); state.setTextSize(13);
        state.setBackground(rounded(accent, 20, 0));
        state.setOnClickListener(v -> {
            state.setEnabled(false); state.setText("读取中…");
            getAsync("/api/p/" + node.optString("id") + "/state", new JsonCb() {
                @Override public void ok(JSONObject j) {
                    state.setEnabled(true); state.setText("读取模块状态");
                    stateText.setText("kp/1 · rev " + j.optInt("rev", 0) + " · " + j.optString("project", ""));
                }
                @Override public void fail(String m) { state.setEnabled(true); state.setText("读取模块状态"); err(m); }
            });
        });
        body.addView(state, lp(LinearLayout.LayoutParams.MATCH_PARENT, dp(44), 8));
        scroll.addView(body);
        root.addView(scroll, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
        setRoot(root);
    }

    private LinearLayout topBar(String title, boolean back, Runnable backAction) {
        LinearLayout header = new LinearLayout(this);
        header.setOrientation(LinearLayout.HORIZONTAL);
        header.setGravity(Gravity.CENTER_VERTICAL);
        header.setPadding(dp(12), dp(10), dp(14), dp(8));
        LinearLayout.LayoutParams hp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        header.setLayoutParams(hp);
        header.setBackground(rounded(mix(card, bg, .52f), 18, line));
        if (back) {
            TextView b = tv("← 返回", 11, muted, false);
            b.setGravity(Gravity.CENTER);
            b.setPadding(dp(11), 0, dp(11), 0);
            b.setBackground(rounded(card, 18, line));
            b.setClickable(true);
            b.setOnClickListener(v -> backAction.run());
            header.addView(b, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, dp(36)));
        }
        TextView t = tv(title, 16, ink, true);
        t.setPadding(back ? dp(10) : 0, 0, 0, 0);
        header.addView(t, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        return header;
    }

    // ---------------- messages ----------------
    private void showMessages() { showMessages(messagesTab); }
    private void showMessages(int tab) {
        messagesTab = tab;
        String[] items = {"通知", "私信"};
        KpPopup popup = new KpPopup(this, "消息", items, tab, (p, index) -> messagesPane(p, index),
                bg, card, ink, muted, line, accent, soft);
        popup.show();
    }
    private View messagesPane(KpPopup popup, int tab) {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        TextView head = tv(tab == 0 ? "通知" : "私信", 17, ink, true);
        head.setPadding(0, 0, dp(44), dp(10));
        root.addView(head);
        LinearLayout actions = new LinearLayout(this);
        actions.setOrientation(LinearLayout.HORIZONTAL);
        actions.setGravity(Gravity.END);
        TextView readAll = smallButton("全部已读");
        readAll.setOnClickListener(v -> markAllFromPopup(popup));
        actions.addView(readAll);
        root.addView(actions);
        ScrollView scroll = new ScrollView(this);
        LinearLayout list = new LinearLayout(this);
        list.setOrientation(LinearLayout.VERTICAL);
        list.setPadding(0, dp(4), 0, dp(8));
        scroll.addView(list);
        root.addView(scroll, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
        if (tab == 0) loadNotificationsPane(popup, list);
        else loadPrivatePane(popup, list);
        return root;
    }
    private void loadNotificationsPane(KpPopup popup, LinearLayout list) {
        list.addView(tv("读取中…", 12, muted, false));
        getAsync("/api/notifications?limit=200", new JsonCb() {
            @Override public void ok(JSONObject j) {
                list.removeAllViews();
                JSONArray arr = j.optJSONArray("items");
                if (arr == null || arr.length() == 0) { list.addView(empty("还没有通知。")); return; }
                for (int i = 0; i < arr.length(); i++) {
                    final JSONObject n = arr.optJSONObject(i);
                    if (n == null) continue;
                    list.addView(simpleRow(n.optString("title", "消息"), n.optString("body", ""), n.optBoolean("read", false) ? 0 : 1, () -> {
                        if (n.optBoolean("read")) return;
                        JSONObject body = new JSONObject();
                        try { JSONArray ids = new JSONArray(); ids.put(n.optString("id")); body.put("ids", ids); } catch (Exception ignored) {}
                        postAsync("/api/notifications/read", body, new JsonCb() {
                            @Override public void ok(JSONObject x) { popup.selectTab(0); refreshBadge(); }
                            @Override public void fail(String m) { err(m); }
                        });
                    }));
                }
            }
            @Override public void fail(String m) { list.removeAllViews(); list.addView(empty("读取失败：" + m)); }
        });
    }
    private void loadPrivatePane(KpPopup popup, LinearLayout list) {
        list.addView(tv("读取中…", 12, muted, false));
        getAsync("/api/messages/threads", new JsonCb() {
            @Override public void ok(JSONObject j) {
                list.removeAllViews();
                JSONArray arr = j.optJSONArray("threads");
                if (arr == null || arr.length() == 0) { list.addView(empty("还没有私信。")); return; }
                for (int i = 0; i < arr.length(); i++) {
                    JSONObject t = arr.optJSONObject(i);
                    if (t == null) continue;
                    final String peer = t.optString("peer", "");
                    JSONObject last = t.optJSONObject("last");
                    list.addView(simpleRow("🐾 " + peer, last == null ? "" : last.optString("body", ""), t.optInt("unread", 0),
                            () -> showThreadPane(popup, peer)));
                }
            }
            @Override public void fail(String m) { list.removeAllViews(); list.addView(empty("读取失败：" + m)); }
        });
    }
    private void markAllFromPopup(KpPopup popup) {
        JSONObject body = new JSONObject();
        try { body.put("all", true); } catch (Exception ignored) {}
        postAsync("/api/notifications/read", body, new JsonCb() {
            @Override public void ok(JSONObject j) {
                JSONObject dm = new JSONObject();
                try { dm.put("all", true); } catch (Exception ignored) {}
                postAsync("/api/messages/read", dm, new JsonCb() {
                    @Override public void ok(JSONObject x) { popup.selectTab(messagesTab); refreshBadge(); }
                    @Override public void fail(String m) { err(m); }
                });
            }
            @Override public void fail(String m) { err(m); }
        });
    }
    private void showThreadPane(KpPopup popup, String peer) {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        LinearLayout head = new LinearLayout(this);
        head.setOrientation(LinearLayout.HORIZONTAL);
        head.setGravity(Gravity.CENTER_VERTICAL);
        TextView back = tv("←", 16, muted, false);
        back.setGravity(Gravity.CENTER);
        back.setBackground(rounded(card, 20, line));
        back.setClickable(true);
        back.setOnClickListener(v -> popup.selectTab(1));
        head.addView(back, new LinearLayout.LayoutParams(dp(36), dp(36)));
        TextView title = tv("与 " + peer, 15, ink, true);
        title.setPadding(dp(9), 0, dp(44), 0);
        head.addView(title, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        root.addView(head);
        ScrollView scroll = new ScrollView(this);
        LinearLayout list = new LinearLayout(this);
        list.setOrientation(LinearLayout.VERTICAL);
        list.setPadding(0, dp(8), 0, dp(8));
        scroll.addView(list);
        root.addView(scroll, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
        LinearLayout composer = new LinearLayout(this);
        composer.setOrientation(LinearLayout.HORIZONTAL);
        composer.setGravity(Gravity.BOTTOM);
        composer.setPadding(0, dp(6), 0, 0);
        EditText input = field("发消息给 " + peer + "…", false);
        composer.addView(input, new LinearLayout.LayoutParams(0, dp(44), 1f));
        TextView send = tv("↑", 18, Color.WHITE, true);
        send.setGravity(Gravity.CENTER);
        send.setBackground(rounded(accent, 22, 0));
        LinearLayout.LayoutParams sp = new LinearLayout.LayoutParams(dp(44), dp(44)); sp.leftMargin = dp(7);
        composer.addView(send, sp);
        root.addView(composer);
        popup.setContent(root);
        loadThreadPane(list, peer, scroll, popup);
        send.setOnClickListener(v -> {
            String text = input.getText().toString().trim();
            if (text.length() == 0) return;
            send.setEnabled(false);
            JSONObject body = new JSONObject();
            try { body.put("to", peer); body.put("body", text); } catch (Exception ignored) {}
            postAsync("/api/messages/send", body, new JsonCb() {
                @Override public void ok(JSONObject j) { input.setText(""); send.setEnabled(true); loadThreadPane(list, peer, scroll, popup); refreshBadge(); }
                @Override public void fail(String m) { send.setEnabled(true); err("发送失败：" + m); }
            });
        });
    }
    private void loadThreadPane(LinearLayout list, String peer, ScrollView scroll, KpPopup popup) {
        list.removeAllViews();
        list.addView(tv("读取中…", 12, muted, false));
        getAsync("/api/messages/thread?peer=" + android.net.Uri.encode(peer), new JsonCb() {
            @Override public void ok(JSONObject j) {
                list.removeAllViews();
                JSONArray arr = j.optJSONArray("messages");
                String me = session == null ? "" : session.optString("user", "");
                if (arr == null || arr.length() == 0) list.addView(empty("还没有消息。"));
                else for (int i = 0; i < arr.length(); i++) {
                    JSONObject m = arr.optJSONObject(i);
                    if (m == null) continue;
                    boolean mine = me.equals(m.optString("from", ""));
                    LinearLayout row = new LinearLayout(MainActivity.this);
                    row.setOrientation(LinearLayout.HORIZONTAL);
                    row.setGravity(mine ? Gravity.END : Gravity.START);
                    if (mine) {
                        TextView read = tv(m.optBoolean("read", false) ? "已读" : "未读", 8.5f, m.optBoolean("read", false) ? muted : accent, false);
                        read.setPadding(0, 0, dp(5), dp(4));
                        row.addView(read);
                    }
                    LinearLayout bubble = new LinearLayout(MainActivity.this);
                    bubble.setOrientation(LinearLayout.VERTICAL);
                    bubble.setPadding(dp(11), dp(8), dp(11), dp(7));
                    bubble.setBackground(rounded(mine ? accent : card, 14, mine ? 0 : line));
                    TextView b = tv(m.optString("body", ""), 12.5f, mine ? Color.WHITE : ink, false);
                    b.setMaxWidth(dp(250));
                    bubble.addView(b);
                    LinearLayout.LayoutParams bp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
                    bp.leftMargin = mine ? 0 : dp(4); bp.rightMargin = mine ? dp(4) : 0; bp.bottomMargin = dp(7);
                    row.addView(bubble, bp);
                    list.addView(row);
                }
                JSONObject readBody = new JSONObject();
                try { readBody.put("peer", peer); } catch (Exception ignored) {}
                postAsync("/api/messages/read", readBody, new JsonCb() {
                    @Override public void ok(JSONObject x) { refreshBadge(); }
                    @Override public void fail(String m) {}
                });
                scroll.post(() -> scroll.fullScroll(View.FOCUS_DOWN));
            }
            @Override public void fail(String m) { list.removeAllViews(); list.addView(empty("读取失败：" + m)); }
        });
    }
    private TextView tabChip(String label, boolean active) {
        TextView v = tv(label, 12, active ? Color.WHITE : ink, true);
        v.setGravity(Gravity.CENTER);
        v.setBackground(rounded(active ? accent : card, 18, active ? accent : line));
        v.setClickable(true);
        return v;
    }
    private TextView smallButton(String label) {
        TextView v = tv(label, 11, accent, true);
        v.setGravity(Gravity.CENTER);
        v.setPadding(dp(12), dp(7), dp(12), dp(7));
        v.setBackground(rounded(card, 16, line));
        v.setClickable(true);
        return v;
    }
    private void loadMessages(LinearLayout list, int tab) {
        list.removeAllViews();
        list.addView(tv("读取中…", 12, muted, false));
        if (tab == 1) {
            getAsync("/api/messages/threads", new JsonCb() {
                @Override public void ok(JSONObject j) {
                    list.removeAllViews();
                    JSONArray arr = j.optJSONArray("threads");
                    if (arr == null || arr.length() == 0) { list.addView(empty("还没有私信。")); return; }
                    for (int i = 0; i < arr.length(); i++) {
                        JSONObject t = arr.optJSONObject(i);
                        if (t == null) continue;
                        final String peer = t.optString("peer", "");
                        JSONObject last = t.optJSONObject("last");
                        int unread = t.optInt("unread", 0);
                        list.addView(simpleRow("🐾 " + peer, last == null ? "" : last.optString("body", ""), unread, () -> showThread(peer)));
                    }
                }
                @Override public void fail(String m) { list.removeAllViews(); list.addView(empty("读取失败：" + m)); }
            });
        } else {
            getAsync("/api/notifications?limit=200", new JsonCb() {
                @Override public void ok(JSONObject j) {
                    list.removeAllViews();
                    JSONArray arr = j.optJSONArray("items");
                    if (arr == null || arr.length() == 0) { list.addView(empty("还没有通知。")); return; }
                    for (int i = 0; i < arr.length(); i++) {
                        final JSONObject n = arr.optJSONObject(i);
                        if (n == null) continue;
                        list.addView(simpleRow(n.optString("title", "消息"), n.optString("body", ""), n.optBoolean("read", false) ? 0 : 1, () -> markNotification(n.optString("id", ""))));
                    }
                }
                @Override public void fail(String m) { list.removeAllViews(); list.addView(empty("读取失败：" + m)); }
            });
        }
    }
    private View empty(String text) {
        TextView v = tv(text, 12, muted, false);
        v.setGravity(Gravity.CENTER);
        v.setPadding(0, dp(36), 0, dp(36));
        return v;
    }
    private View simpleRow(String title, String body, int unread, Runnable click) {
        LinearLayout r = new LinearLayout(this);
        r.setOrientation(LinearLayout.VERTICAL);
        r.setPadding(dp(13), dp(11), dp(13), dp(11));
        r.setBackground(rounded(unread > 0 ? Color.argb(18, Color.red(accent), Color.green(accent), Color.blue(accent)) : card, 14, line));
        LinearLayout head = new LinearLayout(this);
        head.setOrientation(LinearLayout.HORIZONTAL);
        head.setGravity(Gravity.CENTER_VERTICAL);
        TextView t = tv(title, 12.5f, ink, true);
        head.addView(t, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        if (unread > 0) {
            TextView dot = tv("●", 10, RED, false);
            head.addView(dot);
        }
        r.addView(head);
        if (body != null && body.length() > 0) {
            TextView b = tv(body, 11, muted, false);
            b.setMaxLines(3);
            b.setPadding(0, dp(3), 0, 0);
            r.addView(b);
        }
        r.setClickable(true);
        r.setOnClickListener(v -> click.run());
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        p.bottomMargin = dp(8); r.setLayoutParams(p);
        return r;
    }
    private void markNotification(String id) {
        if (id.length() == 0) return;
        JSONObject body = new JSONObject();
        try { JSONArray a = new JSONArray(); a.put(id); body.put("ids", a); } catch (Exception ignored) {}
        postAsync("/api/notifications/read", body, new JsonCb() {
            @Override public void ok(JSONObject j) { showMessages(0); refreshBadge(); }
            @Override public void fail(String m) { err(m); }
        });
    }
    private void markAllRead() {
        JSONObject body = new JSONObject();
        try { body.put("all", true); } catch (Exception ignored) {}
        postAsync("/api/notifications/read", body, new JsonCb() {
            @Override public void ok(JSONObject j) {
                JSONObject dm = new JSONObject();
                try { dm.put("all", true); } catch (Exception ignored) {}
                postAsync("/api/messages/read", dm, new JsonCb() {
                    @Override public void ok(JSONObject x) { showMessages(messagesTab); refreshBadge(); }
                    @Override public void fail(String m) { err(m); }
                });
            }
            @Override public void fail(String m) { err(m); }
        });
    }
    private void showThread(String peer) {
        screen = "thread"; messagesPeer = peer;
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(bg);
        root.addView(topBar("与 " + peer, true, this::showMessages));
        ScrollView scroll = new ScrollView(this);
        LinearLayout list = new LinearLayout(this);
        list.setOrientation(LinearLayout.VERTICAL);
        list.setPadding(dp(14), dp(8), dp(14), dp(14));
        scroll.addView(list);
        root.addView(scroll, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));

        LinearLayout composer = new LinearLayout(this);
        composer.setOrientation(LinearLayout.HORIZONTAL);
        composer.setGravity(Gravity.BOTTOM);
        composer.setPadding(dp(10), dp(8), dp(10), dp(10));
        EditText input = field("发消息给 " + peer + "…", false);
        composer.addView(input, new LinearLayout.LayoutParams(0, dp(46), 1f));
        TextView send = tv("↑", 18, Color.WHITE, true);
        send.setGravity(Gravity.CENTER);
        send.setBackground(rounded(accent, 23, 0));
        LinearLayout.LayoutParams sp = new LinearLayout.LayoutParams(dp(46), dp(46)); sp.leftMargin = dp(7);
        composer.addView(send, sp);
        root.addView(composer);
        setRoot(root);
        loadThread(list, peer, scroll);
        send.setOnClickListener(v -> {
            String text = input.getText().toString().trim();
            if (text.length() == 0) return;
            send.setEnabled(false);
            JSONObject body = new JSONObject();
            try { body.put("to", peer); body.put("body", text); } catch (Exception ignored) {}
            postAsync("/api/messages/send", body, new JsonCb() {
                @Override public void ok(JSONObject j) { input.setText(""); send.setEnabled(true); loadThread(list, peer, scroll); refreshBadge(); }
                @Override public void fail(String m) { send.setEnabled(true); err("发送失败：" + m); }
            });
        });
    }
    private void loadThread(LinearLayout list, String peer, ScrollView scroll) {
        list.removeAllViews();
        list.addView(tv("读取中…", 12, muted, false));
        getAsync("/api/messages/thread?peer=" + android.net.Uri.encode(peer), new JsonCb() {
            @Override public void ok(JSONObject j) {
                list.removeAllViews();
                JSONArray arr = j.optJSONArray("messages");
                if (arr == null || arr.length() == 0) { list.addView(empty("还没有消息。")); }
                else {
                    String me = session == null ? "" : session.optString("user", "");
                    for (int i = 0; i < arr.length(); i++) {
                        JSONObject m = arr.optJSONObject(i);
                        if (m == null) continue;
                        boolean mine = me.equals(m.optString("from", ""));
                        LinearLayout row = new LinearLayout(MainActivity.this);
                        row.setOrientation(LinearLayout.HORIZONTAL);
                        row.setGravity(mine ? Gravity.END : Gravity.START);
                        if (mine) {
                            TextView read = tv(m.optBoolean("read", false) ? "已读" : "未读", 8.5f, m.optBoolean("read", false) ? muted : accent, false);
                            read.setPadding(0, 0, dp(5), dp(4));
                            row.addView(read, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT, 0f));
                        }
                        LinearLayout bubbleBox = new LinearLayout(MainActivity.this);
                        bubbleBox.setOrientation(LinearLayout.VERTICAL);
                        bubbleBox.setPadding(dp(11), dp(8), dp(11), dp(7));
                        bubbleBox.setBackground(rounded(mine ? accent : card, 14, mine ? 0 : line));
                        TextView b = tv(m.optString("body", ""), 12.5f, mine ? Color.WHITE : ink, false);
                        b.setMaxWidth(dp(250));
                        bubbleBox.addView(b);
                        LinearLayout.LayoutParams bp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
                        bp.leftMargin = mine ? 0 : dp(4); bp.rightMargin = mine ? dp(4) : 0; bp.bottomMargin = dp(7);
                        row.addView(bubbleBox, bp);
                        list.addView(row);
                    }
                    JSONObject rd = new JSONObject();
                    try { rd.put("peer", peer); } catch (Exception ignored) {}
                    postAsync("/api/messages/read", rd, new JsonCb() {
                        @Override public void ok(JSONObject x) { refreshBadge(); }
                        @Override public void fail(String m) {}
                    });
                }
                scroll.post(() -> scroll.fullScroll(View.FOCUS_DOWN));
            }
            @Override public void fail(String m) { list.removeAllViews(); list.addView(empty("读取失败：" + m)); }
        });
    }

    // ---------------- bottle (native Canvas) ----------------
    private void showBottle(JSONObject node) {
        if (node != null) currentProject = node;
        screen = "bottle";
        showLoading("正在打捞漂流瓶…");
        loadBottleState();
    }
    private void loadBottleState() {
        getAsync("/api/p/bottle/state", new JsonCb() {
            @Override public void ok(JSONObject j) {
                bottleRev = j.optInt("rev", 0);
                renderBottle(j.optJSONObject("data"));
            }
            @Override public void fail(String m) { err("漂流瓶读取失败：" + m); showHome(); }
        });
    }
    private void renderBottle(JSONObject data) {
        if (data == null) data = new JSONObject();
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(bg);
        LinearLayout header = topBar("时光漂流瓶", true, this::showHome);
        TextView refresh = action("⟳", this::loadBottleState);
        header.addView(refresh, new LinearLayout.LayoutParams(dp(38), dp(38)));
        root.addView(header);

        FrameLayout stage = new FrameLayout(this);
        bottleView = new BottleView(this);
        bottleView.setData(data.optJSONArray("bottles"), data.optJSONObject("layout"));
        bottleView.setListener(new BottleView.Listener() {
            @Override public void onTap(JSONObject bottle) { showBottleDetail(bottle); }
            @Override public void onMoved(Map<String, android.graphics.PointF> positions) { saveBottlePositions(positions); }
        });
        stage.addView(bottleView, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        TextView write = tv("＋ 写一瓶", 13, Color.WHITE, true);
        write.setGravity(Gravity.CENTER);
        write.setPadding(dp(16), 0, dp(16), 0);
        write.setBackground(rounded(accent, 23, 0));
        write.setElevation(dp(4));
        write.setOnClickListener(v -> showBottleCompose());
        FrameLayout.LayoutParams wp = new FrameLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, dp(46));
        wp.gravity = Gravity.BOTTOM | Gravity.END;
        wp.rightMargin = dp(18); wp.bottomMargin = dp(18);
        stage.addView(write, wp);
        root.addView(stage, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
        setRoot(root);
    }
    private void showBottleDetail(JSONObject b) {
        String from = b.optString("from", "");
        String to = b.optString("to", "");
        String openAt = b.optString("openAt", "");
        String msg = b.optString("message", "");
        boolean canOpen = b.optBoolean("canOpen", false);
        String text;
        if (msg.length() > 0) text = msg;
        else if (canOpen) text = "已到开启日。\n\n来自 " + from + " · 给 " + to + "\n开启日 " + openAt + "\n\n点“打开”收下这句话。";
        else text = "还没到开启日。\n\n来自 " + from + " · 给 " + to + "\n开启日 " + openAt;
        AlertDialog.Builder d = new AlertDialog.Builder(this);
        d.setTitle(msg.length() > 0 ? "来自 " + from + " 的漂流瓶" : "漂流瓶");
        d.setMessage(text);
        if (canOpen) {
            final String id = b.optString("id", "");
            d.setPositiveButton("打开", (dialog, which) -> openBottle(id));
        }
        d.setNegativeButton(msg.length() > 0 ? "收下这句话" : "先放着", null);
        styleDialog(d.show());
    }
    private void openBottle(String id) {
        JSONObject body = new JSONObject();
        try {
            body.put("action", "open");
            body.put("rev", bottleRev);
            JSONObject payload = new JSONObject();
            payload.put("id", id);
            body.put("payload", payload);
        } catch (Exception ignored) {}
        postAsync("/api/p/bottle/action", body, new JsonCb() {
            @Override public void ok(JSONObject j) {
                bottleRev = j.optInt("rev", bottleRev);
                renderBottle(j.optJSONObject("data"));
                refreshBadge();
            }
            @Override public void fail(String m) { err("打开失败：" + m); }
        });
    }
    private void showBottleCompose() {
        getAsync("/api/messages/threads", new JsonCb() {
            @Override public void ok(JSONObject j) {
                JSONArray arr = j.optJSONArray("users");
                final List<String> users = new ArrayList<>();
                String me = session == null ? "" : session.optString("user", "");
                if (arr != null) for (int i = 0; i < arr.length(); i++) {
                    String u = arr.optString(i);
                    if (u.length() > 0 && !u.equals(me)) users.add(u);
                }
                if (users.isEmpty()) { err("没有其他可收信的用户"); return; }
                showBottleComposeDialog(users);
            }
            @Override public void fail(String m) { err("读取用户失败：" + m); }
        });
    }
    private void showBottleComposeDialog(List<String> users) {
        LinearLayout form = new LinearLayout(this);
        form.setOrientation(LinearLayout.VERTICAL);
        form.setPadding(dp(18), dp(8), dp(18), dp(4));
        TextView toLabel = tv("收件人", 11, muted, false); form.addView(toLabel);
        Spinner to = new Spinner(this);
        ArrayAdapter<String> adapter = new ArrayAdapter<>(this, android.R.layout.simple_spinner_item, users);
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        to.setAdapter(adapter);
        form.addView(to, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(42)));
        TextView dateLabel = tv("开启日期", 11, muted, false); dateLabel.setPadding(0, dp(8), 0, 0); form.addView(dateLabel);
        final EditText date = field("YYYY-MM-DD", false);
        Calendar cal = Calendar.getInstance();
        cal.add(Calendar.YEAR, 1);
        final String[] picked = {new SimpleDateFormat("yyyy-MM-dd", Locale.US).format(cal.getTime())};
        date.setText(picked[0]);
        date.setFocusable(false);
        date.setOnClickListener(v -> {
            Calendar c = Calendar.getInstance();
            try { c.setTime(new SimpleDateFormat("yyyy-MM-dd", Locale.US).parse(picked[0])); } catch (Exception ignored) {}
            new DatePickerDialog(MainActivity.this, (view, year, month, day) -> {
                Calendar n = Calendar.getInstance();
                n.set(year, month, day);
                picked[0] = new SimpleDateFormat("yyyy-MM-dd", Locale.US).format(n.getTime());
                date.setText(picked[0]);
            }, c.get(Calendar.YEAR), c.get(Calendar.MONTH), c.get(Calendar.DAY_OF_MONTH)).show();
        });
        form.addView(date, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(44)));
        TextView msgLabel = tv("瓶中信", 11, muted, false); msgLabel.setPadding(0, dp(8), 0, 0); form.addView(msgLabel);
        final EditText message = field("写点什么，封进瓶子…", false);
        message.setSingleLine(false);
        message.setMinLines(4);
        message.setMaxLines(7);
        message.setGravity(Gravity.TOP);
        message.setPadding(dp(10), dp(8), dp(10), dp(8));
        form.addView(message, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(110)));

        AlertDialog.Builder d = new AlertDialog.Builder(this);
        d.setTitle("写一瓶漂流瓶");
        d.setView(form);
        d.setNegativeButton("取消", null);
        d.setPositiveButton("封进瓶子", null);
        AlertDialog dialog = d.create();
        dialog.setOnShowListener(x -> dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
            String text = message.getText().toString().trim();
            if (text.length() == 0) { err("写点什么再封进瓶子吧"); return; }
            String peer = String.valueOf(to.getSelectedItem());
            JSONObject body = new JSONObject();
            try {
                body.put("action", "create");
                body.put("rev", bottleRev);
                JSONObject payload = new JSONObject();
                payload.put("to", peer); payload.put("message", text); payload.put("openAt", picked[0]);
                body.put("payload", payload);
            } catch (Exception ignored) {}
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setEnabled(false);
            postAsync("/api/p/bottle/action", body, new JsonCb() {
                @Override public void ok(JSONObject j) {
                    dialog.dismiss();
                    bottleRev = j.optInt("rev", bottleRev);
                    renderBottle(j.optJSONObject("data"));
                    refreshBadge();
                }
                @Override public void fail(String m) {
                    dialog.getButton(AlertDialog.BUTTON_POSITIVE).setEnabled(true);
                    err("封瓶失败：" + m);
                }
            });
        }));
        dialog.show();
        styleDialog(dialog);
    }
    private void styleDialog(AlertDialog d) {
        Window w = d.getWindow();
        if (w == null) return;
        w.setBackgroundDrawable(rounded(card, 20, line));
        w.setDimAmount(.42f);
        w.setLayout(Math.min(dp(420), getResources().getDisplayMetrics().widthPixels - dp(36)),
                WindowManager.LayoutParams.WRAP_CONTENT);
    }
    private void saveBottlePositions(Map<String, android.graphics.PointF> positions) {
        JSONObject clean = new JSONObject();
        try {
            for (Map.Entry<String, android.graphics.PointF> e : positions.entrySet()) {
                JSONObject p = new JSONObject();
                p.put("x", Math.round(e.getValue().x * 100000) / 100000.0);
                p.put("y", Math.round(e.getValue().y * 100000) / 100000.0);
                clean.put(e.getKey(), p);
            }
            JSONObject body = new JSONObject();
            body.put("action", "save_positions");
            body.put("rev", bottleRev);
            JSONObject payload = new JSONObject();
            payload.put("positions", clean);
            body.put("payload", payload);
            postAsync("/api/p/bottle/action", body, new JsonCb() {
                @Override public void ok(JSONObject j) { bottleRev = j.optInt("rev", bottleRev); }
                @Override public void fail(String m) {}
            });
        } catch (Exception ignored) {}
    }

    // ---------------- settings ----------------
    private void showSettings() {
        screen = "settings";
        String[] items = {"个人资料", "主题外观", "服务器", "关于"};
        KpPopup popup = new KpPopup(this, "设置", items, 0, (p, index) -> settingsPane(p, index),
                bg, card, ink, muted, line, accent, soft);
        popup.show();
    }
    private View settingsPane(KpPopup popup, int index) {
        ScrollView scroll = new ScrollView(this);
        LinearLayout body = new LinearLayout(this);
        body.setOrientation(LinearLayout.VERTICAL);
        body.setPadding(0, 0, 0, dp(12));
        TextView head = tv(index == 0 ? "个人资料" : index == 1 ? "主题外观" : index == 2 ? "服务器" : "关于", 17, ink, true);
        head.setPadding(0, 0, dp(44), dp(14));
        body.addView(head);

        if (index == 0) {
            LinearLayout userCard = new LinearLayout(this);
            userCard.setOrientation(LinearLayout.VERTICAL);
            userCard.setPadding(dp(16), dp(14), dp(16), dp(14));
            userCard.setBackground(rounded(mix(card, bg, .45f), 16, line));
            String emoji = session == null ? "🐱" : session.optString("emoji", "🐱");
            String user = session == null ? "" : session.optString("user", "");
            userCard.addView(tv(emoji + "  " + user, 19, ink, true));
            TextView role = tv((session == null ? "" : session.optString("role_label", "")) + " · 原生客户端", 11, muted, false);
            role.setPadding(0, dp(4), 0, 0);
            userCard.addView(role);
            body.addView(userCard);
            TextView hint = tv("账号、会话和消息数据与网页端共享同一个后端。", 11, muted, false);
            hint.setLineSpacing(0, 1.5f);
            hint.setPadding(0, dp(12), 0, 0);
            body.addView(hint);
            TextView logout = pill("退出登录", RED, false);
            logout.setOnClickListener(v -> { popup.dismiss(); clearSession(); showLogin(); });
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, dp(40));
            lp.topMargin = dp(22);
            body.addView(logout, lp);
        } else if (index == 1) {
            TextView preview = tv("主题色", 11, muted, false);
            body.addView(preview);
            LinearLayout colors = new LinearLayout(this);
            colors.setOrientation(LinearLayout.HORIZONTAL);
            int[] cs = {accent, soft, mix(accent, Color.WHITE, .55f), mix(bg, accent, .15f)};
            for (int c : cs) {
                View dot = new View(this);
                GradientDrawable d = new GradientDrawable();
                d.setColor(c); d.setCornerRadius(dp(17)); d.setStroke(dp(2), card);
                dot.setBackground(d);
                LinearLayout.LayoutParams dlp = new LinearLayout.LayoutParams(dp(34), dp(34));
                dlp.rightMargin = dp(8);
                colors.addView(dot, dlp);
            }
            body.addView(colors, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, dp(40)));
            TextView info = tv("当前主题由后端主题对象下发，与网页端使用同一套 bg/card/line/ink/muted/accent/soft。后续在这里接主题切换，而不是在客户端硬编码。", 11.5f, muted, false);
            info.setLineSpacing(0, 1.5f);
            info.setPadding(0, dp(14), 0, 0);
            body.addView(info);
        } else if (index == 2) {
            TextView label = tv("后端地址", 11, ink, true);
            body.addView(label);
            EditText server = field("https://…", false);
            server.setText(api.base);
            server.setInputType(InputType.TYPE_TEXT_VARIATION_URI);
            linearAdd(body, server, dp(46), dp(5));
            TextView hint = tv("网页端和 App 共享同一个 Python 服务：/api 是后端，/static 与 /p 是前端页面。", 10.5f, muted, false);
            hint.setLineSpacing(0, 1.5f);
            hint.setPadding(0, dp(8), 0, dp(14));
            body.addView(hint);
            TextView save = pill("保存并重新连接", accent, true);
            save.setOnClickListener(v -> {
                String b = server.getText().toString().trim();
                if (b.length() == 0) return;
                api.base = b; prefs.edit().putString("base", b).apply();
                popup.dismiss(); loadBootstrap();
            });
            body.addView(save, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, dp(42)));
        } else {
            TextView version = tv("KittenPuppy4Ever native 0.4.0", 15, ink, true);
            body.addView(version);
            TextView info = tv("原生 Android 客户端\n后端：本机 Python / Tailscale Funnel\n前端模板：网页端 Popup / Drawer / Card\n无 WebView", 11.5f, muted, false);
            info.setLineSpacing(0, 1.7f);
            info.setPadding(0, dp(10), 0, 0);
            body.addView(info);
        }
        scroll.addView(body);
        return scroll;
    }
    private void linearAdd(LinearLayout parent, View child, int height, int top) {
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, height);
        lp.topMargin = top;
        parent.addView(child, lp);
    }
    private TextView pill(String label, int color, boolean filled) {
        TextView v = tv(label, 12, filled ? Color.WHITE : color, true);
        v.setGravity(Gravity.CENTER);
        v.setPadding(dp(16), 0, dp(16), 0);
        v.setBackground(rounded(filled ? color : mix(card, bg, .4f), 20, filled ? 0 : line));
        v.setClickable(true);
        return v;
    }
    private View wrapPanel(LinearLayout panel) {
        FrameLayout screen = new FrameLayout(this);
        screen.setBackground(screenBackground());
        int w = Math.min(dp(900), getResources().getDisplayMetrics().widthPixels - dp(16));
        int h = Math.min(dp(620), Math.round(getResources().getDisplayMetrics().heightPixels * .86f));
        FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(w, h);
        lp.gravity = Gravity.CENTER;
        screen.addView(panel, lp);
        return screen;
    }
}
