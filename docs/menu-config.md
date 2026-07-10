# 菜单配置

菜单数据默认从 `backend/app/data/menu.json` 加载。后端启动或 `MenuService` 初始化时会读取并校验该文件；修改菜单配置后需要重启后端。

这不是数据库菜单管理，没有库存、后台管理页面、支付系统，也没有加料加价 SKU。当前只支持通过配置维护静态菜单。

## 配置位置

- 默认配置：`backend/app/data/menu.json`
- 可选外部配置：设置环境变量 `MENU_CONFIG_PATH`

`MENU_CONFIG_PATH` 为空时使用内置默认配置；一旦设置，就只加载指定文件。如果文件不存在、JSON 格式错误或校验失败，后端会报出清晰错误，不会静默回退到默认菜单。

## 顶层字段

- `version`：配置版本，目前只支持 `1`。
- `currency`：币种，当前默认 `CNY`。
- `categories`：分类数组，控制分类顺序、分类别名和分组。
- `category_group_aliases`：分类组别名，例如“主食”“正餐”都可解析到主食组。
- `safe_match_aliases`：安全点菜匹配别名，用于 ASR/输入噪声纠错，例如“机腿饭”匹配“鸡腿饭”。
- `items`：菜单项数组，必须非空。

## 菜单项字段

- `id`：必填，非空字符串，全局唯一。
- `name`：必填，非空字符串，全局唯一。
- `category`：必填，非空字符串，必须出现在 `categories` 中。
- `price`：必填，非负整数，单位为元。
- `tags`：字符串数组，用于推荐和偏好匹配。
- `spicy_level`：非负整数，用于不辣/清淡推荐过滤。
- `available`：布尔值；`false` 的菜品不会展示、推荐或被点单匹配。
- `options`：字符串数组，例如“不辣”“少辣”“加饭”。
- `aliases`：字符串数组，普通菜名别名。
- `description`：展示说明。
- `ingredients`：字符串数组，用于成分、忌口和过敏判断。
- `allergens`：字符串数组，用于过敏提示。
- `recommended_score`：数字，推荐排序主要按分数降序，再按价格升序。
- `recommend_reason`：推荐文案。
- `prep_speed`：出餐速度标签，例如 `fast`、`normal`。
- `taste_profile`：口味标签数组。
- `portion`：分量标签，例如 `small`、`medium`、`large`。

## 常见修改

新增菜品：

1. 在 `items` 中添加一项。
2. 使用唯一的 `id` 和 `name`。
3. 确认 `price` 为非负整数。
4. 确认 `category` 已在 `categories` 中定义。
5. 按需补充 `tags`、`options`、`ingredients` 和 `recommended_score`。

新增别名：

1. 普通菜名别名写到该菜品的 `aliases`。
2. 只用于纠正常见错字/同音字的安全匹配写到 `safe_match_aliases`。
3. 别名不能为空，不能与其他菜品名称或别名冲突。

设置下架：

将菜品的 `available` 改为 `false`。该菜品仍保留在配置中，但不会出现在 `/api/menu`，不会被推荐，也不能通过菜名或别名点单。

调整推荐排序：

调整 `recommended_score`。推荐排序保持现有规则：分数更高优先；同分时价格更低优先。

## 校验规则

- `items` 必须存在且为非空数组。
- `version` 必须是支持的版本。
- `id`、`name`、`category` 必须是非空字符串。
- `price` 必须是非负整数。
- `aliases`、`tags`、`options`、`ingredients`、`allergens`、`taste_profile` 必须是字符串数组。
- `available` 必须是布尔值。
- `recommended_score` 必须是有限数字。
- `id` 不能重复。
- `name` 不能重复。
- `aliases` 和 `safe_match_aliases` 不能包含空字符串。
- 菜名、普通别名和安全匹配别名不能发生冲突。
- `safe_match_aliases` 只能引用存在的 `item id`。
- 菜品 `category` 必须存在于 `categories`。

## 常见错误

- 重复 `id`：改成唯一 `id`。
- 负价格：把 `price` 改成非负整数。
- 缺少 `name`：补齐非空菜名。
- alias 冲突：删除或改名，保证别名只匹配一个菜品。
- JSON 格式错误：检查逗号、引号、括号是否完整。
- 外部配置路径不存在：确认 `MENU_CONFIG_PATH` 指向真实 JSON 文件。
