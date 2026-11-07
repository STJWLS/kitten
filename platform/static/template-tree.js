/*
 * Module page template tree loader.
 *
 * The authoritative tree is /static/template-tree.json:
 *   #module
 *   └── #game  -> selected as "#module.game"
 *
 * Child nodes inherit all parent properties. Arrays are concatenated with
 * de-duplication, objects are merged recursively, scalars are overridden.
 */
(function () {
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
  function fullPath(parentPath, nodeId) {
    var id = String(nodeId || "").replace(/^#/, "");
    if (!parentPath) return "#" + id;
    return parentPath + "." + id;
  }
  function flatten(node, parentPath, parentProps, out) {
    if (!node || !node.id) throw new Error("template node missing id at " + (parentPath || "root"));
    var path = fullPath(parentPath, node.id);
    if (out[path]) throw new Error("duplicate template: " + path);
    var props = merge(parentProps || {}, node.properties || {});
    out[path] = { id: path, shortId: node.id, properties: props };
    (node.children || []).forEach(function (child) {
      flatten(child, path, props, out);
    });
  }
  function apply(props, id) {
    var main = document.querySelector("main.page");
    if (main) {
      (props.pageClasses || []).forEach(function (c) { main.classList.add(c); });
      main.setAttribute("data-template-resolved", id);
      if (props.contentId) main.setAttribute("data-content-id", props.contentId);
    }
    document.body.setAttribute("data-template", id);
    document.documentElement.setAttribute("data-template", id);
    window.KP_TEMPLATE_RESOLVED = props;
  }
  function boot() {
    fetch("/static/template-tree.json", {cache: "no-store"})
      .then(function (r) { if (!r.ok) throw new Error("template tree HTTP " + r.status); return r.json(); })
      .then(function (tree) {
        var nodes = {};
        flatten(tree.root, "", {}, nodes);
        window.KP_TEMPLATE_TREE = nodes;
        var id = window.__KP_TEMPLATE__ || document.body.getAttribute("data-template") || "#module";
        if (!nodes[id]) throw new Error("unknown template: " + id);
        apply(nodes[id].properties, id);
      })
      .catch(function (e) {
        window.KP_TEMPLATE_ERROR = e.message;
        if (window.console) console.warn("[kp-template-tree]", e.message);
      });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
