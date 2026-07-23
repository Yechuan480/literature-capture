/**
 * Standalone PDF reader (library shell).
 */
(function () {
  const state = {
    filename: null,
    item: null,
  };

  const $ = (id) => document.getElementById(id);

  function setStatus(msg) {
    const el = $("status-text");
    if (el) el.textContent = msg || "";
  }

  function showLoading(on, text) {
    const mask = $("loading-mask");
    if (!mask) return;
    mask.classList.toggle("show", !!on);
    mask.textContent = text || "加载中…";
  }

  async function api(path, options) {
    const res = await fetch(path, options);
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const j = await res.json();
        detail = j.detail || JSON.stringify(j);
      } catch (_) {
        /* ignore */
      }
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    const ct = res.headers.get("content-type") || "";
    if (ct.includes("application/json")) return res.json();
    return res;
  }

  function syncChrome() {
    const st = window.PdfViewer?.state;
    if (!st) return;
    $("page-input").value = String(st.page || 1);
    $("page-total").textContent = `/ ${st.numPages || 0}`;
    $("zoom-label").textContent = `${Math.round((st.scale || 1) * 100)}%`;
    $("rotation-label").textContent = `${st.rotation || 0}°`;
  }

  async function setStatusMark(status) {
    if (!state.filename) return;
    try {
      state.item = await api(
        `/api/library/items/${encodeURIComponent(state.filename)}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status }),
        }
      );
      setStatus(`已标记为${status === "done" ? "已读" : "在读"}`);
    } catch (e) {
      setStatus(e.message);
    }
  }

  async function openFile(filename) {
    state.filename = filename;
    if (window.ChatFloat) ChatFloat.setPaperContext(filename);
    $("reader-empty").hidden = true;
    $("reader-toolbar").hidden = false;
    $("reader-stage-wrap").hidden = false;
    $("reader-title").textContent = filename;
    if (window.ShellNav) ShellNav.setMeta(filename);

    try {
      showLoading(true, "加载 PDF…");
      await PdfViewer.load(
        `/api/pdf/${encodeURIComponent(filename)}`,
        filename
      );
      syncChrome();
      setStatus(`已打开 · ${PdfViewer.state.numPages || 0} 页`);

      // mark reading + fetch meta
      try {
        state.item = await api(
          `/api/library/items/${encodeURIComponent(filename)}`
        );
        const title = state.item?.title || filename;
        $("reader-title").textContent = title;
        if (state.item?.status === "unread") {
          await setStatusMark("reading");
        }
      } catch (_) {
        /* overlay optional */
      }
    } catch (e) {
      setStatus(e.message || "加载失败");
      alert(e.message || "加载失败");
    } finally {
      showLoading(false);
    }
  }

  function bind() {
    $("btn-prev").addEventListener("click", async () => {
      await PdfViewer.prev();
      syncChrome();
    });
    $("btn-next").addEventListener("click", async () => {
      await PdfViewer.next();
      syncChrome();
    });
    $("page-input").addEventListener("change", async () => {
      const n = parseInt($("page-input").value, 10);
      if (!Number.isFinite(n)) return;
      await PdfViewer.goTo(n);
      syncChrome();
    });
    $("btn-zoom-in").addEventListener("click", async () => {
      await PdfViewer.zoomBy(0.1);
      syncChrome();
    });
    $("btn-zoom-out").addEventListener("click", async () => {
      await PdfViewer.zoomBy(-0.1);
      syncChrome();
    });
    $("btn-rotate-cw").addEventListener("click", async () => {
      await PdfViewer.rotateBy(90);
      syncChrome();
    });
    $("btn-rotate-ccw").addEventListener("click", async () => {
      await PdfViewer.rotateBy(-90);
      syncChrome();
    });
    $("btn-to-capture").addEventListener("click", () => {
      if (!state.filename) return;
      const q = new URLSearchParams({ f: state.filename });
      window.location.href = `/capture?${q.toString()}`;
    });
    $("btn-mark-reading").addEventListener("click", () => setStatusMark("reading"));
    $("btn-mark-done").addEventListener("click", () => setStatusMark("done"));

    document.addEventListener("pdf:rendered", () => syncChrome());

    document.addEventListener("keydown", (e) => {
      if (e.target && ["INPUT", "TEXTAREA", "SELECT"].includes(e.target.tagName))
        return;
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        $("btn-prev").click();
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        $("btn-next").click();
      }
    });
  }

  async function init() {
    if (window.ShellNav) ShellNav.mount({ active: "reader" });
    bind();
    const params = new URLSearchParams(window.location.search);
    const f = params.get("f") || params.get("filename");
    if (f) {
      await openFile(f);
    } else {
      setStatus("未选择文献");
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    init().catch((e) => setStatus(e.message));
  });
})();
