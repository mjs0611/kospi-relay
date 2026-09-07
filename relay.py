"""밤사이 코스피 — 어제 코스피 마감 → 밤사이 뉴욕 → 오늘 코스피 시가, 한 장.

python relay.py morning   # 06:45 KST: 밤사이 노드 + 조건부 빈도, 시가 노드 비움
python relay.py open      # 09:06 KST: 오늘 시가 채움
python relay.py selfcheck # 정렬·빈도 자기검증
"""
import json, os, sys, html, datetime as dt
from pathlib import Path
import pandas as pd, numpy as np, yfinance as yf
from zoneinfo import ZoneInfo

KST = dt.timezone(dt.timedelta(hours=9))
SITE = Path(__file__).parent / "site"
TICK = {"KOSPI": "^KS11", "KOSDAQ": "^KQ11", "SPY": "SPY", "QQQ": "QQQ", "SOXX": "SOXX", "VIX": "^VIX"}
US = ["SOXX", "QQQ", "SPY"]
LABEL = {"SOXX": "반도체", "QQQ": "나스닥100", "SPY": "S&P500"}
FLAT = 0.003          # 시가 갭 ±0.3% = 보합
BINS = [(-9, -0.005, "강한 하락"), (-0.005, -0.003, "하락"), (-0.003, 0.003, "보합"), (0.003, 0.005, "상승"), (0.005, 9, "강한 상승")]
SITE_URL = os.environ.get("SITE_URL", "https://mjs0611.github.io/kospi-relay")


def fetch():
    out = {}
    for k, t in TICK.items():
        h = yf.Ticker(t).history(start="2021-01-01", auto_adjust=False)
        if h.empty:
            raise RuntimeError(f"no data {t}")
        h.index = h.index.tz_localize(None).normalize()
        out[k] = h[["Open", "Close"]]
    return out


def signal(spy, soxx):
    # ponytail: 고정식. 5년 백테스트에서 롤링 OLS와 차이 ~1.5pt, 재적합 상태 없음
    return 0.4 * (spy + soxx) / 2


def us_window(h, P, D):
    """코스피 전일 종가 P 이후 ~ D 전날까지 미국 세션. (첫 세션 시가%, 누적 종가%, 세션 수) 또는 None."""
    win = h[(h.index >= P) & (h.index <= D - pd.Timedelta(days=1))]
    before = h[h.index < P]
    if win.empty or before.empty:
        return None
    base = before.Close.iloc[-1]
    return win.Open.iloc[0] / base - 1, win.Close.iloc[-1] / base - 1, len(win)


def align(raw):
    """과거 전체: 코스피 D일 갭 vs 그 전 밤 미국. 빈도표 재료."""
    K = raw["KOSPI"]; rows = []
    for i in range(1, len(K)):
        D, P = K.index[i], K.index[i - 1]
        w = {k: us_window(raw[k], P, D) for k in ("SPY", "SOXX")}
        if None in w.values():
            continue
        rows.append({"D": D, "gap": K.Open.iloc[i] / K.Close.iloc[i - 1] - 1, "s": signal(w["SPY"][1], w["SOXX"][1])})
    return pd.DataFrame(rows).set_index("D")


def bin_of(s):
    return next(b for b in BINS if b[0] <= s < b[1])


def frequency(hist, s):
    lo, hi, name = bin_of(s)
    g = hist[(hist.s >= lo) & (hist.s < hi)].gap
    n = len(g)
    up, down = int((g > FLAT).sum()), int((g < -FLAT).sum())
    return {"bin": name, "n": n, "up": up, "flat": n - up - down, "down": down,
            "years": round((hist.index[-1] - hist.index[0]).days / 365.25, 1)}


def sentence(f):
    """공유·텔레그램·OG 한 문장. 아침 헤드라인과 같다."""
    if f["n"] < 30:
        return f"이렇게 마감한 밤은 {int(f['years'])}년간 {f['n']}번뿐이라 빈도는 생략"
    maj = max(("up", "down", "flat"), key=lambda z: f[z])
    return f"뉴욕이 이렇게 마감한 밤 {f['n']}번, 코스피 시가는 {f[maj] / f['n']:.0%}가 {OPENED[maj]}"


OPENED = {"up": "위로 열렸다", "down": "아래로 열렸다", "flat": "±0.3% 안에서 열렸다"}   # 과거 시가가 간 곳
SIDE = {"up": "위쪽", "down": "아래쪽", "flat": "±0.3% 안"}                                   # 오늘 시가가 간 곳


def zone_of(x):
    return None if x is None else ("up" if x > FLAT else "down" if x < -FLAT else "flat")


def headline(f, opened, status):
    """카드 맨 위 한 문장. 아침엔 질문(이런 밤 뒤 시가는 보통 어디?), 시가가 오면 답(오늘은 거기 갔나).
    예측 아님. 과거 빈도와 오늘 시가의 분류만. 누적 적중률은 non-goal이라 만들지 않는다.
    zone은 글이 아니라 차트(시가 점, 평소 구간 음영)가 쓴다. 글은 잉크 한 색."""
    ok = bool(f) and f["n"] >= 30
    maj = max(("up", "down", "flat"), key=lambda z: f[z]) if ok else None
    if status == "pending":
        return {"text": sentence(f) if f else "밤사이 뉴욕 휴장", "zone": maj}
    if status == "closed" or opened is None:
        return {"text": f"오늘은 휴장. {sentence(f)}" if f else "오늘은 휴장", "zone": maj}
    z = zone_of(opened)
    if not ok:
        return {"text": f"코스피 시가 {pct(opened)}. {sentence(f)}" if f else f"코스피 시가 {pct(opened)}", "zone": z}
    share = f[z] / f["n"]
    tail = f"이런 밤 {share:.0%}만 갔던 {SIDE[z]}" if share < 0.4 else f"이런 밤 {share:.0%}가 그랬듯 {SIDE[z]}"
    return {"text": f"코스피 시가 {pct(opened)}, {tail}", "zone": z}


def head_html(h):
    return f'<p class="headline">{html.escape(h["text"])}</p>'


def today_nodes(raw, D):
    K, Q = raw["KOSPI"], raw["KOSDAQ"]
    P = K.index[K.index < D][-1]
    prev = {"date": P, "kospi": K.Close[P] / K.Close[K.index[K.index < P][-1]] - 1,
            "kosdaq": Q.Close[P] / Q.Close[Q.index[Q.index < P][-1]] - 1 if P in Q.index else None}
    us = {k: us_window(raw[k], P, D) for k in US}
    vix = us_window(raw["VIX"], P, D)
    vwin = raw["VIX"][(raw["VIX"].index >= P) & (raw["VIX"].index <= D - pd.Timedelta(days=1))]
    vix_lv = (raw["VIX"][raw["VIX"].index < P].Close.iloc[-1], vwin.Close.iloc[-1]) if vix else None
    opened = K.Open[D] / K.Close[P] - 1 if D in K.index else None
    return prev, us, vix_lv, opened


# ---------- render ----------
def pct(x, sign=True):
    return ("—" if x is None else f"{x * 100:+.2f}%" if sign else f"{x * 100:.2f}%")


def color(x):
    return "var(--flat)" if x is None or abs(x) < 0.0005 else ("var(--up)" if x > 0 else "var(--down)")


def us_hours(day):
    """미국 세션 개장·마감의 KST 시각(어제 15:30 기준 시간축, 24+h). 서머타임 자동."""
    ny = ZoneInfo("America/New_York"); d = pd.Timestamp(day).to_pydatetime().date()
    off = dt.datetime(d.year, d.month, d.day, 12, tzinfo=ny).utcoffset().total_seconds() / 3600   # -4 or -5
    return 9.5 - off + 9, 16 - off + 9                                                          # 22.5/29 (EDT) · 23.5/30 (EST)


def place(x, n_chars, L, R):
    """라벨을 점 오른쪽에, 안 들어가면 왼쫁에. 반환 (anchor, tx)."""
    est = n_chars * 6.6 + 14
    return ("start", x + 12) if x + 12 + est <= R + 40 else ("end", x - 12)


def chart_svg(prev, us, vix_lv, opened, pending_text, us_open_h, us_close_h, f=None):
    W, H = 540, 418
    L, R = 92, 470                 # 축 영역 (왼쪽 시각 라벨 공간 확보)
    x0 = (L + R) / 2
    vals = [prev["kospi"], prev["kosdaq"], opened] + [v for w in us.values() if w for v in w[:2]]
    vals = [abs(v) for v in vals if v is not None]
    rng = max(1.5, np.ceil(max(vals) * 100 * 1.25 * 2) / 2) if vals else 1.5
    sx = lambda v: x0 + (v * 100 / rng) * (R - L) / 2
    # 시간축: 15:30(어제) → 09:00(오늘) 실제 시간 비례
    t0, t1 = 15.5, 24 + 9
    sy = lambda h: 40 + (h - t0) / (t1 - t0) * (H - 80)
    e = html.escape
    o = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" font-family="var(--mono)" font-size="11">']
    # 가로 눈금
    step = 0.5 if rng <= 2 else 1
    v = -np.floor(rng / step) * step
    every = 2 if 2 * rng / step + 1 > 7 else 1   # 라벨 7개 초과면 한 칸 걸러 표기. 숫자 띠가 차트보다 시끄러웠다
    while v <= rng + 1e-9:
        x = sx(v / 100)
        o.append(f'<line x1="{x:.1f}" y1="30" x2="{x:.1f}" y2="{H-30}" stroke="var(--rule)" stroke-width="{1.2 if abs(v)<1e-9 else 0.5}" {"stroke-dasharray=\"2 4\"" if abs(v)>1e-9 else ""}/>')
        if int(round(v / step)) % every == 0:
            o.append(f'<text x="{x:.1f}" y="22" text-anchor="middle" fill="var(--muted)">{v:+.1f}%</text>' if abs(v) > 1e-9 else f'<text x="{x:.1f}" y="22" text-anchor="middle" fill="var(--muted)">0</text>')
        v += step
    # 시각 라벨 + 눈금
    hm = lambda h: f"{int(h) % 24:02d}:{int(round((h % 1) * 60)):02d}"
    for h, lab, sub in [(15.5, "15:30", f"{prev['date']:%-m/%-d} 마감"), (us_open_h, hm(us_open_h), "뉴욕 개장"), (us_close_h, hm(us_close_h), "뉴욕 마감"), (24 + 9, "09:00", "오늘 시가")]:
        y = sy(h)
        o.append(f'<text x="{L-14}" y="{y+4:.1f}" text-anchor="end" fill="var(--ink)" font-weight="600">{lab}</text>')
        o.append(f'<text x="{L-14}" y="{y+17:.1f}" text-anchor="end" fill="var(--muted)" font-family="var(--sans)" font-size="10">{sub}</text>')
        o.append(f'<line x1="{L-8}" y1="{y:.1f}" x2="{L-2}" y2="{y:.1f}" stroke="var(--ink)"/>')
    # 어제 마감 노드 — 맥락일 뿐 질문의 주역이 아니라 톤다운. 주역은 뉴욕 마감→오늘 시가
    y = sy(15.5)
    o.append('<g opacity=".5">')
    for key, r, lab, dy in [("kosdaq", 4, "코스닥", 14), ("kospi", 6, "코스피", -8)]:
        if prev[key] is None: continue
        x = sx(prev[key])
        o.append(f'<line x1="{x0:.1f}" y1="{y:.1f}" x2="{x:.1f}" y2="{y:.1f}" stroke="{color(prev[key])}" stroke-width="2"/>')
        o.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{color(prev[key])}"/>')
        anchor, tx = place(x, len(lab) + 7, L, R)
        o.append(f'<text x="{tx:.1f}" y="{y+dy+4:.1f}" text-anchor="{anchor}" fill="var(--ink)"><tspan font-family="var(--sans)" fill="var(--muted)">{lab} </tspan><tspan font-weight="700">{pct(prev[key])}</tspan></text>')
    o.append('</g>')
    # 뉴욕 세션 (시가→종가 선)
    ya, yb = sy(us_open_h), sy(us_close_h)
    o.append(f'<rect x="{L}" y="{ya:.1f}" width="{R-L}" height="{yb-ya:.1f}" fill="var(--band)"/>')
    if not any(us.values()):
        o.append(f'<text x="{x0}" y="{(ya+yb)/2:.1f}" text-anchor="middle" fill="var(--muted)" font-family="var(--sans)" font-size="13">밤사이 뉴욕 휴장</text>')
    for k in US:
        w = us.get(k)
        if not w: continue
        xa, xb = sx(w[0]), sx(w[1]); c = color(w[1])
        o.append(f'<line x1="{xa:.1f}" y1="{ya:.1f}" x2="{xb:.1f}" y2="{yb:.1f}" stroke="{c}" stroke-width="2.5" stroke-linecap="round"/>')
        o.append(f'<circle cx="{xa:.1f}" cy="{ya:.1f}" r="3" fill="var(--paper)" stroke="{c}" stroke-width="2"/>')
        o.append(f'<circle cx="{xb:.1f}" cy="{yb:.1f}" r="5" fill="{c}"/>')
    # 마감 라벨: 05:00 아래 대기 구간에 x 순서로 층층이 (점과 겹치지 않게)
    for i, k in enumerate(sorted([k for k in US if us.get(k)], key=lambda k: -us[k][1])):   # 오른쪽 점부터 위 행: 지시선이 글자를 안 가로지름
        w = us[k]; xb = sx(w[1])
        anchor, tx = place(xb, len(LABEL[k]) + 7, L, R)
        ly = yb + 14 + 12 * i
        o.append(f'<line x1="{xb:.1f}" y1="{yb+6:.1f}" x2="{xb:.1f}" y2="{ly-3:.1f}" stroke="{color(w[1])}" stroke-width=".8" opacity=".6"/>')
        o.append(f'<text x="{tx-4 if anchor=="start" else tx+4:.1f}" y="{ly+4:.1f}" text-anchor="{anchor}" fill="var(--ink)"><tspan font-family="var(--sans)" fill="var(--muted)">{LABEL[k]} </tspan><tspan font-weight="700">{pct(w[1])}</tspan></text>')
    if vix_lv:
        a, b = vix_lv; c = "var(--down)" if b < a else "var(--up)"   # VIX 상승 = 공포 = 파랑 아님, 붉게: 시장 색과 반대이므로 중립 잉크 사용
        o.append(f'<text x="{R}" y="{ya-8:.1f}" text-anchor="end" fill="var(--muted)" font-size="10" opacity=".8"><tspan font-family="var(--sans)">VIX </tspan>{a:.1f} → {b:.1f}</text>')
    # ★ 오늘 시가 행. 이 카드의 답이 사는 곳. 두 줄로 나눠 겹침을 없앤다:
    #   행(y): 평소 구간 음영 + 연결선 + 점.  아랫줄(y+27): 오늘 숫자, 점 바로 아래 가운데 정렬.
    #   음영 라벨은 위/아래면 음영 안 먼 끝에, 보합이면 음영이 좁아 바로 위에 둔다.
    y = sy(33)
    ok = bool(f) and f["n"] >= 30
    if ok:
        maj = max(("up", "down", "flat"), key=lambda z: f[z]); share = f[maj] / f["n"]
        zx0, zx1 = {"up": (sx(FLAT), R), "down": (L, sx(-FLAT)), "flat": (sx(-FLAT), sx(FLAT))}[maj]
        zc = {"up": "var(--up)", "down": "var(--down)", "flat": "var(--flat)"}[maj]
        o.append(f'<rect x="{zx0:.1f}" y="{y-14:.1f}" width="{zx1-zx0:.1f}" height="28" rx="6" fill="{zc}" opacity=".14"/>')
        lab = f"이런 밤 {share:.0%}는 여기"
        # 라벨은 음영 위, 중앙 쪽 끝. 음영 안에 두면 다수 구간일수록 점이 라벨을 덮는다(9/7 카드에서 확인)
        if maj == "up":     lx, ly_, la = zx0 + 4, y - 19, "start"
        elif maj == "down": lx, ly_, la = zx1 - 4, y - 19, "end"
        else:               lx, ly_, la = x0, y - 19, "middle"
        o.append(f'<text x="{lx:.1f}" y="{ly_:.1f}" text-anchor="{la}" fill="var(--muted)" font-family="var(--sans)" font-size="10">{lab}</text>')
    if opened is None:
        o.append(f'<circle cx="{x0:.1f}" cy="{y:.1f}" r="7" fill="none" stroke="var(--ink)" stroke-width="1.5" stroke-dasharray="3 3"/>')
        o.append(f'<text x="{x0:.1f}" y="{y+27:.1f}" text-anchor="middle" fill="var(--muted)" font-family="var(--sans)" font-size="12">{e(pending_text)}</text>')
    else:
        x = sx(opened); c = color(opened)
        o.append(f'<line x1="{x0:.1f}" y1="{y:.1f}" x2="{x:.1f}" y2="{y:.1f}" stroke="{c}" stroke-width="2.5"/>')
        o.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="9" fill="{c}"/>')
        o.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="13" fill="none" stroke="{c}" stroke-width="1.5" opacity=".45"/>')
        tx = min(max(x, L + 58), R - 58)   # 숫자 줄이 축 밖으로 안 나가게
        o.append(f'<text x="{tx:.1f}" y="{y+29:.1f}" text-anchor="middle" fill="var(--ink)"><tspan font-family="var(--sans)" fill="var(--muted)" font-size="11">코스피 시가 </tspan><tspan font-weight="800" font-size="16" fill="{c}">{pct(opened)}</tspan></text>')
    o.append("</svg>")
    return "\n".join(o)


def freq_html(f):
    if not f or f["n"] == 0:
        return ""
    n = f["n"]; seg = lambda k, c: (f'<div class="seg" style="flex:{f[k]};background:{c}"></div>' if f[k] else "")
    bar = seg("down", "var(--down)") + seg("flat", "var(--flat)") + seg("up", "var(--up)")
    leg = "".join(f'<span style="color:{c}">{lab} {f[k]/n:.0%}</span>' for k, c, lab in [("down", "var(--down)", "아래"), ("flat", "var(--flat)", "±0.3%"), ("up", "var(--up)", "위")])
    return f'<section class="freq"><div class="bar">{bar}</div><p class="legend">{leg}<span class="n">뉴욕 {f["bin"]} 마감 {n}밤</span></p></section>'


def pending_text(status):
    return "09:00에 채워진다" if status == "pending" else ("오늘 휴장" if status == "closed" else "")


def page(D, prev, us, vix_lv, opened, f, status, prev_link):
    date_ko = f"{D.month}월 {D.day}일 {'월화수목금토일'[D.weekday()]}요일"
    pending = pending_text(status)
    us_day = next((raw_d for raw_d in [prev["date"]]), prev["date"])
    svg = chart_svg(prev, us, vix_lv, opened, pending, *us_hours(us_day), f=f)
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>밤사이 코스피 · {D:%Y-%m-%d}</title>
<meta name="description" content="전일 코스피 마감에서 밤사이 뉴욕을 거쳐 오늘 코스피 시가까지, 한 장.">
<meta property="og:title" content="밤사이 코스피 {D:%m.%d}"><meta property="og:image" content="{SITE_URL}/relay.png"><meta property="og:description" content="{html.escape(sentence(f)) if f and f['n'] else '밤사이 흐름 한 장'}">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css">
<link href="https://fonts.googleapis.com/css2?family=Azeret+Mono:wght@500;700;800&display=swap" rel="stylesheet">
<style>
/* 다크 홀로그래픽. 광원(인디고·틸)과 데이터 색(상승 빨강·하락 파랑)은 절대 섞지 않는다 —
   섞으면 등락이 색으로 안 읽힌다. 광원은 카드 바탕, 데이터 색은 차트 안. */
:root{{--paper:#0F1526;--ink:#EAEEF7;--muted:#98A3BC;--rule:rgba(255,255,255,.13);--band:rgba(255,255,255,.05);
/* 상승 빨강·하락 파랑은 한국 시세 관례(아래 고지에도 명시). 다크에서 원래 값은 2.4~3.0:1이라 명도만 올렸다 */
--up:#FF6B5E;--down:#6E9BFF;--flat:#98A3BA;--night:#6C4DE0;--dawn:#1FC8B8;--void:#080B18;
--sans:"Pretendard Variable",Pretendard,-apple-system,"Apple SD Gothic Neo","Noto Sans KR",sans-serif;--mono:"Azeret Mono",ui-monospace,Menlo,monospace}}
*{{box-sizing:border-box}}html,body{{margin:0;background:var(--void);color:var(--ink);font-family:var(--sans);word-break:keep-all}}
/* 스크린샷은 .sheet만 잘라낸다 — 광원을 body가 아니라 카드 안에 둬야 텔레그램 PNG에도 실린다 */
.sheet{{position:relative;width:540px;max-width:100%;margin:0 auto;padding:26px 24px 20px;display:flex;flex-direction:column;min-height:675px;
background:radial-gradient(70% 24% at 20% -2%,rgba(108,77,224,.55) 0,transparent 62%),
radial-gradient(58% 20% at 97% 3%,rgba(74,59,196,.45) 0,transparent 64%),
radial-gradient(84% 26% at 50% 103%,rgba(31,200,184,.32) 0,transparent 64%),
linear-gradient(180deg,#141438 0,#0A0D1E 46%,var(--void) 100%)}}
/* 원래는 잉크 실선이었다. 다크에선 밝은 실선이 제목보다 세게 튀어 스펙트럼 한 줄로 바꿈 */
header{{position:relative;display:flex;justify-content:space-between;align-items:baseline;padding-bottom:10px}}
header::after{{content:"";position:absolute;left:0;right:0;bottom:0;height:1.5px;background:linear-gradient(90deg,var(--night),var(--dawn),transparent)}}
h1{{font-size:20px;font-weight:800;letter-spacing:-.02em;margin:0}}
.stamp{{font-size:11.5px;color:var(--muted);text-align:right;line-height:1.5;letter-spacing:-.01em;white-space:nowrap}}.stamp b{{font-family:var(--mono);color:var(--ink);font-weight:700;font-size:11px}}
/* ★ 시간축 광원 — SVG 세로축이 곧 시간이다(위 15:30 전일 마감 → 아래 09:00 오늘 시가).
   축은 SVG 높이의 10~90% 구간(sy가 40..H-40으로 매핑)이라 스톱을 거기 맞췄다. 장식이 아니라 제목 */
.chart{{flex:1;display:flex;align-items:center;margin:10px -6px 0;border-radius:14px;overflow:hidden;
background:linear-gradient(180deg,rgba(108,77,224,.16) 10%,rgba(24,29,58,.05) 48%,rgba(31,200,184,.13) 90%)}}
svg{{width:100%;height:auto;display:block}}
/* 헤드라인. 카드의 질문 또는 답, 한 문장. 색은 차트가 말한다. 글은 잉크 한 색 */
.headline{{font-size:22px;font-weight:800;letter-spacing:-.022em;line-height:1.3;margin:16px 0 2px;word-break:keep-all;font-variant-numeric:tabular-nums}}
.freq{{border-top:1px solid var(--rule);padding-top:14px;margin-top:4px}}
.bar{{display:flex;height:9px;border-radius:3px;overflow:hidden;gap:2px;box-shadow:inset 0 0 0 1px rgba(255,255,255,.08)}}.seg{{min-width:2px}}
.legend{{display:flex;gap:14px;align-items:baseline;font-family:var(--mono);font-size:11px;font-weight:700;margin:9px 0 0}}.legend .n{{margin-left:auto;font-family:var(--sans);font-weight:500;color:var(--muted)}}
footer{{margin-top:auto;padding-top:14px;font-size:10.5px;color:var(--muted);line-height:1.55;display:flex;justify-content:space-between;gap:12px}}
footer a{{color:var(--dawn)}}
@media (max-width:480px){{.sheet{{padding:18px 14px 16px}}.lede{{font-size:15px}}header{{flex-direction:column;align-items:flex-start;gap:4px}}.stamp{{text-align:left}}}}
</style></head><body><div class="sheet">
<header><h1>밤사이 코스피</h1><div class="stamp">{date_ko} <b>{"06:45" if status=="pending" else "09:06"}</b></div></header>
{head_html(headline(f, opened, status))}
<div class="chart">{svg}</div>
{freq_html(f)}
<footer><span>정보 제공용, 투자 판단 자료 아님</span><span style="white-space:nowrap">{f'<a href="../{prev_link}/">지난 밤 {int(prev_link[5:7])}/{int(prev_link[8:10])}</a> ' if prev_link else ''}{SITE_URL.replace("https://","")}</span></footer>
</div></body></html>"""


# ---------- pipeline ----------
def build(phase):
    now = dt.datetime.now(KST); D = pd.Timestamp(os.environ.get("RELAY_DATE") or now.date())  # RELAY_DATE=YYYY-MM-DD 로컬 재현용
    try: prior = json.loads((SITE / "latest.json").read_text(encoding="utf-8"))   # gh-pages 체크아웃본 — 재시도 크론 판별용
    except Exception: prior = None
    raw = fetch()
    hist = align(raw)
    prev, us, vix_lv, opened = today_nodes(raw, D)
    if phase == "morning":
        opened = None            # 아침엔 시가 노드 비움 (과거 날짜 재현 시에도)
    f = frequency(hist, signal(us["SPY"][1], us["SOXX"][1])) if us.get("SPY") and us.get("SOXX") else None
    # open 단계에 시가가 없어도 휴장으로 단정하지 않는다 — 야후 반영이 09:09보다 늦을 수 있다.
    # 재시도 크론이 뒤따르고, 마지막 크론(RELAY_FINAL=1)에서만 휴장으로 확정한다.
    if phase == "morning": status = "pending"
    elif opened is not None: status = "filled"
    else: status = "closed" if os.environ.get("RELAY_FINAL") else "pending"
    prev_link = f"{prev['date']:%Y-%m-%d}" if (SITE / f"{prev['date']:%Y-%m-%d}").exists() else None
    htm = page(D, prev, us, vix_lv, opened, f, status, prev_link)
    day = SITE / f"{D:%Y-%m-%d}"; day.mkdir(parents=True, exist_ok=True)
    (day / "index.html").write_text(htm.replace('href="../', 'href="../'), encoding="utf-8")
    (SITE / "index.html").write_text(htm.replace('href="../', 'href="./'), encoding="utf-8")
    payload = json.dumps({"date": f"{D:%Y-%m-%d}", "status": status, "prev": {**prev, "date": f"{prev['date']:%Y-%m-%d}"},
        "us": {k: (list(w[:2]) if w else None) for k, w in us.items()}, "vix": vix_lv, "open": opened, "freq": f,
        "head": headline(f, opened, status), "sentence": sentence(f) if f and f["n"] else None, "svg": chart_svg(prev, us, vix_lv, opened, pending_text(status), *us_hours(prev["date"]), f=f),
        "built_at": dt.datetime.now(KST).isoformat(timespec="minutes")}, ensure_ascii=False, default=float)
    (SITE / "latest.json").write_text(payload, encoding="utf-8")
    (SITE / "days").mkdir(exist_ok=True); (SITE / "days" / f"{D:%Y-%m-%d}.json").write_text(payload, encoding="utf-8")
    (SITE / "index.json").write_text(json.dumps(sorted((p.stem for p in (SITE / "days").glob("*.json")), reverse=True)), encoding="utf-8")
    (SITE / ".nojekyll").touch()
    screenshot(SITE / "index.html", SITE / "relay.png")
    already_sent = bool(prior) and prior.get("date") == f"{D:%Y-%m-%d}" and prior.get("status") == "pending"   # 아침 재시도 크론
    if phase == "morning" and os.environ.get("TELEGRAM_BOT_TOKEN") and not already_sent:
        telegram(SITE / "relay.png", sentence(f) if f else "밤사이 뉴욕 휴장")
    print(f"built {D.date()} {status} freq={f}")


def backfill(n):
    raw = fetch(); hist = align(raw); K = raw["KOSPI"]
    for D in K.index[-n:]:
        prev, us, vix_lv, opened = today_nodes(raw, D)
        f = frequency(hist, signal(us["SPY"][1], us["SOXX"][1])) if us.get("SPY") and us.get("SOXX") else None
        day = SITE / f"{D:%Y-%m-%d}"; day.mkdir(parents=True, exist_ok=True)
        (day / "index.html").write_text(page(D, prev, us, vix_lv, opened, f, "filled", None), encoding="utf-8")
        (SITE / "days").mkdir(exist_ok=True)
        (SITE / "days" / f"{D:%Y-%m-%d}.json").write_text(json.dumps({"date": f"{D:%Y-%m-%d}", "status": "filled", "prev": {**prev, "date": f"{prev['date']:%Y-%m-%d}"},
            "us": {k: (list(w[:2]) if w else None) for k, w in us.items()}, "vix": vix_lv, "open": opened, "freq": f,
            "head": headline(f, opened, "filled"), "sentence": sentence(f) if f and f["n"] else None, "svg": chart_svg(prev, us, vix_lv, opened, "", *us_hours(prev["date"]), f=f)}, ensure_ascii=False, default=float), encoding="utf-8")
    (SITE / "index.json").write_text(json.dumps(sorted((p.stem for p in (SITE / "days").glob("*.json")), reverse=True)), encoding="utf-8")
    print("backfilled", n)


def screenshot(html_path, png):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(); pg = b.new_page(viewport={"width": 540, "height": 675}, device_scale_factor=2)
        pg.goto(html_path.resolve().as_uri(), wait_until="networkidle")
        pg.evaluate("document.fonts.ready"); pg.wait_for_timeout(300)
        pg.locator(".sheet").screenshot(path=str(png)); b.close()


def telegram(png, caption):
    import requests
    requests.post(f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendPhoto",
                  data={"chat_id": os.environ["TELEGRAM_CHAT_ID"], "caption": f"{caption}\n{SITE_URL}"}, files={"photo": open(png, "rb")}, timeout=30).raise_for_status()


def selfcheck():
    raw = fetch(); hist = align(raw)
    g = hist.loc["2025-04-07", "gap"]; assert abs(g - (-0.0431)) < 0.001, g          # 관세 폭락 날 실측 -4.31%
    assert hist.loc["2025-04-10", "gap"] > 0.04                                      # 유예 발표 반등
    f = frequency(hist, 0.006); assert f["up"] + f["flat"] + f["down"] == f["n"] and f["up"] / f["n"] > 0.8, f
    tot = sum(frequency(hist, (lo + min(hi, 0.02)) / 2)["n"] for lo, hi, _ in BINS); assert tot == len(hist), (tot, len(hist))
    assert "위로" in sentence(f)
    print("selfcheck ok", len(hist), f)


if __name__ == "__main__":
    {"morning": lambda: build("morning"), "open": lambda: build("open"), "selfcheck": selfcheck,
     "backfill": lambda: backfill(int(sys.argv[2]) if len(sys.argv) > 2 else 20)}[sys.argv[1]]()
