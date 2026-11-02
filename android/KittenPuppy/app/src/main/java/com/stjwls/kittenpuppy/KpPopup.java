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
 * Native equivalent of the web Popup + nested Drawer template.
 *
 * Desktop: 900x620 max, R38 popup, left drawer 25% width / R30, drawer inset m=8.
 * Mobile (<=760dp): popup width = screen - 2m, drawer covers the popup, R0.
 * Content padding is 2m=16; close button is topmost at top-right.
 */
final class KpPopup extends Dialog {
    interface Provider { View create(KpPopup popup, int index); }

    private final Activity activity;
    private final int bg, card, ink, muted, line, accent, soft;
    private final int m;
    private final String[] items;
    private final Provider provider;
    private final FrameLayout cardView;
    private final LinearLayout drawer;
    private final FrameLayout contentHost;
    private final View close;
    private final boolean mobile;
    private int selected = 0;
    private boolean drawerOpen = true;
    private int drawerWidth;

    KpPopup(Activity a, String brand, String[] items, int initial, Provider provider,
            int bg, int card, int ink, int muted, int line, int accent, int soft) {
        super(a, android.R.style.Theme_Translucent_NoTitleBar);
        this.activity = a; this.items = items; this.provider = provider;
        this.bg = bg; this.card = card; this.ink = ink; this.muted = muted;
        this.line = line; this.accent = accent; this.soft = soft;
        this.m = dp(8);
        this.mobile = a.getResources().getConfiguration().smallestScreenWidthDp <= 760;
        requestWindowFeature(Window.FEATURE_NO_TITLE);
        setCanceledOnTouchOutside(true);

        DisplayMetrics dm = a.getResources().getDisplayMetrics();
        int w = Math.min(dp(900), dm.widthPixels - 2 * m);
        int h = Math.min(dp(620), Math.round(dm.heightPixels * .86f));
        drawerWidth = Math.max(dp(160), w / 4);

        FrameLayout root = new FrameLayout(a);
        cardView = new FrameLayout(a);
        GradientDrawable bgCard = new GradientDrawable();
        bgCard.setColor(card);
        bgCard.setCornerRadius(dp(mobile ? 30 : 38));
        bgCard.setStroke(dp(1), line);
        cardView.setBackground(bgCard);
        cardView.setElevation(dp(18));
        FrameLayout.LayoutParams cp = new FrameLayout.LayoutParams(w, h);
        cp.gravity = Gravity.CENTER;
        root.addView(cardView, cp);

        LinearLayout row = new LinearLayout(a);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setPadding(m, m, m, m);
        cardView.addView(row, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        drawer = new LinearLayout(a);
        drawer.setOrientation(LinearLayout.VERTICAL);
        GradientDrawable dbg = new GradientDrawable();
        dbg.setColor(mix(card, bg, .55f));
        dbg.setCornerRadius(dp(mobile ? 0 : 30));
        dbg.setStroke(dp(1), line);
        drawer.setBackground(dbg);
        drawer.setPadding(dp(8), dp(10), dp(8), dp(10));
        TextView mark = new TextView(a);
        mark.setText(brand);
        mark.setTextColor(ink); mark.setTextSize(13.5f);
        mark.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        mark.setPadding(dp(8), dp(6), dp(8), dp(10));
        drawer.addView(mark);
        LinearLayout drawerItems = new LinearLayout(a);
        drawerItems.setOrientation(LinearLayout.VERTICAL);
        for (int i = 0; i < items.length; i++) {
            final int idx = i;
            TextView item = new TextView(a);
            item.setText(items[i]);
            item.setTextSize(12.5f);
            item.setTextColor(ink);
            item.setGravity(Gravity.CENTER_VERTICAL);
            item.setPadding(dp(10), 0, dp(10), 0);
            item.setBackground(rounded(Color.TRANSPARENT, 9, 0));
            item.setClickable(true);
            item.setOnClickListener(v -> { select(idx); if (mobile) closeDrawer(); });
            LinearLayout.LayoutParams ip = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(40));
            ip.bottomMargin = dp(2);
            drawerItems.addView(item, ip);
        }
        drawer.addView(drawerItems, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
        if (!mobile) {
            LinearLayout.LayoutParams dp = new LinearLayout.LayoutParams(drawerWidth, ViewGroup.LayoutParams.MATCH_PARENT);
            dp.rightMargin = m;
            row.addView(drawer, dp);
        }

        contentHost = new FrameLayout(a);
        contentHost.setPadding(dp(mobile ? 56 : 16), dp(10), dp(16), dp(16));
        row.addView(contentHost, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1f));

        close = roundAction("✕", () -> dismiss());
        FrameLayout.LayoutParams clp = new FrameLayout.LayoutParams(dp(44), dp(44));
        clp.gravity = Gravity.TOP | Gravity.END;
        clp.topMargin = m; clp.rightMargin = m;
        cardView.addView(close, clp);
        close.bringToFront();

        // Mobile drawer is an overlay over the entire popup.
        if (mobile) {
            FrameLayout overlay = new FrameLayout(a);
            overlay.setBackground(rounded(mix(bg, Color.BLACK, .25f), 0, 0));
            overlay.setClickable(true);
            overlay.setOnClickListener(v -> closeDrawer());
            FrameLayout.LayoutParams op = new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT);
            overlay.addView(drawer, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
            cardView.addView(overlay, op);
            this.mobileOverlay = overlay;
            close.bringToFront();
            TextView toggle = roundAction("☰", this::openDrawer);
            FrameLayout.LayoutParams tp = new FrameLayout.LayoutParams(dp(44), dp(44));
            tp.gravity = Gravity.TOP | Gravity.START;
            tp.topMargin = m; tp.leftMargin = m;
            cardView.addView(toggle, tp);
        } else {
            this.mobileOverlay = null;
        }

        Window win = getWindow();
        if (win != null) {
            win.setBackgroundDrawableResource(android.R.color.transparent);
            win.addFlags(WindowManager.LayoutParams.FLAG_DIM_BEHIND);
            WindowManager.LayoutParams lp = win.getAttributes();
            lp.dimAmount = .32f;
            win.setAttributes(lp);
        }
        setContentView(root);
        if (mobile) setDrawerOpen(true);
        select(initial);
    }

    private final FrameLayout mobileOverlay; // helper field assigned above

    private void select(int index) {
        selected = Math.max(0, Math.min(items.length - 1, index));
        LinearLayout itemsBox = (LinearLayout) drawer.getChildAt(1);
        for (int i = 0; i < itemsBox.getChildCount(); i++) {
            TextView v = (TextView) itemsBox.getChildAt(i);
            boolean on = i == selected;
            v.setTextColor(on ? Color.WHITE : ink);
            v.setTypeface(null, on ? Typeface.BOLD : Typeface.NORMAL);
            v.setBackground(rounded(on ? accent : Color.TRANSPARENT, 9, 0));
        }
        contentHost.removeAllViews();
        View content = provider.create(this, selected);
        if (content != null) contentHost.addView(content, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
    }

    void selectTab(int index) { select(index); }
    void setContent(View content) {
        contentHost.removeAllViews();
        if (content != null) contentHost.addView(content, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
    }
    void setDrawerOpen(boolean open) {
        drawerOpen = open;
        if (mobileOverlay != null) {
            mobileOverlay.setVisibility(open ? View.VISIBLE : View.GONE);
        }
    }
    private void closeDrawer() { setDrawerOpen(false); }
    void openDrawer() { setDrawerOpen(true); }
    boolean isMobile() { return mobile; }
    int colorCard() { return card; }
    int colorInk() { return ink; }
    int colorMuted() { return muted; }
    int colorLine() { return line; }
    int colorAccent() { return accent; }

    private TextView roundAction(String text, Runnable click) {
        TextView v = new TextView(activity);
        v.setText(text); v.setTextSize(15); v.setTextColor(ink);
        v.setGravity(Gravity.CENTER);
        v.setBackground(rounded(Color.TRANSPARENT, 22, line));
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
    private static int mix(int a, int b, float t) {
        return Color.argb(
                Math.round(Color.alpha(a) + (Color.alpha(b) - Color.alpha(a)) * t),
                Math.round(Color.red(a) + (Color.red(b) - Color.red(a)) * t),
                Math.round(Color.green(a) + (Color.green(b) - Color.green(a)) * t),
                Math.round(Color.blue(a) + (Color.blue(b) - Color.blue(a)) * t));
    }
    private int dp(float v) { return Math.round(v * activity.getResources().getDisplayMetrics().density); }
}
