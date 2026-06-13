"""验证 code-review High 修复点（headless）。运行: QT_QPA_PLATFORM=offscreen py verify_fixes.py"""
import os, sys, io, tempfile, zipfile
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt
app = QApplication(sys.argv)

import main

results = []
def check(name, cond, detail=''):
    results.append((name, cond, detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail and not cond else ''))

# ---- #1 SettingsDialog._swap_rows 不再访问第3列 (2列表) ----
try:
    dlg = main.SettingsDialog([('A', 'C:/a'), ('B', 'C:/b')])
    dlg._swap_rows(0, 1)  # 旧代码会 AttributeError
    r0 = dlg.path_list.item(0, 0).text(); r1 = dlg.path_list.item(1, 0).text()
    check('#1 SettingsDialog 上移/下移不崩溃且正确交换', r0 == 'B' and r1 == 'A', f'got {r0},{r1}')
except Exception as e:
    check('#1 SettingsDialog 上移/下移不崩溃且正确交换', False, repr(e))

# ---- #2 QuickAccessSettingsDialog._swap_rows 同步搬运第3列勾选 ----
try:
    paths = [('桌面', 'C:/d', False), ('磁盘根', 'D:/', True)]
    qdlg = main.QuickAccessSettingsDialog(paths)
    # 交换前: row0 未勾选, row1 勾选
    before = (qdlg.path_list.item(0, 2).checkState(), qdlg.path_list.item(1, 2).checkState())
    qdlg._swap_rows(0, 1)
    n0 = qdlg.path_list.item(0, 0).text()
    c0 = qdlg.path_list.item(0, 2).checkState()
    c1 = qdlg.path_list.item(1, 2).checkState()
    # 交换后 row0 应为“磁盘根”且勾选跟随(=Checked), row1 应为“桌面”未勾选
    ok = (n0 == '磁盘根' and c0 == Qt.Checked and c1 == Qt.Unchecked)
    check('#2 快捷访问勾选随行移动', ok, f'name0={n0} c0={c0} c1={c1} before={before}')
except Exception as e:
    check('#2 快捷访问勾选随行移动', False, repr(e))

# ---- #5 文本预览编码回退: GBK 文件不再乱码 ----
try:
    win = main.MainWindow.__new__(main.MainWindow)  # 不走 __init__，只测方法
    class _Stub:
        def __init__(s): s.text=None
        def setPlainText(s,t): s.text=t
    win.preview_tab = _Stub()
    tmp = tempfile.NamedTemporaryFile('wb', suffix='.txt', delete=False)
    gbk_text = '主板项目 信号测试 评审'
    tmp.write(gbk_text.encode('gbk')); tmp.close()
    win._preview_text(tmp.name)
    os.unlink(tmp.name)
    # 旧代码: utf-8+replace 读 GBK -> 全是替换符，不含原文
    ok = gbk_text in win.preview_tab.text
    check('#5 GBK 文本预览正确解码(不乱码)', ok, f'got={win.preview_tab.text!r}')
except Exception as e:
    check('#5 GBK 文本预览正确解码(不乱码)', False, repr(e))

# ---- #7 zip-slip: 含 ../ 的恶意 zip 被阻止；#4 句柄: 正常 zip 能解压且无残留 ----
try:
    work = tempfile.mkdtemp()
    # 构造恶意 zip
    evil = os.path.join(work, 'evil.zip')
    with zipfile.ZipFile(evil, 'w') as zf:
        zf.writestr('../escaped.txt', 'pwned')
    target_outside = os.path.join(os.path.dirname(work), 'escaped.txt')
    if os.path.exists(target_outside): os.unlink(target_outside)

    win2 = main.MainWindow.__new__(main.MainWindow)
    msgs = []
    class _SB:
        def showMessage(s, m): msgs.append(m)
    win2.statusBar = lambda: _SB()
    # smart_extract 内部用 QMessageBox.warning 报错；patch 掉避免弹窗
    orig_warn = main.QMessageBox.warning
    warn_calls = []
    main.QMessageBox.warning = staticmethod(lambda *a, **k: warn_calls.append(a[-1] if a else ''))
    try:
        win2.smart_extract(evil)
    finally:
        main.QMessageBox.warning = orig_warn
    escaped = os.path.exists(target_outside)
    check('#7 Zip-slip 越界写入被阻止', not escaped, f'escaped_file_created={escaped}')
    if os.path.exists(target_outside): os.unlink(target_outside)

    # #4 正常 zip 解压 + 句柄释放 (能删除源 zip 说明无残留句柄)
    good = os.path.join(work, 'good.zip')
    with zipfile.ZipFile(good, 'w') as zf:
        zf.writestr('a.txt', 'hello'); zf.writestr('sub/b.txt', 'world')
    win3 = main.MainWindow.__new__(main.MainWindow)
    win3.statusBar = lambda: _SB()
    win3.smart_extract(good)
    extracted = os.path.exists(os.path.join(work, 'good', 'a.txt')) or os.path.exists(os.path.join(work, 'a.txt'))
    # 多顶层(a.txt + sub) -> 建 good/ 子目录
    extracted = os.path.exists(os.path.join(work, 'good', 'a.txt'))
    check('#4 正常 zip 正确解压', extracted, f'extracted={extracted}')
except Exception as e:
    import traceback; traceback.print_exc()
    check('#4/#7 zip 解压验证', False, repr(e))

print('\n' + '='*50)
passed = sum(1 for _,c,_ in results if c)
print(f"结果: {passed}/{len(results)} 通过")
sys.exit(0 if passed == len(results) else 1)
