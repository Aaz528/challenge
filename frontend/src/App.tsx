import { useCallback, useEffect, useState } from "react";
import {
  clearLongTermMemory,
  clearWorkingMemory,
  createChat,
  deleteLongTermMemoryItem,
  deleteWorkingMemoryItem,
  fetchBranchFacts,
  fetchBranches,
  fetchChats,
  fetchLongTermMemory,
  fetchMessages,
  fetchWorkingMemory,
  forkBranch,
  patchBranch,
  putLongTermMemoryItem,
  putWorkingMemoryItem,
  sendMessage,
  type Branch,
  type Chat,
  type MemoryItem,
  type Message,
} from "./api";
import "./App.css";

function userIdFromBranch(b: Branch | undefined): string {
  if (!b) return "default_user";
  try {
    const p = JSON.parse(b.strategy_params_json || "{}") as Record<
      string,
      unknown
    >;
    const u = p.user_id;
    if (typeof u === "string" && u.trim()) return u.trim();
  } catch {
    /* ignore */
  }
  return "default_user";
}

const MEMORY_STRATEGY_OPTIONS = [
  { value: "default", label: "Полная история (без summary)" },
  { value: "summary", label: "Summary + сворачивание" },
  { value: "sliding_window", label: "Скользящее окно (N сообщений)" },
  { value: "sticky_facts", label: "Sticky Facts / KV-память" },
  { value: "triple_memory", label: "Triple Memory (short/working/long)" },
] as const;

export default function App() {
  const [chats, setChats] = useState<Chat[]>([]);
  const [activeChatId, setActiveChatId] = useState<number | null>(null);
  const [branches, setBranches] = useState<Branch[]>([]);
  const [activeBranchId, setActiveBranchId] = useState<number | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const [forkAfterId, setForkAfterId] = useState<number | null>(null);
  const [forkTitle, setForkTitle] = useState("Новая ветка");
  const [forkSp, setForkSp] = useState("");
  const [forkTemp, setForkTemp] = useState("");
  const [forkMax, setForkMax] = useState("");
  const [forkTo, setForkTo] = useState("");
  const [editSp, setEditSp] = useState("");
  const [editTemp, setEditTemp] = useState("");
  const [editMax, setEditMax] = useState("");
  const [editTo, setEditTo] = useState("");
  const [editStrategy, setEditStrategy] = useState("summary");
  const [editSlidingN, setEditSlidingN] = useState("20");
  const [editStickyTail, setEditStickyTail] = useState("12");
  const [editTripleTail, setEditTripleTail] = useState("12");
  const [editTripleUserId, setEditTripleUserId] = useState("default_user");
  const [factsPreview, setFactsPreview] = useState("");
  const [showMemoryPanel, setShowMemoryPanel] = useState(false);
  const [memoryTab, setMemoryTab] = useState<"working" | "long">("working");
  const [memorySearch, setMemorySearch] = useState("");
  const [workingMemoryItems, setWorkingMemoryItems] = useState<MemoryItem[]>(
    [],
  );
  const [longTermItems, setLongTermItems] = useState<MemoryItem[]>([]);
  const [memoryLtUserId, setMemoryLtUserId] = useState("default_user");
  const [newWmKey, setNewWmKey] = useState("");
  const [newWmValue, setNewWmValue] = useState("");
  const [newLmKey, setNewLmKey] = useState("");
  const [newLmValue, setNewLmValue] = useState("");
  const [editTarget, setEditTarget] = useState<
    { kind: "wm" | "lm"; key: string } | null
  >(null);
  const [editValue, setEditValue] = useState("");
  const [wmLoading, setWmLoading] = useState(false);
  const [ltLoading, setLtLoading] = useState(false);
  const [wmError, setWmError] = useState<string | null>(null);
  const [ltError, setLtError] = useState<string | null>(null);

  const loadChats = useCallback(async () => {
    const list = await fetchChats();
    setChats(list);
    return list;
  }, []);

  useEffect(() => {
    loadChats().catch((e: unknown) =>
      setError(e instanceof Error ? e.message : String(e)),
    );
  }, [loadChats]);

  const loadBranchesForChat = useCallback(async (chatId: number) => {
    const list = await fetchBranches(chatId);
    setBranches(list);
    const main = list.find((b) => b.parent_branch_id == null) ?? list[0];
    if (main) {
      setActiveBranchId(main.id);
      return main.id;
    }
    return null;
  }, []);

  const selectChat = useCallback(
    async (id: number) => {
      setActiveChatId(id);
      setError(null);
      const bid = await loadBranchesForChat(id);
      if (bid != null) {
        const msgs = await fetchMessages(id, bid);
        setMessages(msgs);
      } else {
        setMessages([]);
      }
    },
    [loadBranchesForChat],
  );

  const switchBranch = useCallback(
    async (branchId: number) => {
      if (activeChatId == null) return;
      setActiveBranchId(branchId);
      setError(null);
      const msgs = await fetchMessages(activeChatId, branchId);
      setMessages(msgs);
    },
    [activeChatId],
  );

  const activeBranch = branches.find((b) => b.id === activeBranchId);

  useEffect(() => {
    if (activeBranch) {
      setEditSp(activeBranch.system_prompt);
      setEditTemp(String(activeBranch.temperature));
      setEditMax(String(activeBranch.max_tokens));
      setEditTo(String(activeBranch.timeout_sec));
      setEditStrategy(activeBranch.memory_strategy);
      let p: Record<string, unknown> = {};
      try {
        p = JSON.parse(activeBranch.strategy_params_json || "{}") as Record<
          string,
          unknown
        >;
      } catch {
        p = {};
      }
      const sw = p.sliding_window_messages;
      const st = p.sticky_tail_messages;
      const tt = p.triple_short_tail_messages;
      const tu = p.user_id;
      setEditSlidingN(
        typeof sw === "number" && Number.isFinite(sw) ? String(sw) : "20",
      );
      setEditStickyTail(
        typeof st === "number" && Number.isFinite(st) ? String(st) : "12",
      );
      setEditTripleTail(
        typeof tt === "number" && Number.isFinite(tt) ? String(tt) : "12",
      );
      setEditTripleUserId(typeof tu === "string" && tu.trim() ? tu : "default_user");
    }
  }, [activeBranch, showSettings]);

  useEffect(() => {
    if (activeBranch) {
      setMemoryLtUserId(userIdFromBranch(activeBranch));
    }
  }, [activeBranch]);

  const loadWorkingMemoryList = useCallback(async () => {
    if (activeChatId == null || activeBranchId == null) return;
    setWmLoading(true);
    setWmError(null);
    try {
      const list = await fetchWorkingMemory(activeChatId, activeBranchId);
      setWorkingMemoryItems(list);
    } catch (e: unknown) {
      setWorkingMemoryItems([]);
      setWmError(e instanceof Error ? e.message : String(e));
    } finally {
      setWmLoading(false);
    }
  }, [activeChatId, activeBranchId]);

  const loadLongTermList = useCallback(async () => {
    const uid = memoryLtUserId.trim() || "default_user";
    setLtLoading(true);
    setLtError(null);
    try {
      const list = await fetchLongTermMemory(uid);
      setLongTermItems(list);
    } catch (e: unknown) {
      setLongTermItems([]);
      setLtError(e instanceof Error ? e.message : String(e));
    } finally {
      setLtLoading(false);
    }
  }, [memoryLtUserId]);

  useEffect(() => {
    if (!showMemoryPanel || activeChatId == null || activeBranchId == null) {
      return;
    }
    void loadWorkingMemoryList();
  }, [
    showMemoryPanel,
    activeChatId,
    activeBranchId,
    loadWorkingMemoryList,
  ]);

  useEffect(() => {
    if (
      !showMemoryPanel ||
      memoryTab !== "long" ||
      !memoryLtUserId.trim()
    ) {
      return;
    }
    void loadLongTermList();
  }, [showMemoryPanel, memoryTab, memoryLtUserId, loadLongTermList]);

  useEffect(() => {
    if (!showSettings || activeChatId == null || activeBranchId == null) {
      return;
    }
    if (editStrategy !== "sticky_facts") {
      setFactsPreview("");
      return;
    }
    void fetchBranchFacts(activeChatId, activeBranchId)
      .then((f) => setFactsPreview(JSON.stringify(f, null, 2)))
      .catch(() => setFactsPreview("(не удалось загрузить)"));
  }, [showSettings, activeChatId, activeBranchId, editStrategy]);

  const handleNewChat = async () => {
    setError(null);
    setLoading(true);
    try {
      const c = await createChat();
      await loadChats();
      await selectChat(c.id);
      setInput("");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const handleSend = async () => {
    const text = input.trim();
    if (!text || activeChatId == null || activeBranchId == null) return;
    setError(null);
    setLoading(true);
    setInput("");
    const optimisticUser: Message = {
      id: -Date.now(),
      role: "user",
      content: text,
      summarized: false,
    };
    setMessages((m) => [...m, optimisticUser]);
    try {
      await sendMessage(activeChatId, activeBranchId, text);
      const msgs = await fetchMessages(activeChatId, activeBranchId);
      setMessages(msgs);
      await loadChats();
      const br = await fetchBranches(activeChatId);
      setBranches(br);
      if (showMemoryPanel) {
        void loadWorkingMemoryList();
        if (memoryTab === "long") void loadLongTermList();
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
      setMessages((m) => m.filter((x) => x.id !== optimisticUser.id));
    } finally {
      setLoading(false);
    }
  };

  const openFork = (messageId: number) => {
    setForkAfterId(messageId);
    const b = branches.find((x) => x.id === activeBranchId);
    setForkTitle("Ветка от сообщения " + messageId);
    setForkSp(b?.system_prompt ?? "");
    setForkTemp(b != null ? String(b.temperature) : "");
    setForkMax(b != null ? String(b.max_tokens) : "");
    setForkTo(b != null ? String(b.timeout_sec) : "");
  };

  const submitFork = async () => {
    if (
      activeChatId == null ||
      activeBranchId == null ||
      forkAfterId == null
    )
      return;
    setLoading(true);
    setError(null);
    try {
      const body: Parameters<typeof forkBranch>[2] = {
        fork_after_message_id: forkAfterId,
        title: forkTitle.trim() || "Новая ветка",
      };
      if (forkSp.trim()) body.system_prompt = forkSp.trim();
      if (forkTemp.trim()) body.temperature = parseFloat(forkTemp);
      if (forkMax.trim()) body.max_tokens = parseInt(forkMax, 10);
      if (forkTo.trim()) body.timeout_sec = parseFloat(forkTo);
      const nb = await forkBranch(activeChatId, activeBranchId, body);
      setForkAfterId(null);
      await loadBranchesForChat(activeChatId);
      setActiveBranchId(nb.id);
      const msgs = await fetchMessages(activeChatId, nb.id);
      setMessages(msgs);
      await loadChats();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const filterMemoryItems = (items: MemoryItem[]) => {
    const q = memorySearch.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (it) =>
        it.key.toLowerCase().includes(q) ||
        it.value.toLowerCase().includes(q),
    );
  };

  const saveBranchSettings = async () => {
    if (activeChatId == null || activeBranchId == null) return;
    setLoading(true);
    setError(null);
    try {
      const params: Record<string, number | string> = {};
      if (editStrategy === "sliding_window") {
        const n = parseInt(editSlidingN, 10);
        params.sliding_window_messages =
          Number.isFinite(n) && n > 0 ? n : 20;
      }
      if (editStrategy === "sticky_facts") {
        const n = parseInt(editStickyTail, 10);
        params.sticky_tail_messages =
          Number.isFinite(n) && n > 0 ? n : 12;
      }
      if (editStrategy === "triple_memory") {
        const n = parseInt(editTripleTail, 10);
        params.triple_short_tail_messages =
          Number.isFinite(n) && n > 0 ? n : 12;
        params.user_id = editTripleUserId.trim() || "default_user";
      }
      await patchBranch(activeChatId, activeBranchId, {
        system_prompt: editSp,
        temperature: parseFloat(editTemp),
        max_tokens: parseInt(editMax, 10),
        timeout_sec: parseFloat(editTo),
        memory_strategy: editStrategy,
        strategy_params_json: JSON.stringify(params),
      });
      const br = await fetchBranches(activeChatId);
      setBranches(br);
      setShowSettings(false);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const refreshMemoryPanel = async () => {
    try {
      if (memoryTab === "working") await loadWorkingMemoryList();
      else await loadLongTermList();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleAddWorkingMemory = async () => {
    if (activeChatId == null || activeBranchId == null) return;
    const k = newWmKey.trim();
    if (!k) return;
    setLoading(true);
    setError(null);
    try {
      await putWorkingMemoryItem(
        activeChatId,
        activeBranchId,
        k,
        newWmValue,
      );
      setNewWmKey("");
      setNewWmValue("");
      await loadWorkingMemoryList();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteWorking = async (key: string) => {
    if (activeChatId == null || activeBranchId == null) return;
    if (!window.confirm(`Удалить ключ «${key}» из рабочей памяти?`)) return;
    setLoading(true);
    setError(null);
    try {
      await deleteWorkingMemoryItem(activeChatId, activeBranchId, key);
      setEditTarget(null);
      await loadWorkingMemoryList();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const handleClearWorking = async () => {
    if (activeChatId == null || activeBranchId == null) return;
    if (!window.confirm("Очистить всю рабочую память этой ветки?")) return;
    setLoading(true);
    setError(null);
    try {
      await clearWorkingMemory(activeChatId, activeBranchId);
      setEditTarget(null);
      await loadWorkingMemoryList();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const handleAddLongTerm = async () => {
    const uid = memoryLtUserId.trim() || "default_user";
    const k = newLmKey.trim();
    if (!k) return;
    setLoading(true);
    setError(null);
    try {
      await putLongTermMemoryItem(uid, k, newLmValue);
      setNewLmKey("");
      setNewLmValue("");
      await loadLongTermList();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteLongTerm = async (key: string) => {
    const uid = memoryLtUserId.trim() || "default_user";
    if (!window.confirm(`Удалить ключ «${key}» из долговременной памяти?`))
      return;
    setLoading(true);
    setError(null);
    try {
      await deleteLongTermMemoryItem(uid, key);
      setEditTarget(null);
      await loadLongTermList();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const handleClearLongTerm = async () => {
    const uid = memoryLtUserId.trim() || "default_user";
    if (!window.confirm(`Очистить всю долговременную память для ${uid}?`))
      return;
    setLoading(true);
    setError(null);
    try {
      await clearLongTermMemory(uid);
      setEditTarget(null);
      await loadLongTermList();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const handleSaveEdit = async () => {
    if (editTarget == null || activeChatId == null || activeBranchId == null)
      return;
    setLoading(true);
    setError(null);
    try {
      if (editTarget.kind === "wm") {
        await putWorkingMemoryItem(
          activeChatId,
          activeBranchId,
          editTarget.key,
          editValue,
        );
        await loadWorkingMemoryList();
      } else {
        const uid = memoryLtUserId.trim() || "default_user";
        await putLongTermMemoryItem(uid, editTarget.key, editValue);
        await loadLongTermList();
      }
      setEditTarget(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="sidebar-head">
          <h1>Чаты</h1>
          <button
            type="button"
            className="btn primary"
            onClick={handleNewChat}
            disabled={loading}
          >
            + Новый
          </button>
        </div>
        <ul className="chat-list">
          {chats.map((c) => (
            <li key={c.id}>
              <button
                type="button"
                className={
                  c.id === activeChatId ? "chat-item active" : "chat-item"
                }
                onClick={() => selectChat(c.id)}
              >
                <span className="chat-title">{c.title}</span>
                <span className="chat-meta">{c.total_tokens} tok</span>
              </button>
            </li>
          ))}
        </ul>
      </aside>
      <main className="main">
        {activeChatId == null ? (
          <div className="empty">Выберите чат или создайте новый</div>
        ) : (
          <div
            className={
              showMemoryPanel ? "main-wrap main-wrap--split" : "main-wrap"
            }
          >
            <div className="main-chat">
            <div className="toolbar">
              <label>
                Ветка:{" "}
                <select
                  value={activeBranchId ?? ""}
                  onChange={(e) => {
                    const v = parseInt(e.target.value, 10);
                    if (!Number.isNaN(v)) void switchBranch(v);
                  }}
                >
                  {branches.map((b) => (
                    <option key={b.id} value={b.id}>
                      {b.title} ({b.total_tokens} tok)
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                className="btn"
                onClick={() => setShowSettings((s) => !s)}
              >
                Настройки ветки
              </button>
              <button
                type="button"
                className={showMemoryPanel ? "btn primary" : "btn"}
                onClick={() => setShowMemoryPanel((s) => !s)}
              >
                Память
              </button>
            </div>
            {showSettings && activeBranch && (
              <div className="settings-panel">
                <h3>Настройки текущей ветки</h3>
                <label>
                  Стратегия памяти
                  <select
                    value={editStrategy}
                    onChange={(e) => setEditStrategy(e.target.value)}
                  >
                    {MEMORY_STRATEGY_OPTIONS.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                </label>
                <p className="hint strategy-hint">
                  {editStrategy === "default" &&
                    "В контекст попадает вся история user/assistant из БД без сводок."}
                  {editStrategy === "summary" &&
                    "Сводки в summaries + «живые» сообщения; периодическое сворачивание старых ходов."}
                  {editStrategy === "sliding_window" &&
                    "В БД и в промпте остаются только последние N сообщений (user+assistant)."}
                  {editStrategy === "sticky_facts" &&
                    "После каждого сообщения пользователя обновляется блок фактов; в промпт идут факты + хвост диалога."}
                  {editStrategy === "triple_memory" &&
                    "Контекст собирается из short-term диалога, working memory ветки и long-term памяти пользователя."}
                </p>
                {editStrategy === "sliding_window" && (
                  <label>
                    Окно: последних сообщений (user+assistant)
                    <input
                      type="number"
                      min={2}
                      value={editSlidingN}
                      onChange={(e) => setEditSlidingN(e.target.value)}
                    />
                  </label>
                )}
                {editStrategy === "sticky_facts" && (
                  <>
                    <label>
                      Хвост диалога (сообщений user+assistant) вместе с фактами
                      <input
                        type="number"
                        min={1}
                        value={editStickyTail}
                        onChange={(e) => setEditStickyTail(e.target.value)}
                      />
                    </label>
                    <label>
                      Текущие факты (только чтение)
                      <textarea
                        rows={6}
                        readOnly
                        className="facts-readonly"
                        value={factsPreview}
                      />
                    </label>
                  </>
                )}
                {editStrategy === "triple_memory" && (
                  <>
                    <label>
                      Short-term хвост (сообщений user+assistant)
                      <input
                        type="number"
                        min={1}
                        value={editTripleTail}
                        onChange={(e) => setEditTripleTail(e.target.value)}
                      />
                    </label>
                    <label>
                      User ID для long-term памяти
                      <input
                        value={editTripleUserId}
                        onChange={(e) => setEditTripleUserId(e.target.value)}
                      />
                    </label>
                  </>
                )}
                <label>
                  System prompt
                  <textarea
                    rows={4}
                    value={editSp}
                    onChange={(e) => setEditSp(e.target.value)}
                  />
                </label>
                <div className="settings-row">
                  <label>
                    Temperature
                    <input
                      type="number"
                      step="0.1"
                      value={editTemp}
                      onChange={(e) => setEditTemp(e.target.value)}
                    />
                  </label>
                  <label>
                    Max tokens
                    <input
                      type="number"
                      value={editMax}
                      onChange={(e) => setEditMax(e.target.value)}
                    />
                  </label>
                  <label>
                    Timeout (сек)
                    <input
                      type="number"
                      step="1"
                      value={editTo}
                      onChange={(e) => setEditTo(e.target.value)}
                    />
                  </label>
                </div>
                <button
                  type="button"
                  className="btn primary"
                  onClick={() => void saveBranchSettings()}
                  disabled={loading}
                >
                  Сохранить
                </button>
              </div>
            )}
            <div className="messages">
              {messages
                .filter((m) => m.role !== "system")
                .map((m) => (
                  <div key={m.id} className="msg-row">
                    <div
                      className={
                        m.role === "user" ? "bubble user" : "bubble assistant"
                      }
                    >
                      {m.summarized && (
                        <span className="badge">в архиве (summary)</span>
                      )}
                      <pre className="text">{m.content}</pre>
                    </div>
                    {m.id > 0 && (
                      <button
                        type="button"
                        className="btn fork-btn"
                        title="Новая ветка от этого сообщения"
                        onClick={() => openFork(m.id)}
                      >
                        ↗
                      </button>
                    )}
                  </div>
                ))}
            </div>
            {error && <div className="err">{error}</div>}
            <div className="composer">
              <textarea
                rows={3}
                placeholder="Сообщение…"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void handleSend();
                  }
                }}
                disabled={loading}
              />
              <button
                type="button"
                className="btn primary"
                onClick={() => void handleSend()}
                disabled={loading || !input.trim()}
              >
                Отправить
              </button>
            </div>
            </div>
            {showMemoryPanel && activeBranchId != null && activeChatId != null && (
              <aside className="memory-panel" aria-label="Память ветки">
                <div className="memory-panel-head">
                  <h2>Память</h2>
                  <button
                    type="button"
                    className="btn"
                    disabled={loading}
                    onClick={() => void refreshMemoryPanel()}
                  >
                    Обновить
                  </button>
                </div>
                <div className="memory-tabs" role="tablist">
                  <button
                    type="button"
                    role="tab"
                    aria-selected={memoryTab === "working"}
                    className={memoryTab === "working" ? "active" : ""}
                    onClick={() => {
                      setMemoryTab("working");
                      setEditTarget(null);
                      void loadWorkingMemoryList();
                    }}
                  >
                    Рабочая
                  </button>
                  <button
                    type="button"
                    role="tab"
                    aria-selected={memoryTab === "long"}
                    className={memoryTab === "long" ? "active" : ""}
                    onClick={() => {
                      setMemoryTab("long");
                      setEditTarget(null);
                      void loadLongTermList();
                    }}
                  >
                    Долговременная
                  </button>
                </div>
                <div className="memory-panel-body">
                  <input
                    type="search"
                    className="memory-search"
                    placeholder="Поиск по ключу или значению…"
                    value={memorySearch}
                    onChange={(e) => setMemorySearch(e.target.value)}
                  />
                  {memoryTab === "working" && (
                    <>
                      <p className="memory-hint">
                        Таблица <code>working_memory</code> для текущей ветки.
                        Факты стратегии sticky_facts — в настройках ветки.
                      </p>
                      {wmLoading && (
                        <p className="memory-status">Загрузка…</p>
                      )}
                      {wmError && (
                        <div className="memory-err" role="alert">
                          {wmError}
                          <br />
                          <span className="memory-hint">
                            Убедитесь, что API запущен и прокси /api доступен.
                          </span>
                        </div>
                      )}
                      {!wmLoading &&
                        !wmError &&
                        filterMemoryItems(workingMemoryItems).length === 0 && (
                          <p className="memory-empty">
                            Нет записей. Добавьте ниже или используйте стратегию{" "}
                            <code>triple_memory</code>, чтобы модель могла
                            менять память через инструменты.
                          </p>
                        )}
                      {!wmLoading &&
                        filterMemoryItems(workingMemoryItems).length > 0 && (
                          <div className="memory-json-block">
                            <strong>Просмотр (JSON)</strong>
                            <pre className="memory-json-preview">
                              {JSON.stringify(
                                Object.fromEntries(
                                  filterMemoryItems(workingMemoryItems).map(
                                    (r) => [r.key, r.value],
                                  ),
                                ),
                                null,
                                2,
                              )}
                            </pre>
                          </div>
                        )}
                      <div className="memory-actions">
                        <button
                          type="button"
                          className="btn"
                          disabled={loading}
                          onClick={() => void handleClearWorking()}
                        >
                          Очистить всё
                        </button>
                      </div>
                      <div className="memory-table-wrap">
                        <table className="memory-table">
                          <thead>
                            <tr>
                              <th>Ключ</th>
                              <th>Значение</th>
                              <th>Обновлено</th>
                              <th />
                            </tr>
                          </thead>
                          <tbody>
                            {filterMemoryItems(workingMemoryItems).map(
                              (row) => (
                                <tr key={row.key}>
                                  <td className="memory-key">{row.key}</td>
                                  <td className="memory-val">
                                    {editTarget?.kind === "wm" &&
                                    editTarget.key === row.key ? (
                                      <div className="memory-edit">
                                        <textarea
                                          value={editValue}
                                          onChange={(e) =>
                                            setEditValue(e.target.value)
                                          }
                                        />
                                        <div className="memory-actions">
                                          <button
                                            type="button"
                                            className="btn primary"
                                            disabled={loading}
                                            onClick={() => void handleSaveEdit()}
                                          >
                                            Сохранить
                                          </button>
                                          <button
                                            type="button"
                                            className="btn"
                                            onClick={() => setEditTarget(null)}
                                          >
                                            Отмена
                                          </button>
                                        </div>
                                      </div>
                                    ) : (
                                      <span className="memory-val-text">
                                        {row.value}
                                      </span>
                                    )}
                                  </td>
                                  <td className="memory-meta">
                                    {row.updated_at}
                                  </td>
                                  <td className="memory-actions">
                                    <button
                                      type="button"
                                      className="btn"
                                      disabled={
                                        loading ||
                                        (editTarget?.kind === "wm" &&
                                          editTarget.key === row.key)
                                      }
                                      onClick={() => {
                                        setEditTarget({
                                          kind: "wm",
                                          key: row.key,
                                        });
                                        setEditValue(row.value);
                                      }}
                                    >
                                      Изм.
                                    </button>
                                    <button
                                      type="button"
                                      className="btn"
                                      disabled={loading}
                                      onClick={() =>
                                        void handleDeleteWorking(row.key)
                                      }
                                    >
                                      Удал.
                                    </button>
                                  </td>
                                </tr>
                              ),
                            )}
                          </tbody>
                        </table>
                      </div>
                      <details className="memory-add-details">
                        <summary>Добавить запись</summary>
                        <div className="memory-add">
                          <input
                            placeholder="Ключ"
                            value={newWmKey}
                            onChange={(e) => setNewWmKey(e.target.value)}
                          />
                          <textarea
                            placeholder="Значение"
                            value={newWmValue}
                            onChange={(e) => setNewWmValue(e.target.value)}
                          />
                          <button
                            type="button"
                            className="btn primary"
                            disabled={loading || !newWmKey.trim()}
                            onClick={() => void handleAddWorkingMemory()}
                          >
                            Добавить
                          </button>
                        </div>
                      </details>
                    </>
                  )}
                  {memoryTab === "long" && (
                    <>
                      <p className="memory-hint">
                        Долговременная память по <code>user_id</code> (таблица{" "}
                        <code>long_term_memory</code>). Должна совпадать с{" "}
                        <code>user_id</code> в параметрах ветки для{" "}
                        <code>triple_memory</code>.
                      </p>
                      <div className="memory-lt-user">
                        <label>
                          User ID
                          <input
                            value={memoryLtUserId}
                            onChange={(e) =>
                              setMemoryLtUserId(e.target.value)
                            }
                          />
                        </label>
                        <button
                          type="button"
                          className="btn primary"
                          disabled={loading}
                          onClick={() => void loadLongTermList()}
                        >
                          Загрузить
                        </button>
                      </div>
                      {ltLoading && (
                        <p className="memory-status">Загрузка…</p>
                      )}
                      {ltError && (
                        <div className="memory-err" role="alert">
                          {ltError}
                        </div>
                      )}
                      {!ltLoading &&
                        !ltError &&
                        filterMemoryItems(longTermItems).length === 0 && (
                          <p className="memory-empty">
                            Нет записей для этого user_id.
                          </p>
                        )}
                      {!ltLoading &&
                        filterMemoryItems(longTermItems).length > 0 && (
                          <div className="memory-json-block">
                            <strong>Просмотр (JSON)</strong>
                            <pre className="memory-json-preview">
                              {JSON.stringify(
                                Object.fromEntries(
                                  filterMemoryItems(longTermItems).map((r) => [
                                    r.key,
                                    r.value,
                                  ]),
                                ),
                                null,
                                2,
                              )}
                            </pre>
                          </div>
                        )}
                      <div className="memory-actions">
                        <button
                          type="button"
                          className="btn"
                          disabled={loading}
                          onClick={() => void handleClearLongTerm()}
                        >
                          Очистить всё
                        </button>
                      </div>
                      <div className="memory-table-wrap">
                        <table className="memory-table">
                          <thead>
                            <tr>
                              <th>Ключ</th>
                              <th>Значение</th>
                              <th>Обновлено</th>
                              <th />
                            </tr>
                          </thead>
                          <tbody>
                            {filterMemoryItems(longTermItems).map((row) => (
                              <tr key={row.key}>
                                <td className="memory-key">{row.key}</td>
                                <td className="memory-val">
                                  {editTarget?.kind === "lm" &&
                                  editTarget.key === row.key ? (
                                    <div className="memory-edit">
                                      <textarea
                                        value={editValue}
                                        onChange={(e) =>
                                          setEditValue(e.target.value)
                                        }
                                      />
                                      <div className="memory-actions">
                                        <button
                                          type="button"
                                          className="btn primary"
                                          disabled={loading}
                                          onClick={() => void handleSaveEdit()}
                                        >
                                          Сохранить
                                        </button>
                                        <button
                                          type="button"
                                          className="btn"
                                          onClick={() => setEditTarget(null)}
                                        >
                                          Отмена
                                        </button>
                                      </div>
                                    </div>
                                  ) : (
                                    <span className="memory-val-text">
                                      {row.value}
                                    </span>
                                  )}
                                </td>
                                <td className="memory-meta">
                                  {row.updated_at}
                                </td>
                                <td className="memory-actions">
                                  <button
                                    type="button"
                                    className="btn"
                                    disabled={
                                      loading ||
                                      (editTarget?.kind === "lm" &&
                                        editTarget.key === row.key)
                                    }
                                    onClick={() => {
                                      setEditTarget({
                                        kind: "lm",
                                        key: row.key,
                                      });
                                      setEditValue(row.value);
                                    }}
                                  >
                                    Изм.
                                  </button>
                                  <button
                                    type="button"
                                    className="btn"
                                    disabled={loading}
                                    onClick={() =>
                                      void handleDeleteLongTerm(row.key)
                                    }
                                  >
                                    Удал.
                                  </button>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                      <details className="memory-add-details">
                        <summary>Добавить запись</summary>
                        <div className="memory-add">
                          <input
                            placeholder="Ключ"
                            value={newLmKey}
                            onChange={(e) => setNewLmKey(e.target.value)}
                          />
                          <textarea
                            placeholder="Значение"
                            value={newLmValue}
                            onChange={(e) => setNewLmValue(e.target.value)}
                          />
                          <button
                            type="button"
                            className="btn primary"
                            disabled={loading || !newLmKey.trim()}
                            onClick={() => void handleAddLongTerm()}
                          >
                            Добавить
                          </button>
                        </div>
                      </details>
                    </>
                  )}
                </div>
              </aside>
            )}
          </div>
        )}
        {forkAfterId != null && (
          <div className="modal-backdrop" role="presentation">
            <div className="modal">
              <h3>Новая ветка</h3>
              <p className="hint">История до сообщения #{forkAfterId} включительно будет скопирована.</p>
              <label>
                Заголовок
                <input
                  value={forkTitle}
                  onChange={(e) => setForkTitle(e.target.value)}
                />
              </label>
              <label>
                System prompt (пусто = как у родителя)
                <textarea
                  rows={3}
                  value={forkSp}
                  onChange={(e) => setForkSp(e.target.value)}
                />
              </label>
              <div className="settings-row">
                <label>
                  Temperature
                  <input
                    value={forkTemp}
                    placeholder="по умолч."
                    onChange={(e) => setForkTemp(e.target.value)}
                  />
                </label>
                <label>
                  Max tokens
                  <input
                    value={forkMax}
                    placeholder="по умолч."
                    onChange={(e) => setForkMax(e.target.value)}
                  />
                </label>
                <label>
                  Timeout
                  <input
                    value={forkTo}
                    placeholder="по умолч."
                    onChange={(e) => setForkTo(e.target.value)}
                  />
                </label>
              </div>
              <div className="modal-actions">
                <button
                  type="button"
                  className="btn"
                  onClick={() => setForkAfterId(null)}
                >
                  Отмена
                </button>
                <button
                  type="button"
                  className="btn primary"
                  onClick={() => void submitFork()}
                  disabled={loading}
                >
                  Создать ветку
                </button>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
