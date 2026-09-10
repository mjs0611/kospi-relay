#!/bin/sh
# Mac launchd가 06:45·09:06(평일)에 실행. GitHub cron이 4~5시간씩 늦어서(9/7 실측) 정시 트리거를 Mac이 맡는다.
# KST 09:00 전 morning, 15:40 전 open, 이후 close. 지연 실행도 실제 시각으로 결정한다.
HM=$(TZ=Asia/Seoul date +%H%M)
if [ "$HM" -lt 900 ]; then PHASE=morning; elif [ "$HM" -lt 1540 ]; then PHASE=open; else PHASE=close; fi
echo "$(date '+%F %T') dispatch $PHASE"
exec /opt/homebrew/bin/gh workflow run relay.yml -R mjs0611/kospi-relay -f phase=$PHASE
