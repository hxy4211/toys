from PIL import Image
base = r"C:\Users\13047\DSwork\toys\pet\assets"
im = Image.open(base + r"\xiaomian-cutout-v7.png").convert("RGBA")
bbox = im.split()[3].point(lambda v: 255 if v > 8 else 0).getbbox()
im = im.crop(bbox)
im.save(base + r"\xiaomian.png")
print("正式素材:", im.size)
for target_h in (320, 160):
    r = target_h / im.size[1]
    s = im.resize((round(im.size[0]*r), target_h), Image.LANCZOS)
    s.save(base + rf"\xiaomian-{target_h}h.png")
    print(f"缩放版 {target_h}h ->", s.size)
# 校验底部
px = im.load(); w,h = im.size
bad = sum(1 for y in range(h-6, h) for x in range(0, w, 4) if px[x,y][3] > 8 and min(px[x,y][:3]) > 200)
print("底部浅色残留:", bad)
