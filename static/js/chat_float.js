/**
 * Floating chat assistant (OpenAI-compatible via /api/chat).
 * Claude-style avatar ball; drag to reposition (localStorage).
 * ShellNav.mount will call ChatFloat.mount automatically when present.
 */
(function (global) {
  const POS_KEY = "literature.chat.ballPos";

  const state = {
    open: false,
    ready: false,
    busy: false,
    messages: [], // {role, content}
    paperFilename: null,
    scope: "global",
    dragging: false,
    dragMoved: false,
  };

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }

  async function api(path, options) {
    const res = await fetch(path, options);
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const j = await res.json();
        detail = j.detail || JSON.stringify(j);
      } catch (_) {}
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    const ct = res.headers.get("content-type") || "";
    if (ct.includes("application/json")) return res.json();
    return res;
  }

  function loadPos() {
    try {
      const raw = localStorage.getItem(POS_KEY);
      if (!raw) return null;
      const p = JSON.parse(raw);
      if (typeof p.left === "number" && typeof p.top === "number") return p;
    } catch (_) {}
    return null;
  }

  function savePos(left, top) {
    try {
      localStorage.setItem(POS_KEY, JSON.stringify({ left, top }));
    } catch (_) {}
  }

  function clampPos(left, top, size) {
    const pad = 8;
    const maxL = Math.max(pad, window.innerWidth - size - pad);
    const maxT = Math.max(pad, window.innerHeight - size - pad);
    return {
      left: Math.min(Math.max(pad, left), maxL),
      top: Math.min(Math.max(pad, top), maxT),
    };
  }

  function applyBallPos(ball, left, top) {
    const size = ball.offsetWidth || 50;
    const p = clampPos(left, top, size);
    ball.style.left = p.left + "px";
    ball.style.top = p.top + "px";
    ball.style.right = "auto";
    ball.style.bottom = "auto";
    positionPanel(ball);
    return p;
  }

  function positionPanel(ball) {
    const panel = $("#chat-panel");
    if (!panel || panel.hidden) return;
    const br = ball.getBoundingClientRect();
    const pw = panel.offsetWidth || 352;
    const ph = panel.offsetHeight || 420;
    const gap = 10;
    let left = br.left + br.width / 2 - pw / 2;
    let top = br.top - ph - gap;
    // Prefer above; if no room, place below
    if (top < 8) top = br.bottom + gap;
    // Clamp horizontal
    left = Math.min(Math.max(8, left), window.innerWidth - pw - 8);
    // Clamp vertical
    top = Math.min(Math.max(8, top), window.innerHeight - ph - 8);
    panel.style.left = left + "px";
    panel.style.top = top + "px";
    panel.style.right = "auto";
    panel.style.bottom = "auto";
  }

  function bindDrag(ball) {
    let startX = 0;
    let startY = 0;
    let origL = 0;
    let origT = 0;
    let pointerId = null;

    const onMove = (e) => {
      if (!state.dragging || e.pointerId !== pointerId) return;
      const dx = e.clientX - startX;
      const dy = e.clientY - startY;
      if (Math.abs(dx) + Math.abs(dy) > 4) state.dragMoved = true;
      applyBallPos(ball, origL + dx, origT + dy);
      e.preventDefault();
    };

    const onUp = (e) => {
      if (e.pointerId !== pointerId) return;
      state.dragging = false;
      ball.classList.remove("dragging");
      try {
        ball.releasePointerCapture(pointerId);
      } catch (_) {}
      pointerId = null;
      const r = ball.getBoundingClientRect();
      const p = applyBallPos(ball, r.left, r.top);
      savePos(p.left, p.top);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
    };

    ball.addEventListener("pointerdown", (e) => {
      if (e.button != null && e.button !== 0) return;
      state.dragging = true;
      state.dragMoved = false;
      pointerId = e.pointerId;
      ball.classList.add("dragging");
      const r = ball.getBoundingClientRect();
      // Convert from right/bottom defaults if needed
      if (!ball.style.left) {
        ball.style.left = r.left + "px";
        ball.style.top = r.top + "px";
        ball.style.right = "auto";
        ball.style.bottom = "auto";
      }
      startX = e.clientX;
      startY = e.clientY;
      origL = parseFloat(ball.style.left) || r.left;
      origT = parseFloat(ball.style.top) || r.top;
      try {
        ball.setPointerCapture(pointerId);
      } catch (_) {}
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
      window.addEventListener("pointercancel", onUp);
      e.preventDefault();
    });

    ball.addEventListener("click", (e) => {
      if (state.dragMoved) {
        e.preventDefault();
        e.stopPropagation();
        state.dragMoved = false;
        return;
      }
      toggle();
    });

    window.addEventListener("resize", () => {
      const r = ball.getBoundingClientRect();
      const p = applyBallPos(ball, r.left, r.top);
      savePos(p.left, p.top);
    });
  }

  function ensureDom() {
    if ($("#chat-float-ball")) return;
    const ball = document.createElement("button");
    ball.type = "button";
    ball.id = "chat-float-ball";
    ball.className = "chat-float-ball offline";
    ball.title = "AI 助手（拖动可移动）";
    ball.setAttribute("aria-label", "AI 助手");
    ball.innerHTML = `<img class="chat-ball-avatar" src="/static/img/claude-avatar.svg" alt="" draggable="false" /><span class="chat-ball-fallback">AI</span>`;

    const panel = document.createElement("div");
    panel.id = "chat-panel";
    panel.className = "chat-panel";
    panel.hidden = true;
    panel.innerHTML = `
      <div class="chat-panel-head">
        <div class="chat-head-brand">
          <img class="chat-head-avatar" src="/static/img/claude-avatar.svg" alt="" draggable="false" />
          <h3>研究助手</h3>
        </div>
        <div class="chat-actions">
          <button type="button" id="chat-clear" title="清空本会话">清空</button>
          <button type="button" id="chat-close" title="关闭">×</button>
        </div>
      </div>
      <div class="chat-msgs" id="chat-msgs"></div>
      <div class="chat-input-row">
        <textarea id="chat-input" rows="2" placeholder="问文献、术语、实验设计…（Enter 发送，Shift+Enter 换行）"></textarea>
        <button type="button" class="primary" id="chat-send">发送</button>
      </div>`;

    document.body.appendChild(panel);
    document.body.appendChild(ball);

    // Restore position or default bottom-right
    const saved = loadPos();
    if (saved) {
      requestAnimationFrame(() => applyBallPos(ball, saved.left, saved.top));
    }

    bindDrag(ball);

    $("#chat-close").addEventListener("click", () => setOpen(false));
    $("#chat-clear").addEventListener("click", () => clearChat());
    $("#chat-send").addEventListener("click", () => send());
    $("#chat-input").addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        send();
      }
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && state.open) {
        setOpen(false);
      }
    });
  }

  function renderMsgs() {
    const box = $("#chat-msgs");
    if (!box) return;
    box.innerHTML = "";
    if (!state.messages.length) {
      const el = document.createElement("div");
      el.className = "chat-msg system";
      el.textContent = state.ready
        ? "你好。可结合当前打开的文献提问。"
        : "AI 未就绪：请到「设置」填写 Base URL / Model / API Key 并启用。";
      box.appendChild(el);
      return;
    }
    for (const m of state.messages) {
      const el = document.createElement("div");
      el.className = "chat-msg " + (m.role === "user" ? "user" : "assistant");
      el.textContent = m.content;
      box.appendChild(el);
    }
    box.scrollTop = box.scrollHeight;
  }

  function setOpen(on) {
    state.open = !!on;
    const panel = $("#chat-panel");
    const ball = $("#chat-float-ball");
    if (panel) panel.hidden = !state.open;
    if (state.open) {
      renderMsgs();
      if (ball) positionPanel(ball);
      const input = $("#chat-input");
      if (input) input.focus();
    }
  }

  function toggle() {
    setOpen(!state.open);
  }

  async function refreshReady() {
    try {
      const st = await api("/api/chat/status");
      state.ready = !!st.ready;
    } catch (_) {
      state.ready = false;
    }
    const ball = $("#chat-float-ball");
    if (ball) {
      ball.classList.toggle("offline", !state.ready);
      ball.title = state.ready
        ? "AI 助手（拖动可移动）"
        : "AI 未配置 — 打开设置（拖动可移动）";
    }
  }

  async function loadHistory() {
    try {
      const data = await api(
        `/api/chat/history?scope=${encodeURIComponent(state.scope)}&limit=40`
      );
      const msgs = (data.messages || [])
        .filter((m) => m.role === "user" || m.role === "assistant")
        .map((m) => ({ role: m.role, content: m.content }));
      state.messages = msgs;
      renderMsgs();
    } catch (_) {
      /* ignore */
    }
  }

  async function clearChat() {
    try {
      await api(`/api/chat/history?scope=${encodeURIComponent(state.scope)}`, {
        method: "DELETE",
      });
    } catch (_) {}
    state.messages = [];
    renderMsgs();
  }

  async function send() {
    if (state.busy) return;
    const input = $("#chat-input");
    const text = (input?.value || "").trim();
    if (!text) return;
    if (!state.ready) {
      state.messages.push({
        role: "assistant",
        content: "AI 未就绪，请先在设置页配置并启用。",
      });
      renderMsgs();
      return;
    }
    input.value = "";
    state.messages.push({ role: "user", content: text });
    renderMsgs();
    state.busy = true;
    const sendBtn = $("#chat-send");
    if (sendBtn) sendBtn.disabled = true;
    try {
      const payload = {
        messages: state.messages.slice(-20),
        paper_filename: state.paperFilename || null,
        scope: state.scope,
        temperature: 0.4,
        persist: true,
      };
      const res = await api("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      state.messages.push({
        role: "assistant",
        content: res.reply || "（空回复）",
      });
    } catch (e) {
      state.messages.push({
        role: "assistant",
        content: "错误：" + (e.message || String(e)),
      });
    } finally {
      state.busy = false;
      if (sendBtn) sendBtn.disabled = false;
      renderMsgs();
    }
  }

  function setPaperContext(filename) {
    state.paperFilename = filename || null;
    state.scope = filename ? filename : "global";
  }

  async function mount(opts) {
    opts = opts || {};
    if (opts.paperFilename) setPaperContext(opts.paperFilename);
    // auto-detect from reader/capture URL
    if (!state.paperFilename) {
      try {
        const p = new URLSearchParams(window.location.search);
        const f = p.get("f") || p.get("filename");
        if (f) setPaperContext(f);
      } catch (_) {}
    }
    ensureDom();
    await refreshReady();
    await loadHistory();
  }

  global.ChatFloat = {
    mount,
    setPaperContext,
    toggle,
    refreshReady,
  };
})(window);
