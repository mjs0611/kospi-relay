"""렌더된 픽셀에서 글자 대비를 실측한다.

왜 계산이 아니라 실측인가: 이 UI는 반투명 유리 뒤로 광원이 비치고, 차트 SVG는
시간축 그라디언트 위에 얹힌다. 표면 색만 놓고 계산하면 통과하는 값이 실제 화면에서는
떨어진다. 합성 결과를 보지 않으면 알 수 없다. 색·투명도·광원을 건드리면 다시 돌릴 것.

사용법:
  1. (cd app && npx vite build) && (cd app/dist && python3 -m http.server 5202)
  2. 브라우저로 열어 뷰포트/전체 스크린샷 PNG와, 아래 형태의 JSON을 저장
     {dpr, vw, vh, items:[{sel, rect:{x,y,w,h}, color, fontSize, fontWeight}]}
     (SVG 텍스트는 color 자리에 computed `fill`을 넣는다)
  3. python3 contrast-check.py <shot.png> <probe.json>   # 미달이 있으면 exit 1

기준: WCAG AA. 본문 4.5:1, 대형(24px+ 또는 18.66px+ & 700) 3:1.
"""
import json, re, sys
from PIL import Image

shot, probe = (sys.argv[1], sys.argv[2]) if len(sys.argv) > 2 else ('.kospi-shot.png', '.kospi-probe.json')
im = Image.open(shot).convert('RGB')
d = json.loads(re.search(r'\{.*\}', open(probe).read(), re.S).group(0))
dpr, (W, H) = d['dpr'], im.size

def lin(c):
    c /= 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
def L(rgb):
    return 0.2126 * lin(rgb[0]) + 0.7152 * lin(rgb[1]) + 0.0722 * lin(rgb[2])
def ratio(a, b):
    la, lb = L(a), L(b); hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)
def parse(c):
    return tuple(int(float(x)) for x in re.findall(r'[\d.]+', c)[:3])
def hexc(t):
    return '#%02X%02X%02X' % t

def bg_band(r):
    """HTML 요소: 위아래 띠에서 배경을 뽑고 가장 밝은 표본(최악)을 고른다."""
    px = []
    for f in (0.05, 0.25, 0.5, 0.75, 0.95):
        for dy in (-5, -3, r['h'] + 3, r['h'] + 5):
            X, Y = int((r['x'] + r['w'] * f) * dpr), int((r['y'] + dy) * dpr)
            if 0 <= X < W and 0 <= Y < H:
                px.append(im.getpixel((X, Y)))
    return max(px, key=L) if px else None

def bg_mode(r, fg):
    """SVG 텍스트: 라벨이 13px 간격으로 붙어 있어 위아래 띠를 뜨면 옆 글자를 집는다.
    bbox 안에서 글자색 근방(글리프·안티에일리어싱)을 걷어내고 남은 것 중 가장 밝은 픽셀
    = 최악의 배경. 최빈색은 굵은 짧은 글자에서 글리프가 다수가 돼 못 쓴다."""
    x0, y0 = int(r['x'] * dpr), int(r['y'] * dpr)
    x1, y1 = int((r['x'] + r['w']) * dpr), int((r['y'] + r['h']) * dpr)
    from collections import Counter
    near = lambda p: sum((p[i] - fg[i]) ** 2 for i in range(3)) < 90 ** 2
    px = [im.getpixel((X, Y))
          for Y in range(max(0, y0), min(H, y1))
          for X in range(max(0, x0), min(W, x1))]
    if not px:
        return None
    rest = Counter(p for p in px if not near(p))
    if not rest:
        return min(px, key=L)
    # 안티에일리어싱 가장자리는 색이 제각각이라 각각 드물고, 진짜 배경은 같은 색이 반복된다.
    # 그래서 빈출 상위만 후보로 두고, 그중 가장 밝은 것(=최악)을 고른다.
    return max((c for c, _ in rest.most_common(5)), key=L)

def bg_sample(r, sel, fg):
    return bg_mode(r, fg) if sel.startswith('svg') else bg_band(r)

print(f"viewport {d['vw']}x{d['vh']} dpr {dpr}  shot {W}x{H}")
print(f"\n{'요소':30} {'글자':9} {'배경(최악)':10} {'대비':>6} {'필요':>5}  판정")
fails = []
for it in d['items']:
    fg, r = parse(it['color']), it['rect']
    bg = bg_sample(r, it['sel'], fg)
    if bg is None:
        continue
    cr = ratio(fg, bg)
    fs, fw = float(it['fontSize'][:-2]), int(it['fontWeight'])
    need = 3.0 if (fs >= 24 or (fs >= 18.66 and fw >= 700)) else 4.5
    ok = cr >= need
    if not ok:
        fails.append((it['sel'], round(cr, 2), need))
    print(f"{it['sel']:30} {hexc(fg):9} {hexc(bg):10} {cr:6.2f} {need:5.1f}  {'OK' if ok else '미달'}")

print('\n미달:', fails if fails else '없음')
sys.exit(1 if fails else 0)
