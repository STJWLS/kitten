# Native template layer

This mirrors the web template engine, not individual page content.

## Tree and radii

`KpTemplate` mirrors `KP_POPUP_TREE` / `KP_DRAWER_KEYS`:

- leaf popup: `22 + m = 30`
- non-drawer popup with drawer children: `8 + max(child radius) = 38`
- drawer inside drawer: `0`
- top-level drawer: `22 + m = 30`

Current nodes:

```text
settings-popup (R38)
├── settings-side-drawer (R30)
└── settings-help-drawer (R30, right)

mail-popup (R38)
└── mail-side-drawer (R30, left)
```

## Popup

- max 900×620dp, 86% screen height
- mobile width = screen - 2m
- radius from tree
- close 44dp, top-right, topmost
- dim behind

## Drawers

- desktop width 25% of popup
- inset m=8
- R30 (R0 when nested in a drawer)
- left/right variants
- bound toggle 44dp
- right drawer top = close bottom + m
- mobile full-cover, no radius, content padding 2m

## Content

- desktop padding 2m, plus open drawer width + 2m so content never sits under drawer
- mobile fixed 2m, drawer overlays content
- drawer toggle buttons are 44dp

## Still to add as native nodes

AI drawer, AI history/settings nested drawers, bottle status drawer, debug drawer, manage popup, bug popup, birthday popup. They can reuse `KpTemplate`/`KpPopup`; they are not page-specific templates.
