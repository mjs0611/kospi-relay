# 2026-09-07 앱인토스 배포 — 다크 홀로그래픽 + 하단 배너

결과: 공식 CLI 업로드 성공(`ait deploy` → "배포가 완료되었어요"). 검수 요청·출시 전환은 하지 않음(콘솔 수동 단계).

- deploymentId: `01a078da-c3f0-74d2-9f4e-7792956a8ab3`
- 테스트: `intoss-private://kospi-relay?_deploymentId=01a078da-c3f0-74d2-9f4e-7792956a8ab3&host=appsInTossHost`
- 파일: `app/kospi-relay.ait` (419,575 bytes)
- SHA-256: `4b085cdc57530ad98af7a146e3e9c73847589c2073ac731e49538e505b22146f`
- 메모: 다크 홀로그래픽 디자인 전환(차트 시간축 광원), 하단 배너 광고 추가, 상승 빨강·하락 파랑 유지, 번들 시드 갱신
- 배너 구좌: `VITE_BANNER_AD_GROUP_ID` (app/.env, 커밋 안 됨) — dist JS 포함 확인
- 번들 시드: `seed 2026-09-04 filled` — 배포 시점 라이브 latest.json이 9/4 (아래 참고)
- 코드: 미커밋 상태로 배포함. 커밋은 별도.

## 검증

tsc·vite build 통과. 브라우저(SDK 미지원)에서 `.ad-banner` 빈 상태 `display:none`, 빈 칸 없음.
대비 실측(`contrast-check.py`): 미니앱 22개·카드 14개 요소 전부 AA 통과.
실기기 테스트·실제 광고 노출은 미검증.

## 참고 — 스케줄 미실행

`relay.yml` cron `45 21 * * 0-4`(06:45 KST)의 첫 예정 실행(9/7 월)이 `gh run list`에 없음.
마지막 relay 실행은 9/6 09:30 KST `workflow_dispatch`. 이 때문에 latest.json·시드가 9/4에 머묾.
09:06 KST cron(`6 0 * * 1-5`)도 확인 필요.
