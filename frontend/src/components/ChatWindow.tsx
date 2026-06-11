import { FormEvent, useState } from "react";
import { resetSession, sendChatMessage } from "../api/chatApi";
import { postVoiceTts } from "../api/voiceApi";
import { createAndStoreSessionId, getOrCreateSessionId } from "../utils/session";
import { MessageBubble } from "./MessageBubble";
import { VoiceControls } from "./VoiceControls";

type Message = {
  id: string;
  role: "user" | "agent";
  text: string;
  trace?: Record<string, unknown>;
};

type TtsPreference = {
  enabled: boolean;
  canSpeak: boolean;
};

export function ChatWindow() {
  const [sessionId, setSessionId] = useState(() => getOrCreateSessionId());
  const [messages, setMessages] = useState<Message[]>([
    { id: "welcome", role: "agent", text: "你好，想看菜单、点餐，还是问配送？" },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [ttsPreference, setTtsPreference] = useState<TtsPreference>({ enabled: false, canSpeak: false });

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
      setMessages((current) => [
        ...current,
        { id: crypto.randomUUID(), role: "agent", text: result.response, trace: result.trace },
      ]);
      void queueTextReplyTts(result.response);
    } catch {
      setMessages((current) => [
        ...current,
        { id: crypto.randomUUID(), role: "agent", text: "后端暂时没连上，请稍后再试。" },
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
    setMessages([{ id: "welcome", role: "agent", text: "会话已重置，想吃点什么？" }]);
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
    <section className="chat-window">
      <header>
        <h1>多 Agent 订餐</h1>
        <button type="button" onClick={onReset}>
          重置
        </button>
      </header>
      <div className="messages">
        {messages.map((message) => (
          <MessageBubble key={message.id} {...message} />
        ))}
      </div>
      <VoiceControls
        sessionId={sessionId}
        onUserFinal={appendVoiceUserMessage}
        onAgentReply={appendVoiceAgentReply}
        onTtsPreferenceChange={setTtsPreference}
      />
      <form onSubmit={onSubmit}>
        <input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="输入：有啥、鸡腿饭不辣、中山大学南校园要送多久？"
        />
        <button type="submit" disabled={loading}>
          发送
        </button>
      </form>
    </section>
  );
}
