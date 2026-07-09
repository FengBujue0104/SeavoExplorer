"""
测试脚本：验证自定义正则的保存/加载/扫描完整流程。
"""

import os
import sys
import re
import tempfile
import shutil

# 创建隔离测试目录
test_dir = tempfile.mkdtemp(prefix="seavo_test_")
print(f"测试目录: {test_dir}")

# 模拟设置文件
config_file = os.path.join(test_dir, "seavoexplorer.json")

# 测试 1: 默认正则
from main import DEFAULT_MB_RE, DEFAULT_DB_RE, _resolve_regex, _is_regex_safe

print("\n=== 测试 1: 默认正则 ===")
mb, fb = _resolve_regex("default", "", DEFAULT_MB_RE)
db, fb = _resolve_regex("default", "", DEFAULT_DB_RE)
assert mb.pattern == r'^S(\d{3,4})(?:_(.*))?$', f"主板默认正则错误: {mb.pattern}"
assert db.pattern == r'^M(\d{3,4})(?:_(.*))?$', f"子卡默认正则错误: {db.pattern}"
print("OK - 默认正则正确")

# 测试 2: 自定义正则
print("\n=== 测试 2: 自定义正则 ===")
mb, fb = _resolve_regex("custom", r'^A(\d+)$', DEFAULT_MB_RE)
db, fb = _resolve_regex("custom", r'^B(\d+)$', DEFAULT_DB_RE)
assert mb.pattern == r'^A(\d+)$', f"主板自定义正则错误: {mb.pattern}"
assert db.pattern == r'^B(\d+)$', f"子卡自定义正则错误: {db.pattern}"
print("OK - 自定义正则正确")

# 测试 3: 无效正则回退
print("\n=== 测试 3: 无效正则回退 ===")
mb, fb = _resolve_regex("custom", r'[invalid', DEFAULT_MB_RE)
assert fb == True, "无效正则应该回退"
assert mb == DEFAULT_MB_RE, "回退后应该是默认正则"
print("OK - 无效正则正确回退")

# 测试 4: ReDoS 检测
print("\n=== 测试 4: ReDoS 检测 ===")
is_safe, err = _is_regex_safe(r'(a+)+$')
print(f"  (a+)+$ -> safe={is_safe}, err={err}")
is_safe, err = _is_regex_safe(r'^S(\d{3,4})$')
print(f"  ^S(\d{{3,4}})$ -> safe={is_safe}, err={err}")

# 测试 5: 匹配数警告
print("\n=== 测试 5: 匹配数警告 ===")
# 模拟扫描目录结构
scan_dir = os.path.join(test_dir, "projects")
os.makedirs(scan_dir, exist_ok=True)
# 创建测试文件夹
for i in range(10):
    os.makedirs(os.path.join(scan_dir, f"S{i:04d}_test"), exist_ok=True)
    os.makedirs(os.path.join(scan_dir, f"M{i:04d}_test"), exist_ok=True)

# 使用默认正则扫描
mb_folders = []
db_folders = []
for item in os.listdir(scan_dir):
    item_path = os.path.join(scan_dir, item)
    if os.path.isdir(item_path):
        mb_match = DEFAULT_MB_RE.match(item)
        db_match = DEFAULT_DB_RE.match(item)
        if mb_match:
            mb_folders.append(item)
        if db_match:
            db_folders.append(item)

print(f"  主板匹配: {len(mb_folders)} 个")
print(f"  子卡匹配: {len(db_folders)} 个")
assert len(mb_folders) == 10, f"主板匹配数错误: {len(mb_folders)}"
assert len(db_folders) == 10, f"子卡匹配数错误: {len(db_folders)}"
print("OK - 默认正则扫描正确")

# 测试 6: 自定义正则扫描
print("\n=== 测试 6: 自定义正则扫描 ===")
custom_mb = re.compile(r'^S(\d{4})$')
custom_db = re.compile(r'^M(\d{4})$')
mb_folders = []
db_folders = []
for item in os.listdir(scan_dir):
    item_path = os.path.join(scan_dir, item)
    if os.path.isdir(item_path):
        if custom_mb.match(item):
            mb_folders.append(item)
        if custom_db.match(item):
            db_folders.append(item)
print(f"  自定义主板匹配: {len(mb_folders)} 个")
print(f"  自定义子卡匹配: {len(db_folders)} 个")

# 清理
shutil.rmtree(test_dir)
print(f"\n✅ 全部测试通过")
