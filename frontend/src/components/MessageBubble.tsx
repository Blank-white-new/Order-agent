type Props = {
  role: "user" | "agent";
  text: string;
  trace?: Record<string, unknown>;
};

export function MessageBubble({ role, text, trace }: Props) {
  return (
    <article className={`message ${role}`}>
      <p>{text}</p>
      {trace ? (
        <details>
          <summary>trace</summary>
          <pre>{JSON.stringify(trace, null, 2)}</pre>
        </details>
      ) : null}
    </article>
  );
}

