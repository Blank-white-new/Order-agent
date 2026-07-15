# 订单生命周期、确认和幂等

## 转换表

| 当前 | 允许目标 |
|---|---|
| `DRAFT` | `CUSTOMER_CONFIRMED`, `CANCELLED` |
| `CUSTOMER_CONFIRMED` | `SUBMISSION_STARTED`, `CANCELLED` |
| `SUBMISSION_STARTED` | `MERCHANT_PENDING`, `SUBMISSION_FAILED`, `CANCELLED` |
| `MERCHANT_PENDING` | `MERCHANT_ACCEPTED`, `MERCHANT_REJECTED`, `CANCELLED` |
| `MERCHANT_ACCEPTED` | `COMPLETED`, `CANCELLED` |
| `MERCHANT_REJECTED`, `SUBMISSION_FAILED` | `CANCELLED` |
| `CANCELLED`, `COMPLETED` | 无 |

所有 DB order status 改变经 `OrderLifecycleService`，非法转换返回 `INVALID_ORDER_TRANSITION`并追加 OrderEvent。涉及 merchant 的后续状态仅供明确 synthetic fixture 测试；产品路径没有 POS，因此只到 `CUSTOMER_CONFIRMED`。

`unknown != accepted`，`pending != accepted`，HTTP 200、本地 `SIM-*` ID 和 `CUSTOMER_CONFIRMED` 都不是 merchant acceptance。对外同时返回 `lifecycleStatus=CUSTOMER_CONFIRMED` 和 `merchantStatus=NOT_INTEGRATED`。兼容字段 `submitted` 已 deprecated，只表示本地模拟草稿已锁定。

## 确认绑定

确认保存 `order_id + draft_version + confirmation_fingerprint + source + confirmed_at`。确认前重新从 DB 读取价格、币种、modifier、售罄、过敏原和配送费。session 中持久化草稿与本次请求 fingerprint 不同时返回 `CONFIRMATION_STALE`。问句、沉默或另一 session 不创建 confirmation。

已确认订单不允许继续修改；开始新点餐使用新 Order。管理性确认失效会标记 `invalidated_at`、取消原 order 并使旧幂等结果返回 `CONFIRMATION_STALE`。

## 幂等

唯一范围是 `(restaurant_id, branch_id, scope, idempotency_key)`。请求 fingerprint 由权威草稿内容生成：

- 同 key + 同 fingerprint：返回同一 order/confirmation；
- 同 key + 不同 fingerprint：`IDEMPOTENCY_CONFLICT`；
- 不同 restaurant/branch：结果不复用；
- 并发插入由数据库唯一约束收敛为一个资源；
- 确认前的业务失败不写入成功记录，修复后可安全重试。
