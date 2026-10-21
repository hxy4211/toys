# 小面宝宝桌宠 🍼

用宝宝照片做的 Windows 桌面宠物。**只在 DSH Desktop 运行时出现**，关掉就自动躲起来。

<img src="../../preview-states.png" width="900">

（从上到下：待机呼吸 / 跟手右倾 / 跟手左倾 / 睡觉 Zzz / 说话气泡）

---

## 怎么用

**双击 `启动小面.vbs`** 就行，不会弹黑框。

| 操作 | 效果 |
|---|---|
| 鼠标移动 | 头身会朝鼠标方向轻微偏移 + 倾斜（跟手） |
| 按住拖动 | 拖到屏幕任意位置，松手有果冻弹性回弹，位置自动记住 |
| 单击 | 蹦一下 + 冒一句随机台词 |
| 双击 | 睡觉 / 叫醒（睡觉时下沉压扁 + 冒 Zzz） |
| 右键 | 菜单：说句话 / 睡觉 / 回到右下角 / 隐身 10 分钟 / 退出 |

透明区域鼠标会穿透过去，不会挡住你点下面的窗口。

**只在我打开时出现**：桌宠每 0.5 秒检测一次 `DSH Desktop` 进程，没在跑就自动隐藏（进程保留不退出，你重新打开 DSH 它就自己回来）。想让它一直显示，用 `python pet.py --force` 启动。

---

## 文件说明

```
pet/
├─ pet.py                  桌宠主程序（纯 ctypes + Pillow，约 600 行）
├─ 启动小面.vbs            无黑框启动器
├─ state.json              记住的位置（自动生成，不进版本库）
├─ pet.log                 出错日志（自动生成）
├─ assets/
│  ├─ xiaomian.png         抠好的立绘 644×669 透明 PNG
│  ├─ xiaomian-320h.png    桌宠实际用的尺寸
│  ├─ xiaomian-160h.png    小尺寸备用
│  └─ raw/                 原图（未抠）
├─ tools/
│  ├─ cutout.py            抠图脚本（可重复运行，参数在文件头）
│  ├─ finalize.py          从抠图结果生成三种尺寸
│  └─ fetch_wheels.mjs     从镜像下载 wheel（本机 pip 装不了包时的绕路方案）
└─ .pylibs/                Pillow 本体（不进版本库）
```

---

## 技术要点

**透明窗口**：没用 tkinter 的 `-transparentcolor` 色键（会留锯齿白边），而是纯 ctypes 调
`UpdateLayeredWindow` 做逐像素 alpha 的分层窗口，边缘是真正半透明。鼠标经过 alpha<24 的
像素时 `WM_NCHITTEST` 返回 `HTTRANSPARENT`，点击穿透到下层窗口。

**只动整张图**：只有一张正面照，所以除 Zzz 和气泡外所有动效都是整张立绘的位移/旋转/纵向缩放
（呼吸、跟手倾斜、拖拽弹性、睡觉下沉压扁）。果冻回弹用阻尼弹簧：`a = k(目标-当前) - c·v`，
`k=130, c=12`。

**性能**：单帧渲染 5–13 ms（含旋转、缩放、气泡、预乘 alpha），定时器 16 ms 一帧，占用很低（约 68 MB 内存）。

**抠图**：不用 AI 模型，纯 Pillow 手写流程 —— 颜色判据区分"低饱和浅色背景"和"偏红皮肤"→
从四边连通蔓生 → 按面积+质心剔除左右黑车把 → 大核闭运算接上被白领口断开的头身 →
只填小孔洞（避免把椅子坐垫填成实心）→ 边缘守卫 + 羽化。细节见 `tools/cutout.py` 文件头注释。

---

## 换一张照片

1. 把新照片放进 `assets/raw/`
2. 改 `tools/cutout.py` 开头的 `SRC`，按需调 `LUM_SHADOW / CHROMA_MAX / REDNESS_MAX`
3. 跑 `python tools/cutout.py`，看 `debug/checker-*.png` 是否满意
4. 跑 `python tools/finalize.py` 生成三种尺寸
5. `python pet.py --preview` 出状态对比图

---

## 环境说明

这台机器上 `pip` 装不了包（Python 装在 `D:\python`，沙箱禁止写入；解包时还会 `Permission denied`），
所以 Pillow 是手动下载 wheel 解压到 `.pylibs` 的，`pet.py` 启动时自己把该目录加进 `sys.path`。
换台机器可以直接 `pip install pillow`，然后把 `.pylibs` 删掉。
