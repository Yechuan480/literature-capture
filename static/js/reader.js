/**
 * Standalone PDF reader (library shell) + bilingual region/full translate.
 */
(function () {
  const PDFJS_CDN = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.8.69/pdf.min.mjs";
  const WORKER_CDN =
    "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.8.69/pdf.worker.min.mjs";

  const state = {
    filename: null,
    item: null,
    compareMode: false,
    originalFilename: null,
    translatedName: null,
    translateMode: false,
    fullJobPoll: null,
    provider: "ai",
    providers: [],
  };

  /** Lightweight secondary PDF.js instance for 译稿 pane */
  const zhViewer = {
    pdfjsLib: null,
    pdfDoc: null,
    pageNum: 1,
    scale: 1.1,
    rotation: 0,
    rendering: false,
    pending: null,
    async ensureLib() {
      if (this.pdfjsLib) return this.pdfjsLib;
      this.pdfjsLib = await import(PDFJS_CDN);
      this.pdfjsLib.GlobalWorkerOptions.workerSrc = WORKER_CDN;
      return this.pdfjsLib;
    },
    canvas() {
      return document.getElementById("pdf-canvas-zh");
    },
    async load(url) {
      const lib = await this.ensureLib();
      this.pdfDoc = await lib.getDocument({ url, withCredentials: false }).promise;
      this.pageNum = 1;
      this.rotation = 0;
      await this.render();
    },
    async render() {
      if (!this.pdfDoc) return;
      if (this.rendering) {
        this.pending = this.pageNum;
        return;
      }
      this.rendering = true;
      try {
        const page = await this.pdfDoc.getPage(this.pageNum);
        const canvas = this.canvas();
        if (!canvas) return;
        const ctx = canvas.getContext("2d", { alpha: false });
        const viewport = page.getViewport({
          scale: this.scale,
          rotation: this.rotation,
        });
        const dpr = window.devicePixelRatio || 1;
        canvas.width = Math.floor(viewport.width * dpr);
        canvas.height = Math.floor(viewport.height * dpr);
        canvas.style.width = `${Math.floor(viewport.width)}px`;
        canvas.style.height = `${Math.floor(viewport.height)}px`;
        const transform = dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : null;
        await page.render({ canvasContext: ctx, viewport, transform }).promise;
      } finally {
        this.rendering = false;
        if (this.pending != null) {
          const p = this.pending;
          this.pending = null;
          this.pageNum = p;
          await this.render();
        }
      }
    },
    async goTo(n) {
      if (!this.pdfDoc) return;
      this.pageNum = Math.min(Math.max(1, n | 0), this.pdfDoc.numPages);
      await this.render();
    },
    async setScale(s) {
      this.scale = Math.min(3, Math.max(0.5, Number(s) || 1));
      if (this.pdfDoc) await this.render();
    },
    async setRotation(deg) {
      const d = (((Number(deg) || 0) % 360) + 360) % 360;
      this.rotation = (Math.round(d / 90) * 90) % 360;
      if (this.pdfDoc) await this.render();
    },
    clear() {
      this.pdfDoc = null;
      this.pageNum = 1;
      const canvas = this.canvas();
      if (canvas) {
        const ctx = canvas.getContext("2d");
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        canvas.width = 0;
        canvas.height = 0;
      }
    },
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

  function showZhLoading(on, text) {
    const mask = $("loading-mask-zh");
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

  function providerLabel(id) {
    const p = (state.providers || []).find((x) => x.id === id);
    if (p && p.label) return p.label;
    const map = {
      ai: "AI 翻译",
      google: "Google 翻译",
      baidu: "百度翻译",
      cnki: "CNKI 翻译",
    };
    return map[id] || id || "—";
  }

  function currentProvider() {
    const sel = $("tr-provider");
    const v = (sel && sel.value) || state.provider || "ai";
    return String(v).toLowerCase();
  }

  function showTrPanel({ text, translation, source, model, error, provider }) {
    const panel = $("tr-panel");
    if (!panel) return;
    panel.hidden = false;
    $("tr-body").textContent = error
      ? `失败：${error}`
      : translation || "（空译文）";
    const srcEl = $("tr-src");
    srcEl.textContent = text || (error ? "—" : "（无可提取原文，已走视觉翻译）");
    const bits = [];
    if (provider) bits.push(providerLabel(provider));
    if (source)
      bits.push(
        source === "vision" ? "视觉" : source === "text" ? "文本" : source
      );
    if (model) bits.push(model);
    $("tr-meta").textContent = bits.join(" · ");
  }

  async function loadTranslateProviders() {
    try {
      const st = await api("/api/translate/settings");
      state.provider = st.provider || "ai";
      state.providers = st.providers || [];
      const sel = $("tr-provider");
      if (sel) {
        if (state.providers.length) {
          sel.innerHTML = state.providers
            .map(
              (p) =>
                `<option value="${p.id}">${p.label || p.id}</option>`
            )
            .join("");
        }
        sel.value = state.provider;
      }
    } catch (_) {
      /* optional */
    }
  }

  function hideTrPanel() {
    const panel = $("tr-panel");
    if (panel) panel.hidden = true;
  }

  async function setCompareMode(on, translatedName) {
    state.compareMode = !!on;
    document.body.classList.toggle("compare-on", state.compareMode);
    const paneZh = $("pane-zh");
    const openBtn = $("btn-tr-open");
    if (!state.compareMode) {
      if (paneZh) paneZh.hidden = true;
      zhViewer.clear();
      if (openBtn) {
        openBtn.textContent = "对照译稿";
        openBtn.dataset.mode = "zh";
      }
      return;
    }
    if (paneZh) paneZh.hidden = false;
    if (openBtn) {
      openBtn.hidden = false;
      openBtn.textContent = "退出对照";
      openBtn.dataset.mode = "exit";
    }
    const name =
      translatedName ||
      state.translatedName ||
      (state.originalFilename || state.filename || "").replace(
        /\.pdf$/i,
        ""
      ) + ".zh-CN.pdf";
    state.translatedName = name;
    showZhLoading(true, "加载译稿…");
    try {
      // Match main viewer scale roughly (slightly smaller for dual pane)
      const mainScale = window.PdfViewer?.state?.scale || 1.25;
      zhViewer.scale = Math.max(0.6, mainScale * 0.85);
      zhViewer.rotation = window.PdfViewer?.state?.rotation || 0;
      await zhViewer.load(`/api/translate/file/${encodeURIComponent(name)}`);
      const page = window.PdfViewer?.state?.page || 1;
      await zhViewer.goTo(page);
      setStatus(
        `左右对照 · 原文 ${window.PdfViewer?.state?.numPages || 0} 页 / 译稿 ${zhViewer.pdfDoc?.numPages || 0} 页`
      );
    } catch (e) {
      state.compareMode = false;
      document.body.classList.remove("compare-on");
      if (paneZh) paneZh.hidden = true;
      setStatus(e.message || "译稿加载失败");
      throw e;
    } finally {
      showZhLoading(false);
    }
  }

  async function syncZhToMain() {
    if (!state.compareMode || !zhViewer.pdfDoc) return;
    const page = window.PdfViewer?.state?.page || 1;
    const scale = window.PdfViewer?.state?.scale || 1.25;
    const rot = window.PdfViewer?.state?.rotation || 0;
    zhViewer.scale = Math.max(0.6, scale * 0.85);
    zhViewer.rotation = rot;
    await zhViewer.goTo(page);
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
        btn.hidden = !st.exists && !state.compareMode;
        if (st.translated_name) {
          btn.dataset.name = st.translated_name;
          state.translatedName = st.translated_name;
        }
        if (!state.compareMode) {
          btn.textContent = "对照译稿";
          btn.dataset.mode = "zh";
        }
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
          setStatus(job.message || "全文翻译完成 · 可点「对照译稿」");
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
    if (!state.filename) {
      setStatus("请先打开文献");
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

    if (window.RegionSelect?.syncOverlayToCanvas) {
      RegionSelect.syncOverlayToCanvas();
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
      const provider = currentProvider();
      const body = {
        filename: state.originalFilename || state.filename,
        page: PdfViewer.state.page || 1,
        rect: sel,
        canvas: { w: cssW, h: cssH },
        image_b64,
        rotation: PdfViewer.state.rotation || 0,
        provider,
      };
      const res = await api("/api/translate/region", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      showTrPanel(res);
      setStatus(
        res.ok
          ? `区域对照完成 · ${providerLabel(res.provider || provider)}`
          : res.error || "翻译失败"
      );
    } catch (e) {
      showTrPanel({
        error: e.message,
        translation: "",
        text: "",
        provider: currentProvider(),
      });
      setStatus(e.message || "翻译失败");
    } finally {
      showLoading(false);
    }
  }

  async function startFullTranslate(force) {
    const base = state.originalFilename || state.filename;
    if (!base) return;
    const provider = currentProvider();
    showLoading(true, "提交全文翻译…");
    try {
      const job = await api("/api/translate/pdf", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          filename: base,
          force: !!force,
          provider,
        }),
      });
      if (job.id === "cached" || (job.status === "done" && job.result_name)) {
        setStatus(job.message || "已存在译稿 · 可点「对照译稿」");
        if (job.result_name) state.translatedName = job.result_name;
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

  async function enterCompare() {
    const base = state.originalFilename || state.filename;
    if (!base) return;
    const name =
      $("btn-tr-open")?.dataset.name ||
      state.translatedName ||
      base.replace(/\.pdf$/i, "") + ".zh-CN.pdf";
    setTranslateUi(false);
    hideTrPanel();
    try {
      showLoading(true, "进入对照…");
      await setCompareMode(true, name);
      $("reader-title").textContent =
        (state.item?.title || base) + " · 左右对照";
    } catch (e) {
      alert(e.message || "译稿加载失败");
    } finally {
      showLoading(false);
    }
  }

  async function exitCompare() {
    await setCompareMode(false);
    const base = state.originalFilename || state.filename;
    $("reader-title").textContent = state.item?.title || base || "—";
    setStatus("已退出对照");
    await refreshTranslateStatus();
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
    state.compareMode = false;
    state.translatedName = null;
    document.body.classList.remove("compare-on");
    const paneZh = $("pane-zh");
    if (paneZh) paneZh.hidden = true;
    zhViewer.clear();
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
      openBtn.textContent = "对照译稿";
      openBtn.dataset.mode = "zh";
      openBtn.hidden = true;
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
      await syncZhToMain();
    });
    $("btn-next").addEventListener("click", async () => {
      await PdfViewer.next();
      syncChrome();
      await syncZhToMain();
    });
    $("page-input").addEventListener("change", async () => {
      const n = parseInt($("page-input").value, 10);
      if (!Number.isFinite(n)) return;
      await PdfViewer.goTo(n);
      syncChrome();
      await syncZhToMain();
    });
    $("btn-zoom-in").addEventListener("click", async () => {
      await PdfViewer.zoomBy(0.1);
      syncChrome();
      await syncZhToMain();
    });
    $("btn-zoom-out").addEventListener("click", async () => {
      await PdfViewer.zoomBy(-0.1);
      syncChrome();
      await syncZhToMain();
    });
    $("btn-rotate-cw").addEventListener("click", async () => {
      await PdfViewer.rotateBy(90);
      syncChrome();
      await syncZhToMain();
    });
    $("btn-rotate-ccw").addEventListener("click", async () => {
      await PdfViewer.rotateBy(-90);
      syncChrome();
      await syncZhToMain();
    });
    $("btn-to-capture").addEventListener("click", () => {
      const fn = state.originalFilename || state.filename;
      if (!fn) return;
      const q = new URLSearchParams({ f: fn });
      window.location.href = `/capture?${q.toString()}`;
    });
    $("btn-mark-reading").addEventListener("click", () =>
      setStatusMark("reading")
    );
    $("btn-mark-done").addEventListener("click", () => setStatusMark("done"));

    $("btn-tr-region").addEventListener("click", () => {
      setTranslateUi(!state.translateMode);
      setStatus(
        state.translateMode
          ? `框选模式 · ${providerLabel(currentProvider())}：拖选后点「译选区」`
          : "已退出框选翻译"
      );
    });
    $("btn-tr-run").addEventListener("click", () => runRegionTranslate());
    $("btn-tr-cancel").addEventListener("click", () => {
      setTranslateUi(false);
      setStatus("已取消框选");
    });
    $("tr-provider")?.addEventListener("change", () => {
      state.provider = currentProvider();
      setStatus(`翻译引擎：${providerLabel(state.provider)}`);
    });
    $("btn-tr-full").addEventListener("click", () => {
      const force = !!(window.event && window.event.shiftKey);
      startFullTranslate(force);
    });
    $("btn-tr-open").addEventListener("click", () => {
      if ($("btn-tr-open").dataset.mode === "exit" || state.compareMode) {
        exitCompare();
      } else {
        enterCompare();
      }
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
      if (window.RegionSelect?.syncOverlayToCanvas) {
        RegionSelect.syncOverlayToCanvas();
      }
      if (state.translateMode && window.RegionSelect) {
        RegionSelect.setActive(true);
      }
      if (state.compareMode) syncZhToMain();
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
      } else if (e.key === "Escape") {
        if (state.translateMode) {
          setTranslateUi(false);
          hideTrPanel();
        } else if (state.compareMode) {
          exitCompare();
        } else {
          hideTrPanel();
        }
      }
    });
  }

  async function init() {
    if (window.ShellNav) ShellNav.mount({ active: "reader" });
    if (window.RegionSelect) RegionSelect.bind();
    bind();
    await loadTranslateProviders();
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
