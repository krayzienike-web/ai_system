# Architecture Decision Records

Формат: контекст → решение → последствия. Новое решение — новый файл, старые не переписываются (меняется статус).

| ADR | Решение | Статус |
|-----|---------|--------|
| [0001](0001-modular-monolith.md) | Модульный монолит на Python/FastAPI + PostgreSQL | Предложено |
| [0002](0002-deterministic-analytics-llm-on-top.md) | Расчеты детерминированно, LLM только поверх результатов через tool use | Предложено |
| [0003](0003-multitenancy-rls.md) | Мультиарендность и роли: RBAC + scope + Postgres RLS | Предложено |
| [0004](0004-canonical-model-and-adapters.md) | Канонная модель данных + адаптеры источников (XLS сейчас, API потом) | Предложено |
| [0005](0005-llm-provider-abstraction.md) | LLM-провайдер: Claude API за тонким шлюзом | Принято |
| [0006](0006-tasks-execution-and-traceability.md) | Директора исполняют без оспаривания; быстрые задачи и трассировка до результата в ₽ | Принято |
