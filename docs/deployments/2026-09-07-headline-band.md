# 2026-09-07 앱인토스 배포 — 결과 헤드라인 + 시가 밴드 + 스케줄 재시도

결과: `ait deploy` 성공. 검수 요청·출시 전환은 하지 않음(콘솔 수동 단계).

- deploymentId: `01a07904-6e7a-78a5-840f-d48f719dc6e3`
- 테스트: `intoss-private://kospi-relay?_deploymentId=01a07904-6e7a-78a5-840f-d48f719dc6e3&host=appsInTossHost`
- 파일: `app/kospi-relay.ait` · SHA-256 `e677513c94bd61edd5801a71891343fcd5119de05f9974bcb18eafc2956fdb41`
- 코드: `ae6c6c2`, `ff29329` (origin/main)
- 번들 시드: `seed 2026-09-07 pending` — head 포함 ("이런 밤 277번 중 80%는 위로 열렸습니다 — 답은 09:00 시가")
- 선행 Actions: `morning`(34066401919) → `backfill`(34066403681) 모두 success. 라이브 latest.json·days/*.json에 head, SVG에 ±0.3% 밴드·톤다운 그룹 확인

## 스케줄 관찰

옛 cron `45 21`(06:45 KST)이 08:13 KST에 뒤늦게 실행됨(run 34066260970, schedule, success) — 죽은 게 아니라 1시간 28분 지연.
새 재시도 크론(06:47/07:20, 09:09/09:40/10:30)이 이 지연 폭을 덮는다. 오늘 09:09·09:40·10:30 open 크론 실행 여부로 최종 확인.

## 미검증

실기기 배너 노출, 실기기 헤드라인·밴드 렌더, 텔레그램 발송(시크릿 설정 여부 미확인).
