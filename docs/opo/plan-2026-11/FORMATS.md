# Форматы: что это и что мы про них знаем

Короткая справка для агентов. Полное ТЗ — `TASKS-19-11.md`, доска — `TASKBAR.md`.
Обновлено 19.11.2026 после разбора настоящих файлов с диска.

## Главное: два разных вида, их нельзя путать

| Программа | Что это | Языки | Файл |
|---|---|---|---|
| **Machine Expert** (ME, CODESYS) | программа **ПЛК** | LD и ST | `.project` |
| **Haiwell Happy** | программа **ПЛК** | **только LD** | `.gpc` |
| **ONI Visual Studio** | **экраны** панели оператора | — | папка с `.fsprj` |
| **EasyBuilder** (Weintek) | **экраны** панели оператора | — | `.cmtp` |

ONI Visual Studio — это русская сборка **Flexem Studio**. Отсюда `schemas.flexem.com` в XML и `.fsprj`/`.wcfg`.
EasyBuilder — Weintek, отсюда `.cmtp` и `ebpro-cmtp`.

Ошибка, которую уже сделали один раз: назвать ONI форматом программы ПЛК. ONI — панель. В `plc_formats` у
каждого формата теперь есть `kind`: `plc` или `hmi`.

## Что умеем по каждому

| Формат | Читаем | Пишем | Чем не готов |
|---|---|---|---|
| `me` | да | да | — |
| `hawell` | нет | нет | `.gpc` сжат своим способом |
| `oni` | **да** | **да** | окно перезаписывается без потерь (45/45 окон Достоево); новый проект — по образцу, в ONI не проверен |
| `easybuilder` | да | да | — |

`read` и `write` — разные вещи. «Готово» значит «проверено на настоящем файле», а не «код написан».

## ONI (Flexem): разобрано

Проект — **папка**, не один файл:

```
Line.fsprj                        сам проект: версия, язык (XML, ~250 байт)
HMI/Frame/**/*.wcfg               окна: одно окно — один файл, открытый XML
HMI/System/ConnectInfo.cfg        ПЛК и протокол (Modbus TCP и другие)
HMI/System/GlobalConfigInfo.cfg   стартовое окно (InitWindow)
HMI/System/AlertAndEventConfigInfo.cfg  тревоги и события
HMI/Frame/Startup/Startup.sscfg   заставка
```

Окно — `<HMIWindowInfo>` с `Width`/`Height` и объектами `<GraphicsBase i:type="…">`:

- тип объекта — в `xsi:type` (`SwitchInfo`, `NumericCharInfo`, `StaticTextInfo`, `StaticPictureInfo`, `LineInfo`,
  `RectangleInfo`, `GroupGraphicsInfo`, `AlertAndEventInfo`, `PopupWindowInfo`, `UserRightsBrowserInfo`,
  `QRCodeInfo`, `SingleSelectorInfo`, `CalendarAndTimeInfo`, `FileBrowserInfoDto`, `TouchSourceInfo`, `ArcInfo`);
- геометрия — `NormalInfo/Position` (`X`, `Y`, `Width`, `Height`);
- привязка к ПЛК — `DynamicGraphInfo/ControlAddress`; у клавиши их четыре: `BeforeBitAddress`,
  `AfterBitAddress`, `BeforeWordAddress`, `AfterWordAddress`;
- текст — `NormalInfo/StaticTextContentInfos/StaticTextContentInfo/LabelContent`;
- картинка — base64 PNG в `NormalInfo/ImageData`.

### Адрес: два вида, второй легко пропустить

1. `Abbreviation` — адрес как его видит инженер: `4X_bit3.13`, `0X3079`.
2. `Raw/MainAddress` + `Raw/RegisterId` — число и регистр, `Abbreviation` при этом **пустая**.

Регистры (`RegisterId` → префикс):

| `RegisterId` | Префикс | Что это |
|---|---|---|
| `257` | `SRB` | системный бит |
| `65791` | `LW` | локальное слово |
| `65792` | `SRW` | системное слово |
| `65788` | `SRWR` | системный регистр слова |
| `6` | `4X_bit` | бит Modbus |

Так `MainAddress 13` при `RegisterId 257` — это `SRB13`. Если смотреть только `Abbreviation`, теряется
**159 из 159** числовых полей и 275 из 389 клавиш: в Достоево было найдено 47 адресов вместо 330.

### У окон нет имён

`GraphicsName` пустая: программа ссылается на окна по GUID. Имя окна в разборе — первый текст на нём,
личность — GUID. `oni_objects` принимает GUID, имя файла или это имя.

### Разрешение панели — выбор инженера

Панели разные, и экран под 1024×768 на 800×480 не влезает. Разрешение — параметр при создании проекта, а не
константа. Реестр в `oniproj.RESOLUTIONS`: 800×480, 1024×600, 1024×768, 1280×800, 1366×768, 1920×1080,
640×480, 480×272. Разрешение проекта = самое большое окно (всплывающие меньше и экран не задают).

Достоево нарисовано под **1024×768**.

### Инструменты

`oni_windows`, `oni_objects`, `oni_addresses`, `oni_check`, `oni_panel` — в отдельном инструменте
`oni-project` (экраны панели это не программа ПЛК; в `plc-kit` их больше нет). Проект Haiwell Happy —
тоже отдельный инструмент `haiwell-happy`, а не часть `plc-kit`: другая среда, другой формат, другой язык.
Код — `hub/seed/oni-project/oniproj.py`. Тесты — `tests/test_hub_seed_oni.py` (8 тестов, проверены мутацией).

### Запись: что проверено

`oni_write_window` пишет окно и **читает его снова** — в ответе `same`, совпало ли разобранное окно.
Байт-в-байт не совпадёт (ElementTree поднимает неймспейсы к корню, `<X />` вместо `<X/>`), но для ONI это
одно и то же — это XmlSerializer .NET.

**Проверено на всех 45 окнах Достоево: расхождений 0.**

Тонкость, которую пришлось закрыть: `\r\n` в подписи. XML-парсер по спецификации превращает сырой `\r\n`
в `\n`, поэтому `\r` экранируется в `&#13;`. Без этого 8 окон из 45 расходились — терялся перевод строки
в подписи («Перевести в ⏎ ручной режим»).

`oni_new_project` собирает проект по образцу: `<имя>.fsprj`, окно нужного размера, описание ПЛК, стартовое
окно. **Чего не гарантирует: что ONI Visual Studio откроет файл без замечаний** — программы здесь нет.

### Что осталось по ONI

Генерация экранов из спецификации: объекты, привязки, картинки — а не только пустое окно с заголовком.
И проверка открытия в самой ONI Visual Studio.

## Machine Expert: разобрано

`.project` — контейнер CODESYS V3 (AES + ZIP). `plcproj` его читает, `plcme.Project.load` даёт программы,
классы, переменные, адреса. `plc_project_build` пишет настоящий `.project` из папки ST и шаблона.

Графические POU (LD, CFC) в проекте есть — `plcproj.GRAPHIC` знает их типы (`25e509de-…` → `ld`,
`32d3375e-…` → `cfc`), но **тело LD не разбирается**: это рисунок, а не текст.

`.export` (Проект → Экспорт…) содержит **только объявления** — переменные, устройства, типы. Кода LD/ST в нём
нет. Для разбора LD нужен сам `.project`.

## Haiwell Happy: не разобрано

`.gpc` — бинарный, magic `b0 b0 "HaiWell"`. Энтропия 7,06 бит/байт, zlib-потоков нет, читаемых строк нет.
Свой способ сжатия. Нужен REA-разбор (T24): найти структуру, описать схему, проверить round-trip.

Язык у Haiwell **только LD** — ST там нет.

## Где лежат настоящие файлы

Скачано в `/app/workspace/.tmp/drive/` (не в git — 857 МБ):

| Что | Где |
|---|---|
| Достоево целиком (1479 файлов) | `dostoevo/ЕФБШ 621-01 Достоево/` |
| — экраны ONI | `dostoevo/…/HMI/` (45 окон, 1206 объектов, 330 адресов, 1 ПЛК Modbus TCP) |
| — ПЛК Machine Expert | `dostoevo/…/PLC/Dostoevo.project` (3,2 МБ, 6 программ, 7 классов) |
| Haiwell Happy проект | `D2/DATA/DATA/BLAGOVESCHINSK_LD/600_S1_Благовещенск_01A1_071223.gpc` (51 КБ) |
| 4 экспорта ME | `D2/DATA/DATA/{DOSTAEVO_ST,RODINA_LD,TERANOSTRA_LD,VULKOVSKI_LD}/` (26–37 МБ) |
| Пак картинок (2990 файлов) | `pics/` |
| Стиль «Достоево» | `styles/Достоево.json` |

`V2.2.rar` (154 МБ) — установщик Machine Expert V2.2, проектов там нет. `HaiwellHappy … Setup.rar` — только
установщик. `ONI Visual Studio … Setup.exe` (248 МБ) — только установщик.

## Чем распаковывать

`7z` (p7zip 25.01) **не берёт** эти RAR: «Unsupported Method» на `v6:32M:m3`. Работает `bsdtar`
(`apt-get install -y libarchive-tools`). `unrar` в репозитории нет.

## Выводы, которые стоили времени

1. **ONI — панель, не ПЛК.** Проверять, что за программа перед тобой, прежде чем называть формат.
2. **Адрес в ONI — не только `Abbreviation`.** Без `RegisterId` + `MainAddress` теряется 86% адресов.
3. **`.export` — не код.** Объявления есть, логики нет.
4. **XML-неймспейс — не внешний адрес.** Проверка хаба ругалась на `www.w3.org` и `schemas.flexem.com`;
   теперь неймспейсы вырезаются перед поиском URL (`hub.NAMESPACE_PREFIXES`).
5. **`GraphicsName` — не имя.** Это подпись типа по умолчанию, часто по-китайски («开关/指示灯»).
