import type { RelayDay } from '../lib/types'

function dateKo(iso: string) {
  const d = new Date(`${iso}T09:00:00+09:00`)
  return `${d.getMonth() + 1}월 ${d.getDate()}일 ${'일월화수목금토'[d.getDay()]}요일`
}

export default function Relay({ day }: { day: RelayDay }) {
  return (
    <article className="sheet" aria-label={`${day.date} 릴레이`}>
      <header className="stamp">
        <span>{dateKo(day.date)}</span>
        <b>{day.status === 'pending' ? '06:45' : '09:06'}</b>
      </header>
      {day.head && (day.head.claim
        ? <><p className="cond">{day.head.cond}</p><p className="claim">{day.head.claim}</p></>
        : <p className="claim">{day.head.cond}</p>)}
      {/* 원인 → 결과 그림은 파이프라인이 만든 그대로. 웹·PNG·미니앱이 한 그림 */}
      <div className="chart" dangerouslySetInnerHTML={{ __html: day.svg }} />
    </article>
  )
}
