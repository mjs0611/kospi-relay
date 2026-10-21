"""밤사이 코스피 — 어제 코스피 마감 → 밤사이 뉴욕 → 오늘 코스피 시가, 한 장.

python relay.py morning   # 06:45 KST: 밤사이 노드 + 조건부 빈도, 시가 노드 비움
python relay.py open      # 09:06 KST: 오늘 시가 채움
python relay.py selfcheck # 정렬·빈도 자기검증
"""
import json, os, sys, html, datetime as dt
import hashlib, re
from html.parser import HTMLParser
from pathlib import Path
import shutil, time
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
ADSENSE_SLOT = os.environ.get("ADSENSE_SLOT", "")
ADSENSE = os.environ.get("ADSENSE_CLIENT", "")  # ca-pub-… 저장소 변수. 비면 광고 스크립트 없음
WEB_ANALYTICS = '<script defer src="https://ditoaxis.com/m.js"></script>'
WEB_ANALYTICS_NOTICE = """<h2>방문 통계</h2>
<p><a href="https://www.cloudflare.com/web-analytics/">Cloudflare Web Analytics</a>로 방문 통계(페이지 주소, 유입 경로, 브라우저·기기 종류, 국가, 로딩 성능)를 수집합니다. 쿠키나 기기 식별자를 사용하지 않으며, 개인을 알아볼 수 없는 집계로만 확인합니다.</p>
"""


def fetch():
    out = {}
    for k, t in TICK.items():
        last = None
        for attempt, delay in enumerate((0, 2, 5), 1):
            if delay:
                time.sleep(delay)
            try:
                h = yf.Ticker(t).history(start="2021-01-01", auto_adjust=False, timeout=15)
                if h.empty:
                    raise ValueError("empty history")
                h.index = h.index.tz_localize(None).normalize()
                if h.index.has_duplicates or h.index.hasnans:
                    raise ValueError("invalid history dates")
                h = h[["Open", "Close"]].apply(pd.to_numeric, errors="coerce").sort_index()
                h = h.where(np.isfinite(h) & (h > 0))  # 행·날짜는 보존, 무효 가격만 결측 처리
                last = h
                if h.iloc[-1].notna().all():
                    break
                print(f"{t}: incomplete latest prices ({attempt}/3)")
            except Exception as exc:  # 외부 응답 경계. 마지막 실패는 배포를 막아 기존 자료를 보존한다.
                print(f"{t}: fetch {attempt}/3 failed: {exc}")
        if last is None:
            raise RuntimeError(f"no usable history for {t} after 3 attempts")
        out[k] = last
    return out


def change(price, base):
    if any(x is None or not np.isfinite(x) or x <= 0 for x in (price, base)):
        return None
    value = price / base - 1
    return value if np.isfinite(value) else None


def signal(spy, soxx):
    # ponytail: 고정식. 5년 백테스트에서 롤링 OLS와 차이 ~1.5pt, 재적합 상태 없음
    if spy is None or soxx is None:
        return np.nan
    return 0.4 * (spy + soxx) / 2


def us_window(h, P, D):
    """코스피 전일 종가 P 이후 ~ D 전날까지 미국 세션. (첫 세션 시가%, 누적 종가%, 세션 수) 또는 None."""
    win = h[(h.index >= P) & (h.index <= D - pd.Timedelta(days=1))]
    before = h[h.index < P]
    if win.empty:
        return None
    if before.empty:
        return None, None, len(win)
    base = before.Close.iloc[-1]
    # 세션을 삭제하면 전날 종가를 최신 종가로 오인한다. 존재하지만 미완성인 밤은 따로 보존한다.
    prices = [base, win.Open.iloc[0], win.Close.iloc[-1]]
    if not all(np.isfinite(p) and p > 0 for p in prices):
        return None, None, len(win)
    return win.Open.iloc[0] / base - 1, win.Close.iloc[-1] / base - 1, len(win)


def known_us_sessions(raw):
    """A session seen in a peer index is not a holiday in an index that omitted it."""
    keys = [k for k in (*US, "VIX") if k in raw]
    dates = pd.DatetimeIndex([])
    for k in keys:
        dates = dates.union(raw[k].index)
    return {**raw, **{k: raw[k].reindex(dates.sort_values()) for k in keys}}


def align(raw):
    """과거 전체: 코스피 D일 갭 vs 그 전 밤 미국. 빈도표 재료."""
    raw = known_us_sessions(raw)
    K = raw["KOSPI"]; rows = []
    for i in range(1, len(K)):
        D, P = K.index[i], K.index[i - 1]
        w = {k: us_window(raw[k], P, D) for k in ("SPY", "SOXX")}
        if None in w.values():
            continue
        rows.append({"D": D, "gap": change(K.Open.iloc[i], K.Close.iloc[i - 1]), "s": signal(w["SPY"][1], w["SOXX"][1])})
    return pd.DataFrame(rows, columns=["D", "gap", "s"]).set_index("D").replace([np.inf, -np.inf], np.nan).dropna()


def bin_of(s):
    return next(b for b in BINS if b[0] <= s < b[1])


def frequency(hist, s, D):
    """Use only observed sessions before the publication date, for every caller."""
    hist = hist.loc[hist.index < pd.Timestamp(D)].sort_index()
    if not np.isfinite(s) or not BINS[0][0] <= s < BINS[-1][1] or hist.empty:
        return {"bin": "자료 대기", "n": 0, "up": 0, "flat": 0, "down": 0, "years": 0}
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


def shown_pct(x):
    """화면에 보이는 값(퍼센트, 소수 둘째 자리 반올림). 구간 판정은 이 값으로 해요."""
    return round(x * 100, 2)


def is_flat(x):
    """'거의 그대로' = 보이는 값이 ±0.3% 이내(경계 포함). kospi-threshold.md"""
    return abs(shown_pct(x)) <= round(FLAT * 100, 2)


# 시가·마감 공통 크기 구간 (kospi-threshold.md): 0.3% 초과~1% 미만 조금, 1~2% 미만 꽤, 2~5% 미만 많이, 5% 이상 아주 크게
BANDS = ((1.0, "조금"), (2.0, "꽤"), (5.0, "많이"))


def band_of(x):
    """보이는 값 기준 크기 말. 거의 그대로면 None."""
    if is_flat(x):
        return None
    p = abs(shown_pct(x))
    return next((word for limit, word in BANDS if p < limit), "아주 크게")


def zone_of(x):
    return None if x is None else ("flat" if is_flat(x) else "up" if x > 0 else "down")


def headline(f, opened, status, source_states=None):
    """카드 제목 두 줄. cond = 조건('지난밤 뉴욕이 크게 올랐어요'), claim = 규칙('코스피는 10번 중 8번 올라서 시작했어요').
    오늘 시가는 제목이 아니라 그림의 마커가 말한다. 예측 아님, 과거 빈도 서술만. 말투는 해요체."""
    if f and f["bin"] == "자료 대기":
        claim = f"코스피는 {pct(opened)}로 시작했어요" if opened is not None and status != "pending" else "자료가 채워지면 통계를 보여드릴게요"
        return {"cond": "뉴욕 자료를 기다리고 있어요", "claim": claim, "zone": zone_of(opened)}
    if not f:   # 거래일 캘린더가 없으므로 자료 부재만으로 휴장을 단정하지 않는다.
        claim = f"코스피는 {pct(opened)}로 시작했어요" if opened is not None and status != "pending" else "비교할 밤이 없어요. 오늘 시가만 볼게요"
        return {"cond": "비교할 뉴욕 자료가 없어요", "claim": claim, "zone": zone_of(opened)}
    cond = "이전에 확인한 뉴욕 자료예요" if 'reused' in (source_states or {}).values() else NIGHT[f["bin"]]
    if f["n"] < 30:
        return {"cond": cond, "claim": f"비슷한 밤이 {f['n']}번뿐이라 통계는 안 냈어요", "zone": zone_of(opened)}
    maj = max(("up", "down", "flat"), key=lambda z: f[z])
    return {"cond": cond, "claim": f"코스피는 {tenths(f[maj] / f['n'])} {WENT[maj]}", "zone": maj}


def sentence(f, source_states=None):
    """공유·텔레그램·OG 한 문장 = 제목 두 줄을 이은 것."""
    h = headline(f, None, "pending", source_states)
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
    vals = [us[k][1] for k in US if us.get(k) and us[k][1] is not None]
    if not any(us.get(k) for k in US):
        o.append('<text x="0" y="46" fill="var(--muted)">비교할 뉴욕 자료가 없어요</text>')
    else:
        # 호가창처럼 길이 = 크기, 색 = 방향. 음수를 왼쪽으로 뻗게 하면 라벨을 침범한다(9/7 카드에서 확인)
        x0, unit = 76, 100 / max(0.005, max((abs(v) for v in vals), default=0))   # 막대 시작 x, 최대 막대 100px
        o.append(f'<line x1="{x0}" y1="2" x2="{x0}" y2="{H - 2}" stroke="var(--rule)" stroke-width="1"/>')
        for i, k in enumerate(US):
            w = us.get(k); y = 16 + 26 * i
            o.append(f'<text x="{x0 - 8}" y="{y + 4}" text-anchor="end" fill="var(--muted)">{LABEL[k]}</text>')
            if not w: continue
            if w[1] is None:
                o.append(f'<text x="{x0 + 6}" y="{y + 4}" fill="var(--muted)">종가 대기</text>')
                continue
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
    if not f or f["n"] < 30:   # f 없음 = 뉴욕 휴장(미국 공휴일), 있어도 30 미만 = 표본 부족. 오늘 시가는 그래도 찍는다
        note = "비교할 뉴욕 자료가 없어 통계는 안 내요" if not f else "자료가 채워지면 통계를 보여드릴게요" if f.get("bin") == "자료 대기" else "비슷한 밤이 적어 통계는 안 냈어요"
        o.append(f'<text x="0" y="40" fill="var(--muted)">{note}</text>')
        if opened is not None and status in ("filled", "done"):
            c = color(opened)
            o.append(f'<text x="0" y="76"><tspan fill="var(--muted)">오늘 시가 </tspan><tspan font-weight="800" font-size="14" fill="{c}">{pct(opened)}</tspan></text>')
        elif status == "pending":
            o.append(f'<text x="0" y="76" fill="var(--muted)" font-size="11">오늘 시가는 9시 이후 자료가 오면 표시해요</text>')
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
        o.append(f'<text x="{W}" y="{H - 2}" text-anchor="end" fill="var(--muted)" font-size="11">{"오늘 시가는 9시 이후 자료가 오면 표시해요" if status == "pending" else "오늘은 휴장이에요"}</text>')
    o.append("</svg>")
    return "\n".join(o)


def today_nodes(raw, D):
    raw = known_us_sessions(raw)
    K, Q = raw["KOSPI"], raw["KOSDAQ"]
    past = K.index[K.index < D]
    if len(past) < 2:
        raise RuntimeError("KOSPI history needs two prior sessions; preserving published data")
    P = past[-1]
    qpast = Q.index[Q.index < P]
    prev = {"date": P, "kospi": change(K.Close[P], K.Close[past[-2]]),
            "kosdaq": change(Q.Close[P], Q.Close[qpast[-1]]) if P in Q.index and len(qpast) else None}
    us = {k: us_window(raw[k], P, D) for k in US}
    vix = us_window(raw["VIX"], P, D)
    vwin = raw["VIX"][(raw["VIX"].index >= P) & (raw["VIX"].index <= D - pd.Timedelta(days=1))]
    vix_lv = (raw["VIX"][raw["VIX"].index < P].Close.iloc[-1], vwin.Close.iloc[-1]) if vix and vix[1] is not None else None
    opened = change(K.Open[D], K.Close[P]) if D in K.index else None
    closed_pct = change(K.Close[D], K.Close[P]) if D in K.index else None   # 장중엔 현재가. close 단계에서만 믿는다
    return prev, us, vix_lv, opened, closed_pct


# ---------- render ----------
def pct(x, sign=True):
    return ("—" if x is None else f"{x * 100:+.2f}%" if sign else f"{x * 100:.2f}%")


def color(x):
    # 숫자 색도 '거의 그대로'(보이는 값 ±0.3% 이내)면 회색이에요. 문구와 색이 어긋나지 않게.
    return "var(--flat)" if x is None or is_flat(x) else ("var(--up)" if x > 0 else "var(--down)")


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


def share_card_page(D, prev, us, vix_lv, opened, f, status, prev_link, tail=None, og_image=None, source_note=None, source_states=None, landscape=False):
    date_ko = f"{D.month}월 {D.day}일 {'월화수목금토일'[D.weekday()]}요일"
    stamp_t = {"pending": "자료 대기", "done": "마감 반영"}.get(status, "시가 반영")
    pending = pending_text(status)
    ny, kr = ny_svg(us), kr_svg(f, opened, status)
    head = headline(f, opened, status, source_states)
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>밤사이 코스피 · {D:%Y-%m-%d}</title>
<meta name="description" content="전날 코스피 마감, 밤사이 미국 증시, 다음 날 코스피 아침 시작을 한 장에 담았어요.">
<link rel="canonical" href="{SITE_URL}/{D:%Y-%m-%d}/">
<meta property="og:type" content="article"><meta property="og:site_name" content="밤사이 코스피"><meta property="og:url" content="{SITE_URL}/{D:%Y-%m-%d}/">
<meta property="og:title" content="{html.escape(head['cond'])}"><meta property="og:description" content="{html.escape(head['claim'] or '오늘 코스피 시가')}">
<meta property="og:image" content="{og_image or f'{SITE_URL}/{D:%Y-%m-%d}/og.png'}"><meta property="og:image:width" content="1200"><meta property="og:image:height" content="630"><meta property="og:image:type" content="image/png"><meta name="twitter:card" content="summary_large_image"><meta name="twitter:image" content="{og_image or f'{SITE_URL}/{D:%Y-%m-%d}/og.png'}">
<link rel="icon" href="{SITE_URL.rstrip('/')}/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css">
<style>
/* 밤 / 낮 두 쪽. 왼쪽은 밤사이 뉴욕(어둡게), 오른쪽은 다음 날 코스피 시가(밝게). 경계가 곧 릴레이.
   채도는 상승 빨강·하락 파랑뿐. 그라디언트·그림자·글로우·모노 폰트 없음. 폰트는 Pretendard 하나, 숫자는 tnum. */
:root{{--sans:"Pretendard Variable",Pretendard,-apple-system,"Apple SD Gothic Neo","Noto Sans KR",sans-serif}}
*{{box-sizing:border-box}}html,body{{margin:0;background:#E5E8EB;font-family:var(--sans);word-break:keep-all;font-variant-numeric:tabular-nums}}
.sheet{{width:540px;max-width:100%;margin:0 auto;display:grid;grid-template-columns:230px 1fr;border-radius:10px;overflow:hidden;background:#F2F4F6}}
.night{{background:#15171D;color:#FFF;padding:20px 20px 22px;--ink:#FFF;--muted:#A7ADBA;--up:#FF6B5E;--down:#6E9BFF;--flat:#9AA3B5;--rule:rgba(255,255,255,.2)}}
.day{{padding:20px 22px 22px;color:#191F28;--ink:#191F28;--muted:#4E5968;--up:#D22030;--down:#1B64DA;--flat:#4E5968;--rule:#D1D6DB}}
.brand{{font-size:13px;font-weight:700;color:var(--muted);margin:0}}
.stamp{{font-size:11.5px;color:var(--muted);text-align:right;margin:0}}.stamp b{{color:var(--ink)}}
.cond{{font-size:19px;font-weight:800;letter-spacing:-.02em;line-height:1.3;margin:28px 0 0}}
.claim{{font-size:20px;font-weight:800;letter-spacing:-.02em;line-height:1.3;margin:24px 0 0}}
.lab{{font-size:11px;color:var(--muted);margin:26px 0 8px}}
svg{{width:100%;height:auto;display:block}}
.cap{{font-size:11px;color:var(--muted);margin:10px 0 0}}
.tail{{font-size:13px;font-weight:600;line-height:1.4;margin:16px 0 0}}
footer{{grid-column:1/-1;display:flex;justify-content:space-between;gap:12px;padding:12px 22px 14px;border-top:1px solid #D1D6DB;font-size:10.5px;color:#4E5968}}
footer a{{color:#1B64DA}}
.share{{margin-left:10px;border:1px solid #D1D6DB;background:#FFF;color:#191F28;border-radius:6px;padding:4px 10px;font:600 11px var(--sans);cursor:pointer}}
@media (max-width:480px){{.sheet{{grid-template-columns:1fr}}.cond{{margin-top:18px}}.claim{{margin-top:4px}}}}
{'.og-card .sheet{width:600px;height:315px;grid-template-columns:230px 1fr;grid-template-rows:1fr auto;border-radius:0}.og-card .night,.og-card .day{padding:16px 20px;min-height:0}.og-card .cond,.og-card .claim{font-size:18px;line-height:1.35;margin:18px 0 0}.og-card .lab{margin:16px 0 6px}.og-card .night svg{height:76px}.og-card .day svg{height:86px}.og-card .cap{margin-top:6px}.og-card .tail,.og-card .provenance{display:none}.og-card footer{padding:10px 20px;font-size:9px}.og-card .share{display:none}' if landscape else ''}
</style></head><body{' class="og-card"' if landscape else ''}><div class="sheet">
<section class="night"><p class="brand">밤사이 코스피</p>{head_html(head)[0]}<p class="lab">뉴욕 지표</p>{ny}</section>
<section class="day"><p class="stamp">{date_ko} <b>{stamp_t}</b></p>{head_html(head)[1]}<p class="lab">다음 날 코스피 시가</p>{kr}{f'<p class="cap">2021년부터 비슷한 밤 {f["n"]}번</p>' if f and f["n"] >= 30 else ''}{f'<p class="tail">{html.escape(tail)}</p>' if tail else ''}{f'<p class="cap provenance">{html.escape(source_note)}</p>' if source_note else ''}</section>
<footer><span>정보 제공용, 투자 판단 자료 아님 · <a href="../privacy/">개인정보처리방침</a></span><span style="white-space:nowrap">{f'<a href="../{prev_link}/">지난 밤 {int(prev_link[5:7])}/{int(prev_link[8:10])}</a> ' if prev_link else ''}<button class="share" type="button">공유</button></span></footer>
<script>
/* 공유: Web Share가 있으면 시스템 공유 시트, 없으면 링크 복사. 링크는 이 날짜 페이지(OG 카드 붙음) */
document.querySelector('.share').addEventListener('click', async function () {{
  var url = '{SITE_URL}/{D:%Y-%m-%d}/', text = {json.dumps(f"{head['cond']}. {head['claim']}" if head['claim'] else head['cond'], ensure_ascii=False)};
  try {{ if (navigator.share) {{ await navigator.share({{ title: '밤사이 코스피', text: text, url: url }}); return; }} }} catch (e) {{ if (e && e.name === 'AbortError') return; }}
  try {{ await navigator.clipboard.writeText(text + '\\n' + url); this.textContent = '링크 복사됨'; }} catch (e) {{ location.href = url; }}
}});
</script>
</div></body></html>"""


# ---------- web edition (published JSON is read-only here) ----------
WEB_CSS = """
:root{font-family:"Pretendard Variable",-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo",sans-serif;font-size:100%;font-variant-numeric:tabular-nums;color:#191F28;--ink:#191F28;--up:#D22030;--down:#1B64DA;--flat:#B0B8C1;--rule:#E5E8EB}
*{box-sizing:border-box}body{margin:0;background:#FFF;word-break:keep-all;font-size:1rem;line-height:1.5}
a{color:inherit;text-underline-offset:4px}button{font:inherit;color:inherit}a:focus-visible,button:focus-visible{outline:2px solid var(--ink);outline-offset:4px}
.wrap{max-width:1120px;margin:auto}.site-header{display:flex;align-items:center;justify-content:space-between;gap:20px;min-height:80px;border-bottom:1px solid var(--rule)}
.brand{font-size:1.26667rem;font-weight:800;text-decoration:none}.site-header nav{display:flex;gap:24px;font-size:0.933333rem}
.page-heading{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:28px 0}h1{font-size:1.86667rem;letter-spacing:-.04em;margin:0}h2{font-size:1.26667rem;letter-spacing:-.025em;margin:0 0 20px}h3{font-size:1.06667rem;margin:28px 0 8px}p{margin:12px 0}
.day-nav{display:flex;flex-wrap:wrap;gap:12px 24px;font-size:0.933333rem;margin:0 0 24px}.day-nav a{white-space:nowrap}
.answer-band{display:grid;grid-template-columns:320px minmax(0,1fr);gap:40px;padding:8px 0 36px}.kospi-side{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:36px}
.ny-area,.frequency-area,.result-area{min-width:0}.ny-area{padding-right:28px;border-right:1px solid var(--rule)}.graphic-row{margin:0 0 16px}.row-label{display:flex;align-items:baseline;justify-content:space-between;gap:8px;font-size:0.933333rem}.row-label strong{font-size:1.26667rem;font-weight:650}.ticker{font-size:.875rem;margin-left:6px}.source-state{display:block;font-size:.875rem;margin-top:3px}.source-state:empty{display:none}
.ny-track{height:8px;position:relative;background:#F2F4F6;margin-top:8px}.ny-track:before{content:"";position:absolute;left:50%;top:-3px;height:14px;width:1px;background:var(--flat)}.ny-track i{position:absolute;height:8px;display:block;background:var(--flat)}
.frequency-scale{display:flex;justify-content:space-between;font-size:.875rem;margin-bottom:10px}.frequency-track{height:12px;background:#F2F4F6;margin-top:7px}.frequency-track i{display:block;height:12px;background:var(--flat)}.frequency-value{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:0 6px;font-size:0.875rem;font-weight:400}.frequency-value span{white-space:nowrap}.sample-count{font-size:0.875rem;margin:16px 0 0}.answer{font-size:0.933333rem;line-height:1.6;margin:18px 0 0}.empty{display:flex;align-items:center;min-height:172px;font-size:1rem}
.result-basis{font-size:0.875rem;margin:0 0 12px}.result-axis{display:flex;justify-content:space-between;font-size:.875rem;margin:0 0 16px}.result-axis span:nth-child(2){text-align:center}.result-track{position:relative;height:20px;margin:8px 8px 18px;border-bottom:1px solid var(--rule)}.result-track:before{content:"";position:absolute;width:1px;background:var(--flat);left:50%;top:0;height:25px}.result-mark{position:absolute;bottom:-6px;display:block;width:11px;height:11px;border-radius:50%;background:var(--flat);transform:translateX(-50%)}.result-mark.close{border-radius:0}.pending-value{font-size:0.933333rem!important;font-weight:500!important}
.comparison{border-top:1px solid var(--rule);padding:28px 0 0}.section-heading{display:flex;justify-content:space-between;align-items:baseline;gap:12px}.section-heading a{font-size:0.933333rem}.comparison table,.archive-table{width:100%;border-collapse:collapse;font-size:0.933333rem;table-layout:fixed}.comparison th,.comparison td,.archive-table th,.archive-table td{padding:14px 8px;border-bottom:1px solid var(--rule);text-align:right;font-weight:500}.comparison th:first-child,.comparison td:first-child,.archive-table th:first-child,.archive-table td:first-child{text-align:left;width:19%}.comparison thead th,.archive-table thead th{font-size:0.875rem}.comparison td a,.archive-table td a{font-weight:650}.cell-mark{display:inline-block;width:5px;height:5px;border-radius:50%;background:var(--flat);margin-right:5px;vertical-align:middle}.cell-wait{font-size:.875rem}.column-unit{display:block;font-size:.875rem;font-weight:400}.archive-table .no-record{text-align:center}.comparison .current-row{background:#F2F4F6}.comparison .current-row th{border-left:2px solid var(--ink)}.ad-slot{margin-top:32px;min-height:310px;border-top:1px solid var(--rule);padding-top:12px;font-size:.875rem}.ad-slot ins{display:block;height:280px}
.site-footer{display:flex;flex-wrap:wrap;justify-content:space-between;gap:12px 24px;border-top:1px solid var(--rule);padding:24px 0 32px;margin-top:48px;font-size:.875rem}.site-footer nav{display:flex;gap:20px}.share{background:#FFF;border:1px solid var(--rule);border-radius:8px;padding:7px 14px;font-size:0.875rem;cursor:pointer}.share:not([hidden]){display:inline-block}.prose{max-width:720px}.prose p,.prose li{line-height:1.8}.method-table{width:100%;border-collapse:collapse}.method-table td,.method-table th{text-align:left;padding:10px;border-bottom:1px solid var(--rule)}
@media(max-width:1199px){.wrap{margin:0 32px}.answer-band{grid-template-columns:280px minmax(0,1fr);gap:28px}.kospi-side{gap:28px}}
@media(max-width:900px){.answer-band{grid-template-columns:1fr;gap:28px}.ny-area{padding:0 0 16px;border-right:0;border-bottom:1px solid var(--rule)}.kospi-side{gap:32px}.ny-area .graphic-row{max-width:480px}}
@media(max-width:600px){.wrap{margin:0 20px}.site-header{min-height:68px;gap:12px}.brand{font-size:1.13333rem}.site-header nav{gap:16px;font-size:0.875rem}.page-heading{padding:24px 0}h1{font-size:1.66667rem}h2{font-size:1.2rem;margin-bottom:20px}.kospi-side{grid-template-columns:1fr;gap:28px}.frequency-area{padding-bottom:24px;border-bottom:1px solid var(--rule)}.answer-band{padding-bottom:28px}.ny-area{padding-bottom:24px}.graphic-row{margin-bottom:18px}.comparison{padding-top:24px}.comparison th,.comparison td,.archive-table th,.archive-table td{padding:12px 1px;font-size:.875rem}.comparison thead th,.archive-table thead th{font-size:.875rem}.comparison th:first-child,.comparison td:first-child,.archive-table th:first-child,.archive-table td:first-child{width:17%}.comparison .cell-mark,.archive-table .cell-mark{display:none}.comparison .cell-wait{font-size:.875rem}.section-heading{align-items:baseline}.section-heading h2{font-size:1.13333rem}.section-heading a{font-size:.875rem}.site-footer{display:block;margin-top:36px}.site-footer nav{margin-top:12px}.day-nav{font-size:0.875rem}.empty{min-height:120px}}
.service-family{border-bottom:1px solid var(--rule)}.service-family a{display:inline-flex;align-items:center;gap:10px;max-width:100%;min-height:44px;color:#4E5968;font-size:.875rem;text-decoration:none}.axis-mark{font-size:1.53333rem;font-weight:500;line-height:1;color:var(--ink)}
body{overflow-wrap:anywhere}.row-label{flex-wrap:wrap;gap:4px 12px}
.site-header{flex-wrap:wrap;padding-block:12px;gap:8px 24px}.site-header nav{flex-wrap:wrap;gap:4px 20px}.site-header nav a,.day-nav a,.section-heading>a,.site-footer nav a{display:inline-flex;align-items:center;min-height:44px}.site-header nav a[aria-current]{text-decoration-thickness:2px}.day-nav{gap:4px 20px}.page-heading,.section-heading{flex-wrap:wrap}.share{min-height:44px;min-width:56px}
.table-hint{font-size:.875rem;color:#4E5968;margin:4px 0 12px}.table-scroll{overflow-x:auto;overscroll-behavior-inline:contain;scrollbar-color:#B0B8C1 #F2F4F6;padding-bottom:6px}.table-scroll:focus-visible{outline:2px solid var(--ink);outline-offset:4px}.table-scroll table{min-width:30rem}.table-scroll tbody th{position:sticky;left:0;z-index:1;background:#FFF;box-shadow:none}.table-scroll .current-row th{background:#F2F4F6}.table-scroll th a{display:inline-flex;align-items:center;min-height:44px;min-width:44px}
.skip{position:fixed;top:-100px;left:16px;background:white;color:var(--ink);padding:12px;z-index:10}.skip:focus{top:12px}main:focus-visible{outline:2px solid var(--ink);outline-offset:4px}
@media(min-width:901px){.table-hint{display:none}}@media(hover:hover) and (pointer:fine){.service-family a:hover,.site-header nav a:hover,.day-nav a:hover{color:#1B64DA}}


/* ==========================================================================
   dito-common.css — 디토엑시스 8개 사이트 공용 층 (v1, 2026-10-20)
   범위: 공용 헤더(.dx-bar) · 공용 푸터(.dx-footer) · 글꼴 · 뒤로가기 링크(.dx-back)
   원칙: 각 사이트 테마는 건드리지 않아요. 모든 선택자는 .dx- 접두사, 토큰은 --dx- 접두사.
   JS 없이 동작해요(<details>/<summary> 사용). 라이트 모드 전용.
   ========================================================================== */

/* 1) 글꼴 — Pretendard (CDN 기본, font-display: swap 포함)
   <head>에 아래 두 줄을 이 CSS보다 먼저 넣어 주세요(@import보다 빠름).
   <link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>
   <link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css">
   자체 호스팅을 쓸 때는 spec-common.md §3 참고. */

:root {
  /* 글꼴 */
  --dx-font: "Pretendard Variable", Pretendard, -apple-system, BlinkMacSystemFont, system-ui,
             "Apple SD Gothic Neo", "Noto Sans KR", "Malgun Gothic", "Segoe UI", Roboto, sans-serif;

  /* 중립 색 — 흰 바탕(#FFFFFF)과 종이 바탕(#F2EBDC, donbti) 모두에서 AA 통과 */
  --dx-ink:      #191F28;   /* 본문·링크 글자  흰 16.6 / 종이 14.0 */
  --dx-ink-2:    #333D4B;   /* 강조 보조       흰 11.0 / 종이 9.3 */
  --dx-muted:    #4E5968;   /* 보조 글자       흰 7.1  / 종이 6.0 */
  --dx-line:     rgba(25, 31, 40, .14);  /* 구분선(바탕색에 섞여서 둘 다 자연스러움) */
  --dx-hover:    rgba(25, 31, 40, .06);  /* hover/active 바탕 */
  --dx-surface:  #FFFFFF;   /* 펼친 메뉴 패널 */
  --dx-blue:     #1B64DA;   /* 회사 공용 파랑(마크 점·포커스)  흰 5.4 / 종이 4.6 */
  --dx-focus:    var(--dx-blue);
  --dx-shadow:   0 16px 48px rgba(0,0,0,.18);  /* 펼친 메뉴(대화상자급)에만 */

  /* 간격 (4px 단위) */
  --dx-space-1: 4px;  --dx-space-2: 8px;  --dx-space-3: 12px;
  --dx-space-4: 16px; --dx-space-5: 24px; --dx-space-6: 32px; --dx-space-7: 48px;

  /* 크기 */
  --dx-tap: 44px;           /* 최소 터치 영역 */
  --dx-bar-h: 48px;         /* 공용 헤더 높이 */
  --dx-mark: 18px;          /* 마크 아이콘 */
  --dx-max: 1120px;         /* 공용 헤더·푸터 안쪽 최대 폭. 사이트 컨테이너 폭에 맞춰 덮어써요 */
  --dx-gutter: 20px;        /* 좌우 여백(모바일). PC는 아래 미디어쿼리에서 32px */

  /* 모서리 */
  --dx-radius-s: 4px; --dx-radius-m: 8px; --dx-radius-l: 12px; --dx-radius-pill: 999px;

  /* 글자 크기 (최소 14px — 50~60대 사용자 기준) */
  --dx-text-xs: 14px;   /* 캡션·법적 고지 하한 */
  --dx-text-sm: 15px;   /* 공용 헤더 링크, 푸터 */
  --dx-text-md: 16px;   /* 본문 기본 */
  --dx-text-lg: 18px;
  --dx-text-xl: 20px;
  --dx-text-2xl: 24px;
  --dx-text-3xl: 28px;
  --dx-text-4xl: 34px;  /* PC 큰 제목 */
  --dx-leading: 1.6;
  --dx-leading-tight: 1.3;
}

/* 글꼴 적용: 명시도 0이라 사이트가 따로 지정한 제목 글꼴(예: donbti 명조)은 그대로 이겨요 */
:where(html) { font-family: var(--dx-font); }
:where(body, button, input, select, textarea) { font-family: inherit; }

/* 공통 보조 */
.dx-sr { position: absolute !important; width: 1px; height: 1px; margin: -1px; padding: 0;
         overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }
.dx-bar :focus-visible, .dx-footer :focus-visible, .dx-back:focus-visible {
  outline: 3px solid var(--dx-focus); outline-offset: 2px; border-radius: var(--dx-radius-s);
}
.dx-bar *, .dx-footer * { box-sizing: border-box; }

/* 2) 공용 헤더 ============================================================ */
.dx-bar {
  position: relative; z-index: 1000;
  font-family: var(--dx-font); color: var(--dx-ink);
  background: transparent;                 /* 사이트 바탕(흰/종이)을 그대로 보여요 */
  border-bottom: 1px solid var(--dx-line);
  -webkit-text-size-adjust: 100%;
}
.dx-bar__in {
  max-width: var(--dx-max); margin: 0 auto; padding: 0 var(--dx-gutter);
  min-height: var(--dx-bar-h);
  display: flex; align-items: center; justify-content: space-between; gap: var(--dx-space-3);
}
.dx-bar__home {
  display: inline-flex; align-items: center; gap: 6px;
  min-height: var(--dx-tap); padding: 0 var(--dx-space-1); margin-left: calc(-1 * var(--dx-space-1));
  color: var(--dx-ink); text-decoration: none;
  font-size: var(--dx-text-md); font-weight: 800; letter-spacing: -.04em; line-height: 1;
}
.dx-bar__home svg { width: var(--dx-mark); height: var(--dx-mark); flex: none; }
.dx-dot { width: 5px; height: 5px; border-radius: 50%; background: var(--dx-blue); align-self: flex-start; margin: 13px 0 0 -3px; }

/* 다른 서비스: <details> 디스클로저 (JS 없이 열고 닫혀요) */
.dx-more { position: static; }
.dx-more > summary {
  list-style: none; cursor: pointer;
  display: inline-flex; align-items: center; gap: 6px;
  min-height: var(--dx-tap); padding: 0 var(--dx-space-3); margin-right: calc(-1 * var(--dx-space-3));
  border-radius: var(--dx-radius-pill);
  font-size: var(--dx-text-sm); font-weight: 600; color: var(--dx-ink-2);
  -webkit-tap-highlight-color: transparent; user-select: none;
}
.dx-more > summary::-webkit-details-marker { display: none; }
.dx-more > summary::marker { content: ""; }
.dx-more > summary:hover, .dx-more[open] > summary { background: var(--dx-hover); color: var(--dx-ink); }
.dx-more > summary svg { width: 16px; height: 16px; flex: none; transition: transform .15s ease; }
.dx-more[open] > summary svg { transform: rotate(180deg); }

.dx-more__panel {
  position: absolute; left: var(--dx-space-2); right: var(--dx-space-2); top: calc(100% + 6px);
  max-height: min(72vh, 640px); overflow: auto; overscroll-behavior: contain;
  background: var(--dx-surface); color: var(--dx-ink);
  border: 1px solid var(--dx-line); border-radius: var(--dx-radius-l); box-shadow: var(--dx-shadow);
  padding: var(--dx-space-2);
}
.dx-more__title { margin: var(--dx-space-2) var(--dx-space-3) var(--dx-space-1); font-size: var(--dx-text-xs); font-weight: 600; color: var(--dx-muted); }
.dx-more__list { list-style: none; margin: 0; padding: 0; }
.dx-more__list a {
  display: grid; grid-template-columns: 1fr auto; align-items: center; column-gap: var(--dx-space-3);
  min-height: 56px; padding: 10px var(--dx-space-3); border-radius: var(--dx-radius-m);
  color: var(--dx-ink); text-decoration: none;
}
.dx-more__list a:hover { background: var(--dx-hover); }
.dx-more__name { font-size: var(--dx-text-md); font-weight: 700; line-height: var(--dx-leading-tight); }
.dx-more__desc { grid-column: 1; font-size: var(--dx-text-xs); color: var(--dx-muted); line-height: 1.45; margin-top: 2px; }
.dx-more__list a[aria-current="page"] { background: var(--dx-hover); }
.dx-more__list a[aria-current="page"]::after {
  content: "지금 보는 곳"; grid-column: 2; grid-row: 1 / span 2;
  font-size: var(--dx-text-xs); font-weight: 600; color: var(--dx-muted);
  padding: 2px 8px; white-space: nowrap; border: 1px solid var(--dx-line); border-radius: var(--dx-radius-pill);
}
.dx-more__all {
  display: flex; align-items: center; justify-content: center; gap: 6px;
  min-height: 48px; margin-top: var(--dx-space-2); border-top: 1px solid var(--dx-line);
  font-size: var(--dx-text-sm); font-weight: 600; color: var(--dx-ink); text-decoration: none;
}
.dx-more__all:hover { text-decoration: underline; text-underline-offset: 4px; }

/* 3) 공용 푸터 ============================================================ */
.dx-footer {
  font-family: var(--dx-font); color: var(--dx-muted);
  background: transparent; border-top: 1px solid var(--dx-line);
  font-size: var(--dx-text-sm); line-height: var(--dx-leading);
  -webkit-text-size-adjust: 100%;
}
.dx-footer__in { max-width: var(--dx-max); margin: 0 auto; padding: var(--dx-space-5) var(--dx-gutter) var(--dx-space-6); }
.dx-footer__brand { display: inline-flex; align-items: center; gap: 6px; min-height: var(--dx-tap);
  color: var(--dx-ink); text-decoration: none; font-weight: 800; letter-spacing: -.04em; font-size: var(--dx-text-md); }
.dx-footer__brand svg { width: 16px; height: 16px; }
.dx-footer__op { margin: var(--dx-space-1) 0 0; padding: 0; list-style: none; display: flex; flex-wrap: wrap; align-items: center; column-gap: 16px; }
.dx-footer__op li { display: inline-flex; align-items: center; }
/* 구분점(·) 없이 간격으로만 나눠요. 모바일에서 줄이 바뀌어도 줄 끝에 점이 남지 않아요 */
.dx-footer__op a, .dx-footer__links a {
  display: inline-flex; align-items: center; min-height: var(--dx-tap);
  color: var(--dx-ink-2); text-decoration: underline; text-underline-offset: 4px; text-decoration-thickness: 1px;
  overflow-wrap: anywhere;
}
.dx-footer__links { list-style: none; margin: var(--dx-space-2) 0 0; padding: 0; display: flex; flex-wrap: wrap; column-gap: var(--dx-space-5); }
.dx-footer__links a { font-weight: 600; }
/* 사이트 컨테이너(좌우 여백 있음) 안에 넣을 때: <div class="dx-footer dx-footer--flush"> */
.dx-footer--flush .dx-footer__in { padding-left: 0; padding-right: 0; }
.dx-footer__copy { margin: var(--dx-space-2) 0 0; font-size: var(--dx-text-xs); }

/* 4) 뒤로가기 링크(사이트 안 하위 화면용) ================================== */
.dx-back {
  display: inline-flex; align-items: center; gap: 4px;
  min-height: var(--dx-tap); padding: 0 var(--dx-space-2) 0 0;
  font-family: var(--dx-font); font-size: var(--dx-text-md); font-weight: 600;
  color: inherit; text-decoration: none;
}
.dx-back svg { width: 20px; height: 20px; }
.dx-back:hover { text-decoration: underline; text-underline-offset: 4px; }

/* 5) PC (≥ 768px) ======================================================== */
@media (min-width: 768px) {
  :root { --dx-gutter: 32px; }
  .dx-more { position: relative; }
  .dx-more__panel { left: auto; right: calc(-1 * var(--dx-space-3)); width: 400px; }
  .dx-footer__in { display: grid; grid-template-columns: auto 1fr; column-gap: var(--dx-space-6); align-items: start; }
  .dx-footer__brand { grid-row: 1 / span 3; }
  .dx-footer__op { margin-top: 0; }
  .dx-footer__op, .dx-footer__links, .dx-footer__copy { grid-column: 2; }
}

/* 6) 접근성 환경 대응 */
@media (prefers-reduced-motion: reduce) { .dx-more > summary svg { transition: none; } }
@media (forced-colors: active) {
  .dx-more__panel { border: 1px solid CanvasText; }
  .dx-dot { background: CanvasText; }
}
@media print { .dx-bar { display: none; } }

/* kospi v1020 (spec-sites.md ②) */
:root{--dx-max:1120px}
.date-line{margin:6px 0 0;font-size:1rem;color:#4E5968}
.ticker{color:#4E5968}
.frequency-value .freq-pct{font-size:1.25rem;font-weight:750}
.forecast-note{margin:16px 0 0;padding:14px 16px;border-radius:12px;background:#F9FAFB;border:0;color:#333D4B;font-size:1rem;line-height:1.55}
.forecast-note .note-title{display:block;font-size:1.0625rem;color:#191F28;margin-bottom:2px}
.forecast-note p{margin:0}
.site-footer{flex-direction:column;align-items:stretch;padding-bottom:0}
.site-footer .notes{display:flex;flex-wrap:wrap;justify-content:space-between;gap:12px 24px;font-size:.9375rem;color:#4E5968}
.site-footer .dx-footer{margin-top:8px}
.dx-bar__in{max-width:calc(var(--dx-max) + 64px);padding:0 32px}@media(max-width:600px){.dx-bar__in{padding:0 20px}}
"""


DX_BAR = '<nav class="dx-bar" aria-label="디토엑시스"><div class="dx-bar__in"><a class="dx-bar__home" href="https://ditoaxis.com/" aria-label="ditoaxis 디토엑시스 홈"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M12 2v20M2 12h20M5 5l14 14"/></svg><span>ditoaxis</span><span class="dx-dot" aria-hidden="true"></span></a><details class="dx-more"><summary>디토엑시스 다른 서비스<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="m6 9 6 6 6-6"/></svg></summary><div class="dx-more__panel"><p class="dx-more__title" id="dx-more-title">디토엑시스가 만든 서비스</p><ul class="dx-more__list" aria-labelledby="dx-more-title"><li><a href="https://dito.ditoaxis.com/"><span class="dx-more__name">Dito</span><span class="dx-more__desc">살 물건 비교, 할인, 장바구니 시세를 한곳에서 봐요</span></a></li><li><a href="https://exit.ditoaxis.com/"><span class="dx-more__name">퇴사 정산서</span><span class="dx-more__desc">퇴직금과 남은 연차수당을 미리 계산해요</span></a></li><li><a href="https://fx.ditoaxis.com/"><span class="dx-more__name">환율 신호등</span><span class="dx-more__desc">오늘 환율을 보고 원화로 바로 계산해요</span></a></li><li><a href="https://kospi.ditoaxis.com/" aria-current="page"><span class="dx-more__name">밤사이 코스피</span><span class="dx-more__desc">어젯밤 미국 증시와 오늘 코스피를 나란히 봐요</span></a></li><li><a href="https://donbti.ditoaxis.com/"><span class="dx-more__name">지갑사주</span><span class="dx-more__desc">12문항으로 내 소비 유형을 알아봐요</span></a></li><li><a href="https://menu.ditoaxis.com/"><span class="dx-more__name">랜덤식탁</span><span class="dx-more__desc">오늘 먹을 메뉴를 골라 드려요</span></a></li><li><a href="https://giun.ditoaxis.com/"><span class="dx-more__name">오행 기운</span><span class="dx-more__desc">다섯 가지 기운을 만지며 잠깐 쉬어 가요</span></a></li></ul><a class="dx-more__all" href="https://ditoaxis.com/#products">디토엑시스 홈에서 전체 보기</a></div></details></div></nav>'
DX_FOOTER = '<div class="dx-footer dx-footer--flush"><div class="dx-footer__in"><a class="dx-footer__brand" href="https://ditoaxis.com/" aria-label="ditoaxis 디토엑시스 홈"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M12 2v20M2 12h20M5 5l14 14"/></svg><span>ditoaxis</span></a><ul class="dx-footer__op" aria-label="운영 정보"><li>디토엑시스</li><li>대표 모준승</li><li>사업자 221-22-95805</li><li><a href="mailto:help.ditoaxis@gmail.com">문의 help.ditoaxis@gmail.com</a></li></ul><ul class="dx-footer__links"><li><a href="/privacy/">개인정보처리방침</a></li><li><a href="https://www.ftc.go.kr/www/selectBizCommList.do?key=254">사업자정보 확인</a></li><li><a href="https://ditoaxis.com/#products">디토엑시스 다른 서비스</a></li></ul><p class="dx-footer__copy">© 2026 디토엑시스</p></div></div>'
DX_CLOSE_JS = "<script>document.addEventListener('click',e=>{document.querySelectorAll('.dx-more[open]').forEach(d=>{if(!d.contains(e.target))d.open=false})});document.addEventListener('keydown',e=>{if(e.key!=='Escape')return;const d=document.querySelector('.dx-more[open]');if(d){d.open=false;d.querySelector('summary').focus()}});</script>"
WEB_LABEL = {"SOXX": ("반도체 지수", "SOXX"), "QQQ": ("나스닥", "기술주 QQQ"), "SPY": ("S&P500", "대표 500곳 SPY")}
WEB_Z = {"up": "올라서 시작", "flat": "거의 그대로", "down": "내려서 시작"}
FORECAST_NOTE = '<div class="forecast-note" role="note"><b class="note-title">예측이 아니에요</b><p>지난 기록을 세어 본 숫자예요. 이번에도 똑같다는 뜻은 아니에요. 투자는 직접 판단해 주세요.</p></div>'
WEEKDAYS = "월화수목금토일"


def web_footer():
    """Site notes (해요체 disclaimer) + shared ditoaxis operator footer; one contentinfo landmark."""
    e = html.escape
    privacy = web_url('privacy/')
    return ('<footer class="site-footer"><div class="notes"><span>정보를 보여 드리는 서비스예요. 투자 권유나 예측이 아니에요.</span>'
            f'<nav><a href="{e(web_url("about/"))}">집계 기준</a><a href="{e(privacy)}">개인정보처리방침</a></nav></div>'
            + DX_FOOTER.replace('href="/privacy/"', f'href="{e(privacy)}"') + '</footer>')


def web_words(value, verb):
    """+0.0123, '마감' -> '1.23% 꽤 올라서 마감했어요' (색만으로 뜻을 전하지 않아요).
    구간은 kospi-threshold.md: ±0.3% 이내 거의 그대로 / 조금 / 꽤 / 많이 / 아주 크게 (보이는 반올림 값 기준)."""
    p = shown_pct(value)
    if p == 0:
        return f'어제 마감과 같게 {verb}했어요'
    if is_flat(value):
        return f'{abs(p):.2f}% {"올라" if p > 0 else "내려"} 거의 그대로 {verb}했어요'
    return f'{abs(p):.2f}% {band_of(value)} {"올라서" if p > 0 else "내려서"} {verb}했어요'


def web_url(path=""):
    return SITE_URL.rstrip("/") + "/" + path.lstrip("/")


WEB_TABLE_SCRIPT = """<script id="market-table-keys">
document.querySelectorAll('.table-scroll').forEach(region => {
  region.addEventListener('keydown', event => {
    if (event.target !== region || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || region.scrollWidth <= region.clientWidth) return;
    const step = Math.max(44, Math.round(region.clientWidth * 0.65));
    const moves = {ArrowLeft: -step, ArrowRight: step, Home: -region.scrollWidth, End: region.scrollWidth};
    if (!(event.key in moves)) return;
    event.preventDefault();
    region.scrollLeft += moves[event.key];
  });
});
</script>"""


WEB_IMAGE_ALT = '밤사이 미국 증시와 코스피 아침 시작, 오후 마감'


def web_description(date):
    return f'{date} 밤사이 미국 증시와 그다음 코스피 아침 시작, 오후 마감을 함께 봐요. 비슷했던 밤 다음 날 코스피가 어떻게 시작했는지 지난 기록으로 세어 봤어요'


def refresh_meta(text):
    """Old head wording (뉴욕 지표 / 시가) -> 밤사이 / 아침 시작 / 오후 마감. Head only; idempotent."""
    text = re.sub(r'(\d{4}-\d{2}-\d{2}) 뉴욕 세 지표와 비슷한 밤의 과거 빈도, 코스피 시가와 종가를 함께 봐요',
                  lambda m: html.escape(web_description(m[1])), text)
    return text.replace(' · 밤사이 뉴욕 지표와 코스피 시가"', f' · {WEB_IMAGE_ALT}"')


def web_shell(title, path, body, description=None, image_day=None, share_day=None, noindex=False):
    e = html.escape
    url = web_url(path)
    description = description or title
    robots_meta = '<meta name="robots" content="noindex">' if noindex else ''
    image_meta = f'<meta property="og:image" content="{e(web_url(image_day + "/og.png"))}"><meta property="og:image:width" content="1200"><meta property="og:image:height" content="630"><meta property="og:image:type" content="image/png"><meta property="og:image:alt" content="{e(title)} · {e(WEB_IMAGE_ALT)}"><meta name="twitter:card" content="summary_large_image"><meta name="twitter:image" content="{e(web_url(image_day + "/og.png"))}">' if image_day else ""
    share_script = ""
    if share_day:
        # JSON encoding plus escaping '<' keeps published text out of script markup.
        target = json.dumps(web_url(share_day + "/")).replace("<", "\\u003c")
        share_script = f"""<script>
const shareButton = document.querySelector('.share');
shareButton.hidden = false;
shareButton.addEventListener('click', async function () {{
  const url = {target};
  try {{ if (navigator.share) {{ await navigator.share({{title:'밤사이 코스피',url}}); return; }} }} catch(e) {{ if(e.name === 'AbortError') return; }}
  try {{ await navigator.clipboard.writeText(url); this.textContent = '링크를 복사했어요'; }} catch(e) {{ location.href = url; }}
}});
</script>"""
    ad_head = f'<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={e(ADSENSE)}" crossorigin="anonymous"></script>' if ADSENSE else ""
    return f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)} | 밤사이 코스피</title><meta name="description" content="{e(description)}">{robots_meta}
<link rel="canonical" href="{e(url)}"><meta property="og:url" content="{e(url)}"><meta property="og:type" content="website"><meta property="og:site_name" content="밤사이 코스피"><meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(description)}">{image_meta}{ad_head}
{WEB_ANALYTICS}
<link rel="icon" href="{e(web_url('favicon.svg'))}" type="image/svg+xml">
<link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css">
<style>{WEB_CSS}</style></head><body><a class="skip" href="#main">본문으로 이동</a>{DX_BAR}<div class="wrap">
<header class="site-header"><a class="brand" href="{e(web_url())}">밤사이 코스피</a><nav aria-label="사이트"><a href="{e(web_url('archive/' + image_day[:7] + '/')) if image_day else e(web_url() + '#records')}">지난 기록</a><a href="{e(web_url('about/'))}">집계 기준</a></nav></header>
<main id="main" tabindex="-1">{body}</main>{web_footer()}</div>{share_script}{DX_CLOSE_JS}{WEB_TABLE_SCRIPT if 'class="table-scroll"' in body else ''}</body></html>'''


def web_frequency(record, hist):
    """Recompute numbers; never render legacy aggregates, text or SVG fields."""
    us = record.get("us", {})
    spy, soxx = us.get("SPY"), us.get("SOXX")
    s = signal(spy[1], soxx[1]) if spy and soxx else np.nan
    return frequency(hist, s, pd.Timestamp(record["date"]))


def no_us_session(record):
    """Legacy null freq means no comparison window, not an incomplete price.

    Read only this state flag, never stored frequency numbers. A missing field
    gives no evidence about whether a US session existed.
    """
    return "freq" in record and record["freq"] is None


def web_ny(record, latest):
    us = record.get("us", {})
    values = [us[k][1] for k in US if us.get(k) and us[k][1] is not None]
    scale = max([.005] + [abs(v) for v in values])
    rows = []
    for k in US:
        value = us[k][1] if us.get(k) else None
        state = record.get("source_states", {}).get(k)
        stamp = record.get("source_dates", {}).get(k)
        reused = f'기존 게시값 {korean_date(stamp) if stamp else "기준일 미확인"}' if state == "reused" else ""
        bar = ""
        if value is not None:
            width = abs(value) / scale * 50
            left = 50 - width if value < 0 else 50
            bar = f'<i style="left:{left:.3f}%;width:{width:.3f}%;background:{color(value)}"></i>'
        value_class = ' class="pending-value"' if value is None else ''
        missing = "자료 대기" if latest and not no_us_session(record) else "기록이 없어요"
        rows.append(f'<div class="graphic-row"><div class="row-label"><span>{html.escape(WEB_LABEL[k][0])}<span class="ticker">{html.escape(WEB_LABEL[k][1])}</span></span><strong{value_class}>{pct(value) if value is not None else missing}</strong></div><div class="ny-track" aria-hidden="true">{bar}</div><span class="source-state">{reused}</span></div>')
    if 'reused' in record.get('source_states', {}).values():
        note = '이전에 확인한 미국 증시 자료예요'
    elif len(values) < 3:
        note = '미국 증시 자료를 기다리고 있어요' if latest and not no_us_session(record) else '비교할 미국 증시 자료가 없어요' if not values else '일부 미국 증시 기록이 없어요'
    elif all(v > 0 for v in values):
        note = '미국 세 지수가 모두 올랐어요'
    elif all(v < 0 for v in values):
        note = '미국 세 지수가 모두 내렸어요'
    elif all(v == 0 for v in values):
        note = '미국 세 지수가 그대로였어요'
    else:
        note = '미국 세 지수의 방향이 엇갈렸어요'
    return '<section class="ny-area" aria-labelledby="ny-title"><h2 id="ny-title">어젯밤 미국 증시</h2>' + ''.join(rows) + f'<p class="answer">{note}</p></section>'


def web_frequency_graph(f, latest, no_session=False):
    n = f["n"]
    if n < 30:
        missing = "비교할 미국 증시 자료가 없어요" if no_session else "자료가 채워지면 통계를 보여드릴게요" if latest else "비교할 과거 기록이 없어요"
        message = missing if not n else f'비슷한 밤이 {n}번뿐이라 통계는 안 냈어요'
        content = f'<div class="empty">{message}</div>'
    else:
        rows = []
        for z in ("up", "flat", "down"):
            share = f[z] / n
            rows.append(f'<div class="graphic-row"><div class="row-label"><span>{WEB_Z[z]}</span><span class="frequency-value"><span class="dx-sr">{n:,}번 중 {f[z]:,}번, </span><b class="freq-pct">{share:.0%}</b></span></div><div class="frequency-track" aria-hidden="true"><i style="width:{share * 100:.3f}%;background:var(--{z})"></i></div></div>')
        majority = max(("up", "down", "flat"), key=lambda z: f[z])
        content = ''.join(rows) + f'<p class="answer">지난 {n:,}번 중 {f[majority]:,}번 {WENT[majority]}</p>' + FORECAST_NOTE
    return f'<section class="frequency-area" aria-labelledby="frequency-title" data-sample-count="{n}"><h2 id="frequency-title">비슷했던 밤 다음 날, 코스피는 어떻게 시작했을까요?</h2>{content}</section>'


def web_result(record, latest):
    opened = record.get("open")
    closed = record.get("close") if record.get("status") == "done" else None
    scale = max([.01] + [abs(v) * 1.15 for v in (opened, closed) if v is not None])
    rows = []
    for name, value, kind in (("아침 시작<span class=\"ticker\">시가</span>", opened, "open"), ("오후 마감<span class=\"ticker\">종가</span>", closed, "close")):
        waiting = "기록이 없어요" if not latest else "시가 대기" if kind == "open" else "종가 대기"
        label = f'<strong>{pct(value)}</strong>' if value is not None else f'<strong class="pending-value">{waiting}</strong>'
        mark = f'<i class="result-mark {kind}" style="left:{50 + value / scale * 50:.3f}%;background:{color(value)}"></i>' if value is not None else ""
        rows.append(f'<div class="result-row" data-observed="{str(value is not None).lower()}"><div class="row-label"><span>{name}</span>{label}</div><div class="result-track" aria-hidden="true">{mark}</div></div>')
    if closed is not None:
        answer = f'코스피는 {web_words(closed, "마감")}'
    elif opened is not None:
        answer = f'코스피는 {web_words(opened, "시작")}'
    else:
        answer = "코스피는 9시에 시작해요. 시작하면 여기에 보여요." if latest else "이날은 관측한 코스피 기록이 없어요"
    return f'<section class="result-area" aria-labelledby="result-title"><h2 id="result-title">이날 코스피</h2><p class="result-basis">어제 마감보다</p><div class="result-axis"><span>{-scale:.1%}</span><span>0%</span><span>+{scale:.1%}</span></div>{"".join(rows)}<p class="answer">{answer}</p></section>'


def web_value(value, waiting="기록이 없어요"):
    return f'<span class="cell-mark" style="background:{color(value)}" aria-hidden="true"></span>{pct(value)}' if value is not None else f'<span class="cell-wait">{waiting}</span>'


def korean_date(value):
    parts = [int(part) for part in value.split('-')]
    return f'{parts[0]}년 {parts[1]}월' + (f' {parts[2]}일' if len(parts) == 3 else '')


def has_kospi_data(record):
    return record.get("open") is not None or (record.get("status") == "done" and record.get("close") is not None)


def record_table(records, latest_date, current_date=None, archive=False):
    """Share columns, missing values and provenance across recent/month tables."""
    rows = []
    for r in records:
        latest = r["date"] == latest_date
        cells = []
        for k in US:
            value = r.get("us", {}).get(k)
            cell = web_value(value[1] if value else None, "자료 대기" if latest and not no_us_session(r) else "기록이 없어요")
            if value and r.get("source_states", {}).get(k) == 'reused':
                source_date = r.get('source_dates', {}).get(k)
                stamp = korean_date(source_date) if source_date else '기준일 미확인'
                cell += f'<span class="source-state" title="기존 게시값 {stamp}">기존 값</span>'
            cells.append(f'<td>{cell}</td>')
        if not has_kospi_data(r) and not latest:
            cells.append('<td colspan="2" class="no-record">기록이 없어요</td>')
        else:
            cells += [f'<td>{web_value(r.get("open"), "시가 대기" if latest else "기록이 없어요")}</td>',
                      f'<td>{web_value(r.get("close") if r.get("status") == "done" else None, "종가 대기" if latest else "기록이 없어요")}</td>']
        current = ' class="current-row" aria-current="date"' if r["date"] == current_date else ''
        rows.append(f'<tr data-date="{r["date"]}"{current}><th scope="row"><a href="{html.escape(web_url(r["date"] + "/"))}">{r["date"][5:].replace("-", "/")}</a></th>' + ''.join(cells) + '</tr>')
    table_class = 'archive-table' if archive else 'comparison-table'
    return '<p class="table-hint">표를 좌우로 밀어 모든 항목을 볼 수 있어요.</p><div class="table-scroll" role="region" aria-label="시장 기록 비교표, 좌우로 스크롤" tabindex="0">' + f'<table class="{table_class}"><thead><tr><th scope="col">날짜</th>' + ''.join(f'<th scope="col">{x}<span class="column-unit">등락률</span></th>' for x in (*US, "시가", "종가")) + '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>'


def comparison_table(records, as_of):
    recent = [r for r in records if r["date"] <= as_of and has_kospi_data(r)][:5]
    latest_date = records[0]["date"]
    if recent:
        return record_table(recent, latest_date, current_date=as_of)
    return '<p>시가가 들어오면 기록을 모아 보여드릴게요</p>' if as_of == latest_date else '<p>관측한 시가 기록이 없어요</p>'


def web_day(record, records, hist, home=False):
    date = record["date"]
    latest = date == records[0]["date"]
    pos = next(i for i, r in enumerate(records) if r["date"] == date)
    links = []
    for rel, i, label in (("prev", pos + 1, "‹"), ("next", pos - 1, "›")):
        if 0 <= i < len(records):
            d = records[i]["date"]
            day_label = f'{int(d[5:7])}월 {int(d[8:10])}일 기록'
            links.append(f'<a rel="{rel}" href="{html.escape(web_url(d + "/"))}">' + (f'{label} {day_label}' if rel == "prev" else f'{day_label} {label}') + '</a>')
    if not latest:
        links.append(f'<a href="{html.escape(web_url())}">최신 기록 보기</a>')
    title = f'{date} 코스피 기록'
    weekday = WEEKDAYS[dt.date.fromisoformat(date).weekday()]
    heading = f'<div class="page-heading"><div><h1>어젯밤 미국 증시와 코스피</h1><p class="date-line"><time datetime="{date}">{korean_date(date)}({weekday})</time> 기록</p></div><button class="share" type="button" hidden>공유</button></div>'
    nav = '<nav class="day-nav" aria-label="날짜별 기록">' + ''.join(links) + '</nav>'
    f = web_frequency(record, hist)
    band = '<div class="answer-band">' + web_ny(record, latest) + '<div class="kospi-side">' + web_frequency_graph(f, latest, no_us_session(record)) + web_result(record, latest) + '</div></div>'
    table = f'<section class="comparison" id="records"><div class="section-heading"><h2>최근 5일 기록</h2><a href="{html.escape(web_url("archive/" + date[:7] + "/"))}">월별 기록 보기</a></div>{comparison_table(records, date)}</section>'
    ad = ""
    if ADSENSE and ADSENSE_SLOT and has_kospi_data(record):
        ad = f'<aside class="ad-slot" aria-label="광고"><div>광고</div><ins class="adsbygoogle" data-ad-client="{html.escape(ADSENSE)}" data-ad-slot="{html.escape(ADSENSE_SLOT)}" data-ad-format="horizontal" data-full-width-responsive="true"></ins></aside><script>(window.adsbygoogle = window.adsbygoogle || []).push({{}});</script>'
    return web_shell(title, "" if home else date + "/", heading + nav + band + table + ad,
                     description=web_description(date), image_day=date, share_day=date)


def web_archive(month, records, months):
    month_records = [r for r in records if r["date"].startswith(month)]
    i = months.index(month)
    links = []
    for rel, j, label in (("prev", i + 1, "이전 달"), ("next", i - 1, "다음 달")):
        if 0 <= j < len(months):
            links.append(f'<a rel="{rel}" href="{html.escape(web_url("archive/" + months[j] + "/"))}">{label} {int(months[j][5:])}월</a>')
    body = f'<div class="page-heading"><h1>{korean_date(month)} 기록</h1></div><nav class="day-nav" aria-label="월별 기록">{"".join(links)}</nav>{record_table(month_records, records[0]["date"], archive=True)}'
    return web_shell(f'{month} 코스피 기록', f'archive/{month}/', body, image_day=records[0]["date"])


def web_about(hist):
    period = (f'이번에 확보한 유효 이력은 {korean_date(hist.index.min().strftime("%Y-%m-%d"))}부터 '
              f'{korean_date(hist.index.max().strftime("%Y-%m-%d"))}까지예요.' if not hist.empty
              else '현재 가격 이력을 기다리고 있어요.')
    body = f'''<div class="page-heading"><h1>집계 기준</h1></div><article class="prose">
<h2>밤사이 뉴욕을 어떻게 보나요?</h2><p>SOXX는 반도체, QQQ는 나스닥100, SPY는 S&amp;P500을 따라가는 ETF예요. 지수 자체의 등락률과는 차이가 있을 수 있어요. 코스피 전일 거래일부터 이 날짜 전날까지 미국 거래가 여러 번 열렸다면 그 기간의 누적 등락률을 써요.</p>
<h2>비슷한 밤을 어떻게 묶나요?</h2><p>SPY와 SOXX의 등락률을 평균 낸 뒤 0.4를 곱해 같은 구간의 밤을 모아요. QQQ는 비교용으로 보여주며 구간 계산에는 넣지 않아요.</p>
<table class="method-table"><thead><tr><th>구간</th><th>평균에 0.4를 곱한 값</th></tr></thead><tbody><tr><td>강한 하락</td><td>-0.5% 미만</td></tr><tr><td>하락</td><td>-0.5% 이상 -0.3% 미만</td></tr><tr><td>보합</td><td>-0.3% 이상 +0.3% 미만</td></tr><tr><td>상승</td><td>+0.3% 이상 +0.5% 미만</td></tr><tr><td>강한 상승</td><td>+0.5% 이상</td></tr></tbody></table>
<h2>과거 빈도는 무엇인가요?</h2><p>비슷한 밤 뒤에 코스피가 전일 종가보다 얼마나 달라져 시작했는지 세어요. 시가가 +0.3%를 넘으면 상승, -0.3%보다 낮으면 하락, 그 사이인 ±0.3%는 경계를 포함해 보합이에요. 비슷한 밤이 30번보다 적으면 비율을 보여주지 않아요. 과거 빈도는 앞으로의 상승 확률이 아니에요. 화면에서는 상승을 '올라서 시작', 보합을 '거의 그대로', 하락을 '내려서 시작'이라고 불러요. 시가가 어제 마감과 ±{FLAT * 100:.1f}% 안이면 '거의 그대로'로 셌어요.</p>
<h2>어느 기간을 쓰나요?</h2><p>2021년부터 가격을 조회해요. {period} 각 날짜의 빈도에는 그 날짜보다 앞선 코스피 거래일만 넣어요. 이 날짜와 그 뒤의 자료는 쓰지 않아요. 이력을 구하지 못하면 이전에 저장한 통계를 대신 보여주지 않아요.</p>
<h2>시가와 종가는 어떻게 보나요?</h2><p>시가와 종가를 각각 전일 종가와 비교해요. 두 점은 장중 가격 경로가 아니에요. 최신 기록에서 아직 관측하지 못한 가격은 대기로 남겨요. 지난 기록에서 빠진 가격은 기록이 없다고 표시해요. 이미 확인한 같은 날짜의 값을 다시 쓸 때는 기존 게시값이라고 표시해요.</p>
<h2>언제 새로고침하나요?</h2><p>한국 시간 평일 06:45에 뉴욕 자료, 09:06에 코스피 시가, 15:40에 종가를 반영하도록 실행해요. 자료가 늦게 오거나 실행이 지연되면 이후 재시도에서 채워요. 관측값이 없다는 이유만으로 휴장이라고 표시하지 않아요.</p>
<h2>자료와 운영</h2><p>가격 자료는 Yahoo Finance에서 받아요. 운영자는 디토엑시스예요. 문의는 <a href="mailto:help.ditoaxis@gmail.com">help.ditoaxis@gmail.com</a>으로 보내주세요.</p><p><a href="{html.escape(web_url('privacy/'))}">개인정보처리방침 보기</a></p></article>'''
    return web_shell("집계 기준", "about/", body)


def add_web_analytics(source):
    """Leave exactly one canonical loader in the head, or return None when no head is present."""
    if re.search(r'<head\b[^>]*>.*?</head\s*>', source, re.I | re.S) is None:
        return None
    # Any older form anywhere in the page (body, scheme-relative, query string) counts as a loader.
    loader = r'<script\b[^>]*\ssrc\s*=\s*([\'"])(?:https:)?//ditoaxis\.com/m\.js(?:\?[^\'"]*)?\1[^>]*>\s*</script\s*>'
    head = re.search(r'<head\b[^>]*>.*?</head\s*>', source, re.I | re.S)
    if len(re.findall(loader, source, re.I)) == 1 and WEB_ANALYTICS in head[0]:
        return source
    source = re.sub(loader, '', source, flags=re.I)
    head = re.search(r'<head\b[^>]*>.*?</head\s*>', source, re.I | re.S)
    text = head[0]
    ad = re.search(r'<script\b[^>]*\ssrc\s*=\s*([\'"])https://pagead2\.googlesyndication\.com/pagead/js/adsbygoogle\.js(?:\?[^\'"]*)?\1[^>]*>\s*</script\s*>', text, re.I)
    if ad:
        text = text[:ad.end()] + '\n' + WEB_ANALYTICS + text[ad.end():]
    else:
        text = re.sub(r'</head\s*>', lambda _: WEB_ANALYTICS + '\n</head>', text, count=1, flags=re.I)
    return source[:head.start()] + text + source[head.end():]


def restyle():
    """Apply presentation to existing published HTML without any price lookup.

    Historical frequencies stay in their published markup. No JSON, share PNG,
    domain, advertising configuration or financial text is regenerated.
    """
    if not (SITE / 'index.html').is_file() or not (SITE / 'latest.json').is_file():
        raise RuntimeError('A restored published site is required; no bootstrap in restyle mode')
    latest = json.loads((SITE / 'latest.json').read_text())
    if not isinstance(latest, dict) or dt.date.fromisoformat(latest['date']).isoformat() != latest['date']:
        raise RuntimeError('Published latest record is invalid')

    def protected():
        return {str(p.relative_to(SITE)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in SITE.rglob('*') if p.is_file() and '.git' not in p.relative_to(SITE).parts
                and p.suffix != '.html' and p.relative_to(SITE).as_posix() != 'favicon.svg'}

    def main_text(source):
        bodies = re.findall(r'<main(?:\s[^>]*)?>(.*?)</main>', source, re.S)
        if len(bodies) != 1:
            raise RuntimeError('Expected one published main; refusing to guess at the template')
        body = re.sub(r'<p class="table-hint">.*?</p>', '', bodies[0], flags=re.S)
        class Text(HTMLParser):
            def __init__(self):
                super().__init__()
                self.parts = []
            def handle_data(self, value):
                self.parts.append(value)
        parser = Text()
        parser.feed(body)
        return ' '.join(''.join(parser.parts).split())

    before = protected()
    updates = {}
    table_pattern = r'(<table class="(?:comparison-table|archive-table)".*?</table>)'
    for page in sorted(SITE.rglob('*.html')):
        source = page.read_text(encoding='utf-8')
        text = add_web_analytics(source)
        if text is not None:
            text = refresh_meta(text)
        if text is None:
            if page in (SITE / 'index.html', SITE / 'privacy' / 'index.html') or '<header class="site-header">' in source:
                raise RuntimeError(f'Missing published head in {page.relative_to(SITE)}; refusing partial update')
            print(f'::warning::Skipped headless HTML {page.relative_to(SITE)}; left unchanged')
            continue
        icon = f'<link rel="icon" href="{html.escape(web_url("favicon.svg"))}" type="image/svg+xml">'
        if icon not in text:
            text = re.sub(r'</head\s*>', lambda _: icon + '\n</head>', text, count=1, flags=re.I)
        if page == SITE / 'privacy' / 'index.html' and 'https://www.cloudflare.com/web-analytics/' not in text:
            if '<h2>문의</h2>' not in text:
                raise RuntimeError('Published privacy template is unknown; refusing partial update')
            text = text.replace('<h2>문의</h2>', WEB_ANALYTICS_NOTICE + '<h2>문의</h2>', 1)
        if '<header class="site-header">' not in source:
            if page == SITE / 'index.html':
                raise RuntimeError('Published homepage template is unknown')
            updates[page] = text
            continue  # Other templates receive shared head changes and the privacy notice.
        text, count = re.subn(r'<style>.*?</style>', lambda _: '<style>' + WEB_CSS + '</style>', text, count=1, flags=re.S)
        if count != 1:
            raise RuntimeError(f'Missing published stylesheet in {page.name}')
        # Shared ditoaxis shell (outside <main>): dx-bar replaces the old company strip, shared footer.
        text = re.sub(r'\s*<nav class="service-family"[^>]*>.*?</nav>\s*', '\n', text, count=1, flags=re.S)
        if 'class="dx-bar"' not in text:
            if '<body><div class="wrap">' in text:
                text = text.replace('<body><div class="wrap">', '<body><a class="skip" href="#main">본문으로 이동</a>' + DX_BAR + '<div class="wrap">', 1)
            elif '<a class="skip" href="#main">본문으로 이동</a><div class="wrap">' in text:
                text = text.replace('<a class="skip" href="#main">본문으로 이동</a><div class="wrap">', '<a class="skip" href="#main">본문으로 이동</a>' + DX_BAR + '<div class="wrap">', 1)
            else:
                raise RuntimeError('Published shell is unknown; refusing partial update')
        text, footers = re.subn(r'<footer class="site-footer">.*?</footer>', lambda _: web_footer(), text, count=1, flags=re.S)
        if not footers and '</main>' in text:
            text = text.replace('</main>', '</main>' + web_footer(), 1)
        if DX_CLOSE_JS not in text:
            text = text.replace('</body>', DX_CLOSE_JS + '</body>', 1)
        text = re.sub(r'<main(?:\s[^>]*)?>', '<main id="main" tabindex="-1">', text, count=1)
        tables = re.findall(table_pattern, text, re.S)
        if 'class="table-scroll"' not in text:
            text = re.sub(table_pattern, r'<p class="table-hint">표를 좌우로 밀어 모든 항목을 볼 수 있어요.</p><div class="table-scroll" role="region" aria-label="시장 기록 비교표, 좌우로 스크롤" tabindex="0">\1</div>', text, flags=re.S)
        elif text.count('class="table-scroll"') != len(tables):
            raise RuntimeError('Mixed table templates; refusing partial update')
        text = re.sub(r'<script id="market-table-keys">.*?</script>', '', text, flags=re.S)
        if tables:
            text = text.replace('</body>', WEB_TABLE_SCRIPT + '</body>')
        if main_text(source) != main_text(text) or re.findall(table_pattern, source, re.S) != re.findall(table_pattern, text, re.S):
            raise RuntimeError(f'Published financial content changed in {page.name}')
        updates[page] = text
    if SITE / 'index.html' not in updates:
        raise RuntimeError('No published homepage to restyle')
    for page, text in updates.items():
        page.write_text(text, encoding='utf-8')
    write_web_assets()
    if protected() != before:
        raise RuntimeError('Published non-HTML files changed; refusing publication')
    print(f'restyled {len(updates)} existing pages; financial text, tables and published data hashes unchanged; refreshed favicon.svg')


def load_web_records():
    """Isolate invalid archive files at the read boundary; never rewrite them."""
    records = []
    for path in sorted((SITE / "days").glob("*.json"), reverse=True):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(record, dict):
                raise ValueError("expected a record object")
            date = record["date"]
            if dt.date.fromisoformat(date).isoformat() != date:
                raise ValueError("expected YYYY-MM-DD date")
            for key in ("us", "source_states", "source_dates"):
                if not isinstance(record.get(key, {}), dict):
                    raise ValueError(f"invalid {key} mapping")
            prices = [record.get("open"), record.get("close")]
            for key in US:
                window = record.get("us", {}).get(key)
                if window is not None:
                    if not isinstance(window, list) or len(window) < 2:
                        raise ValueError(f"invalid {key} prices")
                    prices.extend(window[:2])
                source_date = record.get("source_dates", {}).get(key)
                if source_date is not None:
                    if dt.date.fromisoformat(source_date).isoformat() != source_date:
                        raise ValueError(f"invalid {key} source date")
            if any(value is not None and (not isinstance(value, (int, float)) or not np.isfinite(value)) for value in prices):
                raise ValueError("invalid price change")
        except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
            print(f"::warning::Skipping web record {path.name}: {exc}")
            continue
        records.append(record)
    return sorted(records, key=lambda record: record["date"], reverse=True)


def regenerate(hist=None):
    """Rebuild HTML and missing OG images; preserve published JSON and relay PNGs.

    Pass aligned fixture history for offline rendering. CLI fetches it once; an
    outage deliberately empties web statistics instead of trusting legacy freq.
    """
    if hist is None:
        try:
            hist = align(fetch())
        except Exception as exc:
            print(f"::warning::Web price history unavailable; frequency pending: {exc}")
            hist = pd.DataFrame(columns=["gap", "s"], index=pd.DatetimeIndex([]))
    records = load_web_records()
    SITE.mkdir(parents=True, exist_ok=True)
    valid_dates = {r["date"] for r in records}
    for page in sorted(SITE.glob("*/index.html")):
        date = page.parent.name
        try:
            if dt.date.fromisoformat(date).isoformat() != date:
                continue
        except ValueError:
            continue
        if date not in valid_dates:
            body = f'<div class="page-heading"><h1>기록이 없어요</h1></div><p><a href="{html.escape(web_url())}">최신 기록 보기</a></p>'
            page.write_text(web_shell(f"{date} 기록이 없어요", date + "/", body, noindex=True), encoding="utf-8")
            print(f"::warning::Replaced orphan date page {date}/index.html: no valid record")
    months = sorted({r["date"][:7] for r in records}, reverse=True)
    if records:
        (SITE / "index.html").write_text(web_day(records[0], records, hist, home=True), encoding="utf-8")
    else:
        (SITE / "index.html").write_text(web_shell("밤사이 코스피", "", '<div class="page-heading"><h1>밤사이 코스피</h1></div><p id="records">첫 기록을 기다리고 있어요</p>'), encoding="utf-8")
    for r in records:
        day = SITE / r["date"]
        day.mkdir(exist_ok=True)
        if not (day / "og.png").exists():
            f = None if no_us_session(r) else web_frequency(r, hist)
            screenshot_card(share_card_page(pd.Timestamp(r["date"]), r.get("prev"), r.get("us", {}), r.get("vix"),
                                           r.get("open"), f, r.get("status", "pending"), None,
                                           source_states=r.get("source_states"), landscape=True), day / "og.png")
        (day / "index.html").write_text(web_day(r, records, hist), encoding="utf-8")
    for month in months:
        folder = SITE / "archive" / month
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "index.html").write_text(web_archive(month, records, months), encoding="utf-8")
    (SITE / "about").mkdir(exist_ok=True)
    (SITE / "about" / "index.html").write_text(web_about(hist), encoding="utf-8")
    write_site_files([r["date"] for r in records])
    (SITE / ".nojekyll").touch()
    print(f'regenerated {len(records)} dates, {len(months)} months')


# ---------- pipeline ----------
def current_phase(now):
    hm = (now.hour, now.minute)
    return "close" if hm >= (15, 40) else "open" if hm >= (9, 0) else "morning"


def preserve_day(previous, prev, us, vix_lv, opened, closed_pct):
    """같은 날짜의 게시물 보호. 기준 거래일이 후퇴하면 발행하지 않는다."""
    old_basis = previous.get("prev", {}).get("date", "")
    if old_basis > f"{prev['date']:%Y-%m-%d}":
        print("::warning::Previously known KOSPI session missing; preserving publication")
        return None
    if old_basis == f"{prev['date']:%Y-%m-%d}":
        # 같은 날짜·같은 기준일의 확인된 값만 재사용한다. 서로 다른 기준의 수익률은 섞지 않는다.
        for k, w in us.items():
            old = previous.get("us", {}).get(k)
            if (not w or w[1] is None) and old and all(np.isfinite(old)):
                us[k] = tuple(old)
                print(f"::warning::{k}: reusing verified same-day prices")
        for k in ("kospi", "kosdaq"):
            if prev[k] is None:
                prev[k] = previous["prev"].get(k)
        if opened is None:
            opened = previous.get("open")
        if previous.get("status") == "done" and closed_pct is None:
            closed_pct = previous.get("close")
        if vix_lv is None:
            vix_lv = previous.get("vix")
    return prev, us, vix_lv, opened, closed_pct


def restore_session(K, previous):
    """발행분(open·close = 기준일 종가 대비 %)으로 상류에서 사라진 세션 한 개를 복원. 마감 확정(done)·기준일 존재·수치 유효일 때만."""
    day, basis = pd.Timestamp(previous["date"]), pd.Timestamp(previous.get("prev", {}).get("date") or "1970-01-01")
    o, c = previous.get("open"), previous.get("close")
    if previous.get("status") != "done" or basis not in K.index or not all(isinstance(x, (int, float)) and np.isfinite(x) for x in (o, c)):
        return None
    base = K.Close[basis]
    if not np.isfinite(base) or base <= 0:
        return None
    row = pd.DataFrame({"Open": [base * (1 + o)], "Close": [base * (1 + c)]}, index=[day])
    return pd.concat([K, row]).sort_index()


def source_provenance(raw, D, us, observed_us, saved):
    """Keep fresh, missing and preserved source values identifiable in every publisher."""
    states = {k: ('missing' if not us.get(k) or us[k][1] is None else
                  'fresh' if observed_us.get(k) and observed_us[k][1] is not None else 'reused') for k in US}
    dates = {k: (f"{raw[k].index[raw[k].index < D][-1]:%Y-%m-%d}" if states[k] == 'fresh'
                 else saved.get('source_dates', {}).get(k) if states[k] == 'reused' and saved.get('source_states', {}).get(k) in ('fresh', 'reused') else None) for k in US}
    note = "뉴욕 자료 기준 · " + " · ".join(
        f"{k} 자료 대기" if states[k] == 'missing' else
        f"{k} {dates[k] or '기준일 미확인'}" + (' (기존 게시값)' if states[k] == 'reused' else '') for k in US)
    return states, dates, note


def build(phase):
    now = dt.datetime.now(KST); D = pd.Timestamp(os.environ.get("RELAY_DATE") or now.date())  # RELAY_DATE=YYYY-MM-DD 로컬 재현용
    if D > pd.Timestamp(now.date()):
        raise ValueError("Cannot publish a future date")
    if D.weekday() >= 5:  # 주말엔 코스피 시가가 없다. 2026-10-17 토요일 수동 실행이 대기 카드를 발행함
        print("::warning::Weekend date skipped"); return
    if D == pd.Timestamp(now.date()):
        phase = current_phase(now)  # 지연된 open도 마감 이후에는 close. 장중 현재가를 마감으로 표시하지 않는다.
    previous = json.loads((SITE / "latest.json").read_text()) if (SITE / "latest.json").exists() else {}
    if previous.get("date", "") > f"{D:%Y-%m-%d}":
        print("::warning::Older run skipped; preserving newer publication")
        return
    raw = fetch()
    if previous.get("status") in ("filled", "done") and pd.Timestamp(previous["date"]) not in raw["KOSPI"].index:
        # 상류(야후)가 직전 세션을 늦게 주는 아침엔 발행분에서 그 세션을 복원해 새 날을 발행한다. 같은 날짜 재실행·마감 미확정은 기존대로 보존 (2026-09-17: 9/16 결측이 9/17 카드를 통째로 막았다)
        restored = restore_session(raw["KOSPI"], previous) if pd.Timestamp(previous["date"]) < D else None
        if restored is None:
            print("::warning::Previously published KOSPI session missing; preserving publication")
            return
        raw["KOSPI"] = restored
        print(f"::warning::KOSPI {previous['date']} missing upstream; restored from published open/close")
    saved = previous if previous.get("date") == f"{D:%Y-%m-%d}" else {}
    basis = saved.get("prev", {}).get("date")
    if basis and pd.Timestamp(basis) not in raw["KOSPI"].index:
        # 같은 날 뒷단계도 아침에 확인한 기준 세션을 날짜별 마감 확정 게시본에서 복원한다.
        archive = SITE / "days" / f"{basis}.json"
        published = json.loads(archive.read_text()) if archive.exists() else {}
        restored = restore_session(raw["KOSPI"], published) if published.get("date") == basis else None
        if restored is not None:
            raw["KOSPI"] = restored
            print(f"::warning::KOSPI {basis} missing upstream; restored from published open/close")
    hist = align(raw)
    prev, us, vix_lv, opened, closed_pct = today_nodes(raw, D)
    if phase == "morning":
        opened = None            # 아침엔 시가 노드 비움 (과거 날짜 재현 시에도)
    if phase != "close":
        closed_pct = None        # 장중 야후 일봉의 Close는 현재가. 마감 단계에서만 쓴다
    observed_us = dict(us)
    nodes = preserve_day(saved, prev, us, vix_lv, opened, closed_pct)
    if nodes is None:
        return
    prev, us, vix_lv, opened, closed_pct = nodes
    f = frequency(hist, signal(us["SPY"][1], us["SOXX"][1]), D) if us.get("SPY") and us.get("SOXX") else None
    # 휴장 캘린더 없이 자료 부재를 휴장으로 확정하지 않는다. 확인된 시가·마감은 후속 작업에서도 보존한다.
    if opened is None: status = "pending"
    elif closed_pct is not None: status = "done"     # 15:40 마감 반영
    else: status = "filled"
    if f and f["bin"] == "자료 대기":
        print("::warning::Overnight prices incomplete; publishing explicit waiting state")
    tail = tail_text(status, closed_pct, us_hours(D)[0])
    prev_link = f"{prev['date']:%Y-%m-%d}" if (SITE / f"{prev['date']:%Y-%m-%d}").exists() else None
    source_states, source_dates, source_note = source_provenance(raw, D, us, observed_us, saved)
    payload = json.dumps({"source_states": source_states, "source_dates": source_dates, "source_note": source_note, "date": f"{D:%Y-%m-%d}", "status": status, "prev": {**prev, "date": f"{prev['date']:%Y-%m-%d}"},
        "us": {k: (list(w[:2]) if w and w[1] is not None else None) for k, w in us.items()}, "vix": vix_lv, "open": opened, "close": closed_pct, "tail": tail, "freq": f,
        "head": headline(f, opened, status, source_states), "sentence": sentence(f, source_states) if f and f["n"] else None, "ny": ny_svg(us), "kr": kr_svg(f, opened, status),
        "built_at": dt.datetime.now(KST).isoformat(timespec="minutes")}, ensure_ascii=False, default=float, allow_nan=False)
    day = SITE / f"{D:%Y-%m-%d}"; day.mkdir(parents=True, exist_ok=True)
    (SITE / "latest.json").write_text(payload, encoding="utf-8")
    (SITE / "days").mkdir(exist_ok=True); (SITE / "days" / f"{D:%Y-%m-%d}.json").write_text(payload, encoding="utf-8")
    write_index()
    (SITE / ".nojekyll").touch()
    screenshot_card(share_card_page(D, prev, us, vix_lv, opened, f, status, prev_link, tail,
                                  source_note=source_note, source_states=source_states), SITE / "relay.png")
    shutil.copyfile(SITE / "relay.png", day / "relay.png")   # 기존 콘텐츠 캡처 경로 보존
    screenshot_card(share_card_page(D, prev, us, vix_lv, opened, f, status, prev_link, tail,
                                  source_note=source_note, source_states=source_states, landscape=True), day / "og.png")
    regenerate(hist)
    print(f"built {D.date()} {status} freq={f}")


def write_index():
    """index.json = [{d: 날짜, z: 그날 시가 방향}] 최신순. 미니앱 '지난 밤들' 칩이 색 점으로 쓴다."""
    rows = []
    for q in sorted((SITE / "days").glob("*.json"), reverse=True):
        try: z = zone_of(json.loads(q.read_text(encoding="utf-8")).get("open"))
        except Exception: z = None
        rows.append({"d": q.stem, "z": z})
    (SITE / "index.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")


PRIVACY = """<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
""" + WEB_ANALYTICS + """
<title>개인정보처리방침 · 밤사이 코스피</title><style>body{font:15px/1.7 -apple-system,"Apple SD Gothic Neo",sans-serif;max-width:640px;margin:0 auto;padding:24px 16px;color:#191F28;background:#FFF}h1{font-size:20px}h2{font-size:16px;margin-top:28px}</style></head><body>
<h1>개인정보처리방침</h1>
<p>디토엑시스(이하 "운영자")는 밤사이 코스피 웹사이트에서 회원가입이나 개인정보 입력을 받지 않습니다.</p>
<h2>광고와 쿠키</h2>
<p>이 사이트는 Google AdSense 광고를 게재할 수 있습니다. Google을 비롯한 제3자 공급업체는 쿠키를 사용해 사용자가 이 사이트나 다른 웹사이트를 방문한 기록을 바탕으로 광고를 게재합니다. 사용자는 <a href="https://adssettings.google.com">Google 광고 설정</a>에서 맞춤 광고를 끌 수 있습니다. 자세한 내용은 <a href="https://policies.google.com/technologies/ads">Google 광고 정책</a>을 참고하십시오.</p>
""" + WEB_ANALYTICS_NOTICE + """
<h2>문의</h2>
<p>디토엑시스 · help.ditoaxis@gmail.com</p>
<p><a href="../">밤사이 코스피로 돌아가기</a></p>
</body></html>"""


def write_site_files(days):
    """검색·광고 심사용 정적 파일. SITE_URL이 github.io가 아니면 CNAME도 쓴다(Pages 커스텀 도메인)."""
    privacy = PRIVACY.replace('</head>', f'<link rel="canonical" href="{html.escape(web_url("privacy/"))}"><link rel="icon" href="{html.escape(web_url("favicon.svg"))}" type="image/svg+xml"></head>')
    write_web_assets()
    (SITE / "privacy").mkdir(exist_ok=True); (SITE / "privacy" / "index.html").write_text(privacy, encoding="utf-8")
    months = sorted({d[:7] for d in days}, reverse=True)
    urls = [web_url()] + [web_url(d + '/') for d in days] + [web_url('archive/' + m + '/') for m in months] + [web_url('about/'), web_url('privacy/')]
    (SITE / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                                      + "".join(f"<url><loc>{html.escape(u)}</loc></url>\n" for u in urls) + "</urlset>\n", encoding="utf-8")
    (SITE / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n", encoding="utf-8")
    host = SITE_URL.split("//", 1)[1].split("/", 1)[0]
    if not host.endswith("github.io"): (SITE / "CNAME").write_text(host + "\n", encoding="utf-8")


def write_web_assets():
    shutil.copyfile(Path(__file__).parent / 'assets' / 'favicon.svg', SITE / 'favicon.svg')


def backfill(n):
    raw = fetch(); hist = align(raw); K = raw["KOSPI"]
    for D in K.index[K.index < pd.Timestamp(dt.datetime.now(KST).date())][-n:]:
        archive = SITE / "days" / f"{D:%Y-%m-%d}.json"
        previous = json.loads(archive.read_text()) if archive.exists() else {}
        saved = previous if previous.get("date") == f"{D:%Y-%m-%d}" else {}
        prev, us, vix_lv, opened, closed_pct = today_nodes(raw, D)
        observed_us = dict(us)
        nodes = preserve_day(saved, prev, us, vix_lv, opened, closed_pct)
        if nodes is None:
            continue
        prev, us, vix_lv, opened, closed_pct = nodes
        f = frequency(hist, signal(us["SPY"][1], us["SOXX"][1]), D) if us.get("SPY") and us.get("SOXX") else None
        if no_us_session(saved) and not any(w and w[1] is not None for w in us.values()):
            f = None  # keep the published no-session flag; backfill must not turn it into a waiting state
        status = "done" if closed_pct is not None else "filled" if opened is not None else "pending"
        source_states, source_dates, source_note = source_provenance(raw, D, us, observed_us, saved)
        day = SITE / f"{D:%Y-%m-%d}"; day.mkdir(parents=True, exist_ok=True)
        payload = {"source_states": source_states, "source_dates": source_dates, "source_note": source_note,
            "date": f"{D:%Y-%m-%d}", "status": status, "prev": {**prev, "date": f"{prev['date']:%Y-%m-%d}"},
            "us": {k: (list(w[:2]) if w and w[1] is not None else None) for k, w in us.items()}, "vix": vix_lv, "open": opened, "close": closed_pct, "tail": None, "freq": f,
            "head": headline(f, opened, status, source_states), "sentence": sentence(f, source_states) if f and f["n"] else None,
            "ny": ny_svg(us), "kr": kr_svg(f, opened, status),
            "built_at": dt.datetime.now(KST).isoformat(timespec="minutes")}
        # 기존 relay.png는 내용이 바뀔 때만 갱신하고, 공유 이미지는 누락 시에도 만든다.
        changed = any(saved.get(key) != payload[key] for key in ("status", "open", "close", "us", "freq", "head", "kr", "sentence", "source_note"))
        if changed or not (day / "relay.png").exists():
            screenshot_card(share_card_page(D, prev, us, vix_lv, opened, f, status, None, None,
                                           source_note=source_note, source_states=source_states), day / "relay.png")
        if changed or not (day / "og.png").exists():
            screenshot_card(share_card_page(D, prev, us, vix_lv, opened, f, status, None, None,
                                           source_note=source_note, source_states=source_states, landscape=True), day / "og.png")
        (SITE / "days").mkdir(exist_ok=True)
        archive.write_text(json.dumps(payload, ensure_ascii=False, default=float, allow_nan=False), encoding="utf-8")
    write_index()
    regenerate(hist)
    print("backfilled", n)


def screenshot_card(markup, png):
    """Render the share template independently of the web pages, without publishing it."""
    import tempfile
    with tempfile.TemporaryDirectory(prefix="kospi-share-") as tmp:
        card = Path(tmp) / "card.html"
        card.write_text(markup, encoding="utf-8")
        screenshot(card, png)


def screenshot(html_path, png):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(); pg = b.new_page(viewport={"width": 600 if 'class="og-card"' in html_path.read_text(encoding="utf-8") else 540, "height": 675}, device_scale_factor=2)
        pg.goto(html_path.resolve().as_uri(), wait_until="networkidle")
        pg.evaluate("document.fonts.ready"); pg.wait_for_timeout(300)
        pg.locator(".sheet").screenshot(path=str(png)); b.close()


def selfcheck():
    raw = fetch(); hist = align(raw)
    g = hist.loc["2025-04-07", "gap"]; assert abs(g - (-0.0431)) < 0.001, g          # 관세 폭락 날 실측 -4.31%
    assert hist.loc["2025-04-10", "gap"] > 0.04                                      # 유예 발표 반등
    cutoff = hist.index.max() + pd.Timedelta(days=1)
    f = frequency(hist, 0.006, cutoff); assert f["up"] + f["flat"] + f["down"] == f["n"] and f["up"] / f["n"] > 0.8, f
    tot = sum(frequency(hist, (lo + min(hi, 0.02)) / 2, cutoff)["n"] for lo, hi, _ in BINS); assert tot == len(hist), (tot, len(hist))
    D = hist.index[len(hist) // 2]
    before = sum(frequency(hist, (lo + min(hi, 0.02)) / 2, D)["n"] for lo, hi, _ in BINS)
    assert before == len(hist[hist.index < D]), (before, D)
    assert "올라서" in sentence(f)
    print("selfcheck ok", len(hist), f)


if __name__ == "__main__":
    {"morning": lambda: build("morning"), "open": lambda: build("open"), "close": lambda: build("close"), "selfcheck": selfcheck,
     "backfill": lambda: backfill(int(sys.argv[2]) if len(sys.argv) > 2 else 20), "regenerate": regenerate, "restyle": restyle}[sys.argv[1]]()
