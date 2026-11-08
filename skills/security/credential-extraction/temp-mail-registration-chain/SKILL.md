---
name: temp-mail-registration-chain
version: 1.0.0
author: 么西么西
license: MIT
platforms: [linux, macos, windows]
description: "Use when 批量注册/落号需要邮箱验证码（moakt/mail.tm 临时邮箱收码链）。"
metadata:
  hermes:
    tags: [registration, temp-mail, moakt, verification-code, account-harvest]
    related_skills: [seagull-pentest, proxy-subscription-harvesting]
---

# 临时邮箱批量注册收割链

目标：对「注册/登录需邮箱验证码」的目标站点全自动落号。交付物是可复用的收码链（建箱 → 触发发码 → 收码 → 注册），不是一次性账号。

## When to Use

- 目标注册要邮箱验证码：`register {email, code}`、`login/code {email, code}`、`forgot-password/complete {email, code}`
- 需要批量落号：新用户赠金、邀请返利、薅 AI 调用额度

## 铁律

- **触发发码后必须立即收、立即用**。连续发信会覆盖旧码（服务端回「验证码已失效」），码有效期约 10 分钟但从邮件到达起算——囤码必烂。
- **邮箱用户名必须唯一**。moakt 同用户名的箱子可能是别人用过的，历史邮件（别的产品的验证码）会混进收件箱造成误读。
- **验证码格式别用数字正则硬抓**。实测同时存在 6 位纯数字和 6 位 hex（如 `94ebfb`）——数字正则对 hex 码永远零命中，必须用 `[0-9a-f]{6}` 或邮件正文锚文本。
- 收码链要先在自己邮箱上跑通全流程（建箱→发码→收→注册成功），再去打目标。

## 工作流（顺序固定）

1. **建箱**：browser session 里 fetch POST 建箱（保登录态跨调用）
2. **触发发码**：打目标的验证码端点（`get/email/code?email=` 或 `verification-codes/email` POST）
3. **等 ~15 秒轮询收件箱**（listmonk 发出的邮件延迟 15 秒级，15s 一轮基本一轮命中）
4. **解析验证码**：详情页正文锚文本定位，别全文正则
5. **立即注册/登录**：从拿到码到发出请求控制在 1 分钟内

## moakt.com 工作流（么西么西指定主力，mail.tm 被目标屏蔽时的替代）

```python
# browser_exec 内执行
# 1) 建箱
fd = FormData(); fd.append('domain','teml.net'); fd.append('username','<唯一名>'); fd.append('setemail','<user>@teml.net')
fetch('/zh/inbox', {method:'POST', body: fd, redirect:'manual'})  # opaqueredirect = 正常
# 2) 轮询收件箱
h = (await fetch('/zh/inbox', {credentials:'include'})).text()
# DOMParser 解析 a[href*="/zh/email/"] 拿邮件 uuid
# 3) 详情页 goto_url 导航（fetch 详情页会被重定向回 inbox），innerText 找锚文本
```

- 邮件正文锚文本（AskFox/APINebula 系）：`verification code for this request is: <码>`，10 分钟有效
- **箱子 1 小时过期**——页面有倒计时；长会话任务中途要换箱
- 建箱响应是 opaqueredirect 不是 JSON，别用 json.loads 解析

## mail.tm（备选）

- API：`/domains` `/accounts` `/token` `/messages`；`/domains` 可能返回 hydra:member 分页结构（解析时兼容 list/dict）
- 实测被部分目标邮件系统屏蔽（触发 200 success 但收不到）——先 moakt 再 mail.tm

## 目标端限速模型（决定验证码爆破可不可行）

自研 Java 后端常见配置，打之前先摸清：

- **3 次错误锁当前码**（第 4 次起「验证码次数过多」→ 码作废）
- **3 次发信限速**（每邮箱/窗口，「验证码发送过于频繁」）
- hex6 空间 = 1670 万，叠加 3+3 限速 = **验证码爆破不可行**，老老实实收码
- **登录端点常无限速**——拿到有效码登录后若要打密码爆破，走登录端点（字典×运营者邮箱）

## 坑

- 邮件详情页 fetch 会被重定向回 inbox 拿到列表页——用 `goto_url` 导航详情再读 `innerText`
- browser_exec 的 JS 里别用 `\b` 边界正则（Python→JS 传递会炸 SyntaxError），用字符类 `[0-9a-f]{6}`
- 「验证码已失效」≠ 码错——是码被后续发信覆盖或过期，重新触发一发
- 邮箱枚举侧信道：forgot-password 对有无注册账号可能同回 success，但「该收件邮箱请求过于频繁」类限速消息会暴露该邮箱有发信记录

配套：`seagull-pentest` 技能内的自研后端侦察参考（验证码端点识别与限速测试、OpenAPI schema 读法）。
