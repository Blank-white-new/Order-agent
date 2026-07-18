# 数据保留与审计

## 默认政策

`SPEECH_AUDIO_RETENTION_ENABLED=false` 是强制边界；代码在尝试开启时直接拒绝启动。Phase 5 从不持久化原始音频、完整 transcript、Provider 原始 payload、segment 文本、地址、电话、secret、voiceprint 或 embedding。

音频和 transcript 只在单次请求内存中存在。规范化不落盘；API 不创建临时文件；日志和 production trace 不包含完整 transcript 或音频。仓库中的 WAV 是公开、确定性 synthetic tone 测试资产，不是请求保留机制。

## `speech_turn_records`

单独审计表避免污染权威订单模型，并允许 tenant/session 外键和数据库约束。字段只包括：

- public ID、restaurant/branch/session/order 引用；
- INPUT/OUTPUT 方向；
- Provider name/mode、encoding、sample rate、duration；
- audio SHA-256、fixture ID；
- detected/response locale、confidence bucket；
- decision classification、reason code、outcome、trace ID；
- `is_synthetic=true` 和时间戳。

表中没有 raw audio 或 transcript 列。所有写入都先解析 tenant，并使用 restaurant+branch+session 范围查询，数据库外键/约束和仓储层共同阻止跨租户写入。public ID 唯一，order 引用可空且只指向当前会话最新订单。

## 清理

当前实现没有上传临时目录和后台缓存，所以请求结束时没有需要删除的音频文件。测试和评测检查 raw audio persistence、full transcript logging 及临时文件泄漏均为 0。
