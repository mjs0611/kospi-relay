import type { RelayDay } from '../lib/types'

const pct = (x: number | null) => (x == null ? '—' : `${x >= 0 ? '+' : ''}${(x * 100).toFixed(2)}%`)

function dateKo(iso: string) {
  const d = new Date(`${iso}T09:00:00+09:00`)
  return `${d.getFullYear()}년 ${d.getMonth() + 1}월 ${d.getDate()}일 ${'일월화수목금토'[d.getDay()]}요일`
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
        <span className="tag">{day.status === 'pending' ? '시가 대기' : day.status === 'closed' ? '휴장' : `시가 ${pct(day.open)}`}</span>
      </header>
      {day.head && (
        <p className="headline">
          {day.head.lead}<b className={`z-${day.head.zone ?? 'flat'}`}>{day.head.num}</b>{day.head.tail}
        </p>
      )}
      {/* SVG는 파이프라인이 만든 그대로 — 웹·PNG·미니앱이 한 그림 */}
      <div className="chart" dangerouslySetInnerHTML={{ __html: day.svg }} />
      {f && f.n > 0 && legend && (
        <section className="freq">
          <p className="lede">{day.sentence}</p>
          <div className="bar" role="img" aria-label={legend.map(([l, v]) => `${l} ${Math.round((v / f.n) * 100)}%`).join(', ')}>
            {legend.map(([l, v, c]) => v > 0 && <div key={l} className="seg" style={{ flex: v, background: c }} />)}
          </div>
          <p className="legend">
            {legend.map(([l, v, c], i) => (
              <span key={l}>{i > 0 && ' · '}<span style={{ color: c }}>{l} {Math.round((v / f.n) * 100)}%</span></span>
            ))}
            <span className="n">n={f.n} · 뉴욕 {f.bin} 구간</span>
          </p>
        </section>
      )}
    </article>
  )
}
