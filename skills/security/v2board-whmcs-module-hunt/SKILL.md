---
name: v2board-whmcs-module-hunt
description: "Use when 找 v2board WHMCS 模块同类洞 / 机场 .git 泄露。"
version: 1.0.0
author: 么西么西
license: MIT
metadata:
  hermes:
    tags: [pentest, v2board, whmcs, airport, git-leak]
    related_skills: [whmcs-assessment, xboard-airport-pentest]
---

# v2board WHMCS 模块：同类洞狩猎

目标形态：机场站用 WHMCS 做计费前台，装第三方 `modules/servers/v2board/` 模块，对外桥接 v2board 后端 API。模块的 `config.php` 里存 `api_url` + `api_token`（明文）。

## 为什么不能靠 FOFA 页面特征找

把模块源码读完就知道了：`v2board.php` 只有 `v2board_AdminServicesTabFields`（**后台**服务页字段）和 `v2board_ConfigOptions`（后台产品配置），**前台一行输出都没有**。所以 `body="v2board"`、`body="modules/servers/v2board"` 这类查询全部 0 结果（实测）。

## 唯一可行的指纹：直连 php 看是否被 PHP 执行

```
GET /modules/servers/v2board/v2board.php
```

- **500 + `Fatal error`**（常带绝对路径）→ 模块存在且被执行，拿到源码路径，顺路径探 `.git`
- **200 但 body 极短/空** → 文件存在无输出
- **200 + 完整 HTML** → SPA 前端 fallback，**假阳性**
- **404 `File not found.`** → 没装
- **502 / 403 / 418** → 反代挂了 / CDN 拦截 / WAF，**全部假阳性**

同一路径再探 `/modules/servers/v2board/.git/config`，判据是 body 含 `repositoryformatversion`，否则就是 SPA 冒充。

## 批量脚本

`/root/.hermes/cache/scratch/v2hunt/` 下三个（可直接复制改）：

- `probe_module.py` —— 对含 `clientarea.php` 的机场站探四点（模块/模块.git/根.git/WHMCS 安装 SQL）
- `probe_v2b_module.py` —— 对 `title="V2Board"` 面板站探同域模块
- `probe_leak.py` —— 对 `body="v2board" && body=".git"` 候选探泄露

统一走 mihomo 7890，15 并发，7s 超时。

## 实测命中率（先看这个再决定投入）

| 候选池 | 来源 | 结果 |
|---|---|---|
| 59 | `body="v2board" && body=".git"` | 真命中 0 |
| 274 | `body="clientarea.php" && body="机场"` | 装模块的 0 |
| 802 | `title="V2Board"` | 真命中 0 |

**结论：这不是通杀洞。** 1135 个样本里没有一例同时满足“装了该模块 + `.git` 可读”。这个模块装机量本来就低，再加上要 `.git` 没删 + nginx deny 失效 + token 弱口令，四个条件叠加。别拿“v2board 洞”当批量靶子。

## 非目标面的副产物（顺手能当新入口）

同一批扫描里真实捞到的：

- `/resources/sql/install/tblconfiguration.data.sql` 可读 → **WHMCS 安装 SQL 残留**，明文版本号（实测有 7.7.1、8.13.3 两例）。老版本 CVE 面大，值得单开一轮。
- 根目录 `/.git/config` 可读 → 可能是任意开源程序（实测两例是 onenav 导航站，非机场）。**先看 remote url 再判断价值**，别看到 git 就兴奋。

## 假阴性防坑

- **CDN IP 直连必 403**：FOFA 返回 104.21.x / 172.67.x 这类 Cloudflare 段，直连没 Host 头就是 403，别当成“目录存在但被保护”。
- **502 占大头**：机场站反代经常是坏的，空 body 502 不代表模块在。
- **判据要卡死**：`len(body) < 200 and "<html" not in body` 会把 502 也算进去，必须显式分状态码。

## 打穿后的链路（模块确实命中时）

1. `.git` 逐对象 dump 恢复 8 个文件（`v2board.php` / `hooks.php` / `lib/v2board.php` / `config.php` / `client.tpl` 等）
2. `config.php` → `api_url` + `api_token`
3. `GET {api_url}/v1/whmcs/{server_id}/{service_id}`，header `authorization: <token>`（**裸写，不加 Bearer**）
4. 返回 `uuid/passwd/subscribe_token/transfer_enable/expired_at`；`service_id` 线性可遍历
5. `GET {sub_host}/clash/{service_id}/{subscribe_token}/` 拉完整 Clash YAML

详细手法见 `whmcs-assessment` 与 `xboard-airport-pentest`。
