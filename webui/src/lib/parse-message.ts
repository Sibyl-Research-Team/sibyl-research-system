import type { ChatMessage, ContentBlock, JsonValue } from "./types";

function normalizeRole(rawRole: string | undefined, rawType: string | undefined): "user" | "assistant" | "system" {
  if (rawRole === "user" || rawType === "user") return "user";
  if (rawRole === "assistant" || rawType === "assistant") return "assistant";
  return "system";
}

function stringifyContent(value: JsonValue | undefined): string {
  if (typeof value === "string") return value;
  if (value === null || value === undefined) return "";
  return JSON.stringify(value, null, 2);
}

function parseBlocks(content: unknown): ContentBlock[] {
  if (!Array.isArray(content)) {
    return [];
  }
  return content.flatMap((block): ContentBlock[] => {
    if (!block || typeof block !== "object") return [];
    const item = block as Record<string, JsonValue>;
    const type = item.type;
    if (type === "text" && typeof item.text === "string") {
      return [{ type: "text", text: item.text }];
    }
    if (type === "thinking" && typeof item.text === "string") {
      return [{ type: "thinking", text: item.text }];
    }
    if (type === "tool_use") {
      return [
        {
          type: "tool_use",
          id: typeof item.id === "string" ? item.id : "",
          name: typeof item.name === "string" ? item.name : "Tool",
          input:
            item.input && typeof item.input === "object" && !Array.isArray(item.input)
              ? (item.input as Record<string, JsonValue>)
              : {},
        },
      ];
    }
    if (type === "tool_result") {
      return [
        {
          type: "tool_result",
          tool_use_id: typeof item.tool_use_id === "string" ? item.tool_use_id : "",
          content: stringifyContent(item.content),
          is_error: item.is_error === true,
        },
      ];
    }
    return [
      {
        type: "json",
        label: typeof type === "string" ? type : "block",
        value: item,
      },
    ];
  });
}

export function parseConversationEntry(entry: unknown): ChatMessage | null {
  if (!entry || typeof entry !== "object") return null;
  const payload = entry as Record<string, JsonValue>;
  const message = payload.message && typeof payload.message === "object" ? payload.message as Record<string, JsonValue> : {};
  const blocks = parseBlocks(message.content);
  if (blocks.length === 0) {
    return null;
  }
  const usageRaw =
    message.usage && typeof message.usage === "object" ? (message.usage as Record<string, JsonValue>) : null;

  return {
    id:
      (typeof payload.uuid === "string" && payload.uuid) ||
      (typeof payload.timestamp === "string" && payload.timestamp) ||
      crypto.randomUUID(),
    role: normalizeRole(
      typeof message.role === "string" ? message.role : undefined,
      typeof payload.type === "string" ? payload.type : undefined,
    ),
    blocks,
    model: typeof message.model === "string" ? message.model : undefined,
    usage: usageRaw
      ? {
          input_tokens: Number(usageRaw.input_tokens || 0),
          output_tokens: Number(usageRaw.output_tokens || 0),
        }
      : undefined,
    timestamp: typeof payload.timestamp === "string" ? payload.timestamp : undefined,
  };
}
