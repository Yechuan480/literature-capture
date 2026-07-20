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

2. **确认标题**  
   系统会尝试从元数据/首页/文件名识别，可手改后点 **确认标题**。  
   文件夹名会按标题生成安全 slug。

3. **找表（推荐）**  
   - 打开后自动扫描含 `table` / `tables` 的页面  
   - 工具栏 **‹表** / **表›**，或快捷键 `T` / `Shift+T`  
   - 匹配词在页面上 **黄色高亮**  
   - 点中间 `Table n/m` 可重新扫描  

4. **框选截取**  
   - **框选模式** → 拖拽矩形 → **确认截取**  
   - 可选勾选「使用 AI 视觉增强」  
   - 输出：`_captures/{slug}/{slug}-tableN.png|.csv|.xlsx`

5. **无表格**  
   整篇没有可截表格时点 **无表格**，列表会标注并沉底。

6. **删除文献**  
   侧栏 `×` 或标题栏 **删除文献**：删除 `pdfs/` 中 PDF 及对应 `_captures` 文件夹（不可恢复）。

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

1. 左侧为待校对队列（**已通过的不会出现**）  
2. 中间左右对比：原图 PNG | 提取表（可下 CSV/Excel）  
3. **通过**：该项移出队列；该篇全部通过后整篇不再进入队列  
4. **不通过**：可选策略重提后再核对  
   - 自动 / Tesseract / RapidOCR / AI / 组合策略  
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

**Table 扫描失败 / findPages is not a function**  
强制刷新：`Cmd+Shift+R`（Windows：`Ctrl+Shift+R`）。

**Table 0 / 无高亮**  
扫描版 PDF 常无文本层，需手动翻页框选。

**OCR 效果差**  
安装 Tesseract：`brew install tesseract tesseract-lang`；或在校对页换 RapidOCR / AI 重提。

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
        ├── meta.json     # 标题、计数、校对状态
        └── {slug}-tableN.png / .csv / .xlsx
```
