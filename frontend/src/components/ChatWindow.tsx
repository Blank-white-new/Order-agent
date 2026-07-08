import { FormEvent, useEffect, useRef, useState } from "react";
import { resetSession, sendChatMessage } from "../api/chatApi";
import { postVoiceTts } from "../api/voiceApi";
import { normalizeOrderState, OrderStateView } from "../types/order";
import { createAndStoreSessionId, getOrCreateSessionId } from "../utils/session";
import { MenuPanel } from "./MenuPanel";
import { MessageBubble } from "./MessageBubble";
import { NextStepHint } from "./NextStepHint";
import { OrderSummary } from "./OrderSummary";
import { VoiceControls } from "./VoiceControls";

type Message = {
  id: string;
  role: "user" | "agent";
  text: string;
  trace?: Record<string, unknown>;
  tone?: "normal" | "error" | "system";
};

type TtsPreference = {
  enabled: boolean;
  canSpeak: boolean;
};

export function ChatWindow() {
  const [sessionId, setSessionId] = useState(() => getOrCreateSessionId());
  const [messages, setMessages] = useState<Message[]>([
    { id: "welcome", role: "agent", text: "你好！可以说“推荐一下”，或直接告诉我想吃什么。", tone: "system" },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [orderState, setOrderState] = useState<OrderStateView>(() => normalizeOrderState(null));
  const [ttsPreference, setTtsPreference] = useState<TtsPreference>({ enabled: false, canSpeak: false });
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView?.({ block: "end" });
  }, [messages, loading]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const text = input.trim();
    if (!text || loading) {
      return;
    }
    setInput("");
    setLoading(true);
    setMessages((current) => [...current, { id: crypto.randomUUID(), role: "user", text }]);
    try {
      const result = await sendChatMessage(sessionId, text);
      setOrderState(result.state);
      setMessages((current) => [
        ...current,
        { id: crypto.randomUUID(), role: "agent", text: result.response, trace: result.trace },
      ]);
      void queueTextReplyTts(result.response);
    } catch (err) {
      console.warn("Text chat request failed.", err);
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "agent",
          text: "后端暂时没连上，请稍后再试。详情请查看浏览器控制台。",
          tone: "error",
        },
      ]);
    } finally {
      setLoading(false);
    }
  }

  async function onReset() {
    const previousSessionId = sessionId;
    const nextSessionId = createAndStoreSessionId();
    setSessionId(nextSessionId);
    setInput("");
    setLoading(false);
    setOrderState(normalizeOrderState(null));
    setMessages([{ id: "welcome", role: "agent", text: "会话已重置，想吃点什么？", tone: "system" }]);
    try {
      await resetSession(previousSessionId);
    } catch (err) {
      console.warn("Failed to reset previous order session.", err);
    }
  }

  function appendVoiceUserMessage(text: string) {
    setMessages((current) => [...current, { id: crypto.randomUUID(), role: "user", text }]);
  }

  function appendVoiceAgentReply(text: string, trace: Record<string, unknown>) {
    setMessages((current) => [...current, { id: crypto.randomUUID(), role: "agent", text, trace }]);
  }

  function fillInputFromMenu(text: string) {
    setInput(text);
    inputRef.current?.focus();
  }

  async function queueTextReplyTts(text: string) {
    if (!ttsPreference.enabled || !ttsPreference.canSpeak || !text.trim()) {
      return;
    }
    try {
      const result = await postVoiceTts(text, sessionId);
      if (!result.queued) {
        console.warn(`Text reply TTS was not queued: ${result.error ?? "unknown_error"}`);
      }
    } catch (err) {
      console.warn("Text reply TTS request failed.", err);
    }
  }

  return (
    <section className="ordering-workspace">
      <section className="chat-window" aria-label="当前对话">
        <header>
          <div>
            <h1>订餐助手</h1>
            <p>文字与语音共用订单状态；提交的是安全的 mock order</p>
          </div>
          <button type="button" className="secondary" onClick={onReset}>
            新订单
          </button>
        </header>
        <div className="messages" aria-live="polite">
          {messages.map((message) => (
            <MessageBubble key={message.id} {...message} />
          ))}
          {loading ? <p className="sending-indicator">正在发送...</p> : null}
          <div ref={messagesEndRef} />
        </div>
        <VoiceControls
          sessionId={sessionId}
          onUserFinal={appendVoiceUserMessage}
          onAgentReply={appendVoiceAgentReply}
          onOrderStateChange={setOrderState}
          onTtsPreferenceChange={setTtsPreference}
        />
        <form onSubmit={onSubmit} className="composer">
          <label className="sr-only" htmlFor="chat-input">
            输入点餐消息
          </label>
          <input
            id="chat-input"
            ref={inputRef}
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="输入：招牌菜是啥、黑椒牛肉饭不辣、配送到中山大学南校园"
          />
          <button type="submit" disabled={loading || !input.trim()}>
            {loading ? "发送中" : "发送"}
          </button>
        </form>
      </section>
      <aside className="support-panel" aria-label="订单辅助信息">
        <NextStepHint state={orderState} />
        <OrderSummary state={orderState} />
        <MenuPanel onPickItem={fillInputFromMenu} />
      </aside>
    </section>
  );
}
