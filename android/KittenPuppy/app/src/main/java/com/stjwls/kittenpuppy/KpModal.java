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

/** Leaf modal template (bug / birthday / confirm): centered, no drawer, tree radius. */
final class KpModal extends Dialog {
    interface Provider { View create(KpModal modal); }
    private final Activity activity;
    private final int card, ink, muted, line, accent;
    private final FrameLayout contentHost;

    KpModal(Activity a, String nodeKey, String title, Provider provider,
            int card, int ink, int muted, int line, int accent) {
        super(a, android.R.style.Theme_Translucent_NoTitleBar);
        activity = a; this.card = card; this.ink = ink; this.muted = muted; this.line = line; this.accent = accent;
        requestWindowFeature(Window.FEATURE_NO_TITLE);
        setCanceledOnTouchOutside(true);
        DisplayMetrics dm = a.getResources().getDisplayMetrics();
        int w = Math.min(dp(420), dm.widthPixels - dp(36));
        FrameLayout root = new FrameLayout(a);
        LinearLayout box = new LinearLayout(a);
        box.setOrientation(LinearLayout.VERTICAL);
        int radius = KpTemplate.radius(nodeKey);
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(card); bg.setCornerRadius(dp(radius)); bg.setStroke(dp(1), line);
        box.setBackground(bg);
        box.setElevation(dp(16));
        box.setPadding(dp(20), dp(16), dp(20), dp(14));

        LinearLayout head = new LinearLayout(a);
        head.setOrientation(LinearLayout.HORIZONTAL);
        head.setGravity(Gravity.CENTER_VERTICAL);
        TextView t = new TextView(a);
        t.setText(title); t.setTextSize(17); t.setTextColor(ink);
        t.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        head.addView(t, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        TextView close = new TextView(a);
        close.setText("✕"); close.setTextSize(15); close.setTextColor(muted);
        close.setGravity(Gravity.CENTER);
        close.setClickable(true);
        close.setOnClickListener(v -> dismiss());
        head.addView(close, new LinearLayout.LayoutParams(dp(44), dp(44)));
        box.addView(head);
        contentHost = new FrameLayout(a);
        contentHost.setPadding(0, dp(8), 0, 0);
        box.addView(contentHost, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        View c = provider == null ? null : provider.create(this);
        if (c != null) contentHost.addView(c, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(w, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.gravity = Gravity.CENTER;
        root.addView(box, lp);
        setContentView(root);
        Window win = getWindow();
        if (win != null) {
            win.setBackgroundDrawableResource(android.R.color.transparent);
            win.addFlags(WindowManager.LayoutParams.FLAG_DIM_BEHIND);
            WindowManager.LayoutParams wl = win.getAttributes();
            wl.dimAmount = .32f;
            win.setAttributes(wl);
        }
    }
    private int dp(float v) { return Math.round(v * activity.getResources().getDisplayMetrics().density); }
}
