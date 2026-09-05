import { defineConfig } from '@apps-in-toss/web-framework/config'

// v3 웹 프레임워크 config: 브랜드 이름·로고는 콘솔 앱 정보에서 옴(brand엔 primaryColor만 타입 존재)
export default defineConfig({
  appName: 'kospi-relay',
  brand: { primaryColor: '#10172A' },
  navigationBar: { withBackButton: true, withHomeButton: true },
  webView: { bounces: false, pullToRefreshEnabled: false },
  webBundleDir: 'dist',
  permissions: [],
})
