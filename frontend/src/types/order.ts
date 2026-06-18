export type OrderItemView = {
  key: string;
  name: string;
  price: number | null;
  quantity: number;
  options: string[];
  notes: string | null;
  category: string | null;
  unit: string | null;
};

export type OrderStateView = {
  currentOrder: OrderItemView[];
  fulfillmentType: string | null;
  officialDeliveryAddress: string | null;
  pendingDeliveryAddress: string | null;
  phone: string | null;
  stage: string | null;
  submitted: boolean;
  submittedOrderId: string | null;
};

export type MenuItemView = {
  id: string;
  name: string | null;
  category: string;
  price: number | null;
  tags: string[];
  options: string[];
  recommendedScore: number | null;
  recommendReason: string | null;
  description: string | null;
};

export type MenuView = {
  categories: string[];
  items: MenuItemView[];
};

export function normalizeOrderState(raw: unknown): OrderStateView {
  const state = isRecord(raw) ? raw : {};
  const rawOrder = Array.isArray(state.current_order) ? state.current_order : [];
  return {
    currentOrder: rawOrder.map(normalizeOrderItem),
    fulfillmentType: optionalString(state.fulfillment_type),
    officialDeliveryAddress: optionalString(state.official_delivery_address),
    pendingDeliveryAddress: pendingAddressLabel(state.pending_delivery_address_candidate),
    phone: optionalString(state.phone),
    stage: optionalString(state.stage),
    submitted: state.submitted === true,
    submittedOrderId: optionalString(state.submitted_order_id),
  };
}

export function normalizeMenuResponse(raw: unknown): MenuView {
  const response = isRecord(raw) ? raw : {};
  const rawItems = Array.isArray(response.items) ? response.items : [];
  const rawCategories = Array.isArray(response.categories) ? response.categories : [];
  const items = rawItems.map(normalizeMenuItem);
  const categories = uniqueStrings([
    ...rawCategories.map(optionalString).filter((value): value is string => Boolean(value)),
    ...items.map((item) => item.category),
  ]);

  return { categories, items };
}

export function orderLineSubtotal(item: OrderItemView): number | null {
  if (item.price === null) {
    return null;
  }
  return item.price * item.quantity;
}

export function knownOrderTotal(items: OrderItemView[]): number {
  return items.reduce((total, item) => total + (orderLineSubtotal(item) ?? 0), 0);
}

export function hasUnknownOrderPrice(items: OrderItemView[]): boolean {
  return items.some((item) => item.price === null);
}

export function formatPrice(value: number | null): string {
  if (value === null) {
    return "价格待确认";
  }
  return `${formatNumber(value)} 元`;
}

function normalizeOrderItem(raw: unknown, index: number): OrderItemView {
  const item = isRecord(raw) ? raw : {};
  const rawName = optionalString(item.name);
  return {
    key: optionalString(item.item_id) ?? rawName ?? `order-item-${index}`,
    name: rawName ?? "菜品待确认",
    price: finiteNumber(item.price),
    quantity: positiveQuantity(item.quantity),
    options: stringList(item.options),
    notes: optionalString(item.notes),
    category: optionalString(item.category),
    unit: optionalString(item.unit),
  };
}

function normalizeMenuItem(raw: unknown, index: number): MenuItemView {
  const item = isRecord(raw) ? raw : {};
  return {
    id: optionalString(item.id) ?? `menu-item-${index}`,
    name: optionalString(item.name),
    category: optionalString(item.category) ?? "未分类",
    price: finiteNumber(item.price),
    tags: stringList(item.tags),
    options: stringList(item.options),
    recommendedScore: finiteNumber(item.recommended_score),
    recommendReason: optionalString(item.recommend_reason),
    description: optionalString(item.description),
  };
}

function pendingAddressLabel(raw: unknown): string | null {
  if (!isRecord(raw)) {
    return null;
  }
  return optionalString(raw.normalized) ?? optionalString(raw.raw);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function optionalString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function finiteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function positiveQuantity(value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return 1;
  }
  return Math.max(1, Math.floor(value));
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.map(optionalString).filter((entry): entry is string => Boolean(entry));
}

function uniqueStrings(values: string[]): string[] {
  return Array.from(new Set(values));
}

function formatNumber(value: number): string {
  if (Number.isInteger(value)) {
    return String(value);
  }
  return value.toFixed(2).replace(/\.?0+$/, "");
}
