# 使用说明

面向日常文库阅读、截取与校对的操作手册。安装与目录约定见 [README.md](README.md)。

## 启动

```bash
cd literature-capture
source .venv/bin/activate
uvicorn app.main:app --reload --host 127.0.0.1 --port 8765
```

浏览器打开：http://127.0.0.1:8765 （默认**文库**）

把 PDF 放进文献根目录下的 `pdfs/`（默认在应用上一级）。**不要**用 `file://` 打开 HTML。

顶栏：**文库 · 阅读 · 截取 · 校对 · 设置**。

---

## 文库 `/`

1. 左侧集合：全部 / 未读 / 在读 / 已读；可新建自定义集合（双击删除）。
2. 中间列表：搜索标题/文件名/标签/DOI；单击选中，**双击打开阅读**。
3. 右侧详情：改阅读状态、**自定义集合勾选**、标签、笔记 → **保存**；**打开阅读** / **表格截取** / 校对（带 `?slug=`）。
4. **同步**：重新扫描 `pdfs/` 并合并到 `data/library.json`（不入库、勿提交）。
5. **今日待读**：工具栏按钮（有待处理时显示数字角标）。见下节。

---

## 今日待读（Google 学术邮件）

1. **设置** → 启用邮箱 → 填写 IMAP（Gmail 默认 `imap.gmail.com:993`）与 **应用专用密码** → **测试 IMAP**。
2. 文库点 **今日待读** → **刷新邮件**，解析 Scholar Alert 中的条目。
3. 勾选感兴趣文献 → **保留并下载**：仅尝试开放获取 PDF（直链 / Unpaywall / 明显 `.pdf`）；付费墙记为失败，**不**走 Sci-Hub 或登录。
4. 成功的 PDF 进入 `pdfs/`，并加入集合「今日导入」；**忽略所选** 仅改状态。
5. 凭据存 `data/email_settings.json`，收件缓存 `data/scholar_inbox.json` — 均勿提交 Git。

---

## 阅读 `/read?f=文件名.pdf`

翻页 / 缩放 / 旋转；可标「在读」「已读」；**截取表格**跳到 `/capture?f=`。

### PDF 翻译

目标语言固定 **简体中文（zh-CN）**。界面为**左右对照**。工具栏可选引擎：**AI / Google / 百度 / CNKI**（默认在 **设置 → 翻译** 配置）。

1. **框选翻译**  
   - 先选引擎 → 点 **框选翻译** → 在页面上拖出区域 → **译选区**。  
   - 选区按当前页面旋转映射到 PDF 坐标后 crop（pdfplumber）；文字过少时可用选区截图走 **AI 视觉**（仅 AI 引擎）。  
   - 底部面板 **左原文 · 右译文**，可 **复制译文** / **关闭**；`Esc` 退出框选。

2. **全文翻译**  
   - 点 **全文翻译** 提交后台任务（按页提取 → 所选引擎机译 → 写入 reflow PDF）。  
   - 完成后出现 **对照译稿**：左右分栏同步翻页/缩放/旋转。  
   - 译稿文件名为 `{原名stem}.zh-CN.pdf`，与原文同目录（`pdfs/`）。  
   - 已有译稿时再次点击会直接复用；**Shift+全文翻译** 可强制重译。  
   - 扫描件无可提取文本时全文任务会失败；区域翻译可改用 AI 视觉。

3. **引擎说明**  
   - **AI**：OpenAI 兼容接口（设置中的 AI Key）；支持视觉回退。  
   - **Google**：非官方 gtx 端点，免密钥，可能限流。  
   - **百度**：开放平台通用翻译 API（App ID + 密钥，存 `data/translate_settings.json`）。  
   - **CNKI**：尽力调用公开接口；常需账号/token，失败时换其他引擎。

4. **注意**  
   - 译稿为简易 reflow，版式不等于原文。  
   - 不修改原 PDF；API 密钥与译稿路径勿提交 git。

---

## 截取表格 `/capture`

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
   - 默认 **img2table + Tesseract**，失败回退 RapidOCR；可选「提取时使用 AI 视觉增强」  
   - 输出：`_captures/{slug}/{slug}-tableN.csv|.xlsx`（PNG 已存在）  
   - 列表单项也可点 **提取** / **重新提取**（仅当前篇）  
   - 侧栏徽章 `count/pending` 表示该篇已标记数 / 仍待提取数
   - 侧栏筛选芯片：**全部 / 未通过 / 待校对 / 已通过 / 未提取 / 待办**

7. **无表格**  
   整篇没有可截表格时点 **无表格**，列表会标注并沉底。

8. **删除文献**  
   侧栏 `×` 或标题栏 **删除文献**：删除 `pdfs/` 中 PDF 及对应 `_captures` 文件夹（不可恢复，含 `si/`）。

### 快捷键

| 键 | 作用 |
|----|------|
| `Tab` / `Shift+Tab` | 下一篇 / 上一篇文献（按当前筛选） |
| `←` / `→` | 上一页 / 下一页 |
| `T` / `Shift+T` | 下一 / 上一 Table 页 |
| `R` / `Shift+R` | 顺时针 / 逆时针旋转 90° |
| `Esc` | 取消框选 |

---

## 校对页：`/review`

入口：主页「→ 进入表格校对」或直接访问 http://127.0.0.1:8765/review

1. 左侧为校对队列，可用芯片筛选：**待办 / 未通过 / 待校对 / 已通过 / 全部**  
2. 中间左右对比：原图 PNG | 提取表（可下 CSV/Excel）  
3. **通过**：该项移出默认待办队列；该篇全部通过后整篇不再进入待办  
4. **不通过**：可选策略重提后再核对  
   - AI 视觉 / 自动(img2table→RapidOCR) / Tesseract / RapidOCR / 组合策略  
5. **跳过**：先处理其他项  

### 快捷键

| 键 | 作用 |
|----|------|
| `Y` / `1` | 通过 |
| `N` / `2` | 不通过 |
| `Tab` / `Shift+Tab` | 下一项 / 上一项 |
| `S` | 跳过 |
| `R` | 按当前策略重新提取 |

---

## AI 设置（可选）

1. 顶栏进入 **设置**  
2. 启用 AI，填写 Base URL、Model、API Key（OpenAI 兼容）  
3. **保存**，可用 **测试连接**  
4. Key 仅存本机 `data/ai_settings.json`，**不会**进 Git  
5. 全站右下角 **悬浮助手**（Claude 风格头像，可拖动位置）依赖同一 Key  

环境变量种子（可选）：

```bash
export LITERATURE_AI_API_KEY=sk-...
export LITERATURE_AI_ENABLED=true
```

---

## 常见问题

**批量提取效果差 / 无 Tesseract**  
安装 Tesseract：`brew install tesseract tesseract-lang`。默认 `ocr.engine: auto` 优先 img2table+Tesseract，失败回退 RapidOCR。也可用「AI 视觉增强」。健康检查：`GET /api/health`。

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
