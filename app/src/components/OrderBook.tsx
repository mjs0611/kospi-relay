import { useMemo, type CSSProperties } from 'react'

type Tone = 'ink' | 'muted' | 'up' | 'flat' | 'down'
type Fragment = { text: string; tone: Tone; strong: boolean }
type Row = { label: string; value: Fragment[]; marker: Fragment[]; tone: Tone; width: number }

function tone(element: Element, fallback: Tone = 'ink'): Tone {
  const match = element.getAttribute('fill')?.match(/^var\(--(ink|muted|up|flat|down)\)$/)
  return match ? match[1] as Tone : fallback
}

function fragments(element: Element): Fragment[] {
  const inherited = tone(element)
  const strong = Number(element.getAttribute('font-weight')) >= 600
  return Array.from(element.childNodes).map(node => {
    const child = node.nodeType === 1 ? node as Element : null
    return {
      text: node.textContent ?? '',
      tone: child ? tone(child, inherited) : inherited,
      strong: child?.hasAttribute('font-weight') ? Number(child.getAttribute('font-weight')) >= 600 : strong,
    }
  })
}

// 배포된 SVG의 문구·반올림·색·막대 길이를 그대로 읽는다. 통계나 시가 분류를 앱에서 다시 계산하지 않는다.
export function readOrderBook(markup: string, kind: 'ny' | 'kr') {
  // 생성기는 S&P500의 &를 HTML 문맥으로 보낸다. 원래 innerHTML과 같은 파싱 규칙을 유지한다.
  const document = new DOMParser().parseFromString(markup, 'text/html')
  const svg = document.querySelector('svg')
  if (!svg) return null
  const texts = Array.from(svg.querySelectorAll('text'))
  if (texts.length === 0) return null
  const bars = Array.from(svg.querySelectorAll('rect')).filter(rect => rect.getAttribute('height') === '14')
  const used = new Set<Element>()
  const labels = texts.filter(text => kind === 'ny'
    ? text.getAttribute('text-anchor') === 'end'
    : ['상승', '보합', '하락'].includes(text.textContent ?? ''))
  const rows = labels.map<Row>(label => {
    const y = Number(label.getAttribute('y'))
    const peers = texts.filter(text => text !== label && Number(text.getAttribute('y')) === y)
    const bar = bars.find(rect => Number(rect.getAttribute('y')) + 11 === y)
    const marker = kind === 'kr' ? peers.find(text => text.getAttribute('text-anchor') === 'end') : undefined
    const value = peers.find(text => text !== marker)
    used.add(label)
    peers.forEach(text => used.add(text))
    return {
      label: label.textContent ?? '',
      value: value ? fragments(value) : [{ text: '자료 대기', tone: 'muted', strong: false }],
      marker: marker ? fragments(marker) : [],
      tone: bar ? tone(bar) : 'muted',
      width: bar ? Math.min(100, Math.max(0, Number(bar.getAttribute('width')) / (kind === 'ny' ? 100 : 120) * 100)) : 0,
    }
  })
  return { rows, notes: texts.filter(text => !used.has(text)).map(fragments) }
}

function Text({ parts }: { parts: Fragment[] }) {
  return <>{parts.map((part, index) => <span key={index} className={`tone-${part.tone}${part.strong ? ' book-strong' : ''}`}>{part.text}</span>)}</>
}

export default function OrderBook({ markup, kind }: { markup: string; kind: 'ny' | 'kr' }) {
  const book = useMemo(() => readOrderBook(markup, kind), [markup, kind])
  if (!book) return <p className="book-note">자료를 표시하지 못했어요. 다른 날짜를 선택해 주세요.</p>
  return (
    <div className={`order-book book-${kind}`}>
      {book.rows.length > 0 && <ul className="book-rows">
        {book.rows.map(row => <li key={row.label} className={`book-row row-${row.tone}${row.marker.length ? ' is-current' : ''}`}>
          <span className="book-label">{row.label}</span>
          <span className="book-track" aria-hidden="true"><span className={`book-bar tone-${row.tone}`} style={{ width: `${row.width}%` } as CSSProperties} /></span>
          <span className="book-value"><Text parts={row.value} /></span>
          {row.marker.length > 0 && <span className="book-marker"><Text parts={row.marker} /></span>}
        </li>)}
      </ul>}
      {book.notes.map((note, index) => <p className="book-note" key={index}><Text parts={note} /></p>)}
    </div>
  )
}
