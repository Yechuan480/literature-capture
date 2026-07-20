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

  function clearViewer() {
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
    updateTitleUi();
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
      if (count > 0) {
        badge.classList.add("done");
        badge.title = `已截取 ${count} 张表格`;
        badge.innerHTML = `<span class="check">✓</span><span class="count">${count}</span>`;
      } else if (p.no_tables) {
        badge.classList.add("none");
        badge.title = "已标记：无表格";
        badge.textContent = "无表格";
      } else {
        badge.classList.add("empty-badge");
        badge.title = "尚未处理";
        badge.textContent = "";
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
    if (typeof absoluteCount === "number") {
      patch.capture_count = absoluteCount;
    } else {
      const p = state.papers.find((x) => x.filename === filename);
      patch.capture_count = (Number(p?.capture_count) || 0) + 1;
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
    el.innerHTML = [
      `PNG: ${result.paths.png}`,
      `CSV: ${result.paths.csv}`,
      `XLSX: ${result.paths.xlsx}`,
    ].join("<br>");
  }

  function renderCaptures(items) {
    const ul = $("capture-list");
    ul.innerHTML = "";
    if (!items || !items.length) {
      ul.innerHTML = `<li class="empty">本篇尚无截图</li>`;
      return;
    }
    for (const c of items) {
      const li = document.createElement("li");
      li.innerHTML = `
        <div class="cap-title"></div>
        <div class="cap-meta"></div>
        <div class="cap-actions">
          <button type="button" data-act="reextract">重新提取</button>
        </div>`;
      li.querySelector(".cap-title").textContent = c.stem || `table${c.table_id}`;
      li.querySelector(".cap-meta").textContent = [
        c.png_name,
        c.csv_name,
        c.xlsx_name,
      ]
        .filter(Boolean)
        .join(" · ");
      li.querySelector('[data-act="reextract"]').addEventListener("click", () =>
        reextract(c.table_id)
      );
      ul.appendChild(li);
    }
  }

  async function loadConfig() {
    state.config = await api("/api/config");
    const ocr = state.config.ocr || {};
    $("ocr-badge").textContent = `OCR: ${ocr.engine || "?"}`;
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
        ? "截取时在本地 OCR 后调用视觉模型增强"
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
    const q = (state.filter || "").trim();
    setStatus(
      q
        ? `已加载 ${state.papers.length} 篇 · 筛选「${q}」`
        : `已加载 ${state.papers.length} 篇 PDF`
    );
  }

  async function openPaper(filename) {
    try {
      showLoading(true, "加载 PDF…");
      state.filename = filename;
      state.paperSlug = null;
      state.folder = null;
      state.noTables = false;
      state.lastResult = null;
      state.tableHits = [];
      state.tableHitIndex = -1;
      state.tableScanToken += 1;
      state.tableScanning = false;
      updateTableNavUi();
      const known = state.papers.find((p) => p.filename === filename);
      if (known) {
        state.noTables = !!known.no_tables;
        state.paperSlug = known.paper_slug || null;
        if (known.title) state.title = known.title;
      }
      renderPaperList();
      renderPreview(null);
      renderPaths(null);
      renderCaptures([]);

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
      // Non-blocking scan for table pages after first paint
      scanTablePages({ announce: true }).catch(() => {});
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
      showLoading(true, "截取并提取表格…");
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
      fd.append("use_ai", $("ai-toggle").checked ? "true" : "false");

      const result = await api("/api/capture", { method: "POST", body: fd });
      state.lastResult = result;
      state.paperSlug = result.paper_slug;
      state.folder = result.folder;
      state.noTables = false;
      updateTitleUi();
      renderPreview(result.preview);
      renderPaths(result);
      await refreshCaptures();
      bumpPaperCaptureCount(state.filename, result.table_id);

      const warn =
        result.warnings && result.warnings.length
          ? ` · 警告: ${result.warnings.join("; ")}`
          : "";
      setStatus(
        `已保存 table${result.table_id}（${result.engine}，${result.rows}×${result.cols}）${warn}`,
        result.warnings?.length ? "warn" : "ok"
      );
    } catch (e) {
      setStatus(`截取失败: ${e.message}`, "warn");
    } finally {
      showLoading(false);
    }
  }

  async function reextract(tableId) {
    if (!state.paperSlug) return;
    try {
      showLoading(true, "重新提取…");
      const useAi = $("ai-toggle").checked;
      const result = await api(
        `/api/capture/${encodeURIComponent(state.paperSlug)}/${tableId}/reextract?use_ai=${useAi}`,
        { method: "POST" }
      );
      state.lastResult = result;
      renderPreview(result.preview);
      renderPaths(result);
      if (result.captures) renderCaptures(result.captures);
      else await refreshCaptures();
      setStatus(`已重新提取 table${tableId}（${result.engine}）`, "ok");
    } catch (e) {
      setStatus(`重提取失败: ${e.message}`, "warn");
    } finally {
      showLoading(false);
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
    $("btn-cancel-select").addEventListener("click", () => {
      RegionSelect.cancel();
      RegionSelect.setActive(false);
      $("btn-select").classList.remove("active");
      setStatus("已取消框选");
    });

    document.addEventListener("pdf:rendered", () => {
      RegionSelect.cancel();
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
