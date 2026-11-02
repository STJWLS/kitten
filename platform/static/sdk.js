/* KittenPuppy4Ever 平台 · 客户端 SDK（子项目视图共用）
 *
 * 子项目视图只需要写：
 *   class Schedule extends KittenProjectView { render(){...} bind(){...} }
 *   new Schedule(document.body);
 *
 * 继承来的能力（类比抽象类的默认实现）：
 *   - this.id / this.manifest / this.state / this.rev
 *   - this.action(name, payload)  统一 kp/1 动作，自动带 rev（乐观并发）
 *   - this.refresh()              重新拉 state
 *   - this.applyTheme()           把 manifest.ui.theme 注入 CSS 变量
 *   - this.esc() / this.notify()  模板与提示
 */
(function () {
  class KittenProjectView {
    constructor(root) {
      this.root = root;
      this.id = root.getAttribute("data-project");
      this.state = null;
      this.manifest = null;
      this.rev = 0;
      this.mount().catch((e) => this.fatal(e));
    }

    async mount() {
      // 一次请求同时拿 manifest + state（/api/p/<id>/state 已带 manifest）
      const j = await this.call("/api/p/" + encodeURIComponent(this.id) + "/state");
      this.manifest = j.manifest || {};
      this.rev = j.rev || 0;
      this.state = j.data || {};
      this.applyTheme();
      if (typeof this.bind === "function") this.bind();
      if (typeof this.render === "function") this.render();
    }

    async loadManifest() {
      const j = await this.call("/api/p/" + encodeURIComponent(this.id));
      this.manifest = j.manifest || {};
      this.rev = j.rev || 0;
      this.applyTheme();
    }

    async refresh() {
      const j = await this.call("/api/p/" + encodeURIComponent(this.id) + "/state");
      this.rev = j.rev;
      this.state = j.data || {};
      if (typeof this.render === "function") this.render();
    }

    async action(action, payload) {
      const j = await this.call("/api/p/" + encodeURIComponent(this.id) + "/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: action, payload: payload || {}, rev: this.rev }),
      });
      this.rev = j.rev;
      this.state = j.data || {};
      if (typeof this.render === "function") this.render();
      return j;
    }

    async call(url, opts) {
      const r = await fetch(url, Object.assign({ cache: "no-store" }, opts || {}));
      let j;
      try {
        j = await r.json();
      } catch (e) {
        throw new Error("非 JSON 响应（HTTP " + r.status + "）");
      }
      if (!j.ok) {
        const err = j.error || {};
        const e = new Error(err.message || ("HTTP " + r.status));
        e.code = err.code;
        e.status = r.status;
        throw e;
      }
      return j;
    }

    applyTheme() {
      const theme = (this.manifest.ui && this.manifest.ui.theme) || {};
      const map = {
        accent: "--p-accent", bg: "--p-bg", ink: "--p-ink",
        muted: "--p-muted", card: "--p-card", line: "--p-line",
      };
      const s = document.documentElement.style;
      for (const k in map) if (theme[k]) s.setProperty(map[k], theme[k]);
      if (this.manifest.title) {
        document.title = this.manifest.title + " · KittenPuppy4Ever";
      }
    }

    esc(v) {
      return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) {
        return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
      });
    }

    notify(msg, bad) {
      let t = document.querySelector(".kp-toast");
      if (!t) {
        t = document.createElement("div");
        t.className = "kp-toast";
        document.body.appendChild(t);
      }
      t.textContent = msg;
      t.classList.toggle("bad", !!bad);
      t.classList.add("show");
      clearTimeout(this._t);
      this._t = setTimeout(function () { t.classList.remove("show"); }, 2600);
    }

    fatal(e) {
      const box = document.createElement("div");
      box.className = "kp-fatal";
      box.innerHTML = "<b>项目加载失败</b><br>" + this.esc(e.message || e);
      document.body.appendChild(box);
    }
  }

  window.KittenProjectView = KittenProjectView;
})();
