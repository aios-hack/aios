# Surrogate feedback adaptation v3

Третья итерация добавляет фактические OPM-ответы 018 и 021 в train; выбранный
предыдущей моделью candidate-020 удержан вне градиентов как transfer-validation.
Сохранены все 490 старых train-сценариев и 105 validation-сценариев.

После 10 эпох интерполяция с исходным member 2 выбрала `alpha=0.825` по 020 при
ограничении historical-test loss ≤1,01. Фактическое отношение — 1,00932798.
Loss на 020 — 0,00626227; дополнительная audit loss на 009 — 0,00707762.

Версия research checkpoint:
`b5e7c05a40e0de161991c0b38573be99277ee50fc6d306dc868f67aa0c2bf685`.
SHA-256 файла:
`d0aa63bf22cc88605c8d4d3ec07713bb4617e3da10ecdeed3122101559cb95db`.

Prospective A/B этот checkpoint **не прошёл**: trajectory выбрал 022 с
2 763 623 896,54 ₽, direct-head выбрал 023 с 2 772 289 226,37 ₽. Поэтому v3
не заменяет v2 и не включается в production. Результат показывает, что локальная
trajectory-адаптация должна использоваться совместно с direct-head, а не вместо неё.
