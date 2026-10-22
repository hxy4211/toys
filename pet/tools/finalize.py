"""
从小面抠图结果生成桌宠实际使用的素材。

流程：cutout.py -> assets/xiaomian-cutout.png（原始抠图，带透明外边）
      本脚本     -> assets/xiaomian.png（裁掉透明边的主素材）
                  -> assets/xiaomian-320h.png（桌宠运行时真正加载的尺寸）
中间产物 xiaomian-cutout.png 不进版本库，缺失时本脚本会自动重跑 cutout.py。
"""
import subprocess
import sys
from pathlib import Path

from PIL import Image

BASE = Path(__file__).resolve().parent.parent      # pet/
ASSETS = BASE / "assets"
CUTOUT = ASSETS / "xiaomian-cutout.png"
MASTER = ASSETS / "xiaomian.png"
RUNTIME = ASSETS / "xiaomian-320h.png"
SPRITE_H = 320

if not CUTOUT.exists():
    print("缺少中间产物 xiaomian-cutout.png，正在重新抠图...")
    subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "cutout.py")], check=True)

im = Image.open(CUTOUT).convert("RGBA")
bbox = im.split()[3].point(lambda v: 255 if v > 8 else 0).getbbox()
im = im.crop(bbox)
im.save(MASTER)
print("主素材:", im.size, "->", MASTER.name)

ratio = SPRITE_H / im.size[1]
sprite = im.resize((round(im.size[0] * ratio), SPRITE_H), Image.LANCZOS)
sprite.save(RUNTIME)
print(f"运行素材 {SPRITE_H}h ->", sprite.size, "->", RUNTIME.name)
