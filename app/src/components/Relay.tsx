import type { RelayDay } from '../lib/types'

function dateKo(iso: string) {
  const d = new Date(`${iso}T09:00:00+09:00`)
  return `${d.getMonth() + 1}월 ${d.getDate()}일 ${'일월화수목금토'[d.getDay()]}요일`
}

const NIGHT: Record<string, string> = {
  '강한 상승': '뉴욕이 크게 오른 밤', '상승': '뉴욕이 오른 밤', '보합': '뉴욕이 조용했던 밤',
  '하락': '뉴욕이 내린 밤', '강한 하락': '뉴욕이 크게 내린 밤',
}

export default function Relay({ day }: { day: RelayDay }) {
  const f = day.freq
  return (
    <article className="sheet" aria-label={`${day.date} 릴레이`}>
      <header className="stamp">
        <span>{dateKo(day.date)}</span>
        <b>{day.status === 'pending' ? '06:45' : '09:06'}</b>
      </header>
      {day.head && <p className="headline">{day.head.text}</p>}
      {/* 막대·차트 SVG는 파이프라인이 만든 그대로. 웹·PNG·미니앱이 한 그림 */}
      {day.bar && f && (
        <>
          <div className="freqbar" dangerouslySetInnerHTML={{ __html: day.bar }} />
          <p className="cap">2021년부터 {NIGHT[f.bin] ?? f.bin} {f.n}번</p>
        </>
      )}
      <div className="chart" dangerouslySetInnerHTML={{ __html: day.svg }} />
    </article>
  )
}
