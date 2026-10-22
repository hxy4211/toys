"""
小面宝宝抠图（最终版）
======================
纯 Pillow 实现，不用任何 AI 模型。

判据
----
1. **颜色**：白色椅背/墙面 = 亮(≥150) + 中性(色度<24) + 不偏红(R-B<30)；
   皮肤明显偏红(R-B≈60)，头发/深裙很暗 —— 这两类一定不是背景。
2. **纹理**：白荷叶边和白椅背颜色完全重叠（亮度都 190~240、色度都 <20），单靠颜色分不开。
   但荷叶边有褶皱、局部方差高（实测 365~2010），墙和椅背平滑（方差≈0）。
   于是"高纹理"也算主体，荷叶边就不会被当成背景吃掉 —— 手臂和身体因此天然连通，
   不再需要大核闭运算去补缝（那样会糊出白色凹口）。

流程
----
  1) 逐像素分类：主体 = 非背景色 ∪ 高纹理
  2) 剔除黑色车把：近乎纯黑的中性色 + 位于画面外侧下方
     ⚠ 左手臂和左车把在二值图里是**连成一整块**的，只能按颜色在像素层面挖掉车把，
       再清掉车把包围盒内的非皮肤残留；整块丢弃会把手臂一起丢掉。
  3) 连通块过滤：面积 + 质心/肤色组合规则
  4) 小核闭运算 + 填内部孔洞 + 小开运算
  5) 边缘守卫（贴边的背景色像素强制透明）
  6) 收缩 2px 再羽化 + 边缘去白边（反解混入的背景色），避免小尺寸下出现白圈
"""
import sys
from collections import deque

from PIL import Image, ImageChops, ImageDraw, ImageFilter

SRC = r"C:\Users\13047\DSwork\toys\pet\assets\raw\xiaomian-original.jpg"
OUT = r"C:\Users\13047\DSwork\toys\pet\assets"
DBG = r"C:\Users\13047\DSwork\toys\pet\debug"

# ---- 颜色判据（用于判定"像背景"）----
LUM_MIN = 150        # 背景亮度下限
CHROMA_MAX = 24      # 背景色度上限
REDNESS_MAX = 30     # R-B 上限，超过就是皮肤

# ---- 纹理判据 ----
VAR_RADIUS = 5
VAR_THRESHOLD = 250  # 局部方差大于此值视为有褶皱的布料

# ---- 黑色车把 ----
HANDLE_LUM = 50
HANDLE_CHROMA = 10
HANDLE_MIN_AREA = 2000
HANDLE_ZONE_X = 0.25     # 左车把 bbox 右界 < 0.25w；右车把 bbox 左界 > 0.75w
HANDLE_ZONE_Y = 0.65     # 且竖向中心 > 0.65h

# ---- 连通块 ----
MIN_AREA = 20000
ARM_MIN_AREA = 8000
CX_LO, CX_HI = 0.18, 0.82

# ---- 形态学 / 边缘 ----
CLOSE_R = 9
OPEN_R = 3
HOLE_MAX = 20000
EDGE_M = 40
SHRINK_R = 5         # 羽化前收缩（约 2px）
FEATHER = 1.6
BG_ESTIMATE = (236, 236, 230)


def bg_like(r, g, b):
    lum = (r * 299 + g * 587 + b * 114) // 1000
    if lum < LUM_MIN:
        return False
    if max(r, g, b) - min(r, g, b) > CHROMA_MAX:
        return False
    return not (r - b > REDNESS_MAX)


def variance_mask(im, radius, threshold):
    """局部方差 > threshold 的像素（荷叶边等有褶皱的布料）"""
    g = im.convert("L")
    mean_img = g.filter(ImageFilter.BoxBlur(radius))
    mean_sq = ImageChops.multiply(g, g).filter(ImageFilter.BoxBlur(radius))
    mb, m2b = mean_img.tobytes(), mean_sq.tobytes()
    # ImageChops.multiply 按 /255 缩放，还原时要乘回 255
    return bytearray(1 if m2b[i] * 255.0 - mb[i] * mb[i] > threshold else 0
                     for i in range(len(mb)))


def remove_handles(fg, px, w, h):
    """剔除黑色车把手（连同它周围一圈非皮肤的过渡像素）"""
    dark = bytearray(w * h)
    for i in range(w * h):
        r, g, b = px[3 * i], px[3 * i + 1], px[3 * i + 2]
        lum = (r * 299 + g * 587 + b * 114) // 1000
        if lum < HANDLE_LUM and (max(r, g, b) - min(r, g, b)) < HANDLE_CHROMA:
            dark[i] = 1

    seen = bytearray(w * h)
    removed = 0
    for start in range(w * h):
        if not dark[start] or seen[start]:
            continue
        q = deque([start]); seen[start] = 1
        cells = []
        minx, miny, maxx, maxy = w, h, 0, 0
        while q:
            j = q.popleft(); cells.append(j)
            x, y = j % w, j // w
            minx = min(minx, x); maxx = max(maxx, x)
            miny = min(miny, y); maxy = max(maxy, y)
            for k, ok in ((j - 1, x > 0), (j + 1, x < w - 1), (j - w, y > 0), (j + w, y < h - 1)):
                if ok and dark[k] and not seen[k]:
                    seen[k] = 1; q.append(k)

        cy = (miny + maxy) / 2
        if not (len(cells) >= HANDLE_MIN_AREA and cy > HANDLE_ZONE_Y * h
                and (maxx < HANDLE_ZONE_X * w or minx > (1 - HANDLE_ZONE_X) * w)):
            continue   # 不在外侧下方 -> 不是车把（可能是头发里的暗块）

        pad = 20
        for y in range(max(0, miny - pad), min(h, maxy + pad + 1)):
            for x in range(max(0, minx - pad), min(w, maxx + pad + 1)):
                i = y * w + x
                if not fg[i]:
                    continue
                r, g, b = px[3 * i], px[3 * i + 1], px[3 * i + 2]
                lum = (r * 299 + g * 587 + b * 114) // 1000
                if r - b > 35 and lum > 80:
                    continue   # 皮肤：保留（压在这个包围盒里的手臂）
                fg[i] = 0
        removed += len(cells)
        print(f"  剔除车把 area={len(cells)} bbox=({minx},{miny},{maxx},{maxy})")
    print(f"车把合计 {removed} px")


def keep_components(fg, px, w, h):
    """连通块过滤：面积够大且质心居中，或面积中等但肤色占比高（手臂）"""
    lab = [0] * (w * h)
    comps = []
    cur = 0
    for i in range(w * h):
        if not fg[i] or lab[i]:
            continue
        cur += 1
        q = deque([i]); lab[i] = cur
        n = sx = skin = 0
        while q:
            j = q.popleft()
            n += 1
            x, y = j % w, j // w
            sx += x
            r, g, b = px[3 * j], px[3 * j + 1], px[3 * j + 2]
            lum = (r * 299 + g * 587 + b * 114) // 1000
            if r - b > 40 and lum > 90:
                skin += 1
            for k, ok in ((j - 1, x > 0), (j + 1, x < w - 1), (j - w, y > 0), (j + w, y < h - 1)):
                if ok and fg[k] and not lab[k]:
                    lab[k] = cur; q.append(k)
        comps.append((n, cur, sx / n, skin / n))

    keep = set()
    for n, cid, cx, skin in sorted(comps, reverse=True):
        mid = CX_LO * w <= cx <= CX_HI * w
        if (n >= MIN_AREA and mid) or (n >= ARM_MIN_AREA and skin >= 0.40):
            keep.add(cid)
            print(f"  保留 #{cid} area={n} 质心x={cx:.0f} 肤色={skin:.0%}")
    print(f"保留 {len(keep)} 块 / 共 {len(comps)} 块")
    return lab, keep


def fill_holes(mask):
    """填充不与画面边界连通、且面积不大的内部孔洞（荷叶边内部的平滑部分）"""
    inv = ImageChops.invert(mask)
    ip = inv.load()
    solid = mask.load()
    w, h = mask.size
    seen = bytearray(w * h)
    filled = 0
    for start in range(w * h):
        if ip[start % w, start // w] == 0 or seen[start]:
            continue
        q = deque([start]); seen[start] = 1
        cells = []
        touch = False
        while q:
            j = q.popleft(); cells.append(j)
            x, y = j % w, j // w
            if x == 0 or y == 0 or x == w - 1 or y == h - 1:
                touch = True
            for k, ok in ((j - 1, x > 0), (j + 1, x < w - 1), (j - w, y > 0), (j + w, y < h - 1)):
                if ok and not seen[k] and ip[k % w, k // w] > 0:
                    seen[k] = 1; q.append(k)
        if not touch and len(cells) <= HOLE_MAX:
            for j in cells:
                solid[j % w, j // w] = 255
            filled += len(cells)
    print(f"填内部孔洞: {filled} px")


def edge_guard(mask, px, w, h):
    """贴边的像素如果是背景色，强制透明（闭运算会把贴边白条糊成前景）"""
    mp = mask.load()
    cleared = 0
    for y in range(h):
        for x in range(w):
            if not mp[x, y]:
                continue
            near = x < EDGE_M or x > w - 1 - EDGE_M or y < EDGE_M or y > h - 1 - EDGE_M
            if near and bg_like(px[3 * (y * w + x)], px[3 * (y * w + x) + 1], px[3 * (y * w + x) + 2]):
                mp[x, y] = 0
                cleared += 1
    print(f"边缘守卫清除: {cleared} px")


def decontaminate(img, bg=BG_ESTIMATE):
    """边缘去白边：羽化后的半透明像素里混着原背景（浅白），
    按 observed = a*fg + (1-a)*bg 反解出 fg，小尺寸下才不会出现白圈。"""
    px = img.load()
    w, h = img.size
    n = 0
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if 0 < a < 250:
                af = max(a / 255.0, 0.25)
                inv = 1.0 - af
                px[x, y] = (
                    max(0, min(255, int((r - inv * bg[0]) / af))),
                    max(0, min(255, int((g - inv * bg[1]) / af))),
                    max(0, min(255, int((b - inv * bg[2]) / af))),
                    a,
                )
                n += 1
    print(f"去白边: 处理 {n} 个边缘像素")
    return img


def main():
    im = Image.open(SRC).convert("RGB")
    w, h = im.size
    px = im.tobytes()

    # 1) 逐像素分类
    var = variance_mask(im, VAR_RADIUS, VAR_THRESHOLD)
    print(f"高纹理像素: {sum(var) / (w * h):.1%}")

    fg = bytearray(w * h)
    for i in range(w * h):
        if not bg_like(px[3 * i], px[3 * i + 1], px[3 * i + 2]):
            fg[i] = 1                 # 皮肤 / 头发 / 裙子
        elif var[i]:
            fg[i] = 1                 # 荷叶边
    print(f"初始主体: {sum(fg) / (w * h):.1%}")

    # 2) 车把
    remove_handles(fg, px, w, h)

    # 3) 连通块
    lab, keep = keep_components(fg, px, w, h)
    mask = Image.frombytes("L", (w, h), bytes(
        255 if (fg[i] and lab[i] in keep) else 0 for i in range(w * h)))

    # 4) 形态学
    mask = mask.filter(ImageFilter.MaxFilter(CLOSE_R)).filter(ImageFilter.MinFilter(CLOSE_R))
    fill_holes(mask)
    mask = mask.filter(ImageFilter.MinFilter(OPEN_R)).filter(ImageFilter.MaxFilter(OPEN_R))

    # 5) 边缘守卫
    edge_guard(mask, px, w, h)

    # 6) 收缩 + 羽化 + 去白边
    if SHRINK_R:
        mask = mask.filter(ImageFilter.MinFilter(SHRINK_R))
    mask = mask.filter(ImageFilter.GaussianBlur(FEATHER))

    out = im.convert("RGBA")
    out.putalpha(mask)
    bbox = mask.point(lambda v: 255 if v > 10 else 0).getbbox()
    cut = out.crop(bbox)
    cut = decontaminate(cut)
    print("裁剪框:", bbox, "尺寸", cut.size)
    cut.save(rf"{OUT}\xiaomian-cutout.png")

    # 棋盘预览
    pw, ph = cut.size
    prev = Image.new("RGB", (pw, ph), (255, 255, 255))
    d = ImageDraw.Draw(prev)
    for y in range(0, ph, 20):
        for x in range(0, pw, 20):
            if ((x // 20) + (y // 20)) % 2 == 0:
                d.rectangle([x, y, x + 19, y + 19], fill=(222, 222, 222))
    prev.paste(cut, (0, 0), cut)
    prev.save(rf"{DBG}\checker.png")
    print(f"输出 -> {OUT}\\xiaomian-cutout.png")


if __name__ == "__main__":
    sys.exit(main())
