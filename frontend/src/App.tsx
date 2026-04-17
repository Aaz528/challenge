import { useCallback, useEffect, useRef, useState } from "react";
import {
  clearLongTermMemory,
  clearWorkingMemory,
  createChat,
  createInvariant,
  deleteInvariant,
  deleteLongTermMemoryItem,
  deleteWorkingMemoryItem,
  fetchBranchFacts,
  fetchBranches,
  fetchChats,
  fetchIrkutskWeather,
  fetchInvariants,
  fetchLongTermMemory,
  fetchMemoryProfiles,
  fetchTaskFsm,
  fetchMessages,
  fetchWorkingMemory,
  forkBranch,
  patchBranch,
  pauseTaskFsm,
  putLongTermMemoryItem,
  putWorkingMemoryItem,
  resumeTaskFsm,
  resumeMessageStream,
  runRagBenchmark,
  runRagQuery,
  runMcpEduPipeline,
  sendMessageStream,
  stopAndPauseMessageStream,
  stopMessageStream,
  type Branch,
  type Chat,
  type Invariant,
  type MemoryItem,
  type MemoryProfile,
  type RagBenchmarkResponse,
  type RagQueryResponse,
  type MCPPipelineResult,
  type TaskFSM,
  type WeatherPopup,
  type Message,
} from "./api";
import "./App.css";

const DEFAULT_PROFILE_USER_ID = "profile_starter";

function userIdFromBranch(b: Branch | undefined): string {
  if (!b) return DEFAULT_PROFILE_USER_ID;
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
  return DEFAULT_PROFILE_USER_ID;
}

function profileChoiceFromUserId(
  profiles: MemoryProfile[],
  userId: string,
): string {
  const uid = userId.trim();
  const found = profiles.find((p) => p.user_id === uid);
  return found ? found.id : "custom";
}

const INVARIANT_CATEGORY_OPTIONS = [
  { value: "architecture", label: "Архитектура" },
  { value: "decision", label: "Решение" },
  { value: "stack", label: "Стек" },
  { value: "business", label: "Бизнес" },
  { value: "other", label: "Другое" },
] as const;

const INVARIANT_SEVERITY_OPTIONS = [
  { value: "hard", label: "hard (нельзя нарушать)" },
  { value: "soft", label: "soft (предпочтительно)" },
] as const;

const MEMORY_STRATEGY_OPTIONS = [
  { value: "default", label: "Полная история (без summary)" },
  { value: "summary", label: "Summary + сворачивание" },
  { value: "sliding_window", label: "Скользящее окно (N сообщений)" },
  { value: "sticky_facts", label: "Sticky Facts / KV-память" },
  { value: "triple_memory", label: "Triple Memory (short/working/long)" },
] as const;

type StreamPhase =
  | "idle"
  | "request"
  | "facts"
  | "wm_merge"
  | "tools"
  | "answer"
  | "done"
  | "stopped";

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
  const [editTripleUserId, setEditTripleUserId] = useState(
    DEFAULT_PROFILE_USER_ID,
  );
  const [factsPreview, setFactsPreview] = useState("");
  const [showMemoryPanel, setShowMemoryPanel] = useState(false);
  const [memoryTab, setMemoryTab] = useState<"working" | "long" | "invariants">(
    "working",
  );
  const [memorySearch, setMemorySearch] = useState("");
  const [workingMemoryItems, setWorkingMemoryItems] = useState<MemoryItem[]>(
    [],
  );
  const [longTermItems, setLongTermItems] = useState<MemoryItem[]>([]);
  const [memoryLtUserId, setMemoryLtUserId] = useState(
    DEFAULT_PROFILE_USER_ID,
  );
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
  const [invariantItems, setInvariantItems] = useState<Invariant[]>([]);
  const [invLoading, setInvLoading] = useState(false);
  const [invError, setInvError] = useState<string | null>(null);
  const [newInvCategory, setNewInvCategory] = useState("architecture");
  const [newInvSeverity, setNewInvSeverity] = useState("hard");
  const [newInvTitle, setNewInvTitle] = useState("");
  const [newInvStatement, setNewInvStatement] = useState("");
  const [memoryProfiles, setMemoryProfiles] = useState<MemoryProfile[]>([]);
  const [tripleProfileChoice, setTripleProfileChoice] = useState("custom");
  const [ltProfileChoice, setLtProfileChoice] = useState("custom");
  const [taskFsm, setTaskFsm] = useState<TaskFSM | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamStatus, setStreamStatus] = useState("");
  const [streamPhase, setStreamPhase] = useState<StreamPhase>("idle");
  const [canResumeAnswer, setCanResumeAnswer] = useState(false);
  const [weatherPopupOpen, setWeatherPopupOpen] = useState(false);
  const [weatherLoading, setWeatherLoading] = useState(false);
  const [weatherError, setWeatherError] = useState<string | null>(null);
  const [weatherData, setWeatherData] = useState<WeatherPopup | null>(null);
  const [lastWeatherAt, setLastWeatherAt] = useState<number>(0);
  const [pipelinePopupOpen, setPipelinePopupOpen] = useState(false);
  const [pipelineQuery, setPipelineQuery] = useState("Иркутск");
  const [pipelineFile, setPipelineFile] = useState("outputs/mcp_pipeline_summary.txt");
  const [pipelineLoading, setPipelineLoading] = useState(false);
  const [pipelineError, setPipelineError] = useState<string | null>(null);
  const [pipelineData, setPipelineData] = useState<MCPPipelineResult | null>(null);
  const [ragLabOpen, setRagLabOpen] = useState(false);
  const [ragQuestion, setRagQuestion] = useState("Где в проекте маршрутизация MCP-инструментов?");
  const [ragMode, setRagMode] = useState<"without_rag" | "with_rag" | "both">("both");
  const [ragStrategy, setRagStrategy] = useState<"fixed" | "structured" | "all">("structured");
  const [ragRewriteMode, setRagRewriteMode] = useState<"none" | "heuristic">("heuristic");
  const [ragRerankMode, setRagRerankMode] = useState<"none" | "threshold" | "hybrid">("hybrid");
  const [ragTopKBefore, setRagTopKBefore] = useState("20");
  const [ragTopKAfter, setRagTopKAfter] = useState("5");
  const [ragThreshold, setRagThreshold] = useState("0.12");
  const [ragAnswerMinScore, setRagAnswerMinScore] = useState("");
  const [ragMaxContext, setRagMaxContext] = useState("6000");
  const [ragForceLocal, setRagForceLocal] = useState(true);
  const [ragLoading, setRagLoading] = useState(false);
  const [ragError, setRagError] = useState<string | null>(null);
  const [ragResult, setRagResult] = useState<RagQueryResponse | null>(null);
  const [ragBenchLoading, setRagBenchLoading] = useState(false);
  const [ragBenchError, setRagBenchError] = useState<string | null>(null);
  const [ragBenchResult, setRagBenchResult] = useState<RagBenchmarkResponse | null>(null);
  const streamAbortRef = useRef<AbortController | null>(null);

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

  useEffect(() => {
    void fetchMemoryProfiles()
      .then((items) => setMemoryProfiles(items))
      .catch(() => setMemoryProfiles([]));
  }, []);

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
      const uid =
        typeof tu === "string" && tu.trim()
          ? tu
          : DEFAULT_PROFILE_USER_ID;
      setEditTripleUserId(uid);
      setTripleProfileChoice(profileChoiceFromUserId(memoryProfiles, uid));
    }
  }, [activeBranch, showSettings, memoryProfiles]);

  useEffect(() => {
    if (activeBranch) {
      const uid = userIdFromBranch(activeBranch);
      setMemoryLtUserId(uid);
      setLtProfileChoice(profileChoiceFromUserId(memoryProfiles, uid));
    }
  }, [activeBranch, memoryProfiles]);

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
    const uid = memoryLtUserId.trim() || DEFAULT_PROFILE_USER_ID;
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

  const loadInvariantList = useCallback(async () => {
    const uid = memoryLtUserId.trim() || DEFAULT_PROFILE_USER_ID;
    setInvLoading(true);
    setInvError(null);
    try {
      const list = await fetchInvariants(uid);
      setInvariantItems(list);
    } catch (e: unknown) {
      setInvariantItems([]);
      setInvError(e instanceof Error ? e.message : String(e));
    } finally {
      setInvLoading(false);
    }
  }, [memoryLtUserId]);

  useEffect(() => {
    if (
      !showMemoryPanel ||
      memoryTab !== "invariants" ||
      !memoryLtUserId.trim()
    ) {
      return;
    }
    void loadInvariantList();
  }, [showMemoryPanel, memoryTab, memoryLtUserId, loadInvariantList]);

  useEffect(() => {
    if (!showMemoryPanel || activeChatId == null || activeBranchId == null) {
      return;
    }
    void loadWorkingMemoryList();
    void fetchTaskFsm(activeChatId, activeBranchId)
      .then((s) => setTaskFsm(s))
      .catch(() => setTaskFsm(null));
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

  const openWeatherPopup = useCallback(async () => {
    setWeatherLoading(true);
    setWeatherError(null);
    setWeatherPopupOpen(true);
    try {
      const data = await fetchIrkutskWeather();
      setWeatherData(data);
      setLastWeatherAt(Date.now());
    } catch (e: unknown) {
      setWeatherError(e instanceof Error ? e.message : String(e));
    } finally {
      setWeatherLoading(false);
    }
  }, []);

  useEffect(() => {
    // Автопоказ раз в час, пока приложение открыто.
    if (activeChatId == null) return;
    const hourMs = 60 * 60 * 1000;
    const id = window.setInterval(() => {
      const now = Date.now();
      if (now - lastWeatherAt >= hourMs) {
        void openWeatherPopup();
      }
    }, 60 * 1000);
    return () => window.clearInterval(id);
  }, [activeChatId, lastWeatherAt, openWeatherPopup]);

  const runPipelineDemo = useCallback(async () => {
    setPipelineLoading(true);
    setPipelineError(null);
    setPipelineData(null);
    try {
      const out = await runMcpEduPipeline({
        query: pipelineQuery,
        output_file: pipelineFile,
        overwrite: true,
      });
      setPipelineData(out);
    } catch (e: unknown) {
      setPipelineError(e instanceof Error ? e.message : String(e));
    } finally {
      setPipelineLoading(false);
    }
  }, [pipelineFile, pipelineQuery]);

  const runRagLab = useCallback(async () => {
    setRagLoading(true);
    setRagError(null);
    setRagResult(null);
    try {
      const amRaw = ragAnswerMinScore.trim();
      const answer_min_score =
        amRaw === "" ? undefined : Number.parseFloat(amRaw);
      const out = await runRagQuery({
        question: ragQuestion,
        mode: ragMode,
        strategy: ragStrategy,
        rewrite_mode: ragRewriteMode,
        rerank_mode: ragRerankMode,
        top_k_before: Math.max(1, parseInt(ragTopKBefore || "20", 10) || 20),
        top_k_after: Math.max(1, parseInt(ragTopKAfter || "5", 10) || 5),
        sim_threshold: Number.parseFloat(ragThreshold || "0.12") || 0.12,
        answer_min_score:
          answer_min_score !== undefined && !Number.isNaN(answer_min_score) ? answer_min_score : undefined,
        max_context_chars: Math.max(800, parseInt(ragMaxContext || "6000", 10) || 6000),
        force_local: ragForceLocal,
      });
      setRagResult(out);
    } catch (e: unknown) {
      setRagError(e instanceof Error ? e.message : String(e));
    } finally {
      setRagLoading(false);
    }
  }, [
    ragAnswerMinScore,
    ragForceLocal,
    ragMaxContext,
    ragMode,
    ragQuestion,
    ragRerankMode,
    ragRewriteMode,
    ragStrategy,
    ragThreshold,
    ragTopKAfter,
    ragTopKBefore,
  ]);

  const runRagBenchmarkUi = useCallback(async () => {
    setRagBenchLoading(true);
    setRagBenchError(null);
    setRagBenchResult(null);
    try {
      const out = await runRagBenchmark({
        strategy: ragStrategy,
        top_k_before: Math.max(1, parseInt(ragTopKBefore || "20", 10) || 20),
        top_k_after: Math.max(1, parseInt(ragTopKAfter || "5", 10) || 5),
        sim_threshold: Number.parseFloat(ragThreshold || "0.12") || 0.12,
        force_local: ragForceLocal,
      });
      setRagBenchResult(out);
    } catch (e: unknown) {
      setRagBenchError(e instanceof Error ? e.message : String(e));
    } finally {
      setRagBenchLoading(false);
    }
  }, [ragForceLocal, ragStrategy, ragThreshold, ragTopKAfter, ragTopKBefore]);

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
    setIsStreaming(true);
    setCanResumeAnswer(false);
    setStreamStatus("Запрос отправлен...");
    setStreamPhase("request");
    setInput("");
    const optimisticUser: Message = {
      id: -Date.now(),
      role: "user",
      content: text,
      summarized: false,
    };
    const optimisticAssistantId = -(Date.now() + 1);
    const optimisticAssistant: Message = {
      id: optimisticAssistantId,
      role: "assistant",
      content: "",
      summarized: false,
    };
    setMessages((m) => [...m, optimisticUser, optimisticAssistant]);
    try {
      const ctrl = new AbortController();
      streamAbortRef.current = ctrl;
      await sendMessageStream(activeChatId, activeBranchId, text, (event) => {
        if (event.type === "delta") {
          setStreamPhase("answer");
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === optimisticAssistantId
                ? { ...msg, content: msg.content + event.delta }
                : msg,
            ),
          );
          return;
        }
        if (event.type === "status") {
          setStreamStatus(event.message || "Обработка...");
          const p = event.phase as StreamPhase;
          if (
            p === "request" ||
            p === "facts" ||
            p === "wm_merge" ||
            p === "tools" ||
            p === "answer"
          ) {
            setStreamPhase(p);
          }
          return;
        }
        if (event.type === "stopped") {
          setStreamStatus("Остановлено");
          setStreamPhase("stopped");
          return;
        }
        if (event.type === "error") {
          throw new Error(event.message);
        }
      }, ctrl.signal);
      setStreamPhase("done");
      setStreamStatus("Готово");
      const msgs = await fetchMessages(activeChatId, activeBranchId);
      setMessages(msgs);
      await loadChats();
      const br = await fetchBranches(activeChatId);
      setBranches(br);
      if (showMemoryPanel) {
        void loadWorkingMemoryList();
        if (memoryTab === "long") void loadLongTermList();
        if (memoryTab === "invariants") void loadInvariantList();
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      if (msg.includes("aborted") || msg.includes("AbortError")) {
        const msgs = await fetchMessages(activeChatId, activeBranchId);
        setMessages(msgs);
      } else {
        setError(msg);
        setMessages((m) =>
          m.filter((x) => x.id !== optimisticUser.id && x.id !== optimisticAssistantId),
        );
      }
    } finally {
      streamAbortRef.current = null;
      setStreamStatus("");
      setStreamPhase("idle");
      setIsStreaming(false);
      setLoading(false);
    }
  };

  const handleStopGenerate = async () => {
    if (activeChatId == null || activeBranchId == null) return;
    try {
      await stopMessageStream(activeChatId, activeBranchId);
      setStreamStatus("Останавливаю...");
      setStreamPhase("stopped");
    } catch {
      /* ignore stop errors */
    }
    streamAbortRef.current?.abort();
  };

  const handleStopAndPause = async () => {
    if (activeChatId == null || activeBranchId == null) return;
    try {
      const state = await stopAndPauseMessageStream(
        activeChatId,
        activeBranchId,
        "Пауза пользователем во время генерации",
      );
      setTaskFsm(state);
      setCanResumeAnswer(true);
      setStreamStatus("Останавливаю и ставлю на паузу...");
      setStreamPhase("stopped");
    } catch {
      setStreamStatus("Останавливаю...");
      setStreamPhase("stopped");
    }
    streamAbortRef.current?.abort();
  };

  const handleResumeAnswer = async () => {
    if (activeChatId == null || activeBranchId == null) return;
    setError(null);
    setLoading(true);
    setIsStreaming(true);
    setStreamStatus("Продолжаю ответ...");
    setStreamPhase("answer");
    try {
      const ctrl = new AbortController();
      streamAbortRef.current = ctrl;
      await resumeMessageStream(activeChatId, activeBranchId, (event) => {
        if (event.type === "delta") {
          setMessages((prev) => {
            for (let i = prev.length - 1; i >= 0; i -= 1) {
              if (prev[i].role === "assistant") {
                const next = [...prev];
                next[i] = { ...next[i], content: next[i].content + event.delta };
                return next;
              }
            }
            return prev;
          });
          return;
        }
        if (event.type === "status") {
          setStreamStatus(event.message || "Продолжаю...");
          return;
        }
        if (event.type === "error") {
          throw new Error(event.message);
        }
      }, ctrl.signal);
      const msgs = await fetchMessages(activeChatId, activeBranchId);
      setMessages(msgs);
      await loadChats();
      const br = await fetchBranches(activeChatId);
      setBranches(br);
      setCanResumeAnswer(false);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      if (!msg.includes("aborted") && !msg.includes("AbortError")) {
        setError(msg);
      }
    } finally {
      streamAbortRef.current = null;
      setStreamStatus("");
      setStreamPhase("idle");
      setIsStreaming(false);
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

  const filterInvariantItems = (items: Invariant[]) => {
    const q = memorySearch.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (it) =>
        it.title.toLowerCase().includes(q) ||
        it.statement.toLowerCase().includes(q) ||
        it.category.toLowerCase().includes(q),
    );
  };

  const detectValueType = (raw: string) => {
    const t = raw.trim();
    if (!t) return "empty";
    if (t === "true" || t === "false") return "boolean";
    if (!Number.isNaN(Number(t)) && t !== "") return "number";
    try {
      const parsed: unknown = JSON.parse(t);
      if (parsed !== null && typeof parsed === "object") return "json";
    } catch {
      /* ignore */
    }
    return "text";
  };

  const getTypeStats = (items: MemoryItem[]) => {
    const counts: Record<string, number> = {
      text: 0,
      number: 0,
      boolean: 0,
      json: 0,
      empty: 0,
    };
    for (const it of items) {
      const kind = detectValueType(it.value);
      counts[kind] = (counts[kind] ?? 0) + 1;
    }
    return counts;
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
      }
      params.user_id = editTripleUserId.trim() || DEFAULT_PROFILE_USER_ID;
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
      else if (memoryTab === "long") await loadLongTermList();
      else await loadInvariantList();
      if (activeChatId != null && activeBranchId != null) {
        const s = await fetchTaskFsm(activeChatId, activeBranchId);
        setTaskFsm(s);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handlePauseTask = async () => {
    if (activeChatId == null || activeBranchId == null) return;
    setLoading(true);
    setError(null);
    try {
      const s = await pauseTaskFsm(activeChatId, activeBranchId);
      setTaskFsm(s);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const handleResumeTask = async () => {
    if (activeChatId == null || activeBranchId == null) return;
    setLoading(true);
    setError(null);
    try {
      const s = await resumeTaskFsm(activeChatId, activeBranchId);
      setTaskFsm(s);
      if (canResumeAnswer) {
        await handleResumeAnswer();
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
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
    const uid = memoryLtUserId.trim() || DEFAULT_PROFILE_USER_ID;
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
    const uid = memoryLtUserId.trim() || DEFAULT_PROFILE_USER_ID;
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
    const uid = memoryLtUserId.trim() || DEFAULT_PROFILE_USER_ID;
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

  const handleAddInvariant = async () => {
    const uid = memoryLtUserId.trim() || DEFAULT_PROFILE_USER_ID;
    const title = newInvTitle.trim();
    const statement = newInvStatement.trim();
    if (!title || !statement) return;
    setLoading(true);
    setError(null);
    try {
      await createInvariant(uid, {
        category: newInvCategory,
        severity: newInvSeverity,
        title,
        statement,
      });
      setNewInvTitle("");
      setNewInvStatement("");
      await loadInvariantList();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteInvariant = async (id: number) => {
    const uid = memoryLtUserId.trim() || DEFAULT_PROFILE_USER_ID;
    if (!window.confirm("Удалить этот инвариант?")) return;
    setLoading(true);
    setError(null);
    try {
      await deleteInvariant(uid, id);
      await loadInvariantList();
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
        const uid = memoryLtUserId.trim() || DEFAULT_PROFILE_USER_ID;
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

  const currentMemoryItems =
    memoryTab === "working"
      ? workingMemoryItems
      : memoryTab === "long"
        ? longTermItems
        : [];
  const filteredMemoryItems = filterMemoryItems(currentMemoryItems);
  const memoryTypeStats = getTypeStats(currentMemoryItems);
  const filteredInvariantItems = filterInvariantItems(invariantItems);
  const phaseStep = (() => {
    if (streamPhase === "request") return 0;
    if (streamPhase === "facts" || streamPhase === "wm_merge" || streamPhase === "tools") return 1;
    if (streamPhase === "answer") return 2;
    if (streamPhase === "done") return 3;
    if (streamPhase === "stopped") return 2;
    return -1;
  })();
  const phaseTwoLabel = (() => {
    const strategy = activeBranch?.memory_strategy ?? "summary";
    if (strategy === "sticky_facts") return "2. Sticky Facts";
    if (strategy === "triple_memory") return "2. Working/Tools";
    return "2. Контекст";
  })();

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
              <button
                type="button"
                className="btn"
                onClick={() => void openWeatherPopup()}
                disabled={loading || weatherLoading}
              >
                Погода (Иркутск)
              </button>
              <button
                type="button"
                className="btn"
                onClick={() => setPipelinePopupOpen(true)}
                disabled={loading || pipelineLoading}
              >
                MCP pipeline demo
              </button>
              <button
                type="button"
                className="btn"
                onClick={() => setRagLabOpen(true)}
                disabled={loading || ragLoading || ragBenchLoading}
              >
                RAG Lab
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
                    "Контекст собирается из short-term диалога, working memory ветки и long-term памяти пользователя. Если на сервере включён MCP (MCP_ENABLED), к тем же инструментам wm_* добавляются tools с подключённого MCP-сервера (например погода)."}
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
                  <label>
                    Short-term хвост (сообщений user+assistant)
                    <input
                      type="number"
                      min={1}
                      value={editTripleTail}
                      onChange={(e) => setEditTripleTail(e.target.value)}
                    />
                  </label>
                )}
                <label>
                  Профиль / user_id (инварианты для всех стратегий; long-term при triple)
                  <select
                    value={tripleProfileChoice}
                    onChange={(e) => {
                      const choice = e.target.value;
                      setTripleProfileChoice(choice);
                      const picked = memoryProfiles.find((p) => p.id === choice);
                      if (picked) setEditTripleUserId(picked.user_id);
                    }}
                  >
                    {memoryProfiles.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.title}
                      </option>
                    ))}
                    <option value="custom">Пользовательский (manual)</option>
                  </select>
                </label>
                {tripleProfileChoice === "custom" && (
                  <label>
                    User ID (manual)
                    <input
                      value={editTripleUserId}
                      onChange={(e) => setEditTripleUserId(e.target.value)}
                    />
                  </label>
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
              {isStreaming && streamStatus && (
                <div className="stream-progress" aria-live="polite">
                  <div className="stream-stepper">
                    <span className={phaseStep >= 0 ? "stream-step active" : "stream-step"}>
                      1. Отправка
                    </span>
                    <span className={phaseStep >= 1 ? "stream-step active" : "stream-step"}>
                      {phaseTwoLabel}
                    </span>
                    <span className={phaseStep >= 2 ? "stream-step active" : "stream-step"}>
                      3. Ответ
                    </span>
                    <span className={phaseStep >= 3 ? "stream-step active" : "stream-step"}>
                      4. Готово
                    </span>
                  </div>
                  <div className="hint">{streamStatus}</div>
                </div>
              )}
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
              {isStreaming && (
                <>
                  <button
                    type="button"
                    className="btn"
                    onClick={() => void handleStopGenerate()}
                  >
                    Стоп
                  </button>
                  <button
                    type="button"
                    className="btn"
                    onClick={() => void handleStopAndPause()}
                  >
                    Стоп + Пауза
                  </button>
                </>
              )}
              {!isStreaming && canResumeAnswer && (
                <button
                  type="button"
                  className="btn"
                  onClick={() => void handleResumeAnswer()}
                >
                  Продолжить ответ
                </button>
              )}
            </div>
            </div>
            {showMemoryPanel && activeBranchId != null && activeChatId != null && (
              <aside className="memory-panel" aria-label="Память ветки">
                <div className="memory-panel-head">
                  <h2>Память</h2>
                  <div className="memory-actions">
                    <button
                      type="button"
                      className="btn"
                      disabled={loading}
                      onClick={() => void refreshMemoryPanel()}
                    >
                      Обновить
                    </button>
                    <button
                      type="button"
                      className="btn"
                      disabled={loading || taskFsm?.stage === "paused"}
                      onClick={() => void handlePauseTask()}
                    >
                      Пауза
                    </button>
                    <button
                      type="button"
                      className="btn"
                      disabled={loading || taskFsm?.stage !== "paused"}
                      onClick={() => void handleResumeTask()}
                    >
                      Продолжить
                    </button>
                  </div>
                </div>
                {taskFsm && (
                  <div className="memory-fsm">
                    <div><strong>Этап:</strong> {taskFsm.stage}</div>
                    <div><strong>Шаг:</strong> {taskFsm.current_step || "—"}</div>
                    <div><strong>Ожидаемое действие:</strong> {taskFsm.expected_action || "—"}</div>
                  </div>
                )}
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
                  <button
                    type="button"
                    role="tab"
                    aria-selected={memoryTab === "invariants"}
                    className={memoryTab === "invariants" ? "active" : ""}
                    onClick={() => {
                      setMemoryTab("invariants");
                      setEditTarget(null);
                      void loadInvariantList();
                    }}
                  >
                    Инварианты
                  </button>
                </div>
                <div className="memory-panel-body">
                  <input
                    type="search"
                    className="memory-search"
                    placeholder={
                      memoryTab === "invariants"
                        ? "Поиск по заголовку, тексту, категории…"
                        : "Поиск по ключу или значению…"
                    }
                    value={memorySearch}
                    onChange={(e) => setMemorySearch(e.target.value)}
                  />
                  {(memoryTab === "working" || memoryTab === "long") && (
                  <div className="memory-stats">
                    <div className="memory-stats-row">
                      <span>Всего записей:</span>
                      <strong>{currentMemoryItems.length}</strong>
                    </div>
                    <div className="memory-stats-row">
                      <span>Показано по фильтру:</span>
                      <strong>{filteredMemoryItems.length}</strong>
                    </div>
                    <div className="memory-stats-types">
                      <span>Типы:</span>
                      <span className="chip">text: {memoryTypeStats.text}</span>
                      <span className="chip">number: {memoryTypeStats.number}</span>
                      <span className="chip">boolean: {memoryTypeStats.boolean}</span>
                      <span className="chip">json: {memoryTypeStats.json}</span>
                      <span className="chip">empty: {memoryTypeStats.empty}</span>
                    </div>
                  </div>
                  )}
                  {memoryTab === "invariants" && (
                  <div className="memory-stats">
                    <div className="memory-stats-row">
                      <span>Всего инвариантов:</span>
                      <strong>{invariantItems.length}</strong>
                    </div>
                    <div className="memory-stats-row">
                      <span>По фильтру:</span>
                      <strong>{filteredInvariantItems.length}</strong>
                    </div>
                  </div>
                  )}
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
                          Профиль
                          <select
                            value={ltProfileChoice}
                            onChange={(e) => {
                              const choice = e.target.value;
                              setLtProfileChoice(choice);
                              const picked = memoryProfiles.find((p) => p.id === choice);
                              if (picked) setMemoryLtUserId(picked.user_id);
                            }}
                          >
                            {memoryProfiles.map((p) => (
                              <option key={p.id} value={p.id}>
                                {p.title}
                              </option>
                            ))}
                            <option value="custom">Пользовательский (manual)</option>
                          </select>
                        </label>
                        {ltProfileChoice === "custom" && (
                          <label>
                            User ID (manual)
                            <input
                              value={memoryLtUserId}
                              onChange={(e) =>
                                setMemoryLtUserId(e.target.value)
                              }
                            />
                          </label>
                        )}
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
                  {memoryTab === "invariants" && (
                    <>
                      <p className="memory-hint">
                        Инварианты по <code>user_id</code> (таблица <code>invariants</code>), отдельно от
                        диалога. В запрос ассистенту подставляются из настроек ветки — поле «Профиль /
                        user_id» (тот же <code>user_id</code>, что для долговременной памяти).
                      </p>
                      <div className="memory-lt-user">
                        <label>
                          Профиль
                          <select
                            value={ltProfileChoice}
                            onChange={(e) => {
                              const choice = e.target.value;
                              setLtProfileChoice(choice);
                              const picked = memoryProfiles.find((p) => p.id === choice);
                              if (picked) setMemoryLtUserId(picked.user_id);
                            }}
                          >
                            {memoryProfiles.map((p) => (
                              <option key={p.id} value={p.id}>
                                {p.title}
                              </option>
                            ))}
                            <option value="custom">Пользовательский (manual)</option>
                          </select>
                        </label>
                        {ltProfileChoice === "custom" && (
                          <label>
                            User ID (manual)
                            <input
                              value={memoryLtUserId}
                              onChange={(e) =>
                                setMemoryLtUserId(e.target.value)
                              }
                            />
                          </label>
                        )}
                        <button
                          type="button"
                          className="btn primary"
                          disabled={loading}
                          onClick={() => void loadInvariantList()}
                        >
                          Загрузить
                        </button>
                      </div>
                      {invLoading && (
                        <p className="memory-status">Загрузка…</p>
                      )}
                      {invError && (
                        <div className="memory-err" role="alert">
                          {invError}
                        </div>
                      )}
                      {!invLoading &&
                        !invError &&
                        filteredInvariantItems.length === 0 && (
                          <p className="memory-empty">
                            Нет инвариантов для этого user_id.
                          </p>
                        )}
                      {filteredInvariantItems.length > 0 && (
                        <div className="memory-table-wrap">
                          <table className="memory-table">
                            <thead>
                              <tr>
                                <th>Категория</th>
                                <th>Строгость</th>
                                <th>Заголовок</th>
                                <th>Формулировка</th>
                                <th />
                              </tr>
                            </thead>
                            <tbody>
                              {filteredInvariantItems.map((row) => (
                                <tr key={row.id}>
                                  <td className="memory-key">{row.category}</td>
                                  <td className="memory-meta">{row.severity}</td>
                                  <td className="memory-key">{row.title}</td>
                                  <td className="memory-val">
                                    <span className="memory-val-text">
                                      {row.statement}
                                    </span>
                                  </td>
                                  <td className="memory-actions">
                                    <button
                                      type="button"
                                      className="btn"
                                      disabled={loading}
                                      onClick={() =>
                                        void handleDeleteInvariant(row.id)
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
                      )}
                      <details className="memory-add-details">
                        <summary>Добавить инвариант</summary>
                        <div className="memory-add">
                          <label>
                            Категория
                            <select
                              value={newInvCategory}
                              onChange={(e) =>
                                setNewInvCategory(e.target.value)
                              }
                            >
                              {INVARIANT_CATEGORY_OPTIONS.map((o) => (
                                <option key={o.value} value={o.value}>
                                  {o.label}
                                </option>
                              ))}
                            </select>
                          </label>
                          <label>
                            Строгость
                            <select
                              value={newInvSeverity}
                              onChange={(e) =>
                                setNewInvSeverity(e.target.value)
                              }
                            >
                              {INVARIANT_SEVERITY_OPTIONS.map((o) => (
                                <option key={o.value} value={o.value}>
                                  {o.label}
                                </option>
                              ))}
                            </select>
                          </label>
                          <input
                            placeholder="Краткий заголовок"
                            value={newInvTitle}
                            onChange={(e) => setNewInvTitle(e.target.value)}
                          />
                          <textarea
                            placeholder="Формулировка правила"
                            value={newInvStatement}
                            onChange={(e) =>
                              setNewInvStatement(e.target.value)
                            }
                          />
                          <button
                            type="button"
                            className="btn primary"
                            disabled={
                              loading ||
                              !newInvTitle.trim() ||
                              !newInvStatement.trim()
                            }
                            onClick={() => void handleAddInvariant()}
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
        {weatherPopupOpen && (
          <div className="modal-backdrop" role="presentation">
            <div className="modal">
              <h3>Погода в Иркутске</h3>
              <p className="hint">
                Автопоказ раз в час, пока открыт интерфейс агента. Можно открыть вручную кнопкой в тулбаре.
              </p>
              {weatherLoading && <p>Загрузка...</p>}
              {!weatherLoading && weatherError && (
                <div className="memory-err" role="alert">
                  {weatherError}
                </div>
              )}
              {!weatherLoading && !weatherError && weatherData && (
                <div className="weather-popup-grid">
                  <div><strong>Город:</strong> {weatherData.city}</div>
                  <div><strong>Температура:</strong> {weatherData.temperature_c}°C</div>
                  <div><strong>Ветер:</strong> {weatherData.wind_speed_kmh} км/ч</div>
                  <div><strong>Код погоды:</strong> {weatherData.weather_code}</div>
                  <div><strong>Локальное время:</strong> {weatherData.time_local}</div>
                  <div><strong>Источник:</strong> {weatherData.source}</div>
                </div>
              )}
              <div className="modal-actions">
                <button
                  type="button"
                  className="btn"
                  onClick={() => setWeatherPopupOpen(false)}
                >
                  Закрыть
                </button>
                <button
                  type="button"
                  className="btn primary"
                  onClick={() => void openWeatherPopup()}
                  disabled={weatherLoading}
                >
                  Обновить
                </button>
              </div>
            </div>
          </div>
        )}
        {pipelinePopupOpen && (
          <div className="modal-backdrop" role="presentation">
            <div className="modal modal-wide">
              <h3>MCP pipeline demo (Yandex)</h3>
              <p className="hint">
                Запускает инструменты MCP по шагам: search → summarize → saveToFile.
              </p>
              <label>
                Query (город из пресетов или lat,lon)
                <input
                  value={pipelineQuery}
                  onChange={(e) => setPipelineQuery(e.target.value)}
                  placeholder="Иркутск или 52.286974,104.305018"
                />
              </label>
              <label>
                Куда сохранить summarize JSON
                <input
                  value={pipelineFile}
                  onChange={(e) => setPipelineFile(e.target.value)}
                  placeholder="outputs/mcp_pipeline_summary.txt"
                />
              </label>
              {pipelineLoading && <p>Выполнение пайплайна...</p>}
              {!pipelineLoading && pipelineError && (
                <div className="memory-err" role="alert">
                  {pipelineError}
                </div>
              )}
              {!pipelineLoading && !pipelineError && pipelineData && (
                <div className="pipeline-grid">
                  <div className="pipeline-step">
                    <h4>1) search</h4>
                    <pre className="text">{pipelineData.search_raw}</pre>
                  </div>
                  <div className="pipeline-step">
                    <h4>2) summarize</h4>
                    <pre className="text">{pipelineData.summarize_raw}</pre>
                  </div>
                  <div className="pipeline-step">
                    <h4>3) saveToFile</h4>
                    <pre className="text">{pipelineData.save_raw}</pre>
                  </div>
                </div>
              )}
              <div className="modal-actions">
                <button
                  type="button"
                  className="btn"
                  onClick={() => setPipelinePopupOpen(false)}
                >
                  Закрыть
                </button>
                <button
                  type="button"
                  className="btn primary"
                  onClick={() => void runPipelineDemo()}
                  disabled={pipelineLoading || !pipelineQuery.trim()}
                >
                  Запустить
                </button>
              </div>
            </div>
          </div>
        )}
        {ragLabOpen && (
          <div className="modal-backdrop" role="presentation">
            <div className="modal modal-wide">
              <h3>RAG Lab</h3>
              <p className="hint">
                Запуск одиночного RAG-запроса и benchmark (10 вопросов): baseline vs improved.
              </p>
              <div className="pipeline-grid">
                <div className="pipeline-step">
                  <h4>Параметры запроса</h4>
                  <label>
                    Вопрос
                    <textarea
                      rows={3}
                      value={ragQuestion}
                      onChange={(e) => setRagQuestion(e.target.value)}
                    />
                  </label>
                  <div className="settings-row">
                    <label>
                      Mode
                      <select
                        value={ragMode}
                        onChange={(e) => setRagMode(e.target.value as "without_rag" | "with_rag" | "both")}
                      >
                        <option value="both">both</option>
                        <option value="without_rag">without_rag</option>
                        <option value="with_rag">with_rag</option>
                      </select>
                    </label>
                    <label>
                      Strategy
                      <select
                        value={ragStrategy}
                        onChange={(e) => setRagStrategy(e.target.value as "fixed" | "structured" | "all")}
                      >
                        <option value="structured">structured</option>
                        <option value="fixed">fixed</option>
                        <option value="all">all</option>
                      </select>
                    </label>
                    <label>
                      Rewrite
                      <select
                        value={ragRewriteMode}
                        onChange={(e) => setRagRewriteMode(e.target.value as "none" | "heuristic")}
                      >
                        <option value="heuristic">heuristic</option>
                        <option value="none">none</option>
                      </select>
                    </label>
                    <label>
                      Rerank
                      <select
                        value={ragRerankMode}
                        onChange={(e) => setRagRerankMode(e.target.value as "none" | "threshold" | "hybrid")}
                      >
                        <option value="hybrid">hybrid</option>
                        <option value="threshold">threshold</option>
                        <option value="none">none</option>
                      </select>
                    </label>
                  </div>
                  <div className="settings-row">
                    <label>
                      Top-K before
                      <input value={ragTopKBefore} onChange={(e) => setRagTopKBefore(e.target.value)} />
                    </label>
                    <label>
                      Top-K after
                      <input value={ragTopKAfter} onChange={(e) => setRagTopKAfter(e.target.value)} />
                    </label>
                    <label>
                      Similarity threshold
                      <input value={ragThreshold} onChange={(e) => setRagThreshold(e.target.value)} />
                    </label>
                    <label>
                      Answer min score (опц.)
                      <input
                        value={ragAnswerMinScore}
                        onChange={(e) => setRagAnswerMinScore(e.target.value)}
                        placeholder="как sim_threshold"
                      />
                    </label>
                    <label>
                      Max context chars
                      <input value={ragMaxContext} onChange={(e) => setRagMaxContext(e.target.value)} />
                    </label>
                  </div>
                  <label className="checkbox-row">
                    <input
                      type="checkbox"
                      checked={ragForceLocal}
                      onChange={(e) => setRagForceLocal(e.target.checked)}
                    />
                    Force local fallback (без внешнего LLM)
                  </label>
                  <div className="modal-actions">
                    <button
                      type="button"
                      className="btn primary"
                      onClick={() => void runRagLab()}
                      disabled={ragLoading || !ragQuestion.trim()}
                    >
                      {ragLoading ? "Выполняю..." : "Запустить Query"}
                    </button>
                    <button
                      type="button"
                      className="btn"
                      onClick={() => void runRagBenchmarkUi()}
                      disabled={ragBenchLoading}
                    >
                      {ragBenchLoading ? "Benchmark..." : "Запустить Benchmark"}
                    </button>
                  </div>
                </div>
                <div className="pipeline-step">
                  <h4>Результаты Query</h4>
                  {ragError && <div className="memory-err">{ragError}</div>}
                  {!ragError && !ragResult && <p className="hint">Пока нет результата.</p>}
                  {ragResult && (
                    <>
                      {ragResult.without_rag && (
                        <>
                          <h4>without_rag</h4>
                          <pre className="text">{ragResult.without_rag.answer}</pre>
                        </>
                      )}
                      {ragResult.with_rag && (
                        <>
                          <h4>with_rag</h4>
                          {ragResult.with_rag.dont_know && (
                            <p className="memory-err">
                              {ragResult.with_rag.dont_know_reason === "no_query_term_overlap"
                                ? `Вне домена индекса: вопрос не пересекается с содержимым репозитория (max overlap ${ragResult.with_rag.keyword_overlap_max ?? "—"}, требуется ≥${ragResult.with_rag.keyword_overlap_required ?? "—"}).`
                                : `Режим «не знаю» (${ragResult.with_rag.dont_know_reason ?? "?"}) — max_score ${ragResult.with_rag.relevance_max_score ?? "—"}, порог ${ragResult.with_rag.relevance_threshold ?? "—"}.`}
                            </p>
                          )}
                          <pre className="text">{ragResult.with_rag.answer}</pre>
                          <p className="hint">
                            {`rewritten: ${ragResult.with_rag.query_rewritten ?? ""} | before: ${
                              ragResult.with_rag.retrieved_before_count ?? 0
                            } -> after: ${ragResult.with_rag.retrieved_count ?? 0}`}
                            {` | quotes: ${(ragResult.with_rag.quotes ?? []).length}`}
                          </p>
                          {!ragResult.with_rag.dont_know && (
                            <>
                              <table className="rag-table">
                                <thead>
                                  <tr>
                                    <th>score</th>
                                    <th>rerank</th>
                                    <th>file</th>
                                    <th>section</th>
                                    <th>chunk_id</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {(ragResult.with_rag.sources ?? []).slice(0, 8).map((s) => (
                                    <tr key={s.chunk_id}>
                                      <td>{s.score.toFixed(4)}</td>
                                      <td>{(s.rerank_score ?? 0).toFixed(4)}</td>
                                      <td>{s.file}</td>
                                      <td>{s.section}</td>
                                      <td>{s.chunk_id}</td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                              {(ragResult.with_rag.quotes ?? []).length > 0 && (
                                <>
                                  <h4>Цитаты</h4>
                                  <table className="rag-table">
                                    <thead>
                                      <tr>
                                        <th>chunk_id</th>
                                        <th>текст</th>
                                      </tr>
                                    </thead>
                                    <tbody>
                                      {(ragResult.with_rag.quotes ?? []).slice(0, 12).map((q) => (
                                        <tr key={`${q.chunk_id}-${q.text.slice(0, 12)}`}>
                                          <td>{q.chunk_id}</td>
                                          <td className="text">{q.text}</td>
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                </>
                              )}
                            </>
                          )}
                          {ragResult.with_rag.dont_know && (
                            <p className="hint">
                              Источники и цитаты скрыты: модель перешла в безопасный режим «не знаю».
                            </p>
                          )}
                          {!ragResult.with_rag.dont_know && (
                            <>
                              <h4>Filtered Out</h4>
                              {(ragResult.with_rag.filtered_out ?? []).length === 0 ? (
                                <p className="hint">Нет отфильтрованных чанков для текущих параметров.</p>
                              ) : (
                                <table className="rag-table">
                                  <thead>
                                    <tr>
                                      <th>score</th>
                                      <th>file</th>
                                      <th>section</th>
                                      <th>chunk_id</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {(ragResult.with_rag.filtered_out ?? []).slice(0, 12).map((s) => (
                                      <tr key={s.chunk_id}>
                                        <td>{s.score.toFixed(4)}</td>
                                        <td>{s.file}</td>
                                        <td>{s.section}</td>
                                        <td>{s.chunk_id}</td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              )}
                            </>
                          )}
                        </>
                      )}
                    </>
                  )}
                </div>
                <div className="pipeline-step">
                  <h4>Benchmark</h4>
                  {ragBenchError && <div className="memory-err">{ragBenchError}</div>}
                  {!ragBenchError && !ragBenchResult && <p className="hint">Запустите benchmark для отчёта.</p>}
                  {ragBenchResult && (
                    <>
                      <p className="hint">{ragBenchResult.stdout}</p>
                      <p>
                        <strong>Report:</strong> {ragBenchResult.report_path}
                      </p>
                      <pre className="text">{ragBenchResult.report_preview}</pre>
                    </>
                  )}
                </div>
              </div>
              <div className="modal-actions">
                <button type="button" className="btn" onClick={() => setRagLabOpen(false)}>
                  Закрыть
                </button>
              </div>
            </div>
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
