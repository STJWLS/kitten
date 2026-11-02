package com.stjwls.kittenpuppy;

import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;

/** Mirrors the web KP_POPUP_TREE / KP_DRAWER_KEYS radius algorithm. */
final class KpTemplate {
    static final int M = 8;
    static final int BUTTON = 44;

    static final Map<String, String> PARENT = new HashMap<>();
    static final Map<String, String[]> CHILDREN = new HashMap<>();
    static final Set<String> DRAWERS = new HashSet<>(Arrays.asList(
            "ai-drawer", "bottle-status-drawer", "debug",
            "settings-side-drawer", "settings-help-drawer",
            "manage-side-drawer", "mail-side-drawer"));
    static {
        PARENT.put("ai-drawer", "window");
        PARENT.put("bottle-status-drawer", "window");
        PARENT.put("debug", "window");
        PARENT.put("settings-popup", "window");
        PARENT.put("settings-side-drawer", "settings-popup");
        PARENT.put("settings-help-drawer", "settings-popup");
        PARENT.put("manage-popup", "window");
        PARENT.put("manage-side-drawer", "manage-popup");
        PARENT.put("bug-popup", "window");
        PARENT.put("birthday-popup", "window");
        PARENT.put("mail-popup", "window");
        PARENT.put("mail-side-drawer", "mail-popup");
        CHILDREN.put("window", new String[]{"ai-drawer", "bottle-status-drawer", "debug",
                "settings-popup", "manage-popup", "bug-popup", "birthday-popup", "mail-popup"});
        CHILDREN.put("settings-popup", new String[]{"settings-side-drawer", "settings-help-drawer"});
        CHILDREN.put("manage-popup", new String[]{"manage-side-drawer"});
        CHILDREN.put("mail-popup", new String[]{"mail-side-drawer"});
    }

    static int radius(String key) {
        if (DRAWERS.contains(key)) {
            String p = PARENT.get(key);
            return p != null && DRAWERS.contains(p) ? 0 : 22 + M;
        }
        String[] kids = CHILDREN.get(key);
        if (kids == null || kids.length == 0) return 22 + M;
        int max = 0;
        for (String k : kids) max = Math.max(max, radius(k));
        return M + max;
    }
    static int drawerRadius(String key) { return radius(key); }
    private KpTemplate() {}
}
