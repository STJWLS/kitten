package com.stjwls.kittenpuppy;

import android.app.Activity;
import android.app.Dialog;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.util.DisplayMetrics;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.view.WindowManager;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;

/**
 * Native Popup + Drawer template engine, mirroring web KP_POPUP_TREE rules.
 *
 * Desktop: popup max 900x620, radius by tree, left drawer 25%/R30 inset m,
 * right drawer top = close-bottom + m, content padding 2m (+ drawer width when open).
 * Mobile (<=760dp): popup width screen-2m, drawers full-cover R0, content padding 2m.
 */
final class KpPopup extends Dialog {
    interface Provider { View create(KpPopup popup, int index); }

    private final Activity activity;
    private final int bg, card, ink, muted, line, accent, soft;
    private final int m = KpTemplate.M;
    private final boolean mobile;
    private final String nodeKey;
    private final FrameLayout cardView;
    private final FrameLayout contentHost;

    private LinearLayout leftDrawer;
    private FrameLayout leftDrawerHost;
    private TextView leftToggle;
    private final String[] leftItems;
    private final Provider leftProvider;
    private final int leftW;
    private final int popupW, popupH;
    private int selected = 0;
    private boolean leftOpen = true;

    private LinearLayout rightDrawer;
    private FrameLayout rightDrawerHost;
    private TextView rightToggle;
    private final int rightW;
    private boolean rightOpen = false;

    KpPopup(Activity a, String nodeKey, String brand, String[] items, int initial,
            Provider provider, int bg, int card, int ink, int muted, int line, int accent, int soft) {
        super(a, android.R.style.Theme_Translucent_NoTitleBar);
        this.activity = a; this.nodeKey = nodeKey; this.leftItems = items;
        this.leftProvider = provider; this.bg = bg; this.card = card;
        this.ink = ink; this.muted = muted; this.line = line; this.accent = accent; this.soft = soft;
        this.mobile = a.getResources().getConfiguration().smallestScreenWidthDp <= 760;
        requestWindowFeature(Window.FEATURE_NO_TITLE);
        setCanceledOnTouchOutside(true);

        DisplayMetrics dm = a.getResources().getDisplayMetrics();
        popupW = Math.min(dp(900), dm.widthPixels - 2 * m);
        popupH = Math.min(dp(620), Math.round(dm.heightPixels * .86f));
        leftW = Math.max(dp(160), popupW / 4);
        rightW = Math.max(dp(160), popupW / 4);

        FrameLayout root = new FrameLayout(a);
        cardView = new FrameLayout(a);
        int radius = mobile ? Math.min(30, KpTemplate.radius(nodeKey)) : KpTemplate.radius(nodeKey);
        GradientDrawable cardBg = new GradientDrawable();
        cardBg.setColor(card); cardBg.setCornerRadius(dp(radius)); cardBg.setStroke(dp(1), line);
        cardView.setBackground(cardBg);
        cardView.setElevation(dp(18));
        FrameLayout.LayoutParams cp = new FrameLayout.LayoutParams(popupW, popupH);
        cp.gravity = Gravity.CENTER;
        root.addView(cardView, cp);

        contentHost = new FrameLayout(a);
        cardView.addView(contentHost, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        leftDrawer = buildLeftDrawer(brand, items);
        FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(mobile ? ViewGroup.LayoutParams.MATCH_PARENT : leftW,
                ViewGroup.LayoutParams.MATCH_PARENT);
        if (mobile) { lp.leftMargin = 0; lp.topMargin = 0; lp.bottomMargin = 0; }
        else { lp.leftMargin = m; lp.topMargin = m; lp.bottomMargin = m; }
        cardView.addView(leftDrawer, lp);

        close = roundAction("✕", this::dismiss);
        FrameLayout.LayoutParams clp = new FrameLayout.LayoutParams(dp(44), dp(44));
        clp.gravity = Gravity.TOP | Gravity.END;
        clp.topMargin = m; clp.rightMargin = m;
        cardView.addView(close, clp);
        close.bringToFront();

        leftToggle = roundAction("←", this::toggleLeft);
        FrameLayout.LayoutParams ltp = new FrameLayout.LayoutParams(dp(44), dp(44));
        ltp.gravity = Gravity.BOTTOM | Gravity.START;
        ltp.leftMargin = m; ltp.bottomMargin = m;
        cardView.addView(leftToggle, ltp);

        updateInsets();
        setContentView(root);
        select(initial);
        syncToggles();
        clearWindowBackground();
    }

    private final View close;

    private LinearLayout buildLeftDrawer(String brand, String[] items) {
        LinearLayout drawer = drawerBox(brand, KpTemplate.drawerRadius("settings-side-drawer"));
        LinearLayout box = new LinearLayout(activity);
        box.setOrientation(LinearLayout.VERTICAL);
        for (int i = 0; i < items.length; i++) {
            final int idx = i;
            TextView item = new TextView(activity);
            item.setText(items[i]);
            item.setTextSize(12.5f);
            item.setTextColor(ink);
            item.setGravity(Gravity.CENTER_VERTICAL);
            item.setPadding(dp(10), 0, dp(10), 0);
            item.setBackground(rounded(Color.TRANSPARENT, 9, 0));
            item.setClickable(true);
            item.setOnClickListener(v -> { select(idx); if (mobile) setLeftOpen(false); });
            LinearLayout.LayoutParams ip = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(40));
            ip.bottomMargin = dp(2);
            box.addView(item, ip);
        }
        drawer.addView(box, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
        return drawer;
    }

    private LinearLayout drawerBox(String title, int radius) {
        LinearLayout drawer = new LinearLayout(activity);
        drawer.setOrientation(LinearLayout.VERTICAL);
        GradientDrawable dbg = new GradientDrawable();
        dbg.setColor(mix(card, bg, .55f));
        dbg.setCornerRadius(dp(radius));
        dbg.setStroke(dp(1), line);
        drawer.setBackground(dbg);
        drawer.setPadding(dp(8), dp(10), dp(8), dp(10));
        TextView mark = new TextView(activity);
        mark.setText(title);
        mark.setTextColor(ink); mark.setTextSize(13.5f);
        mark.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        mark.setPadding(dp(8), dp(6), dp(8), dp(10));
        drawer.addView(mark);
        return drawer;
    }

    /** Optional right-side drawer; its content is independent from the main content. */
    void addRightDrawer(String title, Provider provider) {
        rightDrawer = drawerBox(title, KpTemplate.drawerRadius("settings-help-drawer"));
        rightDrawerHost = new FrameLayout(activity);
        rightDrawerHost.setPadding(dp(2), dp(2), dp(2), dp(2));
        rightDrawer.addView(rightDrawerHost, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
        FrameLayout.LayoutParams rp = new FrameLayout.LayoutParams(mobile ? ViewGroup.LayoutParams.MATCH_PARENT : rightW,
                ViewGroup.LayoutParams.MATCH_PARENT);
        if (mobile) { rp.leftMargin = 0; rp.topMargin = 0; rp.bottomMargin = 0; }
        else {
            rp.gravity = Gravity.END;
            rp.rightMargin = m;
            rp.topMargin = m + dp(44) + m; // close bottom + m
            rp.bottomMargin = m;
        }
        cardView.addView(rightDrawer, rp);
        rightDrawer.setVisibility(View.GONE);
        close.bringToFront();

        rightToggle = roundAction("?", this::toggleRight);
        FrameLayout.LayoutParams rtp = new FrameLayout.LayoutParams(dp(44), dp(44));
        rtp.gravity = Gravity.BOTTOM | Gravity.END;
        rtp.rightMargin = m; rtp.bottomMargin = m;
        cardView.addView(rightToggle, rtp);
        rightToggle.bringToFront();
        rightDrawer.setTag(provider);
        if (provider != null) {
            View v = provider.create(this, 0);
            if (v != null) rightDrawerHost.addView(v, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        }
        syncToggles();
    }

    private void select(int index) {
        selected = Math.max(0, Math.min(leftItems.length - 1, index));
        LinearLayout itemsBox = (LinearLayout) leftDrawer.getChildAt(1);
        for (int i = 0; i < itemsBox.getChildCount(); i++) {
            TextView v = (TextView) itemsBox.getChildAt(i);
            boolean on = i == selected;
            v.setTextColor(on ? Color.WHITE : ink);
            v.setTypeface(null, on ? Typeface.BOLD : Typeface.NORMAL);
            v.setBackground(rounded(on ? accent : Color.TRANSPARENT, 9, 0));
        }
        contentHost.removeAllViews();
        View content = leftProvider.create(this, selected);
        if (content != null) contentHost.addView(content, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
    }

    private void toggleLeft() { setLeftOpen(!leftOpen); }
    private void setLeftOpen(boolean open) {
        leftOpen = open;
        leftDrawer.setVisibility(open ? View.VISIBLE : View.GONE);
        updateInsets();
        syncToggles();
    }
    private void toggleRight() { setRightOpen(!rightOpen); }
    private void setRightOpen(boolean open) {
        if (rightDrawer == null) return;
        rightOpen = open;
        rightDrawer.setVisibility(open ? View.VISIBLE : View.GONE);
        if (rightDrawerHost != null && rightDrawerHost.getChildCount() == 0) {
            Object tag = rightDrawer.getTag();
            if (tag instanceof Provider) {
                View v = ((Provider) tag).create(this, 0);
                if (v != null) rightDrawerHost.addView(v, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
            }
        }
        updateInsets();
        syncToggles();
    }
    private void updateInsets() {
        int l = dp(16), r = dp(16);
        if (!mobile) {
            if (leftOpen) l += leftW + 2 * m;
            if (rightOpen) r += rightW + 2 * m;
        }
        contentHost.setPadding(l, dp(16), r, dp(16));
    }
    private void syncToggles() {
        if (leftToggle != null) leftToggle.setText(leftOpen ? "←" : "☰");
        if (rightToggle != null) rightToggle.setText(rightOpen ? "→" : "?");
        if (close != null) close.bringToFront();
        if (leftToggle != null) leftToggle.bringToFront();
        if (rightToggle != null) rightToggle.bringToFront();
    }

    void selectTab(int index) { select(index); }
    void setContent(View content) {
        contentHost.removeAllViews();
        if (content != null) contentHost.addView(content, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
    }
    void openDrawer() { setLeftOpen(true); }
    boolean isMobile() { return mobile; }

    private TextView roundAction(String text, Runnable click) {
        TextView v = new TextView(activity);
        v.setText(text); v.setTextSize(15); v.setTextColor(ink);
        v.setGravity(Gravity.CENTER);
        v.setBackground(rounded(mix(card, bg, .35f), 22, line));
        v.setClickable(true);
        v.setOnClickListener(x -> click.run());
        return v;
    }
    private GradientDrawable rounded(int color, float radius, int stroke) {
        GradientDrawable g = new GradientDrawable();
        g.setColor(color); g.setCornerRadius(dp(radius));
        if (stroke != 0) g.setStroke(dp(1), stroke);
        return g;
    }
    private void clearWindowBackground() {
        Window win = getWindow();
        if (win == null) return;
        win.setBackgroundDrawableResource(android.R.color.transparent);
        win.addFlags(WindowManager.LayoutParams.FLAG_DIM_BEHIND);
        WindowManager.LayoutParams lp = win.getAttributes();
        lp.dimAmount = .32f;
        win.setAttributes(lp);
    }
    private static int mix(int a, int b, float t) {
        return Color.argb(Math.round(Color.alpha(a) + (Color.alpha(b) - Color.alpha(a)) * t),
                Math.round(Color.red(a) + (Color.red(b) - Color.red(a)) * t),
                Math.round(Color.green(a) + (Color.green(b) - Color.green(a)) * t),
                Math.round(Color.blue(a) + (Color.blue(b) - Color.blue(a)) * t));
    }
    private int dp(float v) { return Math.round(v * activity.getResources().getDisplayMetrics().density); }
}
