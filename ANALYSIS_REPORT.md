# SeavoExplorer 代码分析报告（历史资料，截至 v0.6.0）

> 分析对象当时为 0.5.4，修复随 v0.6.0 发布。现行行为以工作树代码、`README.md` 和 `打包指南.txt` 为准。下方 2026-08-31 缺陷清单已被文首「审查更正与修复状态」取代，不要当作 0.7.0 的现行问题列表。

- 分析对象：`SeavoExplorer` @ `d2b8857`（当时 `APP_VERSION = 0.5.4`；修复后发布版本为 0.6.0）
- 分析方式：源码通读 + 运行时实测（临时目录、回环 HTTP、子进程隔离）；2026-08-31 分析全程只读，2026-09-09 增补节包含修复与构建
- 报告生成日期：2026-08-31（2026-09-09 增补复审与修复状态）
- 未执行：GUI 端到端验证、远端发布；严格 venv 构建/冒烟/哈希已在 2026-09-09 增补节执行

> 本报告只描述事实与可复现的实测结果。所有"缺陷"均给出触发路径与实测数据；
> 所有"已验证正确"项同样给出实测数据，避免只报问题不报结论。

---

## 审查更正与修复状态（2026-09-09）

> 本节由新一轮复审补充，优先级高于下方 2026-08-31 的历史结论。
> 代码修复已随 v0.6.0 发布；下方测试构建哈希为提交前工作树产物，最终发布产物以 GitHub Release 为准。

### 结论更正

| 原结论 | 复审更正 |
| --- | --- |
| F1 只说"载入侧无校验"，修复建议是复用保存期校验 | **保存期启发式本身可被 `{m,n}` 绕过**：`^S(\d{1,2})+$` 会被设置对话框接受并持久化，扫描 36 字符目录名耗时 5.166s；灾难性回溯持有 GIL，主线程 Python 定时器/槽无法执行，`closeEvent` 的 `os._exit(0)` 兜底不可依赖。F1 仍为 P1，但触发条件从"手改配置"扩大为 **UI 可达**，修复不能只做载入侧复用。 |
| F2 建议"UTF-8 优先，双向严格更优" | **不成立**：1920 个 GBK 双字节序列同时是合法 UTF-8；常用汉字中 20/136 存在歧义（一、为、之、说、也、时、要、没、去、学、然、写、目、原、图、录、硬、模、协、准）。固定顺序只是权衡，因此改为 BOM + 乱码启发式。 |
| F3 定为 P2，称部分解压器会告警/覆盖 | 重复条目属实，但 Python `zipfile.testzip()` 返回 `None`、7-Zip `t` 退出码 0"Everything is Ok"；应降为 P3/P4 的产物质量问题。 |
| F4 称列表形态抛 `.items`、旧配置导致崩溃 | 部分字典不一致在真实构造路径下属实；列表形态实际抛 `'list' object has no attribute 'get'`；git 历史显示首个提交即为 dict，**没有"旧配置"证据**，只能算手改/损坏配置。 |
| F6 称 DirectConnection 与 closeEvent 快照构成竞态 | worker 线程执行属实，但 `list()`/`list.remove()` 受 GIL 保护，未发现实际故障；DirectConnection 还能在主事件循环阻塞时及时清理僵尸列表。保留实现并加注释，不按原建议改 AutoConnection。 |
| F7 称非本地 URL 吞掉内部缓存、Ctrl+V 失效 | 属于**设计选择**：系统剪贴板一旦带 URL 说明用户已替换剪贴板，继续用旧内部路径会粘贴错文件。保留行为并新增测试固定该语义。 |

### 本轮修复

- **P1 正则安全**：新增结构分析器，覆盖 `{m,n}` 量词、嵌套重复组、回溯引用；`_resolve_regex` 对自定义正则复用保存期校验并回退默认；`load_settings` 对无效自定义正则追加启动警告；条件组等无法安全分析的结构 fail-closed。
- **预览编码**：改为 BOM 识别 + UTF-8 优先 + GBK 乱码启发式；BOM 不再泄漏；大文件仍截断并有提示。
- **zip**：删除重复目录条目写入，产物不再出现 `Duplicate name`。
- **folder_structure**：新增 `_normalize_folder_structure`，载入与对话框统一归一化；部分字典、列表、非 dict、非法版本、非字符串自定义目录均安全处理。
- **失效根目录**：`FolderStatsThread`/`FileSearchThread` 在 root 不存在时发出 error 信号，不再静默显示 0。
- **old/ 守卫**：已在 `old/` 内或目录本身名为 `old` 的项目跳过归档，避免 `old/old` 嵌套。
- **文档与清理**：帮助章节重新编号；PDF 文案改为"预览前 3 页文本"；README 修正"至少 1 个捕获组"和 ReDoS 启发式表述；移除 `OpenWithDialog`、`_extract_with_7z`、`_fetch_latest_release`、`generate_video_thumbnails`、`_capture_video_frames`、未用 import/常量；合并 `_WINDOWS_RESERVED_NAMES` 重复定义。

### 新增回归测试

`test_safety.py` 新增 28 项（合计 104 项）：正则绕过与回退、编码启发式/BOM/截断、zip 无重复条目、folder_structure 归一化、失效根目录错误信号、old/ 守卫、剪贴板优先级语义、帮助编号/README 契约/保留名。

### 本轮验证

- `python -m unittest -q test_safety.py test_tooling.py` → **104 tests OK**
- `py_compile` 7 个模块 + Python 3.8 grammar AST → OK
- `git diff --check` → clean
- 严格 venv（Python 3.13.2 x64，`include-system-site-packages=false`）构建：
  - `dist/SeavoExplorer.exe`，**96,948,767 bytes / 92.46 MiB**
  - SHA-256：**F5D487EC3B58987665A3AF577044473B96A0E377EA31A228EA8666BC7F4ECBAE**
  - manifest：`strict_environment=true`、`path_sanitized=true`、`external_binary_count=0`，全部 8 项检查为 true（含隔离冒烟）
  - **`source.dirty=true`**：这是提交前工作树的测试构建，EXE SHA-256 为 `F5D487EC3B58987665A3AF577044473B96A0E377EA31A228EA8666BC7F4ECBAE`，仅用于本地验证，已被 clean 发布构建取代。
- **v0.6.0 正式发布（2026-09-09）**：
  - commit `29b3dab5960ef9efd55a5123294f19ca17b38e7f`，annotated tag `v0.6.0`（tag object `589e35669d47f4b974160cb474def7d22f3b4228`）
  - clean 发布构建：`dist/SeavoExplorer.exe` **96,948,502 bytes**，SHA-256 **44E769B707F6DDEB144B5994BF7674AE33FA9E64317243125387F615291A75D2**
  - manifest `source.dirty=false`、`strict_environment=true`、`path_sanitized=true`、`external_binary_count=0`，全部 8 项检查为 true
  - GitHub Release：https://github.com/FengBujue0104/SeavoExplorer/releases/tag/v0.6.0
  - 远端三资产（EXE、`.sha256`、`.build.json`）digest 已核对；独立下载 EXE 复核哈希一致。

### 0.6.1 补充（2026-09-09）

- 新增自签名构建管线：`SEAVO_SIGN_MODE=store|pfx`、manifest `code_signing`、`SEAVO_REQUIRE_SIGNING=1` 发布门禁。
- 新增同 EXE 更新模式：`--apply-update` 等待旧 PID 退出，用 `ReplaceFileW` 替换并保留 `.old` 备份，主程序提供“下载并更新”入口。
- 测试增至 117 项；当前发布使用自签名证书，Windows SmartScreen 仍可能提示“未知发布者”。
- v0.6.1 发布：tag `v0.6.1`（tag object `a7929378bebcd0061e4208ec3eab5799f45c8e72`）指向 `4b47e2d18673e7c1de1cffb79ac4c3334f5bc1db`；EXE 96,963,776 bytes，SHA-256 `994D7CBF7D3141BB532C2CAA7740AC7535ABD4BF17DC0F25AC6C8209F70D6001`；发布页：https://github.com/FengBujue0104/SeavoExplorer/releases/tag/v0.6.1
- v0.6.2 发布：tag `v0.6.2`（tag object `ec78efbd281582726303de00dc8a182f89d5e039`）指向 `acc54cdd4a06207ef2e23a97092fe4e7257ce1c5`；EXE 96,963,888 bytes，SHA-256 `6B730DD639F2BBAA1149C76975A8E4E0E56BD62C4EA2A02F339413A426842234`；该版本仅修改版本号，用于验证 0.6.1 → 0.6.2 更新流程。

### 其他更正

- 原报告"`_transactional_extract_archive` 6 处测试调用"应为 **8 处**（922、941、954、967、974、985、1001、1074）。
- 原报告"构建/发布链 fail-closed"仍主要来自静态阅读 + tooling 单测；本轮未执行远端发布，结论等级应视为"代码审查 + 单测支持"，不是端到端发布验证。

---

## 0. 结论摘要

| ID | 严重度 | 一句话结论 |
| --- | --- | --- |
| F1 | **P1** | 配置文件里的自定义正则不校验，可注入灾难性回溯模式，导致扫描线程不可中断地挂死 |
| F2 | P2 | 文本预览先按 GBK 解码，14 个中文样本中 8 个被错解；改为 UTF-8 优先后双向全对 |
| F3 | P2 | 打包 zip 时每个目录被写入两次，产物含重复条目（Python 直接告警） |
| F4 | P2 | `folder_structure` 无类型校验，旧/手改配置导致崩溃或"5 个勾选框、只建 1 个目录" |
| F5 | P3 | 统计与搜索线程对失效根目录静默返回 0，而代码注释声称会报错 |
| F6 | P3 | `_safe_stop_thread` 用 `DirectConnection`，清理逻辑实际在 worker 线程执行 |
| F7 | P3 | 剪贴板仅含非本地 URL 时，程序内复制缓存被吞掉，`Ctrl+V` 失效 |
| F8 | P3 | 对已在 `old/` 内的文件再归档会产生 `old/old/` 嵌套，无守卫 |
| F9 | P3 | UTF-8 BOM 泄漏到预览文本；内置帮助章节编号重复；PDF 预览"可翻页"与代码不符 |
| F10 | P4 | 死代码、未使用 import、常量重复定义（非功能缺陷） |

正面结论：事务式解压、保存版本、原子写入、配置损坏回退、终端启动、回收站、粘贴自复制守卫、
版本比较、7-Zip 工具查找等关键不变量**全部实测通过**；构建/发布链是 fail-closed 的，未发现
可以通过文档修饰掩盖的缺口。

---

## 1. 代码规模与结构（实测）

| 指标 | 数值 |
| --- | --- |
| `main.py` | 7,135 行 / 323,633 字节 / 纯 LF 换行 |
| 顶层类 | 22 个 = 12 个 `QWidget` 派生（含 `MainWindow`，2,891–7,085 共 4,195 行）+ 7 个 `QThread` + 3 个异常类 |
| 模块级函数 | 46 个 |
| `MainWindow` 方法 | 156 个 |
| 构建/发布 | `build_support.py` 1,279 行，`release.py` 746 行，`main.spec` 唯一配置 |
| 测试 | `test_safety.py` 1,082 行（53 项）+ `test_tooling.py` 582 行（23 项）= **76 项，全部通过** |

分层清晰：纯函数层（正则/路径/解压事务）→ 7 个后台线程 → 对话框与控件 → `MainWindow`。
`MainWindow` 是单体类，但注释与测试表明作者有意识地守住了若干不变量，不是无序堆砌。

---

## 2. 缺陷清单

> 以下为 2026-08-31 原结论；F1/F2/F3/F4/F6/F7 的更正与修复状态见上方「审查更正与修复状态（2026-09-09）」。

### F1（P1）配置载入侧的自定义正则不做安全校验 → 扫描线程挂死

**现象**：设置对话框保存时会用 `_validate_project_regex` 校验正则（含 ReDoS 启发式），
但**从 JSON 载入时没有任何校验**，扫描器直接编译并使用。

**实测证据链**（四步全链路复现）：

```
1) load_settings 接受危险正则: '^(a+)+$' | regex_state: custom | 警告数: 0
2) _resolve_regex 编译成功: ^(a+)+$ | fallback: False
3) 保存期校验会拒绝同一正则: (False, '正则存在灾难性回溯风险（nested quantifier），请简化规则')
4) 目录名长度 22 -> 0.135s | 24 -> 0.541s | 26 -> 2.163s（指数增长）
5) 目录名长度 35（子进程，超时 30s）-> TIMEOUT，进程挂死
```

**位置**：[main.py:3350](/main.py#L3350)（载入）、[main.py:52](/main.py#L52)（`_resolve_regex` 只编译）、
[main.py:1747](/main.py#L1747)（`FolderScanThread.run`）。

**影响**：CPython 的 `re` 在 C 层执行，`requestInterruption()` 无法打断；扫描线程卡死后
`closeEvent` 会不断重试，最终在第 31 次走 `os._exit(0)` 强杀（[main.py:4092](/main.py#L4092)）。
触发条件是手工编辑或被污染的 `seavoexplorer.json`，属低概率但不可恢复的可用性事故。

**建议**：在 `load_settings` 里复用 `_validate_project_regex`，不通过则回退默认规则并加入
`_pending_load_warnings` 提示（与配置损坏同一处理路径）。

### F2（P2）文本预览解码顺序导致概率性乱码

**现象**：`_preview_text` 按 `('gbk', 'utf-8')` 顺序尝试，UTF-8 字节若恰好是合法 GBK 序列
就会被错解且不抛异常，从而不会回退到 UTF-8。

**实测**：14 个代表性中文样本（说明 / 项目文件 / 主板 / 物料清单 / 信号测试报告 / 版本 …）

| 解码顺序 | UTF-8 文件正确 | GBK 文件正确 |
| --- | --- | --- |
| gbk 优先（当前） | 6/14 | 14/14 |
| utf-8 优先（建议） | **14/14** | **14/14** |

错解样例：`说明 → 璃圧榻`、`项目文件 → 榻撯滾…`、`版本 → 鐗堟湰`、`BOM 清单 v2 → BOM 濂楀嵃 v2`。
不对称性来源：UTF-8 字节有 7–8/11 的概率恰好合法 GBK，而 GBK 字节几乎不可能合法 UTF-8（0/11）。

**位置**：[main.py:5774](/main.py#L5774)。**附带**：UTF-8 BOM 文件预览首字符为 `﻿`。

**建议**：改为 `('utf-8', 'gbk')`（一处改动，双向严格更优），并处理 `utf-8-sig`。

### F3（P2）打包 zip 时目录条目重复

**现象**：`_write_path_to_zip` 先用顶层目录名写一次目录项，随后 `os.walk` 循环里又用
`rel_root` 和 `dirs` 各写一次，导致每个目录被写入两次。

**实测**：

```
包内条目: ['tree/', 'tree/', 'tree/inner/', 'tree/inner/', 'tree/inner/f.txt']
重复条目数: 2
UserWarning: Duplicate name: 'tree/' / 'tree/inner/'
```

**位置**：[main.py:3862](/main.py#L3862) 与 [main.py:3866-3871](/main.py#L3866) 两处都写目录项。

**影响**：产物含重复条目，部分解压器会告警或弹出覆盖确认；不影响数据正确性，但影响交付物质量。

**建议**：删掉 `rel_root` 那一次写入（`dirs` 循环已覆盖所有子目录）。

### F4（P2）`folder_structure` 缺类型校验

**实测**：

```
列表形态（旧/手改配置）: AttributeError: 'list' object has no attribute 'items'
缺键形态 selected_folders={'BOM': True}:
  勾选框状态: {'BOM': True, 'SCH': True, '物料': True, '评审': True, '信号测试': True}
  预览文本  : 'V00/\n  - BOM\n'
  实际创建  : ['BOM']            <- 5 个框全勾，只建 1 个目录
```

**位置**：[main.py:3333](/main.py#L3333)（原样载入）、[main.py:2225](/main.py#L2225)（`update_preview` 用 `.items()`）。

**影响**：前者被 `new_folder_structure` 的兜底 except 吞成一句"创建子文件夹失败"；
后者更隐蔽——用户看到 5 个勾，实际只创建 1 个目录。

**建议**：载入时按 dict 规范化，缺失键用默认值补齐。

### F5（P3）失效根目录被静默报为 0

**实测**：

```
FolderStatsThread 失效根: {'count': 0, 'size': 0, 'trunc': False}   # 未触发 stats_error
FileSearchThread  失效根: {'results': [], 'trunc': False}           # 未触发 search_error
```

`os.walk` 对不存在的路径静默返回空，不会抛异常。而 [main.py:1789](/main.py#L1789) 与
[main.py:1825](/main.py#L1825) 的注释明确说这两个 error 信号是为"root 失联"设计的
（两个线程类见 [main.py:1782](/main.py#L1782)、[main.py:1823](/main.py#L1823)；
（注释原文见 [main.py:1817](/main.py#L1817) 与 [main.py:1869](/main.py#L1869)，
UI 侧处理见 [main.py:5516](/main.py#L5516)、[main.py:5522](/main.py#L5522)）——
网络盘断开、项目被删时用户会看到"0 个文件"或"未找到匹配文件"，而非错误提示。

**建议**：遍历前先 `os.path.isdir(root)` 判断，否则发 error 信号。

### F6（P3）`_safe_stop_thread` 的清理逻辑跑在 worker 线程

**实测**（连接 `QThread.finished`，打印槽所在线程）：

| 连接方式 | 槽是否在 GUI 线程执行 |
| --- | --- |
| `AutoConnection` | 是 |
| **`DirectConnection`（当前）** | **否（worker 线程）** |
| `QueuedConnection` | 是 |

**位置**：[main.py:4083](/main.py#L4083)。该槽执行 `t.deleteLater()` 并从
`self._zombie_threads` 移除元素。

**影响**：`deleteLater()` 本身可跨线程调用，但列表增删发生在非 GUI 线程，与 `closeEvent`
里的 `list(self._zombie_threads)` 快照构成竞态；而 DirectConnection 想规避的"事件循环阻塞"
场景下 `deleteLater` 仍要等事件循环，因此换不来收益。

**建议**：改用默认 `AutoConnection`。

### F7（P3）剪贴板非本地 URL 吞掉程序内缓存

**实测矩阵**（内部缓存始终有效）：

| 剪贴板内容 | 返回结果 |
| --- | --- |
| 仅非本地 URL（`https://…`） | `[]`（内部缓存未生效） |
| 仅本地文件 URL | 正常返回 |
| 纯文本无 URL | 正常回退内部缓存 |
| 非本地 + 本地混合 | 正常返回本地项 |

**位置**：[main.py:5066](/main.py#L5066)，`hasUrls()` 为真时无条件 `return paths`。
触发场景：从浏览器复制链接后再按 `Ctrl+V`。

### F8（P3）`old/` 归档无嵌套守卫

**实测**：对已在 `old/` 内的文件再次归档，会移动到 `old/old/`；重复操作会不断加深嵌套。
对比之下粘贴操作有明确的"不能复制到自身或子目录"守卫（已实测生效）。

**位置**：[main.py:5527](/main.py#L5527)。

### F9（P3）文档与细节

- UTF-8 BOM 泄漏到预览文本（同 F2）。
- 内置帮助章节编号重复：两个"四、"（[main.py:6660](/main.py#L6660)、[main.py:6697](/main.py#L6697)），
  后续整体错位（末尾"十三、"应为"十四、"）。
- 帮助称 PDF"多页预览，可翻页查看"（[main.py:6702](/main.py#L6702)），但实现固定渲染前
  `PREVIEW_PDF_PAGES = 3` 页且无翻页控件（[main.py:5799](/main.py#L5799)）。
  注：README 的"支持多页预览"说法站得住（确实渲染 3 页），无需改。

### F10（P4）死代码与卫生问题

- 未被引用的类与方法：`OpenWithDialog`、`MainWindow._extract_with_7z`、
  `MainWindow._fetch_latest_release`（已被 `CheckUpdateThread` 取代）、
  `MainWindow.generate_video_thumbnails`（连带 `_capture_video_frames` 不可达）。
- 未使用的 import：`QToolBar`、`QSizePolicy`、`numpy as np`、`PIL.Image`（后两者仅作可用性探测）。
- 未生效的常量：`FolderScanThread.MAX_FILES`、`MAX_MATCHES_WARNING`、`scan_started` 信号、
  `_SEARCH_TYPE_EXTS` 占位。
- `_WINDOWS_RESERVED_NAMES` 重复定义（137 / 362 行），后者覆盖前者并丢掉 `CLOCK$`。
  实测 Windows 本身允许创建 `CLOCK$`，因此这不是功能缺陷，仅需合并常量。

---

## 3. 已验证正确的关键不变量（实测）

| 不变量 | 实测结果 |
| --- | --- |
| 事务式解压（预检→staging→校验→无覆盖提交） | 6 处测试直接调用 `_transactional_extract_archive`，含取消后不提交、路径穿越拒绝、软链接拒绝、压缩比异常拒绝 |
| 保存版本序列 | `S1200-10.dsn → _20260831 → …a → …b` 正确 |
| 中间版本缺失不回填 | 删除 `a` 后再保存得到 `c`（不是重新生成 `a`） |
| 仅大小写不同的目标不覆盖 | 已存在 `…C.dsn` 时新版本跳到 `…d.dsn` |
| 版本上限 | 造满 703 个候选后明确弹错"已达上限"，未新增文件（未覆盖） |
| 原子写入 | 20 次连续写入，文件始终是合法 JSON；无 `.tmp` 残留 |
| 目标只读时仍可保存 | 预先 `chmod 0o444` 后写入成功，且恢复隐藏属性 |
| 配置语法/语义损坏 | 均生成 `.bak` 备份并给出提示（不是静默重置） |
| 粘贴自复制守卫 | 把文件夹粘进自身/子目录被拦截并给出中文原因 |
| 粘贴重名 | `doc.txt → doc_副本1.txt → doc_副本2.txt` |
| 版本比较 | `0.5.10 > 0.5.3`（数值比较非字符串）、预发布 `0.5.3-beta.1 < 0.5.3`、`v` 前缀容错全部正确 |
| 更新资产选择 | 无 exe 资产返回 `None`；多 exe 优先 `SeavoExplorer`；大小写不敏感匹配 |
| 扫描去重 | 同一目录以两种斜杠形式登记两次 → 结果不重复；父+子嵌套根 → 深层项目只出现一次 |
| 自定义正则 | 生效（如 `^PCB(\d{2})(?:-(.*))?$`）；组 1 非数字时跳过而不崩溃 |
| 注释优先级 | `seavo_comments.json` 覆盖文件夹名后缀 |
| 统计/搜索截断 | 达到软上限时 `truncated=True` 并正确上报 |
| 视频抽帧 | 合成视频抽出 5 帧，尺寸与 `VIDEO_PREVIEW_POSITIONS` 一致 |
| 更新检查 | 回环 HTTP 下解析正常，请求带 `SeavoExplorer/<version>` 的 User-Agent |
| 7-Zip 工具查找 | 只接受名为 `7z.exe` 的现有文件（有测试）；未授权的 rar/7z 预览不启动外部进程（有测试） |
| 终端启动 | 路径只作为 argv/cwd，UNC 用 base64 编码命令（有测试） |
| 构建/发布链 | `gh` 版本基线 + 认证 + origin 白名单（拒 http/凭据/仿冒域名）+ HEAD==origin/main + 发布前后两次状态复核 + annotated tag digest 校验 + 三资产发布前后 digest 校验；冒烟在 `build/` 隔离目录 offscreen 启动并按进程路径前缀终止（有白名单守卫） |

---

## 4. 测试覆盖实测

76 项测试全部通过，但覆盖面偏窄（用 `sys.settrace` + AST 限定名统计**真实执行**）：

- `MainWindow` 156 个方法中，测试期间实际执行 **21 个**。
- 46 个模块级函数中实际执行 36 个；**从未执行**的 10 个里，4 个直接对应安全/不变量：
  `_validate_windows_filename`（重命名与新建项目的名称校验）、`_resolve_regex` 与
  `_extract_project_fields`（扫描期正则契约）、`_get_app_dir`（sidecar 落盘位置）。
- 7 个 `QThread` 中只有 `UpdateDownloadThread` 被触及（7 个方法），其余 6 个**零覆盖**。
  其中解压线程的**核心逻辑**被测试直接调用覆盖（6 处），缺口只在约 42 行的线程包装器，
  即"提交后到达的取消不能改报失败"这条契约没有测试。

补充观察：下载测试用 `https://example.invalid` 并同步调用 `thread.run()`，靠失败路径驱动；
本机 `HTTP_PROXY`/`HTTPS_PROXY` 已设置且无 `NO_PROXY`，因此失败来自代理而非 DNS。
测试仍然确定（3 秒跑完），但语义上依赖代理行为，建议改为 mock `urllib.request.urlopen`。

---

## 5. 文档与代码漂移

> 以下为 0.5.4 分析时的状态；0.6.0 已同步版本号、测试数、正则安全说明与 PDF/帮助文案。

| 位置 | 现状 |
| --- | --- |
| `AGENTS.md` | 测试数写"70 项 / 47 项产品"，实测 **76 项 / 53 项** |
| `AGENTS.md` | 称 `_is_regex_safe` 未接入保存链路——**已过时**，它已接入保存/实时校验（[main.py:77](/main.py#L77)）；真正残留的缺口只在**载入侧**（见 F1） |
| `AGENTS.md` | 称 `main.py` 约 6,300 行，实测 7,135 行 |
| 内置帮助 | 章节编号重复、PDF"可翻页"与实现不符（见 F9） |
| `README.md` | 版本 0.5.4 与 `main.py`/`pyproject.toml` 三方一致；"多页预览"表述无需修改 |

---

## 6. 建议的修复顺序

1. **F1 载入侧正则校验**（不可恢复的挂死风险；复用现成校验函数，改动集中在 `load_settings`）
2. **F2 解码顺序**（一行改动；实测 8/14 → 0/14 错解，GBK 不受影响）
3. **F4 `folder_structure` 规范化**（顺带消除"勾选框与预览不一致"）
4. **F3 重复目录条目**（删一处写入；产物质量）
5. **F5 失效根目录报错**（对齐注释与实现）
6. **F6 `AutoConnection`** → **F7 剪贴板兜底** → **F8 `old/` 守卫** → **F9 文案** → **F10 清理**

每项建议配一条回归测试，并顺带把第 4 节列出的 4 个未覆盖安全相关函数纳入测试。

---

## 附录 A：本轮执行的验证

- `git status --short` / `git diff --check` / `git log -1`（每轮前后各一次，全程为空）
- `python -m unittest -q test_safety.py test_tooling.py` → 76 tests OK
- `python -m py_compile`（7 个模块）；`ast.parse(feature_version=(3,8))` 全部通过
- 线程实测：`FolderScanThread`（去重/排序/递归/自定义正则/注释覆盖/非数字跳过）、
  `FolderStatsThread`、`FileSearchThread`、`VideoFrameThread`（合成视频）、
  `CheckUpdateThread`（回环 HTTP，未触外网）
- 持久化实测：语法/语义损坏回退、类型宽容度、原子写入、只读目标、连续写入
- 文件操作实测：保存版本（序列/不回填/大小写/上限）、`old/` 归档、粘贴副本、zip 打包
- 辅助函数实测：版本比较表、资产选择、文件大小格式化
- ReDoS 端到端：子进程隔离 + 30 秒超时

所有临时数据写在系统临时目录并已清理。**仓库内唯一的新增文件是本报告**；未构建、未发布、
未读取或写入任何真实 sidecar 数据（仓库目录下当前不存在 `seavoexplorer.json` / `seavo_comments.json`）。

## 附录 B：方法学说明（含本次分析中已纠正的两处错误）

1. **终端字符编码不是程序行为的证据。** 首轮我把 PowerShell 控制台按 GBK 解码的输出当成了
   程序的解码结果，据此误判"UTF-8 预览必然乱码"。改用与编码无关的判定（布尔比对、`ascii()`
   转义、真实文件走真实函数）后修正为"内容相关、8/14 概率错解"。
2. **覆盖率必须按限定名统计。** 第二版追踪脚本按函数名记录，`UpdateDownloadThread.run`
   一执行就让 7 个线程的 `run` 全被算作已覆盖。改用 `co_firstlineno` + AST 限定名
   （`ClassName.method`）后修正为"6/7 线程零覆盖"。

本报告中的每条结论都尽量满足：可复现、有数据、能指出触发路径与代码位置。
仍未覆盖的是 GUI 渲染与交互——静态分析和函数级实测都不能替代端到端验证。
