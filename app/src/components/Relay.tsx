import type { RelayDay } from '../lib/types'

function dateKo(iso: string) {
  const d = new Date(`${iso}T09:00:00+09:00`)
  return `${d.getMonth() + 1}월 ${d.getDate()}일 ${'일월화수목금토'[d.getDay()]}요일`
}

export default function Relay({ day }: { day: RelayDay }) {
  const f = day.freq
  const legend = f && f.n
    ? [['아래', f.down, 'var(--down)'], ['±0.3%', f.flat, 'var(--flat)'], ['위', f.up, 'var(--up)']] as const
    : null
  return (
    <article className="sheet" aria-label={`${day.date} 릴레이`}>
      <header className="stamp">
        <span>{dateKo(day.date)}</span>
        <b>{day.status === 'pending' ? '06:45' : '09:06'}</b>
      </header>
      {day.head && <p className="headline">{day.head.text}</p>}
      {/* SVG는 파이프라인이 만든 그대로 — 웹·PNG·미니앱이 한 그림 */}
      <div className="chart" dangerouslySetInnerHTML={{ __html: day.svg }} />
      {f && f.n > 0 && legend && (
        <section className="freq">
          <div className="bar" role="img" aria-label={legend.map(([l, v]) => `${l} ${Math.round((v / f.n) * 100)}%`).join(', ')}>
            {legend.map(([l, v, c]) => v > 0 && <div key={l} className="seg" style={{ flex: v, background: c }} />)}
          </div>
          <p className="legend">
            {legend.map(([l, v, c]) => <span key={l} style={{ color: c }}>{l} {Math.round((v / f.n) * 100)}%</span>)}
            <span className="n">뉴욕 {f.bin} 마감 {f.n}밤</span>
          </p>
        </section>
      )}
    </article>
  )
}
