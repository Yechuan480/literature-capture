/**
 * Standalone PDF reader (library shell) + region/full translate.
 */
(function () {
  const state = {
    filename: null,
    item: null,
    viewingTranslated: false,
    originalFilename: null,
    translateMode: false,
    fullJobPoll: null,
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

  function blobToB64(blob) {
    return new Promise((resolve, reject) => {
      const r = new FileReader();
      r.onload = () => {
        const s = String(r.result || "");
        const i = s.indexOf(",");
        resolve(i >= 0 ? s.slice(i + 1) : s);
      };
      r.onerror = () => reject(new Error("读取图片失败"));
      r.readAsDataURL(blob);
    });
  }

  function syncChrome() {
    const st = window.PdfViewer?.state;
    if (!st) return;
    $("page-input").value = String(st.page || 1);
    $("page-total").textContent = `/ ${st.numPages || 0}`;
    $("zoom-label").textContent = `${Math.round((st.scale || 1) * 100)}%`;
    $("rotation-label").textContent = `${st.rotation || 0}°`;
  }

  function setTranslateUi(on) {
    state.translateMode = !!on;
    $("btn-tr-region")?.classList.toggle("active", state.translateMode);
    $("btn-tr-run").hidden = !state.translateMode;
    $("btn-tr-cancel").hidden = !state.translateMode;
    if (window.RegionSelect) {
      RegionSelect.setActive(state.translateMode);
      if (!state.translateMode) RegionSelect.cancel();
    }
  }

  function showTrPanel({ text, translation, source, model, error }) {
    const panel = $("tr-panel");
    if (!panel) return;
    panel.hidden = false;
    $("tr-body").textContent = error
      ? `失败：${error}`
      : translation || "（空译文）";
    const srcEl = $("tr-src");
    if (text) {
      srcEl.hidden = false;
      srcEl.textContent = text;
    } else {
      srcEl.hidden = true;
      srcEl.textContent = "";
    }
    const bits = [];
    if (source) bits.push(source === "vision" ? "视觉" : source === "text" ? "文本" : source);
    if (model) bits.push(model);
    $("tr-meta").textContent = bits.join(" · ");
  }

  function hideTrPanel() {
    const panel = $("tr-panel");
    if (panel) panel.hidden = true;
  }

  async function refreshTranslateStatus() {
    const base = state.originalFilename || state.filename;
    if (!base) return;
    try {
      const st = await api(
        `/api/translate/status?filename=${encodeURIComponent(base)}`
      );
      const btn = $("btn-tr-open");
      if (btn) {
        btn.hidden = !st.exists;
        btn.dataset.name = st.translated_name || "";
      }
      if (st.job && (st.job.status === "queued" || st.job.status === "running")) {
        setStatus(st.job.message || st.job.progress || "翻译中…");
        scheduleFullPoll(st.job.id);
      }
    } catch (_) {
      /* optional */
    }
  }

  function stopFullPoll() {
    if (state.fullJobPoll) {
      clearTimeout(state.fullJobPoll);
      state.fullJobPoll = null;
    }
  }

  function scheduleFullPoll(jobId) {
    stopFullPoll();
    if (!jobId || jobId === "cached") return;
    const tick = async () => {
      try {
        const job = await api(`/api/translate/jobs/${encodeURIComponent(jobId)}`);
        if (job.status === "done") {
          setStatus(job.message || "全文翻译完成");
          stopFullPoll();
          await refreshTranslateStatus();
          return;
        }
        if (job.status === "error") {
          setStatus(job.error || "全文翻译失败");
          stopFullPoll();
          return;
        }
        setStatus(job.message || job.progress || "翻译中…");
        state.fullJobPoll = setTimeout(tick, 1500);
      } catch (e) {
        setStatus(e.message || "轮询失败");
        stopFullPoll();
      }
    };
    state.fullJobPoll = setTimeout(tick, 800);
  }

  async function runRegionTranslate() {
    if (!state.filename || state.viewingTranslated) {
      setStatus("请在原文上框选翻译");
      return;
    }
    if (!window.RegionSelect) {
      setStatus("框选组件未加载");
      return;
    }
    const sel = RegionSelect.getSelectionCss();
    if (!sel) {
      setStatus("请先拖拽选择区域");
      return;
    }
    const canvas = PdfViewer.getCanvas();
    const cssW = canvas?.clientWidth || parseFloat(canvas?.style.width) || 0;
    const cssH = canvas?.clientHeight || parseFloat(canvas?.style.height) || 0;
    if (!cssW || !cssH) {
      setStatus("页面尚未渲染");
      return;
    }

    showLoading(true, "翻译选区…");
    setStatus("翻译选区…");
    try {
      let image_b64 = null;
      try {
        const blob = await RegionSelect.cropToPngBlob();
        image_b64 = await blobToB64(blob);
      } catch (_) {
        /* vision optional */
      }
      const body = {
        filename: state.originalFilename || state.filename,
        page: PdfViewer.state.page || 1,
        rect: sel,
        canvas: { w: cssW, h: cssH },
        image_b64,
      };
      const res = await api("/api/translate/region", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      showTrPanel(res);
      setStatus(res.ok ? "区域翻译完成" : res.error || "翻译失败");
    } catch (e) {
      showTrPanel({ error: e.message, translation: "", text: "" });
      setStatus(e.message || "翻译失败");
    } finally {
      showLoading(false);
    }
  }

  async function startFullTranslate(force) {
    const base = state.originalFilename || state.filename;
    if (!base) return;
    if (state.viewingTranslated) {
      setStatus("请先回到原文再全文翻译");
      return;
    }
    showLoading(true, "提交全文翻译…");
    try {
      const job = await api("/api/translate/pdf", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename: base, force: !!force }),
      });
      if (job.id === "cached" || (job.status === "done" && job.result_name)) {
        setStatus(job.message || "已存在译稿");
        await refreshTranslateStatus();
        showLoading(false);
        return;
      }
      setStatus(job.message || "已排队全文翻译…");
      scheduleFullPoll(job.id);
    } catch (e) {
      setStatus(e.message || "提交失败");
    } finally {
      showLoading(false);
    }
  }

  async function openTranslated() {
    const base = state.originalFilename || state.filename;
    if (!base) return;
    const name =
      $("btn-tr-open")?.dataset.name ||
      base.replace(/\.pdf$/i, "") + ".zh-CN.pdf";
    state.viewingTranslated = true;
    state.originalFilename = base;
    setTranslateUi(false);
    hideTrPanel();
    $("reader-title").textContent = `${name}（译稿）`;
    try {
      showLoading(true, "加载译稿…");
      await PdfViewer.load(
        `/api/translate/file/${encodeURIComponent(name)}`,
        name
      );
      syncChrome();
      setStatus(`译稿 · ${PdfViewer.state.numPages || 0} 页 · 点「打开原文」返回`);
      const openBtn = $("btn-tr-open");
      if (openBtn) {
        openBtn.hidden = false;
        openBtn.textContent = "打开原文";
        openBtn.dataset.mode = "orig";
      }
    } catch (e) {
      state.viewingTranslated = false;
      setStatus(e.message || "译稿加载失败");
      alert(e.message || "译稿加载失败");
    } finally {
      showLoading(false);
    }
  }

  async function openOriginal() {
    const base = state.originalFilename || state.filename;
    if (!base) return;
    state.viewingTranslated = false;
    const openBtn = $("btn-tr-open");
    if (openBtn) {
      openBtn.textContent = "打开译稿";
      openBtn.dataset.mode = "zh";
    }
    await openFile(base, { skipMeta: false });
  }

  async function setStatusMark(status) {
    const fn = state.originalFilename || state.filename;
    if (!fn) return;
    try {
      state.item = await api(
        `/api/library/items/${encodeURIComponent(fn)}`,
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

  async function openFile(filename, opts) {
    opts = opts || {};
    state.filename = filename;
    state.originalFilename = filename;
    state.viewingTranslated = false;
    if (window.ChatFloat) ChatFloat.setPaperContext(filename);
    $("reader-empty").hidden = true;
    $("reader-toolbar").hidden = false;
    $("reader-stage-wrap").hidden = false;
    $("reader-title").textContent = filename;
    if (window.ShellNav) ShellNav.setMeta(filename);
    setTranslateUi(false);
    hideTrPanel();
    const openBtn = $("btn-tr-open");
    if (openBtn) {
      openBtn.textContent = "打开译稿";
      openBtn.dataset.mode = "zh";
    }

    try {
      showLoading(true, "加载 PDF…");
      await PdfViewer.load(
        `/api/pdf/${encodeURIComponent(filename)}`,
        filename
      );
      syncChrome();
      setStatus(`已打开 · ${PdfViewer.state.numPages || 0} 页`);

      if (!opts.skipMeta) {
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
      }
      await refreshTranslateStatus();
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
      const fn = state.originalFilename || state.filename;
      if (!fn) return;
      const q = new URLSearchParams({ f: fn });
      window.location.href = `/capture?${q.toString()}`;
    });
    $("btn-mark-reading").addEventListener("click", () => setStatusMark("reading"));
    $("btn-mark-done").addEventListener("click", () => setStatusMark("done"));

    $("btn-tr-region").addEventListener("click", () => {
      if (state.viewingTranslated) {
        setStatus("请在原文上使用框选翻译");
        return;
      }
      setTranslateUi(!state.translateMode);
      setStatus(
        state.translateMode
          ? "框选模式：拖拽选区后点「译选区」"
          : "已退出框选翻译"
      );
    });
    $("btn-tr-run").addEventListener("click", () => runRegionTranslate());
    $("btn-tr-cancel").addEventListener("click", () => {
      setTranslateUi(false);
      setStatus("已取消框选");
    });
    $("btn-tr-full").addEventListener("click", () => {
      const force = !!(window.event && window.event.shiftKey);
      startFullTranslate(force);
    });
    $("btn-tr-open").addEventListener("click", () => {
      if ($("btn-tr-open").dataset.mode === "orig") openOriginal();
      else openTranslated();
    });
    $("btn-tr-copy").addEventListener("click", async () => {
      const t = $("tr-body")?.textContent || "";
      try {
        await navigator.clipboard.writeText(t);
        setStatus("已复制译文");
      } catch (_) {
        setStatus("复制失败");
      }
    });
    $("btn-tr-close").addEventListener("click", hideTrPanel);

    document.addEventListener("pdf:rendered", () => {
      syncChrome();
      if (state.translateMode && window.RegionSelect) {
        RegionSelect.setActive(true);
      }
    });

    document.addEventListener("region:selected", () => {
      if (state.translateMode) setStatus("选区就绪 · 点「译选区」");
    });

    document.addEventListener("keydown", (e) => {
      if (e.target && ["INPUT", "TEXTAREA", "SELECT"].includes(e.target.tagName))
        return;
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        $("btn-prev").click();
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        $("btn-next").click();
      } else if (e.key === "Escape" && state.translateMode) {
        setTranslateUi(false);
        hideTrPanel();
      }
    });
  }

  async function init() {
    if (window.ShellNav) ShellNav.mount({ active: "reader" });
    if (window.RegionSelect) RegionSelect.bind();
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
