"""headline()·sentence()·relay_svg() 검증. relay.py는 pandas·yfinance를 import하므로 통째로 못 불러온다.
ast로 필요한 정의만 뽑아 실행한다. 실행: python3 test_headline.py"""
import ast, pathlib, html, json, datetime, subprocess

src = pathlib.Path(__file__).with_name("relay.py").read_text()
tree = ast.parse(src)
keep = {"FLAT", "US", "LABEL", "NIGHT", "WENT", "LABEL_Z", "tenths", "pct", "color", "zone_of", "headline", "head_html", "sentence", "ny_svg", "kr_svg", "tail_text"}
keep.update({"page", "pending_text"})
mod = ast.Module(body=[n for n in tree.body
                       if (isinstance(n, ast.FunctionDef) and n.name in keep)
                       or (isinstance(n, ast.Assign) and any(getattr(t, "id", None) in keep for t in n.targets))], type_ignores=[])
ns = {"html": html, "json": json, "SITE_URL": "https://example.com"}; exec(compile(mod, "relay-slice", "exec"), ns)
headline, zone_of, sentence, ny_svg, kr_svg, FLAT = ns["headline"], ns["zone_of"], ns["sentence"], ns["ny_svg"], ns["kr_svg"], ns["FLAT"]

f = {"n": 541, "up": 174, "flat": 277, "down": 90, "bin": "보합", "years": 5.6}
fu = {"n": 277, "up": 222, "flat": 45, "down": 10, "bin": "강한 상승", "years": 5.6}
us = {"SOXX": (0.01, 0.0352, 1), "QQQ": (0.0, 0.0018, 1), "SPY": (0.0, -0.0039, 1)}
h = headline(fu, None, "pending");  assert h == {"cond": "지난밤 뉴욕이 크게 올랐어요", "claim": "코스피는 10번 중 8번 올라서 시작했어요", "zone": "up"}, h
h = headline(f, 0.0276, "filled");  assert h["cond"] == "지난밤 뉴욕은 잠잠했어요" and h["claim"] == "코스피는 10번 중 5번 거의 그대로 시작했어요", h
h = headline({"n": 10, "up": 5, "flat": 3, "down": 2, "bin": "상승", "years": 5.6}, None, "pending"); assert h["claim"] == "비슷한 밤이 10번뿐이라 통계는 안 냈어요", h
h = headline(None, None, "pending"); assert h["cond"] == "비교할 뉴욕 자료가 없어요" and "오늘 시가만" in h["claim"]
h = headline(None, 0.0072, "done"); assert h["claim"] == "코스피는 +0.72%로 시작했어요" and h["zone"] == "up"
assert sentence(fu) == "지난밤 뉴욕이 크게 올랐어요. 코스피는 10번 중 8번 올라서 시작했어요"
assert headline(fu, None, "pending", {"SPY": "reused"})["cond"] == "이전에 확인한 뉴욕 자료예요"
assert sentence(fu, {"SPY": "reused"}).startswith("이전에 확인한 뉴욕 자료예요.")
assert headline(fu, None, "pending", {"SPY": "fresh"}) == headline(fu, None, "pending")
assert "올라서" in sentence(fu)                                  # relay.py selfcheck와 같은 계약
assert zone_of(FLAT) == "flat" and zone_of(FLAT + 1e-9) == "up" and zone_of(-FLAT - 1e-9) == "down"
for s_ in (sentence(f), sentence(fu), h["cond"]):
    assert "—" not in s_ and "·" not in s_ and "습니다" not in s_ and "열렸다" not in s_, s_   # 줄표·중점·합쇼체·신문체 금지
ny = ny_svg(us); assert ny.count("<rect") == 3 and "+3.52%" in ny and "-0.39%" in ny and "mono" not in ny, ny[:200]
assert "자료가 없어요" in ny_svg({})
kr = kr_svg(fu, 0.0334, "filled"); assert kr.count("<rect") == 4 and "상승" in kr and "80%" in kr and "오늘 " in kr and "+3.34%" in kr, kr[:300]   # 막대 3 + 오늘 행 칠
kr = kr_svg(fu, None, "pending");  assert kr.count("<rect") == 3 and "9시 이후" in kr and "+3.34%" not in kr
assert "비교할 뉴욕 자료가 없어" in kr_svg(None, None, "pending") and "+0.72%" in kr_svg(None, 0.0072, "done") and "통계는 안 냈어요" in kr_svg({"n": 5, "up": 3, "flat": 1, "down": 1, "bin": "상승", "years": 5}, None, "pending")
cond, claim = ns["head_html"](headline(fu, None, "pending")); assert cond.startswith('<p class="cond">') and claim.startswith('<p class="claim">')
tail = ns["tail_text"]
assert tail("done", 0.0124, 22.5) == "오늘 코스피는 +1.24%로 마감했어요. 뉴욕은 22:30에 열려요"
assert tail("done", -0.005, 23.5) == "오늘 코스피는 -0.50%로 마감했어요. 뉴욕은 23:30에 열려요"
assert tail("filled", 0.01, 22.5) is None and tail("done", None, 22.5) is None
kr = kr_svg(fu, 0.0334, "done"); assert "오늘 " in kr and "+3.34%" in kr   # done도 마커
print("headline ok")

# 생성된 JavaScript를 실행해 공유 성공·취소·실패와 기존 복사 폴백을 검증한다.
page = ns["page"](datetime.date(2026, 9, 25), None, {}, None, None, None, "pending", None)
script = page.split("<script>", 1)[1].split("</script>", 1)[0]
subprocess.run(["node", "-e", r"""
const assert = require('node:assert/strict');
const vm = require('node:vm');
(async () => {
  for (const outcome of ['success', 'AbortError', 'NotAllowedError', 'TypeError', 'Error', 'missing']) {
    for (const copyFails of [false, true]) {
      let click, shared, copied;
      const button = {textContent: '공유'};
      const location = {href: 'unchanged'};
      const navigator = {clipboard: {writeText: async text => {
        copied = text;
        if (copyFails) throw new Error('clipboard denied');
      }}};
      if (outcome !== 'missing') navigator.share = async data => {
        shared = data;
        if (outcome !== 'success') throw Object.assign(new Error(outcome), {name: outcome});
      };
      vm.runInNewContext(process.argv[1], {
        navigator, location, document: {querySelector: () => ({addEventListener: (_, fn) => {click = fn;}})}
      });
      await click.call(button);
      const fallback = !['success', 'AbortError'].includes(outcome);
      assert.equal(copied, fallback ? '비교할 뉴욕 자료가 없어요. 비교할 밤이 없어요. 오늘 시가만 볼게요\nhttps://example.com/2026-09-25/' : undefined, outcome);
      assert.equal(button.textContent, fallback && !copyFails ? '링크 복사됨' : '공유', outcome);
      assert.equal(location.href, fallback && copyFails ? 'https://example.com/2026-09-25/' : 'unchanged', outcome);
      assert.equal(!!shared, outcome !== 'missing', outcome);
    }
  }
  console.log('share fallback ok');
})().catch(error => {console.error(error); process.exitCode = 1;});
""", script], check=True, timeout=10)
