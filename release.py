"""
SeavoExplorer 一键发布脚本

流程：检查环境 -> 确认版本号 -> 打 tag -> 推送 -> 创建 GitHub Release 并上传 exe

用法：
    py release.py            # 交互式输入版本号
    py release.py v0.4.2     # 直接指定版本号
    py release.py --build v0.4.2   # 先运行打包再发布

依赖：已安装并登录 GitHub CLI（gh auth login），git 远程为 origin。
"""

import os
import sys
import subprocess

os.chdir(os.path.dirname(os.path.abspath(__file__)))

REPO = "15948707537/SeavoExplorer"
EXE = "dist/SeavoExplorer.exe"
APP_NAME = "SeavoExplorer"


def run(cmd, check=True, capture=False):
    """执行命令；capture=True 时返回 stdout 字符串。"""
    result = subprocess.run(
        cmd, capture_output=capture, text=True, encoding="utf-8", errors="replace"
    )
    if check and result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        fail(f"命令失败（退出码 {result.returncode}）：{' '.join(cmd)}\n{err}")
    return (result.stdout or "").strip() if capture else result.returncode


def pause_before_exit():
    try:
        if sys.stdin.isatty():
            input("\n按回车键退出...")
    except EOFError:
        pass


def fail(msg):
    print()
    print("========================================")
    print(" 发布中止")
    print("========================================")
    print(msg)
    pause_before_exit()
    sys.exit(1)


def confirm(prompt):
    return input(prompt).strip().lower() in ("y", "yes", "是", "")


def main():
    print("========================================")
    print(f" {APP_NAME} 一键发布")
    print("========================================")
    print()

    # 1. 前置检查：gh 是否可用并已登录
    if run(["gh", "--version"], check=False, capture=True) == "":
        fail("未检测到 GitHub CLI（gh）。请先安装：https://cli.github.com/")
    if run(["gh", "auth", "status"], check=False) != 0:
        fail("GitHub CLI 未登录。请先执行：gh auth login")

    # 2. 解析参数：--build 表示先打包，其余非选项参数为版本号
    do_build = "--build" in sys.argv[1:]
    positional = [a for a in sys.argv[1:] if not a.startswith("-")]

    # 3. 需要打包则先运行 build_onefile.py
    if do_build:
        print("先执行打包 build_onefile.py ...")
        if not os.path.exists("build_onefile.py"):
            fail("未找到 build_onefile.py，无法 --build。")
        if run([sys.executable, "build_onefile.py"], check=False) != 0:
            fail("打包失败，已中止发布。")

    # 4. 检查产物是否存在
    if not os.path.exists(EXE):
        fail(f"未找到可执行文件 {EXE}。请先运行 build_onefile.py 打包（或加 --build）。")
    size_mb = os.path.getsize(EXE) / 1024 / 1024
    print(f"待发布文件：{EXE}（{size_mb:.1f} MB）")

    # 5. 检查工作区是否干净
    dirty = run(["git", "status", "--porcelain"], capture=True)
    if dirty:
        print("\n[警告] 工作区有未提交的改动：")
        print(dirty)
        if not confirm("仍要基于当前 HEAD 继续发布？(Y/n) "):
            fail("已取消。请先提交或清理改动后重试。")

    # 6. 确认版本号
    version = positional[0].strip() if positional else ""
    if not version:
        version = input("\n请输入版本号（如 v0.4.2）：").strip()
    if not version:
        fail("未提供版本号。")
    if not version.startswith("v"):
        version = "v" + version

    # 7. tag 不能重复
    existing = run(["git", "tag", "--list", version], capture=True)
    if existing:
        fail(f"tag {version} 已存在。请换一个版本号，或先删除：git tag -d {version}")

    print()
    if not confirm(f"将发布 {version} 到 {REPO}，确认？(Y/n) "):
        fail("已取消。")

    # 8. 打 tag
    print(f"\n创建 tag {version} ...")
    run(["git", "tag", "-a", version, "-m", f"{APP_NAME} {version}"])

    # 9. 推送当前分支与 tag
    print("推送分支与 tag ...")
    run(["git", "push", "origin", "HEAD"])
    run(["git", "push", "origin", version])

    # 10. 创建 Release 并上传 exe
    print("创建 GitHub Release 并上传 exe（约 90MB，请稍候）...")
    notes = (
        f"## {APP_NAME} {version}\n\n"
        f"### 新增功能\n\n"
        f"- **保存版本**：右键文件选择「保存版本」，自动生成 `文件名_YYYYMMDD[后缀].ext` 的日期版本副本，当天多次保存自动递增字母后缀（a/b/c...）\n"
        f"- **归档到 old 文件夹**：右键选择「归档到old文件夹」，将选中文件移入同目录下的 `old/` 子文件夹（自动创建），支持多选批量归档\n\n"
        f"### 修复\n\n"
        f"- **F5 刷新文件树**：修复 QFileSystemModel 缓存导致文件树不更新的问题\n"
        f"- **右键重命名失效**：修复菜单 action dispatch 缺失导致右键重命名无效的问题\n"
        f"- 打包配置统一：`main.spec` 输出名与其他脚本对齐为 `SeavoExplorer.exe`\n\n"
        f"### 下载\n"
        f"下方 `SeavoExplorer.exe` 为 Windows 单文件可执行程序，"
        f"下载即用，无需安装 Python 环境。"
    )
    run([
        "gh", "release", "create", version, EXE,
        "-R", REPO,
        "--title", f"{APP_NAME} {version}",
        "--notes", notes,
    ])

    url = run(
        ["gh", "release", "view", version, "-R", REPO, "--json", "url",
         "--jq", ".url"],
        capture=True,
    )

    print()
    print("========================================")
    print(" 发布成功！")
    print(f" {url}")
    print("========================================")
    pause_before_exit()


if __name__ == "__main__":
    main()
