/**
 * Floating chat assistant (OpenAI-compatible via /api/chat).
 * ShellNav.mount will call ChatFloat.mount automatically when present.
 */
(function (global) {
  const state = {
    open: false,
    ready: false,
    busy: false,
    messages: [], // {role, content}
    paperFilename: null,
    scope: "global",
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

  function ensureDom() {
    if ($("#chat-float-ball")) return;
    const ball = document.createElement("button");
    ball.type = "button";
    ball.id = "chat-float-ball";
    ball.className = "chat-float-ball offline";
    ball.title = "AI 助手";
    ball.textContent = "AI";
    ball.addEventListener("click", () => toggle());

    const panel = document.createElement("div");
    panel.id = "chat-panel";
    panel.className = "chat-panel";
    panel.hidden = true;
    panel.innerHTML = `
      <div class="chat-panel-head">
        <h3>研究助手</h3>
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
    if (panel) panel.hidden = !state.open;
    if (state.open) {
      renderMsgs();
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
      ball.title = state.ready ? "AI 助手" : "AI 未配置 — 打开设置";
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
