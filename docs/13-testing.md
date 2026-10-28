# 13. Тестирование: стратегия и реестр тест-кейсов

Документ отвечает на три вопроса: как проверяем продукт, что уже покрыто тестами и что еще нет.
Реестр ниже — источник истины для тест-кейсов. Новое требование или исправленный баг → строка в реестре
и тест, который на нее ссылается. Реестр ведет агент-тестировщик (`.claude/agents/test-engineer.md`) и сверяет
его с кодом на каждом этапе.

## Уровни и инструменты

| Уровень | Что проверяет | Инструмент | Где | Запуск |
|---------|---------------|------------|-----|--------|
| Модульные (бэкенд) | формулы движка, разбор файлов, правила работы с находками | pytest | `backend/tests/test_*_units.py`, `test_import_parsing.py`, `test_recipes.py`, `test_period.py`, `test_work_stage.py` | `make test` |
| Интеграционные (бэкенд) | API + PostgreSQL + RLS: доступы, изоляция, импорт, движок на демо-сети | pytest + TestClient, тестовая БД `franchise_test` | остальные `backend/tests/` | `make test` |
| Модульные (фронтенд) | форматирование чисел и дат, периоды, правила доступа демо-режима, проверка ввода | Vitest | `frontend/src/**/*.test.ts` | `make test` (`npm test`) |
| Сквозные (e2e) | сценарии пользователя в браузере на демо-сборке | Playwright | `frontend/e2e/*.spec.ts` | `make e2e` |

Все четыре уровня идут в CI на каждый push (`.github/workflows/ci.yml`, задачи `backend`, `frontend`, `e2e`).

**Покрытие бэкенда** меряется на каждом прогоне, порог — 90 % строк и ветвлений (`pyproject.toml`,
`[tool.coverage]`). Ниже порога CI красный. На 28.10.2026 (после ревью этапа 4) — 93 % (240 тестов бэкенда, 25 — фронтенда, 16 e2e). Слабые места:

| Модуль | Покрытие | Что не покрыто |
|--------|----------|----------------|
| `chat/service.py` | 83 % | редкие вопросы чата (нет данных, неизвестная находка) |
| `insights/sources.py` | 87 % | «Документы» у находок M4 «перед инвентаризацией» и пропуска продаж; подсказка поставщика у накладных без него |
| `overview/trend.py` | 90 % | запись недели без находок и повторная запись той же недели |
| `tasks/service.py` | 89 % | редкие ошибки назначения |
| `analytics/verify.py` | 89 % | ветки сверки на неполных данных |
| `insights/review.py` | 89 % | ошибки вердиктов («нет находки», повторное подтверждение) |
| `demo/snapshot.py`, `openapi.py` | 16 %, 0 % | служебные: работают в `make demo-snapshot` и `make api-types`, проверяются в CI их результатом |

`app/cli.py` (служебные команды) в покрытие не входит.

## Правила

- **Цифры считает код** (принцип 1): у каждой формулы движка есть модульный тест с расчетом вручную в комментарии.
- **Изоляция** (принцип 2): у каждого нового endpoint есть тест на чужой ресторан и чужую сеть (`TC-ISO-*`).
  Демо-режим соблюдает те же правила, это проверяет `frontend/src/api/demo.test.ts`.
- **Баг → тест**: исправление начинается с теста, который его воспроизводит.
- **Демо-сеть — эталон**: 12 заложенных аномалий (docs/11) движок должен находить. Число находок на демо — в `TC-ENG-10`.
- e2e работают на демо-сборке (без сервера), чтобы проверять ровно то, что видят по ссылке на прототип.
  Сценарии с настоящим сервером проверяются интеграционными тестами API.

## Реестр тест-кейсов

Статус: ✅ — автотест есть, 🟡 — частично, ⬜ — нет (в плане).

### Вход и сессия (AUTH)

| ID | Требование | Тест | Статус |
|----|------------|------|--------|
| TC-AUTH-01 | Вход по e-mail и паролю, e-mail без учета регистра | `test_auth.py::test_login_and_me_for_director`, `test_login_is_case_insensitive_on_email` | ✅ |
| TC-AUTH-02 | Неверный пароль и неизвестный e-mail неотличимы | `test_wrong_password_and_unknown_email_look_the_same` | ✅ |
| TC-AUTH-03 | Отключенный пользователь не входит, его токен перестает работать | `test_inactive_user_cannot_login_and_token_stops_working` | ✅ |
| TC-AUTH-04 | Обновление токена; access-токен не годится как refresh | `test_refresh_flow`, `test_access_token_is_not_a_refresh_token` | ✅ |
| TC-AUTH-05 | Токен с чужим тенантом и мусорный токен отклоняются | `test_token_with_foreign_tenant_claim_is_rejected`, `test_missing_or_garbage_token` | ✅ |
| TC-AUTH-06 | Вход записывается в аудит | `test_login_is_audited` | ✅ |
| TC-AUTH-07 | Сбой сети или 500 не выбрасывает из приложения, выход только при 401 | — | ⬜ |
| TC-AUTH-08 | Ротация refresh-токена, ограничение частоты входа | — | ⬜ (бэклог, до пилота) |
| TC-AUTH-09 | Проверка живости сервиса без входа | `test_auth.py::test_health` | ✅ |
| TC-AUTH-10 | Без `FAI_ENV` настройки считаются рабочими и не принимают dev-секрет JWT; dev и test — принимают | `test_config.py` | ✅ |

### Изоляция данных (ISO)

| ID | Требование | Тест | Статус |
|----|------------|------|--------|
| TC-ISO-01 | RLS включен на каждой таблице, роль приложения его не обходит | `test_isolation_db.py::test_rls_enabled_on_every_public_table`, `test_app_role_cannot_bypass_rls` | ✅ |
| TC-ISO-02 | Без контекста не видно ничего; директор видит свой ресторан; УК — только свою сеть | `test_no_context_sees_nothing`, `test_director_context_sees_own_rows_only`, `test_hq_context_limited_to_its_tenant` | ✅ |
| TC-ISO-03 | Нельзя писать в чужую сеть и вне своего ресторана | `test_cannot_write_into_another_tenant`, `test_director_cannot_create_restaurant_outside_scope`, `test_role_scope_constraint` | ✅ |
| TC-ISO-04 | Рестораны и пользователи через API — только своей сети, управляет администратор УК | `test_isolation_api.py` (11 тестов) | ✅ |
| TC-ISO-05 | Находки и задачи: директор — только свои, без сетевых; чужая сеть — 404 | `test_work_loop.py::test_director_sees_only_own_findings_and_no_network_wide`, `test_hq_sees_all_findings_of_own_tenant_only`, `test_director_sees_only_own_tasks`, `test_other_tenant_cannot_touch_checks_or_tasks` | ✅ |
| TC-ISO-06 | Загрузки, соответствия названий, свежесть данных — в границах ресторана и сети | `test_imports_api.py::test_director_uploads_own_restaurant_and_sees_only_own_batches`, `test_freshness_per_restaurant_and_isolation`, `test_matching_rules_and_isolation`, `test_alias_visibility_and_rights`, `test_isolation_db.py::test_director_cannot_change_or_delete_network_wide_name_matches` | ✅ |
| TC-ISO-07 | Находки на проверке, их сверка, вердикт и параметры движка не видны чужой сети; директор не видит находку на проверке | `test_isolation_api.py::test_engine_findings_and_settings_stay_within_the_tenant` | ✅ |
| TC-ISO-08 | Демо-режим соблюдает те же правила: директор не трогает чужие файлы и данные сети, не видит непроверенное | `frontend/src/api/demo.test.ts` | ✅ |
| TC-ISO-09 | Директор не может изменить находку на проверке и увидеть ее через задачу (уровень БД); не может вернуть свою находку на проверку | `test_isolation_db.py::test_director_can_neither_change_a_finding_under_review_nor_see_it_through_a_task` | ✅ |
| TC-ISO-10 | Просмотр, сопоставление, публикация, повторная обработка и откат чужого файла (другой ресторан, другая сеть) — 404 и ничего не меняют; соответствие названий чужая сеть не меняет и не удаляет | `test_imports_api.py::test_another_restaurant_or_network_cannot_match_reprocess_or_roll_back_a_file` | ✅ |
| TC-ISO-11 | Директор читает, но не может записать сетевые KPI, тренд и журнал пересчетов (уровень БД) | `test_isolation_db.py::test_director_reads_but_cannot_write_network_kpis_trend_and_runs` | ✅ |
| TC-ISO-12 | Новые endpoint в границах сети и ресторана: чат по чужой находке, напоминание и тиражирование из чужой сети — 404; цены других ресторанов в таблице находки M3 директору не уходят (деталь, список, доска находок) | `test_overview.py::test_new_endpoints_keep_to_the_tenant_and_the_restaurant`, `test_a_director_gets_an_m3_finding_without_other_restaurants_prices` | ✅ |
| TC-ISO-13 | Действия с задачами и проверками по id: старт и чек-лист чужой задачи, задача по чужой находке, черновик, предложение, запуск и отклонение проверки чужой сети — 404, ничего не меняется; отчет руководителю и счетчики чужой сети не считают нашу | `test_work_loop.py::test_work_actions_on_another_restaurant_or_network_are_not_found` | ✅ |
| TC-ISO-14 | Журнал аудита для приложения — только добавление и чтение | `test_isolation_db.py::test_the_application_can_only_add_to_the_audit_log` | ✅ |
| TC-ISO-15 | Движок не работает вне контекста RLS своей сети (под владельцем или в контексте чужой сети) и пишет только строки своей сети | `test_engine_store.py::test_the_engine_refuses_to_run_outside_the_networks_context` (и под ролью, обходящей RLS); строки чужой сети остаются — `test_stale_findings_go_only_if_nobody_has_worked_on_them` | ✅ |
| TC-ISO-16 | Рабочая сборка фронтенда не содержит демо-снимок, демо-логины и пароль | CI: `npm run check:bundle` (`frontend/scripts/check-bundle.mjs`) | ✅ |
| TC-ISO-17 | Маршруты этапа 4 — для чужого ресторана и чужой сети: «Документы» (`/findings/{id}/sources`) по правилам карточки — директору только своя проверенная находка, не чужой ресторан, не сетевая и не ждущая проверки, чужой сети — 404; «Сеть» — только УК, матрица и переплаты — только своей сети и только проверенные; «Пересчитать» — только администратор УК, пересчет чужой сети не трогает свои находки и пересчеты. Прототип — так же: находка, отправленная на проверку, закрывает директору и ее документы | `test_isolation_api.py::test_stage_4_endpoints_stay_within_the_restaurant_and_the_network`; `demo.test.ts` «opens «Документы» by the card's rules» | ✅ |
| TC-ISO-18 | Инструмент ассистента работает в своей сессии: только чтение, RLS пользователя (директор видит свой ресторан), неизвестный пользователь — отказ | `test_isolation_db.py::test_a_tool_call_gets_its_own_read_only_session_under_the_users_rls` | ✅ |
| TC-ISO-19 | Обход всех маршрутов API из схемы OpenAPI: объекты чужой сети по id (находка, задача, проверка, файл, сопоставление, ресторан) — только 403/404 для администратора УК и директора; списки и экраны не содержат id и названий чужой сети, у директора — id других ресторанов; записи со ссылкой на чужую находку отклоняются; новый маршрут без группы роняет тест | `test_isolation_routes.py` | ✅ |

### Импорт данных (IMP)

| ID | Требование | Тест | Статус |
|----|------------|------|--------|
| TC-IMP-01 | Разбор CSV (cp1251, `;`) и «красивых» XLSX с заголовками и итогами; номера строк как в файле | `test_import_parsing.py` (11 тестов) | ✅ |
| TC-IMP-02 | Единицы приводятся к базовой; неизвестные и несовместимые — ошибка строки | `test_units_are_converted_to_base_and_unknown_or_incompatible_units_are_errors` | ✅ |
| TC-IMP-03 | Тип файла узнается по заголовку; шаблоны описаны для интерфейса | `test_imports_api.py::test_file_type_is_recognised_without_a_template`, `test_templates_are_described_for_the_ui` | ✅ |
| TC-IMP-04 | Отчет об ошибках по строкам; файл с ошибками не публикуется | `test_report_lists_errors_by_row_and_failed_file_cannot_be_published` | ✅ |
| TC-IMP-05 | Идемпотентность: публикация заменяет период, дубликат файла отклоняется, откат убирает ровно этот файл | `test_publish_replaces_the_period_and_duplicate_files_are_refused`, `test_rollback_removes_exactly_the_batch` | ✅ |
| TC-IMP-06 | Незнакомые названия сопоставляются один раз и запоминаются; исправление пересчитывает файлы | `test_unknown_names_are_matched_once_and_remembered`, `test_wrong_match_is_fixed_and_files_are_reprocessed`, `test_reprocess_applies_the_fixed_match`; соответствие от УК — на всю сеть: `test_hq_admin_match_applies_to_the_whole_network` | ✅ |
| TC-IMP-07 | Справочники сети загружает только УК | `test_reference_data_is_hq_only` | ✅ |
| TC-IMP-08 | Перемещения хранятся один раз и видны обоим ресторанам | `test_transfers_are_stored_once_and_seen_by_both_restaurants` | ✅ |
| TC-IMP-09 | Синхронизация названий 1С:ERP — iiko и контрактные цены | `test_erp_iiko_sync_collapses_names_and_contract_prices_load` | ✅ |
| TC-IMP-10 | Демо-сеть грузится через тот же конвейер с RLS | `test_demo_network_loads_through_the_pipeline_with_rls` | ✅ |
| TC-IMP-11 | Пересекающиеся файлы: более поздний заменяет свои дни; откат возвращает дни раннего, пересчет раннего не затирает поздний | `test_overlapping_files_later_replaces_and_rollback_restores`, `test_rolling_back_an_earlier_file_keeps_what_a_later_one_replaced` | ✅ |
| TC-IMP-12 | Двойное нажатие «Опубликовать» не задваивает строки | `test_publishing_twice_at_once_writes_the_rows_once` | ✅ |
| TC-IMP-13 | e2e: загрузка → сопоставление → публикация → свежесть данных | — | ⬜ |
| TC-IMP-14 | Повторная обработка обновляет число строк и использованные соответствия в отчете о загрузке | `test_imports_api.py::test_reprocess_applies_the_fixed_match` | ✅ |

### Справочники, нормы, периоды (CAT, NORM, PER)

| ID | Требование | Тест | Статус |
|----|------------|------|--------|
| TC-CAT-01 | Техкарты с полуфабрикатами раскладываются до сырья, циклы отклоняются | `test_recipes.py`, `test_imports_api.py::test_recipe_cycle_through_semi_finished_products_is_refused` | ✅ |
| TC-CAT-02 | Подсказки сопоставления: правильный товар первым, чужое не предлагается | `test_matching.py`, `test_demo_generator.py::test_names_from_another_system_are_suggested_correctly` | ✅ |
| TC-CAT-03 | Поставщик и товар с одинаковым названием сопоставляются независимо (интерфейс) | — | ⬜ |
| TC-NORM-01 | Нормы по умолчанию, права на изменение, проверка значений | `test_norms.py` | ✅ |
| TC-NORM-02 | Причины списания из выгрузки сводятся к стандартным | `test_reasons_of_an_export_map_to_standard_ones`, `test_import_classifies_write_off_reasons_and_warns_about_unknown` | ✅ |
| TC-PER-01 | Периоды: недели пн–вс, последний полный месяц и квартал (сравнение с предыдущим), свой диапазон включительно; интерфейс берет готовые периоды с сервера (`/overview/context`), сам не считает | `test_period.py`, `test_overview.py::test_overview_screens_follow_the_access_rules` | ✅ |
| TC-PER-02 | «С последней инвентаризации»: со дня после нее по вчера; у сети — после самой ранней из последних инвентаризаций ресторанов, у директора — своего ресторана; без инвентаризаций периода нет в списке, запрос — 422 | `test_period.py::test_since_the_last_count_runs_from_the_day_after_it_to_yesterday`, `test_period.py::test_since_the_last_count_needs_a_day_of_data_and_at_most_a_year` (инвентаризация вчера — 422, позавчера — один день, не длиннее 366 дней), `test_overview.py::test_since_the_last_count_and_the_quarter_in_the_picker_and_the_report` | ✅ |

### Аналитический движок (ENG)

| ID | Требование (docs/12) | Тест | Статус |
|----|----------------------|------|--------|
| TC-ENG-01 | M1: расход по техкартам с полуфабрикатами, перемещениями и списаниями | `test_analytics.py::test_m1_arithmetic_with_semi_finished_products_transfers_and_write_offs` | ✅ |
| TC-ENG-02 | M1: правила — устаревшая техкарта по сети, выброс, порог существенности | `test_m1_rules_network_pattern_outlier_and_materiality` | ✅ |
| TC-ENG-03 | M2: фудкост блюда выше цели, причина, рекомендованная цена | `test_m2_dish_food_cost_above_target_names_the_cause` | ✅ |
| TC-ENG-04 | M2: бесплатные порции и блюда без цены не ломают пересчет | там же | ✅ |
| TC-ENG-05 | M3: переплата против сети с поставщиком; контракт; рост по всей сети | `test_m3_overpay_against_the_network_with_the_supplier_named`, `test_m3_contract_prices_and_network_growth` | ✅ |
| TC-ENG-06 | Формулы: медиана, robust z с нижней границей, «в месяц», округление цены, себестоимость с запасными вариантами | `test_analytics_units.py` | ✅ |
| TC-ENG-07 | Параметры: перевод единиц (75 % ↔ 0,75), значения сети поверх умолчаний, умолчания в допустимых границах | `test_analytics_units.py::test_params_*`, `test_every_default_lies_within_its_editable_range` | ✅ |
| TC-ENG-08 | Параметры задаются для своей сети и меняют находки; меняет только администратор | `test_engine_params_are_set_per_network_and_change_the_findings` | ✅ |
| TC-ENG-09 | Пересчет запускает только администратор УК | `test_engine_run_is_hq_admin_only` | ✅ |
| TC-ENG-10 | На демо-сети находятся все 16 заложенных проблем (18 находок), сверка проходит для каждой; повторный пересчет идемпотентен | `test_engine_finds_planted_problems_and_review_gates_directors` | ✅ |
| TC-ENG-11 | Движок не выдает две находки с одним ключом: пересчет с дублем ключа останавливается и ничего не меняет | `test_engine_store.py::test_two_findings_with_one_key_stop_the_run` | ✅ |
| TC-ENG-12 | Удаление устаревших находок не трогает находки с задачами, проверками, отклоненные, взятые в работу и закрытые, находки других модулей, ручные и чужой сети | `test_engine_store.py::test_stale_findings_go_only_if_nobody_has_worked_on_them` | ✅ |
| TC-ENG-13 | Пересчет на 100+ ресторанах укладывается во время | ручной замер 27.10.2026: 108 ресторанов, 221 тыс. строк продаж — 7 с ([ревью](reviews/2026-10-27-code-review.md)) | ✅ (замер, не в CI) |
| TC-ENG-14 | M1 сравнивает ресторан с сетью, когда у ресторанов свои дни инвентаризаций (Q15); слишком далекие периоды не сравниваются | `test_m1_compares_restaurants_counting_on_their_own_days` | ✅ |
| TC-ENG-15 | M1 показывает «Расход меньше техкарты» как риск качества без рублей; мелкое отклонение и малый товар — нет (E3) | `test_m1_shows_usage_below_the_recipe_as_a_quality_risk` | 🟡 (нет теста сверки по шагам) |
| TC-ENG-16 | M7 находит блюдо без техкарты и пропуск выгрузки ресторана; обычная пауза в закупках и загруженная техкарта — не находка; на демо-сети — обе заложенные аномалии, сверка проходит | `test_m7_dish_without_a_recipe_and_missing_exports`, `test_engine_finds_planted_problems_and_review_gates_directors` | ✅ |
| TC-ENG-17 | M4: списания перед инвентаризацией и пересорт; ровные списания и обычное расхождение — не находка | `test_m4_write_offs_before_counts_and_mixed_up_products` | ✅ |
| TC-ENG-18 | M5: списания выше сети и по дням недели; разовое списание и списания как у сети — не находка | `test_m5_write_offs_above_the_network_and_on_the_same_weekdays` | ✅ |
| TC-ENG-19 | M6: товар закончится до поставки; мелкие позиции — не находка | `test_m6_shortage_before_the_next_delivery` | ✅ |
| TC-ENG-20 | M4 «бумажные» и пропущенные пересчеты, M7 остаток по документам в минус; честный пересчет и минус из-за пропуска выгрузки — не находка | `test_m4_paper_and_overdue_counts_and_m7_books_below_zero`, демо-тест | ✅ |
| TC-ENG-21 | После публикации файла находки пересчитываются в фоне; журнал виден ролям своей сети и не виден чужой; в аудите — без человека | `test_runs.py::test_publishing_a_file_recomputes_the_findings` | ✅ |
| TC-ENG-22 | Загрузки присоединяются к ожидающему пересчету; пересчет выполняется один раз; ошибка движка записывается | `test_uploads_join_the_waiting_run_and_a_run_goes_once`, `test_a_failed_run_is_logged` | ✅ |
| TC-ENG-23 | С очередью задача уходит в воркер; без очереди или при ее недоступности — пересчет в процессе API | `test_the_queue_is_used_when_configured_and_falls_back_without_it`, `test_the_worker_runs_the_queued_run` | ✅ |
| TC-ENG-24 | Загрузка, присоединившаяся к ожидающему пересчету, держит его до своего коммита; зависший пересчет показывается и записывается прерванным | `test_runs.py::test_an_upload_joining_the_waiting_run_holds_it_until_its_data_is_committed`, `test_a_run_left_going_on_is_shown_and_then_written_as_interrupted` | ✅ |
| TC-ENG-25 | Сверка не падает на измененных данных и повторяет правила движка: M4 после отката инвентаризаций, M7 — техкарта заведена внутри окна | `test_check_of_a_pre_count_finding_after_the_counts_were_rolled_back`, `test_m7_dish_without_a_recipe_and_missing_exports` | ✅ |
| TC-ENG-26 | «Пересчитать» ставит пересчет в очередь (202), а не считает в запросе; нажатие при ждущем пересчете после загрузки делает его ручным | `test_analytics.py` (повторный пересчет), `test_runs.py::test_publishing_a_file_recomputes_the_findings`, `test_the_button_pressed_while_an_upload_waits_makes_the_run_manual`; прототип — как сервер: пересчет только у администратора УК (`demo.test.ts` «lets only the HQ admin press «Пересчитать»») | ✅ |

### Проверка находок (REV)

| ID | Требование (docs/12, «Проверка находок») | Тест | Статус |
|----|------------------------------------------|------|--------|
| TC-REV-01 | Путь находки: найдено → проверено (когда, кто) → в находках; виден с обеих сторон | `test_engine_finds_planted_problems_and_review_gates_directors`, `e2e/review.spec.ts` TC-REV-01 | ✅ |
| TC-REV-02 | Отклонение требует причину, а для «логики» и «другого» — описание | там же, `e2e/review.spec.ts` TC-REV-02, `demo.test.ts` | ✅ |
| TC-REV-03 | Директор не видит проверку и непроверенные находки | там же, `e2e/review.spec.ts` TC-REV-03 | ✅ |
| TC-REV-04 | Сверка с загруженными данными проходит для всех находок демо-сети; сетевые находки M1 и «Цена выше договорной» пересчитываются из строк | `test_engine_finds_planted_problems_and_review_gates_directors`, `test_erp_iiko_sync_collapses_names_and_contract_prices_load` | ✅ |
| TC-REV-05 | Пересчет сохраняет решения; отклоненная находка не всплывает | там же | ✅ |
| TC-REV-06 | Если после новых данных эффект изменился больше порога, находка снова на проверке | там же | ✅ |
| TC-REV-07 | Непроверенная находка не попадает в отчет руководителю, по ней нельзя поставить задачу | там же | ✅ |
| TC-REV-08 | Комментарий проверяющего и его имя директору не показываются | там же, `demo.test.ts` | ✅ |
| TC-REV-09 | Ручную проверку можно выключить: находки сразу у директоров | `test_review_can_be_switched_off` | ✅ |

### Задачи, проверки изменений, отчет (WORK)

| ID | Требование (docs/05) | Тест | Статус |
|----|----------------------|------|--------|
| TC-WORK-01 | Этап работы по находке выводится из задач и проверок | `test_work_stage.py` (9 тестов), `test_work_loop.py::test_findings_carry_work_stage`, `test_stage_filter` | ✅ |
| TC-WORK-02 | УК ставит шаг директору, сетевая находка — всем директорам, чужому ресторану нельзя | `test_work_loop.py::test_hq_assigns_*`, `test_network_wide_finding_goes_to_every_director`, `test_finding_of_one_restaurant_cannot_go_to_another`, `test_director_takes_own_step_but_not_for_others`, `test_analyst_cannot_assign`, `test_due_date_must_be_reasonable` | ✅ |
| TC-WORK-03 | Директор выполняет свои задачи с отчетом; результат не пишет человек | `test_director_completes_with_report_and_result_is_pending`, `test_no_endpoint_lets_a_person_write_a_result`, `test_hq_does_not_execute_and_director_cannot_complete_others` | ✅ |
| TC-WORK-04 | Запуск и отклонение проверки изменений; правила вывода результата | `test_launch_sets_tasks_for_test_restaurants`, `test_reject_proposal`, `test_outcome_rules`, `test_check_result_reaches_its_done_tasks` | ✅ |
| TC-WORK-05 | Отчет руководителю: цифры, провалы, границы периода | `test_head_report_numbers_and_failures`, `test_head_report_period_excludes_earlier_events`; проверки и отчет — только УК: `test_checks_and_head_report_are_hq_only` | ✅ |

### Обзоры, действия и чат на сервере (OVR, ADR 0007)

| ID | Требование | Тест | Статус |
|----|------------|------|--------|
| TC-OVR-01 | KPI — доли выручки; среднее по сети взвешено по выручке | `test_overview.py::test_kpis_are_shares_of_revenue_and_the_network_is_weighted_by_it` | ✅ |
| TC-OVR-02 | «Это много?» словами: насколько и в какую сторону от сети или нормы | `test_scale_answer_says_how_far_and_which_way` | ✅ |
| TC-OVR-03 | Числа словами как на экранах (₽, склонения, %) | `test_words` | ✅ |
| TC-OVR-04 | Обзор сети, список ресторанов, «Моя неделя», счетчики: суммы из находок, права, чужой ресторан и чужая сеть — 404 | `test_overview_screens_follow_the_access_rules`, `test_findings_board_filters_counts_and_sums` | ✅ |
| TC-OVR-05 | Находка несет, как ее показать (шкала, состав, динамика, документы), и вывод «что получилось» | `test_findings_carry_how_they_are_shown` | ✅ |
| TC-OVR-06 | Чек-лист задачи отмечает только ее директор; напоминание — администратор УК и только по просроченной | `test_task_checklist_and_reminders` | ✅ |
| TC-OVR-07 | Черновик проверки от системы, предложение, тиражирование только сработавшей и один раз; чужая сеть — 404 | `test_checks_are_drafted_proposed_and_rolled_out` | ✅ |
| TC-OVR-08 | Отчет руководителю с трендом и проверками; чат не показывает директору другие рестораны | `test_head_report_and_chat` | ✅ |
| TC-OVR-09 | Тиражирование одновременно двумя запросами создает задачи один раз; вторая проверка той же находки — 422 | `test_checks_are_drafted_proposed_and_rolled_out` | ✅ |
| TC-OVR-10 | Черновик проверки для ресторана без выручки (нет периода инвентаризаций) не падает | `test_a_check_draft_for_a_restaurant_without_revenue_yet` | ✅ |
| TC-OVR-11 | Итоги, «в год», динамика и вывод словами приходят из API (экран не считает); чат отвечает про дефицит по находкам M6 | `test_trend_line_in_figures_and_words` (расчет вручную), `test_totals_a_year_and_the_trend_come_from_the_api`, `test_head_report_and_chat`, `test_demo_snapshot.py` | ✅ |
| TC-OVR-12 | «Откуда цифры» до документа: строки загруженных файлов по находке (накладные с номером, поставщиком и ценой; инвентаризации с начальной; списания; продажи), файл у каждой строки, общее вынесено над таблицей; директор — только свой ресторан, чужой ресторан, сетевая находка и чужая сеть — 404; находка без данных говорит, что документов нет | `test_overview.py::test_where_the_figures_come_from_down_to_the_invoice` | ✅ |
| TC-OVR-13 | «Сеть»: рестораны × процессы — каждая ячейка равна сумме открытых проверенных проблем ресторана по процессу, статус «в норме» только без проблем, итог строки и порядок по убыванию; вывод словами; фудкост и списания сети, переплаты поставщикам = проблемы по закупкам | `test_overview.py::test_restaurants_by_processes_and_the_networks_figures` | ✅ |
| TC-OVR-14 | «Документы» после ревью этапа 4: директор-получатель видит входящее перемещение без имени и файла отправителя; товар, которого нет в справочнике, — строк нет | `test_overview.py::test_documents_after_the_stage_4_review` | ✅ |
| TC-OVR-15 | «Документы» по видам находок: блюдо (M2) — продажи по дням × ресторан × блюдо (число строк и выручка строки сходятся с таблицей продаж, деньги — строкой `Decimal`, не больше 200 строк); списания (M5) — акты с причиной, число — как в таблице; поставки (M6) — накладные за 4 недели до конца периода и инвентаризации | `test_overview.py::test_documents_of_sales_write_offs_and_purchases_on_the_demo_network` | ✅ |

### Ассистент: шлюз к модели, инструменты, чат (AI, этап 5)

Модель в тестах — заглушка `FakeModel`: ключа Claude API пока нет (Q12), и тесты не должны зависеть от сети.

| ID | Требование | Тест | Статус |
|----|------------|------|--------|
| TC-AI-01 | Каждый вызов модели записан в `ai_runs`: пользователь, задача, промпт и его версия (и хэш), модель, запрос, ответ, токены, стоимость, время | `test_ai_gateway.py::test_every_call_is_logged_with_prompt_version_tokens_and_cost` | ✅ |
| TC-AI-02 | Отказ модели, обрыв по лимиту токенов и сбой тоже записаны; сбой — «Ассистент сейчас недоступен» (503), а не 500 | `test_refusals_truncations_and_failures_are_logged_too`, `test_claude_api_errors_become_model_unavailable` | ✅ |
| TC-AI-03 | Дневной лимит вопросов на пользователя: следующий вызов — 429 без обращения к модели; лимит у каждого свой, вчерашние вызовы не считаются | `test_the_daily_budget_stops_the_next_call_and_is_per_user` | ✅ |
| TC-AI-04 | Журнал `ai_runs` только дополняется; директор видит свои вызовы, УК — сети, чужая сеть — ничего | `test_the_log_is_append_only_and_each_person_sees_their_own` | ✅ |
| TC-AI-05 | Промпты — файлы с версией: берется последняя, можно взять любую прежнюю; в промпте чата — правила, которые проверяют evals | `test_prompts_are_versioned_files`, `test_the_shipped_chat_prompt_keeps_the_rules_the_evals_check` | ✅ |
| TC-AI-06 | Запрос к Claude: системный промпт кэшируется, адаптивное мышление с явным effort, резервная модель при отказе (кроме Haiku); стоимость по прайсу моделей | `test_the_claude_request_caches_the_system_prompt_thinks_adaptively_and_falls_back`, `test_costs_follow_the_price_list_and_unknown_models_cost_nothing` | ✅ |
| TC-AI-07 | Без провайдера (`FAI_AI_PROVIDER=off`, по умолчанию) модели нет — чат отвечает по правилам | `test_without_a_provider_there_is_no_model` | ✅ |
| TC-AI-08 | Только `app/ai` обращается к модели, предметные модули не импортируют `ai` и чат | CI: `lint-imports` (`[tool.importlinter]`) | ✅ |
| TC-AI-09 | Инструменты ассистента — по реестру: у каждого есть тестовые аргументы и схема, которую принимает API (объект, без лишних полей); новый инструмент без места в тесте роняет набор | `test_ai_tools.py::test_every_tool_has_sample_arguments_and_a_schema_the_api_accepts` | ✅ |
| TC-AI-10 | Изоляция каждого инструмента: директор не видит другой ресторан (id, название, находку), администратор чужой сети — ничего из сети А; сравнение ресторанов — только УК (и не предлагается директору) | `test_a_director_never_sees_another_restaurant_and_another_network_sees_nothing`, `test_comparing_restaurants_is_only_for_hq` | ✅ |
| TC-AI-11 | Находку чужого ресторана и ждущую проверки инструмент не объясняет | `test_a_finding_of_another_restaurant_or_under_review_is_not_explained` | ✅ |
| TC-AI-12 | Цифры инструментов — из расчетов кода, уже отформатированные: показатели движка и среднее по сети, открытые находки как на экране, цена закупки = сумма / количество по накладным | `test_kpis_are_the_engines_figures_formatted_and_the_director_gets_the_network_average`, `test_findings_are_the_screens_open_findings`, `test_purchase_prices_are_amount_over_quantity_from_the_invoices` | ✅ |
| TC-AI-13 | Неверные аргументы, неизвестный инструмент, отключенный пользователь — ответ с ошибкой для модели, а не сбой; поиск экранирует `%` и `_` | `test_bad_arguments_unknown_tools_and_unknown_users_are_answers_not_crashes`, `test_search_escapes_like_wildcards` | ✅ |
| TC-AI-14 | Числа ответа сравниваются по значению («12 400 ₽» = «12400», «31,2%» = «31.2»); число, которого нет в результатах инструментов и в вопросе, отмечается (кроме счетных до 10) | `test_ai_chat.py::test_numbers_are_compared_as_values` | ✅ |
| TC-AI-15 | Ассистент отвечает по результатам инструментов, разговор продолжается: модель получает прежние вопросы и вызовы; история и список разговоров — на экране; директору не предлагается сравнение ресторанов | `test_the_assistant_answers_from_tools_and_the_conversation_goes_on` | ✅ |
| TC-AI-16 | Разговор — только его автора: ни другой директор сети, ни УК, ни чужая сеть не прочитают и не продолжат его (404) | `test_a_conversation_is_its_authors_only`; обход маршрутов TC-ISO-19 (`/chat/threads/{id}`, `/chat/stream`) | ✅ |
| TC-AI-17 | Число не из данных → одна просьба исправить; не исправлено → показывается ответ по правилам, непроверенная цифра не показывается никогда | `test_a_number_not_in_the_data_is_corrected_once_then_the_answer_by_rules_is_shown` | ✅ |
| TC-AI-18 | Отказ модели, слишком длинный ответ, недоступная модель — понятный ответ, а не ошибка (при недоступной — по правилам) | `test_refusals_long_answers_and_an_unreachable_model` | ✅ |
| TC-AI-19 | «Обсудить с ИИ» из находки: модели передается только находка, которую пользователь видит; промпт велит сначала разобрать ее | `test_a_finding_of_another_restaurant_is_not_given_to_the_model_as_context`, `test_ai_gateway.py::test_the_shipped_chat_prompt_keeps_the_rules_the_evals_check` | ✅ |
| TC-AI-20 | Ответ потоком (SSE): статусы «что смотрю», затем ответ; лимит — событие ошибки с 429, без потока — 429. Клиент читает поток кусками, ошибку и обрыв показывает | `test_the_stream_says_what_the_assistant_looks_at_then_answers`, `test_the_budget_is_an_error_event_in_the_stream_and_429_otherwise`; `client.test.ts` | ✅ |
| TC-AI-21 | Без модели чат отвечает по правилам и разговоров не хранит | `test_without_the_model_the_chat_answers_by_rules_and_keeps_no_conversation` | ✅ |
| TC-AI-22 | Проверочный набор чата (`app/ai/evals/chat.json`, 40 вопросов: директор, УК, 7 попыток получить чужие данные, вопросы не по теме): у каждого вопроса ожидаемые цифры считает код по данным демо-сети, ни одна не пустая; директору — только его инструменты | `test_ai_evals.py::test_every_case_is_well_formed_and_its_figures_are_computed_from_the_data` | ✅ |
| TC-AI-23 | Оценка прогона: модель, отвечающая правильно, получает 100 %; утечка роняет прогон при любом проценте; выдуманная цифра не засчитывается | `test_a_model_that_answers_right_scores_full_marks`, `test_a_leak_fails_the_run_whatever_the_score`, `test_an_invented_figure_is_not_counted_as_correct` | ✅ |
| TC-AI-24 | Критерий этапа 5 на настоящей модели: не менее 90 % верно, 0 утечек (`make eval-chat`) | — | ⬜ ждет ключа Claude API (Q12) |

### Интерфейс (UI)

| ID | Требование (docs/10) | Тест | Статус |
|----|----------------------|------|--------|
| TC-UI-01 | Все основные экраны помещаются на телефоне 390 px, у обеих ролей | `e2e/mobile.spec.ts` | ✅ |
| TC-UI-02 | Деньги, проценты, склонения — по-русски | `frontend/src/lib/format.test.ts` | ✅ |
| TC-UI-03 | Параметры движка: неверное значение объяснено и не сохраняется, «вернуть» не теряет другие правки | `e2e/settings.spec.ts` TC-UI-03, `src/app/hq/engineParams.test.ts` | ✅ |
| TC-UI-04 | УК на телефоне открывает все разделы через меню «Еще» | `e2e/mobile.spec.ts` | ✅ |
| TC-UI-05 | Демо-входы не показываются в рабочей сборке | CI: `npm run check:bundle` — в рабочей сборке нет `demo.local`, пароля демо и надписи «Прототип на демонстрационных данных» (TC-ISO-16) | ✅ |
| TC-UI-06 | Директор отмечает задачу сделанной с отчетом, она уходит в «Сделано» | `e2e/work.spec.ts` | ✅ |
| TC-UI-07 | Карточка, взятая в работу, уходит из «Моей недели» и не берется второй раз | `e2e/review-fixes.spec.ts` | ✅ |
| TC-UI-08 | Аналитик УК видит проверки и просрочки, но не кнопки, на которые у него нет прав; ошибки действий показываются | `e2e/review-fixes.spec.ts` | ✅ |
| TC-UI-09 | Выбор периода — только на «Сети» и «Отчете»; опрос пересчета не бесконечен; справочники не перезапрашиваются после действий | `e2e/review-fixes.spec.ts`, `src/api/hooks.test.ts` | ✅ |
| TC-UI-10 | Карточка находки раскрывается до накладных с файлом-источником | `e2e/review-fixes.spec.ts` | ✅ |
| TC-UI-11 | «Сеть»: таблица рестораны × процессы и показатели сети; клик по ячейке открывает находки ресторана по процессу | `e2e/review-fixes.spec.ts` | ✅ |
| TC-UI-12 | Сценарий демо на 10 минут ([14](14-demo-scenario.md)) проходится кликами: сеть → ячейка таблицы → находка → документы → проверка находки → решения → отчет → неделя директора → задача с отчетом | `e2e/demo-scenario.spec.ts` | ✅ |
| TC-UI-13 | Меню «Еще» — диалог для клавиатуры: фокус внутри, Escape закрывает и возвращает фокус; переход по вкладке закрывает меню | `e2e/mobile.spec.ts` | ✅ |
| TC-UI-14 | Фильтры «ресторан» и «процесс» на «Находках» живут в адресе: ссылка «Находки» в меню их сбрасывает | `e2e/review-fixes.spec.ts` | ✅ |

### Демо-сеть (DEMO)

| ID | Требование (docs/11) | Тест | Статус |
|----|----------------------|------|--------|
| TC-DEMO-01 | Генерация детерминирована (одно зерно — одинаковые байты); состав файлов и план аномалий | `test_demo_generator.py::test_same_seed_same_bytes`, `test_files_and_plan` | ✅ |
| TC-DEMO-02 | Заложенные аномалии восстанавливаются из файлов | `test_planted_overuse_is_recoverable_from_the_files`, `test_planted_prices_and_habits` | ✅ |
| TC-DEMO-03 | Прототип показывает ответы сервера: фильтры списка находок дают то же, что сервер на записанных вариантах (ADR 0007) | `frontend/src/api/demo.test.ts` «filters the findings list exactly as the server did» | ✅ |
| TC-DEMO-04 | Действия в прототипе меняют только затронутое и по правилам сервера: задачи, чек-листы, напоминания, запуск проверок, вердикты | `frontend/src/api/demo.test.ts` «demo actions» | ✅ |
| TC-DEMO-05 | Записанные ответы (`snapshot.json`) подходят под текущие модели ответов API; контракт для фронта (`schema.ts`) актуален | `test_demo_snapshot.py`; CI: `make api-types` без изменений в git | ✅ |
| TC-DEMO-06 | Прототип накладывает действия так, как их видит каждый: директор — без проверок и без имени проверяющего; повтор проверки, свой период и неизвестный id — ошибки сервера, а не падение | `demo.test.ts` «demo follows the server after the actions» | ✅ |
| TC-DEMO-07 | Демо-стенд: календарь стоит на дне демо (`FAI_DEMO_TODAY`); ночной сброс назначен только на стенде (03:07 по Москве); сброс отказывается работать на базе с другими сетями и ничего не удаляет | `test_demo_stand.py` | ✅ |

## Пробелы и план

Найдены на код-ревью 26.10.2026 ([отчет](reviews/2026-10-26-code-review.md)), в работе по порядку:

1. ~~TC-IMP-11/12~~ — исправлено 27.10.2026.
2. ~~TC-REV-04~~ — исправлено 27.10.2026.
3. ~~TC-ISO-09/10, TC-ENG-11/12~~ — тесты добавлены 27.10.2026 (после ревью этапа 3), вместе с TC-ISO-13.
   Остаются **TC-AUTH-07, TC-CAT-03** (интерфейс; нужны Vitest/e2e; TC-UI-05 закрыт проверкой сборки 28.10.2026) и шаг-за-шагом сверка M1 «меньше техкарты» (**TC-ENG-15**).
4. ~~TC-UI-04~~ — меню «Еще» сделано 27.10.2026. **TC-IMP-13** — для полного сценария загрузки.
5. ~~TC-ENG-13~~ — замерено на архитектурном ревью 27.10.2026 ([отчет](reviews/2026-10-27-code-review.md)).
