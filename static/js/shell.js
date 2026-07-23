/**
 * Shared top navigation for literature reader shell.
 * Usage: ShellNav.mount({ active: 'library'|'reader'|'capture'|'review'|'settings' })
 */
(function (global) {
  const LINKS = [
    { id: "library", href: "/", label: "文库" },
    { id: "reader", href: "/read", label: "阅读" },
    { id: "capture", href: "/capture", label: "截取" },
    { id: "review", href: "/review", label: "校对" },
    { id: "settings", href: "/settings", label: "设置" },
  ];

  function ensureStylesheet(href) {
    if (document.querySelector(`link[data-shell-href="${href}"]`)) return;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = href;
    link.dataset.shellHref = href;
    document.head.appendChild(link);
  }

  function ensureScript(src) {
    return new Promise((resolve, reject) => {
      if (document.querySelector(`script[data-shell-src="${src}"]`)) {
        resolve();
        return;
      }
      const s = document.createElement("script");
      s.src = src;
      s.dataset.shellSrc = src;
      s.onload = () => resolve();
      s.onerror = () => reject(new Error("load failed: " + src));
      document.body.appendChild(s);
    });
  }

  async function mountChat() {
    try {
      ensureStylesheet("/static/css/chat.css");
      if (!window.ChatFloat) {
        await ensureScript("/static/js/chat_float.js");
      }
      if (window.ChatFloat) await ChatFloat.mount();
    } catch (_) {
      /* chat optional */
    }
  }

  function mount(opts) {
    opts = opts || {};
    const active = opts.active || "";
    if (!document.getElementById("app-shell-nav")) {
      document.body.classList.add("has-shell");

      const nav = document.createElement("nav");
      nav.id = "app-shell-nav";
      nav.className = "app-shell-nav";
      nav.setAttribute("aria-label", "主导航");

      const brand = document.createElement("a");
      brand.className = "shell-brand";
      brand.href = "/";
      brand.textContent = "Literature";
      nav.appendChild(brand);

      const links = document.createElement("div");
      links.className = "shell-links";
      for (const L of LINKS) {
        const a = document.createElement("a");
        a.className = "shell-link" + (L.id === active ? " active" : "");
        a.href = L.href;
        a.textContent = L.label;
        a.dataset.nav = L.id;
        links.appendChild(a);
      }
      nav.appendChild(links);

      const spacer = document.createElement("div");
      spacer.className = "shell-spacer";
      nav.appendChild(spacer);

      const meta = document.createElement("span");
      meta.className = "shell-meta";
      meta.id = "shell-meta";
      meta.textContent = "";
      nav.appendChild(meta);

      document.body.insertBefore(nav, document.body.firstChild);
    }

    // Floating chat on every shell page
    mountChat();
  }

  function setMeta(text) {
    const el = document.getElementById("shell-meta");
    if (el) el.textContent = text || "";
  }

  global.ShellNav = { mount, setMeta, LINKS };
})(window);
