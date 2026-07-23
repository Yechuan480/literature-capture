/**
 * Drag-to-select region over the PDF canvas and export PNG blob.
 * Also supports programmatic selection (pre-box) and corner resize.
 */
(function (global) {
  let active = false;
  let dragging = false;
  let resizing = false;
  let resizeHandle = null;
  let startX = 0;
  let startY = 0;
  let curX = 0;
  let curY = 0;
  let hasSelection = false;

  function overlay() {
    return document.getElementById("select-overlay");
  }

  function rectEl() {
    return document.getElementById("select-rect");
  }

  function stage() {
    return document.querySelector(".canvas-stage");
  }

  /** Size overlay to the PDF canvas CSS box so selection == crop coords. */
  function syncOverlayToCanvas() {
    const ov = overlay();
    const canvas =
      (global.PdfViewer && global.PdfViewer.getCanvas && global.PdfViewer.getCanvas()) ||
      document.getElementById("pdf-canvas");
    if (!ov || !canvas) return;
    const cssW =
      canvas.clientWidth ||
      parseFloat(canvas.style.width) ||
      0;
    const cssH =
      canvas.clientHeight ||
      parseFloat(canvas.style.height) ||
      0;
    if (cssW > 0 && cssH > 0) {
      ov.style.width = `${Math.floor(cssW)}px`;
      ov.style.height = `${Math.floor(cssH)}px`;
      ov.style.left = "0";
      ov.style.top = "0";
      ov.style.right = "auto";
      ov.style.bottom = "auto";
    }
    const layer = document.getElementById("highlight-layer");
    if (layer && cssW > 0 && cssH > 0) {
      layer.style.width = `${Math.floor(cssW)}px`;
      layer.style.height = `${Math.floor(cssH)}px`;
    }
  }

  function setActive(on) {
    active = !!on;
    const ov = overlay();
    if (!ov) return;
    if (active) syncOverlayToCanvas();
    ov.classList.toggle("active", active);
    if (!active) {
      dragging = false;
      resizing = false;
      resizeHandle = null;
      // keep selection visible if pre-set; only hide when cancel()
    }
    document.dispatchEvent(new CustomEvent("region:mode", { detail: { active } }));
  }

  function isActive() {
    return active;
  }

  function hideRect() {
    const r = rectEl();
    if (r) {
      r.style.display = "none";
      r.classList.remove("has-handles");
    }
    hasSelection = false;
  }

  function updateRect() {
    const r = rectEl();
    if (!r) return;
    const x = Math.min(startX, curX);
    const y = Math.min(startY, curY);
    const w = Math.abs(curX - startX);
    const h = Math.abs(curY - startY);
    if (w < 2 || h < 2) {
      r.style.display = "none";
      hasSelection = false;
      return;
    }
    r.style.display = "block";
    r.style.left = `${x}px`;
    r.style.top = `${y}px`;
    r.style.width = `${w}px`;
    r.style.height = `${h}px`;
    hasSelection = true;
  }

  function getSelectionCss() {
    const x = Math.min(startX, curX);
    const y = Math.min(startY, curY);
    const w = Math.abs(curX - startX);
    const h = Math.abs(curY - startY);
    if (w < 4 || h < 4) return null;
    return { x, y, w, h };
  }

  /**
   * Programmatically set CSS selection (for pre-boxes).
   * Activates select mode so crop works without re-drag.
   */
  function setSelectionCss(sel) {
    if (!sel || sel.w < 4 || sel.h < 4) {
      hideRect();
      return false;
    }
    startX = sel.x;
    startY = sel.y;
    curX = sel.x + sel.w;
    curY = sel.y + sel.h;
    updateRect();
    const r = rectEl();
    if (r) r.classList.add("has-handles");
    setActive(true);
    const btn = document.getElementById("btn-select");
    if (btn) btn.classList.add("active");
    document.dispatchEvent(
      new CustomEvent("region:selected", { detail: getSelectionCss() })
    );
    return true;
  }

  /**
   * Crop current PDF canvas by CSS selection box → PNG Blob.
   */
  async function cropToPngBlob() {
    const sel = getSelectionCss();
    if (!sel) throw new Error("请拖拽选择一个区域");
    const canvas = global.PdfViewer.getCanvas();
    if (!canvas || !canvas.width || !canvas.height) {
      throw new Error("PDF 页面尚未渲染");
    }

    const cssW = canvas.clientWidth || parseFloat(canvas.style.width) || canvas.width;
    const cssH = canvas.clientHeight || parseFloat(canvas.style.height) || canvas.height;
    const scaleX = canvas.width / cssW;
    const scaleY = canvas.height / cssH;

    const sx = Math.max(0, Math.floor(sel.x * scaleX));
    const sy = Math.max(0, Math.floor(sel.y * scaleY));
    const sw = Math.min(canvas.width - sx, Math.floor(sel.w * scaleX));
    const sh = Math.min(canvas.height - sy, Math.floor(sel.h * scaleY));
    if (sw < 4 || sh < 4) throw new Error("选区过小");

    const off = document.createElement("canvas");
    off.width = sw;
    off.height = sh;
    const ctx = off.getContext("2d");
    ctx.drawImage(canvas, sx, sy, sw, sh, 0, 0, sw, sh);

    return new Promise((resolve, reject) => {
      off.toBlob(
        (blob) => {
          if (!blob) reject(new Error("生成 PNG 失败"));
          else resolve(blob);
        },
        "image/png",
        1
      );
    });
  }

  function hitHandle(e) {
    const sel = getSelectionCss();
    if (!sel) return null;
    const ov = overlay();
    if (!ov) return null;
    const bounds = ov.getBoundingClientRect();
    const x = e.clientX - bounds.left;
    const y = e.clientY - bounds.top;
    const pad = 10;
    const corners = {
      nw: { x: sel.x, y: sel.y },
      ne: { x: sel.x + sel.w, y: sel.y },
      sw: { x: sel.x, y: sel.y + sel.h },
      se: { x: sel.x + sel.w, y: sel.y + sel.h },
    };
    for (const [name, p] of Object.entries(corners)) {
      if (Math.abs(x - p.x) <= pad && Math.abs(y - p.y) <= pad) return name;
    }
    return null;
  }

  function onPointerDown(e) {
    if (!active) return;
    e.preventDefault();
    const ov = overlay();
    const bounds = ov.getBoundingClientRect();
    const hx = hitHandle(e);
    if (hx && hasSelection) {
      resizing = true;
      resizeHandle = hx;
      const sel = getSelectionCss();
      // anchor opposite corner
      if (hx === "nw") {
        startX = sel.x + sel.w;
        startY = sel.y + sel.h;
      } else if (hx === "ne") {
        startX = sel.x;
        startY = sel.y + sel.h;
      } else if (hx === "sw") {
        startX = sel.x + sel.w;
        startY = sel.y;
      } else {
        startX = sel.x;
        startY = sel.y;
      }
      curX = e.clientX - bounds.left;
      curY = e.clientY - bounds.top;
      ov.setPointerCapture?.(e.pointerId);
      updateRect();
      return;
    }
    startX = e.clientX - bounds.left;
    startY = e.clientY - bounds.top;
    curX = startX;
    curY = startY;
    dragging = true;
    resizing = false;
    resizeHandle = null;
    ov.setPointerCapture?.(e.pointerId);
    updateRect();
  }

  function onPointerMove(e) {
    if (!active) return;
    const ov = overlay();
    const bounds = ov.getBoundingClientRect();
    if (resizing || dragging) {
      curX = Math.min(Math.max(0, e.clientX - bounds.left), bounds.width);
      curY = Math.min(Math.max(0, e.clientY - bounds.top), bounds.height);
      updateRect();
      return;
    }
    // cursor feedback
    const hx = hitHandle(e);
    if (hx === "nw" || hx === "se") ov.style.cursor = "nwse-resize";
    else if (hx === "ne" || hx === "sw") ov.style.cursor = "nesw-resize";
    else ov.style.cursor = "crosshair";
  }

  function onPointerUp(e) {
    if (!active) return;
    if (!dragging && !resizing) return;
    dragging = false;
    resizing = false;
    resizeHandle = null;
    updateRect();
    const r = rectEl();
    if (r && hasSelection) r.classList.add("has-handles");
    document.dispatchEvent(
      new CustomEvent("region:selected", { detail: getSelectionCss() })
    );
  }

  function bind() {
    const ov = overlay();
    if (!ov || ov.dataset.bound) return;
    ov.dataset.bound = "1";
    ov.addEventListener("pointerdown", onPointerDown);
    ov.addEventListener("pointermove", onPointerMove);
    ov.addEventListener("pointerup", onPointerUp);
    ov.addEventListener("pointercancel", onPointerUp);
    document.addEventListener("pdf:rendered", () => {
      syncOverlayToCanvas();
    });
    window.addEventListener("resize", () => {
      if (active) syncOverlayToCanvas();
    });
  }

  function cancel() {
    dragging = false;
    resizing = false;
    resizeHandle = null;
    hideRect();
    startX = startY = curX = curY = 0;
  }

  global.RegionSelect = {
    bind,
    setActive,
    isActive,
    cropToPngBlob,
    cancel,
    getSelectionCss,
    setSelectionCss,
    syncOverlayToCanvas,
  };
})(window);
