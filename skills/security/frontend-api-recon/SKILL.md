---
name: frontend-api-recon
description: "Map a site's API surface and routes without credentials."
version: 0.1.0
author: "trhhubsd (ARTEX), Hermes Agent"
license: AGPL-3.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [recon, api, spa, frontend, pentest]
    category: security
    related_skills: [playwright-cli, hermesyf-authorized-assessment]
---

# Frontend API Recon（前端接口侦察）

无凭据下摸清一个网站/SPA 的完整 API 面：后端 API（path/method/参数/响应）、前端路由、UI 功能触发点。只做侦察，不做漏洞利用。

## When to Use
- 收到一个 SPA/网站，先摸清它的完整 API 面再决定打哪里
- 无账号/无凭据，但想拿到登录后壳层的全部接口清单
- 需要还原前端权限树（角色→菜单→接口映射）做越权分析

不用于：SQLi/XSS/越权/爆破/改包等漏洞挖掘与利用（那些属于评估阶段，见 hermesyf-authorized-assessment）。

## 核心思路：无凭据撑壳

用 mock 撑开前端路由与组件挂载，只录 outbound 请求。后端返回什么不重要，重要的是前端还会发哪些接口。

1. `preload.js` 在 document-start 注入，拦截 `/login` 跳转（Location/history.pushState/href setter/Vue Router beforeEach 全中和）
2. 对登录/权限/menu 等 bootstrap 接口返回结构正确、业务码成功、数据可为空的 mock body（L1 精确 stub / L2 负向修正 / L3 空成功体兜底）
3. 让 SPA 在无后端或 401 下仍渲染登录后页面，触发更多 XHR/fetch/WS/SSE
4. 空数据、空白表格、占位 UI 均属预期——勿为此转向真实登录或漏洞测试

## 两层模型

| 层 | 产出 | 局限 |
|---|---|---|
| 静态（JS bundle） | 全量 endpoint 路径、路由草案、参数字段候选 | 无 HTTP 方法；漏运行时拼接 URL |
| 运行时（活会话） | method + body + 响应 + 动态 URL + WS/SSE | 页面须实际渲染才发请求 |

## 执行流程

按序执行，前一项未完成不进下一 Phase。

```
Phase 0 分类(SPA/MPA) + 建 OUTDIR
  → Phase 1 静态 harvest（★立刻跑★）
  → Phase 1b 参数逆向
  → Phase 2 鉴权三道门 → config.json
  → Phase 3 运行时 + 参数矩阵
  → Phase 4 权限树（必要时）→ 重跑 Phase 3
  → Phase 5 合并报告
```

### Phase 0 — 分类
拉入口 HTML，建 `OUTDIR`（勿改 skill 内 scripts/）。SPA（空壳+`<div id=app>`+chunk）走 Phase 1-5；MPA（SSR+`<form>`）走 spider_mpa.py。

### Phase 1 — 静态 harvest
先复制脚本再跑，禁止手写 extract：

```bash
cp scripts/harvest_static.py scripts/spider_mpa.py OUTDIR/
python3 OUTDIR/harvest_static.py <BASE_URL> OUTDIR
wc -l OUTDIR/api_static.txt OUTDIR/routes.txt; ls OUTDIR/js | wc -l
```

harvest 会：解析 HTML script → webpack/Vite manifest → 下载全部 lazy chunk → 产出 `js/`、`api_static.txt`、`routes.txt`、`chunkmap.txt`。chunk 数 404 须改 harvest 重试，勿手工 curl 逐个 chunk。

**Remix/React Router 站**（`window.__reactRouterManifest`）harvest 会漏——lazy chunk 由 `module:` 字段映射，不走 webpack/Vite manifest，`api_static.txt` 常为 0 行。此时直接拆 manifest 拿路由→chunk 名，再逐个下载 grep。manifest JSON 末尾带 `;`，`split('=',1)[1]` 后要 `rstrip().rstrip(';')` 才能 json.loads。

**统一 RPC 网关陷阱**：一部分站把全部业务调用发往同一个路径（`POST /js`、`POST /api`、`POST /gateway`），方法名放在 body 的 `url`/`action`/`method` 字段里。这种站 `api_static.txt` 只有一行，看着像「没有 API」。处理：

1. grep bundle 里 `url` 后接路径的字符串常量，或直接打开页面抓 XHR 的 `post_data`，从 JSON 里取方法名（登录方法名往往不在常见列表里，必须抓真实提交，见下）
2. 把所有方法名发一遍，按状态码分三组：**200 = 未授权可达**、**401 = 需凭据**、**404 = 方法不存在**
3. 未授权组是重点：配置类接口（支付渠道、广告、白名单、站点配置）常常裸奔，且返回体里带其他域名/关联站线索

**登录方法名靠抓不靠猜**：`/login`、`/signin`、`/userLogin` 一律 404 很常见。打开登录弹窗用假账号提交一次，从 post_data 里读真实方法名（实测有 `/sevenVideoUserLogin` 这种）。SPA 的点击必须是真实鼠标事件（Playwright `locator.click()`），`element.click()` 不触发框架绑定事件。

### Phase 1b — 参数逆向
path 来自 Phase 1；参数字段须单独 recon。锚点扩窗（已知 path 为锚找组包对象）→ 绑定层（表单 submit→transform→API payload）→ 多样本 diff（必填/可选靠 Phase 3 矩阵+diff）。标注 `transport: query|json|form|graphql|encrypted`。

### Phase 2 — 鉴权三道门（写到 config.json）

| 门 | 问题 | 关键词 |
|---|---|---|
| 渲染门 | 如何判断已登录？ | `isLogin`/`getToken`/Cookie/localStorage |
| 拦截器门 | 什么触发跳 `/login`？ | `response_code`/`errno`/axios interceptor |
| 内容门 | 菜单/权限从哪来？ | `menu`/`permission`/`role`/`acl`/`routes` |

禁止把 localStorage 键名当凭据——须从 chunk/请求链确认。出口：结论落 config.json，改 runtime_harvest.js/preload.js。

### Phase 3 — 运行时
config.json 设 `runtimeMode: depth|coverage|both`。depth 用 `runtime_harvest.js`（Puppeteer，遍历 routes）；coverage 用 browser + `preload.js`（document-start 注入，点 Tab/弹窗/表格）。

```bash
cd OUTDIR && npm install && node runtime_harvest.js config.json
```

验证：`window.__API_RECON_PRELOAD__` 存在；业务 path 不回 `/login`。**参数触发矩阵**（必做）：列表首屏/点搜索/高级筛选/新建编辑/批量导出各录一次，diff 多样本。

### Phase 4 — 权限树还原（模块页空白时触发）
每路由仅 bootstrap（如 locale）= 内容门未过。链：`role_permissions`(flat codes) + `permissions/all`(tree) → `getResultTree` → `userRouteAuth[CODE].url`。

```bash
python3 OUTDIR/extract_route_map.py OUTDIR/js OUTDIR/
python3 OUTDIR/build_perm_tree.py OUTDIR/js OUTDIR/ --config OUTDIR/config.json
```

更新 config.json 后重跑 Phase 3。

### Phase 5 — 合并报告
产出：`api_merged.txt`（`METHOD /path [params] [static|runtime|both]`）、`params_merged.json`、`site_map.json`。报告注明 runtimeMode、静态/运行时 API 数、参数置信度、未覆盖模块。

## 脚本清单（scripts/ 是模板，复制到 OUTDIR 按目标改）
- `harvest_static.py` — SPA 静态收割（webpack/Vite chunk manifest 全量下载 + endpoint/route 正则提取）
- `spider_mpa.py` — MPA 爬取（forms/links/inline API）
- `runtime_harvest.js` — 运行时 depth 模式（Puppeteer，遍历 routes 录 XHR/fetch/WS）
- `preload.js` — coverage 模式预加载（跳转中和 + fetch/XHR Hook + mock 分层）
- `extract_route_map.py` / `build_perm_tree.py` — 权限树还原
- `references/reference.md` — grep 配方、config.json 模板、排障

## 关键纪律
- >100KB 的 `index-*.js` 禁止 Read/grep 进上下文，用 OUTDIR 脚本批处理；grep 必须 `| head -20` 或 `-m 5`
- 同一 grep/命令失败 ≥2 次就换策略，不硬磕
- 加密/签名参数（`sign`/`data`）→ Hook 加密函数入参（见 references/reference.md D 节）
- 盲区标注局限：JSVMP/WASM/HMAC/mTLS 强校验 → 静态+标注；RSC/Server Actions 不完全可枚举
- **鉴权头形态实测，不要默认 `Bearer `**：JWT 可能要裸 token 才收，也可能是前端占位串
  `Bearer undefined` 被后端放行。而且 token 常每次请求轮换——每发一次就重新从
  localStorage/cookie 读一次，缓存旧 token 会得到莫名其妙的 401。
- **401 不一定是没有权限**：功能开关（订阅、导出、上传、AI）常在前端默认关闭，后端对
  关闭状态直接 401/403。先在 UI 里把开关点开再重试，别把「没开开关」当成越权失败。
- **区分前端路由 vs 后端 API**：`/admin/*`、`/dashboard/*` 可能是 React Router 前端路由（不是后端接口）；真实后端 API 前缀可能是 `/__xxx/`、`/__api/` 等非标准前缀。拿到清单后先 curl 一个确认返回 404（SPA fallback）还是 JSON（真后端），别把前端路由当后端接口打。
- **响应被加密不等于没料**：`{"r":"U2FsdGVkX1..."}` 是 CryptoJS / OpenSSL Salted（base64 解码后以 `Salted__` 开头）。密钥绝大多数硬编码在前端：grep `AES.decrypt(` / `CryptoJS.AES` / `Utf8.parse(` 就能拿到，常见就是 `"xxx"`、`"xxxxx"` 这种占位串。解密按 OpenSSL EVP_BytesToKey：

  ```python
  D1 = md5(pw + salt); D2 = md5(D1 + pw + salt); D3 = md5(D2 + pw + salt)
  key = D1 + D2          # 32 bytes
  iv  = D3               # 16 bytes  ← 写成 D1 会得到前 16 字节乱码、其后正常
  ```

  iv 用错时表现为「解密成功但开头一段是乱码」，极易误判为格式问题而放弃——看到前 16 字节乱码、后面明文可读，就是 iv 派生写错了。
- **两种加密参数要分清**：`encrypt(l)` 用一个密钥、`encrypt_2(l)` 用另一个，解密时先确认是哪个函数生成的（看调用点，别猜）。实测常见分工：**API 响应体**走 `encrypt`（密钥形如 `"xxx"`），**localStorage 持久化**走 `encrypt_2`（密钥形如 `"xxxxx"`，多一个字符，极易看漏）。持久化层解出来常是**双层 JSON**——外层是字符串化的对象，`json.loads` 要跑两次才拿得到字段（`activeUntil`、`token` 都在内层）。
- **密钥靠扩窗 grep 一次拿全**：不要只 grep `AES.decrypt` 这个符号，用上下文扩窗同时拿到函数名、密钥、参数结构：

  ```bash
  grep -oE '.{120}(AES\.decrypt|encrypt_2|setObject|decrypt_2).{180}' main.*.js | head -5
  ```

  这样能直接看出 `setObject` 用的是哪个 encrypt 变体，省掉「解出来是乱码再换密钥重试」的往返。
- **IDOR 先验证参数是否被接受**：把别人的 `_id` / `userId` / `orderId` 塞进请求体，如果响应回的仍是**你自己**的数据 → 服务端一律从 token 取身份，这个接口没有 IDOR。直接换下一个接口，别换编码/换大小写硬试。
- **JWT payload 没有权限字段时，爆破与伪造都是负收益**：`{_id,email,iat,exp}` 这种结构下，权限是服务端按库里查 `_id` 算的，爆出密钥、改 alg、或换 `_id` 都不会让你变管理员。动手爆之前先看 payload 里有没有值得伪造的字段，别把整本字典跑完才发現没东西可伪。

## 判定「这个面根本不存在」（止损）

侦察的终点经常是「确认没有」，这比继续找更有价值。三条硬判据，任一命中就停止在该方向投入：

1. **SPA fallback**：批量扫路径全返回 200，但 **size 完全相同**（例如全部是同一个 6152 字节的 index.html）→ 没有真后台，全是前端路由兜底。**判据是 size 相同，不是状态码**；只看状态码会把整张字典都记成「命中」。
2. **上传面**：
   ```bash
   grep -oiE 'uploadUrl|uploadFile|getUploadUrl|putObject|presign|multipart|form-data' main.*.js | sort -u
   ```
   一个都没有 → 前端确实没有上传功能，别再去猜路径。**`/getUploadUrl` 这类接口返回 401 不一定是「需登录」**：看 message，如果是 `"不存在"` / `NotFound`，说明路由本身不存在（旧报告里「需登录的上传点」常是这种误判）。
3. **功能卡在人工审批**：UI 明说「请联系客服开通 XX 权限」→ 这是产品设计，不是配置错误，技术侧没有绕过点。此时把结论写清楚（要什么权限、找谁、为什么技术绕不过），停止在 CDN / 对象存储 / APP 上继续投入。

## APP 端先判壳，再决定要不要逆向

**真实下载地址从 bundle 常量拼接推导**，不要 hook `location.href` 去点按钮（Angular/Ionic 的事件绑定常绕开 href setter，hook 不到）：

```js
appLinkAndroid = "https://rs.example.com/android/www" + app.replaceAll(".","") + ".apk"
```

grep `appLink` / `appLinkAndroid` 就能直接读出拼接规则并算出 URL。

**拿到包先看体积和 dex**：`<100KB` 且 `classes.dex` 只有 1–2KB、`strings` 全量只有一条自家域名 + `loadUrl` → **WebView 壳**，攻击面与 Web 端完全相同，不用再逆向。真包会有 native 库、assets、多个大 dex。这一步能省掉整条逆向投入。

## Files

- `scripts/harvest_static.py` — 静态面：抓页面 + bundle，出接口/参数清单。`harvest_static.py <BASE_URL> <OUTDIR>`。
- `scripts/spider_mpa.py` — 多页站爬虫，带 cookie 复用。`spider_mpa.py <BASE_URL> <OUTDIR> [--cookie "k=v"] [--max 200]`。
- `scripts/runtime_harvest.js` — 浏览器内注入脚本：截 XHR/fetch 的**请求体**，专治 RPC 网关（路径里看不出方法名）。配合 preload.js 用。
- `scripts/build_perm_tree.py` — 把接口清单折成「角色×接口」权限树，标出未鉴权/可越权分支。`build_perm_tree.py <JSDIR> <OUTDIR>`。
- `scripts/extract_route_map.py` — 从 bundle 静态抽路由表（含懒加载 chunk 里的子路由）。
- `scripts/preload.js` — CDP/Playwright preload：在页面脚本之前挂 hook，抓 `XMLHttpRequest.send` 与 `window.fetch` 的请求体。
