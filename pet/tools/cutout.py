"""
抠图 v10：方向性闭运算

v7 用 27×27 的方形闭运算去接白领口断缝，副作用是把手/手臂旁边的椅背白区也糊进轮廓（白色凹口）。

v10 改成有方向的闭运算：
  * 纵向闭合（竖直长条结构元）—— 专门接"头 ↔ 身体"之间被白领口切断的水平缝
  * 横向闭合（水平短条结构元）—— 专门接"手臂 ↔ 身体"之间被白荷叶袖切断的竖直缝
两种方向都不会跨过斜向的大片背景，所以不会糊出白块。

其余沿用 v7：颜色判据 + 四边蔓生 + 剔除黑车把 + 连通块过滤 + 中部小孔填充 + 边缘守卫 + 羽化。
"""
import sys
from collections import deque
from PIL import Image, ImageChops, ImageFilter, ImageDraw, ImageOps

SRC = r"C:\Users\13047\DSwork\toys\pet\assets\raw\xiaomian-original.jpg"
OUT = r"C:\Users\13047\DSwork\toys\pet\assets"
DBG = r"C:\Users\13047\DSwork\toys\pet\debug"

LUM_SHADOW = 150
CHROMA_MAX = 24
REDNESS_MAX = 30

MIN_AREA = 20000
ARM_MIN_AREA = 8000
CX_LO, CX_HI = 0.22, 0.78

HANDLE_LUM = 50
HANDLE_CHROMA = 10
HANDLE_MIN_AREA = 2000
HANDLE_ZONE_X = 0.25
HANDLE_ZONE_Y = 0.65

CLOSE_V = 41        # 纵向闭合长度（接颈口）
CLOSE_H = 21        # 横向闭合长度（接袖口）
ISO_R = 13          # 补充方形闭运算，补掉被吃掉的荷叶边缺口
OPEN_R = 5
HOLE_MAX = 12000
HOLE_CX_LO, HOLE_CX_HI = 0.28, 0.85
BOTTOM_GUARD = 6
EDGE_M = 40
FEATHER = 2.0


def bg_candidate(r, g, b):
    lum = (r * 299 + g * 587 + b * 114) // 1000
    if lum < LUM_SHADOW:
        return False
    if max(r, g, b) - min(r, g, b) > CHROMA_MAX:
        return False
    return not (r - b > REDNESS_MAX)


def shifted(img, dx, dy):
    out = Image.new("L", img.size, 0)
    out.paste(img, (dx, dy))
    return out


def dilate_line(img, length, axis):
    half = length // 2
    out = img
    for k in range(1, half + 1):
        d = (k, 0) if axis == "x" else (0, k)
        out = ImageChops.lighter(out, shifted(img, *d))
        out = ImageChops.lighter(out, shifted(img, -d[0], -d[1]))
    return out


def close_line(img, length, axis):
    """方向性闭运算：沿某个轴用长条结构元先膨胀后腐蚀"""
    return ImageChops.invert(dilate_line(ImageChops.invert(dilate_line(img, length, axis)),
                                         length, axis))


def main():
    im = Image.open(SRC).convert("RGB")
    w, h = im.size
    px = im.tobytes()

    # 1) 颜色候选 + 2) 四边蔓生
    cand = bytearray(w * h)
    for i in range(w * h):
        if bg_candidate(px[3 * i], px[3 * i + 1], px[3 * i + 2]):
            cand[i] = 1

    bg = bytearray(w * h)
    q = deque()
    for x in range(w):
        q.append(x); q.append((h - 1) * w + x)
    for y in range(h):
        q.append(y * w); q.append(y * w + w - 1)
    while q:
        i = q.popleft()
        if bg[i] or not cand[i]:
            continue
        bg[i] = 1
        x, y = i % w, i // w
        if x > 0: q.append(i - 1)
        if x < w - 1: q.append(i + 1)
        if y > 0: q.append(i - w)
        if y < h - 1: q.append(i + w)
    print(f"连通背景: {sum(bg) / (w * h):.1%}")

    fg = bytearray(1 if not v else 0 for v in bg)

    # 3) 剔除黑色车把（左车把和左手臂是连成一整块的，只能按颜色在像素层面抠掉）
    dark_like = bytearray(w * h)
    for i in range(w * h):
        r, g, b = px[3 * i], px[3 * i + 1], px[3 * i + 2]
        lum = (r * 299 + g * 587 + b * 114) // 1000
        if lum < HANDLE_LUM and (max(r, g, b) - min(r, g, b)) < HANDLE_CHROMA:
            dark_like[i] = 1
    seen_h = bytearray(w * h)
    for start in range(w * h):
        if not dark_like[start] or seen_h[start]:
            continue
        q = deque([start]); seen_h[start] = 1
        cells = []
        minx, miny, maxx, maxy = w, h, 0, 0
        while q:
            j = q.popleft(); cells.append(j)
            x, y = j % w, j // w
            minx = min(minx, x); maxx = max(maxx, x)
            miny = min(miny, y); maxy = max(maxy, y)
            for k, ok in ((j - 1, x > 0), (j + 1, x < w - 1), (j - w, y > 0), (j + w, y < h - 1)):
                if ok and dark_like[k] and not seen_h[k]:
                    seen_h[k] = 1; q.append(k)
        cy = (miny + maxy) / 2
        if (len(cells) >= HANDLE_MIN_AREA and cy > HANDLE_ZONE_Y * h
                and (maxx < HANDLE_ZONE_X * w or minx > (1 - HANDLE_ZONE_X) * w)):
            for j in cells:
                x, y = j % w, j // w
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        nx, ny = x + dx, y + dy
                        if 0 <= nx < w and 0 <= ny < h and fg[ny * w + nx]:
                            fg[ny * w + nx] = 0
            print(f"  剔除车把 area={len(cells)} bbox=({minx},{miny},{maxx},{maxy})")

    # 4) 连通块过滤
    lab = [0] * (w * h)
    comps = []
    cur = 0
    for i in range(w * h):
        if fg[i] and not lab[i]:
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

    mask = Image.frombytes("L", (w, h), bytes(
        255 if (fg[i] and lab[i] in keep) else 0 for i in range(w * h)))

    # 5) 方向性闭运算
    mask = close_line(mask, CLOSE_H, "x")
    mask = close_line(mask, CLOSE_V, "y")
    if ISO_R:
        mask = mask.filter(ImageFilter.MaxFilter(ISO_R)).filter(ImageFilter.MinFilter(ISO_R))
        print(f"补充方形闭运算: {ISO_R}")

    # 边缘守卫
    mp = mask.load()
    for y in range(h):
        for x in range(w):
            if not mp[x, y]:
                continue
            near = x < EDGE_M or x > w - 1 - EDGE_M or y < EDGE_M or y > h - 1 - EDGE_M
            if near and bg_candidate(px[3 * (y * w + x)], px[3 * (y * w + x) + 1], px[3 * (y * w + x) + 2]):
                mp[x, y] = 0

    # 6) 只填中部小孔
    hole = ImageOps.invert(mask)
    hp = hole.load()
    solid = mask.load()
    seen = bytearray(w * h)
    filled = 0
    for start in range(w * h):
        if hp[start % w, start // w] == 0 or seen[start]:
            continue
        q = deque([start]); seen[start] = 1
        cells = []; touch = False; sx = 0
        while q:
            j = q.popleft(); cells.append(j)
            x, y = j % w, j // w
            sx += x
            if y >= h - BOTTOM_GUARD or x == 0 or x == w - 1 or y == 0:
                touch = True
            for k, ok in ((j - 1, x > 0), (j + 1, x < w - 1), (j - w, y > 0), (j + w, y < h - 1)):
                if ok and not seen[k] and hp[k % w, k // w] > 0:
                    seen[k] = 1; q.append(k)
        cx = sx / len(cells)
        if not touch and HOLE_CX_LO * w <= cx <= HOLE_CX_HI * w and len(cells) <= HOLE_MAX:
            for j in cells:
                solid[j % w, j // w] = 255
            filled += len(cells)
    print(f"填充小孔: {filled} px")

    mask = mask.filter(ImageFilter.MinFilter(OPEN_R)).filter(ImageFilter.MaxFilter(OPEN_R))
    mask = mask.filter(ImageFilter.GaussianBlur(FEATHER))

    mp = mask.load()
    for y in range(h):
        for x in range(w):
            if not mp[x, y]:
                continue
            near = x < EDGE_M or x > w - 1 - EDGE_M or y < EDGE_M or y > h - 1 - EDGE_M
            if near and bg_candidate(px[3 * (y * w + x)], px[3 * (y * w + x) + 1], px[3 * (y * w + x) + 2]):
                mp[x, y] = 0

    out = im.convert("RGBA")
    out.putalpha(mask)
    bbox = mask.point(lambda v: 255 if v > 10 else 0).getbbox()
    cut = out.crop(bbox)
    print("裁剪框:", bbox, "尺寸", cut.size)

    tag = "final"
    cut.save(rf"{OUT}\xiaomian-cutout-{tag}.png")
    mask.save(rf"{DBG}\mask-{tag}.png")

    pw, ph = cut.size
    prev = Image.new("RGB", (pw, ph), (255, 255, 255))
    d = ImageDraw.Draw(prev)
    for y in range(0, ph, 20):
        for x in range(0, pw, 20):
            if ((x // 20) + (y // 20)) % 2 == 0:
                d.rectangle([x, y, x + 19, y + 19], fill=(222, 222, 222))
    prev.paste(cut, (0, 0), cut)
    prev.save(rf"{DBG}\checker-{tag}.png")
    print(f"预览 -> debug/checker-{tag}.png")


if __name__ == "__main__":
    sys.exit(main())


