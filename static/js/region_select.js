/**
 * Drag-to-select region over the PDF canvas and export PNG blob.
 */
(function (global) {
  let active = false;
  let dragging = false;
  let startX = 0;
  let startY = 0;
  let curX = 0;
  let curY = 0;

  function overlay() {
    return document.getElementById("select-overlay");
  }

  function rectEl() {
    return document.getElementById("select-rect");
  }

  function stage() {
    return document.querySelector(".canvas-stage");
  }

  function setActive(on) {
    active = !!on;
    const ov = overlay();
    if (!ov) return;
    ov.classList.toggle("active", active);
    if (!active) {
      dragging = false;
      hideRect();
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
    }
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
      return;
    }
    r.style.display = "block";
    r.style.left = `${x}px`;
    r.style.top = `${y}px`;
    r.style.width = `${w}px`;
    r.style.height = `${h}px`;
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

  function onPointerDown(e) {
    if (!active) return;
    e.preventDefault();
    const ov = overlay();
    const bounds = ov.getBoundingClientRect();
    startX = e.clientX - bounds.left;
    startY = e.clientY - bounds.top;
    curX = startX;
    curY = startY;
    dragging = true;
    ov.setPointerCapture?.(e.pointerId);
    updateRect();
  }

  function onPointerMove(e) {
    if (!active || !dragging) return;
    const ov = overlay();
    const bounds = ov.getBoundingClientRect();
    curX = Math.min(Math.max(0, e.clientX - bounds.left), bounds.width);
    curY = Math.min(Math.max(0, e.clientY - bounds.top), bounds.height);
    updateRect();
  }

  function onPointerUp(e) {
    if (!active || !dragging) return;
    dragging = false;
    updateRect();
    document.dispatchEvent(new CustomEvent("region:selected", { detail: getSelectionCss() }));
  }

  function bind() {
    const ov = overlay();
    if (!ov || ov.dataset.bound) return;
    ov.dataset.bound = "1";
    ov.addEventListener("pointerdown", onPointerDown);
    ov.addEventListener("pointermove", onPointerMove);
    ov.addEventListener("pointerup", onPointerUp);
    ov.addEventListener("pointercancel", onPointerUp);
  }

  function cancel() {
    dragging = false;
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
  };
})(window);
