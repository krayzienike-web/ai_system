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
`[tool.coverage]`). Ниже порога CI красный. На 02.11.2026 (тестировщик после ревью этапа 5.5) — 93,85 % (355 тестов бэкенда + 1 `xfail` TC-AN-49, 37 — фронтенда, 19 e2e). Модули этапа 5.5 — 92–98 % (`ai/mapping.py` 93 %, `imports/service.py` 92 %). На 03.11.2026 (тестировщик после ревью этапа 6; целевой прогон файлов этапа, полный — не запускался) модули этапа 6: `digests/api.py`, `builder.py`, `service.py`, `ai/digest_writer.py`, `ai/evals/digest.py` — 100 %, `digests/reactions.py` 98 % (ветка «неизвестная причина» — ее раньше отсекает схема), `texts.py` и `weekly.py` — добраны тестами TC-DG-34, TC-DG-41. На 05.11.2026 (тестировщик после ревью этапа 6.1; целевой прогон `test_hq_decision.py` — 20 + 1 `xfail` TC-WORK-11, покрытие не мерилось, полный прогон — у разработчика): добавлены TC-WORK-14…17, расширены TC-WORK-06, 07, 11, TC-REV-09; в прототипе — 2 `it.fails` (TC-WORK-15). На 06.11.2026 (тестировщик после ревью этапа 6.5; целевой прогон файлов этапа на `franchise_rev_b`, полный — у разработчика): 84 теста + 1 `xfail` (TC-ENG-43), 54 — фронтенда; модули этапа по этому прогону: `insights/money.py` 100 %, `links.py` 98 %, `m2.py` 98 %, `m7.py` 98 %, `m6.py` 97 %, `quality.py` 97 %, `m8.py` 95 %, `m3.py` 94 %, `verify.py` 86 % (не покрыты ветки «ресторана / товара больше нет» сверок новых видов и сверки M3 growth/contract — их покрывают другие файлы); добавлены TC-ENG-38…44, TC-IMP-25. Слабые места:

| Модуль | Покрытие | Что не покрыто |
|--------|----------|----------------|
| `worker.py` | 79 % | запуск очереди arq (проверяется на стенде) |
| `analytics/verify.py` | 89 % | ветки сверки на неполных данных |
| `insights/review.py` | 89 % | ошибки вердиктов («нет находки», повторное подтверждение) |
| `tasks/service.py` | 89 % | редкие ошибки назначения |
| `chat/service.py` | 90 % | редкие вопросы чата (нет данных, неизвестная находка) |
| `overview/trend.py` | 90 % | запись недели без находок и повторная запись той же недели |
| `demo/snapshot.py`, `openapi.py`, `ai/evals/__main__.py` | 16 %, 0 %, 0 % | служебные: работают в `make demo-snapshot`, `make api-types`, `make eval-hypotheses` |

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
| TC-ISO-19 | Обход всех маршрутов API из схемы OpenAPI (и чата через модель: все инструменты, в том числе с id чужой сети): объекты чужой сети по id (находка, задача, проверка, файл, сопоставление, ресторан) — только 403/404 для администратора УК и директора; списки и экраны не содержат id и названий чужой сети, у директора — id других ресторанов; записи со ссылкой на чужую находку отклоняются; новый маршрут без группы роняет тест | `test_isolation_routes.py` | ✅ |

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
| TC-IMP-20 | Этап 6.5: «Остатки на дату» загружаются в базовой единице, повтор заменяет; отрицательный учетный остаток — не ошибка строки, файл проходит (docs/09, ревью 6.5, п. 5; исправлено тестировщиком 06.11.2026: строка говорила «ошибка строки») | `test_imports_stage65.py::test_stock_on_a_date_is_loaded_in_the_base_unit_and_replaced_on_reload` | ✅ |
| TC-IMP-21 | «Удаления и отмены»: кассир, после печати пречека, чек без блюда (отмена); слова кассы «да / после пречека / нет» | `::test_voids_keep_the_cashier_and_whether_the_check_was_printed`, `::test_after_print_reads_the_tills_words` | ✅ |
| TC-IMP-22 | Кассир в продажах; ФИО кассира не хранится — устойчивый код, табельный номер — как есть (docs/09, Q26) | `::test_a_sale_keeps_its_cashier`, `::test_a_cashiers_name_is_kept_as_a_stable_code_and_a_number_as_it_is` | ✅ |
| TC-IMP-23 | Новые факты — под RLS ресторана: другой директор и другая сеть их не видят; шаблоны описаны для экрана | `::test_the_new_facts_stay_in_their_restaurant`, `::test_the_templates_describe_the_new_exports` | ✅ |
| TC-IMP-24 | Демо-сеть: остатки за 4 недели, удаления и кассиры с тремя заложенными аномалиями (R06 сливки, R08 удаления после пречека, R05 скидки); остальные рестораны — байт в байт как до этапа | `test_demo_generator.py::test_the_stage_65_data_carry_their_planted_anomalies`, `::test_files_and_plan` | ✅ |
| TC-IMP-25 | Этап 6.5, проход тестировщика 06.11.2026: отрицательный остаток публикуется как есть (−1,5); исправленная выгрузка «Удаления и отмены» тех же дней заменяет прежнюю (тот же файл — дубликат); другая сеть не видит ни остатков, ни удалений и не загружает файл на чужой ресторан | `test_imports_stage65_pass.py::test_a_stock_below_zero_is_published_as_it_is`, `::test_voids_of_the_same_days_published_again_replace_the_first`, `::test_another_network_sees_no_stock_and_no_voids` | ✅ |

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
| TC-ENG-27 | M8: кассир с удалениями после пречека намного больше обычного — находка с эффектом сверх медианы; удаления до пречека и редкие удаления — нет | `test_m8_till.py::test_a_cashier_removing_after_printing_far_more_than_the_others_is_found`, `test_a_few_removals_are_no_finding` | ✅ |
| TC-ENG-28 | M8: доля скидок кассира выше обычной в 2 раза и на 3 п.п. — находка; без кассиров ресторан сравнивается с сетью; карточка показывает числа | `test_m8_till.py` (скидки, ресторан, показ) | ✅ |
| TC-ENG-29 | M6 затоваривание по «Остаткам на дату»: медиана остатка дольше 1,5 × срока годности; риск не больше купленного сверх расхода; мало снимков, нет срока или закупок — нет находки | `test_m6_overstock.py` | ✅ |
| TC-ENG-30 | Демо-сеть: движок находит заложенные аномалии этапа 6.5 (сливки R06, удаления «таб. 103» R08, скидки «таб. 104» R05, скачок цены моцареллы R07, «Пицца Четыре сыра» и «Куриные котлеты» в меню-инжиниринге, ошибочные цены R03 и R11, неполная инвентаризация R05), сверка каждой совпадает с движком | `test_analytics.py::test_engine_finds_planted_problems_and_review_gates_directors`, `test_ai_hypotheses.py::test_the_eval_finds_every_planted_anomaly_and_grades_the_top_three`; сверка «Затоваривание: Руккола» R01 (в первом тесте ее не было) — `test_stage65_demo_pass.py` (TC-ENG-44) | ✅ |
| TC-ENG-31 | M3, скачок цены к своей истории: рост сверх роста у остальных ресторанов > 10% и ≥ 3 000 ₽/мес — находка с суммой сверх прежней цены; рост по всей сети, малый рост, короткая история, товар с договором или уже найденная переплата к сети — нет | `test_m3_jump.py` | ✅ |
| TC-ENG-32 | M2, меню-инжиниринг: популярное блюдо с маржой ниже 70% средней по категории — повышение цены на 5% с суммой; редкое с маржой выше 130% — продвижение с суммой; сбалансированная категория, блюдо одно в категории, малая сумма или блюдо с находкой по фудкосту — нет | `test_m2_menu.py` | ✅ |
| TC-ENG-33 | Связанные находки: затоваривание + списания, рост цены по сети + фудкост блюда, перерасход + дорогая закупка, расход меньше техкарты + остаток в минусе — одна история; одна сторона или разные рестораны — нет; сумма истории — наибольшая находка, итоги обзоров не задваивают; директор видит в истории только свои находки | `test_links.py`; `test_analytics.py::test_linked_findings_show_their_story_to_those_who_may_see_it`; `test_overview.py` (суммы); разные рестораны для receipts и supplier, рост цены без блюд, равные суммы — один раз при любом порядке: `test_stage65_edges.py::test_the_two_sides_of_a_story_in_two_restaurants_are_no_story`, `::test_a_story_of_two_equal_sums_counts_once_whatever_their_order` | ✅ |
| TC-ENG-34 | M7, этап 6.5: строки накладных без суммы и с ценой в 3+ раза от типичной цены сети — находка со строками (обычные и более старые цены — нет); последняя инвентаризация без товаров, бывших в каждой из двух предыдущих и закупленных после, — находка (товар не всегда считали, его больше не закупают, мало инвентаризаций — нет); демо: R03, R11, R05 | `test_m7_prices_counts.py`; `test_analytics.py::test_engine_finds_planted_problems_and_review_gates_directors`; ровно в 3 раза — не ошибка, меньше 3 строк с ценой — нет типичной цены: `test_stage65_edges.py::test_m7_a_price_exactly_three_times_the_typical_is_no_error`, `::test_m7_a_product_with_fewer_than_three_priced_lines_has_no_typical_price` | ✅ |
| TC-ENG-35 | Оценка качества данных 0–100: штрафы по видам с пределами, сетевая находка штрафует рестораны, где блюдо продается; сеть — среднее; отклоненная УК находка баллы не снимает; ниже 60 — уверенность находок ресторана снижается с объяснением в карточке (находки о данных — нет); директор видит оценку и причины только по находкам, которые ему показаны (обзор и сводка), УК — целиком | `test_data_quality.py`; `test_overview.py` (обзор ресторана); `test_digests_review.py::test_p1_a_restaurants_digest_holds_no_network_revenue`; `test_analytics.py::test_a_rejected_data_finding_takes_no_points_off_the_score`. Уточнение 06.11.2026: эти тесты проверяют только случай «сетевая находка не видна»; часть, из которой директору видна лишь одна находка, — TC-ENG-43 (ошибка) | ✅ |
| TC-ENG-36 | Сумма истории одна на всех экранах (ревью 6.5, п. 1, 6): самая большая находка, в ее процессе; supplier — суммы складываются; находки разного вида — один раз; шапка обзора, процессы, матрица и рейтинг ресторана сходятся | `test_story_money.py`; `test_overview.py::test_a_storys_money_agrees_on_every_screen` | ✅ |
| TC-ENG-37 | Ревью 6.5: M8 сравнивает только рестораны с выгрузкой удалений (со скидками); ключи M7 устойчивы при новых строках; отрицательный учетный остаток загружается; «не напечатан» — до печати; код кассира с солью сети, ФИО с цифрами — не табельный номер | `test_m8_till.py::test_restaurants_without_the_export_are_not_the_typical_cashier`; `test_m7_prices_counts.py::test_the_key_stays_when_lines_come_and_go`; `test_imports_stage65.py`; публикация отрицательного остатка и M6 «минус = ноль» — TC-IMP-25, TC-ENG-40 | ✅ |
| TC-ENG-38 | M2, меню-инжиниринг на границах: доля ровно 70% равной доли (35% из двух блюд) — популярное, 34,5% — нет; сумма ровно 3 000 ₽/мес — находка, порог 3 001 — нет; без продаж, без цен, только возвраты — ничего | `test_stage65_edges.py::test_m2_a_dish_at_exactly_seventy_percent_of_an_equal_share_is_popular`, `::test_m2_a_sum_of_exactly_three_thousand_a_month_is_shown`, `::test_m2_no_sales_or_no_prices_give_nothing` | ✅ |
| TC-ENG-39 | M3, скачок цены на границе: рост ровно 10% — нет («больше 10%»), 10,2% — находка 21 857 ₽/мес; возврат в окне цену не меняет | `test_stage65_edges.py::test_m3_a_rise_of_exactly_ten_percent_is_no_jump`, `::test_m3_returns_are_no_purchases_of_the_jump` | ✅ |
| TC-ENG-40 | M6, затоваривание: учетный остаток ниже нуля — ноль на полке (медиана 15, а не 10); 14 снимков — достаточно, 13 — нет; полуфабрикат и нет выгрузки остатков — не проверяются | `test_stage65_edges.py::test_m6_a_stock_below_zero_on_the_books_counts_as_nothing_on_the_shelf`, `::test_m6_fourteen_snapshots_are_enough_thirteen_are_not`, `::test_m6_semi_finished_products_and_no_stock_export_are_skipped` | ✅ |
| TC-ENG-41 | M8 на границах: 8 удалений после пречека — находка, 7 — нет (хотя сумма выше порога); скидки ровно на 3 п.п. выше обычной (5% против 2%) — находка 9 000 ₽/мес, 2,99 п.п. — нет | `test_stage65_edges.py::test_m8_eight_removals_after_printing_are_enough_seven_are_not`, `::test_m8_discounts_exactly_three_points_above_the_usual_are_found` | ✅ |
| TC-ENG-42 | Оценка качества данных на границах: ровно 60 — уверенность не снижается, 55 — снижается (низкая остается низкой, причина — в доказательствах); пределы всех видов, оценка не ниже 0; среднее сети с округлением половины вверх (87,5 → 88); «без техкарты» — только ресторанам, где блюдо продается; уровни словами 80 / 79 / 60 / 59 | `test_stage65_edges.py::test_a_score_of_exactly_sixty_keeps_the_confidence_below_it_is_lowered`, `::test_the_caps_the_floor_of_zero_and_the_networks_rounded_average`, `::test_a_network_no_recipe_finding_takes_points_only_where_the_dish_is_sold`, `::test_the_answer_names_the_level_at_its_limits` | ✅ |
| TC-ENG-43 | Оценка директора через API обзора: без задачи УК — 100 и ни слова; с задачей по «выгрузка не загружена» — 75 и только эта причина; УК — 35 и все причины по убыванию; директор другого ресторана и другая сеть — 404. **Ошибка (найдена 06.11.2026):** если директору видна одна из трех находок «остаток в минусе», часть показывается целиком (30 баллов вместо 10) — оценка говорит о двух находках, которых ему не показывают (`overview.service.visible_quality` оставляет часть целиком) | `test_data_quality_visibility.py::test_a_director_sees_the_parts_of_the_findings_shown_to_them_and_hq_the_whole_score`; **ошибка**: `::test_a_part_counts_only_the_findings_shown_to_the_director` | ✅ |
| TC-ENG-44 | Демо-сеть, проход после ревью 6.5: повторный пересчет — те же ключи и те же числа (суммы, доказательства, истории, уверенность, оценки качества); сверка «Затоваривание: Руккола» сходится; после изменения строк (остатки сливок R06, удаления «таб. 103» R08) сверка показывает расхождение; директор R03 видит 5 баллов за ошибочную цену только после проверки и задачи УК, без сетевой находки; чужой обзор — 404, чужая сверка — 403, в историях — только R03 | `test_stage65_demo_pass.py::test_stage_six_five_on_the_demo_network_after_the_review` | ✅ |

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
| TC-REV-09 | Ручную проверку можно выключить: новые находки минуют «Проверку находок» и сразу ждут решения УК; директору — только с задачей (ADR 0009) | `test_review_can_be_switched_off`, `test_hq_decision.py::test_without_the_review_a_finding_still_waits_for_the_hqs_task` | ✅ |

### Задачи, проверки изменений, отчет (WORK)

| ID | Требование (docs/05) | Тест | Статус |
|----|----------------------|------|--------|
| TC-WORK-01 | Этап работы по находке выводится из задач и проверок | `test_work_stage.py` (9 тестов), `test_work_loop.py::test_findings_carry_work_stage`, `test_stage_filter` | ✅ |
| TC-WORK-02 | УК ставит шаг директору, сетевая находка — всем директорам, чужому ресторану нельзя | `test_work_loop.py::test_hq_assigns_*`, `test_network_wide_finding_goes_to_every_director`, `test_finding_of_one_restaurant_cannot_go_to_another`, `test_director_cannot_task_a_finding_but_keeps_own_tasks`, `test_analyst_cannot_assign`, `test_due_date_must_be_reasonable` | ✅ |
| TC-WORK-03 | Директор выполняет свои задачи с отчетом; результат не пишет человек | `test_director_completes_with_report_and_result_is_pending`, `test_no_endpoint_lets_a_person_write_a_result`, `test_hq_does_not_execute_and_director_cannot_complete_others` | ✅ |
| TC-WORK-04 | Запуск и отклонение проверки изменений; правила вывода результата | `test_launch_sets_tasks_for_test_restaurants`, `test_reject_proposal`, `test_outcome_rules`, `test_check_result_reaches_its_done_tasks` | ✅ |
| TC-WORK-05 | Отчет руководителю: цифры, провалы, границы периода | `test_head_report_numbers_and_failures`, `test_head_report_period_excludes_earlier_events`; проверки и отчет — только УК: `test_checks_and_head_report_are_hq_only` | ✅ |
| TC-WORK-06 | ADR 0009: директор не встречает подтвержденную находку без задачи нигде (карточка, списки, доска, «Моя неделя», задачи, инструменты чата, сводка); сам поставить задачу по находке не может; после задачи от УК — видит везде, и находка уходит из «Решить по находке». Все маршруты с id находки: гипотезы ИИ (GET/POST), «Откуда цифры», «Не согласен» (и отзыв) — 404, до УК ничего не доходит; сверка, предпроверка, проверки, черновик проверки, отчет руководителю, несогласия — 403; после задачи — открываются. Чат: вопрос из находки без задачи (`/chat` и `/chat/stream`) не привязан к ней и модели о ней не сообщает; ответ по правилам не называет находки без задачи | `test_hq_decision.py::test_a_director_meets_a_finding_only_once_the_hq_set_a_task`, `::test_an_unassigned_finding_is_not_found_by_a_director_on_any_endpoint_about_it`, `::test_the_chat_does_not_discuss_an_unassigned_finding_with_a_director`, `::test_the_answer_by_rules_names_no_unassigned_finding` | ✅ |
| TC-WORK-07 | «Решить по находке»: подтвержденные находки без задачи и без проверки — ресторанов и сетевые, дороже вверху (эффект × уверенность, без оценки в рублях — в конце, без повторов); только УК (чужой сети — ни одной); счетчик «Ждут решения» = находки + проверки к запуску + просроченные задачи; предложенная проверка уводит находку из списка, отклоненная — возвращает (счетчик тот же) | `test_hq_decision.py::test_awaiting_holds_restaurants_and_network_findings_and_is_the_hqs`, `::test_awaiting_puts_the_most_valuable_first_and_the_unpriced_last`, `::test_a_rejected_check_returns_the_finding_to_awaiting` | ✅ |
| TC-WORK-08 | Свою задачу без находки директор ставит по-прежнему | `test_hq_decision.py::test_a_directors_own_task_without_a_finding_is_still_theirs` | ✅ |
| TC-WORK-09 | Сводка директора — только находки с задачей на его ресторан (собирается под системным контекстом, мимо RLS) | `test_hq_decision.py::test_a_directors_digest_holds_only_findings_with_a_task` | ✅ |
| TC-WORK-10 | Ревью 6.1, п. 1: основание гипотез ИИ не называет находки ресторана без задачи | `test_hq_decision.py::test_r1_the_ais_basis_names_only_data_problems_the_director_sees` | ✅ |
| TC-WORK-11 | П. 2: сводка, собранная до ADR 0009, не показывает директору находки без задачи — ни пунктом, ни в «Главном за неделю» (сохраненный текст называет главную проблему), ни в «На столе» | `::test_r2_a_digest_stored_before_shows_a_director_only_what_they_see`; **ошибка**: `::test_r2_a_digest_stored_before_does_not_name_an_unassigned_finding_in_its_headline` (xfail strict) — пункты убираются, а `headline` и `on_table` сохраненной сводки остаются  — исправлено 05.11.2026: пункты, «Главное» и «на столе» пересчитаны по видимым (`::test_r2_a_digest_stored_before_does_not_name_an_unassigned_finding_in_its_headline`) | ✅ |
| TC-WORK-12 | П. 3: карточка «Ждут вашего решения» на главной сети равна счетчику меню | `::test_r3_the_network_card_counts_what_the_badge_counts` | ✅ |
| TC-WORK-14 | Задачу по находке ставит только администратор УК: аналитик — 403 (раздел видит); находку ресторана — только ее ресторану; чужой сети — 404; ничего не решено — находка в списке | `test_hq_decision.py::test_a_restaurants_finding_goes_to_its_restaurant_only_and_from_the_admin_only` | ✅ |
| TC-WORK-15 | Сетевая находка части ресторанов: одна задача с чек-листом на выбранный ресторан, находка уходит из «Решить по находке»; директор выбранного видит задачу без названия и суммы сетевой находки («Поставлено управляющей компанией»), директор другого — ни задачи, ни находки; без выбора — всем ресторанам сети. Прототип — так же (`demo.test.ts` «demo «Поставить задачу» keeps the server's rules»); **ошибки прототипа** (`it.fails`): находку ресторана можно поставить другому ресторану; задача директора по сетевой находке называет ее и сумму сети | `test_hq_decision.py::test_a_network_finding_given_to_part_of_the_network_reaches_only_those_directors`, `::test_a_network_finding_without_chosen_restaurants_goes_to_every_restaurant`; `demo.test.ts`  — ошибки прототипа исправлены 05.11.2026 | ✅ |
| TC-WORK-16 | Задача ресторана по находке другого ресторана (тиражирование): директор получает задачу, но не название, сумму и карточку чужой находки | `test_hq_decision.py::test_a_task_on_another_restaurants_finding_does_not_name_it_to_the_director` | ✅ |
| TC-WORK-17 | Политика `findings` (миграция 0025) в базе: задача ресторана открывает директору только находку этого ресторана — не сетевую и не чужую с задачей на его ресторан; находку без задачи директор не меняет (0 строк) | `test_hq_decision.py::test_the_findings_policy_a_task_opens_only_its_own_restaurants_finding` | ✅ |
| TC-WORK-13 | П. 7: директору без задач — «Задач по находкам от управляющей компании пока нет», не «проблем нет»; «Моя неделя» не говорит директору, как выросли суммы находок без задачи | `::test_r7_…`, `::test_the_week_does_not_tell_a_director_how_much_unassigned_findings_grew` | ✅ |

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
| TC-AI-04 | Журнал `ai_runs` только дополняется; каждый видит только свои вызовы — и УК (в журнале целые разговоры, ревью 28.10, п. 5), чужая сеть — ничего | `test_the_log_is_append_only_and_each_person_sees_their_own` | ✅ |
| TC-AI-05 | Промпты — файлы с версией: берется последняя, можно взять любую прежнюю; в промпте чата — правила, которые проверяют evals | `test_prompts_are_versioned_files`, `test_the_shipped_chat_prompt_keeps_the_rules_the_evals_check` | ✅ |
| TC-AI-06 | Запрос к Claude: системный промпт кэшируется, адаптивное мышление с явным effort, резервная модель при отказе (кроме Haiku); стоимость по прайсу моделей; в журнал пишется модель, которая ответила, у модели без цены стоимость пустая, а не 0 (ревью 28.10, п. 12); таймаут 120 с, один повтор, 8000 токенов (п. 19); лимит по умолчанию — 100 обращений | `test_the_claude_request_caches_the_system_prompt_thinks_adaptively_and_falls_back`, `test_costs_follow_the_price_list_and_an_unknown_model_has_no_cost`, `test_a_model_without_a_price_is_logged_with_an_empty_cost`, `test_the_claude_client_waits_two_minutes_retries_once_and_asks_for_a_short_answer` | ✅ |
| TC-AI-07 | Без провайдера (`FAI_AI_PROVIDER=off`, по умолчанию) модели нет — чат отвечает по правилам | `test_without_a_provider_there_is_no_model` | ✅ |
| TC-AI-08 | Только `app/ai` обращается к модели, предметные модули не импортируют `ai` и чат | CI: `lint-imports` (`[tool.importlinter]`) | ✅ |
| TC-AI-09 | Инструменты ассистента — по реестру: у каждого есть тестовые аргументы и схема, которую принимает API (объект, без лишних полей); новый инструмент без места в тесте роняет набор | `test_ai_tools.py::test_every_tool_has_sample_arguments_and_a_schema_the_api_accepts` | ✅ |
| TC-AI-10 | Изоляция каждого инструмента: директор не видит другой ресторан (id, название, находку), администратор чужой сети — ничего из сети А; сравнение ресторанов — только УК (и не предлагается директору) | `test_a_director_never_sees_another_restaurant_and_another_network_sees_nothing`, `test_comparing_restaurants_is_only_for_hq` | ✅ |
| TC-AI-11 | Находку чужого ресторана и ждущую проверки инструмент не объясняет | `test_a_finding_of_another_restaurant_or_under_review_is_not_explained` | ✅ |
| TC-AI-12 | Цифры инструментов — из расчетов кода, уже отформатированные: показатели движка и среднее по сети, открытые находки как на экране, цена закупки = сумма / количество по накладным | `test_kpis_are_the_engines_figures_formatted_and_the_director_gets_the_network_average`, `test_findings_are_the_screens_open_findings`, `test_purchase_prices_are_amount_over_quantity_from_the_invoices` | ✅ |
| TC-AI-13 | Неверные аргументы, неизвестный инструмент, неизвестный пользователь — ответ с ошибкой для модели, а не сбой; пользователь, отключенный посреди вопроса, следующим вызовом инструмента данных не получает; поиск экранирует `%` и `_` | `test_bad_arguments_unknown_tools_and_unknown_users_are_answers_not_crashes`, `test_ai_chat.py::test_access_revoked_during_a_question_stops_the_next_tool_call`, `test_search_escapes_like_wildcards` | ✅ |
| TC-AI-14 | Числа ответа сравниваются по значению («12 400 ₽» = «12400», «31,2%» = «31.2»); число, которого нет в результатах инструментов, отмечается (кроме «голых» счетных до 10; вопрос источником не считается — TC-AI-26) | `test_ai_chat.py::test_numbers_are_compared_as_values` | ✅ |
| TC-AI-15 | Ассистент отвечает по результатам инструментов, разговор продолжается: модель получает прежние вопросы и вызовы; история и список разговоров отдаются API (`/chat/threads`; на экране списка нет — бэклог, ревью 28.10, фронтенд п. 8); директору не предлагается сравнение ресторанов | `test_the_assistant_answers_from_tools_and_the_conversation_goes_on` | ✅ |
| TC-AI-16 | Разговор — только его автора: ни другой директор сети, ни УК, ни чужая сеть не прочитают и не продолжат его (404) | `test_a_conversation_is_its_authors_only`; обход маршрутов TC-ISO-19 (`/chat/threads/{id}`, `/chat/stream`) | ✅ |
| TC-AI-17 | Число не из данных → одна просьба исправить; не исправлено → показывается ответ по правилам, непроверенная цифра не показывается никогда | `test_a_number_not_in_the_data_is_corrected_once_then_the_answer_by_rules_is_shown` | ✅ |
| TC-AI-18 | Отказ модели, слишком длинный ответ, недоступная модель — понятный ответ, а не ошибка (при недоступной — по правилам) | `test_refusals_long_answers_and_an_unreachable_model` | ✅ |
| TC-AI-19 | «Спросить су-шефа» из находки: модели передается id находки, которую пользователь видит, вместе с вопросом; ответ ссылается на нее («откуда цифра»), разговор ее помнит; находка из `explain_finding` — тоже источник; чужая и ждущая проверки (и у УК) не передаются; промпт велит сначала разобрать находку | `test_a_finding_the_person_sees_goes_to_the_model_first_and_is_the_answers_source`, `test_a_finding_of_another_restaurant_is_not_given_to_the_model_as_context`, `test_a_finding_under_review_is_not_given_to_the_model_as_context` (баг найден 28.10, исправлен), `test_ai_gateway.py::test_the_shipped_chat_prompt_keeps_the_rules_the_evals_check` | ✅ |
| TC-AI-20 | Ответ потоком (SSE): статусы «что смотрю», затем ответ; лимит — событие ошибки с 429, без потока — 429. Клиент читает поток кусками, ошибку (с ее статусом) и обрыв передает экрану | `test_the_stream_says_what_the_assistant_looks_at_then_answers`, `test_the_budget_is_an_error_event_in_the_stream_and_429_otherwise`; `client.test.ts` | ✅ |
| TC-AI-21 | Без модели чат отвечает по правилам и разговоров не хранит | `test_without_the_model_the_chat_answers_by_rules_and_keeps_no_conversation` | ✅ |
| TC-AI-22 | Проверочный набор чата (`app/ai/evals/chat.json`, 40 вопросов: директор, УК, 7 попыток получить чужие данные, вопросы не по теме): у каждого вопроса ожидаемые цифры считает код по данным демо-сети, ни одна не пустая; директору — только его инструменты | `test_ai_evals.py::test_every_case_is_well_formed_and_its_figures_are_computed_from_the_data` | ✅ |
| TC-AI-23 | Оценка прогона: модель, отвечающая правильно, получает 100 %; утечка роняет прогон при любом проценте; выдуманная цифра не засчитывается | `test_a_model_that_answers_right_scores_full_marks`, `test_a_leak_fails_the_run_whatever_the_score`, `test_an_invented_figure_is_not_counted_as_correct` | ✅ |
| TC-AI-24 | Критерий этапа 5 на настоящей модели: не менее 90 % верно, 0 утечек (`make eval-chat`) | — | ⬜ ждет ключа Claude API (Q12) |
| TC-AI-25 | Малые числа с единицей («4%», «2 п.п.», «в 3 раза») сверяются всегда, без единицы — счет; даты — одним значением, знак учитывается, UUID ничего не разрешают, «вдвое/втрое» не подтверждаются | `test_ai_chat.py::test_small_figures_with_a_unit_are_checked_too` | ✅ |
| TC-AI-26 | Число из вопроса или из ошибки инструмента не источник; ошибка не повторяет аргументы модели | `test_a_figure_from_the_question_or_from_a_tools_error_is_not_a_source` | ✅ |
| TC-AI-27 | Числа из результатов прошлых вопросов разговора можно повторить | `test_figures_from_earlier_in_the_conversation_may_be_quoted_again` | ✅ |
| TC-AI-28 | Пока модель думает, приложение не держит соединение с открытой транзакцией (POST и поток) | `test_no_connection_waits_in_a_transaction_while_the_model_thinks` | ✅ |
| TC-AI-29 | После отказа, обрыва и непрошедшей проверки разговор остается валидным: вопрос — ответ, без пустых и незакрытых сообщений; хранится то, что человек увидел | `test_after_a_refusal_a_cut_off_answer_or_a_failed_check_the_conversation_stays_valid` | ✅ |
| TC-AI-30 | Два вопроса в один разговор одновременно записываются друг за другом | `test_two_questions_to_one_thread_at_once_are_kept_one_after_the_other` | ✅ |
| TC-AI-31 | Сбой инструмента — ответ модели, а не сбой вопроса | `test_a_tool_that_fails_is_an_answer_for_the_model` | ✅ |
| TC-AI-32 | Лимит обращений проверяется раз на вопрос, начатый вопрос доводится до ответа, текст 429 — «…обновится в полночь»; сутки — по Москве (минута до полуночи МСК — вчера, минута после — сегодня) | `test_the_budget_counts_once_per_question_and_a_started_question_is_finished`, `test_ai_gateway.py::test_the_budgets_day_starts_at_midnight_in_moscow` | ✅ |
| TC-AI-33 | Поток в интерфейсе: символ и пустая строка, разрезанные между кусками, CRLF, keep-alive; повтор после 401; отмена (закрытие чата) до ответа и посреди потока прерывает чтение | `client.test.ts` («stops reading when the chat is closed», «stops in the middle of an answer when the chat is closed») | ✅ |
| TC-AI-34 | Модель, которая все время вызывает инструменты, останавливается после 6 обращений (docs/08, «до 6 шагов»): ответ по правилам, в разговоре у каждого вызова есть результат, вопрос закрыт показанным ответом | `test_ai_chat.py::test_a_model_that_keeps_calling_tools_is_stopped_after_six_rounds` | ✅ |
| TC-AI-35 | Любой сбой внутри потока — событие `error` со статусом 500 и текстом для человека, без подробностей сбоя; клиент отдает экрану статус 500 и текст | `test_ai_chat.py::test_the_stream_ends_with_an_error_event_when_something_breaks_inside`; `client.test.ts` «rejects with 500 when the server fails inside the stream» | ✅ |
| TC-AI-36 | Длинный разговор (больше `KEEP` = 40 сообщений) уходит модели с вопроса, а не с результата инструмента без вызова | `test_ai_chat.py::test_a_long_conversation_is_replayed_from_a_question` | ✅ |
| TC-AI-37 | Срез длинной истории не конфликтует с preserved thinking у Opus 5.5 (ревью 28.10, п. 11) | — | ⬜ ждет ключа Claude API (Q12) |
| TC-AI-38 | Чат на экране: статус «что смотрю» виден, пока ассистент думает; следующий вопрос идет с `thread_id` прошлого ответа; при 429 показывается текст сервера, при другой ошибке — «Не получилось ответить»; закрытие чата отменяет вопрос в полете | — | ⬜ нужен компонентный тест (jsdom + Testing Library — новые зависимости, не добавлены); прототип отвечает сразу, без потока и лимита, поэтому e2e это не проверит. Логика клиента — TC-AI-20, 33, 35 |

### ИИ-помощник аналитика (AN, этап 5.5, ADR 0008)

Модель — заглушка (Q12). Эталон — заложенные аномалии демо-сети с настоящей причиной (`anomalies.json`, `cause`).

| ID | Требование | Тест | Статус |
|----|------------|------|--------|
| TC-AN-01 | Структурированный ответ: схема закрыта (`additionalProperties: false`, все поля обязательны), причины — из фиксированного списка; запрос к Claude передает схему в `output_config.format` | `test_ai_hypotheses.py::test_the_schema_sent_to_the_model_is_closed_and_complete` | ✅ |
| TC-AN-02 | «Почему так»: контекст собирает код (поставщики по месяцам, причины списаний, инвентаризации, проблемы данных, итоги похожих проверок, правила сети); гипотезы хранятся, новая заменяет старую | `test_hypotheses_are_proposed_from_the_facts_and_kept`; поставщики по месяцам и проблемы данных — TC-AN-32 | ✅ |
| TC-AN-03 | Число не из фактов, больше трех гипотез или повтор причины → одна просьба исправить, потом предложения нет (502), неудачные попытки не сохраняются; ответ не по схеме — предложения нет | `test_a_number_not_in_the_facts_is_corrected_once_then_there_is_no_proposal` | ✅ |
| TC-AN-04 | Гипотезы видны по правилам карточки: директору — только по своим проверенным находкам (не по ждущей проверки, не другого ресторана, не сетевой); чужой сети — ничего; контекст находки R01, собранный для УК, без названий других ресторанов | `test_the_cards_rules_decide_who_sees_the_hypotheses` | ✅ |
| TC-AN-05 | Решение по гипотезам принимает человек («Полезно / Не то»); без модели — 503 «Ассистент пока не подключен» | `test_a_person_decides_and_without_the_model_nothing_is_proposed` | ✅ |
| TC-AN-06 | Прогон «почему так»: каждая из 16 заложенных аномалий сопоставлена с находкой движка; модель, называющая настоящую причину, — 100 %, «всегда хищение» — 0 % и провал при цели 80 % | `test_the_eval_finds_every_planted_anomaly_and_grades_the_top_three` | ✅ |
| TC-AN-07 | Критерий этапа на настоящей модели: причина в топ-3 ≥ 80 % (`make eval-hypotheses`) | — | ⬜ ждет ключа (Q12) |
| TC-AN-08 | Предпроверка: «на что посмотреть» считает код без модели (проблемы данных ресторана, разовый всплеск, смена поставщика, праздники, мало данных, непрошедшая сверка) | `test_ai_precheck.py::test_what_to_look_at_is_computed_by_the_code`, `test_holidays_spikes_and_short_periods_are_flagged`; разовый всплеск, смена поставщика, праздник у дня всплеска, непрошедшая сверка — TC-AN-36 (до 02.11 не проверялись) | ✅ |
| TC-AN-09 | Черновик вердикта: причина только при «отклонить» и обязательна для него, числа сверяются; статистика «ИИ предлагал / человек решил» по вердиктам аналитика | `test_the_draft_is_proposed_checked_and_counted_against_the_analysts_verdict`; причина при «подтвердить» — TC-AN-37; совпадение в статистике — TC-AN-27 | ✅ |
| TC-AN-10 | Предпроверка — только для тех, кто проверяет находки; чужая сеть — ничего | `test_the_pre_check_is_for_reviewers_only` | ✅ |
| TC-AN-11 | Идеи находок: агрегаты по дням недели и против сети считает код, заложенная закономерность R07 (хлеб по пн и вт) в них есть | `test_ai_discover.py::test_the_planted_weekday_pattern_is_in_the_aggregates`; «против сети» и порог 4 дней — TC-AN-38 | ✅ |
| TC-AN-12 | Идея обязана ссылаться на строки агрегатов, ее числа — из этих строк; каждая идея — отдельное решение аналитика | `test_ideas_point_at_rows_every_number_is_checked_and_each_is_decided` (число не из таблицы вообще); число из другой строки и больше пяти идей — TC-AN-39 | ✅ |
| TC-AN-13 | Идеи — только для УК: директор не видит, не просит и не решает; чужая сеть — ничего | `test_ideas_are_for_the_hq_only` | ✅ |
| TC-AN-14 | Незнакомый файл: строку заголовков находит код; разметка без обязательной колонки или ломающая больше половины строк отклоняется импортом и уходит модели на исправление один раз | `test_ai_mapping.py::test_the_header_of_an_unknown_file_is_found_by_the_code`, `test_a_marking_that_breaks_most_rows_is_no_proposal` — на деле проверяет заголовок, которого нет в файле; «ломает больше половины строк» и граница 50 % — TC-AN-40 | ✅ |
| TC-AN-15 | Разметка подтверждается один раз и становится профилем источника: тот же файл и файл следующего месяца загружаются без шаблона и без модели; повторное подтверждение отклоняется | `test_marked_once_confirmed_once_then_files_load_by_the_profile` (повтор — ровно 409 с 02.11) | ✅ |
| TC-AN-16 | Разметку справочников сети делает и подтверждает УК; чужая сеть не видит и не подтверждает, профилей чужой сети не видно | `test_who_may_mark_and_confirm` | ✅ |
| TC-AN-17 | Новые маршруты помощника — в обходе изоляции всех маршрутов (предложения по id чужой сети — 404) | `test_isolation_routes.py` (TC-ISO-19) | ✅ |
| TC-AN-18 | Схема ответа требует ровно поля модели, поле `title` сохраняется (все четыре схемы); ответ заглушки сверяется со схемой, и неподходящий роняет тест, а не превращается в 503 | `test_ai_review_55.py::test_every_answer_schema_requires_exactly_its_fields`, `test_a_scripted_answer_that_does_not_fit_the_schema_fails_the_test` | ✅ |
| TC-AN-19 | Основание гипотез директора: нет находок на проверке и отклоненных, нет чужих проверок изменений (только счет по сети) | `test_the_basis_holds_no_finding_under_review_and_no_other_restaurants_checks` (отклоненная); ждущая проверки — TC-AN-33 | ✅ |
| TC-AN-20 | Модель не переназначает сопоставленное словарем; сохраняется ровно проверенная импортом разметка | `test_the_model_cannot_remap_what_the_dictionary_mapped_and_the_preview_is_what_is_confirmed` | ✅ |
| TC-AN-21 | Профиль директора действует в его ресторане, профиль УК — в сети; синонимы шаблона важнее профиля | `test_a_directors_profile_serves_their_restaurant_and_synonyms_win_over_profiles`; «не действует в другом ресторане» тест заявлял, но не проверял — TC-AN-43 | ✅ |
| TC-AN-22 | Заголовок, который уже читается по-другому, и заголовок двум колонкам — отказ; профиль удаляет УК (сетевой) | `test_a_header_read_two_ways_is_refused_and_a_profile_can_be_removed`; сетевой профиль против профиля ресторана — TC-AN-44 (был баг) | ✅ |
| TC-AN-23 | Разметка вытесняет только разметку того же файла; новые идеи не прячут нерешенные | `test_a_marking_replaces_only_a_marking_of_the_same_file_and_new_ideas_keep_undecided_ones`, `test_a_threshold_in_the_rules_sketch_is_a_proposal_but_a_figure_in_the_pattern_is_checked`; та же разметка того же файла вытесняется — TC-AN-42 | ✅ |
| TC-AN-24 | Решение по предложению одно (повтор — 409), «кто решил» видно; разметка принимается только подтверждением | `test_a_proposal_is_decided_once_and_a_marking_only_by_confirming` | ✅ |
| TC-AN-25 | Пороги в наброске правила — предложение, не сверяются; числа закономерности — сверяются | `test_a_threshold_in_the_rules_sketch_is_a_proposal_but_a_figure_in_the_pattern_is_checked` | ✅ |
| TC-AN-26 | Разметка: права раньше модели (403, затем 503), файл больше 20 МБ — отказ | `test_access_comes_before_the_model_and_a_big_file_is_refused` | ✅ |
| TC-AN-27 | Отклоненная проблема данных не флаг; кривой период не роняет; черновик после вердикта не в статистике | `test_a_rejected_data_problem_flags_nothing_and_a_draft_after_the_verdict_is_not_counted` | ✅ |
| TC-AN-28 | Признак ассистента — только для провайдера, который знает сервер; правила сети задаются в нормах | `test_the_assistant_flag_follows_the_provider_the_server_knows`, `test_the_networks_rules_are_set_with_the_norms` | ✅ |
| TC-AN-29 | Прогон «почему так» измеряет, не перезаписывая предложения | `test_the_eval_measures_without_replacing_what_people_see` | ✅ |
| TC-AN-30 | Нераспознанный файл: код `no_header` при определении по файлу, `markable` у загрузки с выбранным шаблоном | `test_an_unrecognised_file_says_it_can_be_marked` | ✅ |
| TC-AN-31 | Поведение блоков ИИ в интерфейсе (загрузка, ошибка, решение, разметка и повторная загрузка) | — | ⬜ нужны компонентные тесты (jsdom + Testing Library), сейчас — серверные тесты и TC-UI-17 |
| TC-AN-32 | Контекст «почему так» (план 5.5, п. 2): поставщики и средняя цена по месяцам, проблемы данных того же ресторана (R10, моцарелла); «на чем основано» называет их словами | `test_ai_assistant_pass.py::test_the_facts_hold_suppliers_by_month_and_the_restaurants_data_problems` | ✅ |
| TC-AN-33 | Основание директора: проблема данных его ресторана, ждущая проверки, не попадает ни в факты модели, ни в ответ (ADR 0008, «Уточнения») | `test_ai_assistant_pass.py::test_a_data_problem_under_review_is_not_in_a_directors_basis` | ✅ |
| TC-AN-34 | Числа сверяются во всех фактических полях: число в шагах и в «как проверить» — одна просьба исправить, потом 502, ничего не сохранено | `test_ai_assistant_pass.py::test_a_number_in_the_steps_or_in_how_to_check_is_checked_too` | ✅ |
| TC-AN-35 | Предложение хранит промпт и его версию (гипотезы — v2), автора, основание; замененное предложение решить нельзя (404), текущее — можно | `test_ai_assistant_pass.py::test_a_proposal_records_its_prompt_version_and_a_replaced_one_cannot_be_decided` | ✅ |
| TC-AN-36 | Предпроверка, флаги кода (расчет вручную): 8 из 10 списаний за день — «разовый всплеск» с датой, 4 из 10 — нет; новый поставщик в периоде — «смена поставщика», тот же — нет; в периоде 61 день праздник называется только у дня всплеска (09.05, не 01.05); непрошедшая сверка называется, прошедшая — нет | `test_ai_assistant_pass.py::test_a_one_off_spike_a_new_supplier_and_a_holiday_by_the_spike_are_flagged`, `test_a_failed_verification_is_flagged` | ✅ |
| TC-AN-37 | Черновик «подтвердить» с причиной — просьба исправить, потом черновика нет | `test_ai_assistant_pass.py::test_a_draft_names_a_reason_only_when_it_rejects` | ✅ |
| TC-AN-38 | Агрегаты идей (расчет вручную): 80 % списаний хлеба по понедельникам — строка; 3 дня списаний — шум, не строка; равномерные 14,3 % — не строка; списания на 1000 ₽ выручки 2,5 против среднего 1,17 (≥ 1,5 раза) — строка «против сети»; id строк сквозные | `test_ai_assistant_pass.py::test_the_aggregates_skip_rare_write_offs_and_compare_with_the_network` | ✅ |
| TC-AN-39 | Число идеи должно быть в ее строках: доля из другой строки таблицы — отказ (502 после исправления); больше пяти идей — просьба исправить | `test_ai_assistant_pass.py::test_an_idea_quotes_only_the_rows_it_points_at_and_there_are_at_most_five` | ✅ |
| TC-AN-40 | Импорт проверяет разметку на самом файле: ошибки в 4 строках из 4 — модель исправляет один раз, потом 502; в 2 из 4 (ровно половина) — разметка принимается, ошибки видны в предпросмотре | `test_ai_assistant_pass.py::test_a_marking_that_breaks_more_than_half_of_the_rows_goes_back_but_half_is_a_marking` | ✅ |
| TC-AN-41 | Подтверждение с конфликтом профилей — 409: профиль не создан, предложение остается «предложено» (одна транзакция) | `test_ai_assistant_pass.py::test_a_confirmation_that_clashes_saves_nothing_and_keeps_the_marking_open` | ✅ |
| TC-AN-42 | Тот же файл того же ресторана размечен заново: старая разметка не подтверждается (404), новая — да, повтор — 409 | `test_ai_assistant_pass.py::test_the_same_file_marked_again_replaces_the_undecided_marking` | ✅ |
| TC-AN-43 | Профиль директора — только его ресторана: другой директор сети не подтверждает разметку, не видит и не удаляет профиль, его файлы профилем не читаются (`markable`); владелец удаляет свой профиль | `test_ai_assistant_pass.py::test_a_directors_profile_stays_in_their_restaurant` | ✅ |
| TC-AN-44 | Сетевой профиль УК не может читать заголовок иначе, чем профиль ресторана (409), и файл ресторана читается по-прежнему. **Баг, исправлен 02.11.2026** в `imports.service.save_profile`: раньше сетевой профиль сохранялся и, как более поздний, перебивал чтение ресторана | `test_ai_assistant_pass.py::test_a_network_profile_does_not_override_a_restaurants_own_reading` | ✅ |
| TC-AN-45 | Формат файла изменился (docs/09, «Адаптивный импорт», п. 4): переименованная колонка не роняет загрузку — файл «можно разметить» (`markable`, `no_header`), новая разметка сохраняет то, что уже читает профиль, и спрашивает модель только о новой колонке | `test_ai_assistant_pass.py::test_a_changed_format_offers_a_new_marking_instead_of_failing` | ✅ |
| TC-AN-46 | Разметка файла ресторана хранится под этим рестораном (RLS) с заголовками и образцами строк как основанием | `test_ai_assistant_pass.py::test_a_marking_of_a_restaurants_file_is_kept_under_that_restaurant` | ✅ |
| TC-AN-47 | Проверочные наборы на настоящей модели для предпроверки, идей и разметки; «разметка незнакомого формата верна после одного подтверждения» на модели (ADR 0008, «Реализация»; план 5.5, п. 6) | — (на заглушках — TC-AN-08…16, 36–45) | ⬜ ждет ключа (Q12) |
| TC-AN-48 | docs/09, «Адаптивный импорт»: профиль хранит соответствие колонок; правила шапки и итогов, форматы дат и чисел, поле `extra` для колонок вне модели — в бэклоге (документ поправлен 02.11.2026) | — | ⬜ бэклог |
| TC-AN-49 | Черновик, повторяющий слово-множитель, которое есть в самих фактах («Больше половины списаний…» из флага кода), не отклоняется; слово не из фактов по-прежнему отмечается | `test_ai_assistant_pass.py::test_a_draft_may_quote_the_pre_checks_own_flag`; `test_ai_chat.py::test_small_figures_with_a_unit_are_checked_too` | ✅ |
| TC-AN-50 | Идеи находок: хранятся и показываются все пачки, без отсечки (Q21, ответ 03.11.2026) | `test_ai_discover.py::test_every_batch_of_ideas_is_kept_and_shown` | ✅ |

### Сводка (DG, этап 6, docs/08 часть 1)

| ID | Требование | Тест | Статус |
|----|------------|------|--------|
| TC-DG-01 | Сводка — за прошлую полную неделю пн–вс (Q24) | `test_digests.py::test_week_before_is_the_last_full_monday_to_sunday` | ✅ |
| TC-DG-02 | Индекс процесса 0–100 и статус по формуле docs/08 | `test_digests.py::test_index_and_status` | ✅ |
| TC-DG-03 | Сводку собирает код: 8 процессов, 3–5 проблем, без дублей по объекту; тексты по правилам цитируют вход | `test_digests.py::test_a_digest_is_built_by_the_code_and_written_by_rules` (проверка дублей до 03.11.2026 была пустой — искала у пункта ключ `object`, которого нет; теперь объект берется из ключа находки); на всех сводках демо — TC-DG-35 | ✅ |
| TC-DG-04 | Идемпотентность: одна сводка на неделю; следующая сравнивается с прошлой (KPI, тренд индексов) | `test_digests.py::test_building_again_replaces_and_the_next_week_compares` | ✅ |
| TC-DG-05 | Тексты модели используются, если прошли; иначе — правила | `test_digests.py::test_a_model_writer_is_used_and_its_absence_falls_back` | ✅ |
| TC-DG-06 | Изоляция: директор видит только сводку своего ресторана, без таблицы ресторанов; сводка сети и чужие — нет | `test_digests.py::test_a_director_sees_only_their_restaurants_digest` | ✅ |
| TC-DG-07 | В сводке ресторана — только проверенные находки этого ресторана | `test_digests.py::test_a_restaurants_digest_holds_only_reviewed_findings_of_it` | ✅ |
| TC-DG-08 | Тексты модели: каждое число — из входа сводки; неверное число — одна просьба исправить, затем правила (промпт `digest.v1`) | `test_digests.py::test_the_models_texts_quote_only_the_digests_numbers` | ✅ |
| TC-DG-09 | Модель пишет тексты ровно для пунктов сводки, иначе — исправление, затем правила | `test_digests.py::test_the_model_must_write_exactly_the_digests_items` | ✅ |
| TC-DG-10 | Модель недоступна или лимит исчерпан — сводка пишется по правилам | `test_digests.py::test_an_unreachable_model_leaves_the_rules` | ✅ |
| TC-DG-11 | Модель для сводки ресторана не получает данных других ресторанов | `test_digests.py::test_a_directors_digest_tells_the_model_nothing_of_other_restaurants` | ✅ |
| TC-DG-12 | Расписание: понедельник 08:31 МСК, о прошлой неделе (Q24) | `test_digests.py::test_the_digests_are_scheduled_on_monday_morning_in_moscow` | ✅ |
| TC-DG-13 | Еженедельный прогон: каждая сеть, каждый ресторан и сеть; повтор не дублирует; вызовы модели фоновой работы — в журнале без человека, людям не видны (миграция 0023) | `test_digests.py::test_the_weekly_run_builds_every_restaurant_and_the_network` | ✅ |
| TC-DG-14 | Без модели еженедельный прогон пишет по правилам | `test_digests.py::test_without_the_model_the_weekly_run_writes_by_rules` | ✅ |
| TC-DG-15 | API: последняя сводка и архив недель; «Пересобрать» — директор только свой ресторан, сеть — только УК; чужое — 404 | `test_digests.py::test_the_digest_screens_read_what_was_built`; обход маршрутов `test_isolation_routes.py` | ✅ |
| TC-DG-16 | «Пересобрать» при включенной модели — тексты модели | `test_digests.py::test_the_rebuild_button_writes_by_the_model_when_it_is_on` | ✅ |
| TC-DG-17 | ADR 0009 (вместо «Беру в работу»): пункт попадает в сводку директора, когда УК поставила задачу по находке, и он там «в работе»; без задачи пункта в сводке директора нет | `test_digests.py::test_the_hqs_task_puts_an_item_in_the_directors_digest` | ✅ |
| TC-DG-18 | «Не согласен» — причина из списка (для «Другое» — комментарий), повтор заменяет, можно отозвать; УК видит список; УК сама не «не согласна» | `test_digests.py::test_disagree_with_a_reason_reaches_the_hq` | ✅ |
| TC-DG-19 | «Не согласен» с находкой чужого ресторана или не прошедшей проверку — 404; обход маршрутов | `test_digests.py::test_a_director_cannot_disagree_with_another_restaurants_finding`; `test_isolation_routes.py` | ✅ |
| TC-DG-20 | «Обсудить с ИИ» — чат с находкой пункта (`finding_id`), без нового API | `test_ai_chat.py::test_a_finding_the_person_sees_goes_to_the_model_first_and_is_the_answers_source`, `::test_a_finding_of_another_restaurant_is_not_given_to_the_model_as_context`; экран — e2e `digest.spec.ts` TC-UI-23 | ✅ |
| TC-DG-21 | Проверочный набор текстов сводки (`make eval-digest`): на каждой последней сводке демо — текст модели принят (числа и пункты), «главное» в 1–3 предложениях, без кодов модулей и приветствий, в сводке ресторана нет других ресторанов (утечка — провал набора); цель ≥ 90 % | `test_ai_evals.py::test_the_digest_eval_passes_good_texts_and_catches_bad_ones`, `::test_a_text_that_falls_back_to_the_rules_is_a_miss` | ✅ на заглушке |
| TC-DG-22 | TC-DG-21 на настоящей модели | — | ⬜ ждет ключа (Q12) |
| TC-DG-23 | Ревью 03.11, п. 1: в сводке ресторана, в запросе к модели и на экране нет выручки сети | `test_digests_review.py::test_p1_a_restaurants_digest_holds_no_network_revenue` | ✅ |
| TC-DG-24 | П. 2: «Пересобрать» не держит соединение, пока думает модель | `::test_p2_the_rebuild_holds_no_connection_while_the_model_thinks` | ✅ |
| TC-DG-25 | П. 3: одновременные сборки не падают, выигрывает прочитавшая данные позже; upsert совпадает с индексом и после подготовки запроса psycopg | `::test_p3_builds_at_once_never_fail_and_the_later_read_wins`, `::test_p17_…` | ✅ |
| TC-DG-26 | Пп. 4–6: выдуманные количества и цифры чужого пункта уводят текст в правила; промпт `digest.v2` требует запись чисел как во входе | `::test_p4_…`, `::test_p5_…`, `::test_p6_…` | ✅ |
| TC-DG-27 | П. 7: «Пересобрать» не заменяет текст ИИ текстом по правилам (409) | `::test_p7_a_rebuild_never_replaces_the_models_text_by_rules` | ✅ |
| TC-DG-28 | Пп. 8, 16: проверочный набор ловит падежи названий, кириллическую «М», не считает «п.п.» концом предложения | `::test_p8_p16_…` | ✅ |
| TC-DG-29 | Пп. 10, 12, 13: один товар в двух ресторанах — два пункта; пустой текст не ответ; задачи недели в одном порядке | `::test_p10_…`, `::test_p12_…`, `::test_p13_…` | ✅ |
| TC-DG-30 | Пп. 14–15 и фронтенд пп. 3, 9, 14: двойное «Не согласен» — одна запись; реакция только на пункт своей сводки; комментарий возвращается; список УК по ресторану; у пункта эффект и первый шаг | `::test_p15_…`, `::test_p14_…`, `::test_items_carry_the_effect_and_a_first_step` | ✅ |
| TC-DG-31 | П. 17: понедельничные догоняющие прогоны собирают только недостающее | `::test_p17_the_monday_runs_catch_up_only_what_is_missing` | ✅ |
| TC-DG-32 | Изоляция каждого эндпоинта этапа 6 — другой ресторан (директор) и другая сеть (УК и директор): `GET /digests/latest` (и с `week_start`), `GET /digests/weeks?restaurant_id=` — 404 и пустой архив; `POST /digests/rebuild` чужого — 404, ничего не собрано; директор без `restaurant_id` получает свою, не сетевую; «Не согласен» с `digest_id` чужой сводки или сводки сети — 404; отозвать чужое несогласие нельзя; `GET /digests/disagreements` — только своя сеть, директорам 403 | `test_digests_gaps.py::test_every_digest_endpoint_keeps_to_the_readers_restaurant_and_network` | ✅ |
| TC-DG-33 | «Пересобрать» — в пределах дневного бюджета человека: сверх бюджета модель не вызывается; текста ИИ еще нет — правила (200), есть — остается (409); вызов записан на директора | `test_digests_gaps.py::test_a_directors_rebuild_stays_within_their_daily_budget` | ✅ |
| TC-DG-34 | Сводка ресторана без находок: 8 процессов «норма» 100 без тренда, блоки пусты, «на столе» 0 ₽, главное — «Открытых проблем с оценкой в рублях нет.», нигде нет «None»; без проблем главное начинается с лучшей возможности | `test_digests_gaps.py::test_a_directors_digest_when_the_restaurant_has_no_findings`, `::test_the_rules_headline_of_a_quiet_week_names_no_figure`, `::test_without_problems_the_rules_headline_leads_with_the_best_opportunity` | ✅ |
| TC-DG-35 | Правило отбора: меньше 3 пунктов — сколько есть, без «натягивания»; не больше 5; по убыванию «эффект × уверенность»; проблема и возможность по одному объекту — один раз; риски — только M6 | `test_digests_gaps.py::test_fewer_than_three_items_are_shown_as_they_are_and_never_more_than_five`, `::test_every_demo_digest_by_rules_quotes_only_its_figures_one_item_per_object` | ✅ |
| TC-DG-36 | Тексты по правилам не называют чисел вне входа: на каждой сводке демо они проходят ту же строгую проверку, что текст модели (`digest_writer.strictly`); «Пересобрать» директора дает тот же вход, что недельный прогон (контекст системы); во входе и текстах сводки ресторана нет кодов и названий других ресторанов ни в каком падеже (TC-DG-11 ловил только точное значение JSON) | `test_digests_gaps.py::test_every_demo_digest_by_rules_quotes_only_its_figures_one_item_per_object` | ✅ |
| TC-DG-37 | Индекс, статус, тренд и «что улучшилось» на ручном примере: 12 000 ₽ в ресторане → 76, в сети из 3 → 92; решено к следующей неделе → 100, тренд +24, процесс в «улучшилось»; главное по правилам дословно | `test_digests_gaps.py::test_the_index_trend_and_what_improved_worked_out_by_hand` | ✅ |
| TC-DG-38 | Проверочный набор: 90 % — проходит, 80 % — нет, одна утечка проваливает и при 95 %, пустой набор — не проход | `test_digests_gaps.py::test_the_digest_eval_target_is_90_percent_and_a_leak_fails_it_whatever_the_score` | ✅ |
| TC-DG-39 | Главное по правилам согласует число задач: «выполнена 1 / 21 задача», «выполнено 2 задачи / 11 задач». **Баг, исправлен 03.11.2026** в `app/digests/texts.py`: было «выполнено 21 задача» | `test_digests_gaps.py::test_the_rules_headline_counts_the_weeks_tasks_in_russian` | ✅ |
| TC-DG-40 | Проверочный набор не принимает собственное название ресторана за чужое: R09 «Ресторан на Красном проспекте» и R12 «Ресторан на Красной» делят основу «красн». **Баг, исправлен 03.11.2026**: слово чужого названия, чья основа есть в своем, ловится только в точной форме («на Красной» в сводке R09 — по-прежнему утечка) | `test_digests_gaps.py::test_the_eval_does_not_take_the_restaurants_own_name_for_another_one` | ✅ |
| TC-DG-41 | Недельный прогон: сводка, упавшая с ошибкой, не останавливает остальные; следующий часовой прогон собирает только ее | `test_digests_gaps.py::test_one_failing_digest_does_not_stop_the_weekly_run` | ✅ |

### Интерфейс (UI)

| ID | Требование (docs/10) | Тест | Статус |
|----|----------------------|------|--------|
| TC-UI-01 | Все основные экраны помещаются на телефоне 390 px, у обеих ролей | `e2e/mobile.spec.ts` | ✅ |
| TC-UI-02 | Деньги, проценты, склонения — по-русски | `frontend/src/lib/format.test.ts` | ✅ |
| TC-UI-03 | Параметры движка: неверное значение объяснено и не сохраняется, «вернуть» не теряет другие правки | `e2e/settings.spec.ts` TC-UI-03, `src/app/hq/engineParams.test.ts` | ✅ |
| TC-UI-04 | УК на телефоне открывает все разделы через меню «Еще» | `e2e/mobile.spec.ts` | ✅ |
| TC-UI-05 | Демо-входы не показываются в рабочей сборке | CI: `npm run check:bundle` — в рабочей сборке нет `demo.local`, пароля демо и надписи «Прототип на демонстрационных данных» (TC-ISO-16) | ✅ |
| TC-UI-06 | Директор отмечает задачу сделанной с отчетом, она уходит в «Сделано» | `e2e/work.spec.ts` | ✅ |
| TC-UI-07 | ADR 0009: у директора нет «Взять в работу»; УК ставит задачу из «Решить по находке» (диалог: шаги одной задачей, срок; сетевая — рестораны), находка уходит из списка, задача появляется у директора (прототип — то же: `demo.test.ts` «a finding the HQ assigns…», «lets only the director do the task…») | `e2e/review-fixes.spec.ts` TC-UI-07 — находка ресторана; выбор ресторанов для сетевой находки и срок в e2e не проверяются | ✅ |
| TC-UI-08 | Аналитик УК видит проверки и просрочки, но не кнопки, на которые у него нет прав; ошибки действий показываются | `e2e/review-fixes.spec.ts` | ✅ |
| TC-UI-09 | Выбор периода — только на «Сети» и «Отчете»; опрос пересчета не бесконечен; справочники не перезапрашиваются после действий | `e2e/review-fixes.spec.ts`, `src/api/hooks.test.ts` | ✅ |
| TC-UI-10 | Карточка находки раскрывается до накладных с файлом-источником | `e2e/review-fixes.spec.ts` | ✅ |
| TC-UI-11 | «Сеть»: таблица рестораны × процессы и показатели сети; клик по ячейке открывает находки ресторана по процессу | `e2e/review-fixes.spec.ts` | ✅ |
| TC-UI-12 | Сценарий демо на 10 минут ([14](14-demo-scenario.md)) проходится кликами: сеть → ячейка таблицы → находка → документы → проверка находки → решения → отчет → неделя директора → задача с отчетом | `e2e/demo-scenario.spec.ts` | ✅ |
| TC-UI-13 | Меню «Еще» — диалог для клавиатуры: фокус внутри, Escape закрывает и возвращает фокус; переход по вкладке закрывает меню | `e2e/mobile.spec.ts` | ✅ |
| TC-UI-14 | Фильтры «ресторан» и «процесс» на «Находках» живут в адресе: ссылка «Находки» в меню их сбрасывает | `e2e/review-fixes.spec.ts` | ✅ |
| TC-UI-15 | «Спросить су-шефа» из находки: чат говорит о ней («Говорим о: …»), вопрос-подсказка получает ответ со ссылкой «Открыть находку», ответ озвучивается областью `role="status"`, «Закрыть» закрывает чат | `e2e/chat.spec.ts` TC-UI-15 | ✅ |
| TC-UI-16 | Чат директора: приветствие про его ресторан, вопросы-подсказки с сервера, поле вопроса ограничено 1000 символами, подсказка получает ответ | `e2e/chat.spec.ts` TC-UI-16 | ✅ |
| TC-UI-17 | В прототипе нет блоков ИИ (версии, предпроверка, идеи, разметка): демо отвечает «ассистента нет», незаписанное действие — по-русски | e2e `review.spec.ts` TC-UI-17; `demo.test.ts` «the prototype has no assistant»; код ошибки сервера (`no_header`) доходит до экрана — `client.test.ts` «an error of the API»; причины отклонения у формы и черновика ИИ — серверные четыре, `src/app/hq/reasons.test.ts` | ✅ |
| TC-UI-18 | «Сводка недели» директора (этап 6): главное, показатели, карта процессов, пункты с реакциями («В работе» и «Обсудить с ИИ» — TC-UI-23; «Беру в работу» убрано, ADR 0009); «Не согласен» с «Другое» требует комментарий, причина доходит до УК; без горизонтальной прокрутки | e2e `digest.spec.ts` TC-UI-18; прототип — `demo.test.ts` «demo digests» | ✅ |
| TC-UI-19 | УК: сводка сети и любого ресторана, архив недель; у УК нет «Не согласен» | e2e `digest.spec.ts` TC-UI-19 | ✅ |
| TC-UI-20 | Директор с телефона открывает сводку из нижней панели, без горизонтальной прокрутки (ревью 03.11, фронтенд п. 1) | e2e `mobile.spec.ts` TC-UI-20 | ✅ |
| TC-UI-21 | Реакции — только на последней неделе (и если ее выбрали в архиве); при смене причины комментарий сохраняется (фронтенд пп. 2–3); прототип не показывает выручку сети и фильтрует несогласия по ресторану | e2e `digest.spec.ts` TC-UI-21; `demo.test.ts` «after the review» | ✅ |
| TC-UI-22 | Прототип держит сводки в ресторане директора: чужая сводка и «Пересобрать» чужого — 404, архив чужого — 404 (сервер — пустой список; ни то, ни другое недель не показывает), без ресторана — своя; «Не согласен» с пунктом чужой сводки — 404 и до УК не доходит | `demo.test.ts` «demo digests keep to the director's restaurant» | ✅ |
| TC-UI-23 | Пункты сводки директора — «В работе», «Беру в работу» нет (ADR 0009); «Обсудить с ИИ» открывает чат о находке пункта | e2e `digest.spec.ts` TC-UI-23 | ✅ |
| TC-UI-24 | Связанные находки на карточке: блок «Это одна история?» с названием истории и суммой «один раз», ссылки ведут на другие находки истории и обратно | e2e `review-fixes.spec.ts` TC-UI-24 | ✅ |
| TC-UI-25 | Неделя директора: блок «Можно ли верить цифрам?» с оценкой из 100; оценка директора без сетевой находки, которую он не видит; прототип: директор — 100 без причин, УК — 90 с «без техкарты», оценка = 100 − причины, среднее сети одно, порог — из параметров движка | e2e `review-fixes.spec.ts` TC-UI-25; `demo.test.ts` «gives a director the score without the network finding they are not shown, HQ the whole one» | ✅ |
| TC-UI-26 | Сводка: строка «Качество данных» с оценкой ресторана и средним по сети; в прототипе совпадает с неделей директора | e2e `review-fixes.spec.ts` TC-UI-26; `demo.test.ts` «says the same on the week and in the digest, with the limit from the server» | ✅ |
| TC-UI-27 | История без суммы («решаются вместе»); в историях директора — только его находки (e2e проверяет лишь список директора без чужих находок, состав истории директора — vitest «builds a finding's story…» и сервер TC-ENG-33; уточнено 06.11.2026); прототип строит историю под смотрящего, суммы досок — по правилу сервера; карточка с историей на 390 px | e2e `review-fixes.spec.ts` TC-UI-27, `mobile.spec.ts`; `demo.test.ts` «builds a finding's story for whoever looks», «counts a story's money once» | ✅ |

### Демо-сеть (DEMO)

| ID | Требование (docs/11) | Тест | Статус |
|----|----------------------|------|--------|
| TC-DEMO-01 | Генерация детерминирована (одно зерно — одинаковые байты); состав файлов и план аномалий | `test_demo_generator.py::test_same_seed_same_bytes`, `test_files_and_plan` | ✅ |
| TC-DEMO-02 | Заложенные аномалии восстанавливаются из файлов | `test_planted_overuse_is_recoverable_from_the_files`, `test_planted_prices_and_habits` | ✅ |
| TC-DEMO-03 | Прототип показывает ответы сервера: фильтры списка находок дают то же, что сервер на записанных вариантах (ADR 0007) | `frontend/src/api/demo.test.ts` «filters the findings list exactly as the server did» | ✅ |
| TC-DEMO-04 | Действия в прототипе меняют только затронутое и по правилам сервера: задачи, чек-листы, напоминания, запуск проверок, вердикты | `frontend/src/api/demo.test.ts` «demo actions» | ✅ |
| TC-DEMO-05 | Записанные ответы (`snapshot.json`) подходят под текущие модели ответов API; контракт для фронта (`schema.ts`) актуален | `test_demo_snapshot.py`; CI: `make api-types` без изменений в git | ✅ |
| TC-DEMO-06 | Прототип накладывает действия так, как их видит каждый: директор — без проверок и без имени проверяющего; повтор проверки, свой период и неизвестный id — ошибки сервера, а не падение | `demo.test.ts` «demo follows the server after the actions» | ✅ |
| TC-DEMO-07 | Демо-стенд: календарь стоит на дне демо (`FAI_DEMO_TODAY`); ночной сброс назначен только на стенде (03:07 по Москве); сброс отказывается работать на базе с другими сетями и ничего не удаляет, а полный цикл возвращает демо-сеть как в первый день; стенд не запускается с паролем прототипа | `test_demo_stand.py`: `test_the_stand_lives_on_the_demos_today`, `test_the_nightly_rebuild_is_scheduled_only_on_the_stand`, `test_the_rebuild_refuses_a_database_with_other_networks`, `test_the_rebuild_brings_the_demo_network_back_as_on_the_first_day`, `test_the_stand_refuses_the_prototypes_demo_password` | ✅ |
| TC-DEMO-08 | Конфигурация стенда (ревью 28.10): `/api` проходит без сжатия и буфера (события чата идут сразу); отсутствующий чанк `/assets/*` — 404, а не `index.html`; страница — `no-cache`; ключ модели — только у `backend`, не у `migrate` и `worker`. Как это работает в живом Caddy и Docker, тест не проверяет — только файлы | `test_demo_stand.py::test_the_stand_streams_the_chat_and_never_serves_a_missing_chunk_as_the_page`, `test_only_the_api_gets_the_models_key` | 🟡 |

## Пробелы и план

Найдены на код-ревью 26.10.2026 ([отчет](reviews/2026-10-26-code-review.md)), в работе по порядку:

1. ~~TC-IMP-11/12~~ — исправлено 27.10.2026.
2. ~~TC-REV-04~~ — исправлено 27.10.2026.
3. ~~TC-ISO-09/10, TC-ENG-11/12~~ — тесты добавлены 27.10.2026 (после ревью этапа 3), вместе с TC-ISO-13.
   Остаются **TC-AUTH-07, TC-CAT-03** (интерфейс; нужны Vitest/e2e; TC-UI-05 закрыт проверкой сборки 28.10.2026) и шаг-за-шагом сверка M1 «меньше техкарты» (**TC-ENG-15**).
4. ~~TC-UI-04~~ — меню «Еще» сделано 27.10.2026. **TC-IMP-13** — для полного сценария загрузки.
5. ~~TC-ENG-13~~ — замерено на архитектурном ревью 27.10.2026 ([отчет](reviews/2026-10-27-code-review.md)).

После ревью этапа 6.5 (тестировщик, 06.11.2026):

6. ~~**TC-ENG-43** — часть оценки качества данных показывалась директору целиком, когда видна одна ее находка~~ —
   исправлено: часть пересчитывается по видимым находкам с тем же штрафом и пределом (`overview/service.py::
   visible_quality`); TC-ENG-35 ✅.
7. ~~Расхождения документов с кодом~~ — исправлены формулировки: docs/12 M6 «хватает **не меньше** 1,5 × срок»;
   docs/09 «Кассиры»: как есть — только код или табельный номер целиком.