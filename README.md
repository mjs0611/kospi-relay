# 밤사이 코스피 (kospi-relay)

전일 코스피 마감 → 밤사이 뉴욕(SOXX·QQQ·SPY·VIX) → 오늘 코스피 시가. 매일 아침 한 장 + 조건부 빈도 한 줄.
예측·판정 없음. 과거 빈도 서술만. 설계: `docs/superpowers/specs/2026-09-05-kospi-relay-design.md`

```
pip install -r requirements.txt && playwright install chromium
python relay.py selfcheck
RELAY_DATE=2026-09-04 python relay.py open   # 로컬 재현
```

GitHub Actions가 06:45 KST(`morning`)·09:06 KST(`open`)에 빌드해 `gh-pages`로 배포. 텔레그램은 `TELEGRAM_BOT_TOKEN`·`TELEGRAM_CHAT_ID` 시크릿 있을 때만 발송.
