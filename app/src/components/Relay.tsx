import type { RelayDay } from '../lib/types'
import OrderBook from './OrderBook'

function dateKo(iso: string) {
  const d = new Date(`${iso}T09:00:00+09:00`)
  return `${d.getMonth() + 1}월 ${d.getDate()}일 ${'일월화수목금토'[d.getDay()]}요일`
}

export default function Relay({ day }: { day: RelayDay }) {
  const f = day.freq
  return (
    <article className="sheet" aria-label={`${day.date} 릴레이`}>
      {/* 밤 / 낮과 호가창 구조 유지. 공유 SVG는 앱 안에서만 읽기 쉬운 행으로 표시한다. */}
      <section className="night" aria-labelledby="ny-title">
        <h1 className="brand">밤사이 코스피</h1>
        {day.head && <p className="cond">{day.head.cond}</p>}
        <h2 className="lab" id="ny-title">뉴욕 지표</h2>
        {day.ny ? <OrderBook markup={day.ny} kind="ny" /> : <p className="book-note">비교할 뉴욕 자료가 없어요</p>}
      </section>
      <section className="day" aria-labelledby="kr-title">
        <p className="stamp"><time dateTime={day.date}>{dateKo(day.date)}</time> <b>{day.status === 'pending' ? '자료 대기' : day.status === 'done' ? '마감 반영' : day.status === 'closed' ? '휴장' : '시가 반영'}</b></p>
        {day.head && <p className="claim">{day.head.claim || '오늘 코스피 시가'}</p>}
        <h2 className="lab" id="kr-title">다음 날 코스피 시가</h2>
        {day.kr ? <OrderBook markup={day.kr} kind="kr" /> : <p className="book-note">비교할 코스피 자료가 없어요</p>}
        {f && f.n >= 30 && <p className="cap">2021년부터 비슷한 밤 {f.n}번</p>}
        {day.tail && <p className="tail">{day.tail}</p>}
        {day.source_note && <details className="source-note" key={day.date}>
          <summary>뉴욕 자료 기준 보기</summary>
          <p className="cap">{day.source_note}</p>
        </details>}
      </section>
    </article>
  )
}
