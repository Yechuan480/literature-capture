# Literature · 个人网页文献阅读器

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-lightgrey.svg)](#环境要求)

本地网页文献阅读器（Zotero 风格初版）：**文库** · **PDF 阅读/中译** · **表格截取/校对** · **悬浮 AI** · **Google 学术邮件 → 今日待读（OA 下载）**。

> **本仓库只包含应用代码，不包含任何 PDF 文献或截取结果。**  
> 请将自己的 PDF 放在 `pdfs/` 目录（默认位于应用上一级的文献根目录下）。

---

## 功能概览

| 模块 | 说明 |
|------|------|
| **文库** | `/` 集合 + 文献列表 + 阅读状态 / 标签 / 笔记（`data/library.json`） |
| **阅读** | `/read?f=` PDF.js 翻页缩放旋转；可标在读/已读，跳转截取 |
| **PDF 翻译** | 框选区域 → 文本/视觉机译 zh-CN；全文任务 → `*.zh-CN.pdf`（reflow） |
| **表格截取** | `/capture` 框选 PNG → 批量提取 CSV/Excel；SI 开放附件 |
| **表格校对** | `/review` PNG 与表对比，通过/不通过，多策略重提 |
| **设置** | `/settings` AI Key + IMAP 学术邮件（`data/*_settings.json`） |
| **今日待读** | 文库「今日待读」：Scholar Alert → 多选保留 → OA PDF 入库（不绕过付费墙） |
| **悬浮 AI 助手** | 右下角悬浮球；全站可用，结合当前 PDF 上下文；历史存 `data/chat/` |
| 标题识别 | PDF 元数据 → 首页正文 → 文件名 |
| **补充材料 SI** | DOI → Crossref / 出版商启发式 → `_captures/{slug}/si/`（不绕过付费墙） |
| 主导航 | 文库 · 阅读 · 截取 · 校对 · 设置 |

---

## 环境要求

- macOS / Linux
- Python 3.10–3.12（推荐）
- （推荐）[Tesseract OCR](https://github.com/tesseract-ocr/tesseract) — img2table 结构识别
- （推荐）AI 视觉：OpenAI 兼容接口（网页「AI 设置」填写 Key）

```bash
# macOS
brew install tesseract tesseract-lang
```

本地提取默认引擎：`img2table + Tesseract` → 失败回退 `RapidOCR`；勾选 AI 时走视觉模型。  
Paddle/PaddleX **已从默认依赖与提取路径移除**（体积大）；如需旧版页面表格检测，可自行 `pip install paddlepaddle paddlex[ocr]` 并设 `paddle.enabled: true`。

内存建议 ≥ 4GB（AI 视觉另计 API 用量）。

---

## 快速开始

```bash
git clone https://github.com/Yechuan480/literature-capture.git
cd literature-capture

python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 默认：文献根目录 = 应用上一级；PDF 放在 ../pdfs/
mkdir -p ../pdfs
# 把你的 PDF 放进 ../pdfs/ 后启动：

uvicorn app.main:app --reload --host 127.0.0.1 --port 8765
```

浏览器打开：**http://127.0.0.1:8765**（默认进入**文库**）

| 路径 | 页面 |
|------|------|
| `/` | 文库（今日待读） |
| `/read?f=xxx.pdf` | 阅读 + 框选/全文翻译 |
| `/capture?f=` | 表格截取 |
| `/review?slug=` | 表格校对 |
| `/settings` | AI + IMAP 设置 |

> 请勿用 `file://` 直接打开 HTML，必须通过上述服务访问。

### 目录约定

```
your-library/                    # 文献根目录（默认 = 应用父目录）
├── pdfs/                        # 放入 PDF（不会被本仓库跟踪）
│   └── *.pdf
├── _captures/                   # 输出（自动创建，不入库）
│   └── {paper_slug}/
│       ├── meta.json
│       ├── {paper_slug}-table1.png
│       ├── {paper_slug}-table1.csv
│       └── {paper_slug}-table1.xlsx
└── literature-capture/          # 本应用（本仓库）
    ├── app/
    ├── static/
    ├── config.yaml
    └── requirements.txt
```

自定义文献根目录：

```bash
export LITERATURE_ROOT="/path/to/your/library"
# 或编辑 config.yaml 中的 literature_root / pdfs_subdir
```

---

## 使用说明

更细的操作步骤见 **[USAGE.md](USAGE.md)**。


### 1. 截取表格（主页 `/`）

1. 将 PDF 放入 `pdfs/`，侧栏点击一篇文献  
2. 核对/编辑标题 → **确认标题**  
3. 若整篇无表格 → **无表格**（列表中标注并沉底）  
4. 用 **‹表 / 表›** / `T` 跳到含 `table` 字样的页（黄色高亮），或手动翻页  
5. **框选模式** 拖拽区域 → **确认截取**（**仅保存 PNG**，不即时提取）  
6. 可继续打开下一篇继续标记（**待提取计数跨文献累加**）  
7. 点工具栏或右侧 **提取表格 (N)** 对**全部**未提取截图批量识别 → 写入 CSV/XLSX  
8. 右侧「本篇已标记」可对单项 **提取** / **重新提取**  

其他快捷键：`Tab`/`Shift+Tab` 下/上一篇 · `←`/`→` 翻页 · `T`/`Shift+T` 跳 Table · `R`/`Shift+R` 旋转 · `Esc` 取消框选 

删除重复/不需要的文献：侧栏 `×` 或标题栏 **删除文献**（会同时删除对应截取文件夹）。

### 2. 校对提取结果（`/review`）

1. 主页链接进入 **表格校对**（仅**已提取**的表格会入队）  
2. 左侧筛选：**待办 / 未通过 / 待校对 / 已通过 / 全部**  
3. 左右对比 PNG 与提取表  
4. **通过** → 该项（及全篇全通过的文献）不再出现在默认待办队列  
5. **不通过** → 选择策略（AI 视觉 / img2table / RapidOCR / 组合）**重新提取**，回到待校对  

快捷键：`Y` 通过 · `N` 不通过 · `Tab`/`Shift+Tab` 下/上一项 · `S` 跳过 · `R` 重提  

### 3. 可选：AI 视觉增强

1. 主页右侧 **AI 设置**  
2. 勾选「启用 AI 视觉」，填写 Base URL、Model、API Key（OpenAI 兼容）  
3. **保存** / **测试连接**  
4. **批量/单项提取时**勾选「提取时使用 AI 视觉增强」，或在校对页选用含 AI 的重提策略  

Key 保存在本机 `literature-capture/data/ai_settings.json`（已 gitignore），也可通过环境变量：

```bash
export LITERATURE_AI_API_KEY=sk-...
export LITERATURE_AI_ENABLED=true
```

---

## API 摘要

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查与 OCR 状态 |
| GET | `/api/papers` | 列出 PDF（含 review 统计） |
| POST | `/api/papers/delete` | 删除 PDF 及截取结果 |
| GET | `/api/settings/ai` | 读取 AI 配置（Key 已掩码） |
| PUT | `/api/settings/ai` | 保存 AI 配置 |
| POST | `/api/settings/ai/test` | 测试 AI 连接 |
| GET | `/api/papers/title?filename=` | 识别标题 |
| POST | `/api/papers/session` | 确认标题 / 建文件夹 |
| GET | `/api/pdf/{filename}` | 获取 PDF |
| POST | `/api/capture` | 上传截图（**仅保存 PNG**，不提取） |
| GET | `/api/extract/pending` | 全局待提取队列（跨文献） |
| POST | `/api/extract/batch-all` | 批量提取**全部**未处理截图 |
| POST | `/api/capture/{slug}/extract-batch` | 批量提取**本篇**未提取截图 |
| POST | `/api/capture/{slug}/{id}/extract` | 提取单张截图 |
| POST | `/api/capture/{slug}/{id}/reextract` | 重新提取 |
| GET | `/api/review/queue?status=` | 校对队列（todo/pending/failed/passed/all） |
| POST | `/api/review/item/{slug}/{id}/verdict` | 通过 / 不通过 |
| POST | `/api/review/item/{slug}/{id}/reextract` | 重新提取 |
| GET | `/api/si/status?filename=` 或 `slug=` | SI 状态 / 文件列表 / job |
| POST | `/api/si/run` | 启动 SI 任务（body: filename, title?, doi?, url?, force?） |
| GET | `/api/si/file/{slug}/{name}` | 下载已保存的 SI 文件 |

`config.yaml` 中 `ocr.engine`：`auto` | `img2table_tesseract` | `rapidocr` | `ai`。  
SI：`si.enabled` / `si.auto_on_open`；环境变量 `LITERATURE_SI_ENABLED`、`LITERATURE_SI_AUTO_ON_OPEN`、`LITERATURE_SI_CROSSREF_MAILTO`。

---

## 技术栈

- **后端**：FastAPI + Uvicorn  
- **PDF**：PDF.js（前端）、pypdf / pdfplumber（标题）、pypdfium2（服务端栅格化）  
- **表格识别（默认）**：AI 视觉（可选）· img2table + Tesseract · RapidOCR  
- **SI 解析**：DOI 提取 + Crossref + 出版商适配器（Elsevier / Springer·Nature / Wiley / ACS / 通用落地页）+ httpx；不绕过付费墙 / 登录 / 验证码  
- **导出**：pandas + openpyxl  
- **AI（可选）**：OpenAI 兼容视觉 Chat Completions  

---

## 说明与限制

- 复杂合并单元格 / 跨页表可能识别不完美；PNG 始终保留便于人工校对  
- 标题中的特殊字符会在文件夹名中消毒，展示标题可保留原文  
- 扫描版 PDF 无文本层时，Table 页扫描与高亮可能不可用（需手动翻页框选）  
- 本工具面向本地科研工作流；请勿将含版权的 PDF 或 API Key 提交到公开仓库  

---

## 许可证

本项目以 [MIT License](LICENSE) 发布。  
Copyright (c) 2026 Yechuan480  

第三方依赖各自遵循其原许可证（Tesseract、PDF.js、img2table、RapidOCR 等）。

---

## 致谢

- [PDF.js](https://mozilla.github.io/pdf.js/)  
- [img2table](https://github.com/xavctn/img2table)  
- [RapidOCR](https://github.com/RapidAI/RapidOCR)  
- [Tesseract](https://github.com/tesseract-ocr/tesseract)  
- [FastAPI](https://fastapi.tiangolo.com/)  
