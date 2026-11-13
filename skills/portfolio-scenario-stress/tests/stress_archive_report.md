# Регрессия normalize_stress.py по архиву (Задача 4.2)

Авто-сгенерировано `normalize_stress.py --batch`. Не редактировать руками.

| Файл | Дата | run_id | Базы `delta_rub` | Метод | Восстановлено | Отсутствует безвозвратно |
|---|---|---|---|---|---|---|
| stress-2026-05-11-mfc-shell-d1-20mo.yaml | 2026-05-11 | stress-2026-05-11-mfc-shell-d1-20mo | price | 2 | price_delta_rub | total_return_rub (нет bond_carry в архиве) |
| stress-2026-05-11-mfc-shell-d1.yaml | 2026-05-11 | stress-2026-05-11-mfc-shell-d1 | price | 2 | price_delta_rub | total_return_rub (нет bond_carry в архиве) |
| stress-2026-05-12-mfc-shell-d1-20mo.yaml | 2026-05-12 | PSS-20260512-MFC-D1-20MO | price | 2 | price_delta_rub | total_return_rub (нет bond_carry в архиве) |
| stress-2026-05-29-shell-d1-2026.yaml | 2026-05-29 | PSS-20260529-SHELL_D1_2026 | price | 2 | price_delta_rub | total_return_rub (нет bond_carry в архиве) |
| stress-2026-05-29-shell-d1-2027.yaml | 2026-05-29 | PSS-20260529-SHELL_D1_2027 | price | 2 | price_delta_rub | total_return_rub (нет bond_carry в архиве) |
| stress-2026-06-08-mfc-shell-d1-6-12-24.yaml | 2026-06-08 | PSS-20260608-MFC_SHELL_D1_6_12_24 | price | 2 | price_delta_rub | total_return_rub (нет bond_carry в архиве) |
| stress-2026-06-28-shell-d1.yaml | 2026-06-28 | PSS-20260628-SHELL_D1 | unknown | 4 | price_delta_rub | — |
| stress-2026-07-02-macro-shell-d1.yaml | 2026-07-02 | PSS-20260702-MACRO_SHELL_D1 | price | 2 | carry_rub, price_delta_rub, total_return_rub | — |
| stress-2026-07-05-geopol-ru-west-shell-d1.yaml | 2026-07-05 | PSS-20260705-GEOPOL_RU_WEST_SHELL_D1 | unknown | 4 | carry_rub, price_delta_rub, total_return_rub | — |
| stress-2026-07-15-geopol-ru-west-shell-d1.yaml | 2026-07-15 | PSS-20260715-GEOPOL_RU_WEST_SHELL_D1 | total_return | 3 | carry_rub, price_delta_rub, total_return_rub | — |
| stress-2026-07-23-geopol-ru-west-shell-d1.yaml | 2026-07-23 | PSS-20260723-GEOPOL_RU_WEST_SHELL_D1 | total_return | 3 | carry_rub, price_delta_rub, total_return_rub | — |
| stress-2026-08-04-geopol-ru-west-shell-d1.yaml | 2026-08-04 | PSS-20260804-GEOPOL_RU_WEST_SHELL_D1 | total_return | 3 | carry_rub, price_delta_rub, total_return_rub | — |
| stress-2026-08-06-geopol-ru-west-shell-d1.yaml | 2026-08-06 | PSS-20260806-GEOPOL_RU_WEST_SHELL_D1 | total_return | 3 | carry_rub, price_delta_rub, total_return_rub | — |
| stress-2026-08-15-geopol-ru-west-shell-d1.yaml | 2026-08-15 | PSS-20260815-GEOPOL_RU_WEST_SHELL_D1 | total_return | 3 | carry_rub, price_delta_rub, total_return_rub | — |
| stress-2026-08-27-geopol-ru-west-shell-d1.yaml | 2026-08-27 | PSS-20260827-GEOPOL_RU_WEST_SHELL_D1 | total_return | 3 | carry_rub, price_delta_rub, total_return_rub | — |
| stress-2026-09-03-geopol-ru-west-shell-d1.yaml | 2026-09-03 | PSS-20260904-GEOPOL_RU_WEST_SHELL_D1 | total_return | 3 | carry_rub, price_delta_rub, total_return_rub | — |
| stress-2026-09-18-geopol-ru-west-macro-d.yaml | 2026-09-18 | PSS-20260918-GEOPOL-RU-WEST-MACRO-D | price | 2 | carry_rub, price_delta_rub, total_return_rub | — |

## Файлы с `basis: unknown` — детали

Официальная база НЕ определена (не price, не total_return) — задача 4.1 запрещает угадывать. Диагностика ниже — дополнительная находка, не замена определению; помечена отдельно, где числа совпали с известным классом ошибки (weight_pct домножен на `base_value_rub` вместо `positions_value_rub` в самом прогоне).

### stress-2026-06-28-shell-d1.yaml

- delta_rub=3153867 не сходится ни с price_sum=2717598 (diff=436269), ни с price_sum+carry_sum (carry_sum отсутствует); ПОХОЖЕ на независимый исторический дефект — delta_rub ≈ price_sum × (base_value_rub/positions_value_rub) = 3153846 (тот же класс ошибки, что регрессия positions_value_rub 2026-09-18, но в самом прогоне, не в валидаторе)
- delta_rub=3536574 не сходится ни с price_sum=3047367 (diff=489207), ни с price_sum+carry_sum (carry_sum отсутствует); ПОХОЖЕ на независимый исторический дефект — delta_rub ≈ price_sum × (base_value_rub/positions_value_rub) = 3536553 (тот же класс ошибки, что регрессия positions_value_rub 2026-09-18, но в самом прогоне, не в валидаторе)
- delta_rub=4173444 не сходится ни с price_sum=3596124 (diff=577320), ни с price_sum+carry_sum (carry_sum отсутствует); ПОХОЖЕ на независимый исторический дефект — delta_rub ≈ price_sum × (base_value_rub/positions_value_rub) = 4173402 (тот же класс ошибки, что регрессия positions_value_rub 2026-09-18, но в самом прогоне, не в валидаторе)
- delta_rub=4569768 не сходится ни с price_sum=3937644 (diff=632124), ни с price_sum+carry_sum (carry_sum отсутствует); ПОХОЖЕ на независимый исторический дефект — delta_rub ≈ price_sum × (base_value_rub/positions_value_rub) = 4569744 (тот же класс ошибки, что регрессия positions_value_rub 2026-09-18, но в самом прогоне, не в валидаторе)
- delta_rub=5469933 не сходится ни с price_sum=4713273 (diff=756660), ни с price_sum+carry_sum (carry_sum отсутствует); ПОХОЖЕ на независимый исторический дефект — delta_rub ≈ price_sum × (base_value_rub/positions_value_rub) = 5469882 (тот же класс ошибки, что регрессия positions_value_rub 2026-09-18, но в самом прогоне, не в валидаторе)
- delta_rub=1778436 не сходится ни с price_sum=1532424 (diff=246012), ни с price_sum+carry_sum (carry_sum отсутствует); ПОХОЖЕ на независимый исторический дефект — delta_rub ≈ price_sum × (base_value_rub/positions_value_rub) = 1778421 (тот же класс ошибки, что регрессия positions_value_rub 2026-09-18, но в самом прогоне, не в валидаторе)
- delta_rub=1963245 не сходится ни с price_sum=1691676 (diff=271569), ни с price_sum+carry_sum (carry_sum отсутствует); ПОХОЖЕ на независимый исторический дефект — delta_rub ≈ price_sum × (base_value_rub/positions_value_rub) = 1963236 (тот же класс ошибки, что регрессия positions_value_rub 2026-09-18, но в самом прогоне, не в валидаторе)
- delta_rub=2784747 не сходится ни с price_sum=2399538 (diff=385209), ни с price_sum+carry_sum (carry_sum отсутствует); ПОХОЖЕ на независимый исторический дефект — delta_rub ≈ price_sum × (base_value_rub/positions_value_rub) = 2784729 (тот же класс ошибки, что регрессия positions_value_rub 2026-09-18, но в самом прогоне, не в валидаторе)
### stress-2026-07-05-geopol-ru-west-shell-d1.yaml

- delta_rub=3823758 не сходится ни с price_sum=1846461 (diff=1977297), ни с price_sum+carry_sum (1714419)
- delta_rub=3910740 не сходится ни с price_sum=1941546 (diff=1969194), ни с price_sum+carry_sum (1687188)
- delta_rub=4284492 не сходится ни с price_sum=2147361 (diff=2137131), ни с price_sum+carry_sum (1832616)
- delta_rub=5318724 не сходится ни с price_sum=2681637 (diff=2637087), ни с price_sum+carry_sum (2275308)
- delta_rub=6703983 не сходится ни с price_sum=2378982 (diff=4325001), ни с price_sum+carry_sum (3972360)
- delta_rub=6878472 не сходится ни с price_sum=2504775 (diff=4373697), ни с price_sum+carry_sum (3998658)
- delta_rub=7337814 не сходится ни с price_sum=2623638 (diff=4714176), ни с price_sum+carry_sum (4327515)
- delta_rub=8731836 не сходится ни с price_sum=2946261 (diff=5785575), ни с price_sum+carry_sum (5369430)
- delta_rub=10775865 не сходится ни с price_sum=3049644 (diff=7726221), ни с price_sum+carry_sum (7259820)
- delta_rub=11108472 не сходится ни с price_sum=3244359 (diff=7864113), ни с price_sum+carry_sum (7366854)
- delta_rub=11454972 не сходится ни с price_sum=3243873 (diff=8211099), ни с price_sum+carry_sum (7718394)
- delta_rub=13081212 не сходится ни с price_sum=3329988 (diff=9751224), ни с price_sum+carry_sum (9261939)
