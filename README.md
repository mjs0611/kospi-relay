# 밤사이 코스피 (kospi-relay)

전일 코스피 마감 → 밤사이 뉴욕(SOXX·QQQ·SPY·VIX) → 오늘 코스피 시가. 매일 아침 한 장 + 조건부 빈도 한 줄.
예측·판정 없음. 과거 빈도 서술만. 설계: `docs/superpowers/specs/2026-09-05-kospi-relay-design.md`

```
pip install -r requirements.txt && playwright install chromium
python relay.py selfcheck
RELAY_DATE=2026-09-04 python relay.py open   # 로컬 재현
```

정시 트리거는 Mac launchd(`ops/com.junseungmo.kospi-relay.plist` → `ops/dispatch.sh`)가 평일 06:45(`morning`)·09:06(`open`)에 `gh workflow run`으로 쏜다. GitHub cron(06:47/07:20, 09:09/09:40/10:30)은 백업 — 4~5시간 늦게 도는 걸 실측해서 정시는 Mac이 맡는다. 빌드는 GitHub Actions, 배포는 `gh-pages`.

```
cp ops/com.junseungmo.kospi-relay.plist ~/Library/LaunchAgents/ && launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.junseungmo.kospi-relay.plist
tail -f ~/Library/Logs/kospi-relay.log
```
