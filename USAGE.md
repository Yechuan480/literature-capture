# 使用说明

面向日常截取与校对的操作手册。安装与目录约定见 [README.md](README.md)。

## 启动

```bash
cd literature-capture
source .venv/bin/activate
uvicorn app.main:app --reload --host 127.0.0.1 --port 8765
```

浏览器打开：http://127.0.0.1:8765

把 PDF 放进文献根目录下的 `pdfs/`（默认在应用上一级）。**不要**用 `file://` 打开 HTML。

---

## 主页：截取表格

1. **选文献**  
   左侧列表点选；可用搜索框按标题/文件名筛选。  
   排序：未处理 → 无表格 → 已截取。

2. **确认标题（可选）**  
   系统会尝试从元数据/首页/文件名识别，可手改后点 **确认标题**。  
   文件夹名会按标题生成安全 slug。  
   **打开文献时会自动建会话**，不必先确认标题也能获取 SI / 标记截图。

3. **补充材料 SI（自动）**  
   - 打开 PDF 后后台解析 DOI（元数据 / 首页 / 文件名）→ Crossref 开放链接 + **出版商页适配**（Elsevier CDN 探测、Springer/Nature HTML、Wiley/ACS 尽力）→ 过滤 SI/表格附件并下载到 `_captures/{slug}/si/`  
   - **不会下载主文 PDF**；401/403/登录页记为付费墙失败，不绕过、不打验证码  
   - 标题栏可填 **DOI 或文章页 URL**，点 **获取 SI**（或 Enter）强制重试  
   - 徽章：`已下载` / `部分成功` / `失败` / `付费墙` / `无开放 SI`；右侧列表可点开已下文件  
   - 侧栏文献旁显示 `SI` / `SIn` 小标记  
   - 配置：`config.yaml` → `si.enabled` / `si.auto_on_open`；关闭后不联网  
   - 说明：部分 Wiley/ACS 站点对脚本返回 403，此类只能手填 SI 直链

4. **Table 词跳转（辅助）**  
   - 打开后自动扫描含 `table` / `tables` 的页面  
   - 工具栏 **‹表** / **表›**，或快捷键 `T` / `Shift+T`  
   - 匹配词在页面上 **黄色高亮**  
   - 点中间 `Table n/m` 可重新扫描  

5. **框选截取（仅保存）**  
   - **框选模式** 手动拖拽表格区域 → **确认截取**  
   - **此时不跑 OCR**：只写入 `{slug}-tableN.png` 并记入「本篇已标记」  
   - 可连续标记多页多处，右侧显示本篇 `n/m 待提取`

6. **批量提取**  
   - 可跨多篇连续标记：每确认截取一次，**全局待提取**计数累加（切换文献不会清零）  
   - 本篇或全部标完后，点工具栏或右侧 **提取表格 (N)** → 对**所有文献**的未提取截图依次识别  
   - 默认优先 **PP-TableMagic**，失败回退 Tesseract / RapidOCR；可选「提取时使用 AI 视觉增强」  
   - 输出：`_captures/{slug}/{slug}-tableN.csv|.xlsx`（PNG 已存在）  
   - 列表单项也可点 **提取** / **重新提取**（仅当前篇）  
   - 侧栏徽章 `count/pending` 表示该篇已标记数 / 仍待提取数

7. **无表格**  
   整篇没有可截表格时点 **无表格**，列表会标注并沉底。

8. **删除文献**  
   侧栏 `×` 或标题栏 **删除文献**：删除 `pdfs/` 中 PDF 及对应 `_captures` 文件夹（不可恢复，含 `si/`）。

### 快捷键

| 键 | 作用 |
|----|------|
| `←` / `→` | 上一页 / 下一页 |
| `T` / `Shift+T` | 下一 / 上一 Table 页 |
| `R` / `Shift+R` | 顺时针 / 逆时针旋转 90° |
| `Esc` | 取消框选 |

---

## 校对页：`/review`

入口：主页「→ 进入表格校对」或直接访问 http://127.0.0.1:8765/review

1. 左侧为待校对队列（**已通过的不会出现**；**尚未批量提取的截图也不会入队**）  
2. 中间左右对比：原图 PNG | 提取表（可下 CSV/Excel）  
3. **通过**：该项移出队列；该篇全部通过后整篇不再进入队列  
4. **不通过**：可选策略重提后再核对  
   - 自动 / **PP-TableMagic** / Tesseract / RapidOCR / AI / 组合策略  
5. **跳过**：先处理其他项  

### 快捷键

| 键 | 作用 |
|----|------|
| `Y` / `1` | 通过 |
| `N` / `2` | 不通过 |
| `S` | 跳过 |
| `R` | 按当前策略重新提取 |

---

## AI 设置（可选）

1. 主页右侧 **AI 设置**  
2. 启用 AI 视觉，填写 Base URL、Model、API Key（OpenAI 兼容）  
3. **保存**，可用 **测试连接**  
4. Key 仅存本机 `data/ai_settings.json`，**不会**进 Git  

环境变量种子（可选）：

```bash
export LITERATURE_AI_API_KEY=sk-...
export LITERATURE_AI_ENABLED=true
```

---

## 常见问题

**批量提取 / Paddle 不可用**  
确认已 `pip install paddlepaddle 'paddlex[ocr]'`，`config.yaml` 中 `paddle.enabled: true`，内存充足。首次会下载模型，可设 `PADDLE_PDX_MODEL_SOURCE=BOS`。健康检查：`GET /api/health`。无 Paddle 时会回退 Tesseract / RapidOCR。

**Table 扫描失败 / findPages is not a function**  
强制刷新：`Cmd+Shift+R`（Windows：`Ctrl+Shift+R`）。

**Table 0 / 无高亮**  
扫描版 PDF 常无文本层，需手动翻页框选。

**OCR 效果差**  
安装 Tesseract：`brew install tesseract tesseract-lang`；或在校对页换 RapidOCR / AI 重提。

**SI 一直失败 / 无开放 SI**  
确认 PDF 含 DOI，或手填 DOI/文章页 URL 后点「获取 SI」。付费墙文章只能记录失败，不会绕过。可在 `config.yaml` 填写 `si.crossref_mailto` 加入 Crossref 礼貌池。

**列表里有重复文献**  
用删除按钮去掉多余 PDF；截取结果会一并清理。

**自定义文献目录**

```bash
export LITERATURE_ROOT="/path/to/your/library"
# 或改 config.yaml 的 literature_root / pdfs_subdir
```

---

## 输出位置

```
$LITERATURE_ROOT/
├── pdfs/                 # 你的 PDF（不进仓库）
└── _captures/
    └── {paper_slug}/
        ├── meta.json     # 标题、DOI、SI 状态、计数、校对状态
        ├── si/           # 自动下载的补充材料
        └── {slug}-tableN.png / .csv / .xlsx
```
