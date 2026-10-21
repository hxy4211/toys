"""
小面宝宝抠图 v5：纯 Pillow 实现（无 numpy / 无 ML 依赖）

流程：
  1) 颜色判据标出"可当背景"（亮中性 + 暗投影；偏红的皮肤、暗色衣物/头发不算）
  2) 从四边连通蔓生吃掉真背景（墙、白椅、椅上投影）
  3) 连通块过滤：按面积 + 质心水平位置保留主体，丢弃左右黑色车把与顶部暗边
  4) 大核闭运算接上被白领口断开的头/身
  5) 填洞：只填"不与边界连通 且 面积小于阈值"的小孔（白领口），
     避免把椅子坐垫这类大片背景也填成实心
  6) 开运算去毛刺 + 羽化，输出 RGBA PNG
"""
import sys
from collections import deque
from PIL import Image, ImageFilter, ImageDraw, ImageOps

SRC = r"C:\Users\13047\DSwork\toys\pet\assets\raw\xiaomian-original.jpg"
OUT = r"C:\Users\13047\DSwork\toys\pet\assets"

LUM_SHADOW = 150     # 低于此亮度一定不是背景
CHROMA_MAX = 24      # 中性色上限
REDNESS_MAX = 30     # R-B 上限，超过是皮肤
MIN_AREA = 20000     # 保留块最小面积
CX_LO, CX_HI = 0.22, 0.78
BRIDGE_R = 27        # 闭运算核：接白领口断缝
OPEN_R = 9           # 开运算核：去毛刺
FEATHER = 2.2
HOLE_MAX = 12000     # 只填小于此面积的孔洞
BOTTOM_GUARD = 6     # 距底边这么近的空白永不填


def bg_candidate(r, g, b):
    lum = (r * 299 + g * 587 + b * 114) // 1000
    if lum < LUM_SHADOW:
        return False
    if max(r, g, b) - min(r, g, b) > CHROMA_MAX:
        return False
    if r - b > REDNESS_MAX:
        return False
    return True


def main():
    im = Image.open(SRC).convert("RGB")
    w, h = im.size
    px = im.tobytes()

    cand = bytearray(w * h)
    for i in range(w * h):
        if bg_candidate(px[3 * i], px[3 * i + 1], px[3 * i + 2]):
            cand[i] = 1

    # --- 2) 从四边连通蔓生 ---
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

    # --- 3) 连通块过滤 ---
    lab = [0] * (w * h)
    comps = []
    cur = 0
    for i in range(w * h):
        if fg[i] and not lab[i]:
            cur += 1
            q = deque([i]); lab[i] = cur
            n = 0; sx = 0
            while q:
                j = q.popleft()
                n += 1
                x, y = j % w, j // w
                sx += x
                for k, ok in ((j - 1, x > 0), (j + 1, x < w - 1), (j - w, y > 0), (j + w, y < h - 1)):
                    if ok and fg[k] and not lab[k]:
                        lab[k] = cur; q.append(k)
            comps.append((n, cur, sx / n))

    keep = {cid for n, cid, cx in comps if n >= MIN_AREA and CX_LO * w <= cx <= CX_HI * w}
    print(f"保留块 {sorted(keep)} / 共 {len(comps)} 块")

    mask = Image.frombytes("L", (w, h), bytes(
        255 if (fg[i] and lab[i] in keep) else 0 for i in range(w * h)))

    # --- 4) 接白领口断缝 ---
    mask = mask.filter(ImageFilter.MaxFilter(BRIDGE_R)).filter(ImageFilter.MinFilter(BRIDGE_R))

    # --- 4.5) 边缘守卫：闭运算会把贴边的窄条背景（照片底部的白桌面）也糊成前景，
    #           这里把"背景色 + 靠近画面边缘"的像素强制还原成透明
    EDGE_M = 40
    mp = mask.load()
    for y in range(h):
        for x in range(w):
            if mp[x, y] == 0:
                continue
            near = x < EDGE_M or x > w - 1 - EDGE_M or y < EDGE_M or y > h - 1 - EDGE_M
            if near and bg_candidate(px[3 * (y * w + x)], px[3 * (y * w + x) + 1], px[3 * (y * w + x) + 2]):
                mp[x, y] = 0
    print("边缘守卫已应用")

    # --- 5) 只在"小且不贴边"的孔洞里填实 ---
    hole_region = ImageOps.invert(mask)
    hp = hole_region.load()
    solid = mask.load()
    seen = bytearray(w * h)
    filled_total = 0
    for start in range(w * h):
        if hp[start % w, start // w] == 0 or seen[start]:
            continue
        q = deque([start]); seen[start] = 1
        cells = []
        touch_bottom = False
        while q:
            j = q.popleft()
            cells.append(j)
            x, y = j % w, j // w
            if y >= h - BOTTOM_GUARD or x == 0 or x == w - 1 or y == 0:
                touch_bottom = True
            for k, ok in ((j - 1, x > 0), (j + 1, x < w - 1), (j - w, y > 0), (j + w, y < h - 1)):
                if ok and not seen[k] and hp[k % w, k // w] > 0:
                    seen[k] = 1; q.append(k)
        if not touch_bottom and len(cells) <= HOLE_MAX:
            for j in cells:
                solid[j % w, j // w] = 255
            filled_total += len(cells)
    print(f"填充小孔: {filled_total} px")

    # --- 6) 开运算 + 羽化 ---
    mask = mask.filter(ImageFilter.MinFilter(OPEN_R)).filter(ImageFilter.MaxFilter(OPEN_R))
    mask = mask.filter(ImageFilter.GaussianBlur(FEATHER))

    # --- 6.5) 羽化会把边缘守卫清掉的浅色又"糊"回来一圈，这里再守一次 ---
    mp = mask.load()
    for y in range(h):
        for x in range(w):
            v = mp[x, y]
            if not v:
                continue
            near = x < EDGE_M or x > w - 1 - EDGE_M or y < EDGE_M or y > h - 1 - EDGE_M
            if near and bg_candidate(px[3 * (y * w + x)], px[3 * (y * w + x) + 1], px[3 * (y * w + x) + 2]):
                mp[x, y] = 0
    print("羽化后二次守卫完成")

    out = im.convert("RGBA")
    out.putalpha(mask)
    bbox = mask.point(lambda v: 255 if v > 10 else 0).getbbox()
    cut = out.crop(bbox)
    print("裁剪框:", bbox, "-> 尺寸", cut.size)

    # 校验：底部几行不该有大片不透明的浅色
    cp = cut.load()
    cw, ch = cut.size
    bad = 0
    for y in range(max(0, ch - 6), ch):
        for x in range(0, cw, 4):
            r, g, b, a = cp[x, y]
            if a > 200 and min(r, g, b) > 200:
                bad += 1
    print(f"底部白色残留采样点: {bad}（应为 0）")

    cut.save(rf"{OUT}\xiaomian-cutout-v7.png")

    pw, ph = cut.size
    prev = Image.new("RGB", (pw, ph), (255, 255, 255))
    d = ImageDraw.Draw(prev)
    for y in range(0, ph, 24):
        for x in range(0, pw, 24):
            if ((x // 24) + (y // 24)) % 2 == 0:
                d.rectangle([x, y, x + 23, y + 23], fill=(226, 226, 226))
    prev.paste(cut, (0, 0), cut)
    prev.save(r"C:\Users\13047\DSwork\toys\pet\debug\checker-v7.png")
    print("预览 -> debug/checker-v7.png")


if __name__ == "__main__":
    sys.exit(main())


