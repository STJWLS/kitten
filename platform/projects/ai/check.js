
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
let me = null, statusData = null, hist = [], contextUsed = 0, pendingFiles = [];
let sessions = [], sessionId = null, sessionTitle = "新对话";
let histArchivedView = false;
let needsResponse = false, sessionUnread = false;
let histVisibleLimit = 30;
let dshMode = false, dshSessionId = "";
let aiSending = false, stopRequested = false, activeAbort = null, activeDshRunId = "";
let dshContextWindow = 1000000;
let modelContexts = {};
let lastUsage = {prompt_tokens: 0, completion_tokens: 0, total_tokens: 0};
const AI_TAGLINES = [
  {a:"和 ", b:" 聊聊，", c:"今天想", d:"做什么？"},
  {a:"把想法交给 ", b:"，", c:"慢慢", d:"聊清楚。"},
  {a:"今天也，和 ", b:" 说说话。", c:"", d:""},
  {a:"不着急，和 ", b:" 一件一件来。", c:"", d:""},
  {a:"想说什么，就和 ", b:" 说。", c:"", d:""}
];
let aiTagIdx = Math.floor(Math.random() * AI_TAGLINES.length);
const EFFORTS = [{id:"low",name:"低"},{id:"medium",name:"中"},{id:"high",name:"高"}];
let effortValue = "high";
function modelLabel(){
  const s = document.querySelector("#model-select");
  return (s && s.value) ? s.value : "AI";
}
function renderSlogan(){
  const el = document.querySelector("#ai-slogan"); if (!el) return;
  const t = AI_TAGLINES[aiTagIdx] || AI_TAGLINES[0];
  el.innerHTML = esc(t.a) + '<span class="tag-model">' + esc(modelLabel()) + "</span>" + esc(t.b) +
    (t.c ? esc(t.c) : "") + (t.d ? "<em>" + esc(t.d) + "</em>" : "");
}
function histKey(){ return "kp_ai_history_" + ((me && me.user) || "anon"); }
function loadHist(){ try { hist = JSON.parse(localStorage.getItem(histKey()) || "[]"); } catch(e){ hist = []; } }
function saveHist(){ try { localStorage.setItem(histKey(), JSON.stringify(hist.slice(-300))); } catch(e){} }
function currentModule(){ return new URLSearchParams(location.search).get("module") || ""; }
function titleFromMessages(msgs){ const m = (msgs || []).find(x => x.role === "user" && (x.text || x.content)); return m ? String(m.text || m.content).replace(/\s+/g, " ").slice(0, 36) : "新对话"; }
function renderSessionSelect(){ /* 会话下拉已移除，历史面板使用双标签 */ }
async function refreshSessions(){
  const j = await api("/api/ai/sessions"); sessions = j.sessions || []; renderSessionSelect(); renderHistory();
}
async function loadSession(id){
  const j = await api("/api/ai/sessions/" + encodeURIComponent(id));
  const d = j.session || {};
  sessionId = d.id; sessionTitle = d.title || "新对话";
  dshSessionId = d.dsh_session_id || "";
  needsResponse = !!d.needs_response; sessionUnread = !!d.unread;
  if (dshMode && d.dsh_model) { const sel = $("#model-select"); if (sel) { if (![...sel.options].some(o => o.value === d.dsh_model)) sel.insertAdjacentHTML("beforeend", '<option value="' + esc(d.dsh_model) + '">' + esc(d.dsh_model) + "</option>"); sel.value = d.dsh_model; } if (modelContexts[d.dsh_model]) dshContextWindow = Number(modelContexts[d.dsh_model]); }
  if (dshMode && d.dsh_effort) { effortValue = d.dsh_effort; updateModelTrigger(); }
  histVisibleLimit = 30;
  hist = (d.messages || []).map(m => ({role: m.role, text: m.content !== undefined ? m.content : (m.text || ""), time: m.time, files: m.files || [], stopped: !!m.stopped, events: m.events || []}));
  if (d.usage) {
    lastUsage = {prompt_tokens: d.usage.prompt_tokens || 0, completion_tokens: d.usage.completion_tokens || 0, total_tokens: d.usage.total_tokens || 0};
    contextUsed = lastUsage.total_tokens || 0;
  }
  if (d.context_window) dshContextWindow = Number(d.context_window) || dshContextWindow;
  saveHist(); try { localStorage.setItem("kp_ai_current_session", sessionId); } catch(e){}
  renderChat(); renderHistory(); renderSessionSelect(); renderContext(); renderSlogan();
  if (d.unread) { sessionUnread = false; try { await persistSession(); } catch(e) {} }
}
async function newSession(){
  const j = await postJson("/api/ai/sessions/save", {session: {title: "新对话", module: currentModule(), messages: []}});
  sessionId = j.session.id; sessionTitle = j.session.title; hist = []; dshSessionId = ""; needsResponse = false; sessionUnread = false; histVisibleLimit = 30;
  saveHist(); try { localStorage.setItem("kp_ai_current_session", sessionId); } catch(e){}
  await refreshSessions(); renderChat(); renderHistory(); showPanel("chat");
}
async function initSessions(){
  const j = await api("/api/ai/sessions"); sessions = j.sessions || [];
  const activeSessions = sessions.filter(x => !x.archived);
  if (activeSessions.length) {
    let wanted = null; try { wanted = localStorage.getItem("kp_ai_current_session"); } catch(e){}
    const pick = activeSessions.find(x => x.id === wanted) || activeSessions[0];
    try { await loadSession(pick.id); renderSessionSelect(); return; }
    catch(e) { /* stale/deleted session: fall back to a fresh one */ }
  }
  const j2 = await postJson("/api/ai/sessions/save", {session: {title: titleFromMessages(hist), module: currentModule(),
    messages: sessionMessages(), usage: lastUsage, context_window: (statusData && statusData.effective && statusData.effective.context_window) || 0}});
  sessionId = j2.session.id; sessionTitle = j2.session.title; await refreshSessions(); renderSessionSelect();
}
function sessionMessages(){
  return hist.map(m => ({role: m.role, content: m.text || "", time: m.time, files: m.files || [], stopped: !!m.stopped, events: m.events || []}));
}
async function persistSession(){
  if (!sessionId) { await newSession(); return; }
  try {
    sessionTitle = titleFromMessages(hist);
    const j = await postJson("/api/ai/sessions/save", {session: {id: sessionId, title: sessionTitle, module: currentModule(),
      messages: sessionMessages(), usage: lastUsage, context_window: (statusData && statusData.effective && statusData.effective.context_window) || 0,
      dsh_session_id: dshSessionId,
      dsh_model: dshMode ? ($("#model-select").value || "") : "",
      dsh_effort: dshMode ? effortValue : "",
      needs_response: needsResponse, unread: sessionUnread}});
    sessionTitle = j.session.title; try { localStorage.setItem("kp_ai_current_session", sessionId); } catch(e){}
    await refreshSessions();
  } catch(e){ console.warn("session save failed", e); }
}
function downloadText(name, text, mime){
  const blob = new Blob([text], {type: mime || "text/plain;charset=utf-8"});
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name;
  document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
function conversationMarkdown(){
  let out = "# " + (sessionTitle || "对话") + "\n\n";
  for (const m of hist) out += "## " + (m.role === "user" ? "我" : "AI") + "\n\n" + (m.text || "") + "\n\n";
  return out;
}
function parseConversation(text){
  const raw = String(text || "");
  if (raw.trim().startsWith("{")) {
    const d = JSON.parse(raw);
    const arr = d.messages || (d.session && d.session.messages) || (Array.isArray(d) ? d : null);
    if (Array.isArray(arr)) return arr.map(m => ({role: m.role === "assistant" ? "assistant" : "user", text: m.content || m.text || "", time: m.time || Date.now()}));
    throw new Error("JSON 中没有 messages");
  }
  const out = [];
  const parts = raw.split(/^##\s+(我|AI)\s*$/m);
  for (let i = 1; i < parts.length; i += 2) out.push({role: parts[i] === "我" ? "user" : "assistant", text: parts[i + 1].trim(), time: Date.now()});
  if (!out.length) throw new Error("无法识别对话格式");
  return out;
}
async function postJson(path, body) {
  return api(path, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
}
async function api(path, opts) {
  const r = await fetch(path, Object.assign({cache:"no-store"}, opts || {}));
  const j = await r.json().catch(() => ({ok:false,error:{message:"非 JSON"}}));
  if (!r.ok || !j.ok) throw new Error((j.error && j.error.message) || ("HTTP " + r.status));
  return j;
}
function setMsg(t){ $("#msg").textContent = t || ""; }
function renderFileChips(){
  const box = $("#file-chips"); if (!box) return;
  box.innerHTML = pendingFiles.map(f => {
    const thumb = String(f.mime || "").startsWith("image/") ? '<img class="ai-file-thumb" src="/api/files/' + encodeURIComponent(f.id) + '" alt="">' : "";
    return '<span class="ai-file-chip" data-id="' + f.id + '">' +
      '<a href="/api/files/' + encodeURIComponent(f.id) + '" target="_blank" rel="noopener">' + thumb + esc(f.name) + "</a>" +
      '<button class="rm" type="button" title="移除">×</button></span>';
  }).join("");
  box.querySelectorAll(".rm").forEach(btn => btn.onclick = () => {
    const id = btn.closest(".ai-file-chip").dataset.id;
    pendingFiles = pendingFiles.filter(x => x.id !== id); renderFileChips();
  });
}
function fileToBase64(file){
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result || "").split(",", 2)[1] || "");
    r.onerror = reject;
    r.readAsDataURL(file);
  });
}
async function uploadFiles(files){
  const arr = [...(files || [])];
  for (const file of arr) {
    if (file.size > 16 * 1024 * 1024) { $("#chat-hint").textContent = "文件超过 16MB：" + file.name; continue; }
    try {
      $("#chat-hint").textContent = "上传中：" + file.name;
      const data = await fileToBase64(file);
      const j = await api("/api/files/upload", {method:"POST",headers:{"Content-Type":"application/json"},
        body: JSON.stringify({name:file.name, mime:file.type || "application/octet-stream", data})});
      pendingFiles.push(j.file);
      renderFileChips();
      $("#chat-hint").textContent = "已加密保存：" + j.file.name;
    } catch(e) { $("#chat-hint").textContent = "上传失败：" + e.message; }
  }
}
let currentPanel = null;
let panelTimer = null;
const kpInitialPanel = new URLSearchParams(location.search).get("panel");
const kpValidInitialPanel = (kpInitialPanel === "history" || kpInitialPanel === "settings") ? kpInitialPanel : "";
let kpPinInitialPanel = !!kpValidInitialPanel;
setTimeout(() => { kpPinInitialPanel = false; }, 1800);
function applyPanel(name) {
  currentPanel = name || null;
  $("#history-pane").classList.toggle("open", name === "history");
  $("#settings-pane").classList.toggle("open", name === "settings");
  document.body.classList.toggle("panel-open", !!name);
  if (name === "history") { renderHistory(); refreshSessions().then(renderHistory).catch(() => {}); }
  if (window.parent !== window) { try { window.parent.postMessage({kpAiPanelState: currentPanel}, "*"); } catch(e){} }
}
function showPanel(name) {
  if (kpPinInitialPanel && kpValidInitialPanel && (!name || name === "chat")) name = kpValidInitialPanel;
  if (name === "chat") name = null;
  if (name === "settings") showAiSettingsTab("main");
  clearTimeout(panelTimer);
  name = name || null;
  const drawerMode = document.body.classList.contains("drawer-mode");
  // 抽屉内直接切换；普通页面切换时先关闭当前面板，避免两个面板同时出现
  if (!drawerMode && currentPanel && name && currentPanel !== name) {
    applyPanel(null);
    panelTimer = setTimeout(() => applyPanel(name), 180);
  } else {
    applyPanel(name);
  }
}
function workFromEvents(events){
  const items = []; let thought = null; let thoughtHasDelta = false; const tools = {};
  for (const ev of (events || [])) {
    if (!ev || !ev.type) continue;
    if (ev.type === "session") { finalSessionId = ev.sessionId || finalSessionId; }
    else if (ev.type === "status" && ev.usage) { finalUsage = ev.usage; }
    if (ev.type === "reasoning_delta") {
      if (!thought) { thought = {type:"thought", title:"思考", text:"", status:""}; items.push(thought); thoughtHasDelta = false; }
      thought.text += ev.text || ""; thoughtHasDelta = true;
    } else if (ev.type === "thinking") {
      if (!thought) { thought = {type:"thought", title:"思考", text:"", status:""}; items.push(thought); }
      if (!thoughtHasDelta) thought.text += ev.text || "";
    } else if (ev.type === "tool_call") {
      thought = null; thoughtHasDelta = false;
      const item = {type:"tool", title:"工具 · " + (ev.tool || "tool"), text:"", status:"调用中"};
      try { item.text = JSON.stringify(ev.input || {}, null, 2); } catch(e) {}
      items.push(item); tools[ev.callId || ""] = item;
    } else if (ev.type === "tool_result") {
      const item = tools[ev.callId || ""];
      if (item) { item.status = ev.status || "完成"; item.text += "\n\n" + String(ev.result || "").slice(0, 4000); }
    } else if (ev.type === "user_answer") {
      thought = null; thoughtHasDelta = false;
      items.push({type:"answer", title:"你的回答", text:String(ev.text || ""), status:""});
    }
  }
  return items;
}
function renderWorkBlock(events, stopped){
  const block = document.createElement("div"); block.className = "ai-work";
  block.innerHTML = '<button class="ai-work-head" type="button"><span class="ai-work-title">' + (stopped ? "已停止" : "工作完成") + '</span><span class="ai-work-chev">▸</span></button><div class="ai-work-body hidden"></div>';
  const body = block.querySelector(".ai-work-body");
  block.querySelector(".ai-work-head").onclick = () => {
    const hid = body.classList.toggle("hidden");
    block.querySelector(".ai-work-chev").textContent = hid ? "▸" : "▾";
  };
  for (const w of workFromEvents(events)) {
    const item = document.createElement("div"); item.className = "ai-work-item";
    const title = w.type === "answer" ? "你的回答" : (w.title || "工作");
    item.innerHTML = '<button class="ai-work-item-head" type="button"><b>' + esc(title) + '</b><span class="wstatus">' + esc(w.status || "") + '</span><span class="wchev">▸</span></button><div class="ai-work-item-body"></div>';
    const ih = item.querySelector(".ai-work-item-head"), ib = item.querySelector(".ai-work-item-body");
    ib.textContent = w.text || "";
    ih.onclick = () => { const o = item.classList.toggle("open"); ih.querySelector(".wchev").textContent = o ? "▾" : "▸"; };
    body.appendChild(item);
  }
  if (events && events.length) {
    const item = document.createElement("div"); item.className = "ai-work-item";
    item.innerHTML = '<button class="ai-work-item-head" type="button"><b>完整事件流 · ' + events.length + '</b><span class="wchev">▸</span></button><div class="ai-work-item-body"></div>';
    const ih = item.querySelector(".ai-work-item-head"), ib = item.querySelector(".ai-work-item-body");
    ib.textContent = JSON.stringify(events, null, 2).slice(0, 120000);
    ih.onclick = () => { const o = item.classList.toggle("open"); ih.querySelector(".wchev").textContent = o ? "▾" : "▸"; };
    body.appendChild(item);
  }
  return block;
}

function renderChat(){
  const box = $("#chat-msgs");
  if (!box) return;
  box.innerHTML = "";
  const all = hist.filter(m => (m.text && String(m.text).trim()) || (m.files && m.files.length) || (m.events && m.events.length));
  const items = all.slice(-histVisibleLimit);
  if (all.length > items.length) {
    const more = document.createElement("button"); more.className = "ai-more"; more.type = "button";
    more.textContent = "加载更早的 " + (all.length - items.length) + " 条";
    more.onclick = () => { histVisibleLimit += 30; renderChat(); };
    box.appendChild(more);
  }
  items.forEach((m, idx) => {
    if (m.role !== "user" && m.role !== "answer" && m.events && m.events.length) box.appendChild(renderWorkBlock(m.events, !!m.stopped));
    const el = document.createElement("div");
    el.className = "ai-msg " + (m.role === "user" ? "user" : m.role === "answer" ? "answer" : "bot");
    const parsed = extractAsk(m.text || "");
    const body = m.role === "answer" ? "你的回答：" + (parsed.reply || m.text || "") : (parsed.reply || m.text || "");
    setMessageText(el, body, m.role !== "user" && m.role !== "answer");
    appendFilePills(el, m.files || []);
    const wrap = document.createElement("div");
    wrap.className = "ai-msg-wrap " + m.role;
    wrap.appendChild(el); el._kpWrap = wrap;
    attachMsgActions(el, m.role, m, wrap);
    box.appendChild(wrap);
    if (m.stopped) { const n = document.createElement("div"); n.className = "ai-stopped-note"; n.textContent = "已终止"; box.appendChild(n); }
    if (parsed.ask && m.role !== "user" && idx === items.length - 1) setTimeout(() => showAskPanel(parsed.ask), 0);
  });
  document.body.classList.toggle("has-chat", all.length > 0);
  box.scrollTop = box.scrollHeight;
}
function renderHistory(){
  const box = $("#hist-list"); if (!box) return;
  const items = (sessions || []).filter(x => !!x.archived === histArchivedView)
    .sort((a, b) => (Number(!!b.pinned) - Number(!!a.pinned)) || String(b.updated || b.created || "").localeCompare(String(a.updated || a.created || "")));
  document.querySelectorAll(".hist-tab").forEach(t => t.classList.toggle("active", String(t.dataset.arch) === (histArchivedView ? "1" : "0")));
  box.innerHTML = items.length ? items.map(s => {
    const when = s.updated ? new Date(s.updated).toLocaleString() : "";
    const mod = s.module ? s.module : "工作台";
    const running = s.running || (aiSending && s.id === sessionId);
    const state = running ? '<i class="ai-spinner" title="运行中"></i>' : s.needs_response ? '<i class="ai-dot yellow" title="需要你回答"></i>' : s.unread ? '<i class="ai-dot green" title="有新回复未读"></i>' : "";
    const pin = s.pinned ? '<span class="ai-hist-pin" title="已置顶">📌</span>' : "";
    const actions = histArchivedView
      ? '<button class="ai-hist-act ai-act-restore" data-act="restore" title="恢复到进行中">↩</button><button class="ai-hist-act ai-act-delete" data-act="delete" title="删除">🗑</button>'
      : '<button class="ai-hist-act ai-act-pin" data-act="pin" title="' + (s.pinned ? "取消置顶" : "置顶") + '">' + (s.pinned ? "📍" : "📌") + '</button><button class="ai-hist-act ai-act-archive" data-act="archive" title="归档">📦</button>';
    return '<div class="ai-hist-session' + (s.id === sessionId ? " active" : "") + (s.pinned ? " pinned" : "") + '" data-id="' + esc(s.id) + '">' +
      '<div class="ai-hist-title"><span class="ai-hist-state">' + state + '</span><span class="ai-hist-name">' + pin + esc(s.title || "新对话") + '</span><span class="ai-hist-time">' + esc(when) + '</span>' +
      '<span class="ai-hist-actions">' + actions + '</span></div>' +
      '<div class="ai-hist-meta">' + esc(mod) + ' · ' + (s.message_count || 0) + ' 条消息' + (s.pinned ? " · 置顶" : "") + '</div></div>';
  }).join("") : '<div class="ai-msg sys">' + (histArchivedView ? "还没有归档会话" : "还没有进行中的会话") + '</div>';
  box.querySelectorAll(".ai-hist-session").forEach(row => {
    row.onclick = async () => { try { await loadSession(row.dataset.id); showPanel(null); } catch(e) {} };
  });
  box.querySelectorAll(".ai-hist-act").forEach(btn => {
    btn.onclick = async (e) => {
      e.stopPropagation();
      const row = btn.closest(".ai-hist-session"); if (!row) return;
      const id = row.dataset.id, act = btn.dataset.act;
      try { await sessionAction(id, act); } catch(err) { setSessionMsg("操作失败：" + (err.message || err)); }
    };
  });
}
async function sessionAction(id, act){
  const s = (sessions || []).find(x => x.id === id);
  if (!s) return;
  if (act === "archive") {
    await postJson("/api/ai/sessions/flags", {id, archived: true, pinned: false});
    await refreshSessions();
    if (id === sessionId) {
      const next = (sessions || []).find(x => !x.archived);
      if (next) await loadSession(next.id); else await newSession();
    }
  } else if (act === "restore") {
    await postJson("/api/ai/sessions/flags", {id, archived: false});
    await refreshSessions();
  } else if (act === "pin") {
    await postJson("/api/ai/sessions/flags", {id, pinned: !s.pinned});
    await refreshSessions();
  } else if (act === "delete") {
    if (!confirm("删除这个已归档会话？此操作不可恢复。")) return;
    await postJson("/api/ai/sessions/delete", {id});
    await refreshSessions();
    if (id === sessionId) {
      const next = (sessions || []).find(x => !x.archived);
      if (next) await loadSession(next.id); else await newSession();
    }
  }
  renderHistory();
}

function renderStatus(){
  if (!statusData) return;
  const e = statusData.effective || {};
  const st = $("#status");
  if (st) {
    st.textContent = e.configured ? "" : "未配置 · " + (statusData.message || "请联系管理员配置服务端 AI");
  }
  $("#admin-note").style.display = me && me.is_admin ? "" : "none";
  const m = statusData.me || {};
  const mode = m.mode || "server";
  document.querySelectorAll('input[name="mode"]').forEach(r => r.checked = r.value === mode);
  $("#personal-form").style.opacity = mode === "server" ? ".72" : "1";
  $("#p-provider").value = m.provider || "";
  $("#p-base").value = m.base_url || "";
  $("#p-model").value = m.model || "";
  $("#p-key").placeholder = m.has_key ? ("已保存：" + m.key_masked + "（留空保持不变）") : "API Key";
  $("#chat-hint").textContent = dshMode ? "" : (e.configured ? "当前对话使用：" + (e.source === "override" ? "个人覆盖" : "服务端") + " · " + (e.model || "默认模型") : "");
  renderContext();
}
function effortName(){ return (EFFORTS.find(e => e.id === effortValue) || EFFORTS[1]).name; }
function applySelectedContextWindow(){
  if (!dshMode) return;
  const sel = $("#model-select");
  const w = sel && modelContexts[sel.value];
  if (w) dshContextWindow = Number(w) || dshContextWindow;
  renderContext();
}
function updateModelTrigger(){
  const sel = $("#model-select");
  const label = $("#model-label"); if (label) label.textContent = (sel && sel.value) || "未选择模型";
  const el = $("#effort-label"); if (el) el.textContent = effortName();
}
function renderContext(){
  const e = (statusData && statusData.effective) || {};
  const win = dshMode ? dshContextWindow : (e.context_window || 128000);
  const pct = Math.min(100, Math.round((contextUsed || 0) / win * 100));
  const circ = 2 * Math.PI * 5;
  const ring = $("#context-ring"); if (ring) ring.setAttribute("stroke-dasharray", (circ * pct / 100).toFixed(2) + " " + circ.toFixed(2));
  const p = $("#context-percent"); if (p) p.textContent = pct + "%";
  const fig = $("#context-figures"); if (fig) fig.textContent = "~" + fmtTokens(contextUsed) + " / " + fmtTokens(win);
  const bar = $("#context-bar"); if (bar) bar.style.width = pct + "%";
  const pTok = lastUsage.prompt_tokens || 0, cTok = lastUsage.completion_tokens || 0, tTok = lastUsage.total_tokens || (pTok + cTok);
  if ($("#ctx-prompt")) $("#ctx-prompt").textContent = "~" + fmtTokens(pTok);
  if ($("#ctx-completion")) $("#ctx-completion").textContent = "~" + fmtTokens(cTok);
  if ($("#ctx-total")) $("#ctx-total").textContent = "~" + fmtTokens(tTok);
  if ($("#ctx-left")) $("#ctx-left").textContent = "~" + fmtTokens(Math.max(0, win - (contextUsed || 0)));
}
function placeDshPopover(el, trigger){
  if (!el || !trigger) return;
  el.style.visibility = "hidden";
  el.classList.remove("hidden");
  const tr = trigger.getBoundingClientRect();
  const w = el.offsetWidth, h = el.offsetHeight, gap = 8;
  const below = innerHeight - tr.bottom - gap;
  const above = tr.top - gap;
  const up = below < h && above > below;
  let top = up ? (tr.top - h - gap) : (tr.bottom + gap);
  top = Math.max(8, Math.min(top, innerHeight - h - 8));
  let left = tr.right - w;
  left = Math.max(8, Math.min(left, innerWidth - w - 8));
  el.style.top = top + "px";
  el.style.left = left + "px";
  el.style.visibility = "";
}
function toggleDshPopover(el, trigger, renderer){
  const willOpen = el.classList.contains("hidden");
  closeDshMenus();
  if (!willOpen) return;
  if (renderer) renderer();
  placeDshPopover(el, trigger);
  trigger.setAttribute("aria-expanded", "true");
}
function renderModelMenu(){
  const sel = $("#model-select");
  const box = $("#model-list"); if (!box) return;
  const opts = [...(sel ? sel.options : [])].filter(o => o.value || o.text);
  box.innerHTML = opts.length ? opts.map(o => '<button type="button" class="dsh-option' + (sel.value === o.value ? " active" : "") + '" data-value="' + esc(o.value) + '"><span class="tick">' + (sel.value === o.value ? "✓" : "") + '</span><span class="opt-label">' + esc(o.textContent || o.value) + "</span></button>").join("") : '<div class="dsh-panel-note" style="padding:7px 8px">未搜索到模型</div>';
  box.querySelectorAll(".dsh-option").forEach(btn => btn.onclick = () => {
    if (sel) { sel.value = btn.dataset.value; sel.dispatchEvent(new Event("change")); }
    closeDshMenus(); updateModelTrigger();
  });
  const ebox = $("#effort-list");
  if (ebox) {
    ebox.innerHTML = EFFORTS.map(e => '<button type="button" class="dsh-option' + (effortValue === e.id ? " active" : "") + '" data-id="' + e.id + '"><span class="tick">' + (effortValue === e.id ? "✓" : "") + '</span><span class="opt-label">' + e.name + "</span></button>").join("");
    ebox.querySelectorAll(".dsh-option").forEach(btn => btn.onclick = () => {
      effortValue = btn.dataset.id; updateModelTrigger(); renderModelMenu(); closeDshMenus();
    });
  }
  updateModelTrigger();
}
function closeDshMenus(){
  $("#model-menu")?.classList.add("hidden");
  $("#context-panel")?.classList.add("hidden");
  $("#model-trigger")?.setAttribute("aria-expanded", "false");
  $("#context-trigger")?.setAttribute("aria-expanded", "false");
}
function fmtTokens(n){ n = Number(n || 0); return n >= 1000 ? (n / 1000).toFixed(n >= 10000 ? 0 : 1) + "k" : String(n); }
async function loadModels(){
  const sel = $("#model-select");
  if (!sel) return;
  let models = [];
  try {
    const j = await api("/api/llm/models");
    models = j.models || [];
  } catch(e) {}
  const eff = (statusData && statusData.effective) || {};
  const current = sel.value || eff.model || "";
  if (current && !models.includes(current)) models.unshift(current);
  sel.innerHTML = models.length ? models.map(m => '<option value="' + esc(m) + '"' + (m === current ? " selected" : "") + ">" + esc(m) + "</option>").join("") : '<option value="">未搜索到模型</option>';
  if (!models.length && eff.model) sel.value = eff.model;
  renderModelMenu();
  renderSlogan();
}
function renderMarkdown(text){
  if (!window.marked || !window.DOMPurify) return null;
  try {
    const blocks = [];
    let src = String(text || "");
    src = src.replace(/\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\]/g, (m, a, b) => {
      const tex = (a !== undefined ? a : b) || "";
      const token = "KPBLOCKMATH" + blocks.length + "TOKEN";
      blocks.push(tex);
      return token;
    });
    let html = window.marked.parse(src, {gfm:true, breaks:true});
    html = window.DOMPurify.sanitize(html, {USE_PROFILES:{html:true}});
    if (blocks.length && window.katex) {
      blocks.forEach((tex, i) => {
        let rendered = "";
        try { rendered = window.katex.renderToString(tex, {displayMode:true, throwOnError:false}); } catch(e) {}
        html = html.split("KPBLOCKMATH" + i + "TOKEN").join(rendered);
      });
    }
    return html;
  } catch(e) { return null; }
}
function renderMathIn(el){
  if (!el || !window.renderMathInElement) return;
  try {
    window.renderMathInElement(el, {
      delimiters: [
        {left:"$$", right:"$$", display:true},
        {left:"\\[", right:"\\]", display:true},
        {left:"\\(", right:"\\)", display:false},
        {left:"$", right:"$", display:false}
      ],
      throwOnError:false,
      ignoredTags:["script","noscript","style","textarea","pre","code"]
    });
  } catch(e) {}
}
function setMessageText(el, text, markdown){
  if (!el) return;
  el.dataset.rawText = String(text == null ? "" : text);
  if (markdown) {
    const html = renderMarkdown(el.dataset.rawText);
    if (html !== null) {
      el.innerHTML = html; el.classList.add("markdown"); renderMathIn(el); return;
    }
  }
  el.classList.remove("markdown"); el.textContent = el.dataset.rawText;
}
function messageText(el){ return el && el.dataset && el.dataset.rawText !== undefined ? el.dataset.rawText : (el ? el.textContent : ""); }
function extractAsk(reply){
  const raw = String(reply || "");
  const idx = raw.lastIndexOf("ASK_USER");
  if (idx < 0) return {reply: raw, ask: null};
  let rest = raw.slice(idx + 8).trim();
  if (rest.startsWith(":")) rest = rest.slice(1).trim();
  try {
    const ask = JSON.parse(rest);
    return {reply: raw.slice(0, idx).trim(), ask: (ask && ask.question) ? ask : null};
  } catch(e) {
    return {reply: raw, ask: null};
  }
}
function maybeShowAsk(el){
  if (!el || !dshMode) return;
  const parsed = extractAsk(messageText(el));
  if (!parsed.ask) return;
  setMessageText(el, parsed.reply || "已向你提问，请在下方选择或回答。", true);
  showAskPanel(parsed.ask);
}
function hideAskPanel(){ const p = $("#ask-panel"); if (p) p.classList.add("hidden"); }
function showAskPanel(ask){
  const panel = $("#ask-panel"); if (!panel || !ask) return;
  $("#ask-question").textContent = ask.question || "";
  const multiple = !!(ask.multiple || ask.multi || ask.type === "multi" || ask.type === "multiple");
  $("#ask-mode").textContent = (ask.options && ask.options.length) ? (multiple ? "多选题 · 可多选，点击「回答」提交" : "单选题 · 选择一项，点击「回答」提交") : "请输入你的回答";
  const opts = $("#ask-options"); opts.innerHTML = "";
  for (const o of (ask.options || [])) {
    const label = document.createElement("label"); label.className = "ai-ask-option";
    const input = document.createElement("input");
    input.type = multiple ? "checkbox" : "radio";
    input.name = "ask-choice"; input.value = o;
    const span = document.createElement("span"); span.textContent = o;
    label.appendChild(input); label.appendChild(span); opts.appendChild(label);
  }
  $("#ask-input").value = ""; panel.classList.remove("hidden");
}
function submitAskAnswer(){
  const selected = [...document.querySelectorAll("#ask-options input:checked")].map(x => x.value);
  const custom = ($("#ask-input").value || "").trim();
  const text = selected.length ? selected.join("；") : custom;
  if (!text) return;
  answerAsk(text);
}
function answerAsk(text){
  if (!text || !String(text).trim()) return;
  hideAskPanel();
  sendChat({answer: String(text).trim()});
}
function int0(v){ const n = Number(v); return Number.isFinite(n) ? Math.trunc(n) : 0; }
async function streamDsh(body, wait, answerText = "", signal = null, controller = null, onFinal = null){
  const res = await fetch("/api/ai/dsh/stream", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body), signal});
  if (!res.ok) {
    let msg = "HTTP " + res.status;
    try { const j = await res.json(); msg = (j.error && j.error.message) || msg; } catch(e) {}
    throw new Error(msg);
  }
  const work = document.createElement("div"); work.className = "ai-work";
  work.innerHTML = '<button class="ai-work-head" type="button"><span class="ai-work-title">工作中</span><span class="ai-work-time">00:00</span><span class="ai-work-chev">▾</span></button>' +
    '<div class="ai-work-body"></div>';
  (wait._kpWrap || wait).before(work);
  const workHead = work.querySelector(".ai-work-head"), workBody = work.querySelector(".ai-work-body"), timeEl = work.querySelector(".ai-work-time");
  const started = Date.now();
  const timer = setInterval(() => {
    const s = Math.floor((Date.now() - started) / 1000);
    timeEl.textContent = String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
  }, 250);
  workHead.onclick = () => {
    const hidden = workBody.classList.toggle("hidden");
    work.querySelector(".ai-work-chev").textContent = hidden ? "▸" : "▾";
  };
  let currentThought = null, streamedText = "", streamedThinking = "";
  const steps = {}, rawEvents = [];
  if (answerText) rawEvents.push({type:"user_answer", text:answerText, time:Date.now()});
  const addWorkItem = (title, open, type = "thought") => {
    const item = document.createElement("div"); item.className = "ai-work-item" + (open ? " open" : "");
    item.innerHTML = '<button class="ai-work-item-head" type="button"><b>' + esc(title) + '</b><span class="wstatus"></span><span class="wchev">' + (open ? "▾" : "▸") + '</span></button><div class="ai-work-item-body"></div>';
    const head = item.querySelector(".ai-work-item-head"), bodyEl = item.querySelector(".ai-work-item-body");
    head.onclick = () => { const o = item.classList.toggle("open"); head.querySelector(".wchev").textContent = o ? "▾" : "▸"; };
    workBody.appendChild(item);
    return item;
  };
  if (answerText) {
    const ans = addWorkItem("你的回答", false, "answer");
    ans.querySelector(".ai-work-item-body").textContent = answerText;
  }
  let workFinished = false;
  const finishWork = (stopped = false) => {
    if (workFinished) return;
    workFinished = true;
    clearInterval(timer);
    const secs = Math.floor((Date.now() - started) / 1000);
    work.querySelector(".ai-work-title").textContent = stopped ? "已停止" : "工作完成";
    timeEl.textContent = String(Math.floor(secs / 60)).padStart(2, "0") + ":" + String(secs % 60).padStart(2, "0");
    workBody.classList.add("hidden");
    work.querySelector(".ai-work-chev").textContent = "▸";
    try { wait._kpEvents = rawEvents; } catch(e) {}
  };
  const appendThought = (text) => {
    if (!text) return;
    if (!currentThought) currentThought = addWorkItem("思考", true, "thought");
    const bodyEl = currentThought.querySelector(".ai-work-item-body");
    bodyEl.textContent += text;
    workBody.scrollTop = workBody.scrollHeight;
    bodyEl.scrollTop = bodyEl.scrollHeight;
  };
  let buf = "", doneObj = null, streamError = "", finalSeen = false, finalText = "", finalSessionId = "", finalUsage = null, finalTimer = null;
  const reader = res.body.getReader(), decoder = new TextDecoder();
  const handle = (ev) => {
    if (!ev || !ev.type) return;
    if (rawEvents.length < 600) { try { rawEvents.push(JSON.parse(JSON.stringify(ev))); } catch(e) { rawEvents.push(ev); } }
    if (ev.type === "session") { finalSessionId = ev.sessionId || finalSessionId; }
    else if (ev.type === "status" && ev.usage) { finalUsage = ev.usage; }
    if (ev.type === "reasoning_delta") {
      streamedThinking += ev.text || ""; appendThought(ev.text || "");
    } else if (ev.type === "thinking") {
      if (!streamedThinking && ev.text) { streamedThinking = ev.text; appendThought(ev.text); }
    } else if (ev.type === "text_delta") {
      streamedText += ev.text || "";
      setMessageText(wait, streamedText, true); maybeShowAsk(wait);
    } else if (ev.type === "tool_call") {
      currentThought = null;
      const item = addWorkItem("工具 · " + (ev.tool || "tool"), false, "tool");
      item.dataset.callId = ev.callId || "";
      item.querySelector(".wstatus").textContent = "调用中…";
      item.querySelector(".ai-work-item-body").textContent = JSON.stringify(ev.input || {}, null, 2);
      steps[ev.callId || ""] = item;
      workBody.scrollTop = workBody.scrollHeight;
    } else if (ev.type === "tool_result") {
      const item = steps[ev.callId || ""];
      if (item) {
        item.querySelector(".wstatus").textContent = ev.status || "完成";
        item.querySelector(".ai-work-item-body").textContent += "\n\n" + String(ev.result || "").slice(0, 4000);
      }
    } else if (ev.type === "text" && ev.text) {
      if (!streamedText || String(ev.text).startsWith(streamedText)) setMessageText(wait, ev.text, true);
      maybeShowAsk(wait);
    } else if (ev.type === "final" && ev.text !== undefined) {
      finalSeen = true; finalText = String(ev.text || streamedText || "");
      if (!streamedText || String(ev.text).startsWith(streamedText)) setMessageText(wait, ev.text, true);
      maybeShowAsk(wait); finishWork();
      if (onFinal && !doneObj) {
        const u = finalUsage || {};
        onFinal({reply: finalText, dsh_session_id: finalSessionId, events: rawEvents,
          usage: {prompt_tokens: int0(u.inputTokens), completion_tokens: int0(u.outputTokens), total_tokens: int0(u.totalTokens)}});
      }
      if (finalTimer) { clearTimeout(finalTimer); finalTimer = null; }
      // Let the background stream finish so trailing tool UI actions can still arrive;
      // the send button is released by the Promise.race on `final`.
    } else if (ev.type === "run") {
      activeDshRunId = ev.run_id || "";
    } else if (ev.type === "done") {
      doneObj = ev;
      if (finalTimer) { clearTimeout(finalTimer); finalTimer = null; }
      if (window.parent !== window) {
        const uis = (ev.ui_events && ev.ui_events.length) ? ev.ui_events : (ev.ui ? [ev.ui] : []);
        if (uis.length) {
          setTimeout(() => { for (const u of uis) { try { window.parent.postMessage({kpAiUi: u}, "*"); } catch(e) {} } }, 0);
        }
      }
    } else if (ev.type === "error") {
      streamError = ev.message || "DSH 执行失败";
    }
  };
  try {
    while (true) {
      let r;
      try { r = await reader.read(); } catch(e) { if (finalSeen) break; throw e; }
      if (r.done) break;
      buf += decoder.decode(r.value, {stream:true});
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const frame = buf.slice(0, idx); buf = buf.slice(idx + 2);
        for (const line of frame.split("\n")) {
          if (!line.startsWith("data:")) continue;
          try { handle(JSON.parse(line.slice(5).trim())); } catch(e) {}
        }
      }
    }
    finishWork();
  } finally {
    if (signal && signal.aborted) finishWork(true);
    if (finalTimer) { clearTimeout(finalTimer); finalTimer = null; }
    activeDshRunId = "";
  }
  if (!doneObj && finalSeen) {
    const u = finalUsage || {};
    doneObj = {reply: finalText, dsh_session_id: finalSessionId, events: rawEvents,
      usage: {prompt_tokens: int0(u.inputTokens), completion_tokens: int0(u.outputTokens), total_tokens: int0(u.totalTokens)}};
  }
  if (streamError && !finalSeen) throw new Error(streamError);
  if (!doneObj) throw new Error("DSH 流结束但没有最终结果");
  doneObj.events = rawEvents;
  return doneObj;
}
async function loadDshStatus(){
  try {
    const j = await api("/api/ai/dsh/status");
    if (j.dsh && j.dsh.enabled) {
      const d = j.dsh;
      dshMode = true; document.body.classList.add("dsh-mode");
      dshContextWindow = Number(d.context_window || 1000000);
      modelContexts = d.model_contexts || {};
      const sel = $("#model-select");
      if (sel) {
        sel.innerHTML = (d.models || []).map(m => '<option value="' + esc(m) + '">' + esc(m) + "</option>").join("");
        sel.value = d.model || (d.models && d.models[0]) || "";
      }
      if (Array.isArray(d.efforts) && d.efforts.length) {
        EFFORTS.splice(0, EFFORTS.length, ...d.efforts.map(e => ({id: e.id, name: e.name || e.id})));
        effortValue = d.effort || (d.efforts[0] && d.efforts[0].id) || "high";
      }
      updateModelTrigger(); renderModelMenu(); applySelectedContextWindow(); renderSlogan();
      const b = $("#dsh-badge"); if (b) b.textContent = "DSH";
      const st = $("#status"); if (st) st.textContent = "";
    }
  } catch(e) {}
}
async function loadStatus(){ statusData = await api("/api/llm/status"); renderStatus(); if (!dshMode) await loadModels(); }
async function loadMe(){ const s = await api("/api/session"); me = s.session; loadHist(); }
function appendFilePills(el, files){
  if (!files || !files.length) return;
  const box = document.createElement("div"); box.className = "ai-msg-files";
  for (const f of files) {
    const a = document.createElement("a");
    a.className = "ai-file-pill"; a.href = "/api/files/" + encodeURIComponent(f.id || "");
    a.target = "_blank"; a.rel = "noopener"; a.title = f.name || "附件";
    a.innerHTML = "📄 <span>" + esc(f.name || "附件") + "</span>";
    box.appendChild(a);
  }
  el.appendChild(box);
}
async function copyTextToClipboard(text){
  const t = String(text == null ? "" : text);
  try { await navigator.clipboard.writeText(t); }
  catch(e) {
    const ta = document.createElement("textarea"); ta.value = t;
    ta.style.position = "fixed"; ta.style.opacity = "0"; document.body.appendChild(ta);
    ta.select(); try { document.execCommand("copy"); } catch(_) {}
    ta.remove();
  }
  setMsg("已复制");
}
function attachMsgActions(el, role, msgRef, host){
  if (!el || (role !== "user" && role !== "assistant")) return;
  const parent = host || el._kpWrap || el.parentElement;
  if (!parent) return;
  parent.querySelectorAll(":scope > .ai-msg-actions").forEach(x => x.remove());
  const bar = document.createElement("div"); bar.className = "ai-msg-actions";
  const copy = document.createElement("button"); copy.type = "button"; copy.className = "ai-msg-act";
  copy.textContent = "📋"; copy.title = "复制"; copy.setAttribute("aria-label", "复制");
  copy.onclick = (e) => { e.stopPropagation(); copyTextToClipboard(messageText(el)).catch(() => {}); };
  bar.appendChild(copy);
  if (role === "assistant") {
    const fork = document.createElement("button"); fork.type = "button"; fork.className = "ai-msg-act fork"; fork.textContent = "⑂";
    fork.title = "Fork：从此回答分叉出一个新会话"; fork.setAttribute("aria-label", "Fork");
    fork.onclick = (e) => { e.stopPropagation(); forkFromMessage(msgRef || el._kpMsg).catch(err => setMsg("Fork 失败：" + (err.message || err))); };
    bar.appendChild(fork);
  }
  el._kpMsg = msgRef || el._kpMsg || null;
  parent.appendChild(bar);
}
async function forkFromMessage(msgRef){
  if (!msgRef) return;
  const idx = hist.indexOf(msgRef);
  if (idx < 0) return;
  const branch = hist.slice(0, idx + 1).map(m => ({role: m.role, content: m.text || "", time: m.time || Date.now(), files: m.files || [], stopped: !!m.stopped, events: m.events || []}));
  const j = await postJson("/api/ai/sessions/save", {session: {
    title: (titleFromMessages(branch) || "分支") + " · 分支",
    module: currentModule(), messages: branch,
    usage: lastUsage, context_window: (statusData && statusData.effective && statusData.effective.context_window) || 0
  }});
  await refreshSessions();
  await loadSession(j.session.id);
  showPanel(null); setMsg("已创建分支会话");
}
function addMsg(text, cls, record, files){
  const el = document.createElement("div");
  el.className = "ai-msg " + (cls || "bot");
  setMessageText(el, text, cls !== "user" && cls !== "sys" && cls !== "answer");
  appendFilePills(el, files);
  const wrap = document.createElement("div");
  wrap.className = "ai-msg-wrap " + (cls || "bot");
  wrap.appendChild(el); el._kpWrap = wrap;
  $("#chat-msgs").appendChild(wrap); document.body.classList.add("has-chat");
  $("#chat-msgs").scrollTop = $("#chat-msgs").scrollHeight;
  if (record !== false){
    const rec = {role: cls === "user" ? "user" : "assistant", text, files: files || [], time: Date.now()};
    hist.push(rec); saveHist();
    attachMsgActions(el, rec.role, rec, wrap);
  }
  return el;
}
function showDshTrace(afterEl, events){
  const calls = (events || []).filter(e => e && e.type === "tool_call");
  if (!calls.length) return;
  const results = {};
  for (const e of events) if (e && e.type === "tool_result") results[e.callId] = e;
  const box = document.createElement("div"); box.className = "ai-trace";
  const rows = calls.slice(-8).map(c => {
    const r = results[c.callId];
    const name = (c.tool || "tool");
    const status = r ? (r.status || "completed") : "called";
    return '<div class="ai-trace-step"><b>' + esc(name) + '</b><span>' + esc(status) + "</span></div>";
  }).join("");
  box.innerHTML = '<div class="ai-trace-title">DSH 执行过程</div>' + rows;
  afterEl.after(box);
}

function updateSendButton(){
  const b = $("#chat-send"); if (!b) return;
  b.classList.toggle("stopping", aiSending);
  b.textContent = aiSending ? "■" : "↑";
  b.title = aiSending ? "停止" : "发送";
}
async function stopGeneration(){
  if (!aiSending) return;
  stopRequested = true;
  const rid = activeDshRunId;
  try { if (activeAbort) activeAbort.abort(); } catch(e) {}
  if (rid) {
    try { await postJson("/api/ai/dsh/stop", {run_id: rid}); } catch(e) {}
  }
}
async function sendChat(opts = {}){
  const input = $("#chat-in");
  const answerText = opts && opts.answer ? String(opts.answer).trim() : "";
  const text = answerText || ((input.value || "").trim());
  if (!text || aiSending) return;
  aiSending = true; stopRequested = false; activeAbort = new AbortController(); updateSendButton();
  const runSessionId = sessionId;
  needsResponse = false; sessionUnread = false;
  if (answerText) { hideAskPanel(); }
  else {
    input.value = ""; if (typeof autoGrow === "function") autoGrow(); hideAskPanel();
    const sentFiles = pendingFiles.slice();
    addMsg(text, "user", true, sentFiles);
  }
  if (answerText) hist.push({role:"answer", text, time:Date.now()});
  const sentFiles = pendingFiles.slice();
  const wait = addMsg("", "bot", false);
  try {
    let j;
    if (dshMode) {
      let resolveFinal;
      const finalPromise = new Promise(r => { resolveFinal = r; });
      j = await Promise.race([
        streamDsh({text, module: currentModule(),
          platform_session_id: sessionId, dsh_session_id: dshSessionId,
          model: $("#model-select").value || undefined, effort: effortValue,
          files: pendingFiles.map(f => f.id)}, wait, answerText, activeAbort.signal, activeAbort,
          (payload) => { try { resolveFinal(payload); } catch(e) {} }),
        finalPromise
      ]);
      dshSessionId = j.dsh_session_id || dshSessionId;
      if (j.context_window) dshContextWindow = Number(j.context_window) || dshContextWindow;
      setMessageText(wait, j.reply || "(空回复)", true);
      // DSH UI actions are posted by streamDsh when the done event arrives.
    } else {
      j = await api("/api/llm/chat", {method:"POST",headers:{"Content-Type":"application/json"},
        body: JSON.stringify({messages:[{role:"user",content:text}],
          model: $("#model-select").value || undefined, effort: effortValue, module: currentModule(),
          files: pendingFiles.map(f => f.id)})});
      setMessageText(wait, j.reply || "(空回复)", true);
      if (j.tool_results && j.tool_results.length) {
        for (const tr of j.tool_results) {
          addMsg("工具 " + tr.tool + "：" + JSON.stringify(tr.result).slice(0, 500), "sys", false);
          if (window.parent !== window && tr.result && tr.result.ui) {
            try { window.parent.postMessage({kpAiUi: tr.result.ui}, "*"); } catch(e) {}
          }
        }
      }
    }
    const askParsed = extractAsk(j.reply || messageText(wait) || "");
    j.reply = askParsed.reply;
    if (wait) setMessageText(wait, j.reply || (askParsed.ask ? "已向你提问，请在下方选择或回答。" : "(空回复)"), true);
    if (askParsed.ask && dshMode) showAskPanel(askParsed.ask);
    else hideAskPanel();
    needsResponse = !!(askParsed.ask && dshMode);
    sessionUnread = (sessionId !== runSessionId || currentPanel === "history");
    if (j.reply && String(j.reply).trim()) {
      const rec = {role:"assistant", text:j.reply, time:Date.now(), events:j.events || wait._kpEvents || []};
      hist.push(rec); attachMsgActions(wait, "assistant", rec);
    }
    saveHist();
    maybeShowAsk(wait);
    pendingFiles = []; renderFileChips();
    await persistSession();
    const u = j.usage || {};
    lastUsage = {prompt_tokens: u.prompt_tokens || 0, completion_tokens: u.completion_tokens || 0, total_tokens: u.total_tokens || 0};
    contextUsed = u.total_tokens || contextUsed;
    renderContext();
    if (dshMode) { const b = $("#dsh-badge"); if (b) b.textContent = "DSH · " + fmtTokens(contextUsed) + " tokens"; }
  } catch(e) {
    if (stopRequested || (e && e.name === "AbortError")) {
      const raw = (messageText(wait) || "").trim();
      const stoppedText = (raw && raw !== "思考中…") ? raw : "已停止";
      setMessageText(wait, stoppedText, true);
      const note = document.createElement("div"); note.className = "ai-stopped-note"; note.textContent = "已终止"; (wait._kpWrap || wait).after(note);
      needsResponse = false;
      sessionUnread = (sessionId !== runSessionId || currentPanel === "history");
      if (stoppedText.trim()) {
        const rec = {role:"assistant", text:stoppedText, stopped:true, time:Date.now(), events:wait._kpEvents || []};
        hist.push(rec); attachMsgActions(wait, "assistant", rec);
      }
      saveHist();
      try { await persistSession(); } catch(e2) {}
      pendingFiles = []; renderFileChips();
    } else {
      setMessageText(wait, "失败：" + e.message, false);
    }
  } finally {
    aiSending = false; stopRequested = false; activeAbort = null; updateSendButton();
  }
  $("#chat-msgs").scrollTop = $("#chat-msgs").scrollHeight;
}

function payload(){
  const out = {provider: $("#p-provider").value, base_url: $("#p-base").value.trim(), model: $("#p-model").value.trim()};
  const key = $("#p-key").value.trim();
  if (key) out.api_key = key;
  return out;
}

function autoGrow(){
  const t = $("#chat-in"); if (!t) return;
  t.style.height = "auto";
  t.style.height = Math.min(160, Math.max(30.68, t.scrollHeight)) + "px";
}
$("#chat-in").addEventListener("input", autoGrow);
function openAiLink(url){
  const viewer = $("#ai-link-viewer"), frame = $("#ai-link-frame"), label = $("#ai-link-url"), ext = $("#ai-link-external");
  if (!viewer || !frame) return;
  label.textContent = url; ext.href = url; frame.src = url; viewer.classList.remove("hidden");
}
function closeAiLink(){
  const viewer = $("#ai-link-viewer"), frame = $("#ai-link-frame");
  if (!viewer) return;
  viewer.classList.add("hidden");
  if (frame) frame.src = "about:blank";
}
$("#ai-link-close").onclick = closeAiLink;
document.addEventListener("click", (e) => {
  const a = e.target.closest("#chat-msgs a[href]");
  if (!a) return;
  const href = a.getAttribute("href") || "";
  if (!/^https?:\/\//i.test(href)) return;
  e.preventDefault(); openAiLink(href);
});
$("#chat-send").onclick = () => { if (aiSending) stopGeneration(); else sendChat(); };
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  const viewer = $("#ai-link-viewer");
  if (viewer && !viewer.classList.contains("hidden")) { e.preventDefault(); closeAiLink(); return; }
  if (aiSending) { e.preventDefault(); stopGeneration(); }
});
$("#ask-send").onclick = submitAskAnswer;
$("#ask-input").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); submitAskAnswer(); } });
function setSessionMsg(t){ const el = $("#session-msg"); if (el) el.textContent = t || ""; }
async function importConversationText(text){
  const msgs = parseConversation(text);
  const mode = ($("#import-mode") && $("#import-mode").value) || "overwrite";
  if (mode === "overwrite" && sessionId) {
    await postJson("/api/ai/sessions/save", {session: {id: sessionId, title: titleFromMessages(msgs), module: currentModule(), messages: msgs}});
    await loadSession(sessionId);
  } else {
    const j = await postJson("/api/ai/sessions/import", {session: {title: titleFromMessages(msgs), module: currentModule(), messages: msgs}, mode: "new"});
    await loadSession(j.session.id);
  }
  await refreshSessions();
  setSessionMsg("已导入 " + msgs.length + " 条消息");
}
async function backupSessions(){
  const j = await api("/api/ai/sessions/backup");
  downloadText("kp-ai-sessions-" + Date.now() + ".json", JSON.stringify(j, null, 2), "application/json;charset=utf-8");
  setSessionMsg("已备份 " + (j.sessions || []).length + " 个 session");
}
async function restoreSessions(text){
  const d = JSON.parse(text);
  const sessionsIn = Array.isArray(d.sessions) ? d.sessions : (d.session ? [d.session] : null);
  if (!sessionsIn) throw new Error("备份文件中没有 sessions");
  const j = await postJson("/api/ai/sessions/import", {sessions: sessionsIn, mode: "new"});
  await refreshSessions();
  if (j.sessions && j.sessions.length) await loadSession(j.sessions[0].id);
  setSessionMsg("已恢复 " + (j.imported || 0) + " 个 session");
}
function showAiSettingsTab(name){
  document.querySelectorAll(".ai-settings-tabs .ai-tab").forEach(b => b.classList.toggle("active", b.dataset.aiset === name));
  const main = $("#ai-settings-main"), skills = $("#ai-settings-skills");
  if (main) main.classList.toggle("hidden", name !== "main");
  if (skills) skills.classList.toggle("hidden", name !== "skills");
  if (name === "skills") loadSkills();
}
async function loadSkills(){
  const box = $("#skill-list"); if (!box) return;
  try {
    const j = await api("/api/ai/skills");
    const list = j.skills || [];
    box.innerHTML = list.length ? list.map(k =>
      '<label class="ai-skill-row"><input type="checkbox" data-skill="' + esc(k.name) + '"' + (k.enabled ? " checked" : "") + '>' +
      '<div><b>' + esc(k.name) + '</b><small>' + esc(k.source || "") + '</small><p>' + esc(k.description || "") + '</p></div></label>'
    ).join("") : '<div class="ai-status">没有发现 skill。可以在下面新增，或把 skill 放到 platform/skills。</div>';
    box.querySelectorAll("input[data-skill]").forEach(inp => inp.onchange = async () => {
      try {
        await postJson("/api/ai/skills/toggle", {name: inp.dataset.skill, enabled: inp.checked});
        const msg = $("#skill-msg"); if (msg) msg.textContent = inp.checked ? "已启用：" + inp.dataset.skill : "已停用：" + inp.dataset.skill;
      } catch(e) { inp.checked = !inp.checked; const msg = $("#skill-msg"); if (msg) msg.textContent = "操作失败：" + e.message; }
    });
  } catch(e) { box.innerHTML = '<div class="ai-status">读取失败：' + esc(e.message) + '</div>'; }
}
async function addSkill(){
  const name = ($("#skill-name").value || "").trim();
  const desc = ($("#skill-desc").value || "").trim();
  const content = ($("#skill-content").value || "").trim();
  if (!name || !content) { $("#skill-msg").textContent = "名称和正文不能为空"; return; }
  try {
    await postJson("/api/ai/skills/import", {name, description: desc, content});
    $("#skill-name").value = ""; $("#skill-desc").value = ""; $("#skill-content").value = "";
    $("#skill-msg").textContent = "已注册并启用：" + name;
    await loadSkills();
  } catch(e) { $("#skill-msg").textContent = "注册失败：" + e.message; }
}
document.querySelectorAll(".ai-settings-tabs .ai-tab").forEach(b => b.onclick = () => showAiSettingsTab(b.dataset.aiset));
$("#skill-refresh").onclick = () => loadSkills();
$("#skill-add").onclick = addSkill;
$("#export-conv").onclick = () => { downloadText("kp-ai-" + Date.now() + ".md", conversationMarkdown(), "text/markdown;charset=utf-8"); setSessionMsg("已导出当前对话 .md"); };
$("#import-pick").onclick = () => $("#import-file").click();
$("#import-file").addEventListener("change", async (e) => {
  const f = e.target.files && e.target.files[0]; e.target.value = "";
  if (!f) return;
  try { await importConversationText(await f.text()); } catch(err){ setSessionMsg("导入失败：" + err.message); }
});
$("#backup-sessions").onclick = () => backupSessions().catch(e => setSessionMsg("备份失败：" + e.message));
$("#restore-pick").onclick = () => $("#restore-file").click();
$("#restore-file").addEventListener("change", async (e) => {
  const f = e.target.files && e.target.files[0]; e.target.value = "";
  if (!f) return;
  try { await restoreSessions(await f.text()); } catch(err){ setSessionMsg("恢复失败：" + err.message); }
});
$("#file-btn").onclick = () => $("#file-input").click();
$("#file-input").addEventListener("change", (e) => { uploadFiles(e.target.files); e.target.value = ""; });
$("#model-refresh").onclick = () => { loadModels(); };
$("#model-select").addEventListener("change", () => { updateModelTrigger(); applySelectedContextWindow(); renderSlogan(); });
$("#model-trigger").onclick = () => toggleDshPopover($("#model-menu"), $("#model-trigger"), renderModelMenu);
$("#context-trigger").onclick = () => toggleDshPopover($("#context-panel"), $("#context-trigger"), renderContext);
document.addEventListener("click", (e) => {
  if (!e.target.closest(".dsh-control")) closeDshMenus();
});
window.addEventListener("resize", closeDshMenus);
$("#ai-slogan").addEventListener("click", () => {
  aiTagIdx = (aiTagIdx + 1 + Math.floor(Math.random() * (AI_TAGLINES.length - 1))) % AI_TAGLINES.length;
  renderSlogan();
  const el = $("#ai-slogan"); el.classList.remove("swap"); void el.offsetWidth; el.classList.add("swap");
  setTimeout(() => el.classList.remove("swap"), 260);
});
$("#ai-slogan").addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("#ai-slogan").click(); }
});
$("#chat-in").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(); } });
$("#session-new").onclick = () => newSession().catch(e => setMsg("新建失败：" + e.message));
document.querySelectorAll(".hist-tab").forEach(t => {
  t.onclick = () => { histArchivedView = t.dataset.arch === "1"; renderHistory(); };
});
$("#p-save").onclick = async () => {
  try {
    const body = payload();
    body.mode = document.querySelector('input[name="mode"]:checked').value;
    await api("/api/llm/me", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
    $("#p-key").value = ""; setMsg("个人设置已保存"); await loadStatus();
  } catch(e){ setMsg("保存失败：" + e.message); }
};
$("#p-test").onclick = async () => {
  try {
    setMsg("测试中…");
    const j = await api("/api/llm/test", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({})});
    setMsg("测试结果：" + JSON.stringify(j).slice(0, 320));
  } catch(e){ setMsg("测试失败：" + e.message); }
};
document.querySelectorAll('input[name="mode"]').forEach(r => r.addEventListener("change", () => {
  $("#personal-form").style.opacity = r.value === "server" ? ".72" : "1";
}));
window.addEventListener("message", (e) => {
  if (!e.data) return;
  if (e.data.kpAiHistory) showPanel("history");
  if (e.data.kpAiPanel !== undefined) showPanel(e.data.kpAiPanel);
  if (e.data.kpAiTab) showPanel(e.data.kpAiTab === "chat" ? null : e.data.kpAiTab);
});
if (new URLSearchParams(location.search).get("drawer") === "1") document.body.classList.add("drawer-mode");
if (kpValidInitialPanel) {
  document.body.classList.add("panel-open");
  const initialPane = document.getElementById(kpValidInitialPanel + "-pane");
  if (initialPane) initialPane.classList.add("open");
}
(async function(){
  try {
    await loadMe();
    renderSlogan(); updateModelTrigger(); renderChat();
    await loadDshStatus();
    await Promise.all([loadStatus(), initSessions()]);
    renderSlogan(); updateModelTrigger(); renderChat();
    if (kpValidInitialPanel) {
      showPanel(kpValidInitialPanel);
      setTimeout(() => showPanel(kpValidInitialPanel), 700);
    }
  } catch(e){ $("#status").textContent = "读取失败：" + e.message; }
})();
