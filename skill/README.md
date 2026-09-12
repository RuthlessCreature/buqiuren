# 不求人命理推演 Skill

这是从 `buqiuren` 产品中单独抽出的能力层。

## 这个目录是什么

它描述“不求人”真正可复用的命理 Agent 能力：

- 八字分析顺序；
- 排盘事实纪律；
- 未知时辰处理；
- 大运/流年推演框架；
- 梅花/周易辅助路由；
- 奇门/紫微未接可靠引擎时的禁止编盘规则；
- 多模态命理资料处理；
- 长文输出标准；
- “俯瞰众生、云里雾里但有盘面依据”的不求人文风。

入口：`SKILL.md`

## 不属于 Skill 的东西

以下是产品实现，不属于命理能力本体，因此没有放进 Skill：

- Cloudflare Worker；
- D1；
- R2；
- 用户注册/登录；
- Session / CSRF；
- 管理后台；
- MiniMax API Key；
- MiniMax-M3 这个具体模型；
- 流式前端；
- Markdown 前端渲染；
- GitHub Actions 部署。

换句话说：把整个 `skill/` 复制给另一个 Agent，它应该仍然知道**怎么按不求人的方式看盘和说话**，至于底层用 GPT、MiniMax、Claude 还是本地模型，是另一层事情。

## 目录

```text
skill/
├── SKILL.md
├── README.md
└── references/
    ├── BAZI_ENGINE.md
    ├── DIVINATION_ROUTING.md
    ├── MULTIMODAL.md
    └── ORACLE_STYLE.md
```

## 建议加载方式

Agent 首先读取 `SKILL.md`。

只有在对应任务需要时再读取 references：

- 要排八字/处理未知时辰 → `BAZI_ENGINE.md`
- 要判断该不该用梅花/奇门/紫微 → `DIVINATION_ROUTING.md`
- 要看图片/视频/命盘截图 → `MULTIMODAL.md`
- 要控制“不求人”口吻 → `ORACLE_STYLE.md`

## 排盘依赖

推荐继续使用：

`china-testing/bazi@33b18354d5407727640e545c3aaec0efb4bf5282`

Skill 本身**不复制该第三方项目源码**。

原因：排盘引擎是事实数据源，不等于 Skill 本身；并且第三方源码的许可状态应独立确认。

如果宿主 Agent 已有另一个经过验证的八字排盘工具，也可以替换排盘引擎，但必须继续遵守 `BAZI_ENGINE.md` 的数据纪律。

## 迁移原则

以后“不求人”产品层如果继续改 prompt / 分析逻辑，应优先把真正通用的能力改动同步到 `skill/`，而不是把网站实现细节塞进 Skill。
