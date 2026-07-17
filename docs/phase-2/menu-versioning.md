# 菜单版本化和权威价格

阶段 2 选择 restaurant-wide 发布模式：一家餐厅的当前发布版本由事务切换到所有 active、未删除分店。`MenuManagementService.publish(restaurant_id, version_id)` 不接收 `branch_ids`；调用者不能表达“只发布到部分分店”。branch 仍保留 `active_menu_version_id`，便于未来经餐厅策略审阅后扩展 branch-specific 指派；本阶段不混用两种语义。

## 发布流程

1. `create_draft` 在 restaurant 内生成新 version number。
2. 导入 category/item/translation/alias/modifier/allergen，所有引用不得跨 version。
3. 数据库部分唯一索引保证同一 restaurant 最多一个 `PUBLISHED`。
4. 一个事务内锁定/归档旧 `PUBLISHED`、发布新版本，并切换该 restaurant 全部 active、未删除 branch 的 active menu。
5. 新请求的 MenuService refresh 直接读取新版本，不需重启 app。

并发发布两个 draft 时数据库唯一索引和事务锁只允许一个竞态赢家；失败者得到 `MENU_PUBLISH_CONFLICT`，不会提交“所有分店无 active menu”的中间状态。已发布/已归档版本经管理服务返回 `PUBLISHED_MENU_IMMUTABLE`。菜单缺失返回 `NO_PUBLISHED_MENU`，价格缺失时不猜测。

## 分店实时状态

MenuVersion 保存相对稳定的菜品、价格和声明；`BranchItemAvailability` 单独保存 branch 售罄状态，并由 branch/restaurant、item/version、version/restaurant 复合外键限制。售罄项不可新增，已在草稿中的项在确认前再验证。`DeliveryZone` 提供 branch-specific integer minor 配送费。

OrderItem 复制当时的 item code/name/price/modifier/allergen/menu version。后续更名、改价、过敏声明变化或归档都不改写历史快照。过敏原缺少声明以显式 `UNKNOWN` 快照保存，不存在 `FREE_FROM`。
