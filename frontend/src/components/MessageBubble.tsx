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
          <summary>调试信息</summary>
          <pre>{JSON.stringify(trace, null, 2)}</pre>
        </details>
      ) : null}
    </article>
  );
}

