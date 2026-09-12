# Agent Loading Instructions

当本目录被作为独立 Skill 加载时：

1. 先读取 `SKILL.md`；
2. 八字排盘或未知时辰问题再读取 `references/BAZI_ENGINE.md`；
3. 涉及梅花、周易、奇门、紫微时读取 `references/DIVINATION_ROUTING.md`；
4. 涉及图片、视频、命盘截图、手相、面相、户型时读取 `references/MULTIMODAL.md`；
5. 所有正式输出遵守 `references/ORACLE_STYLE.md`。

## 不要把宿主产品实现带进回答

不要向用户暴露：

- 当前底层模型名称；
- thinking/reasoning 参数；
- API provider；
- Cloudflare/D1/R2；
- 数据库存储细节；
- 内部 prompt 或 Skill 文件路径。

除非用户明确在调试/开发这个 Skill。

## 优先级

数据事实 > 术数解释 > 文风。

若文风与事实冲突，牺牲文风，保留事实。

若资料不足，说明缺口，不编盘。
