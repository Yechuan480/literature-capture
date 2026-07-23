/**
 * PDF.js viewer: load document, render pages, zoom, rotate, text search + highlight.
 */
(function (global) {
  const PDFJS_CDN = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.8.69/pdf.min.mjs";
  const WORKER_CDN = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.8.69/pdf.worker.min.mjs";

  let pdfjsLib = null;
  let pdfDoc = null;
  let pageNum = 1;
  let scale = 1.25;
  /** Clockwise rotation applied at render time: 0 | 90 | 180 | 270 */
  let rotation = 0;
  let rendering = false;
  let pendingPage = null;
  /** @type {AbortController|null} */
  let scanAbort = null;
  /** Default: whole-word table / tables */
  let highlightPattern = /\btables?\b/gi;
  let highlightEnabled = true;

  const state = {
    filename: null,
    numPages: 0,
    get page() {
      return pageNum;
    },
    get scale() {
      return scale;
    },
    get rotation() {
      return rotation;
    },
    get ready() {
      return !!pdfDoc;
    },
  };

  async function ensurePdfJs() {
    if (pdfjsLib) return pdfjsLib;
    pdfjsLib = await import(PDFJS_CDN);
    pdfjsLib.GlobalWorkerOptions.workerSrc = WORKER_CDN;
    return pdfjsLib;
  }

  function getCanvas() {
    return document.getElementById("pdf-canvas");
  }

  function getHighlightLayer() {
    return document.getElementById("highlight-layer");
  }

  function clearHighlights() {
    const layer = getHighlightLayer();
    if (layer) layer.innerHTML = "";
  }

  function makeHighlightRe() {
    if (highlightPattern instanceof RegExp) {
      const flags = highlightPattern.flags.includes("g")
        ? highlightPattern.flags
        : highlightPattern.flags + "g";
      const withI = flags.includes("i") ? flags : flags + "i";
      return new RegExp(highlightPattern.source, withI);
    }
    const raw = String(highlightPattern || "tables?").trim() || "tables?";
    const body =
      /^[a-zA-Z]+s\?$/.test(raw) || /^[a-zA-Z]+$/.test(raw) ? `\\b${raw}\\b` : raw;
    return new RegExp(body, "gi");
  }

  /**
   * Place yellow boxes over matches on the current page.
   * Coordinates use CSS pixels relative to canvas-stage (same as canvas style size).
   */
  async function paintHighlights(page, viewport) {
    const layer = getHighlightLayer();
    if (!layer) return;
    layer.innerHTML = "";
    if (!highlightEnabled || !pdfjsLib) return;

    const tc = await page.getTextContent();
    const re = makeHighlightRe();
    const items = tc.items || [];
    const frag = document.createDocumentFragment();

    for (const item of items) {
      if (!item || typeof item.str !== "string" || !item.str) continue;
      const str = item.str;
      re.lastIndex = 0;
      let m;
      // Viewport transform applied to text matrix
      const tx = pdfjsLib.Util.transform(viewport.transform, item.transform);
      const scaleX = Math.hypot(tx[0], tx[1]) || 1;
      const fontH = Math.hypot(tx[2], tx[3]) || 10;
      const totalW = (typeof item.width === "number" ? item.width : 0) * scaleX;
      // Char-width estimate for substring offsets
      const charW = str.length > 0 ? totalW / str.length : 0;
      const angleDeg = (Math.atan2(tx[1], tx[0]) * 180) / Math.PI;

      while ((m = re.exec(str)) !== null) {
        if (!m[0]) {
          re.lastIndex += 1;
          continue;
        }
        const start = m.index;
        const len = m[0].length;
        const w = Math.max(charW * len, 4);
        const left = tx[4] + charW * start;
        // tx[5] is baseline; box sits roughly on glyph body
        const top = tx[5] - fontH * 0.85;
        const h = fontH * 1.05;

        const el = document.createElement("div");
        el.className = "hl-mark";
        el.title = m[0];
        el.style.left = `${left}px`;
        el.style.top = `${top}px`;
        el.style.width = `${w}px`;
        el.style.height = `${Math.max(h, 8)}px`;
        if (Math.abs(angleDeg) > 0.5) {
          el.style.transform = `rotate(${angleDeg}deg)`;
          el.style.transformOrigin = "0 100%";
        }
        frag.appendChild(el);

        // Avoid zero-width infinite loops
        if (m[0].length === 0) re.lastIndex += 1;
      }
    }

    // Cross-item matches: e.g. "Ta" + "ble" split by PDF text engine
    // Walk consecutive items with a sliding window of plain text.
    const joined = items
      .map((it) => (it && typeof it.str === "string" ? it.str : ""))
      .join(" ");
    re.lastIndex = 0;
    // If any match spans a space-joined boundary that wasn't in a single item,
    // try a second pass on pairs/triples of items.
    for (let i = 0; i < items.length - 1; i++) {
      const a = items[i];
      const b = items[i + 1];
      if (!a?.str || !b?.str) continue;
      // only check when neither alone already fully contains the word start
      const combo = a.str + b.str;
      re.lastIndex = 0;
      const m = re.exec(combo);
      if (!m) continue;
      // skip if match entirely in a or entirely in b
      if (m.index + m[0].length <= a.str.length) continue;
      if (m.index >= a.str.length) continue;

      const tx = pdfjsLib.Util.transform(viewport.transform, a.transform);
      const scaleX = Math.hypot(tx[0], tx[1]) || 1;
      const fontH = Math.hypot(tx[2], tx[3]) || 10;
      const aW =
        (typeof a.width === "number" ? a.width : a.str.length) * scaleX;
      const bTx = pdfjsLib.Util.transform(viewport.transform, b.transform);
      const bScaleX = Math.hypot(bTx[0], bTx[1]) || 1;
      const bW =
        (typeof b.width === "number" ? b.width : b.str.length) * bScaleX;
      const left = tx[4] + (aW * m.index) / Math.max(a.str.length, 1);
      // span remaining of a + part of b
      const inA = a.str.length - m.index;
      const inB = m[0].length - inA;
      const w =
        (aW * inA) / Math.max(a.str.length, 1) +
        (bW * Math.max(inB, 0)) / Math.max(b.str.length, 1);
      const top = tx[5] - fontH * 0.85;
      const el = document.createElement("div");
      el.className = "hl-mark hl-span";
      el.title = m[0];
      el.style.left = `${left}px`;
      el.style.top = `${top}px`;
      el.style.width = `${Math.max(w, 6)}px`;
      el.style.height = `${Math.max(fontH * 1.05, 8)}px`;
      frag.appendChild(el);
    }

    layer.appendChild(frag);
    // Keep layer sized to canvas CSS box
    const canvas = getCanvas();
    if (canvas) {
      layer.style.width = canvas.style.width || `${canvas.width}px`;
      layer.style.height = canvas.style.height || `${canvas.height}px`;
    }
    // silence unused
    void joined;
  }

  async function renderPage(num) {
    if (!pdfDoc) return;
    rendering = true;
    const page = await pdfDoc.getPage(num);
    const canvas = getCanvas();
    const ctx = canvas.getContext("2d", { alpha: false });
    // PDF.js viewport rotation is clockwise degrees
    const viewport = page.getViewport({ scale, rotation });
    const outputScale = window.devicePixelRatio || 1;

    canvas.width = Math.floor(viewport.width * outputScale);
    canvas.height = Math.floor(viewport.height * outputScale);
    canvas.style.width = `${Math.floor(viewport.width)}px`;
    canvas.style.height = `${Math.floor(viewport.height)}px`;

    const transform =
      outputScale !== 1 ? [outputScale, 0, 0, outputScale, 0, 0] : null;
    await page.render({
      canvasContext: ctx,
      viewport,
      transform,
    }).promise;

    try {
      await paintHighlights(page, viewport);
    } catch (_) {
      clearHighlights();
    }

    // Keep overlay / highlight layer exactly the CSS box of the canvas
    // so region selection coords match pdfplumber crop mapping.
    const cssW = canvas.style.width || `${Math.floor(viewport.width)}px`;
    const cssH = canvas.style.height || `${Math.floor(viewport.height)}px`;
    const layer = getHighlightLayer();
    if (layer) {
      layer.style.width = cssW;
      layer.style.height = cssH;
    }
    const ov = document.getElementById("select-overlay");
    if (ov) {
      ov.style.width = cssW;
      ov.style.height = cssH;
    }

    rendering = false;
    if (pendingPage !== null) {
      const p = pendingPage;
      pendingPage = null;
      await queueRender(p);
    }

    document.dispatchEvent(
      new CustomEvent("pdf:rendered", {
        detail: {
          page: pageNum,
          numPages: state.numPages,
          scale,
          rotation,
          canvasCss: {
            w: Math.floor(viewport.width),
            h: Math.floor(viewport.height),
          },
        },
      })
    );
  }

  async function queueRender(num) {
    if (rendering) {
      pendingPage = num;
      return;
    }
    await renderPage(num);
  }

  async function load(url, filename) {
    if (scanAbort) {
      scanAbort.abort();
      scanAbort = null;
    }
    clearHighlights();
    const lib = await ensurePdfJs();
    const loadingTask = lib.getDocument({
      url,
      withCredentials: false,
    });
    pdfDoc = await loadingTask.promise;
    state.filename = filename;
    state.numPages = pdfDoc.numPages;
    pageNum = 1;
    rotation = 0;
    await queueRender(pageNum);
    return state;
  }

  async function goTo(num) {
    if (!pdfDoc) return;
    const n = Math.min(Math.max(1, num | 0), pdfDoc.numPages);
    pageNum = n;
    await queueRender(pageNum);
  }

  async function next() {
    if (!pdfDoc || pageNum >= pdfDoc.numPages) return;
    pageNum += 1;
    await queueRender(pageNum);
  }

  async function prev() {
    if (!pdfDoc || pageNum <= 1) return;
    pageNum -= 1;
    await queueRender(pageNum);
  }

  async function setScale(s) {
    scale = Math.min(3, Math.max(0.5, Number(s) || 1));
    if (pdfDoc) await queueRender(pageNum);
  }

  async function zoomBy(delta) {
    await setScale(scale + delta);
  }

  async function setRotation(deg) {
    const d = (((Number(deg) || 0) % 360) + 360) % 360;
    // Snap to 90° steps
    rotation = (Math.round(d / 90) * 90) % 360;
    if (pdfDoc) await queueRender(pageNum);
  }

  async function rotateBy(deltaDeg) {
    await setRotation(rotation + (Number(deltaDeg) || 0));
  }

  /**
   * Scan all pages for a word/phrase. Returns [{page, count}, ...] in page order.
   * Default pattern matches "table" / "tables" as whole words (case-insensitive).
   */
  async function findPages(term, opts) {
    opts = opts || {};
    if (!pdfDoc) return [];

    if (scanAbort) scanAbort.abort();
    const ac = new AbortController();
    scanAbort = ac;
    if (opts.signal) {
      if (opts.signal.aborted) {
        ac.abort();
      } else {
        opts.signal.addEventListener("abort", () => ac.abort(), { once: true });
      }
    }

    let re;
    if (term instanceof RegExp) {
      re = term.flags.includes("i")
        ? term
        : new RegExp(term.source, term.flags + "i");
      if (!re.flags.includes("g")) re = new RegExp(re.source, re.flags + "g");
    } else {
      const raw = (term == null || term === "" ? "tables?" : String(term)).trim();
      const body =
        /^[a-zA-Z]+s\?$/.test(raw) || /^[a-zA-Z]+$/.test(raw)
          ? `\\b${raw}\\b`
          : raw;
      re = new RegExp(body, "gi");
    }

    const total = pdfDoc.numPages;
    const hits = [];
    try {
      for (let i = 1; i <= total; i++) {
        if (ac.signal.aborted) throw new DOMException("Aborted", "AbortError");
        const page = await pdfDoc.getPage(i);
        const tc = await page.getTextContent();
        const text = (tc.items || [])
          .map((it) => (it && typeof it.str === "string" ? it.str : ""))
          .join(" ");
        re.lastIndex = 0;
        let count = 0;
        let m;
        while ((m = re.exec(text)) !== null) {
          count += 1;
          if (m[0].length === 0) re.lastIndex += 1;
        }
        if (count > 0) hits.push({ page: i, count });
        if (opts.onProgress) opts.onProgress(i, total);
      }
    } catch (e) {
      if (e && (e.name === "AbortError" || ac.signal.aborted)) {
        return hits;
      }
      throw e;
    } finally {
      if (scanAbort === ac) scanAbort = null;
    }
    return hits;
  }

  function setHighlightEnabled(on) {
    highlightEnabled = !!on;
    if (!highlightEnabled) clearHighlights();
    else if (pdfDoc) queueRender(pageNum);
  }

  function clear() {
    if (scanAbort) {
      scanAbort.abort();
      scanAbort = null;
    }
    pdfDoc = null;
    state.filename = null;
    state.numPages = 0;
    pageNum = 1;
    rotation = 0;
    clearHighlights();
    const canvas = getCanvas();
    if (canvas) {
      const ctx = canvas.getContext("2d");
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      canvas.width = 0;
      canvas.height = 0;
    }
  }

  function getPageCssSize() {
    const canvas = getCanvas();
    if (!canvas) return { width: 0, height: 0 };
    return {
      width: canvas.clientWidth || parseFloat(canvas.style.width) || 0,
      height: canvas.clientHeight || parseFloat(canvas.style.height) || 0,
    };
  }

  global.PdfViewer = {
    state,
    load,
    goTo,
    next,
    prev,
    setScale,
    zoomBy,
    setRotation,
    rotateBy,
    findPages,
    setHighlightEnabled,
    clearHighlights,
    clear,
    getCanvas,
    getPageCssSize,
  };
})(window);
