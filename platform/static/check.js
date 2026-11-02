
(function () {
  try {
    var u = localStorage.getItem("kp_login_user") || sessionStorage.getItem("kp_login_user");
    var t = u && JSON.parse(localStorage.getItem("kp_pubtheme_" + u) || "null");
    if (!t || !t.accent) return;
    var vars = {"--accent": t.accent, "--pink": t.soft, "--pink-deep": t.deep, "--mint": t.mint,
      "--bg": t.bg, "--card": t.card, "--line": t.line, "--ink": t.ink, "--p-accent": t.deep};
    for (var k in vars) if (vars[k]) document.documentElement.style.setProperty(k, vars[k]);
    fetch("/api/public-theme?user=" + encodeURIComponent(u), {cache: "no-store"})
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (!j || !j.ok || !j.theme) return;
        var t2 = j.theme, vs = {"--accent": t2.accent, "--pink": t2.soft, "--pink-deep": t2.deep,
          "--mint": t2.mint, "--bg": t2.bg, "--card": t2.card, "--line": t2.line, "--ink": t2.ink, "--p-accent": t2.deep};
        for (var k2 in vs) if (vs[k2]) document.documentElement.style.setProperty(k2, vs[k2]);
      }).catch(function () {});
  } catch (e) {}
})();


(function () {
  try {
    var u = localStorage.getItem("kp_login_user") || "kitten";
    var t = JSON.parse(localStorage.getItem("kp_pubtheme_" + u) || "null");
    if (!t || !t.accent) return;
    var s = document.documentElement.style;
    var v = {"--accent": t.accent, "--pink": t.soft, "--pink-deep": t.deep, "--mint": t.mint,
      "--accent-weak": t.soft, "--bg": t.bg, "--card": t.card, "--line": t.line,
      "--ink": t.ink, "--p-accent": t.deep};
    for (var k in v) if (v[k]) s.setProperty(k, v[k]);
    (t.tone || []).forEach(function (x) { s.setProperty("--" + x.name, x.color); });
    (t.ramp || []).forEach(function (c, i) { s.setProperty("--kp-ramp-" + i, c); });
    document.documentElement.setAttribute("data-pretheme", "1");
  } catch (e) {}
  // 空闲时再预取初始用户主题，避免和首屏 bootstrap 抢带宽
  try {
    var warm = function () {
      ["kitten", "puppy"].forEach(function (u) {
        fetch("/api/public-theme?user=" + u, { cache: "no-store" })
          .then(function (r) { return r.json(); })
          .then(function (j) {
            if (j && j.ok && j.theme) localStorage.setItem("kp_pubtheme_" + u, JSON.stringify(j.theme));
          }).catch(function () {});
      });
    };
    if (window.requestIdleCallback) requestIdleCallback(warm, { timeout: 2500 });
    else setTimeout(warm, 1500);
  } catch (e) {}
})();


const $ = (s) => document.querySelector(s);
const app = { session: null, tree: null, nodes: {}, routes: {}, current: null };
let loginUser = localStorage.getItem("kp_login_user") || "kitten";

/* ---------------- 基础 ---------------- */
function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function authHeaders(extra) {
  const h = new Headers(extra || {});
  try {
    const t = sessionStorage.getItem("kp_token") || localStorage.getItem("kp_token");
    if (t) h.set("Authorization", "Bearer " + t);
  } catch (e) {}
  return h;
}

async function api(url, opts) {
  opts = Object.assign({ cache: "no-store" }, opts || {});
  opts.headers = authHeaders(opts.headers);
  const r = await fetch(url, opts);
  const j = await r.json().catch(() => ({ ok: false, error: { message: "非 JSON" } }));
  if (r.status === 401 && url.indexOf("/api/login") < 0) { showLogin("会话已过期，请重新登录"); }
  if (!j.ok) throw new Error((j.error && j.error.message) || "HTTP " + r.status);
  return j;
}

/* ---------------- 登录 ---------------- */
function selectRole(u) {
  loadPublicTheme(u);
  loginUser = u;
  localStorage.setItem("kp_login_user", u);
  const un = $("#lg-user"); if (un) un.value = u;
  document.querySelectorAll(".role").forEach((b) => b.classList.toggle("active", b.dataset.u === u));
  $("#lg-err").textContent = "";
}
function showLogin(msg) {
  // 登录独立成 /login 子页面，避免同一页面内遮罩状态残留
  if (msg) { try { sessionStorage.setItem("kp_login_msg", msg); } catch (e) {} }
  const next = location.pathname + location.search;
  location.replace("/login?next=" + encodeURIComponent(next));
}
function hideLogin() { $("#login").classList.remove("show"); }
function hideSplash() {
  const el = $("#boot-splash");
  if (!el || el.classList.contains("hide")) return;
  el.classList.add("hide");
  setTimeout(() => { try { el.remove(); } catch (e) {} }, 280);
}
function shakeLogin() {
  const c = $("#login-card");
  c.classList.remove("shake"); void c.offsetWidth; c.classList.add("shake");
}
let loginMode = "login";
function setLoginMode(mode) {
  loginMode = mode;
  const reg = mode === "register";
  const confirm = $("#lg-confirm");
  if (confirm) confirm.style.display = reg ? "" : "none";
  $("#lg-go").textContent = reg ? "注 册" : "登 录";
  $("#lg-mode").textContent = reg ? "已有账号？登录" : "注册新账号";
  $("#lg-err").textContent = "";
  const hint = document.querySelector(".login-card .sub2");
  if (hint) hint.textContent = reg
    ? "注册新用户 · 注册后自动登录，默认 PinkFDU 主题"
    : "私人工作台 · 选择角色或直接输入用户名";
}
async function doLogin() {
  const user = (($("#lg-user") && $("#lg-user").value) || loginUser || "").trim();
  const pwd = $("#lg-pwd").value.trim();
  if (!user) { $("#lg-err").textContent = "请输入用户名"; return; }
  if (!pwd) { $("#lg-err").textContent = "请输入凭据"; $("#lg-pwd").focus(); return; }
  if (loginMode === "register") {
    const confirm = ($("#lg-confirm") && $("#lg-confirm").value.trim()) || "";
    if (pwd.length < 6) { $("#lg-err").textContent = "口令至少 6 位"; return; }
    if (pwd !== confirm) { $("#lg-err").textContent = "两次口令不一致"; return; }
    try {
      const rr = await fetch("/api/register", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user: user, password: pwd }),
      });
      const rj = await rr.json().catch(() => ({ ok: false }));
      if (!rj.ok) {
        $("#lg-err").textContent = (rj.error && rj.error.message) || "注册失败";
        return;
      }
    } catch (e) {
      $("#lg-err").textContent = "注册失败：" + e.message;
      return;
    }
  }
  const btn = $("#lg-go");
  btn.disabled = true;
  $("#lg-err").textContent = "";
  // 被 GitHub Pages iframe 承载时是第三方上下文：先申请存储权限（CHIPS 的补充）
  if (window.top !== window && document.requestStorageAccess) {
    try { await document.requestStorageAccess(); } catch (e) {}
  }
  try {
    const r = await fetch("/api/login", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user: user, password: pwd }),
    });
    const j = await r.json().catch(() => ({ ok: false }));
    if (!j.ok) {
      $("#lg-err").textContent = (j.error && j.error.message) || "凭据不正确，请重试";
      shakeLogin(); $("#lg-pwd").select();
      return;
    }
    if (j.token) {
      try { sessionStorage.setItem("kp_token", j.token); localStorage.setItem("kp_token", j.token); } catch (e) {}
    }
    try {
      const u = j.session && j.session.user;
      if (u) {
        localStorage.setItem("emf_login_v1", JSON.stringify({ user: u }));
        localStorage.setItem("emf_current_user", u);
        const m = JSON.parse(localStorage.getItem("emf_unlocked_v1") || "{}");
        m[u] = true;
        localStorage.setItem("emf_unlocked_v1", JSON.stringify(m));
      }
    } catch (e) {}
    await boot();
    try { setLoginMode("login"); } catch (e) {}
  } catch (e) {
    $("#lg-err").textContent = "登录失败：" + e.message;
  } finally { btn.disabled = false; }
}

/* ---------------- 树 / 路由 ---------------- */
function indexTree(node, parent) {
  node.children.forEach((n) => {
    app.nodes[n.id] = n;
    if (n.path) app.routes[normalizePath(n.path)] = n;
    indexTree(n, node);
  });
}
function normalizePath(p) {
  let s = (p || "/").split("?")[0];
  if (s.length > 1) s = s.replace(/\/+$/, "");
  return s || "/";
}
function nodeByPath(path) {
  return app.routes[normalizePath(path)] || null;
}
function childLinks(node) {
  return (node.children || []).filter((c) => c.path && !c.hidden);
}

/* ---------------- 工作台 ---------------- */
let homeQuery = "", homeTag = "";
function renderHome() {
  const allRoots = (app.tree.root.children || []).filter((n) => !n.hidden).sort((a, b) => a.order - b.order);
  $("#hello").innerHTML = "你好，" + (app.session.emoji || "") + " <b>" + esc(app.session.user) +
    "</b> —— 欢迎回到工作台";
  const tags = [];
  for (const n of allRoots) for (const t of (n.tags || [])) if (!tags.includes(t)) tags.push(t);
  const tagBox = $("#home-tags");
  tagBox.innerHTML = '<button class="home-tag' + (!homeTag ? " active" : "") + '" data-tag="">全部</button>' +
    tags.map((t) => '<button class="home-tag' + (homeTag === t ? " active" : "") + '" data-tag="' + esc(t) + '">' + esc(t) + "</button>").join("");
  tagBox.querySelectorAll(".home-tag").forEach((b) => {
    b.onclick = () => { homeTag = b.dataset.tag || ""; renderHome(); };
  });
  const search = $("#home-search");
  if (search && search.dataset.bound !== "1") {
    search.dataset.bound = "1";
    search.value = homeQuery;
    const wrap = search.closest(".home-search-wrap");
    const syncClear = () => { if (wrap) wrap.classList.toggle("has-query", !!search.value); };
    search.addEventListener("input", () => { homeQuery = search.value; syncClear(); renderHome(); });
    const clear = $("#home-search-clear");
    if (clear) clear.addEventListener("click", () => { search.value = ""; homeQuery = ""; syncClear(); search.focus(); renderHome(); });
    document.addEventListener("keydown", (e) => {
      if (e.key === "/" && !e.target.closest("input,textarea,select") && $("#view-home").classList.contains("active")) {
        e.preventDefault(); search.focus();
      }
    });
    syncClear();
  }
  const q = homeQuery.trim().toLowerCase();
  const roots = allRoots.filter((n) => {
    if (homeTag && !(n.tags || []).includes(homeTag)) return false;
    if (!q) return true;
    const hay = [n.title, n.desc, (n.tags || []).join(" ")].join(" ").toLowerCase();
    return hay.includes(q);
  });
  const countEl = $("#home-count");
  if (countEl) countEl.textContent = roots.length + " 个模块" + (homeTag ? " · 标签：" + homeTag : "") + (q ? " · 搜索：" + homeQuery.trim() : "");
  const box = $("#cards");
  box.innerHTML = "";
  if (!roots.length) {
    box.innerHTML = '<div class="empty" style="grid-column:1/-1">没有匹配的模块</div>';
    return;
  }
  roots.forEach((n, i) => {
    const accent = userTheme ? userTheme.color : ((n.ui && n.ui.theme && n.ui.theme.accent) || "#9bd1ec");
    const card = document.createElement("article");
    card.className = "card";
    card.style.animationDelay = (60 * i) + "ms";
    card.style.setProperty("--wc", accent);
    const kids = childLinks(n);
    card.innerHTML =
      '<span class="ico">' + esc(n.icon || "📄") + "</span>" +
      "<h2>" + esc(n.title) + "</h2>" +
      "<p>" + esc(n.desc || "") + "</p>" +
      ((n.tags || []).length ? '<div class="card-tags">' + n.tags.map((t) => "<span>" + esc(t) + "</span>").join("") + "</div>" : "") +
      '<div class="foot"><span class="go">进入</span>' +
      '<span class="sub-chips">' + kids.map((k) =>
        '<a class="sub-chip" data-path="' + esc(k.path) + '" href="' + esc(k.path) + '">' +
        esc(k.icon || "") + " " + esc(k.title) + "</a>").join("") + "</span></div>";
    card.onclick = (e) => {
      if (e.target.closest("[data-path]")) return;
      navigate(n);
    };
    card.querySelectorAll("[data-path]").forEach((a) => {
      a.onclick = (e) => { e.preventDefault(); e.stopPropagation(); goPath(a.dataset.path); };
    });
    box.appendChild(card);
  });
  if (userTheme && userTheme.birthday) setTimeout(() => paintBirthdayStickers(document, userTheme.birthday), 0);
}

/* ---------------- 看板 ---------------- */
function renderProject(node) {
  app.current = node;
  $("#view-home").classList.remove("active");
  $("#view-project").classList.add("active");
  $("#p-icon").textContent = node.icon || "📄";
  $("#p-title").textContent = node.title;
  $("#p-desc").textContent = node.desc || "";
  const chips = [];
  if (node.path) chips.push('<span class="chip">' + esc(node.path) + "</span>");
  if ((node.children || []).filter((c) => c.path && !c.hidden).length)
    chips.push('<span class="chip">子页面 ' + childLinks(node).length + "</span>");
  $("#p-meta").innerHTML = chips.join("");
  const frame = $("#host");
  frame.classList.remove("on");
  $("#loading").style.display = "flex";
  const view = node.view || {};
  let src = "/p/" + encodeURIComponent(node.id) + "/";
  if (view.kind === "legacy" && view.url) src = view.url + (view.url.indexOf("?") >= 0 ? "&" : "?") + "embed=1";
  frame.onload = () => {
    $("#loading").style.display = "none";
    requestAnimationFrame(() => frame.classList.add("on"));
    applyFrameTheme(node);
  };
  applyAccent(node);
  frame.src = src;
  document.title = node.title + " · KittenPuppy4Ever";
  updateDrawerTabs();
  preloadAiDrawer();
}

/* ---------------- 路由动作 ---------------- */
function goPath(path, push) {
  try { if (typeof bbClose === "function") bbClose(); } catch (e) {}
  const node = nodeByPath(path);
  if (!node) { goHome(push); return; }
  if (push !== false) history.pushState({ path: path }, "", path);
  renderProject(node);
  postPath();
}
function applyRoleTheme() {
  const user = app.session && app.session.user;
  document.body.classList.toggle("user-kitten", user === "kitten");
  document.body.classList.toggle("user-puppy", user === "puppy");
}

function applyAccent(node) {
  if (userTheme) {
    document.documentElement.style.setProperty("--accent", userTheme.deep || userTheme.color);
    return;
  }
  const accent = node && node.ui && node.ui.theme && node.ui.theme.accent;
  if (accent) document.documentElement.style.setProperty("--accent", accent);
  else document.documentElement.style.removeProperty("--accent");
}

function setFrameBirthday(doc, active){
  if (!doc || !doc.body) return false;
  const was = doc.body.classList.contains("birthday-mode");
  if (was && !active) {
    doc.body.classList.add("bd-leaving");
    if (doc._bdLeaveTimer) clearTimeout(doc._bdLeaveTimer);
    doc._bdLeaveTimer = setTimeout(() => {
      doc.body.classList.remove("birthday-mode", "bd-leaving");
      doc.querySelectorAll(".bd-sticker-el").forEach(n => n.remove());
      doc._bdLeaveTimer = null;
    }, 850);
    return false;
  }
  if (doc._bdLeaveTimer) { clearTimeout(doc._bdLeaveTimer); doc._bdLeaveTimer = null; }
  doc.body.classList.remove("bd-leaving");
  doc.body.classList.toggle("birthday-mode", !!active);
  return !!active;
}
function applyFrameTheme(node) {
  try {
    const doc = $("#host").contentDocument;
    if (!doc || !doc.body) return;
    const user = app.session && app.session.user;
    doc.body.classList.toggle("user-kitten", user === "kitten");
    doc.body.classList.toggle("user-puppy", user === "puppy");
    const theme = userTheme || (user && cachedPublicTheme(user));
    const bday = setFrameBirthday(doc, !!(theme && theme.birthday));
    if (theme && theme.birthday && bday) {
      const lib = theme.birthday.assets || {};
      const pickA = (k, f) => { const a = (!Array.isArray(lib) && lib[k]) || []; return a.length ? a[Math.floor(Math.random()*a.length)] : f; };
      for (const [k, v] of [["--bd-cake", pickA("cake","/static/birthday/cake.png")], ["--bd-balloon", pickA("balloon","/static/birthday/balloon.png")], ["--bd-star", pickA("star","/static/birthday/star.png")], ["--bd-confetti", pickA("confetti","/static/birthday/confetti.png")]]) {
        doc.documentElement.style.setProperty(k, 'url("' + v + '")');
        doc.body.style.setProperty(k, 'url("' + v + '")');
      }
      for (const [k, v] of [["--bd-sticker-a", pickA("cake","/static/birthday/cake.png")], ["--bd-sticker-b", pickA("balloon","/static/birthday/balloon.png")], ["--bd-sticker-c", pickA("star","/static/birthday/star.png")], ["--bd-sticker-d", pickA("confetti","/static/birthday/confetti.png")]]) {
        doc.documentElement.style.setProperty(k, 'url("' + v + '")');
        doc.body.style.setProperty(k, 'url("' + v + '")');
      }
      const bdCols = Array.isArray(theme.birthday.colors) && theme.birthday.colors.length ? theme.birthday.colors : ["#e0a35c","#e98da4","#6fc3ad","#a89bdc","#f2cf7a"];
      bdCols.forEach((c, i) => { doc.documentElement.style.setProperty("--bd-c" + (i + 1), c); doc.body.style.setProperty("--bd-c" + (i + 1), c); });
      setTimeout(() => { try { paintBirthdayStickers(doc, theme.birthday); } catch(e) {} }, 40);
    }
    if (theme) {
      const vars = {"--accent": theme.accent, "--pink": theme.soft, "--pink-deep": theme.deep,
        "--mint": theme.mint, "--bg": theme.bg, "--card": theme.card,
        "--line": theme.line, "--ink": theme.ink, "--p-accent": theme.deep};
      for (const t of theme.tone || []) vars["--" + t.name] = t.color;
      (theme.ramp || []).forEach((c, i) => { vars["--kp-ramp-" + i] = c; });
      for (const el of [doc.documentElement, doc.body]) {
        for (const k in vars) el.style.setProperty(k, vars[k]);
        el.style.setProperty("background-color", vars["--bg"], "important");
        el.style.setProperty("background-image", "none", "important");
      }
    } else {
      const accent = node && node.ui && node.ui.theme && node.ui.theme.accent;
      if (accent) doc.documentElement.style.setProperty("--accent", accent);
    }
  } catch (e) {}
}

function applyThemeToFrame(f) {
  try {
    const doc = f && f.contentDocument;
    if (!doc || !doc.body) return;
    const user = app.session && app.session.user;
    doc.body.classList.toggle("user-kitten", user === "kitten");
    doc.body.classList.toggle("user-puppy", user === "puppy");
    const bday = setFrameBirthday(doc, !!(userTheme && userTheme.birthday));
    if (userTheme && userTheme.birthday && bday) {
      const lib = userTheme.birthday.assets || {};
      const pickA = (k, f) => { const a = (!Array.isArray(lib) && lib[k]) || []; return a.length ? a[Math.floor(Math.random()*a.length)] : f; };
      for (const [k, v] of [["--bd-cake", pickA("cake","/static/birthday/cake.png")], ["--bd-balloon", pickA("balloon","/static/birthday/balloon.png")], ["--bd-star", pickA("star","/static/birthday/star.png")], ["--bd-confetti", pickA("confetti","/static/birthday/confetti.png")]]) {
        doc.documentElement.style.setProperty(k, 'url("' + v + '")');
        doc.body.style.setProperty(k, 'url("' + v + '")');
      }
      for (const [k, v] of [["--bd-sticker-a", pickA("cake","/static/birthday/cake.png")], ["--bd-sticker-b", pickA("balloon","/static/birthday/balloon.png")], ["--bd-sticker-c", pickA("star","/static/birthday/star.png")], ["--bd-sticker-d", pickA("confetti","/static/birthday/confetti.png")]]) {
        doc.documentElement.style.setProperty(k, 'url("' + v + '")');
        doc.body.style.setProperty(k, 'url("' + v + '")');
      }
      const bdCols = Array.isArray(userTheme.birthday.colors) && userTheme.birthday.colors.length ? userTheme.birthday.colors : ["#e0a35c","#e98da4","#6fc3ad","#a89bdc","#f2cf7a"];
      bdCols.forEach((c, i) => { doc.documentElement.style.setProperty("--bd-c" + (i + 1), c); doc.body.style.setProperty("--bd-c" + (i + 1), c); });
      setTimeout(() => { try { paintBirthdayStickers(doc, userTheme.birthday); } catch(e) {} }, 40);
    }
    if (userTheme) {
      const vars = {"--accent": userTheme.accent, "--pink": userTheme.soft, "--pink-deep": userTheme.deep,
        "--mint": userTheme.mint, "--bg": userTheme.bg, "--card": userTheme.card,
        "--line": userTheme.line, "--ink": userTheme.ink, "--p-accent": userTheme.deep};
      for (const t of userTheme.tone || []) vars["--" + t.name] = t.color;
      (userTheme.ramp || []).forEach((c, i) => { vars["--kp-ramp-" + i] = c; });
      for (const el of [doc.documentElement, doc.body]) {
        for (const k in vars) el.style.setProperty(k, vars[k]);
      }
    }
  } catch (e) {}
}

function goHome(push) {
  if (push !== false) history.pushState({ path: "/home" }, "", "/home");
  app.current = null;
  applyAccent(null);
  $("#host").src = "about:blank";
  $("#view-project").classList.remove("active");
  $("#view-home").classList.add("active");
  renderHome();
  document.title = "KittenPuppy4Ever";
  postPath();
  updateDrawerTabs();
}
function navigate(node) {
  if (node.path) goPath(node.path);
  else { // 隐藏项目（调试用）：用 ?p=id 打开
    history.pushState({ p: node.id }, "", "/home?p=" + encodeURIComponent(node.id));
    renderProject(node);
    postPath();
  }
}
let userTheme = null;

const CMAPS = {
  monochrome: null,
  pinkfdu: ["#ec9fbe", "#d97fab", "#b96fa9", "#8f6fb8", "#5b7fc7", "#003da5"],
  viridis: ["#440154", "#3b528b", "#21918c", "#5ec962", "#fde725"],
  plasma: ["#0d0887", "#7e03a8", "#cc4778", "#f89540", "#f0f921"],
  inferno: ["#000004", "#420a68", "#932667", "#dd513a", "#fca50a", "#fcffa4"],
  magma: ["#000004", "#3b0f70", "#8c2981", "#de4968", "#fe9f6d", "#fcfdbf"],
  cividis: ["#002051", "#2d3e6b", "#57647d", "#8a8f8b", "#c6b98e", "#fde737"],
  turbo: ["#30123b", "#4145ab", "#4675ed", "#39a2fc", "#1bcfd4", "#24eca6", "#61fc6c", "#a4fc3b", "#d1e834", "#f3c63a", "#fe9b2d", "#f36315", "#d93806", "#b11901", "#7a0402"],
};
const THEME_PRESETS = [
  ["#ec9fbe", "玫瑰粉"], ["#8fb3e8", "雾蓝"], ["#9bd1ec", "薄荷"], ["#c9b6e4", "藕紫"],
  ["#e8c07a", "茶金"], ["#a9c7a1", "竹绿"], ["#f0a58f", "珊瑚"], ["#b6b0a4", "墨灰"],
];

function hexRgb(h) { const n = parseInt(h.slice(1), 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; }
function rgbHex(rgb) { return "#" + rgb.map((c) => Math.max(0, Math.min(255, Math.round(c))).toString(16).padStart(2, "0")).join(""); }
function rgbHsl(rgb) {
  const [r, g, b] = rgb.map((c) => c / 255);
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2;
  if (mx === mn) return [0, 0, l];
  const d = mx - mn, s = l > 0.5 ? d / (2 - mx - mn) : d / (mx + mn);
  let h = mx === r ? (g - b) / d + (g < b ? 6 : 0) : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [h * 60, s, l];
}
function hslRgb(h, s, l) {
  h = ((h % 360) + 360) % 360;
  const c = (1 - Math.abs(2 * l - 1)) * s, x = c * (1 - Math.abs(((h / 60) % 2) - 1)), m = l - c / 2;
  let rgb;
  if (h < 60) rgb = [c, x, 0]; else if (h < 120) rgb = [x, c, 0]; else if (h < 180) rgb = [0, c, x];
  else if (h < 240) rgb = [0, x, c]; else if (h < 300) rgb = [x, 0, c]; else rgb = [c, 0, x];
  return rgb.map((v) => (v + m) * 255);
}
function mixHex(a, b, t) { const A = hexRgb(a), B = hexRgb(b); return rgbHex(A.map((v, i) => v * (1 - t) + B[i] * t)); }
function lumaHex(h) { const [r, g, b] = hexRgb(h); return (0.299 * r + 0.587 * g + 0.114 * b) / 255; }
function sampleCmap(name, t) {
  const stops = CMAPS[name] || null;
  if (!stops) return "#b25e83";
  t = Math.max(0, Math.min(1, t)) * (stops.length - 1);
  const i = Math.min(stops.length - 2, Math.floor(t));
  return mixHex(stops[i], stops[i + 1], t - i);
}
function interpStops(stops, t) {
  t = Math.max(0, Math.min(1, t)) * (stops.length - 1);
  const i = Math.min(stops.length - 2, Math.floor(t));
  return mixHex(stops[i], stops[i + 1], t - i);
}
function buildRamp(levels, colormap, n = 64) {
  const stops = colormap === "monochrome" ? levels : (CMAPS[colormap] || levels);
  return Array.from({length: n}, (_, i) => interpStops(stops, i / (n - 1)));
}

function computePalette(color, colormap) {
  const [h, s, l] = rgbHsl(hexRgb(color));
  let levels = [];
  if (colormap === "monochrome" || !CMAPS[colormap]) {
    colormap = "monochrome";
    const baseL = Math.max(0.08, Math.min(0.92, l));
    levels = [0.94, 0.70, 0.40].map((frac) => {
      const ll = baseL + (1 - baseL) * frac;
      const ss = Math.min(1, Math.max(0.05, s * (1 - 0.50 * frac)));
      return rgbHex(hslRgb(h, ss, ll));
    });
    levels.push(color.toLowerCase());  // 第 4 级 = 用户选的主题色本身
    for (const frac of [0.30, 0.56]) {
      levels.push(rgbHex(hslRgb(h, Math.min(1, Math.max(0.05, s * 1.12)), Math.max(0.06, baseL * (1 - frac)))));
    }
  } else {
    levels = [0.04, 0.22, 0.40, 0.58, 0.76, 0.95].map((t) => sampleCmap(colormap, t));
  }
  let accent = levels[4];
  if (lumaHex(accent) > 0.55) accent = rgbHex(hexRgb(accent).map((c) => c * 0.66));
  const deep = levels[5];
  const soft = levels[3], mint = levels[2];
  const tone = levels.map((c, i) => ({name: "tone-" + (i + 1), label: "L" + (i + 1), color: c}));
  return {
    color, colormap, accent, deep, soft, pink: soft, mint,
    bg: levels[1], card: levels[0], line: levels[2],
    ink: mixHex("#2a2420", levels[5], 0.18),
    tone,
    ramp: buildRamp(levels, colormap),
  };
}

function samePalette(a, b) {
  return !!a && !!b && a.color === b.color && a.colormap === b.colormap &&
    JSON.stringify(a.tone || []) === JSON.stringify(b.tone || []) &&
    JSON.stringify(a.birthday || null) === JSON.stringify(b.birthday || null);
}
let vtBusy = false;
function applyPaletteAnimated(p) {
  if (samePalette(p, userTheme)) return;
  const lowPerf = document.documentElement.getAttribute("data-perf") === "low" ||
    (window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches);
  const login = $("#login");
  const animate = !lowPerf && document.startViewTransition && !vtBusy && login && login.classList.contains("show");
  if (!animate) { applyPalette(p); return; }
  try {
    vtBusy = true;
    const vt = document.startViewTransition(() => applyPalette(p));
    if (vt && vt.finished) vt.finished.catch(() => {}).finally(() => { vtBusy = false; });
    else vtBusy = false;
  } catch (e) { vtBusy = false; applyPalette(p); }
}

function cachePublicTheme(user, theme) {
  if (!user || !theme || !theme.accent) return;
  try { localStorage.setItem("kp_pubtheme_" + user, JSON.stringify(theme)); } catch (e) {}
}
function cachedPublicTheme(user) {
  try { return JSON.parse(localStorage.getItem("kp_pubtheme_" + user) || "null"); } catch (e) { return null; }
}
async function loadPublicTheme(user, opts) {
  if (!user) return;
  const cached = cachedPublicTheme(user);
  if (cached) applyPaletteAnimated(cached);   // 先用缓存上屏
  try {
    const r = await fetch("/api/public-theme?user=" + encodeURIComponent(user), { cache: "no-store" });
    const j = await r.json();
    if (j.ok && j.theme) {
      cachePublicTheme(user, j.theme);
      if (!cached || cached.color !== j.theme.color || cached.colormap !== j.theme.colormap ||
          JSON.stringify(cached.tone) !== JSON.stringify(j.theme.tone)) {
        applyPaletteAnimated(j.theme);
      }
    }
  } catch (e) {}
}
function prefetchPublicThemes(users) {
  (users || []).forEach((u) => {
    if (cachedPublicTheme(u)) return;
    fetch("/api/public-theme?user=" + encodeURIComponent(u), { cache: "no-store" })
      .then((r) => r.json())
      .then((j) => { if (j.ok && j.theme) cachePublicTheme(u, j.theme); })
      .catch(() => {});
  });
}

function paintBirthdayConfetti(bd){
  const old = document.getElementById("birthday-confetti");
  const reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const low = document.documentElement.getAttribute("data-perf") === "low";
  if (!bd || !bd.active || reduced || low || !Array.isArray(bd.colors) || !bd.colors.length) {
    if (old) old.remove();
    return;
  }
  const layer = old || document.createElement("div");
  layer.id = "birthday-confetti"; layer.setAttribute("aria-hidden", "true");
  if (!old) document.body.appendChild(layer);
  let html = "";
  for (let i = 0; i < 34; i++) {
    const c = bd.colors[i % bd.colors.length];
    const w = 5 + Math.random() * 7;
    const h = 9 + Math.random() * 11;
    const left = Math.random() * 100;
    const dur = (7 + Math.random() * 7).toFixed(2);
    const delay = (-Math.random() * 12).toFixed(2);
    const x = (Math.random() * 160 - 80).toFixed(0);
    const r = (Math.random() * 900 - 450).toFixed(0);
    html += '<i class="bd-confetti-piece" style="left:' + left.toFixed(2) + '%;width:' + w.toFixed(1) +
      'px;height:' + h.toFixed(1) + 'px;--c:' + c + ';--d:' + dur + 's;--delay:' + delay +
      's;--x:' + x + 'px;--r:' + r + 'deg;border-radius:' + (Math.random() < .35 ? "50%" : "2px") + '"></i>';
  }
  layer.innerHTML = html;
}
const BIRTHDAY_EMOJI = window.KP_BIRTHDAY_EMOJI || [];
const BIRTHDAY_EMOJI_BASE = "/static/birthday/emoji/";
let __birthdayPreloadStarted = false;
function preloadBirthdayAssets(extra) {
  if (__birthdayPreloadStarted) return;
  __birthdayPreloadStarted = true;
  const urls = new Set();
  for (const g of (window.KP_BIRTHDAY_EMOJI || [])) {
    for (const slug of (g && g.variants) || []) if (slug) urls.add(BIRTHDAY_EMOJI_BASE + slug + ".webp");
  }
  const lib = extra || {};
  if (lib && typeof lib === "object" && !Array.isArray(lib)) {
    for (const cat of Object.keys(lib)) for (const u of (lib[cat] || [])) if (u) urls.add(u);
  }
  for (const cat of ["cake", "balloon", "star", "confetti"]) urls.add("/static/birthday/" + cat + ".png");
  // Preload links start fetching before stickers are painted.
  for (const u of urls) {
    const l = document.createElement("link");
    l.rel = "preload"; l.as = "image"; l.href = u;
    l.setAttribute("fetchpriority", "high");
    document.head.appendChild(l);
  }
}
function birthdayEmojiGroups(){
  const src = (window.KP_BIRTHDAY_EMOJI || []);
  if (!src.length) return [];
  if (src[0] && Array.isArray(src[0].variants)) {
    return src.filter(g => g && g.variants && g.variants.length);
  }
  const map = new Map();
  for (const e of src) {
    if (!e || !e.slug) continue;
    const base = e.slug.replace(/_v\d+$/, "");
    if (!map.has(base)) map.set(base, {base, relevance: e.relevance || 5, variants: []});
    map.get(base).variants.push(e.slug);
  }
  return Array.from(map.values());
}
function pickBirthdayEmoji(size){
  const groups = birthdayEmojiGroups();
  if (!groups.length) return null;
  const t = Math.max(0, Math.min(1, (size - 14) / 60));
  const exponent = 0.35 + t * 2.35; // larger sticker -> base probability dominates
  let total = 0;
  const weights = groups.map(g => {
    const w = Math.pow(Math.max(0.0001, g.relevance || 0.1), exponent);
    total += w; return w;
  });
  let r = Math.random() * total;
  let chosen = groups[groups.length - 1];
  for (let i = 0; i < groups.length; i++) {
    r -= weights[i];
    if (r <= 0) { chosen = groups[i]; break; }
  }
  const variants = (chosen.variants || []).filter(Boolean);
  if (!variants.length) return chosen.base || null;
  return variants[Math.floor(Math.random() * variants.length)]; // uniform among variants
}
function bdRectOverlap(a, b){
  const l = Math.max(a.left, b.left), r = Math.min(a.left + a.w, b.left + b.w);
  const t = Math.max(a.top, b.top), d = Math.min(a.top + a.h, b.top + b.h);
  if (r <= l || d <= t) return 0;
  return (r - l) * (d - t);
}
function bdTryPlace(doc, rect){
  const list = doc._bdRects || (doc._bdRects = []);
  const area = Math.max(1, rect.w * rect.h);
  for (const r of list) {
    const inter = bdRectOverlap(rect, r);
    if (inter / Math.min(area, Math.max(1, r.w * r.h)) > 0.5) return false;
  }
  list.push(rect);
  return true;
}
function bdSwayStyle(img){
  img.style.setProperty("--sway-dur", (5.2 + Math.random() * 2.6).toFixed(2) + "s");
  img.style.setProperty("--sway-delay", (-Math.random() * 6).toFixed(2) + "s");
}
function paintBirthdayStickers(doc, bd){
  if (!doc || !bd || !bd.active) return;
  doc.querySelectorAll(".bd-sticker-el").forEach(el => el.remove());
  // include already-rendered hero stickers in the collision set
  const tr = doc.defaultView || window;
  doc._bdRects = Array.from(doc.querySelectorAll(".bh-emoji")).map(el => {
    const r = el.getBoundingClientRect();
    return {left: r.left, top: r.top, w: r.width, h: r.height};
  });
  doc._bdFlip = false;
  const rnd = (a, b) => a + Math.random() * (b - a);
  const make = (target, side, size) => {
    const box = target.getBoundingClientRect();
    const w = target.offsetWidth || 220, h = target.offsetHeight || 120;
    let chosen = null;
    for (let attempt = 0; attempt < 24; attempt++) {
      let left = 0, top = 0;
      const pad = size * 0.12;
      if (side === "top") { top = -size * 0.42; left = rnd(pad, Math.max(pad, w - size - pad)); }
      else if (side === "right") { left = w - size + size * 0.42; top = rnd(pad, Math.max(pad, h - size - pad)); }
      else if (side === "bottom") { top = h - size + size * 0.42; left = rnd(pad, Math.max(pad, w - size - pad)); }
      else { left = -size * 0.42; top = rnd(pad, Math.max(pad, h - size - pad)); }
      const rect = {left: box.left + left, top: box.top + top, w: size, h: size};
      if (bdTryPlace(doc, rect)) { chosen = {left, top}; break; }
    }
    if (!chosen) return;
    const span = doc.createElement("span");
    const slug = pickBirthdayEmoji(size);
    span.className = "bd-sticker-el bd-emoji";
    const face = doc.createElement("img"); face.className = "bd-emoji-face"; face.src = BIRTHDAY_EMOJI_BASE + slug + ".webp"; face.alt = ""; face.loading = "eager"; face.decoding = "sync"; face.fetchPriority = "high";
    bdSwayStyle(face);
    span.appendChild(face);
    span.style.width = size + "px"; span.style.height = size + "px";
    const angle = rnd(-25, 25).toFixed(1);
    doc._bdFlip = !doc._bdFlip;
    span.style.transform = "rotate(" + angle + "deg)" + (doc._bdFlip ? " scaleX(-1)" : "");
    span.style.left = chosen.left + "px"; span.style.top = chosen.top + "px";
    target.appendChild(span);
  };
  const panelSides = ["top", "right", "bottom", "left"];
  doc.querySelectorAll(".section,.sm-box,.modal > div").forEach(el => {
    if (!el.offsetWidth) return;
    el.classList.add("bd-sticker-host");
    const n = 2 + Math.floor(Math.random() * 3);
    panelSides.slice(0, n).forEach(side => make(el, side, rnd(30, 54)));
  });
  doc.querySelectorAll(".card").forEach(el => {
    el.classList.add("bd-sticker-host");
    make(el, ["top", "right", "bottom"][Math.floor(Math.random() * 3)], rnd(24, 42));
  });
  doc.querySelectorAll(".btn.primary").forEach(el => {
    el.classList.add("bd-sticker-host");
    make(el, "top", rnd(14, 22));
  });
}

const BIRTHDAY_HERO_MESSAGES = [
  {t: "生日快乐", s: "今天整座工作台都在为你庆祝"},
  {t: "生日快乐，愿望成真", s: "愿新的一岁，所有喜欢都如约而至"},
  {t: "许个愿吧", s: "蜡烛已经点上，好运正在派送"},
  {t: "今天是你的主场", s: "不必长大，也可以被世界偏爱"},
  {t: "又长大一岁啦", s: "愿你的每一天都像今天一样闪闪发光"}
];
function paintHeroMessage(hero, bd, idx, animate){
  if (!hero || !bd) return;
  const list = BIRTHDAY_HERO_MESSAGES.slice();
  list[0] = {t: bd.greeting || "生日快乐", s: list[0].s};
  if (bd.age !== null && bd.age !== undefined && bd.age !== "") {
    list[1] = {t: "生日快乐，你 " + bd.age + " 岁啦", s: "愿新的一岁，所有喜欢都如约而至"};
    list[3] = {t: "今天，你 " + bd.age + " 岁", s: "不必长大，也可以被世界偏爱"};
    list[4] = {t: "你已经 " + bd.age + " 岁了，继续闪闪发光", s: "愿你的每一天都像今天一样明亮"};
  }
  const msg = list[((idx % list.length) + list.length) % list.length];
  const copy = hero.querySelector(".bh-copy");
  const apply = () => {
    const title = hero.querySelector(".bh-title");
    const sub = hero.querySelector(".bh-sub");
    if (title) title.textContent = msg.t;
    if (sub) sub.textContent = msg.s + " · " + (bd.emoji || "🎂");
    hero.dataset.msgIndex = String(idx % list.length);
    if (copy) copy.classList.remove("bh-fading");
  };
  if (!animate) { apply(); return; }
  if (hero._msgTimer) clearTimeout(hero._msgTimer);
  if (copy) copy.classList.add("bh-fading");
  hero._msgTimer = setTimeout(apply, 170);
}
function bindHeroMessages(hero, bd){
  if (!hero) return;
  if (hero.dataset.msgBound === "1") { paintHeroMessage(hero, bd, 0); return; }
  hero.dataset.msgBound = "1";
  hero.title = "点击切换生日祝福";
  let idx = 0;
  paintHeroMessage(hero, bd, idx);
  hero.addEventListener("click", () => {
    idx = (idx + 1) % BIRTHDAY_HERO_MESSAGES.length;
    paintHeroMessage(hero, bd, idx, true);
  });
}
function paintHeroEmojis(hero, bd, tries){
  if (!hero || !bd || !bd.active) return;
  const box = hero.getBoundingClientRect();
  if (box.width < 10 && (tries || 0) < 6) {
    return setTimeout(() => paintHeroEmojis(hero, bd, (tries || 0) + 1), 60);
  }
  const scatterBox = hero.querySelector(".bh-scatter");
  if (!scatterBox) return;
  scatterBox.innerHTML = "";
  document._bdRects = (document._bdRects || []).filter(r => r.w > 0);
  const n = 4 + Math.floor(Math.random() * 3);
  const rows = 2, cols = Math.ceil(n / rows);
  const slots = [];
  for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) slots.push({r, c});
  for (let i = slots.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [slots[i], slots[j]] = [slots[j], slots[i]]; }
  for (let i = 0; i < Math.min(n, slots.length); i++) {
    const slot = slots[i];
    let placed = null;
    for (let attempt = 0; attempt < 30; attempt++) {
      const size = Math.round(40 + Math.random() * 44);
      const left = Math.max(46, Math.min(94,
        47 + (slot.c + 0.5) * (47 / cols) + (Math.random() - 0.5) * 5));
      const top = (slot.r === 0 ? 4 + Math.random() * 22 : 42 + Math.random() * 26);
      const rect = {left: box.left + box.width * left / 100,
                    top: box.top + box.height * top / 100, w: size, h: size};
      if (bdTryPlace(document, rect)) { placed = {size, left, top}; break; }
    }
    if (!placed) continue;
    const angle = (Math.random() * 34 - 17).toFixed(1);
    const slug = pickBirthdayEmoji(placed.size);
    if (!slug) continue;
    const span = document.createElement("span");
    span.className = "bh-emoji";
    span.style.width = placed.size + "px"; span.style.height = placed.size + "px";
    span.style.left = placed.left.toFixed(1) + "%"; span.style.top = placed.top.toFixed(1) + "%";
    document._bdFlip = !document._bdFlip;
    span.style.transform = "rotate(" + angle + "deg)" + (document._bdFlip ? " scaleX(-1)" : "");
    const img = document.createElement("img");
    img.className = "bd-emoji-face"; img.src = BIRTHDAY_EMOJI_BASE + slug + ".webp"; img.alt = ""; img.loading = "eager"; img.decoding = "sync"; img.fetchPriority = "high";
    bdSwayStyle(img);
    span.appendChild(img); scatterBox.appendChild(span);
  }
}
let bdWasActive = false;
let bdLeaveTimer = null;
function applyBirthdayDeco(p){
  let el = document.getElementById("birthday-deco");
  const bd = p && p.birthday;
  const active = !!(bd && bd.active);
  const priorPanels = capturePanelPositions();
  if (bdLeaveTimer) { clearTimeout(bdLeaveTimer); bdLeaveTimer = null; }
  if (!active) {
    if (bdWasActive) {
      bdWasActive = false;
      document.body.classList.add("bd-leaving");
      const exitingHero = document.getElementById("birthday-hero");
      if (exitingHero) { exitingHero.classList.remove("bd-hero-expanded"); exitingHero.classList.add("bd-hero-collapsed"); }
      bdLeaveTimer = setTimeout(() => {
        document.body.classList.remove("birthday-mode", "bd-leaving");
        document.querySelectorAll(".bd-sticker-el,.bh-emoji").forEach(n => n.remove());
        const h = document.getElementById("birthday-hero"); if (h) h.remove();
        const c = document.getElementById("birthday-confetti"); if (c) c.remove();
        bdLeaveTimer = null;
      }, 850);
    } else {
      if (el) el.remove();
      const h = document.getElementById("birthday-hero"); if (h) h.remove();
      const c = document.getElementById("birthday-confetti"); if (c) c.remove();
    }
    return;
  }
  bdWasActive = true;
  document.body.classList.remove("bd-leaving");
  document.body.classList.add("birthday-mode");
  if (!el) { el = document.createElement("div"); el.id = "birthday-deco"; el.setAttribute("aria-hidden", "true"); document.body.appendChild(el); }
  const lib = bd.assets || {};
  const pick = (cat, fallback) => {
    const arr = Array.isArray(lib) ? [] : (lib[cat] || []);
    if (!arr.length) return fallback;
    return arr[Math.floor(Math.random() * arr.length)];
  };
  const cakeU = pick("cake", "/static/birthday/cake.png");
  const balloonU = pick("balloon", "/static/birthday/balloon.png");
  const starU = pick("star", "/static/birthday/star.png");
  const confettiU = pick("confetti", "/static/birthday/confetti.png");
  for (const [k, v] of [["--bd-cake", cakeU], ["--bd-balloon", balloonU], ["--bd-star", starU], ["--bd-confetti", confettiU]]) {
    document.documentElement.style.setProperty(k, 'url("' + v + '")');
    if (document.body) document.body.style.setProperty(k, 'url("' + v + '")');
  }
  for (const [k, v] of [["--bd-sticker-a", cakeU], ["--bd-sticker-b", balloonU], ["--bd-sticker-c", starU], ["--bd-sticker-d", confettiU]]) {
    document.documentElement.style.setProperty(k, 'url("' + v + '")');
    if (document.body) document.body.style.setProperty(k, 'url("' + v + '")');
  }
  const bdColors = Array.isArray(bd.colors) && bd.colors.length ? bd.colors : ["#e0a35c","#e98da4","#6fc3ad","#a89bdc","#f2cf7a"];
  bdColors.forEach((c, i) => {
    document.documentElement.style.setProperty("--bd-c" + (i + 1), c);
    if (document.body) document.body.style.setProperty("--bd-c" + (i + 1), c);
  });
  if (el) el.remove();
  try { preloadBirthdayAssets(lib); } catch(e) {}
  try { paintBirthdayStickers(document, bd); } catch(e) {}
  try { paintBirthdayConfetti(bd); } catch(e) {}
  let hero = document.getElementById("birthday-hero");
  const hello = document.getElementById("hello");
  if (hello) {
    const isNewHero = !hero;
    if (!hero) {
      hero = document.createElement("div");
      hero.id = "birthday-hero";
      hero.className = "birthday-hero bd-hero-collapsed";
      hello.after(hero);
    }
    if (isNewHero) { void hero.offsetHeight; }
    hero.classList.remove("bd-hero-collapsed");
    hero.classList.add("bd-hero-expanded");
    hero.innerHTML = '<div class="bh-copy"><div class="bh-kicker">BIRTHDAY · ' + esc(bd.name || "生日限定") +
      '</div><div class="bh-title">' + esc(bd.greeting || "生日快乐") + '</div><div class="bh-sub">今天整座工作台都在为你庆祝 · ' +
      esc(bd.emoji || "🎂") + '</div><a class="bh-bottle-link" href="/bottle/">🍾 在漂流瓶里许一个生日愿望</a></div><div class="bh-scatter"></div>';
    const bottleLink = hero.querySelector(".bh-bottle-link");
    if (bottleLink) bottleLink.onclick = (e) => {
      e.preventDefault(); e.stopPropagation();
      openBirthdayBottleModal();
    };
    const scatterBox = hero.querySelector(".bh-scatter");
    const heroBox = hero.getBoundingClientRect();
    bindHeroMessages(hero, bd);
    setTimeout(() => paintHeroEmojis(hero, bd), 80);
  }
}
function capturePanelPositions(){
  return Array.from(document.querySelectorAll(".card,.section,.sm-box")).map(el => {
    const r = el.getBoundingClientRect();
    return {el, left: r.left, top: r.top, visible: r.width > 0 && r.height > 0};
  });
}
function playPanelReflow(prev){
  if (!prev || !prev.length) return;
  requestAnimationFrame(() => {
    for (const p of prev) {
      if (!p.visible || !p.el.isConnected) continue;
      const r = p.el.getBoundingClientRect();
      const dx = p.left - r.left, dy = p.top - r.top;
      if (Math.abs(dx) < 1 && Math.abs(dy) < 1) continue;
      p.el.style.transition = "none";
      p.el.style.transform = "translate(" + dx + "px," + dy + "px)";
      requestAnimationFrame(() => {
        p.el.style.transition = "transform .45s cubic-bezier(.22,1,.36,1)";
        p.el.style.transform = "";
        setTimeout(() => { p.el.style.transition = ""; }, 520);
      });
    }
  });
}
function applyPalette(p){
  if (!p || !p.accent) return;
  userTheme = p;
  const vars = {
    "--accent": p.accent, "--pink": p.soft, "--pink-deep": p.deep, "--mint": p.mint,
    "--accent-weak": p.soft, "--bg": p.bg || "#f8f4ec", "--card": p.card || "#fffdf8",
    "--line": p.line || "#e8dfd2", "--ink": p.ink || "#42392b", "--p-accent": p.deep,
  };
  for (const t of p.tone || []) vars["--" + t.name] = t.color;
  (p.ramp || []).forEach((c, i) => { vars["--kp-ramp-" + i] = c; });
  for (const el of [document.documentElement, document.body]) {
    for (const k in vars) if (el && el.style) el.style.setProperty(k, vars[k]);
  }
  try { applyFrameTheme(app.current); } catch (e) {}
  if (p && p.birthday && p.birthday.active) preloadBirthdayAssets(p.birthday.assets);
  applyBirthdayDeco(p);
}

function themeSwatches() {
  const box = $("#theme-swatches");
  if (!box) return;
  box.innerHTML = "";
  for (const [color, name] of THEME_PRESETS) {
    const b = document.createElement("button");
    b.className = "btn theme-dot" + (userTheme && userTheme.color === color ? " active" : "");
    b.style.background = color;
    b.title = name;
    b.onclick = () => {
      $("#theme-custom").value = color;
      previewPalette();
    };
    box.appendChild(b);
  }
}

function paintPalettePreview(p) {
  const box = $("#palette-preview");
  if (!box) return;
  box.innerHTML = "";
  for (const t of p.tone || []) {
    const el = document.createElement("span");
    el.style.background = t.color;
    el.style.color = lumaHex(t.color) > 0.55 ? "#2a2420" : "#fff";
    el.textContent = t.name;
    el.title = t.label + " · " + t.color;
    box.appendChild(el);
  }
}

function paintCmapPreview(p) {
  const el = $("#cmap-preview");
  if (!el) return;
  const colors = (p && p.ramp && p.ramp.length ? p.ramp : (p && p.tone ? p.tone.map((t) => t.color) : []));
  el.style.background = colors.length
    ? "linear-gradient(90deg," + colors.join(",") + ")"
    : "linear-gradient(90deg,#f5eff2,#bf2c67)";
}

function previewPalette() {
  const color = $("#theme-custom").value || "#ec9fbe";
  const colormap = $("#theme-colormap").value || "monochrome";
  const p = computePalette(color, colormap);
  paintPalettePreview(p);
  paintCmapPreview(p);
}

async function saveUserTheme() {
  if (userTheme && userTheme.birthday) { $("#theme-msg").textContent = "生日主题不可更换。"; return; }
  const color = $("#theme-custom").value || "#ec9fbe";
  const colormap = $("#theme-colormap").value || "monochrome";
  $("#theme-msg").textContent = "保存中…";
  try {
    const r = await fetch("/api/theme", {
      method: "POST",
      headers: Object.assign(authHeaders(), { "Content-Type": "application/json" }),
      body: JSON.stringify({ color, colormap }),
    });
    const j = await r.json();
    if (!j.ok) throw new Error((j.error && j.error.message) || "保存失败");
    applyPalette(j.theme);
    if (app.session) cachePublicTheme(app.session.user, j.theme);
    themeSwatches();
    paintPalettePreview(j.theme);
    paintCmapPreview(j.theme);
    $("#theme-msg").textContent = "已保存 · " + j.theme.colormap;
  } catch (e) {
    $("#theme-msg").textContent = "保存失败：" + e.message;
  }
}

function postPath() {
  // 被 GitHub Pages 入口 iframe 承载时，让父页面把地址栏保持在 github.io/... 的旧格式
  if (window.parent === window) return;
  try {
    window.parent.postMessage({ kpPath: location.pathname + location.search }, "https://stjwls.github.io");
  } catch (e) {}
}

function routeFromLocation() {
  const params = new URLSearchParams(location.search);
  const pid = params.get("p");
  if (pid && app.nodes[pid]) { renderProject(app.nodes[pid]); return; }
  const node = nodeByPath(location.pathname);
  if (node) renderProject(node); else goHome(false);
  postPath();
}

/* ---------------- puppy 调试 ---------------- */
function renderDebugTree() {
  const box = $("#dbg-tree");
  box.innerHTML = "";
  const walk = (nodes, depth) => {
    nodes.forEach((n) => {
      if (n.id === "root") return walk(n.children, depth);
      const b = document.createElement("button");
      b.className = "dbg-node" + (depth ? " child" : "");
      b.innerHTML = '<span>' + esc(n.icon || "📄") + "</span><span>" + esc(n.title) +
        '</span><span class="b">' + esc(n.base || "") + "</span>" +
        (n.path ? '<span class="pth">' + esc(n.path) + "</span>" : "");
      b.onclick = () => navigate(n);
      box.appendChild(b);
      if (n.children && n.children.length) walk(n.children, depth + 1);
    });
  };
  walk([app.tree.root], 0);
}
async function refreshMetrics() {
  try {
    const m = await api("/api/metrics");
    const e = m.engine || {};
    $("#dbg-metrics").innerHTML =
      "cache hit <b>" + Math.round((e.cache_hit_rate || 0) * 1000) / 10 + "%</b><br>" +
      "reads <b>" + (e.reads || 0) + "</b> · saves <b>" + (e.saves || 0) + "</b><br>" +
      "doc <b>" + ((e.doc_bytes_total || 0) / 1024).toFixed(1) + "KB</b> · 304 <b>" + (e.etag_304 || 0) + "</b>";
  } catch (e) {
    $("#dbg-metrics").textContent = "指标不可用（需要 puppy 身份）";
  }
}
function positionDebugDrawer() {
  let top = 96;
  const header = document.querySelector("header.top");
  const hello = document.getElementById("hello");
  const pbar = document.querySelector("#view-project .pbar");
  if ($("#view-home").classList.contains("active") && hello && hello.getBoundingClientRect().top) {
    top = hello.getBoundingClientRect().top;
  } else if ($("#view-project").classList.contains("active") && pbar) {
    top = pbar.getBoundingClientRect().bottom + 12;
  } else if (header) {
    top = header.getBoundingClientRect().bottom + 12;
  }
  document.documentElement.style.setProperty("--kp-debug-top", Math.max(60, Math.round(top)) + "px");
}
function showDebugPane(name) {
  document.querySelectorAll(".dbg-tab").forEach((b) => b.classList.toggle("active", b.dataset.dbgpane === name));
  document.querySelectorAll(".dbg-pane").forEach((p) => p.classList.toggle("active", p.id === "dbg-pane-" + name));
  if (name === "sched") {
    const f = document.getElementById("dbg-sched-frame");
    if (f && !f.dataset.ready) {
      f.dataset.ready = "1";
      f.onload = () => applyThemeToFrame(f);
      f.src = "/p/schedule-debug/?drawer=1";
    }
  }
}
function openDebugDrawer() {
  const btn = $("#dbg-toggle");
  positionDebugDrawer();
  $("#debug").classList.add("open");
  document.body.classList.add("debug-open");
  if (btn) { btn.textContent = "←"; btn.classList.add("show"); }
  refreshMetrics();
}
function closeDebugDrawer() {
  const btn = $("#dbg-toggle");
  $("#debug").classList.remove("open");
  document.body.classList.remove("debug-open");
  if (btn) { btn.textContent = "🛠️"; btn.classList.add("show"); }
}
function setupDebug() {
  const isPuppy = app.session && (app.session.user === "puppy" || app.session.role === "主要维护者");
  const btn = $("#dbg-toggle");
  if (!btn) return;
  btn.classList.toggle("show", !!isPuppy);
  if (!isPuppy) return;
  btn.onclick = () => {
    if ($("#debug").classList.contains("open")) closeDebugDrawer();
    else openDebugDrawer();
  };
  document.querySelectorAll(".dbg-tab").forEach((b) => b.onclick = () => showDebugPane(b.dataset.dbgpane));
  renderDebugTree();
  if (new URLSearchParams(location.search).get("debug") === "1") openDebugDrawer();
  setInterval(() => { if ($("#debug").classList.contains("open")) refreshMetrics(); }, 10000);
}

/* ---------------- 启动 ---------------- */
/* ---------------- 右侧 AI 抽屉 / 左侧日程调试抽屉 ---------------- */
let aiDrawerBusy = false;
let bottleStatusTimer = null;
let bottleStatusLoading = false;
function closeBottleStatusDrawer() {
  const d = $("#bottle-status-drawer");
  if (!d) return;
  d.classList.remove("open"); d.setAttribute("aria-hidden", "true");
  document.body.classList.remove("bottle-open");
  const b = $("#bottle-status-btn"); if (b) b.textContent = "🍾";
  if (bottleStatusTimer) { clearInterval(bottleStatusTimer); bottleStatusTimer = null; }
}
async function refreshBottleStatus() {
  if (bottleStatusLoading || !app.session) return;
  bottleStatusLoading = true;
  const list = $("#bottle-status-list");
  try {
    const j = await api("/api/p/bottle/state");
    const mine = ((j.data && j.data.bottles) || []).filter(b => b.from === app.session.user);
    mine.sort((a, b) => String(b.createdAt || "").localeCompare(String(a.createdAt || "")));
    const openCount = mine.filter(b => b.opened).length;
    $("#bottle-status-sub").textContent = mine.length
      ? "我写出去的一共 " + mine.length + " 个 · 漂流中 " + (mine.length - openCount) + " · 已打开 " + openCount
      : "追踪我写出去的所有漂流瓶。";
    if (!mine.length) {
      list.innerHTML = '<div class="bs-empty">还没有写过漂流瓶。<br>去「写一个漂流瓶」留一句话吧。</div>';
      return;
    }
    const dots = '<span class="bs-dots"><i></i><i></i><i></i></span>';
    list.innerHTML = mine.map(b => {
      const st = b.opened
        ? '<span class="bs-state done">已打开</span>'
        : '<span class="bs-state wave">漂流中' + dots + '</span>';
      return '<div class="bs-item"><div class="who">给 ' + esc(b.to || "—") + st + '</div>' +
        '<div class="meta">开启日 ' + esc(b.openAt || "—") +
        (b.opened && b.openedAt ? ' · 打开于 ' + esc(String(b.openedAt).slice(0, 10)) : '') +
        '</div></div>';
    }).join("");
  } catch (e) {
    if (list) list.innerHTML = '<div class="bs-empty">读取失败：' + esc(e.message) + '</div>';
  } finally {
    bottleStatusLoading = false;
  }
}
async function openBottleStatusDrawer() {
  if (!app.session) return;
  closeAiDrawer();
  const d = $("#bottle-status-drawer");
  if (!d) return;
  d.classList.add("open"); d.setAttribute("aria-hidden", "false");
  document.body.classList.add("bottle-open");
  const b = $("#bottle-status-btn"); if (b) b.textContent = "←";
  await refreshBottleStatus();
  if (bottleStatusTimer) clearInterval(bottleStatusTimer);
  bottleStatusTimer = setInterval(refreshBottleStatus, 5000);
}
function toggleBottleStatusDrawer() {
  const d = $("#bottle-status-drawer");
  if (d && d.classList.contains("open")) closeBottleStatusDrawer(); else openBottleStatusDrawer();
}

function updateDrawerTabs(){
  const aiTab = $("#ai-edge");
  const inProject = $("#view-project").classList.contains("active") && app.current;
  const isAi = inProject && app.current.id === "ai";
  if (aiTab) aiTab.classList.toggle("show", !!app.session && inProject && !isAi);
  const onBottle = !!app.session && inProject && app.current && app.current.id === "bottle";
  const bottleBtn = $("#bottle-status-btn");
  if (bottleBtn) bottleBtn.classList.toggle("show", onBottle);
  if (!onBottle) closeBottleStatusDrawer();
  const onAi = !!app.session && inProject && isAi;
  const configFab = $("#ai-page-config"), histFab = $("#ai-page-history");
  if (configFab) configFab.classList.toggle("show", onAi);
  if (histFab) histFab.classList.toggle("show", onAi);
  if (!inProject || isAi) closeAiDrawer(false);
  if ($("#debug").classList.contains("open")) positionDebugDrawer();
  try {
    const h = document.querySelector("header.top");
    if (h) document.documentElement.style.setProperty("--kp-header-h", h.offsetHeight + "px");
    positionAiDrawer();
  } catch (e) {}
}
function closeAiDrawer(clear){
  const d=$("#ai-drawer"); if(!d) return;
  d.classList.remove("open"); d.setAttribute("aria-hidden","true"); document.body.classList.remove("ai-open");
  const b=$("#ai-edge"); if(b) b.textContent="🤖";
  const f=$("#ai-drawer-frame");
  if(f && f.contentWindow){ try{ f.contentWindow.postMessage({kpAiPanel:null},"*"); }catch(e){} }
  aiDrawerPanel=null; syncAiDrawerIcons(); document.body.classList.remove("ai-panel-open");
}
function positionAiDrawer(){
  const pbar = document.querySelector("#view-project .pbar");
  const header = document.querySelector("header.top");
  const base = pbar ? pbar.getBoundingClientRect().bottom : (header ? header.getBoundingClientRect().bottom : 62);
  document.documentElement.style.setProperty("--kp-ai-top", Math.round(base + 12) + "px");
}
let aiPreloadTimer = null;
function preloadAiDrawer(){
  clearTimeout(aiPreloadTimer);
  aiPreloadTimer = setTimeout(() => {
    if (!app.session || !app.current || app.current.id === "ai") return;
    const d = $("#ai-drawer"), f = $("#ai-drawer-frame");
    if (!d || !f || d.classList.contains("open")) return;
    const mod = app.current.id;
    if (f.dataset.ready && f.dataset.module === mod) return;
    f.dataset.ready = "1"; f.dataset.module = mod;
    window.__KP_PRELOADING_AI = true;
    f.onload = () => { window.__KP_PRELOADING_AI = false; applyThemeToFrame(f); };
    f.src = "/p/ai/?drawer=1&preload=1&module=" + encodeURIComponent(mod);
    setTimeout(() => { window.__KP_PRELOADING_AI = false; }, 10000);
  }, 220);
}
async function openAiDrawer(){
  closeBottleStatusDrawer();
  clearTimeout(aiPreloadTimer);
  const d=$("#ai-drawer"); if(!d || !app.session) return;
  positionAiDrawer();
  const f=$("#ai-drawer-frame");
  const mod = (app.current && app.current.id) || "";
  if(f && (!f.dataset.ready || f.dataset.module !== mod)){
    f.dataset.ready="1"; f.dataset.module=mod;
    f.onload=()=>{ applyThemeToFrame(f); if(f.dataset.showHistory){ try{ f.contentWindow.postMessage({kpAiPanel:"history"},"*"); }catch(e){} } };
    f.src="/p/ai/?drawer=1" + (mod ? "&module=" + encodeURIComponent(mod) : "");
  }
  d.classList.add("open"); d.setAttribute("aria-hidden","false"); document.body.classList.add("ai-open");
  applyThemeToFrame(f);
  const b=$("#ai-edge"); if(b) b.textContent="←";
}
let aiPagePanel = null;
let aiDrawerPanel = null;
function syncAiDrawerIcons(){
  const h=$("#ai-history"), c=$("#ai-drawer-settings");
  if(h) { h.textContent = aiDrawerPanel === "history" ? "←" : "🕘"; h.classList.toggle("back", aiDrawerPanel === "history"); }
  if(c) { c.textContent = aiDrawerPanel === "settings" ? "←" : "⚙️"; c.classList.toggle("back", aiDrawerPanel === "settings"); }
}
function toggleAiDrawerPanel(name){
  const f=$("#ai-drawer-frame");
  if(!f || !f.contentWindow) return;
  if(aiDrawerPanel === name){
    f.contentWindow.postMessage({kpAiPanel:null},"*");
    aiDrawerPanel = null;
  } else {
    f.contentWindow.postMessage({kpAiPanel:name},"*");
    aiDrawerPanel = name;
  }
  syncAiDrawerIcons();
}
function syncAiPageIcons(){
  const h=$("#ai-page-history"), c=$("#ai-page-config");
  if(h) { h.textContent = aiPagePanel === "history" ? "←" : "🕘"; h.classList.toggle("back", aiPagePanel === "history"); }
  if(c) { c.textContent = aiPagePanel === "settings" ? "←" : "⚙️"; c.classList.toggle("back", aiPagePanel === "settings"); }
}
function sendAiPageTab(name){
  const f=document.getElementById("host");
  if(!f || !f.contentWindow) return;
  if(aiPagePanel === name){
    f.contentWindow.postMessage({kpAiPanel:null},"*");
    aiPagePanel = null;
  } else {
    f.contentWindow.postMessage({kpAiPanel:name},"*");
    aiPagePanel = name;
  }
  syncAiPageIcons();
}
function sendAiDrawerPanel(name){
  const f=$("#ai-drawer-frame");
  if(f && f.contentWindow) f.contentWindow.postMessage({kpAiPanel:name},"*");
}
function showAiHistory(){
  const d=$("#ai-drawer"), f=$("#ai-drawer-frame");
  if(!d || !app.session) return;
  if(!d.classList.contains("open")) openAiDrawer();
  if(f && f.dataset.ready){ toggleAiDrawerPanel("history"); }
  else if(f){ f.dataset.showHistory="1"; aiDrawerPanel="history"; syncAiDrawerIcons(); }
}

const aiSleep = (ms) => new Promise(r => setTimeout(r, ms));
async function playAiUi(ui) {
  if (!ui || !ui.module || !ui.actions) return;
  if (!app.current || app.current.id !== ui.module) return;
  const host = document.getElementById("host");
  const cursor = document.getElementById("ai-cursor");
  if (!host || !cursor || !host.contentDocument) return;
  const doc = host.contentDocument;
  if (!doc.getElementById("kp-ai-ui-style")) {
    const st = doc.createElement("style"); st.id = "kp-ai-ui-style";
    st.textContent = ".kp-ai-target{outline:3px solid var(--tone-5)!important;outline-offset:3px!important;border-radius:6px;transition:outline-color .2s}";
    (doc.head || doc.documentElement).appendChild(st);
  }
  cursor.classList.add("show");
  cursor.style.left = Math.max(20, innerWidth - 80) + "px";
  cursor.style.top = Math.max(20, innerHeight - 150) + "px";
  await aiSleep(30);
  for (const action of ui.actions) {
    if (!action || !action.type) continue;
    if (action.type === "reload_host") {
      let next = host.src;
      try {
        const u = new URL(host.src, location.href);
        u.searchParams.set("_kp_reload", String(Date.now()));
        next = u.href;
      } catch(e) {}
      try { host.src = next; } catch(_) {}
      continue;
    }
    let target = null;
    if (action.selector) { try { target = doc.querySelector(action.selector); } catch(e) {} }
    if (target) {
      try { target.scrollIntoView({block: "center", behavior: "smooth"}); } catch(e) {}
      await aiSleep(120);
      const fr = host.getBoundingClientRect();
      const tr = target.getBoundingClientRect();
      cursor.style.left = (fr.left + tr.left + tr.width / 2 - 4) + "px";
      cursor.style.top = (fr.top + tr.top + tr.height / 2 - 2) + "px";
      target.classList.add("kp-ai-target");
      await aiSleep(420);
      cursor.classList.remove("click"); void cursor.offsetWidth; cursor.classList.add("click");
      await aiSleep(300);
      target.classList.remove("kp-ai-target");
    }
    try { host.contentWindow.postMessage({kpAiAction: action}, "*"); } catch(e) {}
    await aiSleep(180);
  }
  await aiSleep(250);
  cursor.classList.remove("show", "click");
}
window.addEventListener("message", (e) => {
  if (e.data && e.data.kpAiUi) playAiUi(e.data.kpAiUi);
});

function bindDrawers(){
  const aiTab=$("#ai-edge");
  if(aiTab) aiTab.onclick=()=>{ const d=$("#ai-drawer"); if(d && d.classList.contains("open")) closeAiDrawer(); else openAiDrawer(); };
  const bstatus=$("#bottle-status-btn"); if(bstatus) bstatus.onclick=toggleBottleStatusDrawer;
  const bclose=$("#bottle-status-close"); if(bclose) bclose.onclick=closeBottleStatusDrawer;
  const brefresh=$("#bottle-status-refresh"); if(brefresh) brefresh.onclick=refreshBottleStatus;
  const hist=$("#ai-history"); if(hist) hist.onclick=showAiHistory;
  const drawCfg=$("#ai-drawer-settings"); if(drawCfg) drawCfg.onclick=()=>{
    const f=$("#ai-drawer-frame");
    if(f && f.dataset.ready) toggleAiDrawerPanel("settings");
  };
  const pageHist=$("#ai-page-history"); if(pageHist) pageHist.onclick=()=>sendAiPageTab("history");
  const pageCfg=$("#ai-page-config"); if(pageCfg) pageCfg.onclick=()=>sendAiPageTab("settings");
  window.addEventListener("message",(e)=>{
    if(e.data && e.data.kpAiPanelState !== undefined){
      aiPagePanel = e.data.kpAiPanelState || null;
      aiDrawerPanel = e.data.kpAiPanelState || null;
      syncAiPageIcons();
      syncAiDrawerIcons();
      const dr=$("#ai-drawer");
      document.body.classList.toggle("ai-panel-open", !!aiDrawerPanel && dr && dr.classList.contains("open"));
    }
  });
  const openMod=$("#ai-drawer-open-module");
  if(openMod) openMod.onclick=()=>{ closeAiDrawer(); goPath("/ai/"); };
  document.addEventListener("keydown",(e)=>{ if(e.key==="Escape"){ closeAiDrawer(); closeBottleStatusDrawer(); const dbg=$("#debug"); if(dbg && dbg.classList.contains("open")) closeDebugDrawer(); } });
  window.addEventListener("resize",()=>{ try{ const h=document.querySelector("header.top"); if(h) document.documentElement.style.setProperty("--kp-header-h",h.offsetHeight+"px"); positionAiDrawer(); }catch(e){} });
}
bindDrawers();

async function checkBirthdayDateChange(){
  try {
    const tk = localStorage.getItem("kp_token");
    if (!tk) return;
    const r = await fetch("/api/theme", {cache:"no-store", headers:{Authorization:"Bearer "+tk}});
    const j = await r.json();
    if (!j || !j.theme) return;
    const prev = !!(userTheme && userTheme.birthday && userTheme.birthday.active);
    const now = !!(j.theme.birthday && j.theme.birthday.active);
    if (prev !== now) applyPalette(j.theme);
  } catch (e) {}
}
function startThemeDateWatch(){
  setTimeout(checkBirthdayDateChange, 5000);
  setInterval(checkBirthdayDateChange, 60000);
}
async function boot() {
  // 一次请求拿 session + tree + theme（少一个隧道往返）
  let b = null;
  try { b = await api("/api/bootstrap"); } catch (e) { b = null; }
  if (!b) {
    // 401 时 api() 已跳转到 /login，这里不再重复请求
    hideSplash();
    return;
  }
  if (!b.session) {
    $("#view-home").classList.remove("active");
    $("#view-project").classList.remove("active");
    $("#dbg-toggle").style.display = "none";
    showLogin();
    hideSplash();
    return;
  }
  hideLogin();
  app.session = b.session;
  const mm = $("#menu-manage");
  if (mm) mm.style.display = app.session.is_admin ? "" : "none";
  const bb = $("#bug-btn"); if (bb) bb.style.display = "";
  if (b.theme) { applyPalette(b.theme); cachePublicTheme(app.session.user, b.theme); }
  prefetchPublicThemes(["kitten", "puppy"]);
  applyRoleTheme();
  $("#who").innerHTML = "<b>" + esc(app.session.emoji || "") + " " + esc(app.session.user) +
    "</b> · " + esc(app.session.role || "");
  app.tree = b.tree || { root: null, errors: [] };
  app.nodes = {}; app.routes = {};
  indexTree(app.tree.root, null);
  setupDebug();
  routeFromLocation();
  hideSplash();
  updateDrawerTabs();
}

document.querySelectorAll(".role").forEach((b) => { b.onclick = () => selectRole(b.dataset.u); });
$("#lg-go").onclick = doLogin;
$("#lg-pwd").addEventListener("keydown", (e) => { if (e.key === "Enter") doLogin(); });
const lgMode = $("#lg-mode");
if (lgMode) lgMode.addEventListener("click", (e) => {
  e.preventDefault();
  setLoginMode(loginMode === "login" ? "register" : "login");
});
let lgUserTimer = null;
const lgUserInput = $("#lg-user");
if (lgUserInput) lgUserInput.addEventListener("input", () => {
  const u = lgUserInput.value.trim();
  if (!u) return;
  loginUser = u;
  localStorage.setItem("kp_login_user", u);
  document.querySelectorAll(".role").forEach((b) => b.classList.toggle("active", b.dataset.u === u));
  clearTimeout(lgUserTimer);
  lgUserTimer = setTimeout(() => loadPublicTheme(u), 300);
});
async function doLogout() {
  await fetch("/api/logout", { method: "POST" });
  try { sessionStorage.removeItem("kp_token"); localStorage.removeItem("kp_token"); } catch (e) {}
  try { localStorage.removeItem("kp_login_user"); } catch (e) {}
  app.session = null; app.current = null;
  location.replace("/login");
}
$("#back").onclick = () => goHome();
window.addEventListener("popstate", () => { if (app.session) routeFromLocation(); });


/* ---------------- Bug 反馈（实时本地草稿） ---------------- */
let bugTimer = null, bugBusy = false;

function bugDraftKey() { return "kp_bug_draft_" + ((app.session && app.session.user) || "anon"); }
function bugPageLabel() {
  const p = (app.current && app.current.title) || "工作台";
  return p + " · " + location.pathname;
}
function bugStatusText(st) {
  return { draft: "草稿", open: "待处理", doing: "处理中", fixed: "已修复", closed: "已关闭" }[st] || st;
}
function loadBugDraft() {
  try { return JSON.parse(localStorage.getItem(bugDraftKey()) || "null"); } catch (e) { return null; }
}
function saveBugDraftLocal(d) { try { localStorage.setItem(bugDraftKey(), JSON.stringify(d)); } catch (e) {} }

async function bugAutosave() {
  if (!app.session || bugBusy) return;
  const title = $("#bug-title").value.trim(), detail = $("#bug-detail").value.trim();
  const sev = $("#bug-sev").value;
  if (!title && !detail) return;
  bugBusy = true;
  try {
    const d = loadBugDraft() || {};
    const body = { id: d.id, page: bugPageLabel(), title, detail, severity: sev, draft: true };
    const r = await fetch("/api/bugreport", {
      method: "POST", headers: Object.assign(authHeaders(), { "Content-Type": "application/json" }),
      body: JSON.stringify(body),
    });
    const j = await r.json();
    if (j.ok) {
      d.id = j.report.id; d.title = title; d.detail = detail; d.severity = sev;
      saveBugDraftLocal(d);
      $("#bug-save").textContent = "已实时保存到本地 · " + new Date().toLocaleTimeString();
    }
  } catch (e) {} finally { bugBusy = false; }
}

function bugScheduleSave() {
  clearTimeout(bugTimer);
  bugTimer = setTimeout(bugAutosave, 600);
}

async function refreshBugList() {
  try {
    const j = await api("/api/bugreports");
    const box = $("#bug-list");
    box.innerHTML = "";
    $("#bug-list-title").textContent = app.session && app.session.is_admin ? "全部反馈（" + j.reports.length + "）" : "我的反馈（" + j.reports.length + "）";
    if (!j.reports.length) { box.innerHTML = '<div style="font-size:12px;color:var(--muted)">还没有反馈</div>'; return; }
    for (const r of j.reports.slice(0, 40)) {
      const row = document.createElement("div");
      row.className = "b-row";
      const head = document.createElement("div");
      head.className = "b-head";
      head.innerHTML = '<span class="b-status ' + r.status + '">' + bugStatusText(r.status) + "</span>" +
        '<b style="font-size:12.5px">' + esc(r.title || "(无标题)") + "</b>" +
        '<span style="color:var(--muted);font-size:11px">' + esc(r.user || "") + " · " + esc(r.page || "") + " · " +
        new Date((r.updated || 0) * 1000).toLocaleString() + "</span>";
      const acts = document.createElement("div"); acts.className = "b-actions";
      if (app.session && app.session.is_admin) {
        const sel = document.createElement("select");
        sel.innerHTML = ["open","doing","fixed","closed"].map((x) => '<option value="' + x + '">' + bugStatusText(x) + "</option>").join("");
        sel.value = ["open","doing","fixed","closed"].includes(r.status) ? r.status : "open";
        sel.onchange = async () => {
          try {
            await api("/api/bugreports/" + encodeURIComponent(r.id) + "/status", {
              method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status: sel.value }),
            });
            refreshBugList();
          } catch (e) { $("#bug-msg").textContent = "更新失败：" + e.message; }
        };
        acts.appendChild(sel);
      }
      head.appendChild(acts);
      row.appendChild(head);
      if (r.detail) {
        const d = document.createElement("div"); d.className = "b-detail"; d.textContent = r.detail;
        row.appendChild(d);
      }
      appendIssueComments(row, r, refreshBugList);
      box.appendChild(row);
    }
  } catch (e) {
    $("#bug-msg").textContent = "读取反馈失败：" + e.message;
  }
}

function openBug() {
  if (!app.session) return;
  const d = loadBugDraft();
  $("#bug-title").value = (d && d.title) || "";
  $("#bug-detail").value = (d && d.detail) || "";
  $("#bug-sev").value = (d && d.severity) || "normal";
  $("#bug-page").textContent = "当前页面：" + bugPageLabel();
  $("#bug-save").textContent = d && d.id ? "已恢复本地草稿 · 输入继续实时保存" : "草稿会实时保存到本机";
  $("#bug-msg").textContent = "";
  $("#bug-modal").classList.remove("hidden");
  refreshBugList();
}

async function submitBug() {
  const title = $("#bug-title").value.trim(), detail = $("#bug-detail").value.trim();
  if (!title && !detail) { $("#bug-msg").textContent = "至少写点标题或描述"; return; }
  const d = loadBugDraft() || {};
  try {
    const r = await fetch("/api/bugreport", {
      method: "POST", headers: Object.assign(authHeaders(), { "Content-Type": "application/json" }),
      body: JSON.stringify({ id: d.id, page: bugPageLabel(), title, detail, severity: $("#bug-sev").value, draft: false }),
    });
    const j = await r.json();
    if (!j.ok) throw new Error((j.error && j.error.message) || "提交失败");
    try { localStorage.removeItem(bugDraftKey()); } catch (e) {}
    $("#bug-title").value = ""; $("#bug-detail").value = ""; $("#bug-sev").value = "normal";
    $("#bug-save").textContent = "已提交，草稿已清空";
    $("#bug-msg").textContent = "已提交：" + j.report.id;
    refreshBugList();
  } catch (e) { $("#bug-msg").textContent = "提交失败：" + e.message; }
}

const bugBtn = $("#bug-btn");
if (bugBtn) bugBtn.onclick = openBug;
const bugClose = $("#bug-close");
if (bugClose) bugClose.onclick = () => $("#bug-modal").classList.add("hidden");
["bug-title", "bug-detail", "bug-sev"].forEach((id) => {
  const el = $("#" + id);
  if (el) { el.addEventListener("input", bugScheduleSave); el.addEventListener("change", bugScheduleSave); }
});
const bugSubmit = $("#bug-submit");
if (bugSubmit) bugSubmit.onclick = submitBug;

/* ---------------- 用户管理 ---------------- */
let adminData = null;

function fmtDuration(sec) {
  sec = Math.max(0, Math.floor(sec || 0));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60);
  if (h >= 24) return Math.floor(h / 24) + "天" + (h % 24) + "时";
  if (h > 0) return h + "时" + m + "分";
  return m + "分";
}

const AI_KINDS = [["deepseek","DeepSeek"],["openai","OpenAI"],["anthropic","Anthropic"],["openrouter","OpenRouter"],["moonshot","Moonshot"],["zhipu","智谱"],["qwen","通义千问"],["groq","Groq"],["mistral","Mistral"],["ollama","Ollama"],["dsh","本机 DSH"],["local","本地"],["custom","自定义"]];
function providerCard(p) {
  p = p || {};
  const id = p.id || ("p" + Math.random().toString(36).slice(2, 7));
  const opts = AI_KINDS.map(([v, t]) => '<option value="' + v + '"' + ((p.provider === v) ? " selected" : "") + '>' + t + '</option>').join("");
  const masks = (p.key_masks || []).join(" / ");
  return '<div class="mg-provider" data-id="' + escAttr(id) + '">' +
    '<div class="mg-provider-head"><input class="name p-name" value="' + escAttr(p.name || id) + '" placeholder="名称">' +
    '<label><input type="radio" name="providerActive" class="p-active"' + (p.active ? " checked" : "") + '> 当前</label>' +
    '<button class="mg-provider-del" type="button" title="删除">×</button></div>' +
    '<div class="mg-provider-grid">' +
    '<label class="sm-field">服务商<select class="p-kind">' + opts + '</select></label>' +
    '<label class="sm-field">模型<input class="p-model" value="' + escAttr(p.model || "") + '" placeholder="deepseek-chat"></label>' +
    '<label class="sm-field sm-span2">Base URL<input class="p-base" value="' + escAttr(p.base_url || "") + '" placeholder="https://api.deepseek.com/v1"></label>' +
    '<label class="sm-field">上下文窗口<input class="p-ctx" type="number" value="' + (p.context_window || 128000) + '"></label>' +
    '<label class="sm-field">Key 数量<input value="' + ((p.key_masks || []).length) + '" disabled></label>' +
    '</div>' +
    '<label class="sm-field" style="margin-top:7px">API Keys<textarea class="p-keys" placeholder="' + (p.has_key ? "已保存 " + (p.key_masks || []).length + " 个 Key：" + masks + "；留空保持不变，输入 CLEAR 清空，每行一个 Key" : "每行一个 Key") + '"></textarea></label>' +
    '<div class="hint">多 Key 时按顺序取第一个可用 Key；Key 仅保存在服务端，接口只返回掩码。</div></div>';
}
function escAttr(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c])); }
function renderManageProviders(list) {
  const box = $("#m-ai-providers");
  if (!box) return;
  box.innerHTML = (list && list.length) ? list.map(providerCard).join("") : providerCard({ active: true, provider: "deepseek", base_url: "https://api.deepseek.com/v1", model: "deepseek-chat", context_window: 128000 });
  box.querySelectorAll(".mg-provider-del").forEach(b => b.onclick = () => {
    const card = b.closest(".mg-provider"); const wasActive = card.querySelector(".p-active").checked;
    card.remove();
    if (wasActive) { const first = box.querySelector(".p-active"); if (first) first.checked = true; }
  });
}
const mAiSave = $("#m-ai-save");
if (mAiSave) mAiSave.onclick = () => saveManageAI(false);
const mAiTest = $("#m-ai-test");
if (mAiTest) mAiTest.onclick = () => saveManageAI(true);
const mMinEye = $("#m-mineru-eye"); if (mMinEye) mMinEye.onclick = () => { const inp = $("#m-mineru-token"); if (!inp) return; const show = inp.type === "password"; inp.type = show ? "text" : "password"; mMinEye.textContent = show ? "隐藏" : "显示"; };
const mMinSave = $("#m-mineru-save"); if (mMinSave) mMinSave.onclick = () => saveMineruToken(false);
const mMinCheck = $("#m-mineru-check"); if (mMinCheck) mMinCheck.onclick = () => checkMineruToken();
const mMinClear = $("#m-mineru-clear"); if (mMinClear) mMinClear.onclick = () => saveMineruToken(true);
const mAiAdd = $("#m-ai-add");
if (mAiAdd) mAiAdd.onclick = () => {
  const box = $("#m-ai-providers"); if (!box) return;
  const wasNone = !box.querySelector(".mg-provider");
  box.insertAdjacentHTML("beforeend", providerCard({ active: wasNone, provider: "deepseek", base_url: "", model: "", context_window: 128000 }));
  box.lastElementChild.querySelector(".mg-provider-del").onclick = () => box.lastElementChild.remove();
};
function renderMineruState(mu, message) {
  const pill = $("#m-mineru-pill"), status = $("#m-mineru-status"), bar = $("#m-mineru-bar"), msg = $("#m-mineru-msg");
  const configured = !!mu.configured;
  if (pill) {
    pill.textContent = configured ? (mu.days_left !== null && mu.days_left !== undefined && mu.days_left <= 7 ? "即将到期" : "已配置") : "未配置";
    pill.classList.toggle("ok", configured && !(mu.days_left !== null && mu.days_left !== undefined && mu.days_left <= 7));
    pill.classList.toggle("warn", configured && mu.days_left !== null && mu.days_left !== undefined && mu.days_left <= 7);
  }
  if (status) {
    let text = configured ? ("Token " + (mu.token_masked || "已配置")) : "未配置，PDF 解析将回退到 pypdf";
    if (configured && mu.expires_at) text += " · 到期 " + String(mu.expires_at).replace("T", " ").slice(0, 16) + "（剩余 " + mu.days_left + " 天）";
    status.textContent = text;
  }
  if (bar) {
    let pct = 0;
    if (configured && mu.days_left !== null && mu.days_left !== undefined) pct = Math.max(0, Math.min(100, (Number(mu.days_left) / 90) * 100));
    bar.style.width = pct + "%";
    bar.style.background = (mu.days_left !== null && mu.days_left !== undefined && mu.days_left <= 7) ? "#d8a227" : "";
  }
  if (msg && message) msg.textContent = message;
}
async function saveMineruToken(clear) {
  const input = $("#m-mineru-token"), msg = $("#m-mineru-msg");
  const token = input ? input.value.trim() : "";
  if (!clear && !token) { if (msg) msg.textContent = "请输入 MinerU Token"; return; }
  try {
    const j = await api("/api/llm/admin/mineru", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(clear ? {clear:true} : {token})});
    const mu = j.mineru || {};
    renderMineruState(mu, clear ? "已清除 MinerU Token" : "已保存 MinerU Token");
  } catch(e) { if (msg) msg.textContent = "保存失败：" + e.message; }
}
async function checkMineruToken() {
  const input = $("#m-mineru-token"), msg = $("#m-mineru-msg");
  try {
    const token = input ? input.value.trim() : "";
    const j = await api("/api/llm/admin/mineru/check", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(token ? {token} : {})});
    const c = j.check || {};
    const message = (c.valid ? "✅ " : "❌ ") + (c.message || "") + (c.days_left !== null && c.days_left !== undefined ? (" · 剩余 " + c.days_left + " 天（按保存时间估算）") : "");
    const mu = {configured: !!c.valid || !!c.expires_at, token_masked: "已配置", expires_at: c.expires_at, days_left: c.days_left};
    renderMineruState(mu, message);
  } catch(e) { if (msg) msg.textContent = "检查失败：" + e.message; }
}
function openManageAI() { showPane("manage-modal", "ai"); }
async function refreshManageAI() {
  try {
    const j = await api("/api/llm/admin");
    const g = j.global_ || {};
    const ps = j.providers || [];
    renderManageProviders(ps);
    $("#manage-ai-status").textContent = ps.length
      ? ("已配置 " + ps.length + " 个服务商 · " + ps.map(p => p.name + "(" + ((p.key_masks || []).length) + " key)").join(" / "))
      : "当前未配置全局 AI";
    const pill = $("#manage-ai-pill");
    if (pill) { pill.textContent = ps.length ? "已配置" : "未配置"; pill.classList.toggle("ok", ps.length > 0); }
    const mu = j.mineru || {};
    renderMineruState(mu);
    $("#m-ai-msg").textContent = "";
  } catch (e) { const m = $("#m-ai-msg"); if (m) m.textContent = "读取失败：" + e.message; }
}
function collectManageProviders() {
  return [...document.querySelectorAll("#m-ai-providers .mg-provider")].map((c, i) => ({
    id: c.dataset.id || ("p" + i),
    name: c.querySelector(".p-name").value.trim() || ("服务商" + (i + 1)),
    provider: c.querySelector(".p-kind").value,
    base_url: c.querySelector(".p-base").value.trim(),
    model: c.querySelector(".p-model").value.trim(),
    context_window: parseInt(c.querySelector(".p-ctx").value || "0", 10) || 0,
    keys_text: c.querySelector(".p-keys").value,
    active: c.querySelector(".p-active").checked,
  })).filter(p => p.base_url);
}
async function saveManageAI(test) {
  const providers = collectManageProviders();
  if (!providers.length) { $("#m-ai-msg").textContent = "至少配置一个带 Base URL 的服务商"; return; }
  try {
    await api("/api/llm/admin", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({providers})});
    if (test) {
      const j = await api("/api/llm/test", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({scope:"global"})});
      $("#m-ai-msg").textContent = "测试：" + JSON.stringify(j).slice(0, 300);
    } else {
      $("#m-ai-msg").textContent = "已保存 " + providers.length + " 个服务商配置";
    }
    await refreshManageAI();
  } catch(e) { $("#m-ai-msg").textContent = "操作失败：" + e.message; }
}

async function openUsers() {
  if (!app.session || !app.session.is_admin) return;
  $("#users-msg").textContent = "";
  try {
    adminData = await api("/api/admin/users");
  } catch (e) {
    alert("读取用户失败：" + e.message);
    return;
  }
  renderUsers();
  showPane("manage-modal", "users");
}

function renderUsers() {
  if (!adminData) return;
  const mods = adminData.modules || [];
  const me = app.session || {};
  $("#users-summary").textContent =
    "共 " + adminData.total + " 个可见用户 · 活跃 " + adminData.active_users + " 人（5 分钟内） · 累计在线 " + fmtDuration(adminData.total_active_seconds);

  const box = $("#users-list");
  box.innerHTML = "";
  for (const u of adminData.users) {
    const row = document.createElement("div");
    row.className = "u-row";

    const head = document.createElement("div");
    head.className = "u-head";
    const title = document.createElement("div");
    title.innerHTML = '<span class="u-name">' + (u.emoji || "🐱") + " " + esc(u.name || u.user) +
      '</span> <span class="u-dot ' + (u.active ? "on" : "") + '"></span>';
    const meta = document.createElement("span");
    meta.className = "u-meta";
    meta.textContent = (u.role_label || u.role) + " · 累计在线 " + fmtDuration(u.active_seconds) +
      (u.active ? " · 在线" : (u.last_seen ? " · 最近 " + new Date(u.last_seen * 1000).toLocaleString() : ""));
    head.appendChild(title); head.appendChild(meta);

    const acts = document.createElement("div");
    acts.className = "u-actions";
    const isSelf = u.user === me.user;
    const canTouch = !!u.can_manage;
    if (me.is_super && canTouch && u.role !== "superadmin") {
      const sel = document.createElement("select");
      sel.innerHTML = '<option value="user">成员</option><option value="admin">管理员</option>';
      sel.value = u.role;
      sel.onchange = async () => {
        try { await api("/api/admin/users/" + encodeURIComponent(u.user) + "/role", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ role: sel.value }) }); await openUsers(); }
        catch (e) { $("#users-msg").textContent = "改角色失败：" + e.message; }
      };
      acts.appendChild(sel);
    }
    if (canTouch) {
      const pwd = document.createElement("button");
      pwd.className = "btn soft sm"; pwd.textContent = "重置口令";
      pwd.onclick = async () => {
        const p = prompt("给 " + u.user + " 设置新口令（≥6位）");
        if (!p) return;
        try { await api("/api/admin/users/" + encodeURIComponent(u.user) + "/password", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password: p }) }); $("#users-msg").textContent = "口令已重置"; }
        catch (e) { $("#users-msg").textContent = "重置失败：" + e.message; }
      };
      acts.appendChild(pwd);
      const del = document.createElement("button");
      del.className = "btn ghost sm"; del.textContent = "删除";
      del.onclick = async () => {
        if (!confirm("删除用户 " + u.user + "？")) return;
        try { await api("/api/admin/users/" + encodeURIComponent(u.user), { method: "DELETE" }); await openUsers(); }
        catch (e) { $("#users-msg").textContent = "删除失败：" + e.message; }
      };
      acts.appendChild(del);
    }
    head.appendChild(acts);
    row.appendChild(head);

    // 模块访问 / 维护矩阵
    const grid = document.createElement("div");
    grid.className = "u-grid";
    for (const m of mods) {
      const cell = document.createElement("div");
      cell.className = "u-mod";
      const accessOn = u.role !== "user" ? true : !!(u.modules || {})[m.id];
      const access = document.createElement("label");
      access.innerHTML = '<input type="checkbox" ' + (accessOn ? "checked" : "") + ' ' +
        (u.can_manage && u.role === "user" ? "" : "disabled") + '> 访问';
      access.querySelector("input").onchange = async (e) => {
        try { await api("/api/admin/users/" + encodeURIComponent(u.user) + "/module", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ module: m.id, allow: e.target.checked }) }); await openUsers(); }
        catch (err) { $("#users-msg").textContent = "设置失败：" + err.message; }
      };
      cell.appendChild(access);

      if (u.role === "admin" && me.is_super && u.can_manage) {
        const maint = document.createElement("label");
        const on = !!(u.maintain || {})[m.id];
        maint.innerHTML = '<input type="checkbox" ' + (on ? "checked" : "") + '> 维护';
        maint.querySelector("input").onchange = async (e) => {
          try { await api("/api/admin/users/" + encodeURIComponent(u.user) + "/maintain", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ module: m.id, allow: e.target.checked }) }); await openUsers(); }
          catch (err) { $("#users-msg").textContent = "设置失败：" + err.message; }
        };
        cell.appendChild(maint);
      }
      const name = document.createElement("span");
      name.textContent = (m.icon || "") + " " + m.title;
      cell.appendChild(name);
      grid.appendChild(cell);
    }
    row.appendChild(grid);
    box.appendChild(row);
  }
}

/* ---------------- 顶栏用户菜单 / 统一弹窗 ---------------- */
const userChip = $("#user-chip"), userMenu = $("#user-menu");
if (userChip) userChip.onclick = (e) => {
  e.stopPropagation();
  userMenu.classList.toggle("hidden");
};
document.addEventListener("click", (e) => {
  if (!userMenu || userMenu.classList.contains("hidden")) return;
  if (userMenu.contains(e.target) || userChip.contains(e.target)) return;
  userMenu.classList.add("hidden");
});
if (userMenu) userMenu.querySelectorAll("button[data-menu]").forEach((b) => {
  b.onclick = async () => {
    userMenu.classList.add("hidden");
    const act = b.dataset.menu;
    if (act === "settings") openSettings();
    else if (act === "bug") openBug();
    else if (act === "manage") openUsers();
    else if (act === "switch" || act === "logout") await doLogout();
  };
});

const BB_MESSAGES = [
  "正在把愿望折好…",
  "正在挑选一片安静的水面…",
  "正在给瓶子塞上软木塞…",
  "正在解算所有瓶子的位置…",
  "正在投放…"
];
let bbRev = 0, bbOpenAt = "", bbTimer = null, bbBusy = false;

function bbLocalDate(d) {
  return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
}
function bbNextBirthday(value) {
  const now = new Date();
  let md = "";
  if (/^\d{4}-\d{2}-\d{2}$/.test(value || "")) md = value.slice(5);
  else if (/^\d{2}-\d{2}$/.test(value || "")) md = value;
  if (!md) { const x = new Date(now); x.setFullYear(x.getFullYear() + 1); return bbLocalDate(x); }
  let y = now.getFullYear();
  let d = new Date(y + "-" + md + "T00:00:00");
  if (d <= now) d = new Date((y + 1) + "-" + md + "T00:00:00");
  return bbLocalDate(d);
}
function bbPosition() {
  const el = $("#birthday-bottle-pop");
  if (!el) return;
  requestAnimationFrame(() => {
    const r = el.getBoundingClientRect();
    el.style.left = Math.max(10, Math.round((innerWidth - r.width) / 2)) + "px";
    el.style.top = "72px";
  });
}
function bbForm(show) {
  $("#birthday-bottle-pop .bb-form").style.display = show ? "" : "none";
  $("#bb-progress").classList.toggle("show", !show);
}
async function openBirthdayBottleModal() {
  if (!app.session) return;
  try {
    const [bd, st] = await Promise.all([api("/api/birthday"), api("/api/p/bottle/state")]);
    bbOpenAt = bbNextBirthday(bd.birthday || "");
    bbRev = st.rev;
    const user = app.session.user;
    $("#bb-to").textContent = (app.session.emoji || "") + " " + user;
    $("#bb-open").textContent = bbOpenAt;
    $("#bb-message").value = "";
    $("#bb-msg").textContent = "";
    $("#bb-done").classList.remove("show");
    $("#birthday-bottle-pop .bb-form").style.display = "";
    $("#bb-progress").classList.remove("show");
    $("#bb-submit").disabled = false;
    $("#birthday-bottle-pop").classList.add("show");
    bbPosition();
    setTimeout(() => $("#bb-message").focus(), 80);
  } catch (e) { alert("生日漂流瓶暂时打不开：" + e.message); }
}
function bbClose() {
  $("#birthday-bottle-pop").classList.remove("show");
  if (bbTimer) { clearInterval(bbTimer); bbTimer = null; }
  bbBusy = false;
}
async function submitBirthdayBottle() {
  if (bbBusy) return;
  const message = ($("#bb-message").value || "").trim();
  if (!message) { $("#bb-msg").textContent = "写一句给自己吧。"; return; }
  bbBusy = true;
  $("#bb-msg").textContent = "";
  $("#birthday-bottle-pop .bb-form").style.display = "none";
  $("#bb-done").classList.remove("show");
  $("#bb-progress").classList.add("show");
  let i = 0;
  $("#bb-pmsg").textContent = BB_MESSAGES[0];
  if (bbTimer) clearInterval(bbTimer);
  bbTimer = setInterval(() => {
    i = (i + 1) % BB_MESSAGES.length;
    const el = $("#bb-pmsg");
    el.textContent = BB_MESSAGES[i];
  }, 520);
  const started = Date.now();
  try {
    await api("/api/p/bottle/action", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({action: "create", rev: bbRev, payload: {to: app.session.user, openAt: bbOpenAt, message: message}})
    });
    const remain = Math.max(0, 2600 - (Date.now() - started));
    await new Promise(r => setTimeout(r, remain));
    if (bbTimer) { clearInterval(bbTimer); bbTimer = null; }
    $("#bb-progress").classList.remove("show");
    $("#bb-done").classList.add("show");
    bbBusy = false;
  } catch (e) {
    if (bbTimer) { clearInterval(bbTimer); bbTimer = null; }
    $("#bb-progress").classList.remove("show");
    $("#birthday-bottle-pop .bb-form").style.display = "";
    $("#bb-msg").textContent = "投放失败：" + e.message;
    bbBusy = false;
  }
}
function openSettings() {
  if (!app.session) return;
  $("#theme-custom").value = (userTheme && userTheme.color) || "#ec9fbe";
  $("#theme-colormap").value = (userTheme && userTheme.colormap) || "monochrome";
  $("#theme-msg").textContent = "";
  themeSwatches();
  previewPalette();
  if (userTheme && userTheme.birthday) $("#theme-msg").textContent = "今天是你的生日主题，系统自动应用，暂不可更换。";
  loadBasicInfo();
  showPane("settings-modal", "basic");
}

function showPane(modalId, pane) {
  const modal = document.getElementById(modalId);
  if (!modal) return;
  const head = modal.querySelector(".sm-head b");
  if (head) head.textContent = (pane === "basic" ? "基本信息" : pane === "theme" ? "主题" : head.textContent);
  modal.querySelectorAll(".sm-item").forEach((it) => it.classList.toggle("active", it.dataset.pane === pane));
  modal.querySelectorAll(".sm-pane").forEach((p) => p.classList.toggle("active", p.id === "pane-" + pane));
  modal.classList.remove("hidden");
  if (modalId === "manage-modal" && pane === "feedback") refreshManageBugs();
  if (modalId === "manage-modal" && pane === "stats") renderManageStats();
  if (modalId === "manage-modal" && pane === "ai") refreshManageAI();
}

$("#bb-close").onclick = bbClose;
$("#bb-cancel").onclick = bbClose;
$("#bb-done-close").onclick = bbClose;
$("#bb-submit").onclick = submitBirthdayBottle;

document.querySelectorAll(".sm-item").forEach((it) => {
  it.onclick = () => showPane(it.closest(".modal").id, it.dataset.pane);
});
document.querySelectorAll("[data-close]").forEach((b) => {
  b.onclick = () => document.getElementById(b.dataset.close).classList.add("hidden");
});

const themeSaveBtn = $("#theme-save");
if (themeSaveBtn) themeSaveBtn.onclick = saveUserTheme;
const themeApplyBtn = $("#theme-apply");
if (themeApplyBtn) themeApplyBtn.onclick = () => {
  if (userTheme && userTheme.birthday) { $("#theme-msg").textContent = "生日主题不可更换。"; return; }
  const p = computePalette($("#theme-custom").value || "#ec9fbe", $("#theme-colormap").value || "monochrome");
  applyPalette(p);
  paintPalettePreview(p);
  paintCmapPreview(p.colormap);
  $("#theme-msg").textContent = "已应用到当前界面（点保存才写入账号）";
};
function birthdayAgeText(birthday){
  if (!birthday || !/^\d{4}-\d{2}-\d{2}$/.test(birthday)) return "";
  const b = new Date(birthday + "T00:00:00");
  const n = new Date();
  let age = n.getFullYear() - b.getFullYear();
  const md = String(b.getMonth() + 1).padStart(2, "0") + "-" + String(b.getDate()).padStart(2, "0");
  if (String(n.getMonth() + 1).padStart(2, "0") + "-" + String(n.getDate()).padStart(2, "0") < md) age--;
  return age >= 0 ? age + " 岁" : "";
}
function loadBasicInfo(){
  fetch("/api/birthday", {cache:"no-store"}).then(r=>r.json()).then(j=>{
    if (!j || !j.ok) return;
    const el = $("#birthday-full");
    if (el) {
      let v = j.birthday || "";
      if (/^\d{2}-\d{2}$/.test(v)) v = "";
      el.value = v;
      const age = $("#birthday-age");
      if (age) age.textContent = birthdayAgeText(v) ? "当前年龄：" + birthdayAgeText(v) : "填写年份后可显示年龄";
    }
  }).catch(()=>{});
}
const birthdaySaveBasic = $("#birthday-save-basic");
if (birthdaySaveBasic) birthdaySaveBasic.onclick = async () => {
  const val = ($("#birthday-full").value || "").trim();
  try {
    const r = await fetch("/api/birthday", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({birthday:val})});
    const j = await r.json();
    if (!r.ok || !j.ok) throw new Error((j.error && j.error.message) || "保存失败");
    const age = $("#birthday-age");
    if (age) age.textContent = val ? ("当前年龄：" + (birthdayAgeText(val) || "未知")) : "填写年份后可显示年龄";
    $("#birthday-msg").textContent = val ? "生日已保存：" + val : "生日已清除";
    loadBasicInfo();
  } catch(e) { $("#birthday-msg").textContent = "保存失败：" + e.message; }
};
const themeCustom = $("#theme-custom"), themeColormap = $("#theme-colormap");
if (themeCustom) themeCustom.addEventListener("input", previewPalette);
if (themeColormap) themeColormap.addEventListener("change", previewPalette);



function appendIssueComments(row, r, reload) {
  const box = document.createElement("div");
  box.className = "gh-comments";
  const comments = Array.isArray(r.comments) ? r.comments : [];
  comments.forEach((c) => {
    const el = document.createElement("div");
    el.className = "gh-comment";
    el.innerHTML = '<span class="who">' + esc(c.user || "") + " · " + new Date((c.created || 0) * 1000).toLocaleString() + "</span>" + esc(c.text || "");
    box.appendChild(el);
  });
  const reply = document.createElement("div");
  reply.className = "gh-reply";
  const input = document.createElement("input");
  input.placeholder = comments.length ? "回复这个 issue…" : "写下第一条回复…";
  const btn = document.createElement("button");
  btn.className = "btn ghost sm"; btn.textContent = "回复";
  const send = async () => {
    const text = input.value.trim();
    if (!text) return;
    try {
      await api("/api/bugreports/" + encodeURIComponent(r.id) + "/comments", {
        method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({text})
      });
      reload();
    } catch (e) { $("#manage-bug-msg").textContent = "回复失败：" + e.message; }
  };
  btn.onclick = send;
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") send(); });
  reply.appendChild(input); reply.appendChild(btn); box.appendChild(reply);
  row.appendChild(box);
}

async function refreshManageBugs() {
  try {
    const j = await api("/api/bugreports");
    const box = $("#manage-bug-list");
    const sum = $("#manage-bug-summary");
    box.innerHTML = "";
    const reports = j.reports || [];
    const openCount = reports.filter(r => ["open", "doing"].includes(r.status)).length;
    const closedCount = reports.length - openCount;
    sum.textContent = "全部 " + reports.length + " 条 · Open " + openCount + " · Closed " + closedCount;
    if (!reports.length) { box.innerHTML = '<div class="sm-hint">暂无反馈</div>'; return; }
    const setStatus = async (r, status) => {
      try {
        await api("/api/bugreports/" + encodeURIComponent(r.id) + "/status", {
          method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({status})
        });
        refreshManageBugs();
      } catch (e) { $("#manage-bug-msg").textContent = "更新失败：" + e.message; }
    };
    for (const r of reports.slice(0, 100)) {
      const isOpen = ["open", "doing"].includes(r.status);
      const row = document.createElement("div");
      row.className = "b-row gh-issue";
      const head = document.createElement("div");
      head.className = "gh-head";
      const idShort = (r.id || "").replace(/^bug-/, "").split("-")[0];
      head.innerHTML =
        '<span class="gh-state ' + (isOpen ? "open" : "closed") + '"><span class="gh-dot"></span>' +
        (isOpen ? "Open" : "Closed") + "</span>" +
        '<div class="gh-main"><div class="gh-title">' + esc(r.title || "(无标题)") + "</div>" +
        '<div class="gh-meta">#' + esc(idShort) + " · " + esc(r.user || "") +
        " · " + esc(r.page || "") + " · " + new Date((r.updated || 0) * 1000).toLocaleString() + "</div></div>";
      const labels = document.createElement("div");
      labels.className = "gh-labels";
      const sev = r.severity || "normal";
      if (sev !== "normal") labels.innerHTML += '<span class="gh-label sev-' + esc(sev) + '">' + esc(sev) + "</span>";
      if (r.status === "doing") labels.innerHTML += '<span class="gh-label doing">处理中</span>';
      if (r.status === "fixed") labels.innerHTML += '<span class="gh-label fixed">已修复</span>';
      head.appendChild(labels);

      const acts = document.createElement("div");
      acts.className = "gh-actions";
      if (isOpen) {
        if (r.status !== "doing") {
          const b = document.createElement("button");
          b.className = "btn soft sm gh-btn"; b.textContent = "标记处理中";
          b.onclick = () => setStatus(r, "doing"); acts.appendChild(b);
        }
        const fixed = document.createElement("button");
        fixed.className = "btn soft sm gh-btn"; fixed.textContent = "标记已修复";
        fixed.onclick = () => setStatus(r, "fixed"); acts.appendChild(fixed);
        const close = document.createElement("button");
        close.className = "btn soft sm gh-btn close"; close.textContent = "关闭 issue";
        close.onclick = () => setStatus(r, "closed"); acts.appendChild(close);
      } else {
        const reopen = document.createElement("button");
        reopen.className = "btn soft sm gh-btn reopen"; reopen.textContent = "重新打开";
        reopen.onclick = () => setStatus(r, "open"); acts.appendChild(reopen);
      }
      head.appendChild(acts);
      row.appendChild(head);
      if (r.detail) {
        const d = document.createElement("div"); d.className = "b-detail"; d.textContent = r.detail; row.appendChild(d);
      }
      appendIssueComments(row, r, refreshManageBugs);
      box.appendChild(row);
    }
  } catch (e) { $("#manage-bug-msg").textContent = "读取反馈失败：" + e.message; }
}

function renderManageStats() {
  const box = $("#manage-stats");
  if (!box || !adminData) return;
  const users = adminData.users || [];
  const modules = adminData.modules || [];
  box.innerHTML =
    '<div class="stat-card"><b>' + users.length + "</b>可见用户</div>" +
    '<div class="stat-card"><b>' + (adminData.active_users || 0) + "</b>活跃用户（5 分钟）</div>" +
    '<div class="stat-card"><b>' + fmtDuration(adminData.total_active_seconds) + "</b>累计在线</div>" +
    '<div class="stat-card"><b>' + modules.length + "</b>模块数</div>";
}

if (window.requestIdleCallback) requestIdleCallback(() => prefetchPublicThemes(["kitten", "puppy"]), { timeout: 3000 });
else setTimeout(() => prefetchPublicThemes(["kitten", "puppy"]), 1800);

boot().then(() => startThemeDateWatch()).catch((e) => {
  showLogin("加载失败：" + e.message);
  hideSplash();
});

/* 实时 FPS 角标：按 500ms 采样，只统计当前页面 rAF */
(function(){
  const el = document.getElementById("kp-fps");
  if (!el) return;
  let frames = 0, last = performance.now();
  function tick(now){
    frames++;
    const dt = now - last;
    if (dt >= 500) {
      const fps = Math.round(frames * 1000 / dt);
      frames = 0; last = now;
      el.textContent = fps + " FPS";
      el.classList.toggle("good", fps >= 50);
      el.classList.toggle("mid", fps >= 30 && fps < 50);
      el.classList.toggle("bad", fps < 30);
    }
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
})();
