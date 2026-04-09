export type Chat = {
  id: number;
  title: string;
  total_tokens: number;
};

export type Branch = {
  id: number;
  title: string;
  parent_branch_id: number | null;
  fork_after_message_id: number | null;
  system_prompt: string;
  temperature: number;
  max_tokens: number;
  timeout_sec: number;
  total_tokens: number;
  memory_strategy: string;
  strategy_params_json: string;
};

export type Message = {
  id: number;
  role: string;
  content: string;
  summarized: boolean;
};

export type SendMessageResponse = {
  assistant_text: string;
  model: string;
  tokens_this_turn: number | null;
  total_tokens_branch: number;
  total_tokens_chat: number;
  elapsed_sec: number;
};

export type WeatherPopup = {
  city: string;
  temperature_c: number;
  wind_speed_kmh: number;
  weather_code: number;
  time_local: string;
  source: string;
};

export type MCPPipelineResult = {
  ok: boolean;
  query: string;
  search_raw: string;
  summarize_raw: string;
  save_raw: string;
};

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  return res.json() as Promise<T>;
}

export async function fetchChats(): Promise<Chat[]> {
  return json(await fetch("/api/chats"));
}

export async function fetchIrkutskWeather(): Promise<WeatherPopup> {
  return json(await fetch("/api/weather/irkutsk"));
}

export async function runMcpEduPipeline(body: {
  query: string;
  limit?: number;
  max_chars?: number;
  max_points?: number;
  output_file?: string;
  overwrite?: boolean;
}): Promise<MCPPipelineResult> {
  return json(
    await fetch("/api/mcp/edu-pipeline", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
}

export async function createChat(title?: string): Promise<Chat> {
  return json(
    await fetch("/api/chats", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: title ?? null }),
    }),
  );
}

export async function fetchBranches(chatId: number): Promise<Branch[]> {
  return json(await fetch(`/api/chats/${chatId}/branches`));
}

export async function fetchMessages(
  chatId: number,
  branchId: number,
): Promise<Message[]> {
  return json(
    await fetch(`/api/chats/${chatId}/branches/${branchId}/messages`),
  );
}

export async function sendMessage(
  chatId: number,
  branchId: number,
  content: string,
): Promise<SendMessageResponse> {
  return json(
    await fetch(`/api/chats/${chatId}/branches/${branchId}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    }),
  );
}

export type StreamEvent =
  | { type: "delta"; delta: string }
  | { type: "done"; payload: SendMessageResponse }
  | { type: "status"; phase: string; message: string }
  | { type: "stopped"; stopped: boolean }
  | { type: "error"; message: string };

export async function sendMessageStream(
  chatId: number,
  branchId: number,
  content: string,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`/api/chats/${chatId}/branches/${branchId}/messages/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
    signal,
  });
  if (!res.ok || !res.body) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";

    for (const block of blocks) {
      const lines = block.split("\n");
      let eventName = "";
      let dataRaw = "";
      for (const line of lines) {
        if (line.startsWith("event:")) eventName = line.slice(6).trim();
        if (line.startsWith("data:")) dataRaw += line.slice(5).trim();
      }
      if (!eventName || !dataRaw) continue;
      let data: unknown = null;
      try {
        data = JSON.parse(dataRaw);
      } catch {
        continue;
      }
      if (eventName === "delta" && typeof (data as { delta?: unknown }).delta === "string") {
        onEvent({ type: "delta", delta: (data as { delta: string }).delta });
      } else if (eventName === "status") {
        const d = data as { phase?: unknown; message?: unknown };
        onEvent({
          type: "status",
          phase: typeof d.phase === "string" ? d.phase : "",
          message: typeof d.message === "string" ? d.message : "",
        });
      } else if (eventName === "done") {
        onEvent({ type: "done", payload: data as SendMessageResponse });
      } else if (eventName === "stopped") {
        onEvent({ type: "stopped", stopped: Boolean((data as { stopped?: unknown }).stopped) });
      } else if (eventName === "error") {
        onEvent({
          type: "error",
          message:
            typeof (data as { message?: unknown }).message === "string"
              ? (data as { message: string }).message
              : "stream error",
        });
      }
    }
  }
}

export async function resumeMessageStream(
  chatId: number,
  branchId: number,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`/api/chats/${chatId}/branches/${branchId}/messages/resume-stream`, {
    method: "POST",
    signal,
  });
  if (!res.ok || !res.body) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";
    for (const block of blocks) {
      const lines = block.split("\n");
      let eventName = "";
      let dataRaw = "";
      for (const line of lines) {
        if (line.startsWith("event:")) eventName = line.slice(6).trim();
        if (line.startsWith("data:")) dataRaw += line.slice(5).trim();
      }
      if (!eventName || !dataRaw) continue;
      let data: unknown = null;
      try {
        data = JSON.parse(dataRaw);
      } catch {
        continue;
      }
      if (eventName === "delta" && typeof (data as { delta?: unknown }).delta === "string") {
        onEvent({ type: "delta", delta: (data as { delta: string }).delta });
      } else if (eventName === "status") {
        const d = data as { phase?: unknown; message?: unknown };
        onEvent({
          type: "status",
          phase: typeof d.phase === "string" ? d.phase : "",
          message: typeof d.message === "string" ? d.message : "",
        });
      } else if (eventName === "done") {
        onEvent({ type: "done", payload: data as SendMessageResponse });
      } else if (eventName === "stopped") {
        onEvent({ type: "stopped", stopped: Boolean((data as { stopped?: unknown }).stopped) });
      } else if (eventName === "error") {
        onEvent({
          type: "error",
          message:
            typeof (data as { message?: unknown }).message === "string"
              ? (data as { message: string }).message
              : "stream error",
        });
      }
    }
  }
}

export async function stopMessageStream(
  chatId: number,
  branchId: number,
): Promise<{ ok: boolean; found: boolean }> {
  return json(
    await fetch(`/api/chats/${chatId}/branches/${branchId}/messages/stop`, {
      method: "POST",
    }),
  );
}

export async function stopAndPauseMessageStream(
  chatId: number,
  branchId: number,
  reason?: string,
): Promise<TaskFSM> {
  return json(
    await fetch(`/api/chats/${chatId}/branches/${branchId}/messages/stop-and-pause`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: reason ?? "Остановлено пользователем во время генерации" }),
    }),
  );
}

export async function forkBranch(
  chatId: number,
  parentBranchId: number,
  body: {
    fork_after_message_id: number;
    title: string;
    system_prompt?: string | null;
    temperature?: number | null;
    max_tokens?: number | null;
    timeout_sec?: number | null;
  },
): Promise<Branch> {
  return json(
    await fetch(
      `/api/chats/${chatId}/branches/${parentBranchId}/fork`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    ),
  );
}

export async function fetchBranchFacts(
  chatId: number,
  branchId: number,
): Promise<Record<string, string>> {
  return json(
    await fetch(`/api/chats/${chatId}/branches/${branchId}/facts`),
  );
}

export type MemoryItem = {
  key: string;
  value: string;
  updated_at: string;
};

export type Invariant = {
  id: number;
  user_id: string;
  category: string;
  severity: string;
  title: string;
  statement: string;
  active: boolean;
  updated_at: string;
};

export async function fetchInvariants(userId: string): Promise<Invariant[]> {
  return json(
    await fetch(`/api/users/${encodeURIComponent(userId)}/invariants`),
  );
}

export async function createInvariant(
  userId: string,
  body: {
    category: string;
    severity: string;
    title: string;
    statement: string;
  },
): Promise<Invariant> {
  return json(
    await fetch(`/api/users/${encodeURIComponent(userId)}/invariants`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
}

export async function patchInvariant(
  userId: string,
  invariantId: number,
  body: {
    category?: string | null;
    severity?: string | null;
    title?: string | null;
    statement?: string | null;
    active?: boolean | null;
  },
): Promise<Invariant> {
  return json(
    await fetch(
      `/api/users/${encodeURIComponent(userId)}/invariants/${invariantId}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    ),
  );
}

export async function deleteInvariant(
  userId: string,
  invariantId: number,
): Promise<{ deleted: boolean }> {
  return json(
    await fetch(
      `/api/users/${encodeURIComponent(userId)}/invariants/${invariantId}`,
      { method: "DELETE" },
    ),
  );
}

export type MemoryProfile = {
  id: string;
  title: string;
  description: string;
  user_id: string;
};

export type TaskFSM = {
  stage: string;
  current_step: string;
  expected_action: string;
  previous_stage?: string | null;
  pause_reason?: string | null;
};

export async function fetchMemoryProfiles(): Promise<MemoryProfile[]> {
  return json(await fetch("/api/memory-profiles"));
}

export async function fetchTaskFsm(
  chatId: number,
  branchId: number,
): Promise<TaskFSM> {
  return json(
    await fetch(`/api/chats/${chatId}/branches/${branchId}/task-fsm`),
  );
}

export async function pauseTaskFsm(
  chatId: number,
  branchId: number,
  reason?: string,
): Promise<TaskFSM> {
  return json(
    await fetch(`/api/chats/${chatId}/branches/${branchId}/task-fsm/pause`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: reason ?? null }),
    }),
  );
}

export async function resumeTaskFsm(
  chatId: number,
  branchId: number,
): Promise<TaskFSM> {
  return json(
    await fetch(`/api/chats/${chatId}/branches/${branchId}/task-fsm/resume`, {
      method: "POST",
    }),
  );
}

export async function fetchWorkingMemory(
  chatId: number,
  branchId: number,
): Promise<MemoryItem[]> {
  return json(
    await fetch(`/api/chats/${chatId}/branches/${branchId}/working-memory`),
  );
}

export async function putWorkingMemoryItem(
  chatId: number,
  branchId: number,
  key: string,
  value: string,
): Promise<MemoryItem> {
  return json(
    await fetch(
      `/api/chats/${chatId}/branches/${branchId}/working-memory/${encodeURIComponent(key)}`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value }),
      },
    ),
  );
}

export async function deleteWorkingMemoryItem(
  chatId: number,
  branchId: number,
  key: string,
): Promise<{ deleted: boolean }> {
  return json(
    await fetch(
      `/api/chats/${chatId}/branches/${branchId}/working-memory/${encodeURIComponent(key)}`,
      { method: "DELETE" },
    ),
  );
}

export async function clearWorkingMemory(
  chatId: number,
  branchId: number,
): Promise<{ ok: boolean }> {
  return json(
    await fetch(
      `/api/chats/${chatId}/branches/${branchId}/working-memory`,
      { method: "DELETE" },
    ),
  );
}

export async function fetchLongTermMemory(
  userId: string,
): Promise<MemoryItem[]> {
  return json(
    await fetch(`/api/users/${encodeURIComponent(userId)}/long-term-memory`),
  );
}

export async function putLongTermMemoryItem(
  userId: string,
  key: string,
  value: string,
): Promise<MemoryItem> {
  return json(
    await fetch(
      `/api/users/${encodeURIComponent(userId)}/long-term-memory/${encodeURIComponent(key)}`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value }),
      },
    ),
  );
}

export async function deleteLongTermMemoryItem(
  userId: string,
  key: string,
): Promise<{ deleted: boolean }> {
  return json(
    await fetch(
      `/api/users/${encodeURIComponent(userId)}/long-term-memory/${encodeURIComponent(key)}`,
      { method: "DELETE" },
    ),
  );
}

export async function clearLongTermMemory(
  userId: string,
): Promise<{ ok: boolean }> {
  return json(
    await fetch(
      `/api/users/${encodeURIComponent(userId)}/long-term-memory`,
      { method: "DELETE" },
    ),
  );
}

export async function patchBranch(
  chatId: number,
  branchId: number,
  body: {
    title?: string | null;
    system_prompt?: string | null;
    temperature?: number | null;
    max_tokens?: number | null;
    timeout_sec?: number | null;
    memory_strategy?: string | null;
    strategy_params_json?: string | null;
  },
): Promise<Branch> {
  return json(
    await fetch(`/api/chats/${chatId}/branches/${branchId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
}
