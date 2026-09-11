# Архитектура решения

Схемы снимались с кода, а не рисовались по замыслу. Имена модулей в блоках —
настоящие пути в репозитории.

## 1. Общая картина

Три слоя: точки входа, тринадцать ограниченных контекстов, общее ядро.
Зависимости идут только сверху вниз.

```mermaid
graph TD
    CLI["interfaces/cli<br/>aios · 17 команд"]
    HTTP["interfaces/http<br/>консоль · ассистент · дашборд"]

    subgraph Contexts["backend/contexts — 13 контекстов"]
        direction LR
        OPT["optimization<br/>поиск расписания"]
        SUR["surrogate<br/>быстрый прогноз"]
        SIM["simulation<br/>запуск OPM"]
        ECO["economics<br/>ЧДД"]
        SCH["schedule<br/>расписание и проверки"]
        CON["constraints<br/>условия задачи"]
        POL["policy<br/>агенты и правила"]
        RES["reservoir<br/>дек Model_Z"]
        CNT["connectivity<br/>связность скважин"]
        ROB["robustness<br/>устойчивость"]
        RUN["runs<br/>прогоны и сдача"]
        SHW["showcase<br/>витрина интерфейса"]
        AST["assistant<br/>Джарвис"]
    end

    SHARED["backend/shared<br/>errors · settings · paths · i18n · hashing · json_io"]

    CLI --> Contexts
    HTTP --> Contexts
    Contexts --> SHARED

    style Contexts fill:#f6f5f2,stroke:#c9c5bd
    style SHARED fill:#eef2f6,stroke:#9fb3c8
```

Правило слоёв внутри контекста: `domain` не знает ни про `application`,
ни про `infrastructure`. Сторож — `tests/architecture/backend/test_context_boundaries.py`,
списки исключений пусты.

## 2. Сквозной прогон: управление → симулятор → ЧДД

Главный поток `aios run full`. Суть решения в том, что поиск идёт по суррогату,
а подтверждение — по настоящему гидродинамическому симулятору.

```mermaid
flowchart TD
    START(["aios run full --case"]) --> CASE["constraints<br/>загрузка кейса"]
    CASE --> SEARCH

    subgraph SEARCH["Поиск — тысячи итераций на суррогате"]
        direction TB
        POLICY["policy<br/>агенты: месторождение → группа → скважина"]
        CAND["кандидат: управляющая последовательность"]
        PRED["surrogate<br/>прогноз добычи и закачки"]
        GATES{"гейты<br/>optimization/domain/gates"}
        POLICY --> CAND --> PRED --> GATES
        GATES -->|отклонён| POLICY
    end

    SEARCH -->|финалисты| VERIFY

    subgraph VERIFY["Проверка — единицы запусков на OPM"]
        direction TB
        DECK["reservoir<br/>сборка дека Model_Z"]
        OPM["simulation<br/>запуск OPM Flow в контейнере"]
        RESP["отклик: дебиты, давления, обводнённость"]
        DECK --> OPM --> RESP
    end

    VERIFY --> VALID["schedule<br/>проверка ограничений"]
    VALID --> NPV["economics<br/>расчёт ЧДД по методологии"]
    NPV --> CMP{"заявленный ЧДД<br/>= расчётный?"}
    CMP -->|да| SUBMIT["runs<br/>пакет сдачи"]
    CMP -->|нет| FAIL(["отказ: прогноз не подтверждён"])

    SUBMIT --> OUT(["claimed_npv.json<br/>well_schedule.inc<br/>хеши конфигурации"])

    style SEARCH fill:#eef4ee,stroke:#8fae8f
    style VERIFY fill:#f7f0e8,stroke:#c9a87c
    style FAIL fill:#f7e9e6,stroke:#c98a7c
```

Почему так: полный прогон ГГДМ дорог по времени, суррогат — дёшев. Поиск
перебирает варианты на суррогате, но **ни один результат не принимается на веру**:
финалисты пересчитываются настоящим OPM, и если заявленный ЧДД не сошёлся
с расчётным, прогон отклоняется.

## 3. Четыре гейта отбора

Кандидат проходит их по очереди; каждый умеет отклонить.

```mermaid
flowchart LR
    C["кандидат"] --> G1["ood_threshold<br/>в области обучения?"]
    G1 -->|да| G2["bhp_tolerance<br/>забойное давление<br/>в допуске?"]
    G2 -->|да| G3["incumbent<br/>лучше текущего<br/>чемпиона?"]
    G3 -->|да| G4["opm_budget<br/>бюджет запусков<br/>не исчерпан?"]
    G4 -->|да| OK(["на проверку OPM"])

    G1 -->|нет| X1(["отклонён"])
    G2 -->|нет| X2(["отклонён"])
    G3 -->|нет| X3(["отклонён"])
    G4 -->|нет| X4(["отложен"])

    style OK fill:#eef4ee,stroke:#8fae8f
```

`ood_threshold` — защита от главного риска суррогата: модель уверенно
ошибается за пределами обучающей выборки. Кандидат, непохожий на то, что
модель видела, до OPM не доходит.

## 4. Иерархия агентов политики

Решение принимается не одним агентом, а по уровням — от месторождения к скважине.

```mermaid
graph TD
    FIELD["field<br/>уровень месторождения:<br/>баланс закачки и отбора"]
    GROUP["group<br/>уровень группы:<br/>распределение по участкам"]
    WELL["well<br/>уровень скважины:<br/>режим конкретной скважины"]

    WATER["water<br/>обводнённость"]
    PRESS["pressure<br/>пластовое давление"]
    PROJ["projection<br/>проекция на ограничения"]

    FIELD --> GROUP --> WELL
    WATER -.-> FIELD
    WATER -.-> GROUP
    PRESS -.-> FIELD
    PRESS -.-> GROUP
    PROJ -.-> WELL

    style FIELD fill:#eef2f6,stroke:#9fb3c8
    style GROUP fill:#eef2f6,stroke:#9fb3c8
    style WELL fill:#eef2f6,stroke:#9fb3c8
```

Реестр агентов — `policy/domain/agents/registry.py`. Каждое решение попадает
в след (`policy/domain/trace.py`), поэтому инженер может увидеть, **почему**
агент выбрал именно этот режим.

## 5. Объяснимость: Джарвис

Отдельный контекст, который отвечает на вопросы по системе и показывает,
что происходило в прогоне.

```mermaid
flowchart TD
    Q(["вопрос инженера"]) --> ORCH["assistant/application<br/>оркестратор"]

    ORCH --> TOOLS["инструменты"]
    TOOLS --> T1["runs<br/>история прогонов"]
    TOOLS --> T2["council<br/>решения агентов"]
    TOOLS --> T3["docs<br/>поиск по документации"]
    TOOLS --> T4["knowledge<br/>термины и экраны"]

    ORCH --> RAG["docs_index<br/>BM25, 1244 чанка"]
    ORCH --> KB["knowledge<br/>71 термин · 18 узлов · 11 экранов"]

    ORCH --> LLM["llm<br/>OpenRouter · без ключа — фикстуры"]
    LLM --> CARD["карточки-ответы<br/>в интерфейсе"]

    style ORCH fill:#f6f5f2,stroke:#c9c5bd
```

RAG собран на чистой стандартной библиотеке — без внешних зависимостей.
Индексируются документы репозитория и соседнего репозитория документации.

## 6. Развёртывание

```mermaid
flowchart LR
    subgraph Image["Docker-образ aios:latest"]
        direction TB
        APP["backend + собранный frontend/dist"]
        ENTRY["docker/entrypoint.sh<br/>свободный CMD"]
    end

    ENTRY --> S1["webdata<br/>сборка витрины"]
    ENTRY --> S2["web :8000<br/>интерфейс и API"]
    ENTRY --> S3["jarvis :8010<br/>ассистент"]
    ENTRY --> S4["selfcheck<br/>сверка ЧДД"]
    ENTRY --> S5["npv · emit · tests"]

    DATA[("данные организаторов<br/>монтируются снаружи")] -.-> S1
    DATA -.-> S4

    style Image fill:#eef2f6,stroke:#9fb3c8
```

Данные организаторов в образ не входят — монтируются томом. Поэтому образ
собирается и запускается на чистой машине, а расчёт требует смонтированных
данных.
