export type ConcreteLocale = "zh-CN" | "yue-Hant-HK" | "en-HK";
export type LocalePreference = "auto" | ConcreteLocale;

type UiStrings = {
  appTitle: string;
  appSubtitle: string;
  newOrder: string;
  autoDetect: string;
  language: string;
  responseLanguage: string;
  detectedLanguage: string;
  languageConfidence: string;
  mixed: string;
  send: string;
  sending: string;
  inputLabel: string;
  placeholder: string;
  offlineError: string;
  resetWelcome: string;
  languageChanged: string;
  clarification: string;
  textOnly: string;
  debug: string;
  supportPanel: string;
};

const STRINGS: Record<ConcreteLocale, UiStrings> = {
  "zh-CN": {
    appTitle: "订餐助手",
    appSubtitle: "阶段 4 仅处理合成多语言文本，不连接真实餐厅或真人",
    newOrder: "新订单",
    autoDetect: "自动检测",
    language: "回复语言",
    responseLanguage: "当前回复语言",
    detectedLanguage: "检测到的输入",
    languageConfidence: "语言检测置信度",
    mixed: "混合语言输入",
    send: "发送",
    sending: "发送中",
    inputLabel: "输入点餐消息",
    placeholder: "输入：我要两份鸡腿饭，少辣",
    offlineError: "后端暂时没连上，请稍后再试。",
    resetWelcome: "会话已重置，想吃点什么？",
    languageChanged: "语言选项已更新；当前订单不会被清空。",
    clarification: "需要澄清",
    textOnly: "多语言能力仅限文字；不代表语音或电话能力。",
    debug: "调试信息（默认折叠）",
    supportPanel: "订单辅助信息",
  },
  "yue-Hant-HK": {
    appTitle: "落單助手",
    appSubtitle: "階段 4 只處理合成多語文字，唔會連接真實餐廳或者真人",
    newOrder: "新訂單",
    autoDetect: "自動偵測",
    language: "回覆語言",
    responseLanguage: "目前回覆語言",
    detectedLanguage: "偵測到嘅輸入",
    languageConfidence: "語言偵測置信度",
    mixed: "混合語言輸入",
    send: "傳送",
    sending: "傳送中",
    inputLabel: "輸入落單訊息",
    placeholder: "輸入：我要兩份雞髀飯，少辣",
    offlineError: "暫時連唔到後端，請稍後再試。",
    resetWelcome: "對話已重設，想食啲咩？",
    languageChanged: "語言選項已更新；目前張單唔會被清空。",
    clarification: "需要講清楚",
    textOnly: "多語能力只限文字；唔代表語音或者電話能力。",
    debug: "除錯資料（預設收起）",
    supportPanel: "訂單輔助資料",
  },
  "en-HK": {
    appTitle: "Ordering assistant",
    appSubtitle: "Phase 4 handles synthetic multilingual text only; no real restaurant or person is connected",
    newOrder: "New order",
    autoDetect: "Auto-detect",
    language: "Reply language",
    responseLanguage: "Current reply language",
    detectedLanguage: "Detected input",
    languageConfidence: "Language-detection confidence",
    mixed: "Mixed-language input",
    send: "Send",
    sending: "Sending",
    inputLabel: "Enter an ordering message",
    placeholder: "Type: I want two portions of chicken leg rice, less spicy",
    offlineError: "The backend is temporarily unavailable. Please try again later.",
    resetWelcome: "The session has been reset. What would you like?",
    languageChanged: "The language option is updated. The current order has not been cleared.",
    clarification: "Clarification required",
    textOnly: "Multilingual support is text-only and does not represent voice or telephone capability.",
    debug: "Debug information (collapsed by default)",
    supportPanel: "Order supporting information",
  },
};

export function ui(locale: ConcreteLocale): UiStrings {
  return STRINGS[locale];
}

export function localeLabel(locale: string, displayLocale: ConcreteLocale): string {
  const labels: Record<ConcreteLocale, Record<string, string>> = {
    "zh-CN": { "zh-CN": "普通话", "yue-Hant-HK": "粤语", "en-HK": "English", mixed: "混合语言" },
    "yue-Hant-HK": { "zh-CN": "普通話", "yue-Hant-HK": "廣東話", "en-HK": "English", mixed: "混合語言" },
    "en-HK": { "zh-CN": "Mandarin", "yue-Hant-HK": "Cantonese", "en-HK": "English", mixed: "Mixed" },
  };
  return labels[displayLocale][locale] ?? locale;
}
