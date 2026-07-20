# 文献表格截取工具 (Literature Table Capture)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-lightgrey.svg)](#环境要求)

本地网页工具：打开文献 PDF → 识别/确认标题 → 框选表格截图 → 按文献分文件夹自动命名 → 提取表格为 **CSV + Excel**，并支持人工校对与 AI 视觉增强。

> **本仓库只包含应用代码，不包含任何 PDF 文献或截取结果。**  
> 请将自己的 PDF 放在 `pdfs/` 目录（默认位于应用上一级的文献根目录下）。

---

## 功能概览

| 模块 | 说明 |
|------|------|
| PDF 管理 | 扫描 `pdfs/`，侧栏检索/排序，删除文献 |
| 标题识别 | PDF 元数据 → 首页正文 → 文件名（可手动修改） |
| 预览与框选 | PDF.js 翻页 / 缩放 / 旋转；拖拽框选截图 |
| Table 导航 | 自动扫描 `table`/`tables` 所在页，快捷跳转并高亮标注 |
| 表格提取 | Tesseract + img2table（主）；RapidOCR（后备）；可选 AI 视觉 |
| 导出 | `{标题}-tableN.png` / `.csv` / `.xlsx`，每篇独立文件夹 |
| 校对队列 | 左右对比 PNG 与提取表，通过 / 不通过，多策略重提 |
| AI 设置 | 网页内填写 OpenAI 兼容接口（Key 仅存本机，不入库） |

---

## 环境要求

- macOS / Linux
- Python 3.10+
- （推荐）[Tesseract OCR](https://github.com/tesseract-ocr/tesseract)

```bash
# macOS
brew install tesseract tesseract-lang
```

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

浏览器打开：**http://127.0.0.1:8765**

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
4. 使用 **‹表 / 表›** 或快捷键 `T` / `Shift+T` 在含 `table` 的页面间跳转（黄色高亮）  
5. 点击 **框选模式**，拖拽矩形 → **确认截取**  
6. 右侧查看预览；文件写入 `_captures/{slug}/`  

其他快捷键：`←`/`→` 翻页 · `R`/`Shift+R` 旋转 · `Esc` 取消框选  

删除重复/不需要的文献：侧栏 `×` 或标题栏 **删除文献**（会同时删除对应截取文件夹）。

### 2. 校对提取结果（`/review`）

1. 主页链接进入 **表格校对**  
2. 左右对比 PNG 与提取表  
3. **通过** → 该项（及全篇全通过的文献）不再出现在队列  
4. **不通过** → 选择策略（Tesseract / RapidOCR / AI）**重新提取**，回到待校对  

快捷键：`Y` 通过 · `N` 不通过 · `S` 跳过 · `R` 重提  

### 3. 可选：AI 视觉增强

1. 主页右侧 **AI 设置**  
2. 勾选「启用 AI 视觉」，填写 Base URL、Model、API Key（OpenAI 兼容）  
3. **保存** / **测试连接**  
4. 截取时勾选「使用 AI 视觉增强」，或在校对页选用含 AI 的重提策略  

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
| GET | `/api/papers` | 列出 PDF |
| POST | `/api/papers/delete` | 删除 PDF 及截取结果 |
| GET | `/api/settings/ai` | 读取 AI 配置（Key 已掩码） |
| PUT | `/api/settings/ai` | 保存 AI 配置 |
| POST | `/api/settings/ai/test` | 测试 AI 连接 |
| GET | `/api/papers/title?filename=` | 识别标题 |
| POST | `/api/papers/session` | 确认标题 / 建文件夹 |
| GET | `/api/pdf/{filename}` | 获取 PDF |
| POST | `/api/capture` | 上传截图并提取 |
| GET | `/api/review/queue` | 校对队列 |
| POST | `/api/review/item/{slug}/{id}/verdict` | 通过 / 不通过 |
| POST | `/api/review/item/{slug}/{id}/reextract` | 重新提取 |

---

## 技术栈

- **后端**：FastAPI + Uvicorn  
- **PDF**：PDF.js（前端）、pypdf / pdfplumber（标题）  
- **表格 OCR**：img2table + Tesseract；RapidOCR 后备  
- **导出**：pandas + openpyxl  
- **AI（可选）**：OpenAI 兼容视觉 Chat Completions  

---

## 说明与限制

- 复杂合并单元格 / 跨页表可能识别不完美；PNG 始终保留便于人工校对  
- 标题中的特殊字符会在文件夹名中消毒，展示标题可保留原文  
- 扫描版 PDF 无文本层时，Table 页扫描与高亮可能不可用（仍可手动翻页框选）  
- 本工具面向本地科研工作流；请勿将含版权的 PDF 或 API Key 提交到公开仓库  

---

## 许可证

本项目以 [MIT License](LICENSE) 发布。  
Copyright (c) 2026 Yechuan480  

第三方依赖各自遵循其原许可证（Tesseract、PDF.js、img2table 等）。

---

## 致谢

- [PDF.js](https://mozilla.github.io/pdf.js/)  
- [img2table](https://github.com/xavctn/img2table)  
- [Tesseract](https://github.com/tesseract-ocr/tesseract)  
- [FastAPI](https://fastapi.tiangolo.com/)  
