import type { RelayDay } from '../lib/types'

function dateKo(iso: string) {
  const d = new Date(`${iso}T09:00:00+09:00`)
  return `${d.getMonth() + 1}월 ${d.getDate()}일 ${'일월화수목금토'[d.getDay()]}요일`
}

export default function Relay({ day }: { day: RelayDay }) {
  const f = day.freq
  return (
    <article className="sheet" aria-label={`${day.date} 릴레이`}>
      {/* 밤 쪽: 조건과 밤사이 뉴욕. 낮 쪽: 규칙과 다음 날 코스피 시가. SVG는 파이프라인이 만든 그대로 */}
      <section className="night">
        <p className="brand">밤사이 코스피</p>
        {day.head && <p className="cond">{day.head.cond}</p>}
        <p className="lab">밤사이 뉴욕</p>
        {day.ny && <div className="ny" dangerouslySetInnerHTML={{ __html: day.ny }} />}
      </section>
      <section className="day">
        <p className="stamp">{dateKo(day.date)} <b>{day.status === 'pending' ? '06:45' : '09:06'}</b></p>
        {day.head && <p className="claim">{day.head.claim || '오늘 코스피 시가'}</p>}
        <p className="lab">다음 날 코스피 시가</p>
        {day.kr && <div className="kr" dangerouslySetInnerHTML={{ __html: day.kr }} />}
        {f && f.n >= 30 && <p className="cap">2021년부터 비슷한 밤 {f.n}번</p>}
      </section>
    </article>
  )
}
