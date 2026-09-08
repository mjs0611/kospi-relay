import { generateHapticFeedback, share, getTossShareLink, setClipboardText } from '@apps-in-toss/web-framework'

// SDK 3.x는 토스 웹뷰 밖에서 동기 throw → 전부 try/catch 래퍼로만 호출
export function haptic(type: 'tickWeak' | 'tap' | 'success' = 'tap') {
  try { generateHapticFeedback({ type }) } catch { /* 브라우저 */ }
}

// 공유: 토스 공유 링크에 그날 카드 PNG를 OG 이미지로 붙인다(fx-signal 선례). 딥링크 /d/날짜.
// share()가 안 되면 클립보드, 그것도 안 되면 브라우저 클립보드.
export async function shareRelay(day: { date: string; head?: { cond: string; claim: string } | null; sentence?: string | null }): Promise<'shared' | 'copied' | 'failed'> {
  const site = 'https://mjs0611.github.io/kospi-relay'
  let link = `intoss://kospi-relay/d/${day.date}`
  try {
    const got = await Promise.resolve(getTossShareLink(link, `${site}/${day.date}/relay.png`))
    if (typeof got === 'string' && got) link = got
  } catch { /* 기본 딥링크 */ }
  const text = day.head ? (day.head.claim ? `${day.head.cond}. ${day.head.claim}` : day.head.cond) : (day.sentence ?? '밤사이 코스피')
  const message = `${text}\n밤사이 코스피\n${link}`
  try { await Promise.resolve(share({ message })); return 'shared' }
  catch {
    try { await Promise.resolve(setClipboardText(message)); return 'copied' }
    catch { try { await navigator.clipboard.writeText(message); return 'copied' } catch { return 'failed' } }
  }
}
