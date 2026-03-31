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

export type MemoryProfile = {
  id: string;
  title: string;
  description: string;
  user_id: string;
};

export async function fetchMemoryProfiles(): Promise<MemoryProfile[]> {
  return json(await fetch("/api/memory-profiles"));
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
