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

/** Edge drawer template: right-side drawer with nested full-cover sub-drawers. */
final class KpDrawer extends Dialog {
    interface Provider { View create(KpDrawer drawer); }

    private final Activity activity;
    private final int bg, card, ink, muted, line, accent, soft;
    private final boolean mobile;
    private final FrameLayout cardView;
    private final FrameLayout contentHost;
    private final LinearLayout buttonStack;
    private final String[] nestedTitles;
    private final String[] nestedIcons;
    private final Provider[] nestedProviders;
    private final FrameLayout[] nestedViews;
    private int openNested = -1;

    KpDrawer(Activity a, String nodeKey, String title, Provider provider,
             int bg, int card, int ink, int muted, int line, int accent, int soft) {
        super(a, android.R.style.Theme_Translucent_NoTitleBar);
        this.activity = a; this.bg = bg; this.card = card; this.ink = ink;
        this.muted = muted; this.line = line; this.accent = accent; this.soft = soft;
        mobile = a.getResources().getConfiguration().smallestScreenWidthDp <= 760;
        requestWindowFeature(Window.FEATURE_NO_TITLE);
        nestedTitles = new String[2]; nestedIcons = new String[2];
        nestedProviders = new Provider[2]; nestedViews = new FrameLayout[2];

        DisplayMetrics dm = a.getResources().getDisplayMetrics();
        int w = mobile ? dm.widthPixels : Math.round(dm.widthPixels * .25f);
        int top = dp(120);
        int bottom = dp(68);
        int right = mobile ? 0 : dp(14);

        FrameLayout root = new FrameLayout(a);
        cardView = new FrameLayout(a);
        GradientDrawable bgCard = new GradientDrawable();
        bgCard.setColor(card);
        bgCard.setCornerRadius(dp(30));
        bgCard.setStroke(dp(1), line);
        cardView.setBackground(bgCard);
        cardView.setElevation(dp(16));
        FrameLayout.LayoutParams cp = new FrameLayout.LayoutParams(w, ViewGroup.LayoutParams.MATCH_PARENT);
        cp.gravity = Gravity.END;
        cp.topMargin = top; cp.bottomMargin = bottom; cp.rightMargin = right;
        root.addView(cardView, cp);

        LinearLayout head = new LinearLayout(a);
        head.setOrientation(LinearLayout.HORIZONTAL);
        head.setGravity(Gravity.CENTER_VERTICAL);
        head.setPadding(dp(14), dp(10), dp(10), dp(8));
        TextView t = new TextView(a);
        t.setText(title); t.setTextSize(13); t.setTextColor(ink);
        t.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        head.addView(t, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        TextView close = closeButton();
        close.setOnClickListener(v -> dismiss());
        head.addView(close, new LinearLayout.LayoutParams(dp(36), dp(36)));
        cardView.addView(head, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(52)));

        contentHost = new FrameLayout(a);
        contentHost.setPadding(dp(14), dp(4), dp(14), dp(74));
        FrameLayout.LayoutParams chp = new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT);
        chp.topMargin = dp(52);
        cardView.addView(contentHost, chp);
        View content = provider == null ? null : provider.create(this);
        if (content != null) contentHost.addView(content, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        buttonStack = new LinearLayout(a);
        buttonStack.setOrientation(LinearLayout.VERTICAL);
        buttonStack.setGravity(Gravity.END);
        FrameLayout.LayoutParams bsp = new FrameLayout.LayoutParams(dp(44), ViewGroup.LayoutParams.WRAP_CONTENT);
        bsp.gravity = Gravity.BOTTOM | Gravity.END;
        bsp.rightMargin = dp(12); bsp.bottomMargin = dp(16);
        cardView.addView(buttonStack, bsp);
        clearWindow();
        setContentView(root);
    }

    void addNested(String title, String icon, Provider provider) {
        int index = -1;
        for (int i = 0; i < 2; i++) if (nestedTitles[i] == null) { index = i; break; }
        if (index < 0) return;
        nestedTitles[index] = title; nestedIcons[index] = icon; nestedProviders[index] = provider;
        TextView b = roundButton(icon);
        final int idx = index;
        b.setOnClickListener(v -> openNested(idx));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(dp(44), dp(44));
        lp.bottomMargin = dp(8);
        buttonStack.addView(b, lp);
        buttonStack.bringToFront();

        FrameLayout overlay = new FrameLayout(activity);
        GradientDrawable ob = new GradientDrawable();
        ob.setColor(card); ob.setCornerRadius(dp(30)); ob.setStroke(dp(1), line);
        overlay.setBackground(ob);
        overlay.setVisibility(View.GONE);
        LinearLayout header = new LinearLayout(activity);
        header.setOrientation(LinearLayout.HORIZONTAL);
        header.setGravity(Gravity.CENTER_VERTICAL);
        header.setPadding(dp(12), dp(8), dp(10), dp(8));
        TextView back = new TextView(activity);
        back.setText("←"); back.setTextSize(17); back.setTextColor(muted);
        back.setGravity(Gravity.CENTER);
        back.setClickable(true);
        back.setOnClickListener(v -> closeNested());
        header.addView(back, new LinearLayout.LayoutParams(dp(34), dp(34)));
        TextView tt = new TextView(activity);
        tt.setText(title); tt.setTextSize(13); tt.setTextColor(ink);
        tt.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        tt.setPadding(dp(8), 0, 0, 0);
        header.addView(tt, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        overlay.addView(header, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(50)));
        FrameLayout body = new FrameLayout(activity);
        body.setPadding(dp(14), dp(4), dp(14), dp(14));
        FrameLayout.LayoutParams bp = new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT);
        bp.topMargin = dp(50);
        overlay.addView(body, bp);
        View v = provider == null ? null : provider.create(this);
        if (v != null) body.addView(v, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        cardView.addView(overlay, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        nestedViews[index] = overlay;
    }

    private void openNested(int index) {
        if (nestedViews[index] == null) return;
        openNested = index;
        nestedViews[index].setVisibility(View.VISIBLE);
        nestedViews[index].setTranslationX(mobile ? cardView.getWidth() : dp(36));
        nestedViews[index].setAlpha(.4f);
        nestedViews[index].animate().translationX(0).alpha(1f).setDuration(200).start();
        nestedViews[index].bringToFront();
    }
    private void closeNested() {
        if (openNested < 0) return;
        FrameLayout v = nestedViews[openNested];
        v.animate().translationX(mobile ? cardView.getWidth() : dp(36)).alpha(.4f).setDuration(160)
                .withEndAction(() -> v.setVisibility(View.GONE)).start();
        openNested = -1;
    }

    private TextView closeButton() {
        TextView v = new TextView(activity);
        v.setText("×"); v.setTextSize(20); v.setTextColor(muted);
        v.setGravity(Gravity.CENTER);
        v.setClickable(true);
        return v;
    }
    private TextView roundButton(String icon) {
        TextView v = new TextView(activity);
        v.setText(icon); v.setTextSize(17); v.setTextColor(ink);
        v.setGravity(Gravity.CENTER);
        v.setBackground(rounded(mix(card, bg, .3f), 22, line));
        v.setClickable(true);
        return v;
    }
    private GradientDrawable rounded(int color, float radius, int stroke) {
        GradientDrawable g = new GradientDrawable();
        g.setColor(color); g.setCornerRadius(dp(radius));
        if (stroke != 0) g.setStroke(dp(1), stroke);
        return g;
    }
    private static int mix(int a, int b, float t) {
        return Color.argb(Math.round(Color.alpha(a) + (Color.alpha(b) - Color.alpha(a)) * t),
                Math.round(Color.red(a) + (Color.red(b) - Color.red(a)) * t),
                Math.round(Color.green(a) + (Color.green(b) - Color.green(a)) * t),
                Math.round(Color.blue(a) + (Color.blue(b) - Color.blue(a)) * t));
    }
    private void clearWindow() {
        Window win = getWindow();
        if (win == null) return;
        win.setBackgroundDrawableResource(android.R.color.transparent);
        win.addFlags(WindowManager.LayoutParams.FLAG_DIM_BEHIND);
        WindowManager.LayoutParams lp = win.getAttributes();
        lp.dimAmount = .12f;
        win.setAttributes(lp);
    }
    private int dp(float v) { return Math.round(v * activity.getResources().getDisplayMetrics().density); }
}
