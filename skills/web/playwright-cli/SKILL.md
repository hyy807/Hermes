---
name: playwright-cli
description: "Drive a real browser for automation and request intercep…"
version: 0.1.0
author: "trhhubsd (ARTEX), Hermes Agent"
license: AGPL-3.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [browser, playwright, automation, scraping, pentest]
    category: web
    related_skills: [frontend-api-recon]
---

# Browser Automation with playwright-cli

Playwright 官方 CLI（`@playwright/cli`）。无全局命令时用 `npx --no-install playwright cli`，或 `npm install -g @playwright/cli@latest`。是 Hermes 内置 `browser_exec`（Browser Use CLI）的互补工具：route mock 和 storage-state 更适合无凭据撑壳/登录态管理场景。

## When to Use
- 驱动真实浏览器做交互、截图、抓取 JS 渲染后的内容
- 拦截/改写网络请求（route mock），配合 frontend-api-recon 的无凭据撑壳
- 保存/恢复登录态（storage state），复用已验证的 session

## Quick start
```bash
playwright-cli open                    # 开浏览器
playwright-cli goto https://example.com
playwright-cli snapshot                # 拿带 ref 的页面快照
playwright-cli click e15               # 用 ref 点击
type / press / fill e5 "x" --submit
playwright-cli close
```

## 渗透常用命令

### Network — 请求拦截/改写（撑壳、改包）
```bash
playwright-cli route "**/*.jpg" --status=404
playwright-cli route "https://api.example.com/**" --body='{"mock": true}'
playwright-cli route-list
playwright-cli unroute "**/*.jpg"
```

### Storage — 登录态保存/注入
```bash
playwright-cli state-save auth.json      # 保存 cookies+localStorage
playwright-cli state-load auth.json      # 恢复登录态
playwright-cli cookie-set session_id abc123 --domain=example.com --httpOnly --secure
playwright-cli cookie-list --domain=example.com
playwright-cli localstorage-set theme dark
```

### DevTools — 看请求/控制台
```bash
playwright-cli console                # 控制台输出
playwright-cli requests               # 网络请求列表
playwright-cli request 5              # 第 5 个请求详情
playwright-cli eval "document.title"
playwright-cli eval "el => el.getAttribute('data-testid')" e5
playwright-cli run-code "async page => await page.context().grantPermissions(['geolocation'])"
```

### 定位元素
```bash
playwright-cli click "#main > button.submit"          # css
playwright-cli click "getByRole('button', { name: 'Submit' })"
playwright-cli click "getByTestId('submit-button')"
playwright-cli find "Sign in"                          # 快照内搜文本
playwright-cli find --regex "/sign (in|up)/i"
```

### 输出管道化
```bash
playwright-cli --raw eval "JSON.stringify([...document.querySelectorAll('a')].map(a => a.href))" > links.json
TOKEN=$(playwright-cli --raw cookie-get session_id)
playwright-cli list --json
```

### 会话/多标签
```bash
playwright-cli -s=mysession open example.com --persistent   # 持久化 profile
playwright-cli tab-new https://example.com/other
playwright-cli tab-select 0
playwright-cli attach --cdp=http://localhost:9222           # 连已有 Chrome
playwright-cli open --mobile                                 # 移动端布局(快照更小)
```

## 专题（详见 references/）
- 请求 mock: `references/request-mocking.md`
- 测试生成: `references/test-generation.md`
- 会话管理: `references/session-management.md`
- 存储状态(cookie/localStorage): `references/storage-state.md`
- 运行代码: `references/running-code.md`
- 追踪/录像/元素属性: `references/tracing.md` / `video-recording.md` / `element-attributes.md`

## Files

- `references/playwright-tests.md` — Playwright 测试写法与常见坑（等待策略、多标签、trace、CI headless）。
