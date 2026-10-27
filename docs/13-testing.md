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
`[tool.coverage]`). Ниже порога CI красный. На 26.10.2026 — 94 % (159 тестов). Слабые места:

| Модуль | Покрытие | Что не покрыто |
|--------|----------|----------------|
| `analytics/verify.py` | 76 % | сверка сетевых находок M1 и контрактов M3 (см. «Пробелы») |
| `tasks/service.py` | 87 % | редкие ошибки назначения |
| `insights/review.py` | 88 % | ошибки вердиктов («нет находки», повторное подтверждение) |

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

### Изоляция данных (ISO)

| ID | Требование | Тест | Статус |
|----|------------|------|--------|
| TC-ISO-01 | RLS включен на каждой таблице, роль приложения его не обходит | `test_isolation_db.py::test_rls_enabled_on_every_public_table`, `test_app_role_cannot_bypass_rls` | ✅ |
| TC-ISO-02 | Без контекста не видно ничего; директор видит свой ресторан; УК — только свою сеть | `test_no_context_sees_nothing`, `test_director_context_sees_own_rows_only`, `test_hq_context_limited_to_its_tenant` | ✅ |
| TC-ISO-03 | Нельзя писать в чужую сеть и вне своего ресторана | `test_cannot_write_into_another_tenant`, `test_director_cannot_create_restaurant_outside_scope` | ✅ |
| TC-ISO-04 | Рестораны и пользователи через API — только своей сети, управляет администратор УК | `test_isolation_api.py` (10 тестов) | ✅ |
| TC-ISO-05 | Находки и задачи: директор — только свои, без сетевых; чужая сеть — 404 | `test_work_loop.py::test_director_sees_only_own_findings_and_no_network_wide`, `test_other_tenant_cannot_touch_checks_or_tasks` | ✅ |
| TC-ISO-06 | Загрузки, соответствия названий, свежесть данных — в границах ресторана и сети | `test_imports_api.py::test_director_uploads_own_restaurant_and_sees_only_own_batches`, `test_freshness_per_restaurant_and_isolation`, `test_matching_rules_and_isolation`, `test_alias_visibility_and_rights` | ✅ |
| TC-ISO-07 | Находки на проверке, их сверка, вердикт и параметры движка не видны чужой сети; директор не видит находку на проверке | `test_isolation_api.py::test_engine_findings_and_settings_stay_within_the_tenant` | ✅ |
| TC-ISO-08 | Демо-режим соблюдает те же правила: директор не трогает чужие файлы и данные сети, не видит непроверенное | `frontend/src/api/demo.test.ts` | ✅ |
| TC-ISO-09 | Директор не может изменить находку на проверке и увидеть ее через задачу (уровень БД) | — | ⬜ |
| TC-ISO-10 | Повторная загрузка и сопоставление в чужой сети — 404 | — | ⬜ |

### Импорт данных (IMP)

| ID | Требование | Тест | Статус |
|----|------------|------|--------|
| TC-IMP-01 | Разбор CSV (cp1251, `;`) и «красивых» XLSX с заголовками и итогами; номера строк как в файле | `test_import_parsing.py` (11 тестов) | ✅ |
| TC-IMP-02 | Единицы приводятся к базовой; неизвестные и несовместимые — ошибка строки | `test_units_are_converted_to_base_and_unknown_or_incompatible_units_are_errors` | ✅ |
| TC-IMP-03 | Тип файла узнается по заголовку | `test_imports_api.py::test_file_type_is_recognised_without_a_template` | ✅ |
| TC-IMP-04 | Отчет об ошибках по строкам; файл с ошибками не публикуется | `test_report_lists_errors_by_row_and_failed_file_cannot_be_published` | ✅ |
| TC-IMP-05 | Идемпотентность: публикация заменяет период, дубликат файла отклоняется, откат убирает ровно этот файл | `test_publish_replaces_the_period_and_duplicate_files_are_refused`, `test_rollback_removes_exactly_the_batch` | ✅ |
| TC-IMP-06 | Незнакомые названия сопоставляются один раз и запоминаются; исправление пересчитывает файлы | `test_unknown_names_are_matched_once_and_remembered`, `test_wrong_match_is_fixed_and_files_are_reprocessed`, `test_reprocess_applies_the_fixed_match` | ✅ |
| TC-IMP-07 | Справочники сети загружает только УК | `test_reference_data_is_hq_only` | ✅ |
| TC-IMP-08 | Перемещения хранятся один раз и видны обоим ресторанам | `test_transfers_are_stored_once_and_seen_by_both_restaurants` | ✅ |
| TC-IMP-09 | Синхронизация названий 1С:ERP — iiko и контрактные цены | `test_erp_iiko_sync_collapses_names_and_contract_prices_load` | ✅ |
| TC-IMP-10 | Демо-сеть грузится через тот же конвейер с RLS | `test_demo_network_loads_through_the_pipeline_with_rls` | ✅ |
| TC-IMP-11 | Пересекающиеся файлы: более поздний заменяет свои дни; откат возвращает дни раннего, пересчет раннего не затирает поздний | `test_overlapping_files_later_replaces_and_rollback_restores`, `test_rolling_back_an_earlier_file_keeps_what_a_later_one_replaced` | ✅ |
| TC-IMP-12 | Двойное нажатие «Опубликовать» не задваивает строки | `test_publishing_twice_at_once_writes_the_rows_once` | ✅ |
| TC-IMP-13 | e2e: загрузка → сопоставление → публикация → свежесть данных | — | ⬜ |

### Справочники, нормы, периоды (CAT, NORM, PER)

| ID | Требование | Тест | Статус |
|----|------------|------|--------|
| TC-CAT-01 | Техкарты с полуфабрикатами раскладываются до сырья, циклы отклоняются | `test_recipes.py`, `test_imports_api.py::test_recipe_cycle_through_semi_finished_products_is_refused` | ✅ |
| TC-CAT-02 | Подсказки сопоставления: правильный товар первым, чужое не предлагается | `test_matching.py` | ✅ |
| TC-CAT-03 | Поставщик и товар с одинаковым названием сопоставляются независимо (интерфейс) | — | ⬜ |
| TC-NORM-01 | Нормы по умолчанию, права на изменение, проверка значений | `test_norms.py` | ✅ |
| TC-NORM-02 | Причины списания из выгрузки сводятся к стандартным | `test_reasons_of_an_export_map_to_standard_ones`, `test_import_classifies_write_off_reasons_and_warns_about_unknown` | ✅ |
| TC-PER-01 | Периоды: недели пн–вс, последний полный месяц, свой диапазон включительно — одинаково на сервере и в интерфейсе | `test_period.py`, `frontend/src/lib/period.test.ts` | ✅ |

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
| TC-ENG-10 | На демо-сети находится 7 заложенных проблем; повторный пересчет идемпотентен | `test_engine_finds_planted_problems_and_review_gates_directors` | ✅ |
| TC-ENG-11 | Движок не выдает две находки с одним ключом | проверка в `engine.run` | 🟡 (нет отдельного теста) |
| TC-ENG-12 | Удаление устаревших находок не трогает находки с задачами и проверками | — | ⬜ |
| TC-ENG-13 | Пересчет на 100+ ресторанах укладывается во время | — | ⬜ (архитектурное ревью) |
| TC-ENG-14 | M1 сравнивает ресторан с сетью, когда у ресторанов свои дни инвентаризаций (Q15); слишком далекие периоды не сравниваются | `test_m1_compares_restaurants_counting_on_their_own_days` | ✅ |
| TC-ENG-15 | M1 показывает «Расход меньше техкарты» как риск качества без рублей; мелкое отклонение и малый товар — нет (E3) | `test_m1_shows_usage_below_the_recipe_as_a_quality_risk` | 🟡 (нет теста сверки по шагам) |

### Проверка находок (REV)

| ID | Требование (docs/12, «Проверка находок») | Тест | Статус |
|----|------------------------------------------|------|--------|
| TC-REV-01 | Путь находки: найдено → проверено (когда, кто) → в находках; виден с обеих сторон | `test_engine_finds_planted_problems_and_review_gates_directors`, `e2e/review.spec.ts` TC-REV-01 | ✅ |
| TC-REV-02 | Отклонение требует причину, а для «логики» и «другого» — описание | там же, `e2e/review.spec.ts` TC-REV-02, `demo.test.ts` | ✅ |
| TC-REV-03 | Директор не видит проверку и непроверенные находки | там же, `e2e/review.spec.ts` TC-REV-03 | ✅ |
| TC-REV-04 | Сверка с загруженными данными проходит для всех находок демо-сети | там же | 🟡 (сетевые M1 и контракты M3 не пересчитываются) |
| TC-REV-05 | Пересчет сохраняет решения; отклоненная находка не всплывает | там же | ✅ |
| TC-REV-06 | Если после новых данных эффект изменился больше порога, находка снова на проверке | там же | ✅ |
| TC-REV-07 | Непроверенная находка не попадает в отчет руководителю, по ней нельзя поставить задачу | там же | ✅ |
| TC-REV-08 | Комментарий проверяющего и его имя директору не показываются | там же, `demo.test.ts` | ✅ |
| TC-REV-09 | Ручную проверку можно выключить: находки сразу у директоров | `test_review_can_be_switched_off` | ✅ |

### Задачи, проверки изменений, отчет (WORK)

| ID | Требование (docs/05) | Тест | Статус |
|----|----------------------|------|--------|
| TC-WORK-01 | Этап работы по находке выводится из задач и проверок | `test_work_stage.py` (9 тестов) | ✅ |
| TC-WORK-02 | УК ставит шаг директору, сетевая находка — всем директорам, чужому ресторану нельзя | `test_work_loop.py::test_hq_assigns_*`, `test_network_wide_finding_goes_to_every_director`, `test_finding_of_one_restaurant_cannot_go_to_another` | ✅ |
| TC-WORK-03 | Директор выполняет свои задачи с отчетом; результат не пишет человек | `test_director_completes_with_report_and_result_is_pending`, `test_no_endpoint_lets_a_person_write_a_result` | ✅ |
| TC-WORK-04 | Запуск и отклонение проверки изменений; правила вывода результата | `test_launch_sets_tasks_for_test_restaurants`, `test_reject_proposal`, `test_outcome_rules` | ✅ |
| TC-WORK-05 | Отчет руководителю: цифры, провалы, границы периода | `test_head_report_numbers_and_failures`, `test_head_report_period_excludes_earlier_events` | ✅ |

### Обзоры, действия и чат на сервере (OVR, ADR 0007)

| ID | Требование | Тест | Статус |
|----|------------|------|--------|
| TC-OVR-01 | KPI — доли выручки; среднее по сети взвешено по выручке | `test_overview.py::test_kpis_are_shares_of_revenue_and_the_network_is_weighted_by_it` | ✅ |
| TC-OVR-02 | «Это много?» словами: насколько и в какую сторону от сети или нормы | `test_scale_answer_says_how_far_and_which_way` | ✅ |
| TC-OVR-03 | Числа словами как на экранах (₽, склонения, %) | `test_words` | ✅ |
| TC-OVR-04 | Обзор сети, список ресторанов, «Моя неделя», счетчики: суммы из находок, права, чужой ресторан и чужая сеть — 404 | `test_overview_screens_follow_the_access_rules` | ✅ |
| TC-OVR-05 | Находка несет, как ее показать (шкала, состав, динамика, документы), и вывод «что получилось» | `test_findings_carry_how_they_are_shown` | ✅ |
| TC-OVR-06 | Чек-лист задачи отмечает только ее директор; напоминание — администратор УК и только по просроченной | `test_task_checklist_and_reminders` | ✅ |
| TC-OVR-07 | Черновик проверки от системы, предложение, тиражирование только сработавшей и один раз; чужая сеть — 404 | `test_checks_are_drafted_proposed_and_rolled_out` | ✅ |
| TC-OVR-08 | Отчет руководителю с трендом и проверками; чат не показывает директору другие рестораны | `test_head_report_and_chat` | ✅ |

### Интерфейс (UI)

| ID | Требование (docs/10) | Тест | Статус |
|----|----------------------|------|--------|
| TC-UI-01 | Все основные экраны помещаются на телефоне 390 px, у обеих ролей | `e2e/mobile.spec.ts` | ✅ |
| TC-UI-02 | Деньги, проценты, склонения — по-русски | `frontend/src/lib/format.test.ts` | ✅ |
| TC-UI-03 | Параметры движка: неверное значение объяснено и не сохраняется, «вернуть» не теряет другие правки | `e2e/settings.spec.ts`, `src/app/hq/engineParams.test.ts` | ✅ |
| TC-UI-04 | УК на телефоне может открыть все разделы (меню «Еще») | — | ⬜ (дефект, бэклог) |
| TC-UI-05 | Демо-входы не показываются в рабочей сборке | — | ⬜ |
| TC-UI-06 | Директор отмечает задачу сделанной с отчетом, она уходит в «Сделано» | `e2e/work.spec.ts` | ✅ |

### Демо-сеть (DEMO)

| ID | Требование (docs/11) | Тест | Статус |
|----|----------------------|------|--------|
| TC-DEMO-01 | Генерация детерминирована (одно зерно — одинаковые байты) | `test_demo_generator.py::test_same_seed_same_bytes` | ✅ |
| TC-DEMO-02 | Заложенные аномалии восстанавливаются из файлов | `test_planted_overuse_is_recoverable_from_the_files`, `test_planted_prices_and_habits` | ✅ |
| TC-DEMO-03 | Прототип показывает ответы сервера: фильтры списка находок дают то же, что сервер на записанных вариантах (ADR 0007) | `frontend/src/api/demo.test.ts` «filters the findings list exactly as the server did» | ✅ |
| TC-DEMO-04 | Действия в прототипе меняют только затронутое и по правилам сервера: задачи, чек-листы, напоминания, запуск проверок, вердикты | `frontend/src/api/demo.test.ts` «demo actions» | ✅ |
| TC-DEMO-05 | Записанные ответы (`snapshot.json`) подходят под текущие модели ответов API; контракт для фронта (`schema.ts`) актуален | `test_demo_snapshot.py`; CI: `make api-types` без изменений в git | ✅ |

## Пробелы и план

Найдены на код-ревью 26.10.2026 ([отчет](reviews/2026-10-26-code-review.md)), в работе по порядку:

1. ~~TC-IMP-11/12~~ — исправлено 27.10.2026.
2. **TC-REV-04** — сверка сетевых находок M1 и контрактов M3 должна пересчитывать цифры из строк, а не показывать
   сохраненные.
3. **TC-ISO-09/10, TC-ENG-11/12, TC-AUTH-07, TC-CAT-03, TC-UI-05** — недостающие тесты к уже работающему.
4. **TC-UI-04, TC-IMP-13** — после исправления мобильного меню и для полного сценария загрузки.
5. **TC-ENG-13** — нагрузочный прогон движка, вместе с архитектурным ревью в конце этапа 3.
