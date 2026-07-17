import { useEffect, useRef, useState } from "react";
import { getMenu } from "../api/chatApi";
import { formatPrice, MenuItemView, MenuView } from "../types/order";
import { ConcreteLocale } from "../i18n";

type MenuPanelProps = {
  onPickItem: (text: string) => void;
  locale?: ConcreteLocale;
};

export function MenuPanel({ onPickItem, locale = "zh-CN" }: MenuPanelProps) {
  const [menu, setMenu] = useState<MenuView>({ categories: [], items: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const mountedRef = useRef(false);

  async function loadMenu() {
    setLoading(true);
    setError(false);
    try {
      const result = locale === "zh-CN" ? await getMenu() : await getMenu(locale);
      if (mountedRef.current) {
        setMenu(result);
      }
    } catch (err) {
      console.warn("Failed to load menu.", err);
      if (mountedRef.current) {
        setError(true);
        setMenu({ categories: [], items: [] });
      }
    } finally {
      if (mountedRef.current) {
        setLoading(false);
      }
    }
  }

  useEffect(() => {
    mountedRef.current = true;
    void loadMenu();
    return () => {
      mountedRef.current = false;
    };
  }, [locale]);

  const copy = MENU_COPY[locale];

  return (
    <section className="panel menu-panel" aria-labelledby="menu-panel-title">
      <div className="panel-heading">
        <div>
          <h2 id="menu-panel-title">{copy.title}</h2>
          <p>{copy.subtitle}</p>
        </div>
        {loading ? <span className="status-pill">{copy.loading}</span> : null}
      </div>

      {error ? (
        <div className="notice" role="status">
          <p>{copy.error}</p>
          <button type="button" className="secondary" onClick={() => void loadMenu()}>
            {copy.retry}
          </button>
        </div>
      ) : null}

      {!loading && !error && menu.items.length === 0 ? <p className="empty-state">{copy.empty}</p> : null}

      <div className="menu-groups">
        {menu.categories.map((category) => {
          const items = menu.items.filter((item) => item.category === category);
          if (items.length === 0) {
            return null;
          }
          return (
            <section key={category} className="menu-group" aria-label={`${category}菜单`}>
              <h3>{category}</h3>
              <div className="menu-items">
                {items.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    className="menu-item-button"
                    onClick={() => item.name && onPickItem(orderPhrase(locale, item.name))}
                    disabled={!item.name}
                    aria-label={item.name ? `${copy.fill}${orderPhrase(locale, item.name)}` : copy.unknown}
                  >
                    <MenuItemContent item={item} locale={locale} />
                  </button>
                ))}
              </div>
            </section>
          );
        })}
      </div>
    </section>
  );
}

function MenuItemContent({ item, locale }: { item: MenuItemView; locale: ConcreteLocale }) {
  const copy = MENU_COPY[locale];
  const tags = item.tags.slice(0, 3);
  const options = item.options.slice(0, 3);
  const isRecommended = item.recommendedScore !== null && item.recommendedScore >= 8.5;

  return (
    <>
      <span className="menu-item-head">
        <strong>{item.name ?? copy.unknown}</strong>
        {isRecommended ? <em>{copy.recommended}</em> : null}
      </span>
      <span className="menu-price">{formatPrice(item.priceMinor, item.currency)}</span>
      {item.description ? <span className="menu-description">{item.description}</span> : null}
      {tags.length > 0 ? <span className="menu-tags">{tags.join(" · ")}</span> : null}
      {options.length > 0 ? <span className="menu-options">{copy.options}: {options.join(locale === "en-HK" ? ", " : "、")}</span> : null}
    </>
  );
}

const MENU_COPY: Record<ConcreteLocale, Record<string, string>> = {
  "zh-CN": { title: "菜单", subtitle: "点击菜品只会填入输入框", loading: "加载中", error: "菜单暂时加载失败，可继续用文字点餐。", retry: "重试", empty: "菜单暂时为空。", fill: "填入", unknown: "菜品名称待确认", recommended: "推荐", options: "可选" },
  "yue-Hant-HK": { title: "餐牌", subtitle: "撳菜式只會填入輸入框", loading: "載入中", error: "餐牌暫時載入失敗，可以繼續用文字落單。", retry: "再試", empty: "餐牌暫時冇內容。", fill: "填入", unknown: "菜式名稱待確認", recommended: "推介", options: "可選" },
  "en-HK": { title: "Menu", subtitle: "Selecting an item only fills the message box", loading: "Loading", error: "The menu could not be loaded. You may continue ordering by text.", retry: "Retry", empty: "The menu is currently empty.", fill: "Fill message with", unknown: "Item name pending confirmation", recommended: "Recommended", options: "Options" },
};

function orderPhrase(locale: ConcreteLocale, name: string): string {
  if (locale === "en-HK") return `I want one portion of ${name}`;
  if (locale === "yue-Hant-HK") return `我要一份${name}`;
  return `我要一份${name}`;
}
