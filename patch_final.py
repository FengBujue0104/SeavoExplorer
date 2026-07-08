import io

path = r"D:\Desktop\py-script\ohmypi\main.py"
with io.open(path, 'r', encoding='utf8') as f:
    src = f.read()

patches = [
    # Fix 1: save_file_version - extensionless file overwrite (f[:-0] = '' in Python)
    (
        "                    if ext:\n                        middle = f[len(base_name + '_' + today):-len(ext)]\n                    else:\n                        middle = f[len(base_name + '_' + today):]",
        "                    # 提取后缀：_YYYYMMDD 之后的部分\n                    # 注意：当 ext='' 时，f[:-0] 变成 f[:0]='' 导致无法提取后缀\n                    # 所以这里显式处理 ext 为空的情况\n                    suffix_start = len(base_name + '_' + today)\n                    if ext:\n                        middle = f[suffix_start:-len(ext)]\n                    else:\n                        middle = f[suffix_start:]"
    ),
    # Fix 2: cv2 VideoCapture leak when isOpened() returns False
    (
        "        cap = cv2.VideoCapture(path)\n        if not cap.isOpened():\n            return None",
        "        cap = cv2.VideoCapture(path)\n        if not cap.isOpened():\n            cap.release()\n            return None"
    ),
    # Fix 3: cv2 VideoCapture leak when total_frames <= 0
    (
        "        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))\n        if total_frames <= 0:\n            return None",
        "        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))\n        if total_frames <= 0:\n            cap.release()\n            return None"
    ),
]

for old, new in patches:
    if old in src:
        src = src.replace(old, new, 1)
        print(f"OK - patched: {old[:60]}...")
    else:
        print(f"NOT FOUND: {old[:60]}...")

with io.open(path, 'w', encoding='utf8') as f:
    f.write(src)
print("Done")
