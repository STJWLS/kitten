/*
 * Module page template tree.
 * Every manifest ui.template points at a node here; children inherit all parent
 * properties. Server injects window.__KP_TEMPLATE__ from project.json.
 */
(function () {
  var TREE = {
    "#module": {
      properties: {
        pageClasses: ["page", "module-page"],
        sectionClasses: ["section"],
        contentTemplate: "sections",
        pagePadding: "18px 20px 44px",
        pageMaxWidth: "1120px"
      }
    },
    "#module.game": {
      parent: "#module",
      properties: {
        pageClasses: ["module-game"],
        contentTemplate: "directory-list",
        contentId: "content"
      }
    }
  };
  function isObj(v) { return v && typeof v === "object" && !Array.isArray(v); }
  function merge(base, over) {
    var out = {};
    Object.keys(base || {}).forEach(function (k) { out[k] = base[k]; });
    Object.keys(over || {}).forEach(function (k) {
      if (Array.isArray(out[k]) && Array.isArray(over[k])) {
        out[k] = out[k].concat(over[k].filter(function (v) { return out[k].indexOf(v) < 0; }));
      } else if (isObj(out[k]) && isObj(over[k])) {
        out[k] = merge(out[k], over[k]);
      } else {
        out[k] = over[k];
      }
    });
    return out;
  }
  function resolve(id, seen) {
    seen = seen || {};
    if (!TREE[id]) throw new Error("unknown template: " + id);
    if (seen[id]) throw new Error("template cycle: " + id);
    seen[id] = true;
    var node = TREE[id];
    var base = node.parent ? resolve(node.parent, seen) : {};
    return merge(base, node.properties || {});
  }
  function apply() {
    var id = window.__KP_TEMPLATE__ || document.body.getAttribute("data-template") || "#module";
    try {
      var props = resolve(id);
      var main = document.querySelector("main.page");
      if (main) {
        (props.pageClasses || []).forEach(function (c) { main.classList.add(c); });
        main.setAttribute("data-template-resolved", id);
        if (props.contentId) main.setAttribute("data-content-id", props.contentId);
      }
      document.body.setAttribute("data-template", id);
      document.documentElement.setAttribute("data-template", id);
      window.KP_TEMPLATE_TREE = TREE;
      window.KP_TEMPLATE_RESOLVED = props;
    } catch (e) {
      window.KP_TEMPLATE_ERROR = e.message;
      if (window.console) console.warn("[kp-template-tree]", e.message);
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", apply);
  else apply();
})();
