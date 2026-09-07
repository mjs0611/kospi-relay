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


NIGHT = {"강한 상승": "뉴욕이 크게 오른 밤", "상승": "뉴욕이 오른 밤", "보합": "뉴욕이 조용했던 밤",
         "하락": "뉴욕이 내린 밤", "강한 하락": "뉴욕이 크게 내린 밤"}      # 조건을 말로 정의한다
WENT = {"up": "위로", "down": "아래로", "flat": "거의 그대로"}              # 다음 날 시가가 간 곳
LABEL_Z = {"up": "위", "down": "아래", "flat": "거의 그대로"}              # 막대 칸 이름


def tenths(share):
    """0.8 → '10번 중 8번'. 1번 미만이면 100번 단위로."""
    k = round(share * 10)
    return f"10번 중 {k}번" if k else f"100번 중 {round(share * 100)}번"


def zone_of(x):
    return None if x is None else ("up" if x > FLAT else "down" if x < -FLAT else "flat")


def headline(f, opened, status):
    """카드 제목 두 줄. cond = 조건('뉴욕이 크게 오른 밤'), claim = 규칙('다음 날 코스피는 10번 중 8번 위로 열렸다').
    오늘 시가는 제목이 아니라 그림의 마커가 말한다. 예측 아님, 과거 빈도 서술만."""
    if not f:
        return {"cond": "밤사이 뉴욕은 쉬었다", "claim": "", "zone": None}
    cond = NIGHT[f["bin"]]
    if f["n"] < 30:
        return {"cond": cond, "claim": f"비슷한 밤이 {int(f['years'])}년간 {f['n']}번뿐이라 빈도는 생략", "zone": zone_of(opened)}
    maj = max(("up", "down", "flat"), key=lambda z: f[z])
    return {"cond": cond, "claim": f"다음 날 코스피는 {tenths(f[maj] / f['n'])} {WENT[maj]} 열렸다", "zone": maj}


def sentence(f):
    """공유·텔레그램·OG 한 문장 = 제목 두 줄을 이은 것."""
    h = headline(f, None, "pending")
    return f"{h['cond']}. {h['claim']}" if h["claim"] else h["cond"]


def head_html(h):
    e = html.escape
    return (f'<p class="cond">{e(h["cond"])}</p><p class="claim">{e(h["claim"])}</p>' if h["claim"]
            else f'<p class="claim">{e(h["cond"])}</p>')


def relay_svg(us, opened, f, status):
    """★ 원인 → 결과 두 칸. 왼쪽 밤사이 뉴욕(반도체·나스닥100·S&P500 가로 막대), 오른쪽 다음 날 코스피 시가
    빈도 막대 + 오늘 마커. 제목의 '뉴욕이 이럴 때 코스피는 이랬다'를 그대로 그림으로.
    웹·PNG·미니앱이 같은 SVG. 색은 호스트 CSS 변수."""
    W, H = 540, 118
    e = html.escape
    o = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" font-family="var(--sans)">']
    # ── 왼쪽: 밤사이 뉴욕 ──
    o.append('<text x="0" y="13" fill="var(--muted)" font-size="11">밤사이 뉴욕</text>')
    vals = [us[k][1] for k in US if us.get(k)]
    if not vals:
        o.append('<text x="0" y="62" fill="var(--muted)" font-size="12">뉴욕 휴장</text>')
    else:
        x0, unit = 78, 76 / max(0.005, max(abs(v) for v in vals))   # 0선 x, 최대 막대 76px. 값 글자가 화살표(x=222)에 닿지 않게
        o.append(f'<line x1="{x0}" y1="24" x2="{x0}" y2="100" stroke="var(--rule)" stroke-width="1"/>')
        for i, k in enumerate(US):
            w = us.get(k); y = 40 + 24 * i
            o.append(f'<text x="{x0 - 8}" y="{y + 4}" text-anchor="end" fill="var(--muted)" font-size="11">{LABEL[k]}</text>')
            if not w: continue
            v = w[1]; c = color(v); bw = max(2, abs(v) * unit)
            bx = x0 if v >= 0 else x0 - bw
            o.append(f'<rect x="{bx:.1f}" y="{y - 6}" width="{bw:.1f}" height="12" rx="3" fill="{c}"/>')
            o.append(f'<text x="{(x0 + bw if v >= 0 else x0) + 6:.1f}" y="{y + 4}" fill="{c}" font-family="var(--mono)" font-size="12" font-weight="800">{pct(v)}</text>')
    # ── 화살표 ──
    o.append('<path d="M222,46 L236,52 L222,58" fill="none" stroke="var(--muted)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>')   # 두 칸 세로 중심 사이
    # ── 오른쪽: 다음 날 코스피 시가 ──
    L, R = 252, W
    if not f or f["n"] < 30:
        o.append(f'<text x="{L}" y="13" fill="var(--muted)" font-size="11">다음 날 코스피 시가</text>')
        o.append(f'<text x="{L}" y="62" fill="var(--muted)" font-size="12">비슷한 밤이 드물어 빈도는 생략</text>')
    else:
        n = f["n"]; gap = 3; by0, by1 = 30, 56
        o.append(f'<text x="{L}" y="13" fill="var(--muted)" font-size="11">다음 날 코스피 시가, 2021년부터 같은 밤 {n}번</text>')
        x = float(L); centers = {}
        for z, c in (("down", "var(--down)"), ("flat", "var(--flat)"), ("up", "var(--up)")):
            w = (R - L - 2 * gap) * f[z] / n
            if w > 0:
                o.append(f'<rect x="{x:.1f}" y="{by0}" width="{w:.1f}" height="{by1 - by0}" rx="6" fill="{c}"/>')
                lab = f"{LABEL_Z[z]} {f[z] / n:.0%}"
                if w >= len(lab) * 8 + 14:   # 칸에 들어갈 때만 안에 쓴다. 나머지는 아래 범례가 맡는다
                    o.append(f'<text x="{x + w / 2:.1f}" y="{(by0 + by1) / 2 + 4.5:.1f}" text-anchor="middle" fill="var(--paper)" font-size="12" font-weight="700">{lab}</text>')
                centers[z] = (x + w / 2, c)
            x += w + gap
        # 범례: 칸 폭과 무관하게 항상 같은 자리. 좁은 칸의 숫자는 여기서 읽는다
        for z, c, tx, an in (("down", "var(--down)", L, "start"), ("flat", "var(--flat)", (L + R) / 2, "middle"), ("up", "var(--up)", R, "end")):
            o.append(f'<text x="{tx:.1f}" y="{H - 8}" text-anchor="{an}" fill="{c}" font-size="11" font-weight="700">{LABEL_Z[z]} {f[z] / n:.0%}</text>')
        if status == "pending" or opened is None:
            o.append(f'<text x="{(L + R) / 2:.1f}" y="84" text-anchor="middle" fill="var(--muted)" font-size="12">{"오늘 시가는 09:00에" if status == "pending" else "오늘 코스피는 휴장"}</text>')
        else:
            z = zone_of(opened); cx, c = centers.get(z, ((L + R) / 2, "var(--ink)"))
            tx = min(max(cx, L + 56), R - 56)
            o.append(f'<path d="M{cx - 6:.1f},{by1 + 11} L{cx + 6:.1f},{by1 + 11} L{cx:.1f},{by1 + 3} Z" fill="{c}"/>')
            o.append(f'<text x="{tx:.1f}" y="{by1 + 30}" text-anchor="middle"><tspan fill="var(--muted)" font-size="11">오늘 </tspan><tspan font-family="var(--mono)" font-size="15" font-weight="800" fill="{c}">{pct(opened)}</tspan></text>')
    o.append("</svg>")
    return "\n".join(o)


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


def pending_text(status):
    return "09:00에 채워진다" if status == "pending" else ("오늘 휴장" if status == "closed" else "")


def page(D, prev, us, vix_lv, opened, f, status, prev_link):
    date_ko = f"{D.month}월 {D.day}일 {'월화수목금토일'[D.weekday()]}요일"
    pending = pending_text(status)
    svg = relay_svg(us, opened, f, status)
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
.sheet{{position:relative;width:540px;max-width:100%;margin:0 auto;padding:22px 24px 18px;display:flex;flex-direction:column;
background:radial-gradient(70% 24% at 20% -2%,rgba(108,77,224,.55) 0,transparent 62%),
radial-gradient(58% 20% at 97% 3%,rgba(74,59,196,.45) 0,transparent 64%),
radial-gradient(84% 26% at 50% 103%,rgba(31,200,184,.32) 0,transparent 64%),
linear-gradient(180deg,#141438 0,#0A0D1E 46%,var(--void) 100%)}}
/* 원래는 잉크 실선이었다. 다크에선 밝은 실선이 제목보다 세게 튀어 스펙트럼 한 줄로 바꿈 */
header{{position:relative;display:flex;justify-content:space-between;align-items:baseline;padding-bottom:10px}}
header::after{{content:"";position:absolute;left:0;right:0;bottom:0;height:1.5px;background:linear-gradient(90deg,var(--night),var(--dawn),transparent)}}
h1{{font-size:15px;font-weight:800;letter-spacing:-.01em;margin:0}}
.stamp{{font-size:11px;color:var(--muted);text-align:right;line-height:1.5;white-space:nowrap}}.stamp b{{font-family:var(--mono);color:var(--ink);font-weight:700;font-size:11px}}
/* 원인 → 결과 그림. 시간축 광원은 시간축 차트와 함께 폐기 */
.chart{{margin:18px 0 0}}
svg{{width:100%;height:auto;display:block}}
/* 제목 두 줄: 조건(작게, 뮤트) → 규칙(크게, 잉크). 오늘 시가는 그림의 마커가 말한다 */
.cond{{font-size:14px;font-weight:600;color:var(--muted);margin:16px 0 3px;letter-spacing:-.005em}}
.claim{{font-size:21px;font-weight:800;letter-spacing:-.02em;line-height:1.3;margin:0;word-break:keep-all;font-variant-numeric:tabular-nums}}
footer{{margin-top:22px;padding-top:12px;border-top:1px solid var(--rule);font-size:10.5px;color:var(--muted);line-height:1.55;display:flex;justify-content:space-between;gap:12px}}
footer a{{color:var(--dawn)}}
@media (max-width:480px){{.sheet{{padding:18px 14px 16px}}.lede{{font-size:15px}}header{{flex-direction:column;align-items:flex-start;gap:4px}}.stamp{{text-align:left}}}}
</style></head><body><div class="sheet">
<header><h1>밤사이 코스피</h1><div class="stamp">{date_ko} <b>{"06:45" if status=="pending" else "09:06"}</b></div></header>
{head_html(headline(f, opened, status))}
<div class="chart">{svg}</div>
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
        "head": headline(f, opened, status), "sentence": sentence(f) if f and f["n"] else None, "svg": relay_svg(us, opened, f, status),
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
            "head": headline(f, opened, "filled"), "sentence": sentence(f) if f and f["n"] else None, "svg": relay_svg(us, opened, f, "filled")}, ensure_ascii=False, default=float), encoding="utf-8")
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
