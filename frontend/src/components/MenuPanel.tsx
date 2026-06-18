import { useEffect, useRef, useState } from "react";
import { getMenu } from "../api/chatApi";
import { formatPrice, MenuItemView, MenuView } from "../types/order";

type MenuPanelProps = {
  onPickItem: (text: string) => void;
};

export function MenuPanel({ onPickItem }: MenuPanelProps) {
  const [menu, setMenu] = useState<MenuView>({ categories: [], items: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const mountedRef = useRef(false);

  async function loadMenu() {
    setLoading(true);
    setError(false);
    try {
      const result = await getMenu();
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
  }, []);

  return (
    <section className="panel menu-panel" aria-labelledby="menu-panel-title">
      <div className="panel-heading">
        <div>
          <h2 id="menu-panel-title">菜单</h2>
          <p>点击菜品只会填入输入框</p>
        </div>
        {loading ? <span className="status-pill">加载中</span> : null}
      </div>

      {error ? (
        <div className="notice" role="status">
          <p>菜单暂时加载失败，可继续用文字点餐。</p>
          <button type="button" className="secondary" onClick={() => void loadMenu()}>
            重试
          </button>
        </div>
      ) : null}

      {!loading && !error && menu.items.length === 0 ? <p className="empty-state">菜单暂时为空。</p> : null}

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
                    onClick={() => item.name && onPickItem(`我要一份${item.name}`)}
                    disabled={!item.name}
                    aria-label={item.name ? `填入我要一份${item.name}` : "菜品名称待确认"}
                  >
                    <MenuItemContent item={item} />
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

function MenuItemContent({ item }: { item: MenuItemView }) {
  const tags = item.tags.slice(0, 3);
  const options = item.options.slice(0, 3);
  const isRecommended = item.recommendedScore !== null && item.recommendedScore >= 8.5;

  return (
    <>
      <span className="menu-item-head">
        <strong>{item.name ?? "菜品名称待确认"}</strong>
        {isRecommended ? <em>推荐</em> : null}
      </span>
      <span className="menu-price">{formatPrice(item.price)}</span>
      {item.description ? <span className="menu-description">{item.description}</span> : null}
      {tags.length > 0 ? <span className="menu-tags">{tags.join(" · ")}</span> : null}
      {options.length > 0 ? <span className="menu-options">可选：{options.join("、")}</span> : null}
    </>
  );
}
