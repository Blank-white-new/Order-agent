# 音频安全

Phase 5 输入仅允许仓库内已知来源的确定性合成 tone fixture，或开发者明确上传的 synthetic WAV/PCM。它不用于真实个人资料或顾客录音。

## 校验顺序

1. 在 Provider 前检查配置和 `synthetic=true`；
2. 检查请求字节上限、MIME 和声明编码；
3. 严格解析容器、chunk、长度和元数据；
4. 检查 mono、16-bit、8/16 kHz、时长与静音；
5. 规范化只在内存中完成；
6. Replay ASR 同时校验 fixture ID 与完整 payload SHA-256；
7. 任何失败均在进入订单语义解析前 fail closed。

API 不接收文件系统路径、远程 URL、Provider 凭证或设备控制参数。错误响应不包含本机路径、manifest 内容、堆栈或 secret。上传 body 有固定上限，服务不把 body 写到磁盘。

## 数据最小化

- 原始音频不进入数据库、日志或 trace；
- 完整 transcript 仅在当前进程内传入 TextEntryService，不写审计表或日志；
- SHA-256 只作为完整性/去重元数据，不代表声纹；
- 不生成或存储 voiceprint、embedding、Provider payload；
- 没有临时音频目录，因此无需异步清理；测试会检查没有临时文件泄漏。

审计仅保存 tenant/session/order 引用、方向、Provider 元数据、编码、采样率、时长、hash、fixture ID、locale、confidence bucket、SafetyDecision、reason/outcome、trace ID 和 synthetic 标记。
