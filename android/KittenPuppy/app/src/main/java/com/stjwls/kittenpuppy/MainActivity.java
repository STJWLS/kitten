package com.stjwls.kittenpuppy;

import android.app.Activity;
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
import android.view.inputmethod.InputMethodManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.List;
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

    @Override protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        api.base = prefs.getString("base", DEFAULT_BASE);
        api.token = prefs.getString("token", "");
        applyTheme(null);
        if (api.token != null && api.token.length() > 0) loadBootstrap(); else showLogin();
    }

    @Override public void onBackPressed() {
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
    private void setRoot(View view) {
        setContentView(view);
        View root = view;
        root.setBackgroundColor(bg);
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
        ScrollView scroll = new ScrollView(this);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(24), dp(42), dp(24), dp(30));
        root.setBackgroundColor(bg);

        TextView logo = tv("🐱🐶", 38, ink, false);
        root.addView(logo);
        TextView title = tv("KittenPuppy4Ever", 27, ink, true);
        title.setPadding(0, dp(12), 0, 0);
        root.addView(title);
        TextView sub = tv("原生客户端 · 第一阶段", 12, muted, false);
        sub.setPadding(0, dp(4), 0, dp(26));
        root.addView(sub);

        TextView serverLabel = tv("服务器", 12, ink, true);
        root.addView(serverLabel, lp(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT, 0));
        EditText server = field("https://02f5c6734009.tail4ba04e.ts.net", false);
        server.setText(prefs.getString("base", DEFAULT_BASE));
        server.setInputType(InputType.TYPE_TEXT_VARIATION_URI);
        root.addView(server, lp(LinearLayout.LayoutParams.MATCH_PARENT, dp(48), 6));

        TextView userLabel = tv("账号", 12, ink, true);
        root.addView(userLabel, lp(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT, 0));
        LinearLayout roles = new LinearLayout(this);
        roles.setOrientation(LinearLayout.HORIZONTAL);
        TextView kitten = chip("🐱 kitten", true);
        TextView puppy = chip("🐶 puppy", false);
        roles.addView(kitten, new LinearLayout.LayoutParams(0, dp(38), 1));
        LinearLayout.LayoutParams rp = new LinearLayout.LayoutParams(0, dp(38), 1);
        rp.leftMargin = dp(8);
        roles.addView(puppy, rp);
        root.addView(roles, lp(LinearLayout.LayoutParams.MATCH_PARENT, dp(38), 6));
        EditText user = field("kitten", false);
        user.setText(prefs.getString("user", "kitten"));
        root.addView(user, lp(LinearLayout.LayoutParams.MATCH_PARENT, dp(48), 6));

        TextView pwdLabel = tv("口令", 12, ink, true);
        root.addView(pwdLabel, lp(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT, 0));
        EditText pwd = field("输入登录口令", true);
        root.addView(pwd, lp(LinearLayout.LayoutParams.MATCH_PARENT, dp(48), 6));

        Button go = new Button(this);
        go.setText("登 录");
        go.setTextColor(Color.WHITE);
        go.setTextSize(14);
        go.setAllCaps(false);
        go.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        go.setBackground(rounded(accent, 24, 0));
        root.addView(go, lp(LinearLayout.LayoutParams.MATCH_PARENT, dp(48), 6));

        TextView status = tv("登录后会自动读取工作台与主题。", 11, muted, false);
        status.setPadding(0, dp(10), 0, 0);
        root.addView(status);

        kitten.setOnClickListener(v -> user.setText("kitten"));
        puppy.setOnClickListener(v -> user.setText("puppy"));
        go.setOnClickListener(v -> {
            String b = server.getText().toString().trim();
            String u = user.getText().toString().trim();
            String p = pwd.getText().toString();
            if (b.length() == 0 || u.length() == 0 || p.length() == 0) { status.setText("请填写服务器、账号和口令"); return; }
            hideKeyboard();
            go.setEnabled(false); go.setText("登录中…"); status.setText("正在连接服务器…");
            api.base = b;
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

        scroll.addView(root);
        setRoot(scroll);
        pwd.requestFocus();
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
        header.setPadding(dp(16), dp(12), dp(14), dp(8));

        LinearLayout brandBox = new LinearLayout(this);
        brandBox.setOrientation(LinearLayout.VERTICAL);
        TextView brand = tv("🐱🐶 KittenPuppy4Ever", 17, ink, true);
        TextView who = tv(session == null ? "" : "已登录：" + session.optString("emoji", "") + " " + session.optString("user", ""), 10, muted, false);
        brandBox.addView(brand);
        brandBox.addView(who);
        header.addView(brandBox, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));

        final TextView mail = action("✉", () -> { hideKeyboard(); showMessages(); });
        FrameLayout mailWrap = new FrameLayout(this);
        mailWrap.addView(mail, new FrameLayout.LayoutParams(dp(40), dp(40)));
        homeMailBadge = tv("0", 8.5f, Color.WHITE, true);
        homeMailBadge.setGravity(Gravity.CENTER);
        homeMailBadge.setBackground(rounded(RED, 8, 0));
        homeMailBadge.setVisibility(View.GONE);
        FrameLayout.LayoutParams bp = new FrameLayout.LayoutParams(dp(16), dp(16));
        bp.gravity = Gravity.TOP | Gravity.RIGHT;
        mailWrap.addView(homeMailBadge, bp);
        LinearLayout.LayoutParams mw = new LinearLayout.LayoutParams(dp(44), dp(40));
        mw.leftMargin = dp(6);
        header.addView(mailWrap, mw);

        TextView settings = action("⚙", this::showSettings);
        LinearLayout.LayoutParams sw = new LinearLayout.LayoutParams(dp(40), dp(40));
        sw.leftMargin = dp(6);
        header.addView(settings, sw);
        root.addView(header);

        ScrollView scroll = new ScrollView(this);
        LinearLayout body = new LinearLayout(this);
        body.setOrientation(LinearLayout.VERTICAL);
        body.setPadding(dp(16), dp(10), dp(16), dp(28));

        String user = session == null ? "" : session.optString("user", "");
        String emoji = session == null ? "" : session.optString("emoji", "");
        TextView hello = tv("你好，" + emoji + " " + user, 24, ink, true);
        body.addView(hello);
        TextView hint = tv("在这里继续你的日常。原生客户端第一阶段：账号、主题、卡片、路由、消息与设置。", 11.5f, muted, false);
        hint.setPadding(0, dp(6), 0, dp(16));
        body.addView(hint);

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
        cardBox.setOrientation(LinearLayout.HORIZONTAL);
        cardBox.setGravity(Gravity.CENTER_VERTICAL);
        cardBox.setPadding(dp(14), dp(14), dp(14), dp(14));
        cardBox.setBackground(rounded(card, 18, line));
        cardBox.setElevation(dp(2));
        cardBox.setClickable(true);
        cardBox.setOnClickListener(v -> showProject(node));
        TextView icon = tv(node.optString("icon", "📄"), 28, ink, false);
        cardBox.addView(icon, new LinearLayout.LayoutParams(dp(46), dp(46)));
        LinearLayout texts = new LinearLayout(this);
        texts.setOrientation(LinearLayout.VERTICAL);
        texts.setPadding(dp(11), 0, 0, 0);
        TextView title = tv(node.optString("title", "未命名"), 15, ink, true);
        texts.addView(title);
        TextView desc = tv(node.optString("desc", ""), 10.5f, muted, false);
        desc.setMaxLines(3);
        desc.setPadding(0, dp(3), 0, 0);
        texts.addView(desc);
        String tags = "";
        JSONArray ta = node.optJSONArray("tags");
        if (ta != null) for (int i = 0; i < Math.min(4, ta.length()); i++) tags += (i == 0 ? "" : "  ") + "#" + ta.optString(i);
        if (tags.length() > 0) {
            TextView tag = tv(tags, 9.5f, accent, false);
            tag.setPadding(0, dp(5), 0, 0);
            texts.addView(tag);
        }
        cardBox.addView(texts, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        TextView arrow = tv("›", 24, muted, false);
        cardBox.addView(arrow);
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        p.bottomMargin = dp(10);
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
        if (back) {
            TextView b = action("←", backAction);
            header.addView(b, new LinearLayout.LayoutParams(dp(38), dp(38)));
        }
        TextView t = tv(title, 16, ink, true);
        t.setPadding(back ? dp(10) : 0, 0, 0, 0);
        header.addView(t, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        return header;
    }

    // ---------------- messages ----------------
    private void showMessages() { showMessages(messagesTab); }
    private void showMessages(int tab) {
        screen = "messages"; messagesTab = tab;
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(bg);
        root.addView(topBar("消息", true, this::showHome));

        LinearLayout tabs = new LinearLayout(this);
        tabs.setOrientation(LinearLayout.HORIZONTAL);
        tabs.setPadding(dp(16), 0, dp(16), dp(8));
        TextView notice = tabChip("通知", tab == 0);
        TextView dm = tabChip("私信", tab == 1);
        tabs.addView(notice, new LinearLayout.LayoutParams(0, dp(36), 1));
        LinearLayout.LayoutParams dp2 = new LinearLayout.LayoutParams(0, dp(36), 1); dp2.leftMargin = dp(8);
        tabs.addView(dm, dp2);
        notice.setOnClickListener(v -> showMessages(0));
        dm.setOnClickListener(v -> showMessages(1));
        root.addView(tabs);

        LinearLayout actions = new LinearLayout(this);
        actions.setOrientation(LinearLayout.HORIZONTAL);
        actions.setGravity(Gravity.END);
        actions.setPadding(dp(16), 0, dp(16), dp(6));
        TextView readAll = smallButton("全部已读");
        readAll.setOnClickListener(v -> markAllRead());
        actions.addView(readAll);
        root.addView(actions);

        ScrollView scroll = new ScrollView(this);
        LinearLayout list = new LinearLayout(this);
        list.setOrientation(LinearLayout.VERTICAL);
        list.setPadding(dp(16), dp(4), dp(16), dp(24));
        scroll.addView(list);
        root.addView(scroll, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
        setRoot(root);
        loadMessages(list, tab);
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

    // ---------------- settings ----------------
    private void showSettings() {
        screen = "settings";
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(bg);
        root.addView(topBar("设置", true, this::showHome));
        ScrollView scroll = new ScrollView(this);
        LinearLayout body = new LinearLayout(this);
        body.setOrientation(LinearLayout.VERTICAL);
        body.setPadding(dp(18), dp(8), dp(18), dp(28));

        LinearLayout cardBox = new LinearLayout(this);
        cardBox.setOrientation(LinearLayout.VERTICAL);
        cardBox.setPadding(dp(16), dp(14), dp(16), dp(14));
        cardBox.setBackground(rounded(card, 16, line));
        String emoji = session == null ? "🐱" : session.optString("emoji", "🐱");
        String user = session == null ? "" : session.optString("user", "");
        TextView who = tv(emoji + "  " + user, 19, ink, true);
        cardBox.addView(who);
        TextView role = tv((session == null ? "" : session.optString("role_label", "")) + " · 原生客户端", 11, muted, false);
        role.setPadding(0, dp(4), 0, 0);
        cardBox.addView(role);
        body.addView(cardBox, lp(LinearLayout.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT, 6));

        TextView serverLabel = tv("后端地址", 12, ink, true);
        serverLabel.setPadding(0, dp(16), 0, dp(5));
        body.addView(serverLabel);
        EditText server = field("http://10.0.2.2:8772", false);
        server.setText(api.base);
        body.addView(server, lp(LinearLayout.LayoutParams.MATCH_PARENT, dp(46), 4));
        TextView save = smallButton("保存并重新连接");
        save.setOnClickListener(v -> {
            String b = server.getText().toString().trim();
            if (b.length() == 0) return;
            api.base = b; prefs.edit().putString("base", b).apply(); loadBootstrap();
        });
        body.addView(save, lp(LinearLayout.LayoutParams.WRAP_CONTENT, dp(38), 4));

        TextView colorLabel = tv("当前主题", 12, ink, true);
        colorLabel.setPadding(0, dp(18), 0, dp(8));
        body.addView(colorLabel);
        TextView slash = tv("■ " + String.format("#%06X", (0xFFFFFF & accent)), 13, accent, true);
        body.addView(slash);

        TextView logout = smallButton("退出登录");
        logout.setTextColor(RED);
        logout.setOnClickListener(v -> { clearSession(); showLogin(); });
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, dp(38));
        lp.topMargin = dp(24);
        body.addView(logout, lp);
        TextView version = tv("KittenPuppy4Ever native · 0.1.0 · phase 1", 10, muted, false);
        version.setPadding(0, dp(18), 0, 0);
        body.addView(version);
        scroll.addView(body);
        root.addView(scroll, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
        setRoot(root);
    }
}
