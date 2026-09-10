# Surrogate feedback adaptation v4

Четвёртая research-итерация добавляет OPM-траектории candidate-022, 023 и 024
к прежнему feedback train-набору. Новый champion candidate-025 полностью удержан
вне градиентов как local validation; candidate-009 сохранён как audit. Historical
replay содержит 490 train- и 105 validation-сценариев с раздельными scenario ID.

Полный checkpoint после 10 эпох снизил aggregate validation loss с 0,01626442
до 0,00453931 и local loss на candidate-025 до 0,00087520, но его historical
loss ratio 1,0435 превышает защитный предел.

Уточнённая weight interpolation выбрала `alpha=0.20`. Её historical loss ratio
равен 1,00884698 (предел 1,01), а loss на удержанном candidate-025 — 0,06729659
против 0,10328345 у исходного parent checkpoint.

Версия research checkpoint:
`0999e2ad8b0571288a148d116f7dbcac0d6a583ee2eaf88186be528ae1a3d691`.
SHA-256 файла:
`3923096d3e6c1b233730d32343167e54cf2cb960e6a681ac3c4d5ae49591ccc7`.

Модель не включена в production. Её можно использовать только в следующем
prospective screening, после чего оба заранее замороженных arm должны пройти OPM.
