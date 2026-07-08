type Props = {
  role: "user" | "agent";
  text: string;
  trace?: Record<string, unknown>;
  tone?: "normal" | "error" | "system";
};

export function MessageBubble({ role, text, trace, tone = "normal" }: Props) {
  return (
    <article className={`message ${role} ${tone}`} role={tone === "error" ? "alert" : undefined}>
      <p>{text}</p>
      {trace ? (
        <details>
          <summary>调试信息（默认折叠）</summary>
          <pre>{JSON.stringify(redactTraceForDisplay(trace), null, 2)}</pre>
        </details>
      ) : null}
    </article>
  );
}

function redactTraceForDisplay(value: unknown, key = ""): unknown {
  const normalizedKey = key.toLowerCase();
  if (
    normalizedKey === "usermessage" ||
    normalizedKey.includes("address") ||
    normalizedKey.includes("phone") ||
    normalizedKey.includes("pendingcandidate")
  ) {
    return value ? "[已隐藏]" : value;
  }
  if (typeof value === "string") {
    return value.replace(/(?<!\d)1[3-9]\d{9}(?!\d)/g, (phone) => `${phone.slice(0, 3)}****${phone.slice(-4)}`);
  }
  if (Array.isArray(value)) {
    return value.map((item) => redactTraceForDisplay(item));
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([childKey, item]) => [
        childKey,
        redactTraceForDisplay(item, childKey),
      ]),
    );
  }
  return value;
}

