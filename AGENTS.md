# Project Rules

1. 本项目是多 agent 订餐系统。
2. Orchestrator 是唯一统一入口。
3. 子 agent 不能绕过 Orchestrator 修改状态或提交订单。
4. 全局语义意图优先于当前槽位。
5. fallback 永远最后。
6. 菜品、价格、配送费必须来自服务层。
7. 不允许硬编码 API Key。
8. 修改语义路由必须补测试。
9. 下单前必须确认。
10. 问句不得误修改订单状态。

