# 不求人 · AI 命理推演

一个部署在 Cloudflare Workers 上的中文命理对话站。后端使用 Python Worker + D1；八字排盘在构建阶段固定拉取并执行 `china-testing/bazi`；对话模型默认使用 MiniMax M3 Token Plan。

> 当前工程目标是“可部署、可审计、可扩展”，不是把命理计算偷偷塞进大模型提示词里瞎算。

## 功能

- 用户名/密码注册、登录、退出、修改密码
- 用户命理档案：称呼、性别、生辰、公历/农历、闰月、时辰未知
- 未完成档案时强制阻断命理对话
- D1 持久化用户、档案、会话、消息、命盘缓存、审计日志
- `china-testing/bazi` 固定版本排盘；未知时辰进入“三柱约束模式”，不伪造时柱
- MiniMax M3 多轮对话，带完整命盘上下文与高约束系统提示词
- 梅花/周易辅助起卦上下文；奇门、紫微等由方法路由器按问题启用
- 隐藏后台 `/wotamade`：查看用户档案、会话、消息与审计数据（不会暴露密码哈希、会话令牌或任何平台 Secret）
- GitHub Actions 自动拉取指定版本 bazi、初始化/迁移 D1、注入 Cloudflare Secrets、部署 Worker

## 部署所需 GitHub Actions Secrets

在仓库 **Settings → Secrets and variables → Actions** 配置：

- `CLOUDFLARE_API_TOKEN`：具备 Workers Scripts、D1 写权限
- `CLOUDFLARE_ACCOUNT_ID`
- `MINIMAX_API_KEY`：Token Plan 的 `sk-cp...` Key
- `ADMIN_PASSWORD`：`/wotamade` 后台口令
- `SESSION_PEPPER`：至少 32 字节随机字符串，用于会话与认证派生

随后运行 Actions 中的 **Deploy Cloudflare Worker**。工作流会自动查找或创建 `buqiuren-db`，应用 `migrations/`，写入 Worker Secrets 并部署。

## 本地开发

```bash
bash scripts/vendor_bazi.sh
cp wrangler.toml.example wrangler.toml
# 将 wrangler.toml 中的 __D1_DATABASE_ID__ 替换为测试 D1 ID
uv sync
uv run pywrangler dev
```

## 关键环境变量

普通变量见 `wrangler.toml.example`：

- `MINIMAX_MODEL=MiniMax-M3`
- `MINIMAX_BASE_URL=https://api.minimax.io/v1`
- `DIVINATION_TIMEZONE=Asia/Shanghai`
- `APP_NAME=不求人`

敏感项只通过 `wrangler secret put` 注入，不写入源码。

## bazi 上游锁定

当前锁定：`china-testing/bazi@33b18354d5407727640e545c3aaec0efb4bf5282`。

构建阶段仅复制上游根目录 Python 源文件到 Worker bundle，应用层通过 `runpy` 原样执行 `bazi.py`，不重写其排盘算法。详见 `THIRD_PARTY.md`。

## 安全边界

- 密码使用 PBKDF2-SHA256 + 独立随机盐存储
- Session 仅保存服务端哈希，Cookie 为 HttpOnly + Secure + SameSite=Lax
- 写操作要求 CSRF Token
- 登录/注册有 IP 维度的数据库限流
- 管理后台不在任何前端入口出现，并使用独立 Secret 鉴权
- 管理接口默认不返回密码哈希、Session Token、CSRF Secret、平台 Secret

## 免责声明

本站内容属于传统文化研究与娱乐性推演，不构成医疗、法律、证券投资、保险或其他专业意见。涉及现实高风险决策时，应以可验证事实和专业机构意见为准。
