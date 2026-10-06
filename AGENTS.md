<!-- 仅供 GPT/Codex 在本仓库内协作时使用，不是面向最终用户的产品文档。 -->

# SeavoExplorer GPT 协作说明

## 适用范围与事实来源

本文件适用于整个仓库。每次开始任务先查看 `git status --short`、相关源码和现有 diff；工作树中的既有修改、删除和未跟踪文件均按用户资产处理，不能擅自还原、覆盖、删除或纳入无关提交。

事实来源按以下顺序判断：

1. 当前工作树的代码、配置与实际测试结果。
2. 用户最新要求和与任务相关的 Git diff。
3. `README.md`、`打包指南.txt`。
4. 本文件。
5. 被忽略的 `PENDING-FIXES.md`、`OHMYPI.md` 仅是本地线索，可能过时。

## 项目概况

SeavoExplorer 是 Windows PyQt5 桌面文件浏览器，用于发现和管理以 S/M 编号命名的硬件/PCB 项目目录。界面、业务和平台集成集中在约 7,648 行的 `main.py`。

- 当前版本为 0.6.6；运行时版本的首要来源是 `main.py` 的 `APP_VERSION`。
- 源码保持 Python 3.8 grammar 兼容；官方 Windows EXE 已验证环境为 Python 3.13.2 x64。
- UI、用户提示和主要文档使用中文，文本统一 UTF-8。
- Windows 是实际目标平台，代码使用 `os.startfile`、Windows Shell/`ctypes`、强制回收站接口和固定的 7-Zip 安装位置。
- 正常源码入口是 `main.py` 末尾的 `if __name__ == '__main__':`；没有模块级 `main()`，也没有 Python console/gui entry point。

## 文件地图

| 路径 | 职责与注意事项 |
| --- | --- |
| `main.py` | 应用入口和全部主要产品逻辑；运行行为的首要事实来源。 |
| `test_safety.py` | 104 项产品安全/回归测试；会导入 PyQt5，但使用临时数据，不应接触真实项目。 |
| `test_tooling.py` | 30 项无网络辅助链路测试：版本、哈希、严格环境、manifest、快照、完整遍历、环境净化、tag/draft/assets。 |
| `requirements.txt` | Python >=3.8 源码运行依赖范围，不含 PyInstaller。 |
| `requirements-build.txt` | Python 3.13.2 x64 官方构建环境的精确版本锁；除 venv 自带 pip/wheel 外，正式构建拒绝锁外发行包。 |
| `pyproject.toml` | 项目元数据；运行依赖从 `requirements.txt` 动态读取。项目是单模块，不声明无效入口。 |
| `LICENSE` | 与 `pyproject.toml` 一致的 MIT 许可正文。 |
| `main.spec` | onefile/onedir 共用的唯一 PyInstaller 配置；默认 onefile。 |
| `build_support.py` | 构建前检、环境隔离、版本资源、TOC 审计、Authenticode 签名/校验、冒烟、哈希、manifest。 |
| `build_onefile.py` | onefile 薄包装器；默认离线，不安装依赖、不重生图标。 |
| `build_onedir.py` | onedir 薄包装器；与 onefile 共用 `main.spec`。 |
| `make_ico.py` | 显式维护命令；从 PNG 或现有 ICO 原子重建多尺寸 ICO。正常构建不调用。 |
| `release.py` | 检查 clean/synced main，构建并以 draft→资产核验→publish 流程发布。具有远端副作用。 |
| `favicon_src.png` / `favicon.ico` | 必需且应跟踪的构建输入；干净克隆必须同时具备。 |
| `README.md` | 面向用户的功能、安装和简要构建说明。 |
| `打包指南.txt` | 面向维护者的权威 Windows 构建/发布流程。 |

不要直接编辑或提交构建/运行产物：

- `build/`、`dist/`、`__pycache__/`、`*.egg-info/`、临时虚拟环境。
- `seavoexplorer.json`、`seavo_comments.json`、`error_details.log`、`*.part`、`*.bak`。
- 被忽略的 `OHMYPI.md`、`PENDING-FIXES.md`，除非任务明确要求维护本地说明。
- `.git/` 内部文件。

真实 sidecar JSON 包含项目路径、快捷访问和窗口状态，属于用户数据。不要读取其中的具体值，不要复制到代码、文档、日志或回复，也不要以这些路径做自动测试。文件操作测试一律使用临时目录。

## `main.py` 关键结构

- 顶部：可选依赖、版本/GitHub 常量、正则、资源和安全阈值。
- 小型控件/对话框、`UpdateDownloadThread`。
- 扫描、统计、搜索等后台 `QThread`。
- 新建项目/结构、项目设置、7-Zip 授权、快捷访问和新手向导。
- `MainWindow`：UI、持久化、扫描、文件操作、压缩包、预览、更新和帮助。
- 文件末尾：创建 `QApplication`、启动画面与主窗口。

`MainWindow` 是单体类。一个功能常横跨默认状态、加载/保存、设置对话框、处理器和帮助文本；修改时检查完整链路，但不要借机做无关拆分或全文件格式化。

### 项目正则

默认规则：

```text
主板: ^S(\d{3,4})(?:_(.*))?$
子卡: ^M(\d{3,4})(?:_(.*))?$
```

扫描器要求捕获组 1 可转换为整数项目编号，并直接读取捕获组 2 作为注释。自定义规则修改必须覆盖该契约、编译失败回退、持久化和异步扫描快照。

重要现状：`_is_regex_safe()` 已接入保存与解析链路，并在 0.6.0 升级为结构分析器，覆盖 `{m,n}` 量词、嵌套重复组、回溯引用，并在 0.6.3 增加相邻大范围/无上限重复量词检测；它仍是启发式防护，不能保证覆盖所有复杂正则，不要在文档、发布说明或回复中声称对任意自定义规则实现了完整 ReDoS 防护。

### 状态持久化

开发运行时 sidecar 写在脚本旁；PyInstaller 运行时写在 EXE 旁。该行为由 `_get_app_dir()` 决定，不能改成当前工作目录或业务硬编码路径。

- `seavoexplorer.json`：项目根、排序、快捷访问、7-Zip、预览、正则、窗口状态和模板等。
- `seavo_comments.json`：以绝对项目路径为键的用户注释。
- `safe_write_json()` 使用随机独占临时文件、flush/fsync、`os.replace` 原子替换，并恢复 Windows 隐藏属性。
- 配置或注释文件读取/备份失败时必须阻止自动保存覆盖原文件。

新增/改名设置项至少同步默认值、加载、保存、对话框、运行时消费者、旧配置兼容和帮助文本。

### 代码签名与更新

- `SEAVO_SIGN_MODE=store|pfx` 启用 Authenticode 签名；manifest 的 `code_signing` 只能通过公开字段白名单记录主体、指纹、验证状态和时间戳，PFX 路径/密码等执行凭据绝不能进入 manifest。
- `SEAVO_REQUIRE_SIGNING=1` 让 `release.py` 拒绝未签名 manifest；自签名开发构建需同时设置 `SEAVO_SIGN_ALLOW_UNTRUSTED=1`。
- 网络请求必须通过 `_urlopen_with_proxy()`，支持环境代理、Windows 系统代理及 PAC/WPAD，并只允许 HTTP/HTTPS。
- 打包后的 EXE 支持 `--apply-update --target ... --pid ... --sha256 ...`：等待旧进程退出后用唯一临时文件和 `ReplaceFileW` 替换并保留 `.old` 备份；源码模式必须拒绝更新模式。
- 若安装失败且回滚失败，必须停止重试并同时保留 `.old` 备份与下载的新 EXE。
- 自签名不会消除其他电脑的 SmartScreen 提示，正式发布应换用公共可信证书。

### 线程与 UI

磁盘扫描、统计、搜索、下载和媒体处理不能移回 UI 线程。后台线程通过信号更新控件；替换任务时保留 token/取消/`requestInterruption()`，交互路径不得同步等待旧线程，线程结束后再延迟清理；窗口关闭前正确结束线程。

### 文件操作与安全不变量

- 终端、PowerShell、cmd 必须以结构化参数和 `cwd` 在用户选中路径启动；不能把路径拼入命令文本或默认提权。
- 删除只允许 Win10/11 现代回收站后端；失败必须保留源文件，绝不降级永久删除。
- 复制、保存版本、压缩、解压和 `old/` 归档禁止静默覆盖。文件复制采用独占临时文件和无覆盖提交；多选 ZIP 必须剔除父子重复路径、排除输出 ZIP 自身并按成员名去重。
- ZIP/7Z 智能解压必须保留预检、同盘 staging、完整校验、取消处理和无覆盖提交。
- 递归扫描/统计/搜索/打包不得进入 junction/reparse point；`old/` 归档必须使用无覆盖原子移动。
- 7-Zip 配置只能接受名为 `7z.exe` 的现有文件；RAR/7Z 默认不授权，ZIP 不受该开关影响。
- 关闭某类自动预览后，当前文件仍应显示「显示预览」按钮；点击按钮只对当前目标执行一次手动预览。
- 压缩包/Excel 等预览必须保留数量与输出上限，避免大文件或大表格长时间占用 UI。
- `.opj`、`.dsn`、`.sch`、`.brd`、`.dbk`、`.dsnlck` 有意只显示不可预览提示。

## 修改规则

1. 先检查状态和目标 diff，保留所有无关用户改动。
2. 不全量格式化 `main.py`，不顺手改行尾、重排或重构无关区域。
3. 不恢复此前删除的 `fix_all.py`、`release_notes.md`、`test_regex.py`。
4. 新代码保持 Python 3.8 语法兼容；路径必须支持中文、空格、UNC 和 Windows 规则。
5. 版本变更同步 `main.py`、`pyproject.toml`、README、关于/帮助和发布说明；现有测试会检查前三项。
6. 依赖变更同步 `requirements.txt`、`requirements-build.txt`、`pyproject.toml`、`main.spec` 和文档。
7. PyInstaller datas/hidden imports/excludes 只在 `build_support.py`/`main.spec` 维护，不复制回包装器或 pyproject。
8. 输出名始终为 `SeavoExplorer`，发布 onefile 路径始终为 `dist/SeavoExplorer.exe`。
9. 不 push、tag、创建 Release、永久删除或操作真实业务文件，除非用户明确授权该具体动作。

## 开发验证

优先使用当前选中的 `python`。本机 2026-07-10 已确认解释器：

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" --version
```

常用验证：

```powershell
python -m unittest -q test_safety.py test_tooling.py
python -m py_compile main.py test_safety.py test_tooling.py build_support.py build_onefile.py build_onedir.py make_ico.py release.py
python -c "import ast, pathlib; [ast.parse(p.read_text(encoding='utf-8'), filename=str(p), feature_version=(3, 8)) for p in pathlib.Path('.').glob('*.py')]"
git diff --check
git status --short
```

当前 134 项测试中，104 项产品测试覆盖版本/裸 `except`、默认路径、终端、回收站、7-Zip 授权、手动预览、路径规范化、预览资源释放、外部剪贴板粘贴、面包屑双击、保存版本后缀递增、更新 `.part`、事务式解压、正则结构安全、文本编码/BOM、zip 去重、folder_structure 归一化、失效根目录错误信号、old/ 守卫、PAC/WinHTTP 结构体和文档一致性；30 项 tooling tests 覆盖构建/发布、代码签名和 manifest 的 fail-closed 契约。它们不是完整 GUI/所有文件格式的端到端测试，报告时必须区分。

正式 onefile 验证必须使用由 `requirements-build.txt` 创建、未启用 system-site-packages，且除 venv 自带 pip/wheel 外无锁外包的 Python 3.13.2 x64 venv：

```powershell
.\.venv-build\Scripts\python.exe build_onefile.py
```

该命令默认执行上述检查、严格环境核对、净化 PATH、PyInstaller、TOC 二进制来源审计、临时目录隔离启动、SHA-256 和 manifest。`--skip-tests`、`--skip-smoke`、`--allow-unverified-env` 只能用于本地诊断，不能用于发布。

不要把下列命令当普通只读验证：

- `python build_onefile.py` / `python build_onedir.py`：清理并覆盖 `build/`、`dist/`。
- `python make_ico.py`：原子覆盖跟踪的 `favicon.ico`。
- `python release.py vX.Y.Z`：创建/push tag 和 GitHub Release；默认还会重建。

## 已验证发布基线与剩余限制

- annotated tag `v0.5.0` 指向 `b401c2e`；不要把可继续前进的 `main`/`origin/main` 写死到该提交。
- 已发布页面：https://github.com/FengBujue0104/SeavoExplorer/releases/tag/v0.5.0
- 已发布 v0.5.0 EXE SHA-256：`AF2E7C3C9780CE1F6D002BC4215F98FCE5F4141428816579F068AB6412B12A70`。
- 不得用后续本地重新构建的不同哈希静默替换既有 v0.5.0 资产。
- annotated tag `v0.5.1` 指向 `c0b71a0`，发布页为：https://github.com/FengBujue0104/SeavoExplorer/releases/tag/v0.5.1
- 已发布 v0.5.1 EXE 为 96,926,112 bytes，SHA-256：`126134AF93E31344768B847760B25FFE56F24C966AC36EE5216003D51B661937`。
- draft→三资产 digest 核验→publish 自动化已随 v0.5.1 完成首次真实 GitHub 端到端发布；三个远端资产均已核对 digest。
- 新构建会写入 PE FileVersion/ProductVersion；这不等于公共可信的 Authenticode 签名。当前 0.6.1 使用自签名证书。
- 自定义正则安全检查已接入保存与解析链路，并在 0.6.0 升级为结构启发式；仍需注意它不能覆盖所有复杂正则。
- annotated tag `v0.6.0`（tag object `589e35669d47f4b974160cb474def7d22f3b4228`）指向 `29b3dab5960ef9efd55a5123294f19ca17b38e7f`，发布页：https://github.com/FengBujue0104/SeavoExplorer/releases/tag/v0.6.0
- 已发布 v0.6.0 EXE 为 96,948,502 bytes，SHA-256：`44E769B707F6DDEB144B5994BF7674AE33FA9E64317243125387F615291A75D2`；远端三资产 digest 已核对。
- annotated tag `v0.6.1`（tag object `a7929378bebcd0061e4208ec3eab5799f45c8e72`）指向 `4b47e2d18673e7c1de1cffb79ac4c3334f5bc1db`，发布页：https://github.com/FengBujue0104/SeavoExplorer/releases/tag/v0.6.1
- 已发布 v0.6.1 EXE 为 96,963,776 bytes，SHA-256：`994D7CBF7D3141BB532C2CAA7740AC7535ABD4BF17DC0F25AC6C8209F70D6001`；使用自签名证书，远端三资产 digest 已核对。
- annotated tag `v0.6.2`（tag object `ec78efbd281582726303de00dc8a182f89d5e039`）指向 `acc54cdd4a06207ef2e23a97092fe4e7257ce1c5`，发布页：https://github.com/FengBujue0104/SeavoExplorer/releases/tag/v0.6.2
- 已发布 v0.6.2 EXE 为 96,963,888 bytes，SHA-256：`6B730DD639F2BBAA1149C76975A8E4E0E56BD62C4EA2A02F339413A426842234`；该版本仅修改版本号，用于验证 0.6.1 → 0.6.2 更新流程。

- annotated tag `v0.6.3`（tag object `f9ff8f29377ead287887d916cfb4eeeed77e839d`）指向 `14597501b6dde6065308b169dbaaf1bff34a73bc`，发布页：https://github.com/FengBujue0104/SeavoExplorer/releases/tag/v0.6.3
- 已发布 v0.6.3 EXE 为 96,579,280 bytes，SHA-256：`6D0F09CC5B0B9E9EAA3B7F082C668FBA7C6BAA36C7CFA0669868F23E2C3A2C5E`；使用自签名证书，远端三资产 digest 已核对。 本版加固无覆盖提交、ZIP 去重、更新回滚、相邻重复正则、大目录统计、线程清理、预览上限和签名 manifest 脱敏。
- annotated tag `v0.6.4`（tag object `c53fa30c93eac940674a316ab966cb2013471cd7`）指向 `b6fbe3e3ed762aeb8b0f724bf72ba26d99fb49cf`，发布页：https://github.com/FengBujue0104/SeavoExplorer/releases/tag/v0.6.4
- 已发布 v0.6.4 EXE 为 96,580,120 bytes，SHA-256：`D2698016CECCACD1C793E093CEA9A41F4CAECB427918CFD05573DB1E143DD0AD`；使用自签名证书，远端三资产 digest 已核对。本版同步更新程序内外文档描述。
- annotated tag `v0.6.5`（tag object `9472ed85d775f26ff54c83f6c431dc086bc429a9`）指向 `aee6743abde1e347e75cb7564ea66d9402c5735d`，发布页：https://github.com/FengBujue0104/SeavoExplorer/releases/tag/v0.6.5
- 已发布 v0.6.5 EXE 为 96,584,992 bytes，SHA-256：`624D51171EC7AC57B04913E9D3C84F5B9752A848D5009BEC36F8D665F6737F60`；使用自签名证书，远端三资产 digest 已核对。本版增加环境/系统/PAC 代理支持，并加固配置备份、junction 扫描、old/ 归档和构建 manifest 写入。
- annotated tag `v0.6.6`（tag object `66ca6b22ed1b019332044734c5b0f2e5151a4d28`）指向 `3f2d20a12a423c533d0d084996c0ecb2060c09dc`，发布页：https://github.com/FengBujue0104/SeavoExplorer/releases/tag/v0.6.6
- 已发布 v0.6.6 EXE 为 96,973,960 bytes，SHA-256：`EDE1169F4FA1AFB1BBA634F12CA11993F4844F5F20AA56C4108A2EE7CC72BC67`；使用自签名证书，远端三资产 digest 已核对。本版修正 Windows PAC/WPAD 选项结构体，使系统代理解析符合 WinHTTP ABI。

交付时明确报告修改文件、实际执行的检查、构建产物哈希和未执行事项；不要把“语法可解析”表述成“GUI 功能已验证”。
