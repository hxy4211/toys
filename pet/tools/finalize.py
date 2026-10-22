from PIL import Image
base = r"C:\Users\13047\DSwork\toys\pet\assets"
im = Image.open(base + r"\xiaomian-cutout.png").convert("RGBA")
bbox = im.split()[3].point(lambda v: 255 if v > 8 else 0).getbbox()
im = im.crop(bbox)
im.save(base + r"\xiaomian.png")
print("正式素材:", im.size)
for th in (320, 220, 160):
    r = th / im.size[1]
    s = im.resize((round(im.size[0]*r), th), Image.LANCZOS)
    s.save(base + rf"\xiaomian-{th}h.png")
    print(f"  {th}h ->", s.size)
# 边缘放大检查
reg = (60, 90, 220, 200)
c = im.crop(reg)
bg = Image.new("RGB", c.size, (40, 42, 48)); bg.paste(c, (0,0), c)
bg.resize((c.width*5, c.height*5), Image.NEAREST).save(r"C:\Users\13047\DSwork\toys\pet\debug\edge-zoom3.png")
print("edge zoom saved")
