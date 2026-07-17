# Versioned menu translations

The Phase 4 seed covers two synthetic restaurants and four synthetic branches. Each restaurant has 11 active menu items. Each active item has one `zh-CN`, `yue-Hant-HK`, and `en-HK` name and at least one reviewed alias per locale. Category, modifier-group and modifier-option display data is localized as well. Names are presentation data; `menu_item.code` remains the identity in every language.

`scripts/seed_phase4_multilingual_menu.py` uses `Phase4MenuSeedService` and `MenuManagementService`. For each restaurant it clones the current immutable published version into a draft, adds translations and aliases, clones availability/allergen/modifier/link rows, publishes the draft atomically for all active branches, and archives the previous version. Re-running the same catalog version is idempotent. It uses SQLAlchemy services and a transaction on SQLite and PostgreSQL, not raw SQL.

Published historical rows are not edited. Existing order item snapshots retain the menu version, localized name, authoritative unit price and modifier price recorded at confirmation. Branch sold-out state is cloned by item code. Cross-tenant foreign keys and service tenant resolution prevent translations, aliases, modifiers or active versions from being attached to another restaurant.

The existing schema lacked versioned translations for modifier groups and options. Migration `20260718_0005` adds those two real tables, locale uniqueness and composite version/group/option constraints; it is not an empty phase marker.
