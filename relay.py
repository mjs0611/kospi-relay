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


# 말투: 해요체, 짧게, 구어. fx-signal("환전하기 좋아요")과 같은 목소리. 신문체(열렸다)·합쇼체(열렸습니다) 금지
NIGHT = {"강한 상승": "지난밤 뉴욕이 크게 올랐어요", "상승": "지난밤 뉴욕이 조금 올랐어요", "보합": "지난밤 뉴욕은 잠잠했어요",
         "하락": "지난밤 뉴욕이 조금 내렸어요", "강한 하락": "지난밤 뉴욕이 크게 내렸어요"}   # 조건을 말로
WENT = {"up": "올라서 시작했어요", "down": "내려서 시작했어요", "flat": "거의 그대로 시작했어요"}   # 다음 날 시가
LABEL_Z = {"up": "상승", "down": "하락", "flat": "보합"}                                  # 행 이름은 증권 앱 표준어


def tenths(share):
    """0.8 → '10번 중 8번'. 1번 미만이면 100번 단위로."""
    k = round(share * 10)
    return f"10번 중 {k}번" if k else f"100번 중 {round(share * 100)}번"


def zone_of(x):
    return None if x is None else ("up" if x > FLAT else "down" if x < -FLAT else "flat")


def headline(f, opened, status):
    """카드 제목 두 줄. cond = 조건('지난밤 뉴욕이 크게 올랐어요'), claim = 규칙('코스피는 10번 중 8번 올라서 시작했어요').
    오늘 시가는 제목이 아니라 그림의 마커가 말한다. 예측 아님, 과거 빈도 서술만. 말투는 해요체."""
    if not f:
        return {"cond": "지난밤 뉴욕은 휴장이었어요", "claim": "", "zone": None}
    cond = NIGHT[f["bin"]]
    if f["n"] < 30:
        return {"cond": cond, "claim": f"비슷한 밤이 {f['n']}번뿐이라 통계는 안 냈어요", "zone": zone_of(opened)}
    maj = max(("up", "down", "flat"), key=lambda z: f[z])
    return {"cond": cond, "claim": f"코스피는 {tenths(f[maj] / f['n'])} {WENT[maj]}", "zone": maj}


def sentence(f):
    """공유·텔레그램·OG 한 문장 = 제목 두 줄을 이은 것."""
    h = headline(f, None, "pending")
    return f"{h['cond']}. {h['claim']}" if h["claim"] else h["cond"]


def tail_text(status, closed_pct, open_h):
    """15:40 마감 박자. 오늘을 닫고 오늘 밤을 예고한다. 일별 종가만 쓴다(인트라데이 아님)."""
    if status != "done" or closed_pct is None:
        return None
    hm = f"{int(open_h) % 24:02d}:{int(round((open_h % 1) * 60)):02d}"
    return f"오늘 코스피는 {pct(closed_pct)}로 마감했어요. 뉴욕은 {hm}에 열려요"


def head_html(h):
    """(밤 쪽 조건, 낮 쪽 규칙) 두 조각. 조건은 밤에, 규칙은 낮에 산다."""
    e = html.escape
    return (f'<p class="cond">{e(h["cond"])}</p>', f'<p class="claim">{e(h["claim"] or "오늘 코스피 시가")}</p>')


def ny_svg(us):
    """밤 쪽: 밤사이 뉴욕. 호가창처럼 행마다 0선에서 뻗는 가로 막대(반도체·나스닥100·S&P500). 236×84.
    색은 호스트 CSS 변수. 폰에선 낮 쪽 위에 쌓인다."""
    W, H = 236, 84
    o = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" font-family="var(--sans)" font-size="12">']
    vals = [us[k][1] for k in US if us.get(k)]
    if not vals:
        o.append('<text x="0" y="46" fill="var(--muted)">뉴욕은 휴장이었어요</text>')
    else:
        # 호가창처럼 길이 = 크기, 색 = 방향. 음수를 왼쪽으로 뻗게 하면 라벨을 침범한다(9/7 카드에서 확인)
        x0, unit = 76, 100 / max(0.005, max(abs(v) for v in vals))   # 막대 시작 x, 최대 막대 100px
        o.append(f'<line x1="{x0}" y1="2" x2="{x0}" y2="{H - 2}" stroke="var(--rule)" stroke-width="1"/>')
        for i, k in enumerate(US):
            w = us.get(k); y = 16 + 26 * i
            o.append(f'<text x="{x0 - 8}" y="{y + 4}" text-anchor="end" fill="var(--muted)">{LABEL[k]}</text>')
            if not w: continue
            v = w[1]; c = color(v); bw = max(2, abs(v) * unit)
            o.append(f'<rect x="{x0}" y="{y - 7}" width="{bw:.1f}" height="14" fill="{c}"/>')
            o.append(f'<text x="{x0 + bw + 6:.1f}" y="{y + 4}" fill="{c}" font-weight="700">{pct(v)}</text>')
    o.append("</svg>")
    return "\n".join(o)


def kr_svg(f, opened, status):
    """낮 쪽: 다음 날 코스피 시가. 호가창처럼 위 / 거의 그대로 / 아래 세 행, 막대 길이 = 그 밤들의 비율.
    시가가 오면 오늘이 속한 행을 칠하고 오른쪽 끝에 '오늘 +3.34%'. 320×100."""
    W, H = 320, 100
    o = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" font-family="var(--sans)" font-size="12">']
    if not f or f["n"] < 30:
        o.append('<text x="0" y="46" fill="var(--muted)">비슷한 밤이 적어 통계는 안 냈어요</text>')
        o.append("</svg>"); return "\n".join(o)
    n = f["n"]; bx, bmax = 82, 120   # 막대 시작 x, 100% = 120px
    z_today = zone_of(opened) if status in ("filled", "done") and opened is not None else None
    for i, z in enumerate(("up", "flat", "down")):
        y = 16 + 28 * i; share = f[z] / n; c = {"up": "var(--up)", "flat": "var(--flat)", "down": "var(--down)"}[z]
        if z == z_today:
            o.append(f'<rect x="0" y="{y - 13}" width="{W}" height="26" fill="{c}" opacity=".12"/>')
        o.append(f'<text x="0" y="{y + 4}" fill="var(--ink)" font-weight="{700 if z == z_today else 500}">{LABEL_Z[z]}</text>')
        o.append(f'<rect x="{bx}" y="{y - 7}" width="{max(2, share * bmax):.1f}" height="14" fill="{c}"/>')
        o.append(f'<text x="{bx + max(2, share * bmax) + 6:.1f}" y="{y + 4}" fill="{c}" font-weight="700">{share:.0%}</text>')
        if z == z_today:
            o.append(f'<text x="{W}" y="{y + 4}" text-anchor="end" fill="var(--ink)"><tspan fill="var(--muted)">오늘 </tspan><tspan font-weight="800" font-size="14" fill="{c}">{pct(opened)}</tspan></text>')
    if z_today is None:
        o.append(f'<text x="{W}" y="{H - 2}" text-anchor="end" fill="var(--muted)" font-size="11">{"오늘 시가는 9시에 나와요" if status == "pending" else "오늘은 휴장이에요"}</text>')
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
    closed_pct = K.Close[D] / K.Close[P] - 1 if D in K.index else None   # 장중엔 현재가. close 단계에서만 믿는다
    return prev, us, vix_lv, opened, closed_pct


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


def page(D, prev, us, vix_lv, opened, f, status, prev_link, tail=None):
    date_ko = f"{D.month}월 {D.day}일 {'월화수목금토일'[D.weekday()]}요일"
    stamp_t = {"pending": "06:45", "done": "15:40"}.get(status, "09:06")   # f-string 안에 dict 리터럴은 못 쓴다
    pending = pending_text(status)
    ny, kr = ny_svg(us), kr_svg(f, opened, status)
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>밤사이 코스피 · {D:%Y-%m-%d}</title>
<meta name="description" content="전일 코스피 마감에서 밤사이 뉴욕을 거쳐 오늘 코스피 시가까지, 한 장.">
<meta property="og:title" content="밤사이 코스피 {D:%m.%d}"><meta property="og:image" content="{SITE_URL}/relay.png"><meta property="og:description" content="{html.escape(sentence(f)) if f and f['n'] else '밤사이 흐름 한 장'}">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css">
<style>
/* 밤 / 낮 두 쪽. 왼쪽은 밤사이 뉴욕(어둡게), 오른쪽은 다음 날 코스피 시가(밝게). 경계가 곧 릴레이.
   채도는 상승 빨강·하락 파랑뿐. 그라디언트·그림자·글로우·모노 폰트 없음. 폰트는 Pretendard 하나, 숫자는 tnum. */
:root{{--sans:"Pretendard Variable",Pretendard,-apple-system,"Apple SD Gothic Neo","Noto Sans KR",sans-serif}}
*{{box-sizing:border-box}}html,body{{margin:0;background:#DDE1E6;font-family:var(--sans);word-break:keep-all;font-variant-numeric:tabular-nums}}
.sheet{{width:540px;max-width:100%;margin:0 auto;display:grid;grid-template-columns:230px 1fr;border-radius:10px;overflow:hidden;background:#EEF0F3}}
.night{{background:#15171D;color:#FFF;padding:20px 20px 22px;--ink:#FFF;--muted:#A7ADBA;--up:#FF6B5E;--down:#6E9BFF;--flat:#9AA3B5;--rule:rgba(255,255,255,.2)}}
.day{{padding:20px 22px 22px;color:#10172A;--ink:#10172A;--muted:#6C7488;--up:#D9433B;--down:#2C5FD6;--flat:#6F7890;--rule:#CFD5DE}}
.brand{{font-size:13px;font-weight:700;color:var(--muted);margin:0}}
.stamp{{font-size:11.5px;color:var(--muted);text-align:right;margin:0}}.stamp b{{color:var(--ink)}}
.cond{{font-size:19px;font-weight:800;letter-spacing:-.02em;line-height:1.3;margin:28px 0 0}}
.claim{{font-size:20px;font-weight:800;letter-spacing:-.02em;line-height:1.3;margin:24px 0 0}}
.lab{{font-size:11px;color:var(--muted);margin:26px 0 8px}}
svg{{width:100%;height:auto;display:block}}
.cap{{font-size:11px;color:var(--muted);margin:10px 0 0}}
.tail{{font-size:13px;font-weight:600;line-height:1.4;margin:16px 0 0}}
footer{{grid-column:1/-1;display:flex;justify-content:space-between;gap:12px;padding:12px 22px 14px;border-top:1px solid #CFD5DE;font-size:10.5px;color:#6C7488}}
footer a{{color:#2C5FD6}}
@media (max-width:480px){{.sheet{{grid-template-columns:1fr}}.cond{{margin-top:18px}}.claim{{margin-top:4px}}}}
</style></head><body><div class="sheet">
<section class="night"><p class="brand">밤사이 코스피</p>{head_html(headline(f, opened, status))[0]}<p class="lab">밤사이 뉴욕</p>{ny}</section>
<section class="day"><p class="stamp">{date_ko} <b>{stamp_t}</b></p>{head_html(headline(f, opened, status))[1]}<p class="lab">다음 날 코스피 시가</p>{kr}{f'<p class="cap">2021년부터 비슷한 밤 {f["n"]}번</p>' if f and f["n"] >= 30 else ''}{f'<p class="tail">{html.escape(tail)}</p>' if tail else ''}</section>
<footer><span>정보 제공용, 투자 판단 자료 아님</span><span style="white-space:nowrap">{f'<a href="../{prev_link}/">지난 밤 {int(prev_link[5:7])}/{int(prev_link[8:10])}</a> ' if prev_link else ''}{SITE_URL.replace("https://","")}</span></footer>
</div></body></html>"""


# ---------- pipeline ----------
def build(phase):
    now = dt.datetime.now(KST); D = pd.Timestamp(os.environ.get("RELAY_DATE") or now.date())  # RELAY_DATE=YYYY-MM-DD 로컬 재현용
    raw = fetch()
    hist = align(raw)
    prev, us, vix_lv, opened, closed_pct = today_nodes(raw, D)
    if phase == "morning":
        opened = None            # 아침엔 시가 노드 비움 (과거 날짜 재현 시에도)
    if phase != "close":
        closed_pct = None        # 장중 야후 일봉의 Close는 현재가. 마감 단계에서만 쓴다
    f = frequency(hist, signal(us["SPY"][1], us["SOXX"][1])) if us.get("SPY") and us.get("SOXX") else None
    # open 단계에 시가가 없어도 휴장으로 단정하지 않는다 — 야후 반영이 09:09보다 늦을 수 있다.
    # 재시도 크론이 뒤따르고, 마지막 크론(RELAY_FINAL=1)에서만 휴장으로 확정한다.
    if phase == "morning": status = "pending"
    elif opened is None: status = "closed" if os.environ.get("RELAY_FINAL") else "pending"
    elif closed_pct is not None: status = "done"     # 15:40 마감 반영
    else: status = "filled"
    tail = tail_text(status, closed_pct, us_hours(D)[0])
    prev_link = f"{prev['date']:%Y-%m-%d}" if (SITE / f"{prev['date']:%Y-%m-%d}").exists() else None
    htm = page(D, prev, us, vix_lv, opened, f, status, prev_link, tail)
    day = SITE / f"{D:%Y-%m-%d}"; day.mkdir(parents=True, exist_ok=True)
    (day / "index.html").write_text(htm.replace('href="../', 'href="../'), encoding="utf-8")
    (SITE / "index.html").write_text(htm.replace('href="../', 'href="./'), encoding="utf-8")
    payload = json.dumps({"date": f"{D:%Y-%m-%d}", "status": status, "prev": {**prev, "date": f"{prev['date']:%Y-%m-%d}"},
        "us": {k: (list(w[:2]) if w else None) for k, w in us.items()}, "vix": vix_lv, "open": opened, "close": closed_pct, "tail": tail, "freq": f,
        "head": headline(f, opened, status), "sentence": sentence(f) if f and f["n"] else None, "ny": ny_svg(us), "kr": kr_svg(f, opened, status),
        "built_at": dt.datetime.now(KST).isoformat(timespec="minutes")}, ensure_ascii=False, default=float)
    (SITE / "latest.json").write_text(payload, encoding="utf-8")
    (SITE / "days").mkdir(exist_ok=True); (SITE / "days" / f"{D:%Y-%m-%d}.json").write_text(payload, encoding="utf-8")
    write_index()
    (SITE / ".nojekyll").touch()
    screenshot(SITE / "index.html", SITE / "relay.png")
    print(f"built {D.date()} {status} freq={f}")


def write_index():
    """index.json = [{d: 날짜, z: 그날 시가 방향}] 최신순. 미니앱 '지난 밤들' 칩이 색 점으로 쓴다."""
    rows = []
    for q in sorted((SITE / "days").glob("*.json"), reverse=True):
        try: z = zone_of(json.loads(q.read_text(encoding="utf-8")).get("open"))
        except Exception: z = None
        rows.append({"d": q.stem, "z": z})
    (SITE / "index.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")


def backfill(n):
    raw = fetch(); hist = align(raw); K = raw["KOSPI"]
    for D in K.index[-n:]:
        prev, us, vix_lv, opened, closed_pct = today_nodes(raw, D)
        f = frequency(hist, signal(us["SPY"][1], us["SOXX"][1])) if us.get("SPY") and us.get("SOXX") else None
        day = SITE / f"{D:%Y-%m-%d}"; day.mkdir(parents=True, exist_ok=True)
        (day / "index.html").write_text(page(D, prev, us, vix_lv, opened, f, "done", None, None), encoding="utf-8")
        (SITE / "days").mkdir(exist_ok=True)
        (SITE / "days" / f"{D:%Y-%m-%d}.json").write_text(json.dumps({"date": f"{D:%Y-%m-%d}", "status": "done", "prev": {**prev, "date": f"{prev['date']:%Y-%m-%d}"},
            "us": {k: (list(w[:2]) if w else None) for k, w in us.items()}, "vix": vix_lv, "open": opened, "close": closed_pct, "tail": None, "freq": f,
            "head": headline(f, opened, "done"), "sentence": sentence(f) if f and f["n"] else None, "ny": ny_svg(us), "kr": kr_svg(f, opened, "done")}, ensure_ascii=False, default=float), encoding="utf-8")
    write_index()
    print("backfilled", n)


def screenshot(html_path, png):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(); pg = b.new_page(viewport={"width": 540, "height": 675}, device_scale_factor=2)
        pg.goto(html_path.resolve().as_uri(), wait_until="networkidle")
        pg.evaluate("document.fonts.ready"); pg.wait_for_timeout(300)
        pg.locator(".sheet").screenshot(path=str(png)); b.close()


def selfcheck():
    raw = fetch(); hist = align(raw)
    g = hist.loc["2025-04-07", "gap"]; assert abs(g - (-0.0431)) < 0.001, g          # 관세 폭락 날 실측 -4.31%
    assert hist.loc["2025-04-10", "gap"] > 0.04                                      # 유예 발표 반등
    f = frequency(hist, 0.006); assert f["up"] + f["flat"] + f["down"] == f["n"] and f["up"] / f["n"] > 0.8, f
    tot = sum(frequency(hist, (lo + min(hi, 0.02)) / 2)["n"] for lo, hi, _ in BINS); assert tot == len(hist), (tot, len(hist))
    assert "올라서" in sentence(f)
    print("selfcheck ok", len(hist), f)


if __name__ == "__main__":
    {"morning": lambda: build("morning"), "open": lambda: build("open"), "close": lambda: build("close"), "selfcheck": selfcheck,
     "backfill": lambda: backfill(int(sys.argv[2]) if len(sys.argv) > 2 else 20)}[sys.argv[1]]()
