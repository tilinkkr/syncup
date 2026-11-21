/**
 * Agora ConvoAI agent → client message protocol (mirrors agora-agent-client-toolkit v2.9 types).
 * Primary transport: RTM channel messages (parameters.data_channel = "rtm").
 * Fallback: RTC `stream-message`, which may arrive chunked as `message_id|part_idx|part_sum|base64`.
 */

export type AgentEvent =
  | { kind: "user_transcript"; turnId: number; text: string; final: boolean }
  | { kind: "agent_transcript"; turnId: number; text: string; status: "in_progress" | "end" | "interrupted" }
  | { kind: "interrupt"; turnId: number }
  | { kind: "metric"; module: string; name: string; latencyMs: number }
  | { kind: "turn_finished"; turnId?: number; e2eMs?: number }
  | { kind: "state"; state: string }
  | { kind: "error"; module: string; code: number; message: string };

const TURN_STATUS = ["in_progress", "end", "interrupted"] as const;

export function parseAgentMessage(raw: unknown): AgentEvent | null {
  if (!raw || typeof raw !== "object") return null;
  const m = raw as Record<string, any>;
  const object = m.object ?? m.event_type;
  switch (object) {
    case "user.transcription":
      return { kind: "user_transcript", turnId: Number(m.turn_id ?? 0), text: String(m.text ?? ""), final: !!m.final };
    case "assistant.transcription":
      return {
        kind: "agent_transcript",
        turnId: Number(m.turn_id ?? 0),
        text: String(m.text ?? ""),
        status: TURN_STATUS[Number(m.turn_status ?? 0)] ?? "in_progress",
      };
    case "message.interrupt":
      return { kind: "interrupt", turnId: Number(m.turn_id ?? 0) };
    case "message.metrics":
      return { kind: "metric", module: String(m.module), name: String(m.metric_name ?? ""), latencyMs: Number(m.latency_ms) };
    case "turn.finished":
      return { kind: "turn_finished", turnId: m.payload?.turn_id, e2eMs: m.payload?.metrics?.e2e_latency_ms };
    case "message.state":
      return { kind: "state", state: String(m.state ?? "") };
    case "message.error":
      return { kind: "error", module: String(m.module ?? ""), code: Number(m.code ?? 0), message: String(m.message ?? "") };
    default:
      return null;
  }
}

export function decodePayload(data: unknown): unknown | null {
  try {
    if (typeof data === "string") return JSON.parse(data);
    if (data instanceof Uint8Array) return JSON.parse(new TextDecoder().decode(data));
  } catch {
    /* not JSON */
  }
  return null;
}

/** Reassembles chunked RTC data-stream messages; evicts incomplete messages after 30 s. */
export class ChunkAssembler {
  private parts = new Map<string, { sum: number; got: Map<number, string>; t: number }>();

  push(text: string): unknown | null {
    const now = Date.now();
    this.parts.forEach((v, k) => {
      if (now - v.t > 30_000) this.parts.delete(k);
    });
    const seg = text.split("|");
    if (seg.length !== 4) return decodePayload(text);
    const [id, idxStr, sumStr, b64] = seg;
    const idx = parseInt(idxStr, 10);
    const sum = sumStr === "???" ? -1 : parseInt(sumStr, 10);
    if (Number.isNaN(idx)) return null;
    const entry = this.parts.get(id) ?? { sum, got: new Map<number, string>(), t: now };
    entry.got.set(idx, b64);
    if (sum > 0) entry.sum = sum;
    this.parts.set(id, entry);
    if (entry.sum <= 0 || entry.got.size < entry.sum) return null;
    this.parts.delete(id);
    const joined = Array.from(entry.got.entries())
      .sort((a, b) => a[0] - b[0])
      .map(([, v]) => v)
      .join("");
    try {
      const bin = atob(joined);
      const bytes = Uint8Array.from(bin, (c) => c.charCodeAt(0));
      return JSON.parse(new TextDecoder().decode(bytes));
    } catch {
      return null;
    }
  }
}
