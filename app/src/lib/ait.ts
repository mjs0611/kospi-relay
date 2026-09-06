import { generateHapticFeedback, share, getTossShareLink, setClipboardText } from '@apps-in-toss/web-framework'

// SDK 3.x는 토스 웹뷰 밖에서 동기 throw → 전부 try/catch 래퍼로만 호출
export function haptic(type: 'tickWeak' | 'tap' | 'success' = 'tap') {
  try { generateHapticFeedback({ type }) } catch { /* 브라우저 */ }
}

export async function shareRelay(text: string) {
  let link = 'intoss://kospi-relay'
  try {
    const got = await Promise.resolve(getTossShareLink('intoss://kospi-relay'))
    if (typeof got === 'string' && got) link = got
  } catch { /* 기본 딥링크 */ }
  const message = `${text}\n뉴욕 마감에서 오늘 코스피 시가까지, 한 장 — 밤사이 코스피\n${link}`
  try { await Promise.resolve(share({ message })) }
  catch { try { await Promise.resolve(setClipboardText(message)) } catch { /* noop */ } }
}
