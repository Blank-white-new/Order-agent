# 菜单版本化和权威价格

阶段 2 选择 restaurant-wide 发布模式：一家餐厅的当前发布版本由事务切换到所有分店。branch 仍保留 `active_menu_version_id`，便于未来经餐厅策略审阅后扩展 branch-specific 发布；本阶段不同时支持两种发布语义。

## 发布流程

1. `create_draft` 在 restaurant 内生成新 version number。
2. 导入 category/item/translation/alias/modifier/allergen，所有引用不得跨 version。
3. 验证分店均属于该 restaurant。
4. 一个事务内将旧 `PUBLISHED` 归档、新版本发布，并切换 restaurant 的 branch active menu。
5. 新请求的 MenuService refresh 直接读取新版本，不需重启 app。

已发布/已归档版本经管理服务返回 `PUBLISHED_MENU_IMMUTABLE`。菜单缺失返回 `NO_PUBLISHED_MENU`，价格缺失时不猜测。

## 分店实时状态

MenuVersion 保存相对稳定的菜品、价格和声明；`BranchItemAvailability` 单独保存 branch 售罄状态。售罄项不可新增，已在草稿中的项在确认前再验证。`DeliveryZone` 提供 branch-specific integer minor 配送费。

OrderItem 复制当时的 item code/name/price/modifier/allergen/menu version。后续更名、改价、过敏声明变化或归档都不改写历史快照。过敏原缺少声明以显式 `UNKNOWN` 快照保存，不存在 `FREE_FROM`。
