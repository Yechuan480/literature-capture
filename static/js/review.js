/**
 * Review / QA: compare PNG vs extracted table, pass/fail, re-extract.
 */
(function () {
  const state = {
    stats: null,
    queue: [],
    current: null,
    loading: false,
  };

  const $ = (id) => document.getElementById(id);

  function toast(msg, kind) {
    const el = $("toast");
    if (!el) return;
    el.hidden = false;
    el.textContent = msg;
    el.className = "toast" + (kind ? ` ${kind}` : "");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => {
      el.hidden = true;
    }, 2600);
  }

  function showLoading(on, text) {
    const mask = $("loading-mask");
    if (!mask) return;
    mask.classList.toggle("show", !!on);
    mask.textContent = text || "处理中…";
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

  function renderStats(stats) {
    stats = stats || {};
    const remaining = (stats.pending || 0) + (stats.failed || 0);
    $("st-remaining").textContent = String(remaining);
    $("st-passed").textContent = String(stats.passed || 0);
    $("st-failed").textContent = String(stats.failed || 0);
    const papersDone = stats.papers_done || 0;
    const papers = stats.papers || 0;
    $("st-papers").textContent = papers ? `${papersDone}/${papers}` : "0";
  }

  function statusLabel(s) {
    if (s === "passed") return "已通过";
    if (s === "failed") return "未通过";
    return "待校对";
  }

  function renderQueue() {
    const ul = $("queue-list");
    ul.innerHTML = "";
    const q = state.queue || [];
    $("queue-hint").textContent = q.length
      ? `${q.length} 项待处理（已通过的不显示）`
      : "队列为空";
    if (!q.length) {
      ul.innerHTML = `<li class="empty">暂无待校对项</li>`;
      return;
    }
    for (const item of q) {
      const li = document.createElement("li");
      const st = item.review_status || "pending";
      if (st === "failed") li.classList.add("failed");
      if (
        state.current &&
        state.current.paper_slug === item.paper_slug &&
        Number(state.current.table_id) === Number(item.table_id)
      ) {
        li.classList.add("active");
      }
      li.innerHTML = `
        <div class="q-title"></div>
        <div class="q-meta">
          <span class="q-id"></span>
          <span class="tag"></span>
        </div>`;
      li.querySelector(".q-title").textContent =
        item.title || item.paper_slug || "—";
      li.querySelector(".q-id").textContent = `table${item.table_id}${
        item.page ? ` · p.${item.page}` : ""
      }`;
      const tag = li.querySelector(".tag");
      tag.textContent = statusLabel(st);
      tag.classList.add(st === "failed" ? "failed" : "pending");
      li.addEventListener("click", () => openItem(item.paper_slug, item.table_id));
      ul.appendChild(li);
    }
  }

  function renderTable(matrix) {
    const wrap = $("table-wrap");
    if (!matrix || !matrix.length) {
      wrap.innerHTML = `<div class="empty">无表格数据（CSV 为空）</div>`;
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
    const maxRows = 120;
    matrix.slice(0, maxRows).forEach((row) => {
      const tr = document.createElement("tr");
      for (let c = 0; c < maxCols; c++) {
        const td = document.createElement("td");
        td.textContent = row[c] ?? "";
        tr.appendChild(td);
      }
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    wrap.innerHTML = "";
    wrap.appendChild(table);
    if (matrix.length > maxRows) {
      const more = document.createElement("div");
      more.className = "empty";
      more.textContent = `仅显示前 ${maxRows} 行 · 完整数据见 CSV/Excel`;
      wrap.appendChild(more);
    }
  }

  function showEmpty(on) {
    $("empty-state").hidden = !on;
    $("review-work").hidden = on;
  }

  function renderCurrent(item) {
    state.current = item;
    if (!item) {
      showEmpty(true);
      renderQueue();
      return;
    }
    showEmpty(false);
    $("work-title").textContent = item.title || item.paper_slug;
    $("work-sub").textContent = [
      item.paper_slug,
      `table${item.table_id}`,
      item.page != null ? `page ${item.page}` : null,
      item.png_name,
    ]
      .filter(Boolean)
      .join(" · ");

    const st = item.review_status || "pending";
    const badge = $("badge-status");
    badge.textContent = statusLabel(st);
    badge.className = `badge status-${st}`;
    $("badge-engine").textContent = item.engine || "—";
    const rows = item.rows ?? (item.matrix ? item.matrix.length : "—");
    const cols =
      item.cols ??
      (item.matrix && item.matrix[0] ? item.matrix[0].length : "—");
    $("badge-size").textContent = `${rows}×${cols}`;

    const pngUrl = item.png_url || `/api/review/file/${encodeURIComponent(item.paper_slug)}/${item.table_id}/png`;
    const img = $("png-img");
    img.src = pngUrl + `?t=${Date.now()}`;
    $("png-open").href = pngUrl;
    $("csv-link").href =
      item.csv_url ||
      `/api/review/file/${encodeURIComponent(item.paper_slug)}/${item.table_id}/csv`;
    $("xlsx-link").href =
      item.xlsx_url ||
      `/api/review/file/${encodeURIComponent(item.paper_slug)}/${item.table_id}/xlsx`;

    renderTable(item.matrix || item.preview || []);

    const warns = item.warnings || [];
    const box = $("warn-box");
    if (warns.length) {
      box.hidden = false;
      box.textContent = "警告: " + warns.join(" · ");
    } else {
      box.hidden = true;
      box.textContent = "";
    }

    $("review-note").value = item.review_note || "";

    // Prefer AI strategy when available
    if (item.ai_ready === false) {
      const sel = $("strategy-select");
      [...sel.options].forEach((o) => {
        if (o.value.includes("ai") || o.value === "ai") {
          o.disabled = true;
        }
      });
      if (sel.value.includes("ai") || sel.value === "ai") {
        sel.value = "tesseract";
      }
      $("retry-hint").textContent =
        "AI 未配置：可在主页 AI 设置中填写 Key。当前可用本地策略重提。";
    } else {
      [...$("strategy-select").options].forEach((o) => {
        o.disabled = false;
      });
      $("retry-hint").textContent =
        "重新提取后状态回到「待校对」，会再次进入队列供你核对。";
    }

    renderQueue();
  }

  async function refreshQueue() {
    const data = await api("/api/review/queue");
    state.stats = data.stats;
    state.queue = data.queue || [];
    renderStats(data.stats);
    renderQueue();
    return data;
  }

  async function openItem(slug, tableId) {
    try {
      showLoading(true, "加载表格…");
      const item = await api(
        `/api/review/item/${encodeURIComponent(slug)}/${tableId}`
      );
      renderCurrent(item);
    } catch (e) {
      toast(e.message, "warn");
    } finally {
      showLoading(false);
    }
  }

  async function loadNext(after) {
    try {
      showLoading(true, "加载队列…");
      let url = "/api/review/next";
      if (after?.paper_slug != null && after?.table_id != null) {
        url += `?after_slug=${encodeURIComponent(after.paper_slug)}&after_table_id=${after.table_id}`;
      }
      const data = await api(url);
      state.stats = data.stats;
      renderStats(data.stats);
      await refreshQueue();
      if (!data.item) {
        renderCurrent(null);
        toast("全部校对完成 🎉", "ok");
      } else {
        renderCurrent(data.item);
      }
    } catch (e) {
      toast(e.message, "warn");
    } finally {
      showLoading(false);
    }
  }

  async function submitVerdict(status) {
    if (!state.current) return;
    const { paper_slug, table_id } = state.current;
    const note = $("review-note").value.trim();
    try {
      showLoading(true, status === "passed" ? "标记通过…" : "标记不通过…");
      const res = await api(
        `/api/review/item/${encodeURIComponent(paper_slug)}/${table_id}/verdict`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status, note }),
        }
      );
      state.stats = res.stats;
      renderStats(res.stats);
      await refreshQueue();

      if (status === "passed") {
        toast("已通过，进入下一项", "ok");
        if (res.next) {
          renderCurrent(res.next);
        } else {
          renderCurrent(null);
          toast("队列已空，全部完成", "ok");
        }
      } else if (status === "failed") {
        toast("已标为不通过，可选择策略重新提取", "warn");
        // Stay on item so user can reextract
        await openItem(paper_slug, table_id);
      } else {
        if (res.next) renderCurrent(res.next);
        else renderCurrent(null);
      }
    } catch (e) {
      toast(e.message, "warn");
    } finally {
      showLoading(false);
    }
  }

  async function doReextract() {
    if (!state.current) return;
    const { paper_slug, table_id } = state.current;
    const strategy = $("strategy-select").value || "auto";
    try {
      showLoading(true, `重新提取（${strategy}）…`);
      const item = await api(
        `/api/review/item/${encodeURIComponent(paper_slug)}/${table_id}/reextract?strategy=${encodeURIComponent(strategy)}`,
        { method: "POST" }
      );
      await refreshQueue();
      renderCurrent(item);
      toast(
        `已重提 table${table_id}（${item.engine || strategy}，${item.rows}×${item.cols}）· 请再次核对`,
        "ok"
      );
    } catch (e) {
      toast(e.message, "warn");
    } finally {
      showLoading(false);
    }
  }

  function bind() {
    $("btn-pass").addEventListener("click", () => submitVerdict("passed"));
    $("btn-fail").addEventListener("click", () => submitVerdict("failed"));
    $("btn-skip").addEventListener("click", async () => {
      if (!state.current) return;
      await loadNext(state.current);
    });
    $("btn-reextract").addEventListener("click", doReextract);

    document.addEventListener("keydown", (e) => {
      if (e.target && ["INPUT", "TEXTAREA", "SELECT"].includes(e.target.tagName))
        return;
      if (e.key === "y" || e.key === "Y" || e.key === "1") {
        submitVerdict("passed");
      } else if (e.key === "n" || e.key === "N" || e.key === "2") {
        submitVerdict("failed");
      } else if (e.key === "s" || e.key === "S") {
        if (state.current) loadNext(state.current);
      } else if (e.key === "r" || e.key === "R") {
        doReextract();
      }
    });
  }

  async function init() {
    bind();
    await loadNext();
  }

  document.addEventListener("DOMContentLoaded", () => {
    init().catch((e) => toast(e.message, "warn"));
  });
})();
