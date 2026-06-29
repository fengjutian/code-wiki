import type {
  ChatModelAdapter,
  ChatModelRunOptions,
  ChatModelRunResult,
  TextMessagePart,
} from "@assistant-ui/react";

/**
 * Custom ChatModelAdapter that connects to our backend SSE chat endpoint.
 *
 * IMPORTANT: The runtime calls updateMessage() for each yield, but it uses a
 * captured initialContent (always [] for a new message). Each yield's content
 * REPLACES the previous one — so we MUST accumulate text locally and yield
 * the FULL accumulated text on every chunk, not just the new delta.
 */
export class SSEChatModelAdapter implements ChatModelAdapter {
  async *run({
    messages,
    abortSignal,
  }: ChatModelRunOptions): AsyncGenerator<ChatModelRunResult, void> {
    // Find the last user message
    const lastUserMsg = [...messages].reverse().find((m) => m.role === "user");
    if (!lastUserMsg) {
      yield {
        content: [
          { type: "text", text: "No user message found" } satisfies TextMessagePart,
        ],
      };
      return;
    }

    // Extract plain text from assistant-ui message parts
    const getMessageText = (
      msg: { role: string; content: readonly { type: string; text?: string }[] }
    ): string => {
      return msg.content
        .filter((p): p is { type: "text"; text: string } => p.type === "text")
        .map((p) => p.text)
        .join("\n\n");
    };

    const question = getMessageText(lastUserMsg);
    const history = messages
      .filter((m) => m !== lastUserMsg)
      .map((m) => ({
        role: m.role,
        content: getMessageText(m),
      }));

    // POST to backend
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, history }),
      signal: abortSignal,
    });

    if (!response.ok) {
      let errorDetail = "Request failed (" + response.status + ")";
      try {
        const errBody = await response.json();
        if (errBody.detail) errorDetail = errBody.detail;
      } catch {
        // ignore
      }
      yield {
        content: [
          { type: "text", text: "Error: " + errorDetail } satisfies TextMessagePart,
        ],
      };
      return;
    }

    if (!response.body) {
      yield {
        content: [
          { type: "text", text: "No streaming response from server" } satisfies TextMessagePart,
        ],
      };
      return;
    }

    // ---- SSE stream reader ----
    // Accumulate text locally. Each yield sends the FULL text so far,
    // because the runtime's updateMessage uses a captured initialContent.
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let accumulated = "";

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            const chunk = line.slice(6).trimEnd();
            if (chunk === "[DONE]") {
              // Yield one final time with complete text
              yield {
                content: [
                  { type: "text", text: accumulated } satisfies TextMessagePart,
                ],
              };
              return;
            }
            if (chunk === "") continue;

            accumulated += chunk;

            yield {
              content: [
                { type: "text", text: accumulated } satisfies TextMessagePart,
              ],
            };
          }
        }
      }

      // Final buffer flush
      if (buffer.startsWith("data: ")) {
        const chunk = buffer.slice(6).trimEnd();
        if (chunk !== "[DONE]" && chunk !== "") {
          accumulated += chunk;
          yield {
            content: [
              { type: "text", text: accumulated } satisfies TextMessagePart,
            ],
          };
        }
      }

      // If we reached here without hitting [DONE], yield final accumulated text
      if (accumulated) {
        yield {
          content: [
            { type: "text", text: accumulated } satisfies TextMessagePart,
          ],
        };
      }
    } finally {
      reader.releaseLock();
    }
  }
}
