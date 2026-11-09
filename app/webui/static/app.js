/* FragQ web interface. Plain JS, no build step. All server data goes through textContent. */
(function () {
  "use strict";

  // ------------------------------------------------------------------ tiny DOM helpers
  function h(tag, attrs) {
    var el = document.createElement(tag);
    if (attrs) {
      for (var k in attrs) {
        var v = attrs[k];
        if (v === null || v === undefined || v === false) continue;
        if (k === "class") el.className = v;
        else if (k === "text") el.textContent = v;
        else if (k === "style") el.style.cssText = v;
        else if (k.slice(0, 2) === "on") el.addEventListener(k.slice(2), v);
        else if (k === "value") el.value = v;
        else if (k === "checked" || k === "disabled" || k === "selected") el[k] = !!v;
        else el.setAttribute(k, v === true ? "" : v);
      }
    }
    for (var i = 2; i < arguments.length; i++) append(el, arguments[i]);
    return el;
  }
  function append(el, kid) {
    if (kid === null || kid === undefined || kid === false) return;
    if (Array.isArray(kid)) { kid.forEach(function (k) { append(el, k); }); return; }
    el.appendChild(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  var SVGNS = "http://www.w3.org/2000/svg";
  function icon(name, cls) {
    var s = document.createElementNS(SVGNS, "svg");
    s.setAttribute("class", "i" + (cls ? " " + cls : ""));
    s.setAttribute("aria-hidden", "true");
    var u = document.createElementNS(SVGNS, "use");
    u.setAttribute("href", "#i-" + name);
    s.appendChild(u);
    return s;
  }
  function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }
  function slug(s) { return String(s).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, ""); }
  function clone(v) { return v === undefined ? undefined : JSON.parse(JSON.stringify(v)); }
  function same(a, b) { return JSON.stringify(a === undefined ? null : a) === JSON.stringify(b === undefined ? null : b); }
  function initials(name) {
    return String(name).split(/\s+/).filter(Boolean).slice(0, 3).map(function (w) { return w[0]; }).join("").toUpperCase();
  }
  function fmtDate(ts) {
    if (!ts) return "—";
    var d = new Date(ts * 1000);
    return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) + " " +
      d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  }
  function ago(ts) {
    var s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
    if (s < 60) return s + "s";
    if (s < 3600) return Math.floor(s / 60) + "m";
    if (s < 86400) return Math.floor(s / 3600) + "h " + Math.floor((s % 3600) / 60) + "m";
    return Math.floor(s / 86400) + "d";
  }

  // ------------------------------------------------------------------ api
  function api(method, path, body) {
    var opts = { method: method, headers: { "X-FragQ": "1" }, credentials: "same-origin" };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    return fetch(path, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (!r.ok) {
          var err = new Error(data.error || ("HTTP " + r.status));
          err.status = r.status;
          err.fields = data.fields;
          throw err;
        }
        return data;
      });
    });
  }

  // ------------------------------------------------------------------ toasts / modals / popovers
  function toast(msg, kind) {
    var t = h("div", { class: "toast" + (kind === "error" ? " error" : "") }, icon(kind === "error" ? "alert" : "check"), h("span", { text: msg }));
    document.getElementById("toasts").appendChild(t);
    setTimeout(function () { t.classList.add("out"); setTimeout(function () { t.remove(); }, 250); }, kind === "error" ? 6000 : 3000);
  }

  function modal(opts) {
    var back = h("div", { class: "modal-back" });
    var box = h("div", { class: "modal" + (opts.wide ? " wide" : "") + (opts.danger ? " danger" : ""), role: "dialog", "aria-modal": "true" });
    var closeBtn = h("button", { class: "icon-btn", type: "button", "aria-label": "Close", onclick: function () { close(); } }, icon("x"));
    var body = h("div", { class: "modal-body" });
    var foot = h("div", { class: "modal-foot" });
    append(box, [h("div", { class: "modal-head" }, h("h3", { text: opts.title }), closeBtn), body, foot]);
    back.appendChild(box);
    // Escape with a picker open only closes the picker (its own handler does that).
    function onKey(e) { if (e.key === "Escape" && !openPop) close(); }
    function close() {
      closePop();
      document.removeEventListener("keydown", onKey);
      back.remove();
      if (opts.onclose) opts.onclose();
    }
    back.addEventListener("mousedown", function (e) { if (e.target === back) close(); });
    document.addEventListener("keydown", onKey);
    document.body.appendChild(back);
    return { back: back, box: box, body: body, foot: foot, close: close };
  }

  function confirmModal(opts) {
    return new Promise(function (resolve) {
      var done = false;
      var m = modal({ title: opts.title, danger: opts.danger, onclose: function () { if (!done) resolve(false); } });
      append(m.body, h("p", { text: opts.text }));
      var input = null;
      if (opts.typeToConfirm) {
        append(m.body, h("label", { class: "lbl", text: "Type " + opts.typeToConfirm + " to confirm" }));
        input = h("input", { type: "text", autocomplete: "off", oninput: function () { ok.disabled = input.value.trim() !== opts.typeToConfirm; } });
        append(m.body, input);
      }
      var ok = h("button", { class: "btn " + (opts.danger ? "btn-danger solid" : "btn-primary"), type: "button", disabled: !!opts.typeToConfirm,
        onclick: function () { done = true; m.close(); resolve(true); } }, opts.ok || "Confirm");
      append(m.foot, [h("button", { class: "btn btn-ghost", type: "button", onclick: function () { m.close(); } }, "Cancel"), ok]);
      (input || ok).focus();
    });
  }

  var openPop = null;
  function closePop() { if (openPop) { var p = openPop; openPop = null; p.close(); } }
  // Show `content` in a floating panel next to `anchor` (fixed positioning so scroll containers don't clip it).
  function popover(anchor, content, opts) {
    closePop();
    opts = opts || {};
    var pop = h("div", { class: "pop fixed " + (opts.cls || "") }, content);
    document.body.appendChild(pop);
    var r = anchor.getBoundingClientRect();
    var w = Math.max(opts.minWidth || 0, opts.matchWidth ? r.width : 0);
    if (w) pop.style.minWidth = w + "px";
    var pw = pop.offsetWidth, ph = pop.offsetHeight;
    var left = opts.alignRight ? r.right - pw : r.left;
    left = Math.max(8, Math.min(left, window.innerWidth - pw - 8));
    var top = r.bottom + 6;
    if (top + ph > window.innerHeight - 8 && r.top - ph - 6 > 8) top = r.top - ph - 6;
    pop.style.left = left + "px";
    pop.style.top = top + "px";
    anchor.setAttribute("aria-expanded", "true");
    function outside(e) { if (!pop.contains(e.target) && !anchor.contains(e.target)) closePop(); }
    function key(e) { if (e.key === "Escape") { closePop(); anchor.focus(); } }
    function scroll(e) { if (!pop.contains(e.target)) closePop(); }
    setTimeout(function () {
      document.addEventListener("mousedown", outside);
      document.addEventListener("keydown", key);
      window.addEventListener("scroll", scroll, true);
      window.addEventListener("resize", closePop);
    });
    openPop = {
      el: pop,
      close: function () {
        document.removeEventListener("mousedown", outside);
        document.removeEventListener("keydown", key);
        window.removeEventListener("scroll", scroll, true);
        window.removeEventListener("resize", closePop);
        anchor.setAttribute("aria-expanded", "false");
        pop.remove();
      }
    };
    return pop;
  }

  function menu(anchor, items) {
    var list = h("div", { class: "menu" });
    items.forEach(function (it) {
      if (!it) return;
      if (it === "-") { list.appendChild(h("div", { class: "pop-sep" })); return; }
      list.appendChild(h("button", { class: "pop-item" + (it.urgent ? " urgent" : ""), type: "button",
        onclick: function (e) { e.stopPropagation(); closePop(); it.action(); } }, icon(it.icon), h("span", { text: it.label })));
    });
    popover(anchor, list, { alignRight: true, minWidth: 220 });
  }

  // Searchable single-select. items: [{id, name, color?, meta?, group?}]
  function picker(opts) {
    var wrap = h("div", { class: "picker" });
    var btn = h("button", { class: "picker-btn", type: "button", "aria-haspopup": "listbox" });
    function label() {
      clear(btn);
      var cur = opts.items.find(function (i) { return i.id === opts.value; });
      if (cur) {
        if (opts.kind === "user") btn.appendChild(cur.avatar ? h("img", { class: "av-sm round", src: cur.avatar, alt: "" }) : icon("users"));
        if (opts.kind === "role") btn.appendChild(h("span", { class: "rdot", style: cur.color ? "background:" + cur.color : "" }));
        if (opts.kind === "channel") btn.appendChild(icon("hash"));
        btn.appendChild(h("span", { class: "v", text: cur.name }));
      } else if (opts.value) {
        btn.appendChild(h("span", { class: "v", text: (opts.missing || "Unknown") + " (" + opts.value + ")" }));
      } else {
        btn.appendChild(h("span", { class: "v ph", text: opts.placeholder || "Select…" }));
      }
      btn.appendChild(icon("chevron"));
    }
    label();
    btn.addEventListener("click", function () {
      if (openPop && btn.getAttribute("aria-expanded") === "true") { closePop(); return; }
      var q = h("input", { type: "search", placeholder: "Search…", autocomplete: "off" });
      var list = h("div", { class: "pop-list", role: "listbox" });
      var hl = 0, shown = [], timer = null;
      function render() {
        clear(list);
        var term = q.value.trim().toLowerCase();
        // opts.search(term) -> Promise of items: the server filters (e.g. member search), so show its results as they are
        shown = opts.search ? opts.items.slice() : opts.items.filter(function (i) { return !term || i.name.toLowerCase().indexOf(term) >= 0; });
        if (opts.allowNone && !term) shown = [{ id: null, name: opts.noneLabel || "None" }].concat(shown);
        if (!shown.length) { list.appendChild(h("div", { class: "pop-empty", text: "No matches" })); return; }
        hl = Math.min(hl, shown.length - 1);
        shown.forEach(function (it, idx) {
          var b = h("button", { class: "pop-item" + (it.id === opts.value ? " sel" : "") + (idx === hl ? " hl" : ""), type: "button", role: "option",
            onclick: function () { choose(it); } });
          if (opts.kind === "user") b.appendChild(it.avatar ? h("img", { class: "av-sm round", src: it.avatar, alt: "", loading: "lazy" }) : icon("users"));
          if (opts.kind === "role" && it.id) b.appendChild(h("span", { class: "rdot", style: it.color ? "background:" + it.color : "" }));
          if (opts.kind === "channel" && it.id) b.appendChild(icon("hash"));
          b.appendChild(h("span", { text: it.name }));
          if (it.meta) b.appendChild(h("span", { class: "meta", text: it.meta }));
          list.appendChild(b);
        });
        var cur = list.children[hl];
        if (cur && cur.scrollIntoView) cur.scrollIntoView({ block: "nearest" });
      }
      function choose(it) {
        opts.value = it.id;
        closePop();
        label();
        btn.focus();
        opts.onChange(it.id);
      }
      var seq = 0;
      function fetchItems() {
        var mine = ++seq;  // only the newest search may update the list
        opts.search(q.value.trim()).then(function (items) { if (mine !== seq) return; opts.items = items; hl = 0; render(); })
          .catch(function () { /* keep the last results */ });
      }
      q.addEventListener("input", function () {
        hl = 0;
        if (!opts.search) return render();
        clearTimeout(timer);
        timer = setTimeout(fetchItems, 200);
      });
      if (opts.search) fetchItems();
      q.addEventListener("keydown", function (e) {
        if (e.key === "ArrowDown") { hl = Math.min(hl + 1, shown.length - 1); render(); e.preventDefault(); }
        else if (e.key === "ArrowUp") { hl = Math.max(hl - 1, 0); render(); e.preventDefault(); }
        else if (e.key === "Enter") { if (shown[hl]) choose(shown[hl]); e.preventDefault(); }
      });
      render();
      popover(btn, [h("div", { class: "search" }, icon("search"), q), list], { matchWidth: true, minWidth: 240 });
      q.focus();
    });
    wrap.appendChild(btn);
    wrap.setValue = function (v) { opts.value = v; label(); };
    return wrap;
  }

  // ------------------------------------------------------------------ state
  var S = {
    me: null, schema: null, guilds: [], guild: null, route: {},
    editor: null, timers: [], treeOpen: false,
  };
  var dom = {};

  function setTimer(fn, ms) { S.timers.push(setInterval(fn, ms)); }
  function clearTimers() { S.timers.forEach(clearInterval); S.timers = []; }

  // ------------------------------------------------------------------ routing
  function parseRoute(path) {
    var p = path.split("/").filter(Boolean).map(decodeURIComponent);
    var r = {};
    if (p[0] === "status" || p[0] === "settings") r.page = p[0];
    if (p[0] === "users" || p[0] === "connectors") { r.page = p[0]; r.ugid = p[1]; }
    if (p[0] === "g" && p[1]) {
      r.gid = p[1];
      if (p[2] === "c" && p[3]) {
        r.cid = p[3];
        if (p[4] === "q" && p[5]) { r.qid = p[5]; r.section = p[6]; }
        else { r.view = p[4] || "settings"; r.section = p[5]; }
      }
    }
    return r;
  }
  function link(r) {
    if (r.page) return "/" + r.page + (r.ugid ? "/" + r.ugid : "");
    if (!r.gid) return "/";
    var s = "/g/" + r.gid;
    if (r.cid) {
      s += "/c/" + r.cid;
      if (r.qid) { s += "/q/" + r.qid; if (r.section) s += "/" + r.section; }
      else if (r.view && (r.view !== "settings" || r.section)) { s += "/" + r.view; if (r.section) s += "/" + r.section; }
    }
    return s;
  }
  function go(r, replace) {
    var target = link(r);
    var proceed = function () {
      if (target !== location.pathname) history[replace ? "replaceState" : "pushState"](null, "", target);
      route();
    };
    if (S.editor && S.editor.dirtyCount() && !S.editor.sameTarget(r)) {
      confirmModal({ title: "Unsaved changes", text: "You have unsaved changes. Leave and discard them?", ok: "Discard", danger: true })
        .then(function (ok) { if (ok) { S.editor = null; proceed(); } });
    } else proceed();
  }
  window.addEventListener("popstate", function () {
    if (S.editor && S.editor.dirtyCount() && !S.editor.sameTarget(parseRoute(location.pathname))) {
      if (!window.confirm("You have unsaved changes. Leave and discard them?")) {
        history.pushState(null, "", S.editor.path());
        return;
      }
      S.editor = null;
    }
    route();
  });
  window.addEventListener("beforeunload", function (e) {
    if (S.editor && S.editor.dirtyCount()) { e.preventDefault(); e.returnValue = ""; }
  });

  // ------------------------------------------------------------------ boot
  function boot() {
    api("GET", "/api/me").then(function (me) {
      S.me = me;
      if (!me.bot.ready) return waitForBot();
      return Promise.all([api("GET", "/api/schema"), api("GET", "/api/guilds")]).then(function (res) {
        S.schema = res[0];
        S.guilds = res[1].guilds;
        renderShell();
        route();
      });
    }).catch(function (e) {
      if (e.status === 401) renderLogin();
      else if (e.status === 503) waitForBot();
      else renderFatal(e.message);
    });
  }

  function waitForBot() {
    clear(dom.app = document.getElementById("app"));
    append(dom.app, h("div", { class: "login-wrap" }, h("div", { class: "panel login-card" },
      brand(), h("p", {}, h("span", { class: "spinner sm" }), "  The bot is connecting to Discord…"),
      h("div", { class: "login-foot", text: "This page retries automatically." }))));
    setTimeout(boot, 3000);
  }

  function renderFatal(msg) {
    clear(dom.app = document.getElementById("app"));
    append(dom.app, h("div", { class: "login-wrap" }, h("div", { class: "panel login-card" }, brand(),
      h("div", { class: "flash flash-error", text: msg }),
      h("button", { class: "btn", type: "button", onclick: function () { location.reload(); } }, icon("refresh"), "Retry"))));
  }

  function brand() {
    return h("a", { class: "brand", href: "/", onclick: function (e) { e.preventDefault(); if (S.schema) go({}); } },
      h("span", { class: "brand-mark" }, icon("logo")),
      h("span", { class: "brand-text" },
        h("img", { class: "brand-logo dark", src: "/static/logo.png", alt: "FragQ" }),
        h("img", { class: "brand-logo light", src: "/static/logo-light.png", alt: "FragQ" })));
  }

  function renderLogin() {
    var app = clear(document.getElementById("app"));
    var err = new URLSearchParams(location.search).get("login_error");
    var messages = { state: "The login expired, please try again.", discord: "Discord login failed. Check the bot's client secret and redirect URL.", access_denied: "Login was cancelled." };
    append(app, h("div", { class: "login-wrap" }, h("div", { class: "panel login-card" },
      brand(),
      err ? h("div", { class: "flash flash-error", text: messages[err] || ("Login failed: " + err) }) : null,
      h("p", { text: "Sign in with Discord to configure queues, ratings and maps on the servers you manage." }),
      h("a", { class: "btn btn-discord", href: "/auth/login" }, icon("discord"), "Sign in with Discord"),
      h("div", { class: "login-foot", text: "Server administrators and channel admin roles can manage the bot." }))));
    if (err) history.replaceState(null, "", "/");
  }

  // ------------------------------------------------------------------ shell
  function renderShell() {
    var app = clear(document.getElementById("app"));
    var me = S.me;
    var themeBtn = h("button", { class: "theme-switch", type: "button", title: "Toggle light/dark", "aria-label": "Toggle light/dark theme",
      onclick: function () {
        var root = document.documentElement;
        var t = root.getAttribute("data-theme") === "light" ? "dark" : "light";
        root.setAttribute("data-theme", t);
        try { localStorage.setItem("fragq-theme", t); } catch (e) { /* ignore */ }
      } }, icon("sun"));
    var links = h("nav", { class: "top-links" },
      me.bot.commands ? h("a", { href: me.bot.commands, target: "_blank", rel: "noopener noreferrer" }, icon("book"), h("span", { text: "Commands" })) : null,
      me.bot.invite ? h("a", { href: me.bot.invite, target: "_blank", rel: "noopener noreferrer" }, icon("plus"), h("span", { text: "Invite bot" })) : null,
      me.user.owner ? (dom.statusLink = h("a", { href: "/status", onclick: function (e) { e.preventDefault(); go({ page: "status" }); } },
        icon("terminal"), h("span", { text: "Bot status" }))) : null,
      me.user.owner || me.user.manage_users ? (dom.usersLink = h("a", { href: "/users", onclick: function (e) { e.preventDefault(); go({ page: "users" }); } },
        icon("users"), h("span", { text: "Users" }))) : null,
      me.user.owner || me.user.manage_connectors ? (dom.connectorsLink = h("a", { href: "/connectors", onclick: function (e) { e.preventDefault(); go({ page: "connectors" }); } },
        icon("plug"), h("span", { text: "Connectors" }))) : null,
      me.user.owner || me.user.steam_review ? (dom.settingsLink = h("a", { href: "/settings", onclick: function (e) { e.preventDefault(); go({ page: "settings" }); } },
        icon("gear"), h("span", { text: "Settings" }))) : null);
    Array.prototype.forEach.call(links.children, function (a) { a.title = a.textContent; });  // tooltips when labels are hidden
    drawPendingDot();
    var top = h("header", { class: "topbar" },
      h("button", { class: "icon-box nav-toggle", type: "button", "aria-label": "Channels", onclick: function () { toggleTree(); } }, icon("menu")),
      brand(), links,
      h("div", { class: "top-actions" },
        h("div", { class: "botpill", title: me.bot.ready ? "Connected to Discord" : "Connecting…" },
          me.bot.avatar ? h("img", { src: me.bot.avatar, alt: "" }) : null,
          h("span", { class: "st" }, h("span", { class: "bn", text: me.bot.name }), h("span", { class: "bv", text: "v" + me.bot.version })),
          h("span", { class: "live-dot " + (me.bot.ready ? "on" : "off") })),
        h("div", { class: "whoami", title: me.user.username || me.user.name },
          h("img", { src: me.user.avatar, alt: "" }), h("span", { class: "nm", text: me.user.name }), me.user.owner ? h("span", { class: "role", text: "owner" }) : null),
        h("button", { class: "icon-box", type: "button", title: "Log out", "aria-label": "Log out", onclick: logout }, icon("logout")),
        themeBtn));
    dom.rail = h("nav", { class: "rail", "aria-label": "Servers" });
    dom.tree = h("aside", { class: "tree" });
    dom.main = h("main", { class: "main" });
    dom.shell = h("div", { class: "shell" }, dom.rail, dom.tree, dom.main);
    append(app, [top, dom.shell]);
    renderRail();
  }

  function toggleTree(open) {
    S.treeOpen = open === undefined ? !S.treeOpen : open;
    if (dom.shell) dom.shell.classList.toggle("tree-open", S.treeOpen);
  }

  function logout() {
    api("POST", "/api/logout").finally(function () { location.href = "/"; });
  }

  function renderRail() {
    var rail = clear(dom.rail);
    S.guilds.forEach(function (g) {
      var b = h("button", { class: "g-btn" + (S.route.gid === g.id ? " active" : ""), type: "button", "aria-label": g.name,
        onclick: function () { go({ gid: g.id }); } },
        g.icon ? h("img", { src: g.icon, alt: "", loading: "lazy" }) : initials(g.name),
        h("span", { class: "tip", text: g.name }));
      b.addEventListener("mouseenter", function () {
        var tip = b.querySelector(".tip"); var r = b.getBoundingClientRect();
        tip.style.top = (r.top + r.height / 2 - 14) + "px";
      });
      rail.appendChild(b);
    });
    if (S.guilds.length) rail.appendChild(h("hr"));
    var refresh = h("button", { class: "g-btn act", type: "button", "aria-label": "Refresh server list", onclick: refreshGuilds },
      icon("refresh"), h("span", { class: "tip", text: "Refresh server list" }));
    var add = S.me.bot.invite ? h("a", { class: "g-btn act", href: S.me.bot.invite, target: "_blank", rel: "noopener noreferrer", "aria-label": "Add a server" },
      icon("plus"), h("span", { class: "tip", text: "Add the bot to a server" })) : null;
    [refresh, add].forEach(function (b) {
      if (!b) return;
      b.addEventListener("mouseenter", function () {
        var tip = b.querySelector(".tip"); var r = b.getBoundingClientRect();
        tip.style.top = (r.top + r.height / 2 - 14) + "px";
      });
      rail.appendChild(b);
    });
  }

  function refreshGuilds() {
    api("GET", "/api/guilds").then(function (d) {
      S.guilds = d.guilds;
      renderRail();
      if (S.route.gid) return loadGuild(S.route.gid).then(renderTree);
    }).then(function () { toast("Server list refreshed."); }).catch(function (e) { toast(e.message, "error"); });
  }

  function loadGuild(gid) {
    return api("GET", "/api/guilds/" + gid).then(function (g) { S.guild = g; return g; });
  }

  // ------------------------------------------------------------------ route dispatch
  function route() {
    closePop();
    clearTimers();
    var r = parseRoute(location.pathname);
    var guildChanged = r.gid !== S.route.gid;
    S.route = r;
    if (dom.statusLink) dom.statusLink.classList.toggle("active", r.page === "status");
    if (dom.settingsLink) dom.settingsLink.classList.toggle("active", r.page === "settings");
    if (dom.usersLink) dom.usersLink.classList.toggle("active", r.page === "users");
    if (dom.connectorsLink) dom.connectorsLink.classList.toggle("active", r.page === "connectors");
    renderRail();
    toggleTree(false);
    if (!r.gid) {
      S.guild = null;
      renderTree();
      return r.page === "status" ? renderStatus() : r.page === "settings" ? renderSettings() : r.page === "users" ? renderUsers() : r.page === "connectors" ? renderConnectors() : renderWelcome();
    }
    var p = (guildChanged || !S.guild || S.guild.id !== r.gid) ? loadGuild(r.gid) : Promise.resolve(S.guild);
    if (guildChanged) mainLoading();
    p.then(function () {
      renderTree();
      if (r.qid) renderQueue();
      else if (r.cid) renderChannel();
      else renderOverview();
    }).catch(function (e) {
      S.guild = null;
      renderTree();
      mainMessage("alert", "Can't open this server", e.message);
    });
  }

  function main() { return clear(dom.main).appendChild(h("div", { class: "main-inner" })); }
  function mainLoading() { append(main(), h("div", { class: "empty-state" }, h("span", { class: "spinner" }))); }
  function mainMessage(ic, title, text, extra) {
    append(main(), h("div", { class: "empty-state" }, icon(ic), h("h3", { text: title }), text ? h("p", { text: text }) : null, extra || null));
  }

  // ------------------------------------------------------------------ channel tree
  function renderTree() {
    var tree = clear(dom.tree);
    var g = S.guild;
    if (!g) {
      append(tree, h("div", { class: "tree-body" }, h("div", { class: "empty-state" }, icon("users"),
        h("p", { text: S.guilds.length ? "Pick a server on the left." : "No servers yet." }))));
      return;
    }
    tree.appendChild(h("div", { class: "tree-head", role: "button", tabindex: "0", onclick: function () { go({ gid: g.id }); } },
      h("h3", { text: g.name }),
      h("small", { text: g.channels.length + " queue channel" + (g.channels.length === 1 ? "" : "s") + " · " + (g.members || 0) + " members" })));
    var body = h("div", { class: "tree-body" });
    var lastCat = undefined;
    g.channels.forEach(function (c) {
      if (c.category !== lastCat && c.category) body.appendChild(h("div", { class: "tree-cat", text: c.category }));
      lastCat = c.category;
      var grp = h("div", { class: "tree-group" });
      var active = S.route.cid === c.id && !S.route.qid;
      var more = h("button", { class: "icon-btn t-menu", type: "button", "aria-label": "Channel options", "aria-haspopup": "menu",
        onclick: function (e) { e.stopPropagation(); channelMenu(more, c); } }, icon("more"));
      grp.appendChild(h("div", { class: "t-row ch" + (active ? " active" : ""), role: "link", tabindex: "0",
        onclick: function () { go({ gid: g.id, cid: c.id }); },
        onkeydown: function (e) { if (e.key === "Enter") go({ gid: g.id, cid: c.id }); } },
        icon("hash"), h("span", { class: "t-name", text: c.name }),
        c.paused ? h("span", { class: "t-paused", title: "Queue paused: joining is disabled" }, icon("pause")) : null, more));
      c.queues.forEach(function (q) {
        var qa = S.route.qid === q.id;
        var qmore = h("button", { class: "icon-btn t-menu", type: "button", "aria-label": "Queue options", "aria-haspopup": "menu",
          onclick: function (e) { e.stopPropagation(); queueMenu(qmore, c, q); } }, icon("more"));
        grp.appendChild(h("div", { class: "t-row q" + (qa ? " active" : ""), role: "link", tabindex: "0",
          onclick: function () { go({ gid: g.id, cid: c.id, qid: q.id }); },
          onkeydown: function (e) { if (e.key === "Enter") go({ gid: g.id, cid: c.id, qid: q.id }); } },
          h("span", { class: "pq", text: "PQ" }), h("span", { class: "t-name", text: q.name }),
          h("span", { class: "t-count" + (q.players ? " hot" : ""), text: q.players + "/" + q.size }), qmore));
      });
      if (can("manage_queues", c)) {
        grp.appendChild(h("div", { class: "t-row add", role: "button", tabindex: "0", onclick: function () { createQueueModal(c); },
          onkeydown: function (e) { if (e.key === "Enter") createQueueModal(c); } }, icon("plus"), h("span", { text: "Create queue" })));
      }
      body.appendChild(grp);
    });
    if (can("manage_channels")) {
      body.appendChild(h("div", { class: "t-row add-ch", role: "button", tabindex: "0", onclick: addChannelModal,
        onkeydown: function (e) { if (e.key === "Enter") addChannelModal(); } }, icon("plus"), h("span", { text: "Add channel" })));
    }
    tree.appendChild(body);
  }

  // Web panel permissions (see webui/access.py). Without `c`: server-wide permissions.
  function can(perm, c) {
    var list = c ? c.perms : S.guild && S.guild.perms;
    return !!list && list.indexOf(perm) >= 0;
  }

  function channelMenu(anchor, c) {
    var items = [
      can("panel", c) ? { icon: "panel", label: c.panel ? "Move queue panel down" : "Post queue panel", action: function () { panelAction(c, true); } } : null,
      can("panel", c) && c.panel ? { icon: "x", label: "Remove queue panel", action: function () { panelAction(c, false); } } : null,
      can("pause", c) ? { icon: c.paused ? "play" : "pause", label: c.paused ? "Resume queue" : "Pause queue", action: function () { pauseAction(c, !c.paused); } } : null,
      { icon: "swap", label: can("edit_channel", c) ? "Import / export config" : "Export config", action: function () { cfgModal("channel", c); } },
      can("stats", c) ? { icon: "download", label: "Export players (CSV)", action: function () { location.href = "/api/channels/" + c.id + "/stats/players.csv"; } } : null,
      can("stats", c) ? { icon: "download", label: "Export matches (CSV)", action: function () { location.href = "/api/channels/" + c.id + "/stats/matches.csv"; } } : null,
    ];
    if (can("manage_channels")) {
      items.push("-", { icon: "trash", label: "Disable bot on channel", urgent: true, action: function () { deleteChannel(c); } });
    }
    menu(anchor, items);
  }

  function queueMenu(anchor, c, q) {
    var danger = can("manage_queues", c);
    menu(anchor, [
      { icon: "swap", label: can("edit_queue", c) ? "Import / export config" : "Export config", action: function () { cfgModal("queue", c, q); } },
      can("clear_queues", c) ? { icon: "eraser", label: "Remove all players", action: function () { clearQueue(c, q); } } : null,
      danger ? "-" : null,
      danger ? { icon: "trash", label: "Delete queue", urgent: true, action: function () { deleteQueue(c, q); } } : null,
    ]);
  }

  function panelAction(c, post) {
    api(post ? "POST" : "DELETE", "/api/channels/" + c.id + "/panel").then(function () {
      toast(post ? "Queue panel posted in #" + c.name + "." : "Queue panel removed.");
      return reloadGuild().then(function () { if (S.route.cid === c.id && !S.route.qid) route(); });
    }).catch(function (e) { toast(e.message, "error"); });
  }

  function pauseAction(c, paused) {
    api("POST", "/api/channels/" + c.id + "/pause", { paused: paused }).then(function () {
      toast(paused ? "Queue paused in #" + c.name + ". Players can't join until it's resumed." : "Queue resumed in #" + c.name + ".");
      return reloadGuild().then(function () { if (S.route.cid === c.id && !S.route.qid) route(); });
    }).catch(function (e) { toast(e.message, "error"); });
  }

  function reloadGuild() { return loadGuild(S.route.gid).then(renderTree); }

  function deleteChannel(c) {
    confirmModal({ title: "Disable bot on #" + c.name, danger: true, ok: "Disable & delete",
      text: "This deletes the channel configuration and its " + c.queues.length + " queue(s). Ratings and match history stay in the database.",
      typeToConfirm: c.name
    }).then(function (ok) {
      if (!ok) return;
      return api("DELETE", "/api/channels/" + c.id).then(function () {
        toast("Bot disabled on #" + c.name + ".");
        if (S.editor && S.editor.cid === c.id) S.editor = null;
        return reloadGuild().then(function () { if (S.route.cid === c.id) go({ gid: S.route.gid }, true); });
      });
    }).catch(function (e) { toast(e.message, "error"); });
  }

  function deleteQueue(c, q) {
    confirmModal({ title: "Delete queue " + q.name, danger: true, ok: "Delete queue",
      text: "The queue and its settings are removed from #" + c.name + ". Match history stays in the database." })
      .then(function (ok) {
        if (!ok) return;
        return api("DELETE", "/api/channels/" + c.id + "/queues/" + q.id).then(function () {
          toast("Queue " + q.name + " deleted.");
          if (S.editor && S.editor.qid === q.id) S.editor = null;
          return reloadGuild().then(function () { if (S.route.qid === q.id) go({ gid: S.route.gid, cid: c.id }, true); });
        });
      }).catch(function (e) { toast(e.message, "error"); });
  }

  function clearQueue(c, q) {
    confirmModal({ title: "Remove all players", text: "Remove everybody currently added to " + q.name + "?", ok: "Remove players" })
      .then(function (ok) {
        if (!ok) return;
        return api("POST", "/api/channels/" + c.id + "/queues/" + q.id + "/clear").then(function () {
          toast(q.name + " cleared."); reloadGuild();
        });
      }).catch(function (e) { toast(e.message, "error"); });
  }

  // ------------------------------------------------------------------ modals: create queue / add channel / cfg
  function createQueueModal(c) {
    var m = modal({ title: "Create queue" });
    var name = h("input", { type: "text", placeholder: "e.g. 4v4", maxlength: "64", autocomplete: "off" });
    var size = h("input", { type: "number", value: "8", min: "2", max: "1000" });
    var err = h("div", { class: "f-err hidden" });
    append(m.body, [
      h("p", {}, "New pickup queue on ", h("strong", { text: "#" + c.name }), ". Players join it with ", h("code", { text: "!add <name>" }), "."),
      h("div", { class: "row" },
        h("div", {}, h("label", { class: "lbl", text: "Queue name" }), name),
        h("div", {}, h("label", { class: "lbl", text: "Size" }), size)),
      err]);
    var ok = h("button", { class: "btn btn-primary", type: "button", onclick: submit }, icon("plus"), "Create");
    append(m.foot, [h("button", { class: "btn btn-ghost", type: "button", onclick: m.close }, "Cancel"), ok]);
    [name, size].forEach(function (i) { i.addEventListener("keydown", function (e) { if (e.key === "Enter") submit(); }); });
    name.focus();
    function submit() {
      ok.disabled = true;
      api("POST", "/api/channels/" + c.id + "/queues", { name: name.value.trim(), size: parseInt(size.value, 10) })
        .then(function (q) {
          m.close();
          toast("Queue " + q.name + " created.");
          return reloadGuild().then(function () { go({ gid: S.route.gid, cid: c.id, qid: q.id }); });
        })
        .catch(function (e) { err.classList.remove("hidden"); clear(err); append(err, [icon("alert"), e.message]); ok.disabled = false; });
    }
  }

  function addChannelModal() {
    var g = S.guild;
    var m = modal({ title: "Add channel" });
    var chosen = null;
    var free = g.text_channels.filter(function (c) { return !c.enabled; });
    var warn = h("div", { class: "flash flash-warn hidden", text: "The bot can't send messages in this channel. Check its permissions." });
    var pk = picker({
      kind: "channel", value: null, placeholder: "Select a text channel…",
      items: free.map(function (c) { return { id: c.id, name: c.name, meta: c.category || "" }; }),
      onChange: function (v) {
        chosen = v; ok.disabled = !v;
        var tc = free.find(function (c) { return c.id === v; });
        warn.classList.toggle("hidden", !tc || tc.can_send);
      }
    });
    var err = h("div", { class: "f-err hidden" });
    append(m.body, [
      h("p", { text: "Enable FragQ on a text channel. Same as typing !enable_pubobot there." }),
      free.length ? [h("label", { class: "lbl", text: "Text channel" }), pk, h("div", { style: "margin-top:12px" }, warn)]
        : h("div", { class: "flash flash-warn", text: "Every text channel the bot can see is already enabled." }),
      err]);
    var ok = h("button", { class: "btn btn-primary", type: "button", disabled: true, onclick: function () {
      ok.disabled = true;
      api("POST", "/api/guilds/" + g.id + "/channels", { channel_id: chosen }).then(function (c) {
        m.close();
        toast("Bot enabled on #" + c.name + ".");
        return reloadGuild().then(function () { go({ gid: g.id, cid: c.id }); });
      }).catch(function (e) { err.classList.remove("hidden"); clear(err); append(err, [icon("alert"), e.message]); ok.disabled = false; });
    } }, icon("plus"), "Enable");
    append(m.foot, [h("button", { class: "btn btn-ghost", type: "button", onclick: m.close }, "Cancel"), ok]);
  }

  function download(name, text, type) {
    var a = h("a", { href: URL.createObjectURL(new Blob([text], { type: type || "application/json" })), download: name });
    document.body.appendChild(a); a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 500);
  }

  function cfgModal(kind, c, q) {
    var base = "/api/channels/" + c.id + (kind === "queue" ? "/queues/" + q.id : "");
    var title = kind === "queue" ? q.name : "#" + c.name;
    var m = modal({ title: "Config · " + title, wide: true });
    var mode = "export";
    var tabs = h("div", { class: "mtabs" });
    var pane = h("div");
    append(m.body, [tabs, pane]);
    var exported = null;
    var modes = can(kind === "queue" ? "edit_queue" : "edit_channel", c) ? ["export", "import"] : ["export"];
    function draw() {
      clear(tabs); clear(pane); clear(m.foot);
      modes.forEach(function (t) {
        tabs.appendChild(h("button", { class: "chip" + (mode === t ? " active" : ""), type: "button", onclick: function () { mode = t; draw(); } },
          icon(t === "export" ? "download" : "upload"), t));
      });
      if (mode === "export") {
        var ta = h("textarea", { class: "code", rows: "18", readonly: true, spellcheck: "false" });
        ta.value = exported ? JSON.stringify(exported, null, 2) : "Loading…";
        append(pane, [h("p", { text: "Roles and channels are exported by name, so the config can be imported on another server or channel." }), ta]);
        if (!exported) {
          api("GET", base + "/export").then(function (d) { exported = d; ta.value = JSON.stringify(d, null, 2); })
            .catch(function (e) { ta.value = e.message; });
        }
        append(m.foot, [
          h("button", { class: "btn", type: "button", onclick: function () {
            navigator.clipboard.writeText(ta.value).then(function () { toast("Copied to clipboard."); }, function () { ta.select(); });
          } }, icon("copy"), "Copy"),
          h("button", { class: "btn btn-primary", type: "button", onclick: function () {
            download(slug(kind === "queue" ? q.name : c.name) + (kind === "queue" ? "-queue" : "-channel") + ".cfg", ta.value);
          } }, icon("download"), "Download .cfg")]);
      } else {
        var src = h("textarea", { class: "code", rows: "16", spellcheck: "false", placeholder: '{\n  "size": "8",\n  "maps": [{ "name": "campgrounds" }]\n}' });
        var file = h("input", { type: "file", accept: ".cfg,.json,application/json,text/plain", class: "hidden", onchange: function () {
          var f = file.files[0]; if (!f) return;
          f.text().then(function (t) { src.value = t; });
        } });
        var errs = h("div");
        append(pane, [h("p", { text: "Paste a config exported from FragQ or the PUBobot2 web interface. Only the variables present are changed." }), src, file, errs]);
        var btn = h("button", { class: "btn btn-primary", type: "button", onclick: function () {
          clear(errs);
          var data;
          try { data = JSON.parse(src.value); } catch (e) {
            append(errs, h("ul", { class: "errlist" }, h("li", { text: "Invalid JSON: " + e.message }))); return;
          }
          btn.disabled = true;
          api("PUT", base, { values: data }).then(function () {
            m.close();
            toast("Config imported into " + title + ".");
            exported = null;
            reloadGuild().then(function () {
              if (S.editor && ((kind === "queue" && S.editor.qid === q.id) || (kind === "channel" && !S.editor.qid && S.editor.cid === c.id))) {
                S.editor = null; route();
              }
            });
          }).catch(function (e) {
            btn.disabled = false;
            var list = h("ul", { class: "errlist" });
            if (e.fields) Object.keys(e.fields).forEach(function (k) { list.appendChild(h("li", {}, h("code", { text: k }), ": " + e.fields[k])); });
            else list.appendChild(h("li", { text: e.message }));
            append(errs, list);
          });
        } }, icon("upload"), "Import");
        append(m.foot, [h("button", { class: "btn", type: "button", onclick: function () { file.click(); } }, icon("file"), "Load file…"), btn]);
      }
    }
    draw();
  }

  // ------------------------------------------------------------------ pages: welcome / overview / status
  function renderWelcome() {
    var root = main();
    var FEATURES = [
      ["Web panel", "every channel and queue setting in one place, with import and export"],
      ["Live view", "queues filling up and matches in progress, plus leaderboards and match history with CSV downloads"],
      ["Queue panel", "a Discord message with Join and Leave buttons, player avatars, and moderator buttons to add players or pause the queue"],
      ["Steam linking", "players link their Steam account, optionally required to join, with moderator approval for changes"],
      ["Access control", "give Discord members or roles access to the panel, per server or per channel"],
      ["Game connectors (beta)", "game servers post end-of-match stats in the queue's channel, starting with Quake Live"],
      ["Backup and restore", "every FragQ setting in one file, to move to a new install"],
    ];
    append(root, h("div", { class: "page-head" }, h("div", { class: "welcome" },
      h("h1", { text: "Welcome, " + S.me.user.name }),
      h("p", {}, "FragQ is a self-hosted pickup game bot for Discord, built on top of ",
        h("a", { href: "https://github.com/Leshaka/PUBobot2", target: "_blank", rel: "noopener noreferrer", text: "PUBobot2" }),
        " by Leshaka. It keeps PUBobot2's queues, drafts, ratings and commands, and uses the same database, so existing PUBobot2 setups carry straight over. On top of that, FragQ adds:"),
      h("ul", { class: "welcome-features" }, FEATURES.map(function (f) { return h("li", {}, h("strong", { text: f[0] + ": " }), f[1]); })),
      h("p", { text: S.guilds.length ? "Pick a server below to manage its queue channels." : "You don't manage any server the bot is on yet." }))));
    if (!S.guilds.length) {
      append(root, h("div", { class: "panel" }, h("div", { class: "empty-state" }, icon("discord"),
        h("h3", { text: "Add FragQ to your server" }),
        h("p", { text: "Invite the bot, then type !enable_pubobot in a text channel or add the channel here. You see a server here if you administer it, hold a channel's admin role, or were given access on the Users page." }),
        S.me.bot.invite ? h("a", { class: "btn btn-primary", href: S.me.bot.invite, target: "_blank", rel: "noopener noreferrer" }, icon("plus"), "Invite the bot") : null)));
      return;
    }
    var grid = h("div", { class: "stats server-cards" });
    S.guilds.forEach(function (g) {
      grid.appendChild(h("button", { class: "stat", type: "button", style: "text-align:left;cursor:pointer;color:inherit;font:inherit", onclick: function () { go({ gid: g.id }); } },
        h("div", { class: "k", text: g.admin ? "Administrator" : "Limited access" }),
        h("div", { style: "margin-top:10px;font:600 16px var(--display);letter-spacing:.03em", text: g.name }),
        h("div", { class: "muted", style: "font-size:12.5px;margin-top:4px", text: g.channels + " queue channel" + (g.channels === 1 ? "" : "s") })));
    });
    root.appendChild(grid);
  }

  function personEl(p) {
    return h("span", { class: "person" }, p && p.avatar ? h("img", { src: p.avatar, alt: "", loading: "lazy" }) : h("span", { style: "width:6px" }), p ? p.name : "?");
  }

  function queueCard(q, extra) {
    var pct = q.size ? Math.round(100 * q.players / q.size) : 0;
    return h("div", { class: "qcard" },
      h("div", { class: "qcard-head" }, h("span", { class: "pq", text: "PQ" }), h("strong", { text: q.name }), extra || null,
        h("span", { class: "t-count" + (q.players ? " hot" : ""), text: q.players + "/" + q.size }),
        h("span", { class: "meter" }, h("span", { style: "width:" + pct + "%" }))),
      q.who && q.who.length ? h("div", { class: "ppl" }, q.who.map(personEl)) : null);
  }

  function matchCard(m, chanName) {
    return h("div", { class: "qcard" },
      h("div", { class: "qcard-head" },
        h("strong", { text: "#" + m.id + " · " + m.queue }),
        chanName ? h("span", { class: "muted", text: "in #" + chanName }) : null,
        h("span", { class: "badge " + (m.state === "waiting report" ? "blue" : "warn"), style: "margin-left:auto", text: m.state }),
        m.ranked ? h("span", { class: "badge ok", text: "ranked" }) : null,
        h("span", { class: "faint mono", text: ago(m.started) })),
      m.maps && m.maps.length ? h("div", { class: "muted", style: "margin-top:6px;font-size:13px", text: "Maps: " + m.maps.join(", ") }) : null,
      h("div", { class: "teams" }, m.teams.map(function (t) {
        return h("div", { class: "team" }, h("b", { text: t.name }), h("div", { text: t.players.map(function (p) { return p ? p.name : "?"; }).join(", ") || "—" }));
      })));
  }

  function chanName(id) {
    var c = S.guild && S.guild.channels.find(function (x) { return x.id === id; });
    return c ? c.name : id;
  }

  function renderOverview() {
    S.editor = null;
    var g = S.guild;
    var root = main();
    append(root, h("div", { class: "page-head" },
      h("div", { class: "title" }, g.icon ? h("img", { src: g.icon, alt: "", style: "width:48px;height:48px;border-radius:12px" }) : null,
        h("div", {}, h("h1", { text: g.name }), h("p", { text: g.admin ? "You are an administrator of this server." : "You have limited access: only the channels and actions you were given are shown." }))),
      h("div", { class: "head-actions" },
        g.manage_users ? h("button", { class: "btn", type: "button", onclick: function () { go({ page: "users", ugid: g.id }); } }, icon("users"), "Users") : null,
        can("manage_channels") ? h("button", { class: "btn btn-primary", type: "button", onclick: addChannelModal }, icon("plus"), "Add channel") : null)));
    var body = h("div");
    root.appendChild(body);
    if (!g.channels.length) {
      append(body, h("div", { class: "panel" }, h("div", { class: "empty-state" }, icon("hash"),
        h("h3", { text: "No queue channels yet" }),
        h("p", { text: "Enable the bot on a text channel to create pickup queues there." }),
        can("manage_channels") ? h("button", { class: "btn btn-primary", type: "button", onclick: addChannelModal }, icon("plus"), "Add channel") : null)));
      return;
    }
    function load() {
      api("GET", "/api/guilds/" + g.id + "/overview").then(function (o) {
        if (S.route.cid || S.route.gid !== g.id) return;
        clear(body);
        append(body, h("div", { class: "stats" },
          stat("Queue channels", o.channels), stat("Queues", o.queues), stat("Players in queue", o.players_in_queue), stat("Active matches", o.matches.length)));
        append(body, h("div", { class: "grid-2" },
          h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h2", { text: "Filling queues" }), h("span", { class: "badge ok", text: "live" })),
            o.active_queues.length ? o.active_queues.map(function (q) { return queueCard(q, h("span", { class: "muted", text: "#" + chanName(q.channel) })); })
              : h("div", { class: "empty-state", style: "padding:34px" }, h("p", { text: "Nobody is added to a queue right now." }))),
          h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h2", { text: "Matches in progress" })),
            o.matches.length ? o.matches.map(function (m) { return matchCard(m, chanName(m.channel)); })
              : h("div", { class: "empty-state", style: "padding:34px" }, h("p", { text: "No matches in progress." })))));
      }).catch(function (e) { clear(body); append(body, h("div", { class: "flash flash-error", text: e.message })); });
    }
    load();
    setTimer(load, 10000);
  }

  function stat(k, v) { return h("div", { class: "stat" }, h("div", { class: "k", text: k }), h("div", { class: "v", text: String(v) })); }

  function renderStatus() {
    S.editor = null;
    var root = main();
    append(root, h("div", { class: "page-head" }, h("div", {}, h("h1", { text: "Bot status" }), h("p", { text: "Owner-only view of the running bot." }))));
    var body = h("div"); root.appendChild(body);
    function load() {
      api("GET", "/api/status").then(function (s) {
        if (S.route.page !== "status") return;
        clear(body);
        var up = s.uptime, d = Math.floor(up / 86400), hh = Math.floor(up % 86400 / 3600), mm = Math.floor(up % 3600 / 60);
        append(body, h("div", { class: "stats" },
          stat("Uptime", (d ? d + "d " : "") + hh + "h " + mm + "m"), stat("Latency", s.latency === null ? "—" : s.latency + " ms"),
          stat("Servers", s.guilds), stat("Channels", s.channels), stat("Queues", s.queues), stat("Active matches", s.active_matches)));
        var pre = h("pre", { class: "logbox" });
        s.log.forEach(function (line) { pre.appendChild(h("div", { class: /\|ERROR>/.test(line) ? "e" : "", text: line })); });
        append(body, h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h2", { text: "Recent log" })), pre));
        pre.scrollTop = pre.scrollHeight;
      }).catch(function (e) { clear(body); append(body, h("div", { class: "flash flash-error", text: e.message })); });
    }
    load();
    setTimer(load, 15000);
  }

  // ------------------------------------------------------------------ settings page
  // The bot owner gets everything; server admins and channel moderators only the Linked players panel,
  // to review Steam account changes of members of their servers.
  function renderSettings() {
    S.editor = null;
    var root = main();
    var owner = S.me.user.owner;
    append(root, h("div", { class: "page-head" }, h("div", {}, h("h1", { text: "Settings" }),
      h("p", { text: owner ? "Bot-wide settings for every server FragQ is on. Only the bot owner can change these."
        : "Review Steam account changes of players on the servers you moderate." }))));
    var body = h("div"); root.appendChild(body);
    if (!owner) { append(body, steamLinksPanel()); return; }
    body.appendChild(h("div", { class: "empty-state" }, h("span", { class: "spinner" })));
    api("GET", "/api/settings").then(function (s) {
      if (S.route.page !== "settings") return;
      clear(body);
      append(body, botSettingsPanel(s));
      append(body, steamLinksPanel());
      append(body, backupPanel());
    }).catch(function (e) { clear(body); append(body, h("div", { class: "flash flash-error", text: e.message })); });
  }

  function fieldErr() {
    var el = h("div", { class: "f-err" });
    el.hidden = true;
    el.show = function (msg) { el.hidden = !msg; clear(el); if (msg) append(el, [icon("alert"), h("span", { text: msg })]); };
    return el;
  }

  function switchEl(title, onchange) {
    var cb = h("input", { type: "checkbox", onchange: function () { onchange(cb.checked); } });
    return { cb: cb, el: h("label", { class: "switch", title: title }, cb, h("span")) };
  }

  function botSettingsPanel(s) {
    var st = s.steam;
    function save(payload, busy, errEl) {
      busy.disabled = true;
      return api("PUT", "/api/settings", payload).then(function (r) { st = r.steam; draw(); errEl.show(null); return true; })
        .catch(function (e) { errEl.show(e.fields && e.fields.api_key || e.message); return false; })
        .then(function (ok) { busy.disabled = false; testBtn.disabled = removeBtn.disabled = !st.api_key_set; return ok; });
    }

    // Require Linked Steam IDs
    var requireErr = fieldErr(), requireNote = h("div", { class: "f-null" });
    var require = switchEl("Require Linked Steam IDs", function (on) {
      save({ steam: { require_link: on } }, require.cb, requireErr).then(function (ok) {
        if (ok) toast(on ? "Players must now link a Steam account before joining a queue." : "Steam accounts are no longer required to join queues.");
        else require.cb.checked = !on;
      });
    });

    // Steam Web API key
    var badge = h("span");
    var keyErr = fieldErr();
    var keyInput = h("input", { type: "password", autocomplete: "off", spellcheck: "false", class: "mono", style: "max-width:420px" });
    var saveBtn = h("button", { class: "btn btn-primary", type: "button", onclick: saveKey }, icon("check"), "Save key");
    var testBtn = h("button", { class: "btn", type: "button", onclick: testKey }, icon("pulse"), "Test");
    var removeBtn = h("button", { class: "btn btn-ghost", type: "button", onclick: removeKey }, icon("trash"), "Remove key");
    function saveKey() {
      var key = keyInput.value.trim();
      if (!key) return keyErr.show("Paste the key first.");
      save({ steam: { api_key: key } }, saveBtn, keyErr).then(function (ok) { if (ok) toast("Steam API key saved and verified."); });
    }
    function testKey() {
      testBtn.disabled = true;
      api("POST", "/api/settings/steam/test").then(function () { keyErr.show(null); toast("Steam accepted the key."); })
        .catch(function (e) { keyErr.show(e.message); }).then(function () { testBtn.disabled = false; });
    }
    function removeKey() {
      confirmModal({ title: "Remove Steam API key", text: "FragQ goes back to reading public Steam profiles for names and avatars, which is slower and refreshes fewer players at a time.", ok: "Remove", danger: true })
        .then(function (ok) { if (ok) save({ steam: { api_key: "" } }, removeBtn, keyErr).then(function (done) { if (done) toast("Steam API key removed."); }); });
    }
    keyInput.addEventListener("keydown", function (e) { if (e.key === "Enter") saveKey(); });

    function draw() {
      require.cb.checked = !!st.require_link;
      requireNote.textContent = st.linked + " player" + (st.linked === 1 ? "" : "s") + " linked so far.";
      badge.className = "badge " + (st.api_key_set ? "ok" : "warn");
      badge.textContent = st.api_key_set ? "Key saved" : "No key";
      keyInput.value = "";
      keyInput.placeholder = st.api_key_set ? "Saved key ends in …" + st.api_key_hint + ". Paste a new key to replace it." : "32-character Steam Web API key";
      testBtn.disabled = removeBtn.disabled = !st.api_key_set;
    }
    draw();

    function toggleField(title, desc, sw, extra) {
      return h("div", { class: "field" },
        h("div", { class: "f-row-inline" },
          h("div", {}, h("div", { class: "f-head" }, h("span", { class: "f-title", text: title })), h("p", { class: "f-desc", text: desc })),
          h("div", { class: "f-body" }, sw.el)),
        extra);
    }
    return h("section", { class: "panel" },
      h("div", { class: "panel-head" }, h("h2", { text: "Bot settings" })),
      toggleField("Require Linked Steam IDs",
        "Players must link a Steam account before they can join a queue. The first time they press Join or type !add, FragQ asks for their Steam ID. Changing it later with !steam or /steam needs a moderator's approval below. Moderators can still add unlinked players with Add Player.",
        require, [requireNote, requireErr]),
      h("div", { class: "field" },
        h("div", { class: "f-head" }, h("span", { class: "f-title", text: "Steam Web API key" }), badge),
        h("p", { class: "f-desc" }, "Optional. Steam names, avatars and custom profile names (steamcommunity.com/id/…) work without a key by reading public Steam profiles, " +
          "but that is slower and rate limited. With a key FragQ uses the Steam Web API instead. Get one at ",
          h("a", { href: "https://steamcommunity.com/dev/apikey", target: "_blank", rel: "noopener noreferrer", text: "steamcommunity.com/dev/apikey" }),
          ". It is checked with Steam when you save, and never shown again in full."),
        h("div", { class: "f-body" }, keyInput, h("div", { class: "key-actions" }, saveBtn, testBtn, removeBtn), keyErr)));
  }

  function proofBadge(r) {
    if (r.verified_by === "steam") return h("span", { class: "badge ok", title: "Proved by signing in through Steam", text: "Steam proven" });
    if (r.verified_by === "game") return h("span", { class: "badge blue", title: "Confirmed from a game server with !link", text: "In-game" });
    return h("span", { class: "badge", title: "Typed in by the player, not proved", text: "Claimed" });
  }

  function steamCell(r) {
    return h("span", { class: "who-cell" }, r.steam_avatar ? h("img", { src: r.steam_avatar, alt: "", class: "av-sm" }) : null,
      h("span", {}, h("span", { text: r.persona || "—" }), " ",
        h("a", { class: "mono faint", href: r.profile_url, target: "_blank", rel: "noopener noreferrer", text: r.steam_id }), " ", proofBadge(r)));
  }

  function steamLinksPanel() {
    var tbody = h("tbody"), count = h("span", { class: "badge blue", text: "…" }), pendingBadge = h("span", { class: "badge warn" });
    pendingBadge.hidden = true;
    var search = h("input", { type: "search", placeholder: "Search players or Steam IDs…", style: "max-width:260px;height:30px;font-size:13px" });
    var links = [];
    function draw() {
      clear(tbody);
      var term = search.value.trim().toLowerCase(), n = 0;
      links.forEach(function (l) {
        var p = l.pending;
        if (term && [l.name, l.persona, l.steam_id, p && p.persona, p && p.steam_id].join(" ").toLowerCase().indexOf(term) < 0) return;
        n++;
        var steam = l.steam_id ? steamCell(l) : h("span", { class: "faint", text: "Not linked" });
        if (p) steam = h("div", { class: "steam-change" }, steam,
          h("div", { class: "steam-req" }, h("span", { class: "badge warn", text: "Change requested" }), steamCell(p),
            h("span", { class: "faint", text: "requested " + fmtDate(p.requested_at) })));
        var actions = h("div", { class: "row-actions" });
        if (p && l.can_review) {
          actions.appendChild(h("button", { class: "btn btn-sm btn-primary", type: "button", title: "Link " + l.name + " to the requested Steam account",
            onclick: function (e) { review(l, "approve", e.currentTarget); } }, icon("check"), "Approve"));
          actions.appendChild(h("button", { class: "btn btn-sm", type: "button", title: "Keep the current link",
            onclick: function (e) { review(l, "reject", e.currentTarget); } }, icon("x"), "Reject"));
        } else if (p) {
          actions.appendChild(h("span", { class: "faint", text: "Another moderator reviews this" }));
        }
        if (l.steam_id) actions.appendChild(h("button", { class: "btn btn-sm btn-ghost", type: "button", title: "Remove this link",
          onclick: function () { unlink(l); } }, icon("trash"), "Unlink"));
        tbody.appendChild(h("tr", { class: p ? "pending" : "" },
          h("td", {}, h("span", { class: "who-cell" }, l.avatar ? h("img", { src: l.avatar, alt: "", class: "av-sm round" }) : null, h("strong", { text: l.name }))),
          h("td", {}, steam),
          h("td", { class: "date", text: l.linked_at ? fmtDate(l.linked_at) : "—" }),
          h("td", { class: "num" }, actions)));
      });
      if (!n) tbody.appendChild(h("tr", {}, h("td", { colspan: "4" }, h("div", { class: "vt-empty",
        text: links.length ? "No matches." : "No linked players yet. Players link with !steam, /steam, or when FragQ asks them on joining." }))));
    }
    function review(l, action, btn) {
      btn.disabled = true;
      api("POST", "/api/steam/links/" + l.user_id + "/" + action).then(function () {
        toast(action === "approve" ? l.name + " is now linked to " + (l.pending.persona || l.pending.steam_id) + "." : "Kept " + l.name + "'s current link.");
        load(); refreshPending();
      }).catch(function (e) { btn.disabled = false; toast(e.message, "error"); });
    }
    function unlink(l) {
      confirmModal({ title: "Unlink " + l.name, text: "Removes the link to Steam account " + l.steam_id + (l.pending ? " and the pending change" : "") +
        ". If linked Steam IDs are required, " + l.name + " is asked for one again on their next join.", ok: "Unlink", danger: true })
        .then(function (ok) {
          if (!ok) return;
          api("DELETE", "/api/steam/links/" + l.user_id).then(function () { toast("Unlinked " + l.name + "."); load(); refreshPending(); })
            .catch(function (e) { toast(e.message, "error"); });
        });
    }
    function load() {
      api("GET", "/api/steam/links").then(function (d) {
        links = d.links;
        var pending = links.filter(function (l) { return l.pending; }).length;
        count.textContent = String(links.filter(function (l) { return l.steam_id; }).length);
        pendingBadge.hidden = !pending;
        pendingBadge.textContent = pending + " to review";
        draw();
      }).catch(function (e) { clear(tbody); tbody.appendChild(h("tr", {}, h("td", { colspan: "4" }, h("div", { class: "flash flash-error", text: e.message })))); });
    }
    search.addEventListener("input", draw);
    load();
    return h("section", { class: "panel" },
      h("div", { class: "panel-head" }, h("div", { style: "display:flex;gap:12px;align-items:center;flex-wrap:wrap" },
        h("h2", { text: "Linked players" }), count, pendingBadge, search)),
      h("p", { class: "panel-note", text: "A player's first link is immediate. When a linked player switches to another Steam account, the change waits here until a moderator or admin approves it; their current link stays until then." }),
      h("div", { class: "scroll-x" }, h("table", { class: "dtable" },
        h("thead", {}, h("tr", {}, ["Discord", "Steam account", "Linked", ""].map(function (t, i) {
          return h("th", { class: i === 3 ? "num" : "", text: t });
        }))), tbody)));
  }

  // Number of Steam account changes waiting for this user, shown on the top-bar Settings link.
  function refreshPending() {
    api("GET", "/api/me").then(function (me) { S.me.user.steam_pending = me.user.steam_pending; drawPendingDot(); }).catch(function () {});
  }
  function drawPendingDot() {
    var a = dom.settingsLink;
    if (!a) return;
    var dot = a.querySelector(".link-count");
    var n = S.me.user.steam_pending || 0;
    if (!n) { if (dot) dot.remove(); return; }
    if (!dot) { dot = h("b", { class: "link-count" }); a.appendChild(dot); }
    dot.textContent = String(n);
    a.title = "Settings · " + n + " Steam account change" + (n === 1 ? "" : "s") + " to review";
  }

  function backupPanel() {
    var withKey = h("input", { type: "checkbox" });
    var dlBtn = h("button", { class: "btn btn-primary", type: "button", onclick: function () {
      location.href = "/api/settings/backup" + (withKey.checked ? "?steam_key=1" : "");
    } }, icon("download"), "Download backup");

    var file = h("input", { type: "file", accept: ".json,application/json", style: "display:none" });
    var loadBtn = h("button", { class: "btn", type: "button", onclick: function () { file.click(); } }, icon("upload"), "Load backup file…");
    var restoreErr = fieldErr();
    var preview = h("div", { class: "restore-preview" });
    var data = null;
    var PARTS = [
      { id: "settings", label: "Bot settings", desc: function (d) {
        var s = d.settings || {};
        return "Auto-repost, Require Linked Steam IDs" + ("steam_api_key" in s ? " and the Steam Web API key" : " (the backup has no Steam API key)") + ".";
      } },
      { id: "channels", label: "Channels and queues", desc: function (d) {
        var c = d.channels || [], q = c.reduce(function (n, x) { return n + (x.queues || []).length; }, 0);
        return c.length + " channel" + (c.length === 1 ? "" : "s") + " with " + q + " queue" + (q === 1 ? "" : "s") + ": settings, pause state and queue settings.";
      } },
      { id: "steam_links", label: "Steam links", desc: function (d) { var n = (d.steam_links || []).length; return n + " linked player" + (n === 1 ? "" : "s") + "."; } },
      { id: "web_access", label: "Web panel access", desc: function (d) { var n = (d.web_access || []).length; return n + " grant" + (n === 1 ? "" : "s") + " from the Users page."; } },
      { id: "connectors", optional: true, label: "Game connectors", desc: function (d) { var n = (d.connectors || []).length; return n + " connector" + (n === 1 ? "" : "s") + " with their keys: game servers keep working without new keys."; } },
    ];
    var checks = {};

    file.addEventListener("change", function () {
      var f = file.files[0];
      file.value = "";
      if (!f) return;
      var reader = new FileReader();
      reader.onload = function () {
        try { data = JSON.parse(reader.result); } catch (e) { data = null; restoreErr.show("This file isn't valid JSON."); clear(preview); return; }
        if (!data || data.format !== "fragq-backup") { data = null; restoreErr.show("This is not a FragQ backup file."); clear(preview); return; }
        restoreErr.show(null);
        drawPreview(f.name);
      };
      reader.readAsText(f);
    });

    function selected() { return PARTS.filter(function (p) { return checks[p.id] && checks[p.id].checked; }).map(function (p) { return p.id; }); }
    function offered(p) { return !p.optional || Array.isArray(data[p.id]); }  // older backups have no connectors

    function drawPreview(name) {
      clear(preview);
      var list = h("div", { class: "restore-parts" });
      checks = {};
      PARTS.filter(offered).forEach(function (p) {
        var cb = checks[p.id] = h("input", { type: "checkbox", checked: true, onchange: function () { runBtn.disabled = !selected().length; } });
        list.appendChild(h("label", { class: "perm-item" }, cb, h("span", {}, h("b", { text: p.label }), h("small", { text: p.desc(data) }))));
      });
      var runBtn = h("button", { class: "btn btn-danger solid", type: "button", onclick: run }, icon("upload"), "Restore");
      var checkBtn = h("button", { class: "btn", type: "button", onclick: function () { send(true, checkBtn); } }, icon("search"), "Check first");
      var made = data.created_at ? fmtDate(data.created_at) : "unknown date";
      append(preview, [
        h("div", { class: "restore-file" }, icon("file"), h("span", {}, h("strong", { text: name }), " · made " + made +
          (data.source ? " on " + data.source : "") + (data.fragq_version ? " · FragQ " + data.fragq_version : ""))),
        list,
        h("div", { class: "key-actions" }, checkBtn, runBtn),
        h("div", { class: "restore-report" })]);
      function run() {
        confirmModal({ title: "Restore backup", danger: true, ok: "Restore",
          text: "Overwrites the current values of everything you selected with the backup's. Channels and queues in the backup are created or updated; nothing that exists here is deleted." })
          .then(function (ok) { if (ok) send(false, runBtn); });
      }
    }

    function send(dry, btn) {
      var parts = selected();
      if (!parts.length) return;
      btn.disabled = true;
      api("POST", "/api/settings/restore", { backup: data, parts: parts, dry_run: dry }).then(function (r) {
        restoreErr.show(null);
        drawReport(r.report, dry);
        if (!dry) { toast("Backup restored."); refreshGuilds(); }
      }).catch(function (e) { restoreErr.show(e.message); }).then(function () { btn.disabled = false; });
    }

    function drawReport(rep, dry) {
      var box = preview.querySelector(".restore-report");
      clear(box);
      var lines = [];
      var NAMES = { panel_autorepost: "Auto-repost queue panels (now per channel)", panel_autorepost_minutes: "repost interval", require_steam_link: "Require Linked Steam IDs", steam_api_key: "Steam Web API key" };
      if (rep.settings) lines.push(["Bot settings", (dry ? "Would restore: " : "Restored: ") + rep.settings.restored.map(function (n) { return NAMES[n] || n; }).join(", ")]);
      if (rep.channels) {
        var c = rep.channels;
        lines.push(["Channels", c.created + (dry ? " to enable" : " enabled") + ", " + c.updated + (dry ? " to update" : " updated") + ", " + c.missing + " not found · queues: " +
          c.queues_created + (dry ? " to create" : " created") + ", " + c.queues_updated + (dry ? " to update" : " updated")]);
      }
      if (rep.steam_links) lines.push(["Steam links", rep.steam_links.added + (dry ? " to restore" : " restored") + ", " + rep.steam_links.skipped + " skipped"]);
      if (rep.connectors) lines.push(["Game connectors", rep.connectors.added + (dry ? " to add" : " added") + ", " + rep.connectors.replaced + (dry ? " to replace" : " replaced") + ", " + rep.connectors.missing + " skipped"]);
      if (rep.web_access) lines.push(["Web panel access", rep.web_access.added + (dry ? " to add" : " added") + ", " + rep.web_access.replaced + (dry ? " to replace" : " replaced") + ", " + rep.web_access.missing + " skipped"]);
      var notes = [];
      Object.keys(rep).forEach(function (k) { notes = notes.concat(rep[k].notes || []); });
      append(box, [
        h("div", { class: "restore-title", text: dry ? "Check: nothing was changed yet" : "Restore finished" }),
        h("table", { class: "dtable compact" }, h("tbody", {}, lines.map(function (l) { return h("tr", {}, h("td", {}, h("strong", { text: l[0] })), h("td", { text: l[1] })); }))),
        notes.length ? h("ul", { class: "restore-notes" }, notes.slice(0, 50).map(function (n) { return h("li", { text: n }); })) : null,
        notes.length > 50 ? h("p", { class: "faint", text: "…and " + (notes.length - 50) + " more." }) : null,
        !dry && rep.channels ? h("p", { class: "f-desc", text: "Queue panels aren't part of the backup: post them again on each channel page, or with !panel." }) : null,
      ]);
    }

    return h("section", { class: "panel" },
      h("div", { class: "panel-head" }, h("h2", { text: "Backup and restore" })),
      h("div", { class: "field" },
        h("div", { class: "f-head" }, h("span", { class: "f-title", text: "Back up FragQ settings" })),
        h("p", { class: "f-desc", text: "One file with the bot settings, every enabled channel with its settings, pause state and queues, the Steam links and the web panel access grants. " +
          "Restore it on a fresh FragQ install for the same Discord servers. Ratings and match history are not included: back up the database for those." }),
        h("div", { class: "f-body" },
          h("label", { class: "check-line" }, withKey, h("span", { text: "Include the Steam Web API key (the file then contains your key: keep it private)" })),
          h("div", { class: "key-actions" }, dlBtn))),
      h("div", { class: "field" },
        h("div", { class: "f-head" }, h("span", { class: "f-title", text: "Restore from a backup" })),
        h("p", { class: "f-desc", text: "Load a FragQ backup file, choose what to restore, and check what would change before restoring. Channels must be visible to the bot; invite it to the servers first." }),
        h("div", { class: "f-body" }, h("div", { class: "key-actions" }, loadBtn), file, restoreErr, preview)));
  }

  // ------------------------------------------------------------------ users page (web panel access, see webui/access.py)
  function renderUsers() {
    S.editor = null;
    var root = main();
    var gs = S.guilds.filter(function (g) { return g.manage_users; });
    append(root, h("div", { class: "page-head" }, h("div", {}, h("h1", { text: "Users" }),
      h("p", { text: "Give Discord members or roles access to this web panel. Discord commands keep using each channel's moderator and admin roles." }))));
    if (!gs.length) {
      append(root, h("div", { class: "panel" }, h("div", { class: "empty-state" }, icon("users"), h("h3", { text: "Nothing to manage" }),
        h("p", { text: "You don't have the Manage users permission on any server." }))));
      return;
    }
    var gid = gs.some(function (g) { return g.id === S.route.ugid; }) ? S.route.ugid : gs[0].id;
    if (gs.length > 1) {
      var seg = h("div", { class: "seg wrap" });
      gs.forEach(function (g) {
        seg.appendChild(h("button", { type: "button", class: g.id === gid ? "on" : "", onclick: function () { go({ page: "users", ugid: g.id }, true); } }, g.name));
      });
      root.appendChild(h("div", { class: "form-row", style: "margin:0 0 16px" }, seg));
    }
    var body = h("div", {}, h("div", { class: "empty-state" }, h("span", { class: "spinner" })));
    root.appendChild(body);
    function load() {
      Promise.all([api("GET", "/api/guilds/" + gid), api("GET", "/api/guilds/" + gid + "/access")]).then(function (res) {
        if (S.route.page !== "users") return;
        drawUsers(clear(body), res[0], res[1], load);
      }).catch(function (e) { clear(body); append(body, h("div", { class: "flash flash-error", text: e.message })); });
    }
    load();
  }

  function permLabel(d, name) {
    var c = d.catalog.find(function (x) { return x.name === name; });
    return c ? c.label : name;
  }

  function presetOf(d, perms) {
    var key = perms.slice().sort().join();
    var p = d.presets.find(function (x) { return x.perms.slice().sort().join() === key; });
    return p ? p.label : "Custom";
  }

  function scopeText(guild, channels) {
    if (!channels.length) return h("span", { text: "Whole server" });
    return h("span", { class: "mono", style: "font-size:12.5px", text: channels.map(function (id) {
      var c = guild.text_channels.find(function (x) { return x.id === id; });
      return "#" + (c ? c.name : id);
    }).join(", ") });
  }

  function subjectEl(s) {
    return h("span", { class: "who-cell" },
      s.type === "role" ? h("span", { class: "rdot", style: s.color ? "background:" + s.color : "" })
        : s.avatar ? h("img", { src: s.avatar, alt: "", class: "av-sm round" }) : icon("users"),
      h("strong", { text: (s.type === "role" ? "@" : "") + s.name }),
      h("span", { class: "badge", text: s.type === "role" ? "role" : "member" }));
  }

  function permsEl(d, perms) {
    return h("div", {}, h("span", { class: "badge blue", text: presetOf(d, perms) }),
      h("div", { class: "pchips" }, perms.filter(function (p) { return p !== "view"; }).map(function (p) { return h("span", { class: "pchip", text: permLabel(d, p) }); })));
  }

  function drawUsers(body, guild, d, reload) {
    var tbody = h("tbody");
    d.grants.forEach(function (g) {
      tbody.appendChild(h("tr", {},
        h("td", {}, subjectEl(g.subject)),
        h("td", {}, scopeText(guild, g.channels)),
        h("td", {}, permsEl(d, g.perms)),
        h("td", { class: "date" }, g.granted_by ? h("div", { text: "by " + g.granted_by }) : null, h("div", { class: "faint", text: fmtDate(g.updated_at || g.granted_at) })),
        h("td", { class: "num nowrap" }, g.editable ? [
          h("button", { class: "btn btn-sm", type: "button", onclick: function () { grantModal(guild, d, g, reload); } }, icon("edit"), "Edit"),
          h("button", { class: "btn btn-sm btn-ghost", type: "button", onclick: function () { revokeGrant(guild, g, reload); } }, icon("trash"), "Revoke"),
        ] : h("span", { class: "faint", title: "This entry has more access than you can manage", text: "—" }))));
    });
    if (!d.grants.length) tbody.appendChild(h("tr", {}, h("td", { colspan: "5" }, h("div", { class: "vt-empty", text: "Nobody has been given access yet. Use Grant access to add a member or a role." }))));

    var ibody = h("tbody");
    d.implicit.forEach(function (row) {
      ibody.appendChild(h("tr", {},
        h("td", {}, subjectEl(row.subject)),
        h("td", {}, scopeText(guild, row.channels)),
        h("td", {}, h("span", { class: "badge", text: row.perms.length === d.catalog.length ? "Everything" : "Channel admin" })),
        h("td", { class: "muted", text: row.why })));
    });

    append(body, [
      h("section", { class: "panel" },
        h("div", { class: "panel-head" }, h("h2", { text: "Access on " + guild.name }),
          h("button", { class: "btn btn-primary", type: "button", onclick: function () { grantModal(guild, d, null, reload); } }, icon("plus"), "Grant access")),
        h("div", { class: "scroll-x" }, h("table", { class: "dtable" },
          h("thead", {}, h("tr", {}, ["Who", "Access to", "Permissions", "Last changed", ""].map(function (t, i) { return h("th", { class: i === 4 ? "num" : "", text: t }); }))),
          tbody))),
      h("section", { class: "panel" },
        h("div", { class: "panel-head" }, h("h2", { text: "Built-in access" }), h("span", { class: "muted", style: "font-size:12.5px", text: "Comes from Discord and the bot config, can't be changed here" })),
        h("div", { class: "scroll-x" }, h("table", { class: "dtable" },
          h("thead", {}, h("tr", {}, ["Who", "Access to", "Permissions", "Why"].map(function (t) { return h("th", { text: t }); }))),
          ibody))),
    ]);
  }

  function revokeGrant(guild, g, reload) {
    confirmModal({ title: "Revoke access", danger: true, ok: "Revoke",
      text: (g.subject.type === "role" ? "Members with @" : "") + g.subject.name + (g.subject.type === "role" ? " lose" : " loses") + " the web panel access given here. Built-in access (server admin, channel admin role) is not affected." })
      .then(function (ok) {
        if (!ok) return;
        api("DELETE", "/api/guilds/" + guild.id + "/access/" + g.id).then(function () { toast("Access revoked."); reload(); })
          .catch(function (e) { toast(e.message, "error"); });
      });
  }

  function grantModal(guild, d, g, reload) {
    var editing = !!g;
    var ALL = d.catalog.map(function (c) { return c.name; });
    var canServer = d.me.admin || d.me.server.indexOf("manage_users") >= 0;
    var st = {
      type: editing ? g.subject.type : "user", subject: editing ? g.subject.id : null,
      scope: editing ? (g.channels.length ? "channels" : "server") : (canServer ? "server" : "channels"),
      channels: editing ? g.channels.slice() : [], perms: editing ? g.perms.slice() : ["view"],
    };
    var m = modal({ title: editing ? "Edit access" : "Grant access", wide: true });

    function mine(c) { return d.me.admin ? ALL : d.me.server.concat(d.me.channels[c] || []); }
    function held() {  // what this user may hand out over the chosen scope
      if (d.me.admin) return ALL;
      if (st.scope === "server") return d.me.server;
      var scope = st.channels.length ? st.channels : d.channels.map(function (c) { return c.id; });
      return ALL.filter(function (p) { return scope.every(function (c) { return mine(c).indexOf(p) >= 0; }); });
    }
    function serverOnly(p) { return (d.server_only || ["manage_channels"]).indexOf(p) >= 0; }
    function allowed(p) { return held().indexOf(p) >= 0 && !(serverOnly(p) && st.scope === "channels"); }

    var memberPicker = picker({ kind: "user", value: st.type === "user" ? st.subject : null, placeholder: "Search members…", items: [],
      search: function (q) {
        return api("GET", "/api/guilds/" + guild.id + "/access/members?q=" + encodeURIComponent(q)).then(function (r) {
          return r.members.map(function (u) { return { id: u.id, name: u.name, meta: u.username !== u.name ? u.username : "", avatar: u.avatar }; });
        });
      },
      onChange: function (v) { st.subject = v; draw(); } });
    var rolePicker = picker({ kind: "role", value: st.type === "role" ? st.subject : null, placeholder: "Select a role…",
      items: guild.roles.filter(function (r) { return r.name !== "@everyone" && !r.managed; }).map(function (r) { return { id: r.id, name: r.name, color: r.color }; }),
      onChange: function (v) { st.subject = v; draw(); } });
    var err = h("div", { class: "f-err hidden" });
    var save = h("button", { class: "btn btn-primary", type: "button", onclick: submit }, icon("check"), editing ? "Save" : "Grant access");
    var body = h("div");
    append(m.body, [body, err]);
    append(m.foot, [h("button", { class: "btn btn-ghost", type: "button", onclick: m.close }, "Cancel"), save]);

    function segBtn(label, on, fn, disabled) {
      return h("button", { type: "button", class: on ? "on" : "", disabled: !!disabled, onclick: fn }, label);
    }

    function draw() {
      st.perms = st.perms.filter(function (p) { return p === "view" || allowed(p); });
      if (st.perms.indexOf("view") < 0) st.perms.unshift("view");
      clear(body);
      // who
      body.appendChild(h("label", { class: "lbl", text: "Who" }));
      if (editing) {
        body.appendChild(subjectEl(g.subject));
      } else {
        append(body, [
          h("div", { class: "seg" },
            segBtn("Member", st.type === "user", function () { st.type = "user"; st.subject = null; memberPicker.setValue(null); draw(); }),
            segBtn("Role", st.type === "role", function () { st.type = "role"; st.subject = null; rolePicker.setValue(null); draw(); })),
          h("div", { style: "margin-top:8px;max-width:420px" }, st.type === "user" ? memberPicker : rolePicker),
        ]);
      }
      // scope
      append(body, h("div", { class: "form-row" }, h("label", { class: "lbl", text: "Access to" }),
        h("div", { class: "seg" },
          segBtn("Whole server", st.scope === "server", function () { st.scope = "server"; draw(); }, !canServer),
          segBtn("Specific channels", st.scope === "channels", function () { st.scope = "channels"; draw(); })),
        st.scope === "channels" ? h("div", { class: "chan-checks" }, d.channels.length ? d.channels.map(function (c) {
          var cb = h("input", { type: "checkbox", checked: st.channels.indexOf(c.id) >= 0, onchange: function () {
            st.channels = cb.checked ? st.channels.concat([c.id]) : st.channels.filter(function (x) { return x !== c.id; });
            draw();
          } });
          return h("label", {}, cb, icon("hash"), c.name);
        }) : h("span", { class: "muted", text: "No queue channels you can manage." })) : null,
        !canServer ? h("p", { class: "f-null", text: "You can only grant access on the channels where you can manage users." }) : null));
      // presets
      var presetRow = h("div", { class: "seg wrap" });
      d.presets.forEach(function (p) {
        var ok = p.perms.every(function (x) { return x === "view" || allowed(x); });
        presetRow.appendChild(segBtn(p.label, presetOf(d, st.perms) === p.label, function () { st.perms = p.perms.slice(); draw(); }, !ok));
      });
      append(body, h("div", { class: "form-row" }, h("label", { class: "lbl", text: "Preset" }), presetRow,
        h("span", { class: "muted", style: "margin-left:10px;font-size:12.5px", text: presetOf(d, st.perms) === "Custom" ? "Custom selection" : "" })));
      // permissions
      var groups = [];
      d.catalog.forEach(function (c) { if (groups.indexOf(c.group) < 0) groups.push(c.group); });
      var grid = h("div", { class: "perm-grid" });
      groups.forEach(function (gr) {
        var col = h("div", { class: "perm-group" }, h("h4", { text: gr }));
        d.catalog.filter(function (c) { return c.group === gr; }).forEach(function (c) {
          var dis = c.name === "view" || !allowed(c.name);
          var cb = h("input", { type: "checkbox", checked: st.perms.indexOf(c.name) >= 0, disabled: dis, onchange: function () {
            st.perms = cb.checked ? st.perms.concat([c.name]) : st.perms.filter(function (x) { return x !== c.name; });
            draw();
          } });
          var why = c.name === "view" ? "Always included." : serverOnly(c.name) && st.scope === "channels" ? "Whole-server access only." : !allowed(c.name) ? "You don't have this permission here, so you can't give it." : "";
          col.appendChild(h("label", { class: "perm-item" + (dis && c.name !== "view" ? " dis" : ""), title: why },
            cb, h("span", {}, h("b", { text: c.label }), h("small", { text: c.description + (why && c.name !== "view" ? " " + why : "") }))));
        });
        grid.appendChild(col);
      });
      append(body, h("div", { class: "form-row" }, h("label", { class: "lbl", text: "Permissions" }), grid));
      save.disabled = !st.subject || (st.scope === "channels" && !st.channels.length);
    }

    function submit() {
      err.classList.add("hidden");
      save.disabled = true;
      var payload = { channels: st.scope === "server" ? [] : st.channels, perms: st.perms };
      var req = editing ? api("PUT", "/api/guilds/" + guild.id + "/access/" + g.id, payload)
        : api("POST", "/api/guilds/" + guild.id + "/access", { subject_type: st.type, subject_id: st.subject, channels: payload.channels, perms: payload.perms });
      req.then(function () {
        m.close();
        toast(editing ? "Access updated." : "Access granted.");
        reload();
      }).catch(function (e) {
        save.disabled = false;
        err.classList.remove("hidden"); clear(err); append(err, [icon("alert"), h("span", { text: e.message })]);
      });
    }
    draw();
  }

  // ------------------------------------------------------------------ connectors page (game connectors, see bot/connectors.py)
  var DOCS = "https://d00msdaydevice.github.io/fragq/";
  var DENIED = { ip: "IP not allowed", expired: "key expired", disabled: "connector disabled", can_results: "results not allowed",
    can_check: "player checks not allowed", can_link: "Steam linking not allowed", can_export: "reading linked accounts not allowed" };

  function renderConnectors() {
    S.editor = null;
    var root = main();
    var gs = S.guilds.filter(function (g) { return g.manage_connectors; });
    append(root, h("div", { class: "page-head" }, h("div", {},
      h("h1", {}, "Connectors ", h("span", { class: "badge warn beta", text: "Beta" })),
      h("p", { text: "Let game servers send match results to FragQ, which posts them in the queue's channel when the match ends." }))));
    append(root, h("div", { class: "flash flash-info beta-note" }, icon("info"), h("span", {},
      h("strong", { text: "Connectors are in beta. " }),
      "Each game needs its own tool to send its results to FragQ, such as a server plugin or a script that reads the game's logs. FragQ includes a minqlx plugin for Quake Live. For other games, build one with the ",
      h("a", { href: DOCS + "connectors/result-format/", target: "_blank", rel: "noopener noreferrer", text: "result format" }), ".")));
    if (!gs.length) {
      append(root, h("div", { class: "panel" }, h("div", { class: "empty-state" }, icon("pulse"), h("h3", { text: "Nothing to manage" }),
        h("p", { text: "You don't have the Manage connectors permission on any server." }))));
      return;
    }
    var gid = gs.some(function (g) { return g.id === S.route.ugid; }) ? S.route.ugid : gs[0].id;
    if (gs.length > 1) {
      var seg = h("div", { class: "seg wrap" });
      gs.forEach(function (g) {
        seg.appendChild(h("button", { type: "button", class: g.id === gid ? "on" : "", onclick: function () { go({ page: "connectors", ugid: g.id }, true); } }, g.name));
      });
      root.appendChild(h("div", { class: "form-row", style: "margin:0 0 16px" }, seg));
    }
    var body = h("div", {}, h("div", { class: "empty-state" }, h("span", { class: "spinner" })));
    root.appendChild(body);
    var fresh = null;  // {id, key, rotated}: the key just created, shown once
    function load() {
      api("GET", "/api/guilds/" + gid + "/connectors").then(function (d) {
        if (S.route.page !== "connectors") return;
        drawConnectors(clear(body), gid, d, fresh, function (k) { fresh = k; load(); });
        fresh = null;
      }).catch(function (e) { clear(body); append(body, h("div", { class: "flash flash-error", text: e.message })); });
    }
    load();
  }

  function copyField(value, title) {
    return h("div", { class: "copy-field" }, h("code", { text: value }),
      h("button", { class: "icon-btn", type: "button", title: title, "aria-label": title, onclick: function () {
        navigator.clipboard.writeText(value).then(function () { toast("Copied to clipboard."); }, function () { toast("Couldn't copy: select the text instead.", "error"); });
      } }, icon("copy")));
  }

  function exportOnly(c) { return c.can_export && !c.can_results && !c.can_check && !c.can_link; }

  function gameOf(d, id) { return d.games.find(function (g) { return g.id === id; }) || d.games[0]; }

  function queueLabel(d, id) {
    var q = d.queues.find(function (x) { return x.id === id; });
    return q ? "#" + q.channel + " › " + q.name : "deleted queue";
  }

  function drawConnectors(body, gid, d, fresh, reload) {
    var base = "/api/guilds/" + gid + "/connectors";
    var newKey = null;
    if (fresh) {
      var c = d.connectors.find(function (x) { return x.id === fresh.id; });
      newKey = h("div", { class: "flash flash-ok new-key", role: "status" },
        h("strong", { text: (fresh.rotated ? "New key for " : "Connector created: ") + (c ? c.name : "") }),
        h("p", { text: "Copy the key now. It is shown only once" + (fresh.rotated ? ", and the previous key no longer works." : ".") }),
        copyField(fresh.key, "Copy key"),
        c && exportOnly(c) ? h("p", { class: "muted", text: "Enter it in Fragdex, under Settings › FragQ links." }) : null,
        h("p", { class: "muted", text: "Test it:" }),
        h("pre", { class: "example", text: 'curl -H "Authorization: Bearer ' + fresh.key + '" ' + d.api_url + "/status" }));
    }

    function cards(items, empty) {
      var list = h("div", { class: "conn-list" });
      items.forEach(function (c) { list.appendChild(connectorCard(d, base, c, reload)); });
      if (!items.length) list.appendChild(h("div", { class: "vt-empty", text: empty }));
      return list;
    }
    function count(items) {
      return h("span", { class: "muted", style: "margin-left:auto;margin-right:12px;font-size:12.5px", text: items.length + " connector" + (items.length === 1 ? "" : "s") });
    }
    var fragdex = d.connectors.filter(exportOnly);
    var others = d.connectors.filter(function (c) { return !exportOnly(c); });

    append(body, [
      h("section", { class: "panel" },
        h("div", { class: "panel-head" }, h("h2", { text: "Connection" })),
        h("div", { class: "field" },
          h("div", { class: "f-head" }, h("span", { class: "f-title", text: "Connector API address" })),
          h("p", { class: "f-desc", text: "Give a game server this address and the key of its connector. Every request sends the key in the header Authorization: Bearer <key>." }),
          h("div", { class: "f-body" }, copyField(d.api_url, "Copy address"))),
        h("div", { class: "field" },
          h("div", { class: "f-head" }, h("span", { class: "f-title", text: "Quake Live" }), h("span", { class: "badge", text: "minqlx · minqlxtended" })),
          h("p", { class: "f-desc", text: "The FragQ plugin sends end-of-match stats (Top Damage, Most Frags, Highest Accuracy, quitters…) and adds !link, so players can link their Steam account from the game. One file works on both minqlx and minqlxtended." }),
          h("div", { class: "f-body key-actions" },
            h("a", { class: "btn", href: d.plugins.quakelive, download: "fragq.py" }, icon("download"), "Download fragq.py"),
            h("a", { class: "btn btn-ghost", href: DOCS + "connectors/quake-live/", target: "_blank", rel: "noopener noreferrer" }, icon("book"), "Setup guide")))),
      newKey,
      h("section", { class: "panel" },
        h("div", { class: "panel-head" }, h("h2", { text: "Fragdex" }), count(fragdex),
          h("button", { class: "btn btn-primary", type: "button",
            onclick: function () { connectorModal(d, base, null, reload, true); } }, icon("plus"), "Create Fragdex connector")),
        h("div", { class: "field" },
          h("div", { class: "f-head" }, h("span", { class: "f-title", text: "FragQ address" })),
          h("p", { class: "f-desc", text: "Lets Fragdex read which Discord account each member of this server linked to their Steam account, and whether they proved it. In Fragdex, open Settings › FragQ links and enter this address and the key of a connector created here." }),
          h("div", { class: "f-body" }, copyField(d.public_url, "Copy address"))),
        cards(fragdex, "No Fragdex connector yet. Create one to get its key.")),
      h("section", { class: "panel" },
        h("div", { class: "panel-head" }, h("h2", { text: "Additional Connectors" }), count(others),
          h("button", { class: "btn btn-primary", type: "button",
            onclick: function () { connectorModal(d, base, null, reload); } }, icon("plus"), "Create connector")),
        cards(others, "No connectors yet. Create one for each game server, or for each tool that sends results.")),
    ]);
  }

  function connectorCard(d, base, c, reload) {
    var g = gameOf(d, c.game), fragdex = exportOnly(c);
    var st = { active: ["ok", "Active"], expired: ["danger", "Expired"], disabled: ["", "Disabled"] }[c.state];
    function act(path, done) {
      return api("POST", base + "/" + c.id + path).then(done).catch(function (e) { toast(e.message, "error"); });
    }
    var meta = [
      ["Queues", c.queues.length ? c.queues.map(function (q) { return queueLabel(d, q); }).join(", ")
        : c.can_results || c.can_check || c.can_link ? "None: the queues were deleted" : "None"],
      ["Results without a FragQ match", c.unmatched_queue ? "Posted in " + queueLabel(d, c.unmatched_queue) : "Not posted"],
      ["Allowed IPs", c.allowed_ips.length ? c.allowed_ips.join(", ") : "Any"],
      ["Rate limit", c.rate_limit ? c.rate_limit.toLocaleString() + "/min" : "Unlimited"],
      ["Expires", c.expires_at || "Never"],
      ["Last used", c.last_used_at ? fmtDate(c.last_used_at) + " from " + c.last_used_ip : "Never"],
      ["Requests", c.requests.toLocaleString()],
      ["Results", c.results ? c.results.toLocaleString() + ", last " + fmtDate(c.last_result_at) : "None yet"],
      ["Created", fmtDate(c.created_at) + (c.created_by ? " by " + c.created_by : "")],
    ];
    if (fragdex) meta = meta.filter(function (m) { return ["Queues", "Results without a FragQ match", "Results"].indexOf(m[0]) < 0; });
    if (c.last_denied_at) meta.push(["Last refused", fmtDate(c.last_denied_at) + " from " + c.last_denied_ip + ": " + (DENIED[c.last_denied_reason] || c.last_denied_reason), "denied"]);
    return h("article", { class: "conn-card" + (c.state !== "active" ? " is-off" : "") },
      h("div", { class: "conn-head" },
        h("div", { class: "conn-title" }, h("span", { class: "conn-game", text: g.emoji }),
          h("strong", { text: c.name }), h("code", { class: "faint", text: c.prefix + "…" }),
          h("span", { class: "badge " + st[0], text: st[1] }), fragdex ? null : h("span", { class: "badge", text: g.label })),
        h("div", { class: "pchips" },
          c.can_results ? h("span", { class: "pchip", text: "Match results" }) : null,
          c.can_check ? h("span", { class: "pchip", text: "Check linked players" }) : null,
          c.can_link ? h("span", { class: "pchip", text: "Link Steam from game" }) : null,
          c.can_export ? h("span", { class: "pchip", text: "Read linked accounts" }) : null)),
      h("dl", { class: "conn-meta" }, meta.map(function (m) { return h("div", { class: m[2] || "" }, h("dt", { text: m[0] }), h("dd", { text: m[1] })); })),
      h("div", { class: "key-actions" },
        h("button", { class: "btn btn-sm", type: "button", onclick: function () { connectorModal(d, base, c, reload); } }, icon("edit"), "Edit"),
        fragdex ? null : h("button", { class: "btn btn-sm", type: "button", disabled: !c.queues.length, onclick: function (e) {
          var b = e.currentTarget; b.disabled = true;
          act("/test", function (r) { toast("Test result posted in #" + r.channel + "."); }).then(function () { b.disabled = false; });
        } }, icon("upload"), "Send test result"),
        h("button", { class: "btn btn-sm", type: "button", onclick: function () {
          act("/toggle", function (r) { toast(r.connector.disabled ? "Connector disabled: its key is refused until you enable it." : "Connector enabled."); reload(); });
        } }, icon(c.disabled ? "play" : "pause"), c.disabled ? "Enable" : "Disable"),
        h("button", { class: "btn btn-sm", type: "button", onclick: function () {
          confirmModal({ title: "Replace key", ok: "Replace key", danger: true,
            text: "Replace the key of '" + c.name + "' with a new one? Its settings stay, but " + (fragdex ? "Fragdex" : "the game server") + " stops working until you give it the new key." })
            .then(function (ok) { if (ok) act("/rotate", function (r) { reload({ id: c.id, key: r.key, rotated: true }); }); });
        } }, icon("refresh"), "Replace key"),
        h("button", { class: "btn btn-sm btn-ghost", type: "button", onclick: function () {
          confirmModal({ title: "Delete connector", ok: "Delete", danger: true,
            text: "Delete the connector '" + c.name + "'? " + (fragdex ? "Fragdex can no longer read linked accounts with its key." : "Game servers using its key can no longer send results. Results already posted stay in Discord.") })
            .then(function (ok) {
              if (ok) api("DELETE", base + "/" + c.id).then(function () { toast("Connector deleted."); reload(); }).catch(function (e) { toast(e.message, "error"); });
            });
        } }, icon("trash"), "Delete")));
  }

  function connectorModal(d, base, c, reload, fragdex) {
    var editing = !!c;
    fragdex = fragdex || (editing && exportOnly(c));
    var m = modal({ title: (editing ? "Edit " : "Create ") + (fragdex ? "Fragdex connector" : "connector"), wide: true });
    var st = editing ? clone(c) : { name: "", game: "generic", queues: d.queues.length === 1 ? [d.queues[0].id] : [], unmatched_queue: "",
      can_results: true, can_check: true, can_link: true, can_export: false, allowed_ips: [], rate_limit: d.default_rate, expires_at: "" };
    if (fragdex && !editing) {
      st.name = "Fragdex";
      st.queues = [];
      st.can_results = st.can_check = st.can_link = false;
      st.can_export = true;
    }
    var name = h("input", { type: "text", maxlength: "60", value: st.name, placeholder: "CA server #1, CS2 retake server…" });
    var game = h("select", {}, d.games.map(function (g) { return h("option", { value: g.id, selected: g.id === st.game, text: g.emoji + "  " + g.label }); }));
    var gameNote = h("p", { class: "f-desc" });
    var unmatched = h("select");
    var rate = h("input", { type: "number", min: "0", max: String(d.max_rate), value: String(st.rate_limit), class: "mono", style: "max-width:140px" });
    var expires = h("input", { type: "date", value: st.expires_at || "" });
    var ips = h("textarea", { rows: "3", class: "mono", placeholder: "Any address. Or e.g. 203.0.113.10, 198.51.100.0/24" });
    ips.value = (st.allowed_ips || []).join("\n");
    var err = fieldErr();
    var save = h("button", { class: "btn btn-primary", type: "button", onclick: submit }, icon("check"), editing ? "Save" : "Create connector");

    var qbox = h("div", { class: "chan-checks conn-queues" });
    d.queues.forEach(function (q) {
      var cb = h("input", { type: "checkbox", checked: st.queues.indexOf(q.id) >= 0, onchange: function () {
        st.queues = cb.checked ? st.queues.concat([q.id]) : st.queues.filter(function (x) { return x !== q.id; });
        drawUnmatched();
      } });
      qbox.appendChild(h("label", {}, cb, icon("hash"), h("span", { class: "faint", text: q.channel + " › " }), q.name));
    });
    function drawUnmatched() {
      if (st.queues.indexOf(st.unmatched_queue) < 0) st.unmatched_queue = "";
      clear(unmatched);
      unmatched.appendChild(h("option", { value: "", text: "Don't post them (stored only)" }));
      st.queues.forEach(function (id) { unmatched.appendChild(h("option", { value: id, selected: id === st.unmatched_queue, text: "Post in " + queueLabel(d, id) })); });
    }
    unmatched.addEventListener("change", function () { st.unmatched_queue = unmatched.value; });
    function drawGame() {
      gameNote.textContent = game.value === "quakelive"
        ? "Use the FragQ minqlx plugin (Download fragq.py on this page). It needs all three permissions below for stats, the linked-player check and !link."
        : game.value === "generic"
          ? "For any game not listed. The game only changes the icon and colour of posted results; every game sends the same result format."
          : "There is no ready-made plugin for this game yet: it needs a tool that sends results in FragQ's result format (beta).";
    }
    game.addEventListener("change", drawGame);

    var perms = [
      ["can_results", "Send match results", "Post end-of-match results and stats in the queue's channel."],
      ["can_check", "Check linked players", "Ask whether players have linked a Steam account, so the server can keep unlinked players in spectator."],
      ["can_link", "Link Steam accounts from the game", "Players can type !link on the game server. FragQ asks them to confirm in a Discord direct message."],
      ["can_export", "Read linked accounts", "Read every Steam and Discord link of this server's members, for a tool such as Fragdex. Needs no queue. Don't give this to a game server."],
    ].map(function (p) {
      var cb = h("input", { type: "checkbox", checked: !!st[p[0]], onchange: function () { st[p[0]] = cb.checked; } });
      return h("label", { class: "perm-item" }, cb, h("span", {}, h("b", { text: p[1] }), h("small", { text: p[2] })));
    });

    function row(label, el, hint) {
      return h("div", { class: "form-row" }, h("label", { class: "lbl", text: label }), el, hint ? h("p", { class: "f-null", text: hint }) : null);
    }
    append(m.body, [
      fragdex ? row("Name", name) : [h("div", { class: "conn-form-grid" }, row("Name", name), row("Game", game)),
      gameNote,
      row("Queues", d.queues.length ? qbox : h("span", { class: "muted", text: "No queues on this server yet." }),
        "Results are matched to a FragQ match of these queues by the players' linked Steam accounts. A key that only reads linked accounts needs none."),
      row("Results without a FragQ match", unmatched, "When no recent match of these queues has most of the game's players, for example when players aren't linked."),
      row("What the key can do", h("div", { class: "perm-grid one" }, perms))],
      h("div", { class: "conn-form-grid" },
        row("Rate limit (requests / minute)", rate, "0 = unlimited"),
        row("Expires", expires, "Works through this day (UTC). Empty = never.")),
      row("Allowed IPs", ips, "IP addresses or ranges, one per line. Empty = any address. Use the " + (fragdex ? "address Fragdex connects from." : "game server's public address.")),
      err]);
    append(m.foot, [h("button", { class: "btn btn-ghost", type: "button", onclick: m.close }, "Cancel"), save]);
    drawUnmatched();
    drawGame();
    name.focus();

    function submit() {
      save.disabled = true;
      var payload = { name: name.value, game: game.value, queues: st.queues, unmatched_queue: st.unmatched_queue,
        can_results: st.can_results, can_check: st.can_check, can_link: st.can_link, can_export: st.can_export,
        rate_limit: rate.value, expires_at: expires.value, allowed_ips: ips.value };
      (editing ? api("PUT", base + "/" + c.id, payload) : api("POST", base, payload)).then(function (r) {
        m.close();
        toast(editing ? "Connector saved." : "Connector created.");
        reload(editing ? null : { id: r.connector.id, key: r.key });
      }).catch(function (e) { save.disabled = false; err.show(e.message); });
    }
  }

  // ------------------------------------------------------------------ channel page
  var CHANNEL_VIEWS = [
    { id: "settings", label: "Settings", icon: "gear" },
    { id: "live", label: "Live", icon: "pulse" },
    { id: "leaderboard", label: "Leaderboard", icon: "trophy", perm: "stats" },
    { id: "matches", label: "Matches", icon: "history", perm: "stats" },
  ];

  function findChannel(cid) { return S.guild.channels.find(function (c) { return c.id === cid; }); }

  function crumbs(parts) {
    var el = h("div", { class: "crumbs" });
    parts.forEach(function (p, i) {
      if (i) el.appendChild(icon("chevron-right"));
      el.appendChild(p.route ? h("a", { text: p.label, onclick: function () { go(p.route); } }) : h("span", { text: p.label }));
    });
    return el;
  }

  function renderChannel() {
    var r = S.route, c = findChannel(r.cid);
    if (!c) return mainMessage("alert", "Channel not found", "It may have been disabled, or you don't have its admin role.");
    var root = main();
    var head = h("div", { class: "page-head" },
      h("div", {}, crumbs([{ label: S.guild.name, route: { gid: r.gid } }, { label: "Queue channel" }]),
        h("div", { class: "title" }, icon("hash"), h("h1", { text: c.name }),
          c.paused ? h("span", { class: "badge warn", text: "Paused" }) : null)),
      h("div", { class: "head-actions" },
        can("pause", c) ? h("button", { class: "btn" + (c.paused ? " btn-warn" : ""), type: "button",
          title: c.paused ? "Let players join again" : "Stop players joining. Moderators can still add players from the queue panel.",
          onclick: function () { pauseAction(c, !c.paused); } }, icon(c.paused ? "play" : "pause"), c.paused ? "Queue paused" : "Pause queue") : null,
        can("panel", c) ? h("button", { class: "btn", type: "button", title: "Discord message with Join/Leave buttons that updates live",
          onclick: function () { panelAction(c, true); } }, icon("panel"), c.panel ? "Move panel down" : "Post queue panel") : null,
        can("panel", c) && c.panel ? h("button", { class: "btn btn-ghost", type: "button", title: "Delete the queue panel message",
          onclick: function () { panelAction(c, false); } }, icon("x"), "Remove panel") : null,
        h("button", { class: "btn", type: "button", onclick: function () { cfgModal("channel", c); } }, icon("swap"), can("edit_channel", c) ? "Import / export" : "Export"),
        can("manage_queues", c) ? h("button", { class: "btn btn-primary", type: "button", onclick: function () { createQueueModal(c); } }, icon("plus"), "Create queue") : null));
    var views = h("div", { class: "views", role: "tablist" });
    var allowedViews = CHANNEL_VIEWS.filter(function (v) { return !v.perm || can(v.perm, c); });
    if (!allowedViews.some(function (v) { return v.id === r.view; })) r.view = "settings";
    allowedViews.forEach(function (v) {
      views.appendChild(h("button", { class: "tab" + (r.view === v.id ? " active" : ""), type: "button", role: "tab",
        onclick: function () { go({ gid: r.gid, cid: r.cid, view: v.id }); } }, icon(v.icon), v.label));
    });
    var body = h("div");
    append(root, [head, views, body]);
    if (r.view === "live") return renderLive(body, c);
    if (r.view === "leaderboard") return renderLeaderboard(body, c);
    if (r.view === "matches") return renderMatches(body, c);
    if (S.editor && S.editor.cid === c.id && !S.editor.qid) { S.editor.mount(body); return; }
    body.appendChild(h("div", { class: "empty-state" }, h("span", { class: "spinner" })));
    api("GET", "/api/channels/" + c.id).then(function (d) {
      if (S.route.cid !== c.id || S.route.qid || S.route.view !== "settings") return;
      S.editor = new Editor({
        kind: "channel", gid: r.gid, cid: c.id, schema: S.schema.channel, values: d.values,
        base: "/api/channels/" + c.id, readOnly: !can("edit_channel", c),
      });
      S.editor.mount(clear(body));
    }).catch(function (e) { clear(body); append(body, h("div", { class: "flash flash-error", text: e.message })); });
  }

  function renderQueue() {
    var r = S.route, c = findChannel(r.cid);
    var q = c && c.queues.find(function (x) { return x.id === r.qid; });
    if (!q) return mainMessage("alert", "Queue not found", "It may have been deleted.");
    var root = main();
    var head = h("div", { class: "page-head" },
      h("div", {}, crumbs([{ label: S.guild.name, route: { gid: r.gid } }, { label: "#" + c.name, route: { gid: r.gid, cid: c.id } }, { label: "Pickup queue" }]),
        h("div", { class: "title" }, icon("queue"), h("h1", { text: q.name }), h("span", { class: "t-count" + (q.players ? " hot" : ""), text: q.players + "/" + q.size }))),
      h("div", { class: "head-actions" },
        can("clear_queues", c) && q.players ? h("button", { class: "btn", type: "button", onclick: function () { clearQueue(c, q); } }, icon("eraser"), "Remove all players") : null,
        h("button", { class: "btn", type: "button", onclick: function () { cfgModal("queue", c, q); } }, icon("swap"), can("edit_queue", c) ? "Import / export" : "Export"),
        can("manage_queues", c) ? h("button", { class: "btn btn-danger", type: "button", onclick: function () { deleteQueue(c, q); } }, icon("trash"), "Delete") : null));
    var body = h("div");
    append(root, [head, body]);
    if (S.editor && S.editor.qid === q.id) { S.editor.mount(body); return; }
    body.appendChild(h("div", { class: "empty-state" }, h("span", { class: "spinner" })));
    var base = "/api/channels/" + c.id + "/queues/" + q.id;
    api("GET", base).then(function (d) {
      if (S.route.qid !== q.id) return;
      S.editor = new Editor({ kind: "queue", gid: r.gid, cid: c.id, qid: q.id, schema: S.schema.queue, values: d.values, base: base,
        readOnly: !can("edit_queue", c), onSaved: function () { reloadGuild().then(route); } });
      S.editor.mount(clear(body));
    }).catch(function (e) { clear(body); append(body, h("div", { class: "flash flash-error", text: e.message })); });
  }

  function renderLive(body, c) {
    S.editor = null;
    function load() {
      api("GET", "/api/channels/" + c.id + "/live").then(function (d) {
        if (S.route.cid !== c.id || S.route.view !== "live") return;
        clear(body);
        append(body, h("div", { class: "grid-2" },
          h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h2", { text: "Queues" }), h("span", { class: "badge ok", text: "live" })),
            d.queues.length ? d.queues.map(function (q) { return queueCard(q); })
              : h("div", { class: "empty-state", style: "padding:34px" }, h("p", { text: "No queues on this channel yet." }))),
          h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h2", { text: "Matches in progress" })),
            d.matches.length ? d.matches.map(function (m) { return matchCard(m); })
              : h("div", { class: "empty-state", style: "padding:34px" }, h("p", { text: "No matches in progress." })))));
      }).catch(function (e) { clear(body); append(body, h("div", { class: "flash flash-error", text: e.message })); });
    }
    body.appendChild(h("div", { class: "empty-state" }, h("span", { class: "spinner" })));
    load();
    setTimer(load, 5000);
  }

  function csvButtons(c) {
    if (!can("stats", c)) return null;
    return h("div", { class: "head-actions" },
      h("a", { class: "btn btn-sm", href: "/api/channels/" + c.id + "/stats/players.csv" }, icon("download"), "Players CSV"),
      h("a", { class: "btn btn-sm", href: "/api/channels/" + c.id + "/stats/matches.csv" }, icon("download"), "Matches CSV"));
  }

  function renderLeaderboard(body, c) {
    S.editor = null;
    body.appendChild(h("div", { class: "empty-state" }, h("span", { class: "spinner" })));
    api("GET", "/api/channels/" + c.id + "/leaderboard").then(function (d) {
      clear(body);
      var search = h("input", { type: "search", placeholder: "Search players…", style: "max-width:260px;height:30px;font-size:13px" });
      var tbody = h("tbody");
      function draw() {
        clear(tbody);
        var term = search.value.trim().toLowerCase();
        var n = 0;
        d.players.forEach(function (p, i) {
          if (term && String(p.nick || "").toLowerCase().indexOf(term) < 0) return;
          n++;
          var games = p.wins + p.losses + p.draws;
          tbody.appendChild(h("tr", { style: p.hidden ? "opacity:.5" : "" },
            h("td", { class: "rk", text: String(i + 1) }),
            h("td", {}, h("strong", { text: p.nick || p.user_id }), p.hidden ? h("span", { class: "faint", text: "  hidden" }) : null),
            h("td", { class: "mono", text: p.rank || "" }),
            h("td", { class: "num" }, String(p.rating), h("span", { class: "faint", text: " ±" + p.deviation })),
            h("td", { class: "num" }, h("span", { class: "win", text: String(p.wins) }), " / ", h("span", { class: "loss", text: String(p.losses) }), " / " + p.draws),
            h("td", { class: "num", text: games ? Math.round(100 * p.wins / games) + "%" : "—" }),
            h("td", { class: "num " + (p.streak > 0 ? "win" : p.streak < 0 ? "loss" : ""), text: (p.streak > 0 ? "+" : "") + p.streak }),
            h("td", { class: "date", text: p.last_match ? fmtDate(p.last_match) : "—" })));
        });
        if (!n) tbody.appendChild(h("tr", {}, h("td", { colspan: "8" }, h("div", { class: "vt-empty", text: d.players.length ? "No matches." : "No rated players yet. Ratings appear after the first ranked match." }))));
      }
      search.addEventListener("input", draw);
      append(body, h("section", { class: "panel" },
        h("div", { class: "panel-head" }, h("div", { style: "display:flex;gap:12px;align-items:center;flex-wrap:wrap" }, h("h2", { text: "Leaderboard" }),
          h("span", { class: "badge blue", text: d.rating_system }), search), csvButtons(c)),
        h("div", { class: "scroll-x" }, h("table", { class: "dtable" },
          h("thead", {}, h("tr", {}, ["#", "Player", "Rank", "Rating", "W / L / D", "Win %", "Streak", "Last match"].map(function (t, i) {
            return h("th", { class: i >= 3 && i <= 6 ? "num" : "", text: t });
          }))), tbody))));
      draw();
    }).catch(function (e) { clear(body); append(body, h("div", { class: "flash flash-error", text: e.message })); });
  }

  function renderMatches(body, c) {
    S.editor = null;
    body.appendChild(h("div", { class: "empty-state" }, h("span", { class: "spinner" })));
    api("GET", "/api/channels/" + c.id + "/matches?limit=100").then(function (d) {
      clear(body);
      var tbody = h("tbody");
      d.matches.forEach(function (m) {
        var alpha = m.players.filter(function (p) { return p.team === 0; }).map(function (p) { return p.nick; });
        var beta = m.players.filter(function (p) { return p.team === 1; }).map(function (p) { return p.nick; });
        var other = m.players.filter(function (p) { return p.team !== 0 && p.team !== 1; }).map(function (p) { return p.nick; });
        var res = m.winner === 0 ? m.alpha : m.winner === 1 ? m.beta : (m.ranked ? "Draw" : "—");
        tbody.appendChild(h("tr", {},
          h("td", { class: "rk", text: "#" + m.id }),
          h("td", { class: "date", text: fmtDate(m.at) }),
          h("td", {}, h("strong", { text: m.queue }), m.ranked ? h("span", { class: "badge ok", style: "margin-left:8px", text: "ranked" }) : null),
          h("td", { style: "font-size:13px" },
            alpha.length || beta.length ? [h("span", { class: m.winner === 0 ? "win" : "", text: (m.alpha || "A") + ": " + alpha.join(", ") }), h("br"),
              h("span", { class: m.winner === 1 ? "win" : "", text: (m.beta || "B") + ": " + beta.join(", ") })] : other.join(", ")),
          h("td", { class: "muted", style: "font-size:13px", text: m.maps || "" }),
          h("td", { text: res })));
      });
      if (!d.matches.length) tbody.appendChild(h("tr", {}, h("td", { colspan: "6" }, h("div", { class: "vt-empty", text: "No matches played on this channel yet." }))));
      append(body, h("section", { class: "panel" },
        h("div", { class: "panel-head" }, h("h2", { text: "Last " + d.matches.length + " matches" }), csvButtons(c)),
        h("div", { class: "scroll-x" }, h("table", { class: "dtable" },
          h("thead", {}, h("tr", {}, ["Match", "Date", "Queue", "Teams", "Maps", "Winner"].map(function (t) { return h("th", { text: t }); }))), tbody))));
    }).catch(function (e) { clear(body); append(body, h("div", { class: "flash flash-error", text: e.message })); });
  }

  // ------------------------------------------------------------------ settings editor
  function Editor(o) {
    this.kind = o.kind; this.gid = o.gid; this.cid = o.cid; this.qid = o.qid;
    this.schema = o.schema; this.base = o.base; this.onSaved = o.onSaved; this.readOnly = !!o.readOnly;
    this.vars = {};
    var self = this;
    o.schema.variables.forEach(function (v) { self.vars[v.name] = v; });
    this.setValues(o.values);
    this.errors = {};
    this.section = null;
  }

  Editor.prototype.setValues = function (values) {
    this.values = values;
    this.draft = clone(values);
    this.open = {};
    for (var k in this.vars) this.open[k] = values[k] !== null && values[k] !== undefined;
  };
  Editor.prototype.sameTarget = function (r) {
    return r.cid === this.cid && (r.qid || null) === (this.qid || null) && (this.qid || (r.view || "settings") === "settings");
  };
  Editor.prototype.path = function () {
    return link({ gid: this.gid, cid: this.cid, qid: this.qid, view: "settings", section: this.section ? slug(this.section) : null });
  };
  Editor.prototype.isDirty = function (name) {
    var d = this.open[name] ? this.draft[name] : null;
    if (d === "") d = null;
    return !same(d, this.values[name]);
  };
  Editor.prototype.dirtyCount = function () {
    if (this.readOnly) return 0;
    var n = 0;
    for (var k in this.vars) if (this.isDirty(k)) n++;
    return n;
  };

  // Settings shown as a switch at the right end of their section's tab bar instead of as a field.
  // On: the value is the number typed next to it (start says what switching it on fills in). Off: not set.
  var BAR_VARS = { panel_autorefresh: { label: "Auto-refresh panel", before: "every", after: "min", start: "5", min: 1, max: 1440 } };

  Editor.prototype.mount = function (el) {
    this.el = el;
    var secs = this.schema.sections;
    var want = S.route.section;
    this.section = secs.find(function (s) { return slug(s) === want; }) || this.section || secs[0];
    this.render();
  };

  Editor.prototype.render = function () {
    var self = this, el = clear(this.el);
    var chips = h("div", { class: "sections", role: "tablist" });
    this.schema.sections.forEach(function (sec) {
      var names = self.schema.variables.filter(function (v) { return v.section === sec; }).map(function (v) { return v.name; });
      var err = names.some(function (n) { return self.errors[n]; });
      var dirty = names.some(function (n) { return self.isDirty(n); });
      chips.appendChild(h("button", { class: "chip" + (sec === self.section ? " active" : ""), type: "button", role: "tab",
        onclick: function () {
          self.section = sec;
          history.replaceState(null, "", self.path());
          S.route = parseRoute(location.pathname);
          self.render();
        } }, sec, err ? h("span", { class: "bubble err" }) : dirty ? h("span", { class: "bubble dirty" }) : null));
    });
    this.chips = chips;
    var barErrs = [];
    this.schema.variables.forEach(function (v) {
      if (!BAR_VARS[v.name] || v.section !== self.section) return;
      chips.appendChild(self.barToggle(v));
      if (self.errors[v.name]) barErrs.push(h("div", { class: "f-err bar-err" }, icon("alert"), self.errors[v.name]));
    });
    var panel = h("section", { class: "panel" });
    this.schema.variables.forEach(function (v) {
      if (v.section === self.section && !BAR_VARS[v.name]) panel.appendChild(self.renderField(v));
    });
    this.bar = h("div");
    if (this.readOnly) {  // a disabled fieldset turns off every control inside it
      var ro = h("fieldset", { class: "ro-fields", disabled: true }, panel);
      append(el, [chips, barErrs, h("div", { class: "flash flash-warn ro-note" }, icon("info"),
        h("span", { text: "Read-only: you can view these settings, but you don't have permission to change them." })), ro]);
      return;
    }
    append(el, [chips, barErrs, panel, this.bar]);
    this.updateBar();
  };

  Editor.prototype.barToggle = function (v) {
    var self = this, name = v.name, b = BAR_VARS[name], on = !!this.open[name];
    var cb = h("input", { type: "checkbox", checked: on, disabled: this.readOnly, "aria-label": v.display,
      onchange: function () {
        self.open[name] = cb.checked;
        if (cb.checked && !self.draft[name]) self.draft[name] = b.start;
        self.refreshField(name);
      } });
    var num = on ? h("input", { type: "number", class: "mono", min: String(b.min), max: String(b.max), step: "1", disabled: this.readOnly,
      value: this.draft[name] === null || this.draft[name] === undefined ? "" : this.draft[name], "aria-label": v.display + " (" + b.after + ")",
      oninput: function (e) { self.set(name, e.target.value.trim()); } }) : null;
    return h("div", { class: "bar-toggle" + (this.isDirty(name) ? " dirty" : "") + (this.errors[name] ? " err" : ""), "data-name": name, title: v.description },
      h("span", { class: "bt-label", text: b.label }),
      on ? [h("span", { text: b.before }), num, h("span", { text: b.after })] : null,
      h("label", { class: "switch", title: on ? "On" : "Off" }, cb, h("span")));
  };

  Editor.prototype.refreshField = function (name) {
    var old = this.el.querySelector('[data-name="' + name + '"]');
    if (old) old.replaceWith(BAR_VARS[name] ? this.barToggle(this.vars[name]) : this.renderField(this.vars[name]));
    this.updateBar();
  };

  Editor.prototype.changed = function (name) {
    var f = this.el.querySelector('[data-name="' + name + '"]');
    if (f) f.classList.toggle("dirty", this.isDirty(name));
    this.updateBar();
  };

  Editor.prototype.updateBar = function () {
    var self = this, n = this.dirtyCount();
    // refresh section markers
    if (this.chips) {
      Array.prototype.forEach.call(this.chips.children, function (chip, i) {
        var sec = self.schema.sections[i];
        var names = self.schema.variables.filter(function (v) { return v.section === sec; }).map(function (v) { return v.name; });
        var err = names.some(function (k) { return self.errors[k]; }), dirty = names.some(function (k) { return self.isDirty(k); });
        var b = chip.querySelector(".bubble");
        if (b) b.remove();
        if (err || dirty) chip.appendChild(h("span", { class: "bubble " + (err ? "err" : "dirty") }));
      });
    }
    clear(this.bar);
    if (!n) return;
    this.saveBtn = h("button", { class: "btn btn-primary", type: "button", onclick: function () { self.save(); } }, icon("check"), "Save changes");
    append(this.bar, h("div", { class: "savebar" },
      h("div", { class: "msg" }, icon("alert"), n + " unsaved change" + (n === 1 ? "" : "s")),
      h("button", { class: "btn btn-ghost", type: "button", onclick: function () { self.discard(); } }, "Discard"),
      this.saveBtn));
  };

  Editor.prototype.discard = function () {
    this.setValues(this.values);
    this.errors = {};
    this.render();
  };

  Editor.prototype.save = function () {
    var self = this, payload = {};
    for (var k in this.vars) {
      if (!this.isDirty(k)) continue;
      var v = this.open[k] ? this.draft[k] : null;
      payload[k] = v === "" ? null : v;
    }
    if (this.saveBtn) this.saveBtn.disabled = true;
    api("PUT", this.base, { values: payload }).then(function (d) {
      self.errors = {};
      self.setValues(d.values);
      self.render();
      toast("Settings saved.");
      if (self.onSaved) self.onSaved(d);
    }).catch(function (e) {
      if (self.saveBtn) self.saveBtn.disabled = false;
      if (e.fields) {
        self.errors = e.fields;
        var first = Object.keys(e.fields)[0];
        var v = self.vars[first];
        if (v && v.section !== self.section) self.section = v.section;
        self.render();
        toast(e.message, "error");
      } else toast(e.message, "error");
    });
  };

  Editor.prototype.reset = function (v) {
    var self = this;
    api("POST", this.base + "/reset/" + v.name).then(function (d) {
      self.values = d.values;
      self.draft[v.name] = clone(d.values[v.name]);
      self.open[v.name] = d.values[v.name] !== null && d.values[v.name] !== undefined;
      delete self.errors[v.name];
      self.refreshField(v.name);
      toast(v.display + " reset to default.");
      if (self.onSaved) self.onSaved(d);
    }).catch(function (e) { toast(e.message, "error"); });
  };

  function blankFor(v) {
    if (v.default !== null && v.default !== undefined) return clone(v.default);
    switch (v.type) {
      case "bool": return "off";
      case "option": return v.options[0];
      case "slider": return "100";
      case "duration": return "00:05:00";
      case "table": return [];
      case "role": case "channel": case "member": return null;
      default: return "";
    }
  }

  Editor.prototype.renderField = function (v) {
    var self = this, name = v.name;
    var f = h("div", { class: "field" + (this.isDirty(name) ? " dirty" : "") + (this.errors[name] ? " field-error" : ""), "data-name": name });
    var inline = v.type === "bool" && !v.nullable;
    var tools = [];
    if (name !== "name") {
      tools.push(h("button", { class: "icon-btn", type: "button", title: "Reset to default", "aria-label": "Reset " + v.display + " to default",
        onclick: function () {
          confirmModal({ title: "Reset " + v.display, text: "Reset this setting to its default value? It is saved immediately.", ok: "Reset" })
            .then(function (ok) { if (ok) self.reset(v); });
        } }, icon("reset")));
    }
    var sw = null;
    if (v.nullable) {
      var cb = h("input", { type: "checkbox", checked: this.open[name], "aria-label": "Enable " + v.display,
        onchange: function () {
          self.open[name] = cb.checked;
          if (cb.checked && (self.draft[name] === null || self.draft[name] === undefined)) self.draft[name] = blankFor(v);
          self.refreshField(name);
        } });
      sw = h("label", { class: "switch", title: this.open[name] ? "Enabled" : "Disabled" }, cb, h("span"));
    }
    var head = h("div", { class: "f-head" },
      h("span", { class: "f-title", text: v.display }),
      h("code", { class: "f-name", text: name }),
      tools, h("span", { class: "grow" }), sw);
    var desc = v.description ? h("p", { class: "f-desc", text: v.description }) : null;
    var body = null;
    if (!v.nullable || this.open[name]) {
      body = h("div", { class: "f-body" }, this.widget(v));
    } else {
      body = h("div", { class: "f-null", text: "Not set" + (v.default !== null && v.default !== undefined && v.type !== "table" ? " — enabling it starts from " + v.default : "") + "." });
    }
    if (inline) {
      append(f, h("div", { class: "f-row-inline" }, h("div", {}, head, desc), body));
    } else {
      append(f, [head, desc, body]);
    }
    if (this.errors[name]) append(f, h("div", { class: "f-err" }, icon("alert"), this.errors[name]));
    return f;
  };

  Editor.prototype.set = function (name, value) {
    this.draft[name] = value;
    this.changed(name);
  };

  Editor.prototype.widget = function (v) {
    var self = this, name = v.name, val = this.draft[name];
    switch (v.type) {
      case "bool": return seg(["off", "on"], val, function (x) { self.set(name, x); });
      case "option":
        if (v.options.length <= 4 && v.options.join("").length < 40) return seg(v.options, val, function (x) { self.set(name, x); }, true);
        var sel = h("select", { onchange: function () { self.set(name, sel.value); } },
          v.options.map(function (o) { return h("option", { value: o, selected: o === val, text: o }); }));
        return sel;
      case "int":
        return h("input", { type: "number", class: "short", value: val === null ? "" : val, step: "1",
          oninput: function (e) { self.set(name, e.target.value.trim()); } });
      case "slider": return slider(v, val, function (x) { self.set(name, x); });
      case "text":
        var ta = h("textarea", { rows: String(Math.min(12, Math.max(3, String(val || "").split("\n").length + 1))), value: val || "",
          oninput: function (e) { self.set(name, e.target.value); } });
        return ta;
      case "duration": return duration(val, function (x) { self.set(name, x); });
      case "role": return rolePicker(val, function (x) { self.set(name, x); });
      case "channel": return channelPicker(val, function (x) { self.set(name, x); });
      case "table": return this.table(v);
      default:
        return h("input", { type: "text", value: val === null ? "" : val, autocomplete: "off", spellcheck: "false",
          oninput: function (e) { self.set(name, e.target.value); } });
    }
  };

  function seg(options, val, onChange, plain) {
    var el = h("div", { class: "seg", role: "radiogroup" });
    options.forEach(function (o) {
      var b = h("button", { class: (plain ? "" : o) + (o === val ? " on" : ""), type: "button", role: "radio", "aria-checked": o === val ? "true" : "false",
        onclick: function () {
          Array.prototype.forEach.call(el.children, function (c) { c.classList.remove("on"); c.setAttribute("aria-checked", "false"); });
          b.classList.add("on"); b.setAttribute("aria-checked", "true");
          onChange(o);
        } }, plain ? o : (o === "on" ? icon("check") : icon("x")), plain ? null : " " + o);
      el.appendChild(b);
    });
    return el;
  }

  function slider(v, val, onChange) {
    var num = h("input", { type: "number", min: String(v.min), max: String(v.max), value: val === null ? "" : val });
    var rng = h("input", { type: "range", min: String(v.min), max: String(v.max), step: "5", value: val === null ? "100" : val });
    rng.addEventListener("input", function () { num.value = rng.value; onChange(rng.value); });
    num.addEventListener("input", function () { rng.value = num.value; onChange(num.value.trim()); });
    return h("div", { class: "slider" }, rng, h("div", { class: "num" }, num, h("span", { class: "muted mono", text: v.unit })));
  }

  function pad(n) { n = String(n); return n.length < 2 ? "0" + n : n; }
  function duration(val, onChange) {
    var parts = String(val || "00:00:00").split(":").map(function (x) { return parseInt(x, 10) || 0; });
    while (parts.length < 3) parts.unshift(0);
    var hrs = h("input", { type: "number", min: "0", value: String(parts[0]), "aria-label": "Hours" });
    var mins = h("input", { type: "number", min: "0", max: "59", value: pad(parts[1]), "aria-label": "Minutes" });
    var secs = h("input", { type: "number", min: "0", max: "59", value: pad(parts[2]), "aria-label": "Seconds" });
    function emit() {
      var t = (parseInt(hrs.value, 10) || 0) * 3600 + (parseInt(mins.value, 10) || 0) * 60 + (parseInt(secs.value, 10) || 0);
      onChange(pad(Math.floor(t / 3600)) + ":" + pad(Math.floor(t % 3600 / 60)) + ":" + pad(t % 60));
    }
    [hrs, mins, secs].forEach(function (i) { i.addEventListener("input", emit); });
    mins.addEventListener("change", function () { mins.value = pad(mins.value || 0); });
    secs.addEventListener("change", function () { secs.value = pad(secs.value || 0); });
    return h("div", { class: "dur" }, hrs, h("span", { class: "u", text: "h" }), h("span", { class: "sep" }),
      mins, h("span", { class: "u", text: "m" }), h("span", { class: "sep" }), secs, h("span", { class: "u", text: "s" }));
  }

  function rolePicker(val, onChange) {
    return picker({ kind: "role", value: val, placeholder: "Select a role…", missing: "Missing role", allowNone: true, noneLabel: "No role",
      items: S.guild.roles.map(function (r) { return { id: r.id, name: r.name, color: r.color, meta: r.managed ? "bot" : "" }; }),
      onChange: onChange });
  }
  function channelPicker(val, onChange) {
    return picker({ kind: "channel", value: val, placeholder: "Select a channel…", missing: "Missing channel", allowNone: true, noneLabel: "No channel",
      items: S.guild.text_channels.map(function (c) { return { id: c.id, name: c.name, meta: c.category || "" }; }),
      onChange: onChange });
  }

  Editor.prototype.table = function (v) {
    var self = this, name = v.name;
    if (!Array.isArray(this.draft[name])) this.draft[name] = [];
    var rows = this.draft[name];
    var single = v.columns.length === 1;
    var wrap = h("div");
    if (this.bulk && this.bulk[name]) {
      var col = v.columns[0].name;
      var ta = h("textarea", { class: "code", rows: String(Math.min(20, Math.max(6, rows.length + 2))), spellcheck: "false" });
      ta.value = rows.map(function (r) { return r[col] || ""; }).join("\n");
      ta.addEventListener("input", function () {
        var list = ta.value.split("\n").map(function (s) { return s.trim(); }).filter(Boolean);
        var next = list.map(function (s) { var o = {}; o[col] = s; return o; });
        self.set(name, next);
      });
      append(wrap, [h("p", { class: "f-desc", style: "margin:0 0 8px", text: "One " + v.columns[0].display.toLowerCase() + " per line." }), ta,
        h("div", { class: "vt-foot" }, h("button", { class: "btn btn-sm", type: "button", onclick: function () { self.bulk[name] = false; self.refreshField(name); } }, icon("check"), "Done"))]);
      return wrap;
    }
    var thead = h("thead", {}, h("tr", {}, h("th", { text: "#" }), v.columns.map(function (c) {
      return h("th", { title: c.description || "" }, c.display);
    }), h("th")));
    var tbody = h("tbody");
    rows.forEach(function (row, i) {
      var tr = h("tr", { draggable: "true" });
      tr.appendChild(h("td", { class: "idx" }, h("span", { class: "grip", text: String(i + 1), title: "Drag to reorder" })));
      v.columns.forEach(function (c) {
        var cell = h("td");
        var cv = row[c.name];
        var upd = function (x) { row[c.name] = x; self.changed(name); };
        if (c.type === "role") cell.appendChild(rolePicker(cv, upd));
        else if (c.type === "channel") cell.appendChild(channelPicker(cv, upd));
        else if (c.type === "int") cell.appendChild(h("input", { type: "number", value: cv === null ? "" : cv, oninput: function (e) { upd(e.target.value.trim()); } }));
        else cell.appendChild(h("input", { type: "text", value: cv === null ? "" : cv, spellcheck: "false", oninput: function (e) { upd(e.target.value); } }));
        tr.appendChild(cell);
      });
      tr.appendChild(h("td", { class: "act" }, h("button", { class: "icon-btn danger", type: "button", "aria-label": "Remove row",
        onclick: function () { rows.splice(i, 1); self.refreshField(name); } }, icon("x"))));
      tr.addEventListener("dragstart", function (e) { e.dataTransfer.setData("text/plain", String(i)); e.dataTransfer.effectAllowed = "move"; });
      tr.addEventListener("dragover", function (e) { e.preventDefault(); tr.classList.add("drag-over"); });
      tr.addEventListener("dragleave", function () { tr.classList.remove("drag-over"); });
      tr.addEventListener("drop", function (e) {
        e.preventDefault();
        var from = parseInt(e.dataTransfer.getData("text/plain"), 10);
        if (isNaN(from) || from === i) { tr.classList.remove("drag-over"); return; }
        var moved = rows.splice(from, 1)[0];
        rows.splice(i, 0, moved);
        self.refreshField(name);
      });
      tbody.appendChild(tr);
    });
    if (!rows.length) tbody.appendChild(h("tr", {}, h("td", { colspan: String(v.columns.length + 2) }, h("div", { class: "vt-empty", text: "Empty" }))));
    var foot = h("div", { class: "vt-foot" },
      h("button", { class: "btn btn-sm", type: "button", onclick: function () {
        var blank = {};
        v.columns.forEach(function (c) { blank[c.name] = v.blank && v.blank[c.name] !== undefined ? clone(v.blank[c.name]) : null; });
        if (single) blank[v.columns[0].name] = "";
        rows.push(blank);
        self.refreshField(name);
        var inputs = self.el.querySelectorAll('.field[data-name="' + name + '"] tbody tr:last-child input');
        if (inputs[0]) inputs[0].focus();
      } }, icon("plus"), "Add row"),
      single ? h("button", { class: "btn btn-sm btn-ghost", type: "button", onclick: function () { self.bulk = self.bulk || {}; self.bulk[name] = true; self.refreshField(name); } }, icon("edit"), "Bulk edit") : null,
      rows.length ? h("span", { class: "faint mono", style: "font-size:11.5px;margin-left:auto", text: rows.length + " row" + (rows.length === 1 ? "" : "s") }) : null);
    append(wrap, [h("table", { class: "vtable" }, thead, tbody), foot]);
    return wrap;
  };

  // ------------------------------------------------------------------ go
  dom.app = document.getElementById("app");
  boot();
})();
