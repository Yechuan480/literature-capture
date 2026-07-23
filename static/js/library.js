/**
 * Library home: collections + items + detail panel.
 */
(function () {
  const state = {
    collections: [],
    items: [],
    total: 0,
    collectionId: "all",
    q: "",
    selected: null,
    todayItems: [],
    todayPending: 0,
    fetchPoll: null,
  };

  const ST_LABEL = {
    pending: "待处理",
    kept: "已保留",
    dismissed: "已忽略",
    fetching: "下载中",
    fetched: "已入库",
    paywalled: "付费墙",
    failed: "失败",
    no_pdf: "无 OA PDF",
  };

  const $ = (id) => document.getElementById(id);

  const STATUS_LABEL = {
    unread: "未读",
    reading: "在读",
    done: "已读",
    archived: "归档",
  };

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

  function collectionCounts(items) {
    const c = { all: items.length, unread: 0, reading: 0, done: 0, archived: 0 };
    for (const it of items) {
      const st = it.status || "unread";
      if (c[st] != null) c[st] += 1;
      for (const id of it.collection_ids || []) {
        c[id] = (c[id] || 0) + 1;
      }
    }
    return c;
  }

  function renderCollections() {
    const ul = $("col-list");
    ul.innerHTML = "";
    // For counts we need unfiltered totals — use last full fetch when collection is "all"
    // Approximate: count from current items only when filtered by search; ok for v1
    const counts = collectionCounts(state._allItems || state.items);

    const cols = state.collections || [];
    for (const col of cols) {
      const li = document.createElement("li");
      if (col.id === state.collectionId) li.classList.add("active");
      const name = document.createElement("span");
      name.textContent = col.name || col.id;
      const cnt = document.createElement("span");
      cnt.className = "col-count";
      const n =
        col.id === "all"
          ? counts.all
          : counts[col.id] != null
            ? counts[col.id]
            : 0;
      cnt.textContent = String(n);
      li.appendChild(name);
      li.appendChild(cnt);
      li.addEventListener("click", () => {
        if (state.collectionId === col.id) return;
        state.collectionId = col.id;
        loadItems();
      });
      if (!col.builtin) {
        li.title = "双击删除自定义集合";
        li.addEventListener("dblclick", async (e) => {
          e.stopPropagation();
          if (!confirm(`删除集合「${col.name}」？`)) return;
          try {
            await api(`/api/library/collections/${encodeURIComponent(col.id)}`, {
              method: "DELETE",
            });
            if (state.collectionId === col.id) state.collectionId = "all";
            await loadItems();
          } catch (err) {
            alert(err.message);
          }
        });
      }
      ul.appendChild(li);
    }
  }

  function renderItems() {
    const tbody = $("item-tbody");
    tbody.innerHTML = "";
    $("lib-count").textContent = `${state.total} 篇`;
    if (window.ShellNav) ShellNav.setMeta(`${state.total} 篇文献`);

    if (!state.items.length) {
      tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;color:var(--muted);padding:2rem">暂无文献（将 PDF 放入 pdfs/ 后点同步）</td></tr>`;
      return;
    }

    for (const it of state.items) {
      const tr = document.createElement("tr");
      if (state.selected && state.selected.filename === it.filename) {
        tr.classList.add("active");
      }
      const st = it.status || "unread";
      tr.innerHTML = `
        <td><span class="status-pill ${st}"></span></td>
        <td class="title-cell"></td>
        <td class="meta-cell"></td>
        <td class="meta-cell"></td>
        <td class="file-cell"></td>`;
      tr.querySelector(".status-pill").textContent = STATUS_LABEL[st] || st;
      tr.querySelector(".title-cell").textContent =
        it.title || it.filename.replace(/\.pdf$/i, "");
      const cap = it.capture_count || 0;
      const pend = it.pending_extract || 0;
      tr.children[2].textContent = cap
        ? `${cap} 表${pend ? ` · 待提 ${pend}` : ""}`
        : it.no_tables
          ? "无表"
          : "—";
      const rp = it.review_passed || 0;
      const rf = it.review_failed || 0;
      const rpe = it.review_pending || 0;
      tr.children[3].textContent =
        rp + rf + rpe > 0 ? `✓${rp} ✗${rf} ·${rpe}` : "—";
      tr.children[4].textContent = it.filename;
      tr.addEventListener("click", () => selectItem(it));
      tr.addEventListener("dblclick", () => openReader(it.filename));
      tbody.appendChild(tr);
    }
  }

  function selectItem(it) {
    state.selected = it;
    renderItems();
    renderDetail();
  }

  function openReader(filename) {
    const q = new URLSearchParams({ f: filename });
    window.location.href = `/read?${q.toString()}`;
  }

  function openCapture(filename) {
    const q = new URLSearchParams({ f: filename });
    window.location.href = `/capture?${q.toString()}`;
  }

  function renderDetail() {
    const body = $("detail-body");
    const it = state.selected;
    if (!it) {
      body.innerHTML = `<div class="empty">选择一篇文献</div>`;
      return;
    }
    const title = it.title || it.filename.replace(/\.pdf$/i, "");
    const customCols = (state.collections || []).filter((c) => !c.builtin);
    const colChecks = customCols
      .map((c) => {
        const checked = (it.collection_ids || []).includes(c.id) ? "checked" : "";
        return `<label class="col-check"><input type="checkbox" class="d-col" value="${c.id}" ${checked}/> ${c.name}</label>`;
      })
      .join("");
    body.innerHTML = `
      <div class="detail-title"></div>
      <div class="detail-file"></div>
      <div class="detail-stats"></div>
      <div class="detail-field">
        <label>阅读状态</label>
        <select id="d-status">
          <option value="unread">未读</option>
          <option value="reading">在读</option>
          <option value="done">已读</option>
          <option value="archived">归档</option>
        </select>
      </div>
      <div class="detail-field">
        <label>自定义集合</label>
        <div class="col-check-list" id="d-cols">${colChecks || '<span class="hint">暂无（左侧新建）</span>'}</div>
      </div>
      <div class="detail-field">
        <label>标签（逗号分隔）</label>
        <input type="text" id="d-tags" spellcheck="false" />
      </div>
      <div class="detail-field">
        <label>笔记</label>
        <textarea id="d-notes"></textarea>
      </div>
      <div class="detail-actions">
        <button type="button" class="primary" id="d-open">打开阅读</button>
        <button type="button" id="d-capture">表格截取</button>
        <a id="d-review" href="/review">校对</a>
        <button type="button" id="d-save">保存</button>
      </div>`;
    body.querySelector(".detail-title").textContent = title;
    body.querySelector(".detail-file").textContent = it.filename;
    const stats = body.querySelector(".detail-stats");
    const badges = [];
    if (it.doi) badges.push(`DOI ${it.doi}`);
    if (it.paper_slug) badges.push(`slug ${it.paper_slug}`);
    if (it.si_status) badges.push(`SI ${it.si_status}`);
    if (it.translated_pdf) badges.push("有译稿");
    badges.push(`${Math.round((it.size || 0) / 1024)} KB`);
    for (const b of badges) {
      const span = document.createElement("span");
      span.className = "badge";
      span.textContent = b;
      stats.appendChild(span);
    }
    $("d-status").value = it.status || "unread";
    $("d-tags").value = (it.tags || []).join(", ");
    $("d-notes").value = it.notes || "";
    $("d-open").addEventListener("click", () => openReader(it.filename));
    $("d-capture").addEventListener("click", () => openCapture(it.filename));
    const rev = $("d-review");
    if (it.paper_slug) {
      rev.href = `/review?slug=${encodeURIComponent(it.paper_slug)}`;
    } else {
      rev.href = "/review";
    }
    $("d-save").addEventListener("click", () => saveDetail());
  }

  async function saveDetail() {
    const it = state.selected;
    if (!it) return;
    const status = $("d-status").value;
    const tags = $("d-tags")
      .value.split(/[,，]/)
      .map((s) => s.trim())
      .filter(Boolean);
    const notes = $("d-notes").value;
    const collection_ids = Array.from(
      document.querySelectorAll("#d-cols .d-col:checked")
    ).map((el) => el.value);
    try {
      const updated = await api(
        `/api/library/items/${encodeURIComponent(it.filename)}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status, tags, notes, collection_ids }),
        }
      );
      state.selected = updated;
      // refresh list item
      const idx = state.items.findIndex((x) => x.filename === updated.filename);
      if (idx >= 0) state.items[idx] = updated;
      if (state._allItems) {
        const j = state._allItems.findIndex((x) => x.filename === updated.filename);
        if (j >= 0) state._allItems[j] = updated;
      }
      renderCollections();
      renderItems();
      renderDetail();
    } catch (e) {
      alert(e.message);
    }
  }

  async function loadItems() {
    const params = new URLSearchParams();
    if (state.q) params.set("q", state.q);
    if (state.collectionId && state.collectionId !== "all") {
      params.set("collection_id", state.collectionId);
    }
    params.set("sync", "true");
    const data = await api(`/api/library/items?${params.toString()}`);
    state.collections = data.collections || [];
    state.items = data.items || [];
    state.total = data.total || state.items.length;
    // Keep a full snapshot for collection counts when not searching
    if (!state.q && state.collectionId === "all") {
      state._allItems = state.items.slice();
    }
    // If filtered, still refresh collections list definitions
    renderCollections();
    renderItems();
    if (state.selected) {
      const still = state.items.find((x) => x.filename === state.selected.filename);
      state.selected = still || null;
      renderDetail();
    }
  }

  function setTodayBadge(n) {
    state.todayPending = n || 0;
    const b = $("today-badge");
    if (!b) return;
    if (n > 0) {
      b.hidden = false;
      b.textContent = String(n);
    } else {
      b.hidden = true;
    }
  }

  function setTodayStatus(text) {
    const el = $("today-status");
    if (el) el.textContent = text || "";
  }

  function renderTodayList() {
    const root = $("today-list");
    if (!root) return;
    const items = state.todayItems || [];
    if (!items.length) {
      root.innerHTML = `<div class="empty" style="color:var(--muted);padding:1.2rem;text-align:center">暂无条目。请先在设置中配置 IMAP，再点「刷新邮件」。</div>`;
      return;
    }
    root.innerHTML = "";
    for (const it of items) {
      const row = document.createElement("label");
      row.className = "today-item";
      const st = it.status || "pending";
      const canCheck = st === "pending" || st === "kept" || st === "failed" || st === "no_pdf" || st === "paywalled";
      row.innerHTML = `
        <input type="checkbox" class="t-check" ${canCheck ? "" : "disabled"} />
        <div>
          <div class="t-title"></div>
          <div class="t-meta"></div>
          <span class="t-status ${st}"></span>
        </div>`;
      row.querySelector(".t-check").value = it.id;
      row.querySelector(".t-title").textContent = it.title || "（无标题）";
      const metaBits = [];
      if (it.authors) metaBits.push(it.authors);
      if (it.doi) metaBits.push(it.doi);
      if (it.filename) metaBits.push(it.filename);
      if (it.error) metaBits.push(it.error);
      row.querySelector(".t-meta").textContent = metaBits.join(" · ") || it.link || "";
      row.querySelector(".t-status").textContent = ST_LABEL[st] || st;
      root.appendChild(row);
    }
  }

  async function loadToday(opts) {
    opts = opts || {};
    try {
      let inbox;
      if (opts.refresh) {
        inbox = await api("/api/scholar/inbox/refresh", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ force: !!opts.force, days: 2 }),
        });
      } else {
        inbox = await api("/api/scholar/inbox/today");
      }
      state.todayItems = inbox.items || [];
      setTodayBadge(inbox.pending_count || 0);
      renderTodayList();
      const lead = $("today-lead");
      if (lead) {
        lead.textContent = inbox.email_ready
          ? `共 ${state.todayItems.length} 条 · 待处理 ${inbox.pending_count || 0}` +
            (inbox.refreshed_at ? ` · 刷新于 ${inbox.refreshed_at}` : "")
          : "邮箱未就绪：请到「设置」填写 IMAP 与应用专用密码。";
      }
      return inbox;
    } catch (e) {
      setTodayStatus(e.message);
      throw e;
    }
  }

  function selectedTodayIds() {
    return Array.from(document.querySelectorAll("#today-list .t-check:checked"))
      .map((el) => el.value)
      .filter(Boolean);
  }

  function openTodayModal() {
    const m = $("today-modal");
    if (m) m.hidden = false;
    loadToday().catch(() => renderTodayList());
  }

  function closeTodayModal() {
    const m = $("today-modal");
    if (m) m.hidden = true;
    if (state.fetchPoll) {
      clearTimeout(state.fetchPoll);
      state.fetchPoll = null;
    }
  }

  function pollFetchJob(jobId) {
    if (state.fetchPoll) clearTimeout(state.fetchPoll);
    const tick = async () => {
      try {
        const j = await api(`/api/scholar/inbox/fetch-jobs/${encodeURIComponent(jobId)}`);
        setTodayStatus(
          `下载 ${j.done || 0}/${j.total || 0}` +
            (j.status === "done" ? " · 完成" : "…")
        );
        if (j.status === "done") {
          await loadToday();
          await loadItems();
          return;
        }
        state.fetchPoll = setTimeout(tick, 1200);
      } catch (e) {
        setTodayStatus(e.message);
      }
    };
    state.fetchPoll = setTimeout(tick, 600);
  }

  function bind() {
    let t = null;
    $("lib-search").addEventListener("input", () => {
      clearTimeout(t);
      t = setTimeout(() => {
        state.q = $("lib-search").value.trim();
        loadItems().catch((e) => alert(e.message));
      }, 220);
    });
    $("btn-sync").addEventListener("click", async () => {
      try {
        await api("/api/library/sync", { method: "POST" });
        await loadItems();
      } catch (e) {
        alert(e.message);
      }
    });
    $("btn-add-col").addEventListener("click", async () => {
      const name = $("new-col-name").value.trim();
      if (!name) return;
      try {
        await api("/api/library/collections", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name }),
        });
        $("new-col-name").value = "";
        await loadItems();
      } catch (e) {
        alert(e.message);
      }
    });
    $("new-col-name").addEventListener("keydown", (e) => {
      if (e.key === "Enter") $("btn-add-col").click();
    });

    $("btn-today").addEventListener("click", () => openTodayModal());
    $("btn-today-close").addEventListener("click", () => closeTodayModal());
    $("today-modal").addEventListener("click", (e) => {
      if (e.target === $("today-modal")) closeTodayModal();
    });
    $("btn-today-refresh").addEventListener("click", async () => {
      setTodayStatus("拉取邮件…");
      try {
        await loadToday({ refresh: true, force: true });
        setTodayStatus("已刷新");
      } catch (e) {
        setTodayStatus(e.message);
      }
    });
    $("btn-today-all").addEventListener("click", () => {
      document.querySelectorAll("#today-list .t-check:not(:disabled)").forEach((el) => {
        el.checked = true;
      });
    });
    $("btn-today-dismiss").addEventListener("click", async () => {
      const ids = selectedTodayIds();
      if (!ids.length) {
        setTodayStatus("请先勾选条目");
        return;
      }
      try {
        await api("/api/scholar/inbox/decide", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ids, action: "dismiss" }),
        });
        await loadToday();
        setTodayStatus(`已忽略 ${ids.length} 条`);
      } catch (e) {
        setTodayStatus(e.message);
      }
    });
    $("btn-today-keep").addEventListener("click", async () => {
      const ids = selectedTodayIds();
      if (!ids.length) {
        setTodayStatus("请先勾选条目");
        return;
      }
      try {
        setTodayStatus("提交下载…");
        const job = await api("/api/scholar/inbox/fetch-pdfs", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ids }),
        });
        await loadToday();
        if (job.job_id) pollFetchJob(job.job_id);
        else setTodayStatus(`已排队 ${job.queued || 0}`);
      } catch (e) {
        setTodayStatus(e.message);
      }
    });
  }

  async function init() {
    if (window.ShellNav) ShellNav.mount({ active: "library" });
    bind();
    // First load all for counts
    try {
      const all = await api("/api/library/items?sync=true");
      state._allItems = all.items || [];
      state.collections = all.collections || [];
    } catch (_) {
      /* continue */
    }
    await loadItems();
    // soft load today badge + auto-refresh once if empty and email ready
    try {
      let inbox = await loadToday();
      if (
        inbox.email_ready &&
        (!inbox.refreshed_at || !(inbox.items || []).length)
      ) {
        await loadToday({ refresh: true });
      }
    } catch (_) {
      /* optional */
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    init().catch((e) => {
      $("item-tbody").innerHTML = `<tr><td colspan="5" style="color:var(--danger);padding:1rem">${e.message}</td></tr>`;
    });
  });
})();
