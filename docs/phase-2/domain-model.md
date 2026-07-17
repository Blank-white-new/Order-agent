# 阶段 2 领域模型

## 实体关系

```mermaid
erDiagram
  Restaurant ||--o{ Branch : owns
  Restaurant ||--o{ MenuVersion : versions
  MenuVersion ||--o{ MenuCategory : contains
  MenuVersion ||--o{ MenuItem : contains
  MenuItem ||--o{ MenuItemAlias : aliases
  MenuItem ||--o{ MenuItemAllergen : declares
  MenuItem ||--o{ MenuItemModifierGroup : supports
  ModifierGroup ||--o{ ModifierOption : options
  Branch ||--o{ OpeningHours : schedules
  Branch ||--o{ DeliveryZone : zones
  Branch ||--o{ BranchItemAvailability : availability
  Restaurant ||--o{ ConversationSession : isolates
  ConversationSession ||--o{ Order : creates
  Order ||--|{ OrderItem : snapshots
  Order ||--o{ OrderConfirmation : binds_version
  Order ||--o{ OrderEvent : appends
  Restaurant ||--o{ IdempotencyRecord : scopes
```

## 核心不变量

| 领域 | 关键规则 |
|---|---|
| Restaurant / Branch | restaurant `code` 全局唯一；branch `(restaurant_id, code)` 唯一；active menu 使用组合外键禁止跨餐厅。 |
| MenuVersion | `DRAFT/PUBLISHED/ARCHIVED`；部分唯一索引保证每餐厅最多一个 `PUBLISHED`；restaurant-wide 发布是事务；已发布版本经管理服务拒绝修改。 |
| MenuCategory / Item | code 在 menu version 内唯一；item-category 组合外键禁止跨版本；金额为 integer minor。 |
| Translation / Alias | translation 按 entity+locale 唯一；alias 按 version+locale+normalized alias 唯一，不污染其他版本。 |
| Modifier | item/group 由 `(id, menu_version_id)` 复合外键绑定；确认时集中校验 required/min/max、重复、active、归属和名称歧义；option 加价只取权威记录。 |
| Allergen | item/version 和 allergen/restaurant 均由复合外键保护；只有 `CONTAINS/MAY_CONTAIN/UNKNOWN`；source/verified_at/version 可追溯。 |
| Operations | 营业时段可多段、跨午夜、临时关闭；availability 用 branch/restaurant、item/version、version/restaurant 三组复合外键；DeliveryZone 与 Order 用 `(id, branch_id)` 绑定。 |
| Session | `session_key` 全局唯一并首次绑定 restaurant/branch；version 乐观并发；closed 不可修改。 |
| Order | branch/restaurant、session tenant、customer/restaurant、delivery zone/branch 均为数据库复合外键；金额和 currency 经服务重算；正常流程最远到 `CUSTOMER_CONFIRMED`。 |
| Snapshot | OrderItem 保存 item code/name/unit price/modifier/allergen/menu version 快照；item/version、version/restaurant、order/restaurant 均由复合外键保护。 |
| Confirmation | confirmation 绑定 `draft_version` 和 fingerprint；旧版本、其他 session 或问句不能确认。 |
| Event / Idempotency | event `(order_id, sequence)` 唯一且追加；key 按 restaurant+branch+scope 隔离，branch/restaurant 有复合外键，同 key 不同 fingerprint 冲突。 |

Customer 仅保存最小 synthetic 字段。当前对话必需的 synthetic 电话/地址放在独立 `ConversationContactSnapshot`，不放在普通 session JSON、OrderEvent 或常规日志。本阶段未建立生产加密或法定保留期，因此不得写入真实电话和地址。
