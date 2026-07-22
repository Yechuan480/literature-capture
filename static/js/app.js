/**
 * App orchestration: papers list, title session, capture, previews.
 */
(function () {
  const state = {
    papers: [],
    filter: "",
    filename: null,
    title: "",
    titleSource: "",
    paperSlug: null,
    folder: null,
    noTables: false,
    config: null,
    lastResult: null,
    // pages containing "table"/"tables" (1-based), sorted
    tableHits: [],
    tableHitIndex: -1,
    tableScanToken: 0,
    tableScanning: false,
    // Global unextracted marks across all papers
    pendingGlobal: { total: 0, papers: [], items: [] },
    extracting: false,
    // SI / supplementary
    doi: "",
    url: "",
    si: null,
    siPollTimer: null,
    siPollToken: 0,
  };

  const $ = (id) => document.getElementById(id);

  function setStatus(msg, kind) {
    const el = $("status-text");
    if (!el) return;
    el.textContent = msg || "";
    el.className = kind || "";
  }

  function showLoading(on, text) {
    const mask = $("loading-mask");
    if (!mask) return;
    mask.classList.toggle("show", !!on);
    mask.textContent = text || "处理中…";
  }

  function formatSize(n) {
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
    return `${(n / 1024 / 1024).toFixed(1)} MB`;
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

  function slugifyPreview(title) {
    return (
      (title || "")
        .normalize("NFKC")
        .trim()
        .replace(/[\\/:*?"<>|\x00-\x1f]/g, "_")
        .replace(/\s+/g, "_")
        .replace(/_+/g, "_")
        .replace(/^[._]+|[._]+$/g, "")
        .slice(0, 100) || "untitled"
    );
  }

  function updateTitleUi() {
    $("title-input").value = state.title || "";
    $("title-source").textContent = state.titleSource
      ? `来源: ${state.titleSource}`
      : "";
    $("slug-preview").textContent = state.paperSlug
      ? `文件夹: ${state.paperSlug}`
      : `预览 slug: ${slugifyPreview(state.title)}`;
    const btn = $("btn-no-tables");
    if (btn) {
      btn.classList.toggle("no-tables-active", !!state.noTables);
      btn.textContent = state.noTables ? "取消「无表格」" : "无表格";
      btn.disabled = !state.filename;
    }
    const del = $("btn-delete-paper");
    if (del) del.disabled = !state.filename;
  }

  function stopSiPoll() {
    state.siPollToken += 1;
    if (state.siPollTimer) {
      clearTimeout(state.siPollTimer);
      state.siPollTimer = null;
    }
  }

  function clearViewer() {
    stopSiPoll();
    state.filename = null;
    state.title = "";
    state.titleSource = "";
    state.paperSlug = null;
    state.folder = null;
    state.noTables = false;
    state.lastResult = null;
    state.tableHits = [];
    state.tableHitIndex = -1;
    state.tableScanToken += 1;
    state.tableScanning = false;
    state.doi = "";
    state.url = "";
    state.si = null;
    updateTitleUi();
    renderSiUi(null);
    renderPreview(null);
    renderPaths(null);
    renderCaptures([]);
    if (typeof PdfViewer !== "undefined" && PdfViewer.clear) {
      try {
        PdfViewer.clear();
      } catch (_) {
        /* ignore */
      }
    }
    updatePageUi();
    updateTableNavUi();
  }

  function updateTableNavUi() {
    const label = $("table-hit-label");
    const prev = $("btn-table-prev");
    const next = $("btn-table-next");
    if (!label || !prev || !next) return;

    const n = state.tableHits.length;
    const idx = state.tableHitIndex;
    if (state.tableScanning) {
      label.textContent = "扫描…";
      label.title = "正在扫描含 table 的页面…";
      label.classList.add("scanning");
    } else if (!state.filename || !PdfViewer.state.ready) {
      label.textContent = "Table —";
      label.title = "打开文献后自动扫描";
      label.classList.remove("scanning");
    } else if (!n) {
      label.textContent = "Table 0";
      label.title = "未找到 table / tables（扫描版 PDF 可能无文本层）· 点击重新扫描";
      label.classList.remove("scanning");
    } else {
      const page = state.tableHits[Math.max(0, idx)] || state.tableHits[0];
      label.textContent = `Table ${Math.max(1, idx + 1)}/${n}`;
      label.title = `第 ${page} 页 · 共 ${n} 页含 table · 点击重新扫描`;
      label.classList.remove("scanning");
    }

    const canNav = n > 0 && !state.tableScanning;
    prev.disabled = !canNav;
    next.disabled = !canNav;
  }

  function syncTableHitIndexToPage() {
    const page = PdfViewer.state.page || 1;
    const hits = state.tableHits;
    if (!hits.length) {
      state.tableHitIndex = -1;
      return;
    }
    // Prefer exact page match; else nearest hit at or before current page
    let best = 0;
    for (let i = 0; i < hits.length; i++) {
      if (hits[i] === page) {
        state.tableHitIndex = i;
        return;
      }
      if (hits[i] <= page) best = i;
    }
    state.tableHitIndex = best;
  }

  async function scanTablePages(opts) {
    opts = opts || {};
    if (!PdfViewer.state.ready || !state.filename) {
      state.tableHits = [];
      state.tableHitIndex = -1;
      updateTableNavUi();
      return;
    }
    if (typeof PdfViewer.findPages !== "function") {
      state.tableScanning = false;
      state.tableHits = [];
      state.tableHitIndex = -1;
      updateTableNavUi();
      setStatus(
        "Table 扫描不可用：请强制刷新页面（Cmd+Shift+R）以加载最新脚本",
        "warn"
      );
      return;
    }
    const token = ++state.tableScanToken;
    state.tableScanning = true;
    updateTableNavUi();
    try {
      const hits = await PdfViewer.findPages("tables?", {
        onProgress: (done, total) => {
          if (token !== state.tableScanToken) return;
          const label = $("table-hit-label");
          if (label) label.textContent = `扫描 ${done}/${total}`;
        },
      });
      if (token !== state.tableScanToken) return;
      state.tableHits = (hits || []).map((h) => h.page);
      syncTableHitIndexToPage();
      state.tableScanning = false;
      updateTableNavUi();
      if (opts.announce !== false) {
        const n = state.tableHits.length;
        if (n) {
          setStatus(`找到 ${n} 页含 table · T / Shift+T 跳转`, "ok");
        } else {
          setStatus("未找到 table（可能为扫描版或无文本层）", "warn");
        }
      }
    } catch (e) {
      if (token !== state.tableScanToken) return;
      state.tableScanning = false;
      state.tableHits = [];
      state.tableHitIndex = -1;
      updateTableNavUi();
      if (opts.announce !== false) {
        setStatus(`Table 扫描失败: ${e.message}`, "warn");
      }
    }
  }

  async function jumpTableHit(delta) {
    const hits = state.tableHits;
    if (!hits.length) {
      if (!state.tableScanning) await scanTablePages();
      if (!state.tableHits.length) {
        setStatus("没有可跳转的 Table 页", "warn");
        return;
      }
    }
    const n = state.tableHits.length;
    let idx = state.tableHitIndex;
    if (idx < 0) idx = 0;
    else idx = (idx + delta + n) % n;
    state.tableHitIndex = idx;
    const page = state.tableHits[idx];
    RegionSelect.cancel();
    await PdfViewer.goTo(page);
    updatePageUi();
    updateTableNavUi();
    setStatus(`Table ${idx + 1}/${n} · 第 ${page} 页`);
  }

  async function deletePaper(filename, opts) {
    if (!filename) {
      setStatus("请先选择 PDF", "warn");
      return;
    }
    const captureCount =
      typeof opts?.captureCount === "number"
        ? opts.captureCount
        : Number(state.papers.find((p) => p.filename === filename)?.capture_count) ||
          0;
    const capHint =
      captureCount > 0
        ? `\n同时删除已截取的 ${captureCount} 张表格及对应文件夹。`
        : "\n若有对应截取文件夹也会一并删除。";
    const ok = window.confirm(
      `确定删除文献？\n\n${filename}${capHint}\n\n此操作不可恢复。`
    );
    if (!ok) return;
    try {
      showLoading(true, "删除文献…");
      const res = await api("/api/papers/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename, delete_captures: true }),
      });
      const wasOpen = state.filename === filename;
      state.papers = state.papers.filter((p) => p.filename !== filename);
      if (wasOpen) clearViewer();
      renderPaperList();
      const nCap = (res.deleted_captures || []).length;
      setStatus(
        nCap
          ? `已删除 ${filename}（含 ${nCap} 个截取文件夹）`
          : `已删除 ${filename}`,
        "ok"
      );
    } catch (e) {
      setStatus(`删除失败: ${e.message}`, "warn");
    } finally {
      showLoading(false);
    }
  }

  function paperMatchesFilter(p, q) {
    if (!q) return true;
    const hay = `${p.filename || ""} ${p.title || ""} ${p.paper_slug || ""}`.toLowerCase();
    return hay.includes(q);
  }

  function filteredPapers() {
    const q = (state.filter || "").trim().toLowerCase();
    // Server already sorts: unprocessed → no_tables → captured
    if (!q) return state.papers;
    return state.papers.filter((p) => paperMatchesFilter(p, q));
  }

  function renderPaperList() {
    const ul = $("paper-list");
    ul.innerHTML = "";
    const items = filteredPapers();
    const countEl = $("paper-count");
    if (countEl) {
      const total = state.papers.length;
      countEl.textContent =
        items.length === total ? `共 ${total} 篇` : `${items.length} / ${total}`;
    }
    if (!state.papers.length) {
      ul.innerHTML = `<li class="empty">未找到 PDF。请将文件放入文献目录下的 pdfs/ 文件夹。</li>`;
      return;
    }
    if (!items.length) {
      ul.innerHTML = `<li class="empty">无匹配文献，试试其他关键词</li>`;
      return;
    }
    for (const p of items) {
      const li = document.createElement("li");
      if (p.filename === state.filename) li.classList.add("active");
      const count = Number(p.capture_count) || 0;
      if (count > 0) li.classList.add("has-captures");
      if (p.no_tables && count === 0) li.classList.add("no-tables");
      li.innerHTML = `
        <div class="paper-row">
          <div class="paper-main">
            <div class="name"></div>
            <div class="title-line"></div>
            <div class="meta"></div>
          </div>
          <div class="paper-actions">
            <div class="paper-badge" aria-hidden="true"></div>
            <button type="button" class="btn-del-paper" title="删除此 PDF">×</button>
          </div>
        </div>`;
      li.querySelector(".name").textContent = p.filename;
      const titleLine = li.querySelector(".title-line");
      if (p.title) {
        titleLine.textContent = p.title;
      } else {
        titleLine.style.display = "none";
      }
      li.querySelector(".meta").textContent = `${formatSize(p.size)} · ${
        p.mtime?.slice(0, 10) || ""
      }`;
      const badge = li.querySelector(".paper-badge");
      const pending = Number(p.pending_extract) || 0;
      if (count > 0) {
        badge.classList.add("done");
        if (pending > 0) {
          badge.classList.add("pending-extract");
          badge.title = `已标记 ${count} 处 · ${pending} 待提取`;
          badge.innerHTML = `<span class="count">${count}</span><span class="pend">/${pending}</span>`;
        } else {
          badge.title = `已标记 ${count} 处（均已提取）`;
          badge.innerHTML = `<span class="check">✓</span><span class="count">${count}</span>`;
        }
      } else if (p.no_tables) {
        badge.classList.add("none");
        badge.title = "已标记：无表格";
        badge.textContent = "无表格";
      } else {
        badge.classList.add("empty-badge");
        badge.title = "尚未处理";
        badge.textContent = "";
      }
      const siN = Number(p.si_file_count) || 0;
      const siSt = p.si_status || "";
      if (siN > 0 || (siSt && siSt !== "idle" && siSt !== "disabled")) {
        const siDot = document.createElement("span");
        siDot.className = "si-dot " + siBadgeClass(siSt);
        siDot.title = siStatusLabel(siSt) + (siN ? ` · ${siN} 文件` : "");
        siDot.textContent = siN > 0 ? `SI${siN}` : "SI";
        li.querySelector(".paper-actions").insertBefore(siDot, badge);
      }
      const delBtn = li.querySelector(".btn-del-paper");
      delBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        deletePaper(p.filename, { captureCount: count });
      });
      li.addEventListener("click", () => openPaper(p.filename));
      ul.appendChild(li);
    }
  }

  function patchPaper(filename, patch) {
    const p = state.papers.find((x) => x.filename === filename);
    if (!p) return;
    Object.assign(p, patch);
    // Keep server-side sort groups roughly correct after local edits
    state.papers.sort((a, b) => {
      const group = (x) =>
        (Number(x.capture_count) || 0) > 0 ? 2 : x.no_tables ? 1 : 0;
      const ga = group(a);
      const gb = group(b);
      if (ga !== gb) return ga - gb;
      return (a.filename || "").localeCompare(b.filename || "", undefined, {
        sensitivity: "base",
      });
    });
    renderPaperList();
  }

  function bumpPaperCaptureCount(filename, absoluteCount) {
    const patch = { no_tables: false };
    const p = state.papers.find((x) => x.filename === filename);
    if (typeof absoluteCount === "number") {
      patch.capture_count = absoluteCount;
    } else {
      patch.capture_count = (Number(p?.capture_count) || 0) + 1;
    }
    // Prefer global queue count for this paper if available
    const bySlug = state.paperSlug
      ? (state.pendingGlobal.papers || []).find(
          (x) => x.paper_slug === state.paperSlug
        )
      : null;
    const bySrc = (state.pendingGlobal.papers || []).find(
      (x) => x.source_pdf === filename
    );
    const hit = bySlug || bySrc;
    if (hit) {
      patch.pending_extract = Number(hit.pending) || 0;
    } else {
      patch.pending_extract = (Number(p?.pending_extract) || 0) + 1;
    }
    if (state.paperSlug) patch.paper_slug = state.paperSlug;
    if (state.title) patch.title = state.title;
    patchPaper(filename, patch);
  }

  function renderPreview(matrix) {
    const wrap = $("preview-table-wrap");
    if (!matrix || !matrix.length) {
      wrap.innerHTML = `<div class="empty">暂无表格预览</div>`;
      return;
    }
    const table = document.createElement("table");
    table.className = "preview-table";
    const maxCols = Math.max(...matrix.map((r) => r.length));
    const thead = document.createElement("thead");
    const hr = document.createElement("tr");
    for (let c = 0; c < maxCols; c++) {
      const th = document.createElement("th");
      th.textContent = `C${c + 1}`;
      hr.appendChild(th);
    }
    thead.appendChild(hr);
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    for (const row of matrix) {
      const tr = document.createElement("tr");
      for (let c = 0; c < maxCols; c++) {
        const td = document.createElement("td");
        td.textContent = row[c] ?? "";
        tr.appendChild(td);
      }
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    wrap.innerHTML = "";
    wrap.appendChild(table);
  }

  function renderPaths(result) {
    const el = $("path-list");
    if (!result?.paths) {
      el.textContent = "";
      return;
    }
    const lines = [`PNG: ${result.paths.png || "—"}`];
    if (result.paths.csv) lines.push(`CSV: ${result.paths.csv}`);
    if (result.paths.xlsx) lines.push(`XLSX: ${result.paths.xlsx}`);
    if (result.extracted === false) lines.push("（仅截图，待批量提取）");
    el.innerHTML = lines.join("<br>");
  }

  function applyPendingGlobal(data) {
    if (!data || typeof data !== "object") return;
    state.pendingGlobal = {
      total: Number(data.total) || 0,
      papers: data.papers || [],
      items: data.items || [],
    };
    // Keep paper list pending badges in sync when we know per-source counts
    if (Array.isArray(state.papers) && state.papers.length) {
      const bySrc = {};
      for (const p of state.pendingGlobal.papers) {
        if (p.source_pdf) bySrc[p.source_pdf] = Number(p.pending) || 0;
      }
      for (const paper of state.papers) {
        if (Object.prototype.hasOwnProperty.call(bySrc, paper.filename)) {
          paper.pending_extract = bySrc[paper.filename];
        } else if (paper.paper_slug) {
          // zero out if slug known but not in pending list
          const hit = state.pendingGlobal.papers.find(
            (x) => x.paper_slug === paper.paper_slug
          );
          paper.pending_extract = hit ? Number(hit.pending) || 0 : 0;
        }
      }
    }
  }

  function paperPendingCount() {
    if (!state.paperSlug) return 0;
    const hit = (state.pendingGlobal.papers || []).find(
      (p) => p.paper_slug === state.paperSlug
    );
    return hit ? Number(hit.pending) || 0 : 0;
  }

  function updateExtractButtons(localItems) {
    const globalTotal = Number(state.pendingGlobal?.total) || 0;
    const localList = localItems || [];
    const localPending = localList.length
      ? localList.filter((c) => !c.extracted).length
      : paperPendingCount();
    const localTotal = localList.length;
    const enabled = globalTotal > 0 && !state.extracting;
    ["btn-extract-batch", "btn-extract-batch-side"].forEach((id) => {
      const btn = $(id);
      if (!btn) return;
      btn.disabled = !enabled;
      btn.title = state.extracting
        ? "正在提取…"
        : enabled
          ? `批量提取全部 ${globalTotal} 处待处理标记（跨文献）`
          : "暂无待提取标记";
      const label =
        globalTotal > 0 ? `提取表格 (${globalTotal})` : "提取表格";
      btn.textContent = label;
    });
    const hint = $("extract-pending-hint");
    if (hint) {
      const paperN = (state.pendingGlobal.papers || []).length;
      hint.textContent =
        globalTotal > 0
          ? `全局待提取: ${globalTotal}（${paperN} 篇）`
          : "全局待提取: 0";
    }
    const ph = $("extract-paper-hint");
    if (ph) {
      if (!state.paperSlug) {
        ph.textContent = "本篇: —（打开并标记后计入全局）";
      } else if (localTotal) {
        ph.textContent = localPending
          ? `本篇: ${localPending}/${localTotal} 待提取`
          : `本篇: 全部 ${localTotal} 处已提取`;
      } else {
        ph.textContent =
          localPending > 0
            ? `本篇: ${localPending} 待提取`
            : "本篇: 尚无标记";
      }
    }
  }

  async function refreshPendingGlobal() {
    try {
      const data = await api("/api/extract/pending");
      applyPendingGlobal(data);
      updateExtractButtons(null);
      renderPaperList();
    } catch (_) {
      /* ignore — e.g. offline */
    }
  }

  function renderCaptures(items) {
    const ul = $("capture-list");
    ul.innerHTML = "";
    if (!items || !items.length) {
      ul.innerHTML = `<li class="empty">本篇尚无标记截图</li>`;
      updateExtractButtons([]);
      return;
    }
    for (const c of items) {
      const li = document.createElement("li");
      const extracted = !!c.extracted;
      li.classList.toggle("cap-pending", !extracted);
      li.classList.toggle("cap-extracted", extracted);
      li.innerHTML = `
        <div class="cap-title"></div>
        <div class="cap-meta"></div>
        <div class="cap-actions">
          <button type="button" data-act="extract"></button>
        </div>`;
      const status = extracted
        ? c.review_status === "passed"
          ? "已通过"
          : c.review_status === "failed"
            ? "不通过"
            : "已提取"
        : "仅截图";
      li.querySelector(".cap-title").textContent =
        `${c.stem || `table${c.table_id}`} · ${status}`;
      const metaParts = [
        c.page != null ? `p.${c.page}` : null,
        c.png_name,
        c.csv_name,
        c.xlsx_name,
        c.engine || null,
      ].filter(Boolean);
      li.querySelector(".cap-meta").textContent = metaParts.join(" · ");
      const actBtn = li.querySelector('[data-act="extract"]');
      actBtn.textContent = extracted ? "重新提取" : "提取";
      actBtn.addEventListener("click", () => {
        if (extracted) reextract(c.table_id);
        else extractOne(c.table_id);
      });
      ul.appendChild(li);
    }
    updateExtractButtons(items);
  }

  function siStatusLabel(st) {
    const map = {
      idle: "未开始",
      queued: "排队中",
      running: "获取中",
      ok: "已下载",
      partial: "部分成功",
      failed: "失败",
      paywalled: "付费墙",
      no_si: "无开放 SI",
      disabled: "已关闭",
    };
    return map[st] || st || "—";
  }

  function siBadgeClass(st) {
    if (st === "ok") return "si-ok";
    if (st === "partial" || st === "running" || st === "queued") return "si-warn";
    if (st === "failed" || st === "paywalled") return "si-err";
    if (st === "no_si" || st === "disabled") return "si-muted";
    return "";
  }

  function formatBytes(n) {
    n = Number(n) || 0;
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
    return `${(n / 1024 / 1024).toFixed(1)} MB`;
  }

  function parseDoiUrlInput(raw) {
    const s = (raw || "").trim();
    if (!s) return { doi: null, url: null };
    if (/^https?:\/\//i.test(s)) {
      const m = s.match(/10\.\d{4,9}\/[-._;()/:A-Z0-9]+/i);
      return { doi: m ? m[0].replace(/[.,;]+$/, "") : null, url: s };
    }
    const m = s.match(/10\.\d{4,9}\/[-._;()/:A-Z0-9]+/i);
    if (m) return { doi: m[0].replace(/[.,;]+$/, ""), url: null };
    return { doi: s, url: null };
  }

  function renderSiUi(payload) {
    const badge = $("si-badge");
    const msg = $("si-msg");
    const panel = $("si-panel-status");
    const list = $("si-file-list");
    const btn = $("btn-si-run");
    const doiInp = $("doi-input");
    const si = (payload && payload.si) || payload || null;
    state.si = si;

    if (payload && payload.doi) state.doi = payload.doi;
    if (payload && payload.url) state.url = payload.url;
    if (doiInp && document.activeElement !== doiInp) {
      doiInp.value = state.doi || state.url || "";
    }
    if (btn) btn.disabled = !state.filename;

    const st = (si && si.status) || "idle";
    const label = siStatusLabel(st);
    if (badge) {
      badge.textContent = `SI: ${label}`;
      badge.className = "badge si-badge " + siBadgeClass(st);
      badge.title = (si && si.message) || label;
    }
    const text = (si && si.message) || "";
    if (msg) msg.textContent = text;
    if (panel) {
      const n = ((si && si.files) || (payload && payload.files) || []).length;
      panel.textContent =
        text ||
        (st === "idle"
          ? "打开文献后自动检索开放 SI（Crossref）"
          : `${label}${n ? ` · ${n} 个文件` : ""}`);
    }

    const files =
      (payload && payload.files) ||
      (si && si.files) ||
      [];
    if (list) {
      if (!files.length) {
        list.innerHTML = `<li class="empty">${
          st === "running" || st === "queued"
            ? "下载中…"
            : st === "no_si"
              ? "未找到开放补充材料"
              : st === "paywalled"
                ? "疑似付费墙，未能下载"
                : "暂无文件"
        }</li>`;
      } else {
        list.innerHTML = "";
        const slug = state.paperSlug || (payload && payload.paper_slug) || "";
        for (const f of files) {
          const li = document.createElement("li");
          const name = f.name || f.relpath || "file";
          const href = slug
            ? `/api/si/file/${encodeURIComponent(slug)}/${encodeURIComponent(name)}`
            : "#";
          li.innerHTML = `
            <a class="si-file-name" href="${href}" target="_blank" rel="noopener"></a>
            <div class="si-file-meta"></div>`;
          li.querySelector(".si-file-name").textContent = name;
          li.querySelector(".si-file-meta").textContent = [
            f.kind,
            formatBytes(f.bytes),
            f.content_type,
          ]
            .filter(Boolean)
            .join(" · ");
          list.appendChild(li);
        }
      }
    }

    if (state.filename && si) {
      patchPaper(state.filename, {
        doi: state.doi || null,
        si_status: st,
        si_file_count: files.length,
        paper_slug: state.paperSlug || undefined,
      });
    }
  }

  function scheduleSiPoll() {
    stopSiPoll();
    const token = state.siPollToken;
    const filename = state.filename;
    if (!filename) return;
    state.siPollTimer = setTimeout(async () => {
      if (token !== state.siPollToken || state.filename !== filename) return;
      try {
        const st = await api(
          `/api/si/status?filename=${encodeURIComponent(filename)}`
        );
        if (token !== state.siPollToken || state.filename !== filename) return;
        if (st.paper_slug) state.paperSlug = st.paper_slug;
        if (st.doi) state.doi = st.doi;
        if (st.url) state.url = st.url;
        renderSiUi(st);
        const status = (st.si && st.si.status) || "";
        if (status === "queued" || status === "running") {
          scheduleSiPoll();
        }
      } catch (_) {
        if (token === state.siPollToken) scheduleSiPoll();
      }
    }, 1500);
  }

  async function refreshSiStatus() {
    if (!state.filename) {
      renderSiUi(null);
      return null;
    }
    const st = await api(
      `/api/si/status?filename=${encodeURIComponent(state.filename)}`
    );
    if (st.paper_slug) state.paperSlug = st.paper_slug;
    if (st.doi) state.doi = st.doi;
    if (st.url) state.url = st.url;
    if (st.title && !state.title) state.title = st.title;
    renderSiUi(st);
    const status = (st.si && st.si.status) || "";
    if (status === "queued" || status === "running") scheduleSiPoll();
    else stopSiPoll();
    return st;
  }

  async function startSiAuto({ force = false } = {}) {
    if (!state.filename) return;
    const cfg = state.config && state.config.si;
    if (cfg && cfg.enabled === false) {
      renderSiUi({
        si: { status: "disabled", message: "SI 功能已在配置中关闭", files: [] },
      });
      return;
    }
    if (!force && cfg && cfg.auto_on_open === false) {
      await refreshSiStatus().catch(() => {});
      return;
    }
    try {
      const parsed = parseDoiUrlInput($("doi-input")?.value || state.doi || "");
      const body = {
        filename: state.filename,
        title: state.title || null,
        force: !!force,
      };
      if (parsed.doi) body.doi = parsed.doi;
      if (parsed.url) body.url = parsed.url;
      const res = await api("/api/si/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.paper_slug) state.paperSlug = res.paper_slug;
      renderSiUi({
        paper_slug: res.paper_slug,
        doi: body.doi || state.doi,
        si: {
          status: res.si_status || "queued",
          message: res.message || "",
          files: [],
        },
      });
      updateTitleUi();
      const st = res.si_status || "";
      if (st === "queued" || st === "running") scheduleSiPoll();
      else await refreshSiStatus().catch(() => {});
    } catch (e) {
      setStatus(`SI 启动失败: ${e.message}`, "warn");
      renderSiUi({
        si: { status: "failed", message: e.message, files: [] },
      });
    }
  }

  async function runSiManual() {
    if (!state.filename) {
      setStatus("请先选择 PDF", "warn");
      return;
    }
    setStatus("正在获取补充材料…");
    await startSiAuto({ force: true });
  }

  async function loadConfig() {
    state.config = await api("/api/config");
    const ocr = state.config.ocr || {};
    const paddle = state.config.paddle || {};
    let badge = `OCR: ${ocr.engine || "?"}`;
    if (paddle.import_ok || ocr.paddle_available) {
      badge += paddle.paddle_detect || ocr.paddle_detect ? " · Paddle✓" : " · Paddle";
    }
    $("ocr-badge").textContent = badge;
    if (ocr.hint) setStatus(ocr.hint, "warn");
    applyAiUi(state.config.ai || { ready: state.config.ai_enabled });
  }

  function applyAiUi(ai) {
    ai = ai || {};
    const ready = !!ai.ready;
    const enabled = !!ai.enabled;
    const toggle = $("ai-toggle");
    if (toggle) {
      toggle.disabled = !ready;
      if (!ready) toggle.checked = false;
      toggle.title = ready
        ? "批量/单项提取时在本地 OCR 后调用视觉模型增强"
        : "请先在「AI 设置」中启用并填写 API Key";
    }
    const badge = $("ai-status-badge");
    if (badge) {
      badge.classList.remove("ready", "warn", "off");
      if (ready) {
        badge.textContent = `AI: ${ai.model || "就绪"}`;
        badge.classList.add("ready");
      } else if (enabled && !ai.api_key_set) {
        badge.textContent = "AI: 缺 Key";
        badge.classList.add("warn");
      } else {
        badge.textContent = "AI: 未启用";
        badge.classList.add("off");
      }
    }
    // Prefill form if panel fields exist
    if ($("ai-enabled")) $("ai-enabled").checked = enabled;
    if ($("ai-base-url") && !$("ai-base-url").dataset.dirty)
      $("ai-base-url").value = ai.base_url || "https://api.openai.com/v1";
    if ($("ai-model") && !$("ai-model").dataset.dirty)
      $("ai-model").value = ai.model || "gpt-4o";
    if ($("ai-api-key") && !$("ai-api-key").dataset.dirty) {
      $("ai-api-key").value = "";
      $("ai-api-key").placeholder = ai.api_key_set
        ? `已保存 ${ai.api_key_masked || "••••"}（留空保持不变）`
        : "sk-…";
    }
  }

  function setAiMsg(text, kind) {
    const el = $("ai-settings-msg");
    if (!el) return;
    el.textContent = text || "";
    el.className = "hint" + (kind ? ` ${kind}` : "");
  }

  function toggleAiPanel(force) {
    const panel = $("ai-settings-panel");
    if (!panel) return;
    const next = typeof force === "boolean" ? force : panel.hidden;
    panel.hidden = !next;
  }

  async function refreshAiSettings() {
    const ai = await api("/api/settings/ai");
    if (state.config) state.config.ai = ai;
    state.config = state.config || {};
    state.config.ai_enabled = !!ai.ready;
    applyAiUi(ai);
    return ai;
  }

  async function saveAiSettings() {
    try {
      setAiMsg("保存中…");
      const body = {
        enabled: !!$("ai-enabled").checked,
        base_url: $("ai-base-url").value.trim(),
        model: $("ai-model").value.trim(),
        clear_key: !!$("ai-clear-key").checked,
      };
      const key = $("ai-api-key").value;
      if (key && key.trim()) body.api_key = key.trim();
      const ai = await api("/api/settings/ai", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      $("ai-api-key").value = "";
      $("ai-api-key").dataset.dirty = "";
      $("ai-clear-key").checked = false;
      if (state.config) state.config.ai = ai;
      state.config = state.config || {};
      state.config.ai_enabled = !!ai.ready;
      applyAiUi(ai);
      setAiMsg(
        ai.ready
          ? "已保存，AI 可用。截取时勾选「使用 AI 视觉增强」即可。"
          : "已保存。请启用并填写有效 Key 后才能使用。",
        ai.ready ? "ok" : "warn"
      );
      setStatus(ai.ready ? "AI 设置已保存并可用" : "AI 设置已保存", ai.ready ? "ok" : "warn");
    } catch (e) {
      setAiMsg(`保存失败: ${e.message}`, "warn");
    }
  }

  async function testAiSettings() {
    try {
      setAiMsg("测试连接中…");
      // Save current form first if user typed a new key
      const key = $("ai-api-key").value;
      if (
        key.trim() ||
        $("ai-enabled").checked !== !!(state.config?.ai?.enabled) ||
        $("ai-base-url").value.trim() !== (state.config?.ai?.base_url || "") ||
        $("ai-model").value.trim() !== (state.config?.ai?.model || "")
      ) {
        await saveAiSettings();
      }
      const res = await api("/api/settings/ai/test", { method: "POST" });
      const t = res.test || {};
      if (t.ok) {
        setAiMsg(`连接成功 · ${t.model || ""} · 回复: ${t.reply || "OK"}`, "ok");
        setStatus("AI 连接测试成功", "ok");
      } else {
        setAiMsg(`连接失败: ${t.error || "未知错误"}`, "warn");
        setStatus("AI 连接测试失败", "warn");
      }
      applyAiUi(res);
    } catch (e) {
      setAiMsg(`测试失败: ${e.message}`, "warn");
    }
  }

  async function loadPapers() {
    state.papers = await api("/api/papers");
    renderPaperList();
    await refreshPendingGlobal();
    const q = (state.filter || "").trim();
    const pend = Number(state.pendingGlobal?.total) || 0;
    setStatus(
      q
        ? `已加载 ${state.papers.length} 篇 · 筛选「${q}」` +
            (pend ? ` · 待提取 ${pend}` : "")
        : `已加载 ${state.papers.length} 篇 PDF` +
            (pend ? ` · 待提取 ${pend}` : "")
    );
  }

  async function openPaper(filename) {
    try {
      showLoading(true, "加载 PDF…");
      stopSiPoll();
      state.filename = filename;
      state.paperSlug = null;
      state.folder = null;
      state.noTables = false;
      state.lastResult = null;
      state.tableHits = [];
      state.tableHitIndex = -1;
      state.tableScanToken += 1;
      state.tableScanning = false;
      state.doi = "";
      state.url = "";
      state.si = null;
      updateTableNavUi();
      const known = state.papers.find((p) => p.filename === filename);
      if (known) {
        state.noTables = !!known.no_tables;
        state.paperSlug = known.paper_slug || null;
        if (known.title) state.title = known.title;
        if (known.doi) state.doi = known.doi;
      }
      renderPaperList();
      renderPreview(null);
      renderPaths(null);
      renderSiUi(
        known
          ? {
              doi: known.doi,
              paper_slug: known.paper_slug,
              si: {
                status: known.si_status || "idle",
                message: "",
                files: [],
              },
              files: [],
            }
          : null
      );
      // Keep global pending badge; only clear local list until slug known
      renderCaptures([]);
      updateExtractButtons([]);

      const titleInfo = await api(
        `/api/papers/title?filename=${encodeURIComponent(filename)}`
      );
      state.title = titleInfo.title;
      state.titleSource = titleInfo.source;
      // Prefer known meta title if session exists
      if (known?.title) {
        state.title = known.title;
        state.titleSource = "session";
      }
      updateTitleUi();

      if (state.paperSlug) {
        await refreshCaptures();
      }

      await PdfViewer.load(`/api/pdf/${encodeURIComponent(filename)}`, filename);
      updatePageUi();
      RegionSelect.setActive(false);
      $("btn-select").classList.remove("active");
      setStatus(`已打开: ${filename}`);
      // Non-blocking: table page scan + SI auto-fetch (no title confirm required)
      scanTablePages({ announce: true }).catch(() => {});
      startSiAuto({ force: false }).catch(() => {});
    } catch (e) {
      setStatus(`打开失败: ${e.message}`, "warn");
    } finally {
      showLoading(false);
    }
  }

  async function confirmSession() {
    if (!state.filename) {
      setStatus("请先选择 PDF", "warn");
      return;
    }
    const title = $("title-input").value.trim();
    if (!title) {
      setStatus("标题不能为空", "warn");
      return;
    }
    try {
      showLoading(true, "保存标题…");
      const session = await api("/api/papers/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename: state.filename, title }),
      });
      state.title = session.title;
      state.paperSlug = session.paper_slug;
      state.folder = session.folder;
      state.noTables = !!session.no_tables;
      updateTitleUi();
      patchPaper(state.filename, {
        paper_slug: session.paper_slug,
        title: session.title,
        no_tables: !!session.no_tables,
      });
      await refreshCaptures();
      setStatus(`标题已确认 · ${session.folder}`, "ok");
    } catch (e) {
      setStatus(`确认标题失败: ${e.message}`, "warn");
    } finally {
      showLoading(false);
    }
  }

  async function toggleNoTables() {
    if (!state.filename) {
      setStatus("请先选择 PDF", "warn");
      return;
    }
    const title = ($("title-input").value || state.title || "").trim();
    if (!title) {
      setStatus("请先填写标题", "warn");
      return;
    }
    const next = !state.noTables;
    try {
      showLoading(true, next ? "标记无表格…" : "取消标记…");
      const res = await api("/api/papers/status", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          filename: state.filename,
          title,
          no_tables: next,
        }),
      });
      state.title = res.title;
      state.paperSlug = res.paper_slug;
      state.folder = res.folder;
      state.noTables = !!res.no_tables;
      updateTitleUi();
      patchPaper(state.filename, {
        paper_slug: res.paper_slug,
        title: res.title,
        no_tables: !!res.no_tables,
        capture_count: res.capture_count,
      });
      setStatus(
        res.no_tables ? "已标记：本篇无表格" : "已取消「无表格」标记",
        "ok"
      );
    } catch (e) {
      setStatus(`标记失败: ${e.message}`, "warn");
    } finally {
      showLoading(false);
    }
  }

  async function refreshCaptures() {
    if (!state.paperSlug) {
      renderCaptures([]);
      updateExtractButtons([]);
      return;
    }
    const data = await api(
      `/api/papers/${encodeURIComponent(state.paperSlug)}/captures`
    );
    renderCaptures(data.captures || []);
  }

  function updatePageUi() {
    const s = PdfViewer.state;
    $("page-input").value = s.page || 1;
    $("page-total").textContent = `/ ${s.numPages || 0}`;
    $("zoom-label").textContent = `${Math.round((s.scale || 1) * 100)}%`;
    const rotEl = $("rotation-label");
    if (rotEl) rotEl.textContent = `${s.rotation || 0}°`;
    if (state.tableHits.length && !state.tableScanning) {
      syncTableHitIndexToPage();
      updateTableNavUi();
    }
  }

  function toggleSelectMode() {
    if (!PdfViewer.state.ready) {
      setStatus("请先打开 PDF", "warn");
      return;
    }
    const next = !RegionSelect.isActive();
    RegionSelect.setActive(next);
    $("btn-select").classList.toggle("active", next);
    setStatus(next ? "框选模式：在页面上拖拽矩形" : "已退出框选模式");
  }

  async function doCapture() {
    if (!state.filename) {
      setStatus("请先选择 PDF", "warn");
      return;
    }
    const title = $("title-input").value.trim();
    if (!title) {
      setStatus("请先填写并确认标题", "warn");
      return;
    }
    if (!RegionSelect.getSelectionCss()) {
      setStatus("请先拖拽选择表格区域", "warn");
      return;
    }

    try {
      showLoading(true, "保存截图…");
      // Ensure session exists / updated
      if (!state.paperSlug || state.title !== title) {
        const session = await api("/api/papers/session", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ filename: state.filename, title }),
        });
        state.title = session.title;
        state.paperSlug = session.paper_slug;
        state.folder = session.folder;
        updateTitleUi();
      }

      const blob = await RegionSelect.cropToPngBlob();
      const fd = new FormData();
      fd.append("image", blob, "capture.png");
      fd.append("filename", state.filename);
      fd.append("title", title);
      fd.append("page", String(PdfViewer.state.page || 1));
      fd.append("use_ai", "false");

      const result = await api("/api/capture", { method: "POST", body: fd });
      state.lastResult = result;
      state.paperSlug = result.paper_slug;
      state.folder = result.folder;
      state.noTables = false;
      updateTitleUi();
      renderPreview([]);
      renderPaths(result);
      if (result.pending_global) {
        applyPendingGlobal(result.pending_global);
      }
      await refreshCaptures();
      bumpPaperCaptureCount(state.filename, result.table_id);
      if (!result.pending_global) await refreshPendingGlobal();
      else {
        updateExtractButtons(null);
        renderPaperList();
      }

      RegionSelect.cancel();
      // Stay in select mode for the next mark; only the blue rect is cleared

      const g = Number(state.pendingGlobal?.total) || 0;
      setStatus(
        `已标记 table${result.table_id}（仅截图）· 全局待提取 ${g}`,
        "ok"
      );
    } catch (e) {
      setStatus(`截取失败: ${e.message}`, "warn");
    } finally {
      showLoading(false);
    }
  }

  function setExtractProgress(opts) {
    opts = opts || {};
    const panel = $("extract-progress");
    const inline = $("extract-progress-inline");
    const label = $("extract-progress-label");
    const count = $("extract-progress-count");
    const detail = $("extract-progress-detail");
    const bar = $("extract-progress-bar");
    const barInline = $("extract-progress-bar-inline");
    const inlineText = $("extract-progress-inline-text");

    if (opts.hide) {
      if (panel) panel.hidden = true;
      if (inline) inline.hidden = true;
      if (bar) bar.style.width = "0%";
      if (barInline) barInline.style.width = "0%";
      return;
    }

    const done = Math.max(0, Number(opts.done) || 0);
    const total = Math.max(0, Number(opts.total) || 0);
    const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
    const title = opts.label || "提取中…";
    const detailText = opts.detail || "";

    if (panel) panel.hidden = false;
    if (inline) inline.hidden = false;
    if (label) label.textContent = title;
    if (count) count.textContent = total > 0 ? `${done}/${total}` : `${done}`;
    if (detail) detail.textContent = detailText;
    if (bar) bar.style.width = `${pct}%`;
    if (barInline) barInline.style.width = `${pct}%`;
    if (inlineText) inlineText.textContent = `${pct}%`;
  }

  async function extractOne(tableId) {
    if (!state.paperSlug) return;
    if (state.extracting) {
      setStatus("已有提取任务在进行中", "warn");
      return;
    }
    state.extracting = true;
    updateExtractButtons(null);
    try {
      setExtractProgress({
        done: 0,
        total: 1,
        label: "提取中…",
        detail: `table${tableId}`,
      });
      setStatus(`提取 table${tableId}…`);
      const useAi = $("ai-toggle")?.checked ? "true" : "false";
      const result = await api(
        `/api/capture/${encodeURIComponent(state.paperSlug)}/${tableId}/extract?use_ai=${useAi}`,
        { method: "POST" }
      );
      state.lastResult = result;
      renderPreview(result.preview);
      renderPaths(result);
      if (result.pending_global) applyPendingGlobal(result.pending_global);
      if (result.captures) renderCaptures(result.captures);
      else await refreshCaptures();
      if (!result.pending_global) await refreshPendingGlobal();
      else {
        updateExtractButtons(result.captures || null);
        renderPaperList();
      }
      setExtractProgress({
        done: 1,
        total: 1,
        label: "提取完成",
        detail: `table${tableId} · ${result.engine || ""}`,
      });
      setStatus(
        `已提取 table${tableId}（${result.engine}，${result.rows}×${result.cols}）`,
        "ok"
      );
    } catch (e) {
      setStatus(`提取失败: ${e.message}`, "warn");
    } finally {
      state.extracting = false;
      updateExtractButtons(null);
      setTimeout(() => setExtractProgress({ hide: true }), 1200);
    }
  }

  async function extractBatch() {
    if (state.extracting) {
      setStatus("已有提取任务在进行中", "warn");
      return;
    }
    // Prefer live pending list so progress can advance item-by-item
    let queue = Array.isArray(state.pendingGlobal?.items)
      ? state.pendingGlobal.items.slice()
      : [];
    if (!queue.length) {
      try {
        const live = await api("/api/extract/pending");
        applyPendingGlobal(live);
        queue = Array.isArray(live.items) ? live.items.slice() : [];
      } catch (_) {
        /* fall through */
      }
    }
    const total = queue.length;
    if (total <= 0) {
      setStatus("当前没有待提取的标记区域", "warn");
      updateExtractButtons(null);
      return;
    }

    state.extracting = true;
    updateExtractButtons(null);
    const useAi = $("ai-toggle")?.checked ? "true" : "false";
    let ok = 0;
    let failed = 0;
    let lastOk = null;
    const papersTouched = new Set();

    try {
      setExtractProgress({
        done: 0,
        total,
        label: "批量提取中…",
        detail: `共 ${total} 处`,
      });
      setStatus(`批量提取 0/${total}…`);

      for (let i = 0; i < queue.length; i++) {
        const item = queue[i];
        const slug = item.paper_slug;
        const tid = item.table_id;
        const shortTitle =
          (item.title || item.source_pdf || slug || "").slice(0, 48) || slug;
        setExtractProgress({
          done: i,
          total,
          label: "批量提取中…",
          detail: `${shortTitle} · table${tid}`,
        });
        setStatus(`批量提取 ${i + 1}/${total} · ${shortTitle} · table${tid}`);
        try {
          const result = await api(
            `/api/capture/${encodeURIComponent(slug)}/${tid}/extract?use_ai=${useAi}`,
            { method: "POST" }
          );
          ok += 1;
          papersTouched.add(slug);
          lastOk = result;
          if (result.pending_global) applyPendingGlobal(result.pending_global);
          // Live-update current paper captures if same slug
          if (state.paperSlug === slug) {
            if (result.captures) renderCaptures(result.captures);
            if (result.preview) {
              state.lastResult = result;
              renderPreview(result.preview);
              renderPaths(result);
            }
          }
          updateExtractButtons(null);
          renderPaperList();
        } catch (e) {
          failed += 1;
          console.warn("extract failed", slug, tid, e);
        }
        setExtractProgress({
          done: i + 1,
          total,
          label: "批量提取中…",
          detail: `${shortTitle} · table${tid}` + (failed ? ` · 失败 ${failed}` : ""),
        });
      }

      // Final sync
      await refreshPendingGlobal();
      if (state.paperSlug) await refreshCaptures();
      else updateExtractButtons(null);
      renderPaperList();
      if (lastOk && state.paperSlug === lastOk.paper_slug) {
        state.lastResult = lastOk;
        renderPreview(lastOk.preview);
        renderPaths(lastOk);
      }
      setExtractProgress({
        done: total,
        total,
        label: failed ? "提取完成（含失败）" : "提取完成",
        detail: `成功 ${ok}/${total}` + (failed ? `，失败 ${failed}` : ""),
      });
      setStatus(
        `全局批量提取完成：成功 ${ok}/${total}` +
          (failed ? `，失败 ${failed}` : "") +
          ` · 涉及 ${papersTouched.size} 篇`,
        failed ? "warn" : "ok"
      );
    } catch (e) {
      setStatus(`批量提取失败: ${e.message}`, "warn");
    } finally {
      state.extracting = false;
      updateExtractButtons(null);
      setTimeout(() => setExtractProgress({ hide: true }), 1800);
    }
  }

  async function reextract(tableId) {
    if (!state.paperSlug) return;
    if (state.extracting) {
      setStatus("已有提取任务在进行中", "warn");
      return;
    }
    state.extracting = true;
    updateExtractButtons(null);
    try {
      setExtractProgress({
        done: 0,
        total: 1,
        label: "重新提取…",
        detail: `table${tableId}`,
      });
      setStatus("重新提取…");
      const useAi = $("ai-toggle")?.checked ? "true" : "false";
      const result = await api(
        `/api/capture/${encodeURIComponent(state.paperSlug)}/${tableId}/reextract?use_ai=${useAi}`,
        { method: "POST" }
      );
      state.lastResult = result;
      renderPreview(result.preview);
      renderPaths(result);
      if (result.pending_global) applyPendingGlobal(result.pending_global);
      if (result.captures) renderCaptures(result.captures);
      else await refreshCaptures();
      if (!result.pending_global) await refreshPendingGlobal();
      else {
        updateExtractButtons(result.captures || null);
        renderPaperList();
      }
      setExtractProgress({
        done: 1,
        total: 1,
        label: "重新提取完成",
        detail: `table${tableId} · ${result.engine || ""}`,
      });
      setStatus(`已重新提取 table${tableId}（${result.engine}）`, "ok");
    } catch (e) {
      setStatus(`重提取失败: ${e.message}`, "warn");
    } finally {
      state.extracting = false;
      updateExtractButtons(null);
      setTimeout(() => setExtractProgress({ hide: true }), 1200);
    }
  }

  function bindUi() {
    RegionSelect.bind();

    $("btn-refresh").addEventListener("click", () =>
      loadPapers().catch((e) => setStatus(e.message, "warn"))
    );
    $("btn-confirm-title").addEventListener("click", confirmSession);
    $("btn-no-tables")?.addEventListener("click", toggleNoTables);
    $("btn-delete-paper")?.addEventListener("click", () => {
      if (state.filename) deletePaper(state.filename);
    });
    $("btn-si-run")?.addEventListener("click", () => {
      runSiManual().catch((e) => setStatus(e.message, "warn"));
    });
    $("doi-input")?.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        runSiManual().catch((err) => setStatus(err.message, "warn"));
      }
    });
    $("btn-ai-settings")?.addEventListener("click", async () => {
      toggleAiPanel(true);
      try {
        await refreshAiSettings();
      } catch (e) {
        setAiMsg(e.message, "warn");
      }
    });
    $("btn-ai-settings-close")?.addEventListener("click", () => toggleAiPanel(false));
    $("btn-ai-save")?.addEventListener("click", () => saveAiSettings());
    $("btn-ai-test")?.addEventListener("click", () => testAiSettings());
    $("ai-show-key")?.addEventListener("change", () => {
      const inp = $("ai-api-key");
      if (inp) inp.type = $("ai-show-key").checked ? "text" : "password";
    });
    ["ai-base-url", "ai-model", "ai-api-key"].forEach((id) => {
      $(id)?.addEventListener("input", () => {
        if ($(id)) $(id).dataset.dirty = "1";
      });
    });
    $("title-input").addEventListener("input", () => {
      state.title = $("title-input").value;
      if (!state.paperSlug) updateTitleUi();
    });

    const search = $("paper-search");
    if (search) {
      let t = null;
      search.addEventListener("input", () => {
        clearTimeout(t);
        t = setTimeout(() => {
          state.filter = search.value || "";
          renderPaperList();
        }, 120);
      });
    }

    $("btn-prev").addEventListener("click", async () => {
      await PdfViewer.prev();
      updatePageUi();
    });
    $("btn-next").addEventListener("click", async () => {
      await PdfViewer.next();
      updatePageUi();
    });
    $("page-input").addEventListener("change", async () => {
      await PdfViewer.goTo(Number($("page-input").value));
      updatePageUi();
    });
    $("btn-zoom-out").addEventListener("click", async () => {
      await PdfViewer.zoomBy(-0.15);
      updatePageUi();
    });
    $("btn-zoom-in").addEventListener("click", async () => {
      await PdfViewer.zoomBy(0.15);
      updatePageUi();
    });
    $("btn-rotate-cw")?.addEventListener("click", async () => {
      if (!PdfViewer.state.ready) {
        setStatus("请先打开 PDF", "warn");
        return;
      }
      RegionSelect.cancel();
      await PdfViewer.rotateBy(90);
      updatePageUi();
      setStatus(`页面已顺时针旋转 ${PdfViewer.state.rotation}°（仅影响当前查看与截图）`);
    });
    $("btn-rotate-ccw")?.addEventListener("click", async () => {
      if (!PdfViewer.state.ready) {
        setStatus("请先打开 PDF", "warn");
        return;
      }
      RegionSelect.cancel();
      await PdfViewer.rotateBy(-90);
      updatePageUi();
      setStatus(`页面已逆时针旋转，当前 ${PdfViewer.state.rotation}°（仅影响当前查看与截图）`);
    });
    $("btn-table-prev")?.addEventListener("click", () => jumpTableHit(-1));
    $("btn-table-next")?.addEventListener("click", () => jumpTableHit(1));
    $("table-hit-label")?.addEventListener("click", () => {
      if (!PdfViewer.state.ready) {
        setStatus("请先打开 PDF", "warn");
        return;
      }
      scanTablePages({ announce: true });
    });
    $("btn-select").addEventListener("click", toggleSelectMode);
    $("btn-capture").addEventListener("click", doCapture);
    $("btn-extract-batch")?.addEventListener("click", extractBatch);
    $("btn-extract-batch-side")?.addEventListener("click", extractBatch);
    $("btn-cancel-select").addEventListener("click", () => {
      RegionSelect.cancel();
      RegionSelect.setActive(false);
      $("btn-select").classList.remove("active");
      setStatus("已取消框选");
    });

    document.addEventListener("pdf:rendered", () => {
      updatePageUi();
    });

    document.addEventListener("keydown", (e) => {
      if (e.target && ["INPUT", "TEXTAREA"].includes(e.target.tagName)) return;
      if (e.key === "Escape") {
        RegionSelect.cancel();
        RegionSelect.setActive(false);
        $("btn-select").classList.remove("active");
      } else if (e.key === "ArrowLeft") {
        PdfViewer.prev().then(updatePageUi);
      } else if (e.key === "ArrowRight") {
        PdfViewer.next().then(updatePageUi);
      } else if (e.key === "r" || e.key === "R") {
        if (!PdfViewer.state.ready) return;
        RegionSelect.cancel();
        const delta = e.shiftKey ? -90 : 90;
        PdfViewer.rotateBy(delta).then(() => {
          updatePageUi();
          setStatus(`页面旋转 ${PdfViewer.state.rotation}°`);
        });
      } else if (e.key === "t" || e.key === "T") {
        if (!PdfViewer.state.ready) return;
        e.preventDefault();
        jumpTableHit(e.shiftKey ? -1 : 1);
      }
    });
  }

  async function init() {
    bindUi();
    try {
      await loadConfig();
      await loadPapers();
    } catch (e) {
      setStatus(`初始化失败: ${e.message}`, "warn");
    }
  }

  document.addEventListener("DOMContentLoaded", init);
})();
