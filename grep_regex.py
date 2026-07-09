import io

path = r"D:\Desktop\py-script\ohmypi\main.py"
with io.open(path, 'r', encoding='utf8') as f:
    src = f.read()

# 查找 regex 相关行
for i, line in enumerate(src.split('\n'), 1):
    if 'regex' in line.lower() and ('save' in line.lower() or 'get' in line.lower() or 'regex_state' in line.lower() or 'custom_' in line.lower()):
        print(f"{i}: {line.rstrip()}")
