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
    try {
      const updated = await api(
        `/api/library/items/${encodeURIComponent(it.filename)}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status, tags, notes }),
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
  }

  document.addEventListener("DOMContentLoaded", () => {
    init().catch((e) => {
      $("item-tbody").innerHTML = `<tr><td colspan="5" style="color:var(--danger);padding:1rem">${e.message}</td></tr>`;
    });
  });
})();
