# Мини-чат RAG: проверка сценариев

- DB: `/home/nout/projects/challenge/rag_index.db`
- Файл: `/home/nout/projects/challenge/docs/rag_mini_chat_scenarios.json`

## mcp_routing_deep_dive: Маршрутизация MCP и multi-server (12 сообщений)

  - turn 1: dont_know=True sources=0 goal_set=True
  - turn 2: dont_know=False sources=5 goal_set=True
  - turn 3: dont_know=False sources=5 goal_set=True
  - turn 4: dont_know=False sources=5 goal_set=True
  - turn 5: dont_know=False sources=5 goal_set=True
  - turn 6: dont_know=False sources=5 goal_set=True
  - turn 7: dont_know=False sources=5 goal_set=True
  - turn 8: dont_know=False sources=5 goal_set=True
  - turn 9: dont_know=False sources=5 goal_set=True
  - turn 10: dont_know=False sources=5 goal_set=True
  - turn 11: dont_know=False sources=5 goal_set=True
  - turn 12: dont_know=False sources=5 goal_set=True

- Цель/уточнения в памяти: **True**; ходов с источниками: **11/12**

## rag_pipeline_memory: RAG-индекс, чанки и анти-галлюцинации (12 сообщений)

  - turn 1: dont_know=True sources=0 goal_set=True
  - turn 2: dont_know=False sources=5 goal_set=True
  - turn 3: dont_know=False sources=5 goal_set=True
  - turn 4: dont_know=False sources=5 goal_set=True
  - turn 5: dont_know=False sources=2 goal_set=True
  - turn 6: dont_know=False sources=5 goal_set=True
  - turn 7: dont_know=False sources=5 goal_set=True
  - turn 8: dont_know=False sources=5 goal_set=True
  - turn 9: dont_know=False sources=5 goal_set=True
  - turn 10: dont_know=False sources=5 goal_set=True
  - turn 11: dont_know=False sources=5 goal_set=True
  - turn 12: dont_know=False sources=5 goal_set=True

- Цель/уточнения в памяти: **True**; ходов с источниками: **11/12**
