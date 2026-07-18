# 数据保留与审计

## 默认政策

`SPEECH_AUDIO_RETENTION_ENABLED=false` 是强制边界；评测验证当前配置为 false，并验证设为 true 时 `SpeechSettings` 拒绝启动。Phase 5 不持久化原始音频、完整 transcript、Provider 原始 payload、segment 文本、完整地址、完整电话、secret、voiceprint 或 speaker embedding。

音频和 transcript 只在单次请求内存中存在。规范化不落盘；API 使用 bounded in-memory body；日志和 trace 不包含完整 transcript、synthetic 电话、地址或姓名标记。仓库中的 WAV 是公开、确定性的 synthetic tone 测试资产，不是请求保留机制。

## `speech_turn_records`

该表只保存 allow-list 元数据：

- public ID、restaurant/branch/session/order 引用；
- INPUT/OUTPUT 方向；
- Provider name/mode、encoding、sample rate、duration；
- audio SHA-256、fixture ID；
- detected/response locale、confidence bucket；
- decision classification、reason code、outcome、trace ID；
- `is_synthetic=true` 和时间戳。

评测分别验证：

- 审计记录创建：240/240；
- ORM metadata 和真实数据库禁止列：20/20；
- 无 Binary/BLOB/bytea 列，并且 240 个审计行都不含完整 payload 或完整 Base64：241/241；
- retention 配置 fail closed：2/2。

因此“有一条审计记录”只证明 audit metadata 已写入，不能作为“没有 raw audio retention”的证据；后者必须由 schema、数据库列类型和实际内容独立证明。

## 临时文件

评测只快照以下限定范围，不扫描或删除用户的其他临时文件：

- 系统临时目录中以 `phase5-speech-eval-` 开头的评测目录；
- 仓库中本轮新增的 `.wav`、`.pcm`、`.tmp` 文件，忽略 `.git`、虚拟环境、`node_modules`、`dist` 和 `__pycache__`。

评测结束后检查 3/3：评测临时目录已清理、仓库没有新增 WAV/PCM、仓库没有新增 tmp。API 负面测试还在上传前后比较同一快照，证明请求体不写磁盘。当前 temporary audio file leak 为 0。
