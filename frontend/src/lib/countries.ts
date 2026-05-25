// Static ISO-3166-1 alpha-2 country list with russian names.
//
// Per the audit (`audit-profile-country-deposit-filter.md` §4.4 +
// §8) the canonical list lives here, in the frontend, not in the
// backend: there is no API behind it, no `pycountry` dependency, no
// seed table. The backend only stores the 2-letter code on
// ``User.country`` and validates ``^[A-Z]{2}$``; the human-readable
// name + flag is purely a display concern, and pinning the list
// client-side keeps the wire payload small (the public
// ``UserCardDto.country`` field is just ``"RU"``, not ``{code, name,
// flag}``).
//
// The flag emoji is **derived**, not stored — ``flagFromCode("RU")``
// returns ``"🇷🇺"`` by mapping each ASCII letter to its
// regional-indicator codepoint (``U+1F1E6 + (letter - 'A')``). This
// works for every valid alpha-2 code without us shipping ~250
// hard-coded emoji glyphs.
//
// The list itself is pulled from the official ISO-3166-1 publication
// (alpha-2 column) and intentionally pinned: adding / removing
// entries is a deliberate change, not something that drifts when an
// upstream npm package bumps. Russian names follow the standard
// Росстандарт ОК-025-2001 spellings ("Россия", not "Российская
// Федерация", etc.).

export interface Country {
  code: string;
  name: string;
  flag: string;
}

// Compute the regional-indicator flag emoji for an alpha-2 code. We
// don't validate here — the call-sites already filter through
// ``countryFromCode`` (which returns ``null`` for unknown codes) so
// any code that reaches this helper is already known-good.
export function flagFromCode(code: string): string {
  if (code.length !== 2) return "";
  const a = code.charCodeAt(0);
  const b = code.charCodeAt(1);
  // 0x1F1E6 is the regional indicator codepoint for "A".
  return (
    String.fromCodePoint(a - 65 + 0x1f1e6) +
    String.fromCodePoint(b - 65 + 0x1f1e6)
  );
}

// Bare ``code -> russian-name`` pairs. Flag emojis are computed on
// the fly by ``buildCountries`` below so we don't double-bookkeep.
//
// Order: russian alphabetical by name (so the dropdown reads as a
// normal "А-Я" list to the user). The first entry — "Россия" — is
// intentionally NOT pinned to the top: the user can find it via
// search just like any other entry, and a special-cased default
// would lie to non-russian users.
const COUNTRY_NAMES: ReadonlyArray<readonly [string, string]> = [
  ["AU", "Австралия"],
  ["AT", "Австрия"],
  ["AZ", "Азербайджан"],
  ["AX", "Аландские острова"],
  ["AL", "Албания"],
  ["DZ", "Алжир"],
  ["AS", "Американское Самоа"],
  ["AI", "Ангилья"],
  ["AO", "Ангола"],
  ["AD", "Андорра"],
  ["AQ", "Антарктида"],
  ["AG", "Антигуа и Барбуда"],
  ["AR", "Аргентина"],
  ["AM", "Армения"],
  ["AW", "Аруба"],
  ["AF", "Афганистан"],
  ["BS", "Багамы"],
  ["BD", "Бангладеш"],
  ["BB", "Барбадос"],
  ["BH", "Бахрейн"],
  ["BY", "Беларусь"],
  ["BZ", "Белиз"],
  ["BE", "Бельгия"],
  ["BJ", "Бенин"],
  ["BM", "Бермуды"],
  ["BG", "Болгария"],
  ["BO", "Боливия"],
  ["BQ", "Бонэйр, Синт-Эстатиус и Саба"],
  ["BA", "Босния и Герцеговина"],
  ["BW", "Ботсвана"],
  ["BR", "Бразилия"],
  ["IO", "Британская территория в Индийском океане"],
  ["VG", "Британские Виргинские острова"],
  ["BN", "Бруней"],
  ["BF", "Буркина-Фасо"],
  ["BI", "Бурунди"],
  ["BT", "Бутан"],
  ["VU", "Вануату"],
  ["VA", "Ватикан"],
  ["GB", "Великобритания"],
  ["HU", "Венгрия"],
  ["VE", "Венесуэла"],
  ["UM", "Внешние малые острова США"],
  ["VN", "Вьетнам"],
  ["GA", "Габон"],
  ["HT", "Гаити"],
  ["GY", "Гайана"],
  ["GM", "Гамбия"],
  ["GH", "Гана"],
  ["GP", "Гваделупа"],
  ["GT", "Гватемала"],
  ["GN", "Гвинея"],
  ["GW", "Гвинея-Бисау"],
  ["DE", "Германия"],
  ["GG", "Гернси"],
  ["GI", "Гибралтар"],
  ["HN", "Гондурас"],
  ["HK", "Гонконг"],
  ["GD", "Гренада"],
  ["GL", "Гренландия"],
  ["GR", "Греция"],
  ["GE", "Грузия"],
  ["GU", "Гуам"],
  ["DK", "Дания"],
  ["JE", "Джерси"],
  ["DJ", "Джибути"],
  ["DM", "Доминика"],
  ["DO", "Доминиканская Республика"],
  ["EG", "Египет"],
  ["ZM", "Замбия"],
  ["EH", "Западная Сахара"],
  ["ZW", "Зимбабве"],
  ["IL", "Израиль"],
  ["IN", "Индия"],
  ["ID", "Индонезия"],
  ["JO", "Иордания"],
  ["IQ", "Ирак"],
  ["IR", "Иран"],
  ["IE", "Ирландия"],
  ["IS", "Исландия"],
  ["ES", "Испания"],
  ["IT", "Италия"],
  ["YE", "Йемен"],
  ["CV", "Кабо-Верде"],
  ["KZ", "Казахстан"],
  ["KH", "Камбоджа"],
  ["CM", "Камерун"],
  ["CA", "Канада"],
  ["QA", "Катар"],
  ["KE", "Кения"],
  ["CY", "Кипр"],
  ["KG", "Киргизия"],
  ["KI", "Кирибати"],
  ["TW", "Китайская Республика (Тайвань)"],
  ["CN", "Китай"],
  ["KP", "КНДР"],
  ["CC", "Кокосовые острова"],
  ["CO", "Колумбия"],
  ["KM", "Коморы"],
  ["CG", "Конго"],
  ["CD", "ДР Конго"],
  ["XK", "Косово"],
  ["CR", "Коста-Рика"],
  ["CI", "Кот-д'Ивуар"],
  ["CU", "Куба"],
  ["KW", "Кувейт"],
  ["CW", "Кюрасао"],
  ["LA", "Лаос"],
  ["LV", "Латвия"],
  ["LS", "Лесото"],
  ["LR", "Либерия"],
  ["LB", "Ливан"],
  ["LY", "Ливия"],
  ["LT", "Литва"],
  ["LI", "Лихтенштейн"],
  ["LU", "Люксембург"],
  ["MU", "Маврикий"],
  ["MR", "Мавритания"],
  ["MG", "Мадагаскар"],
  ["YT", "Майотта"],
  ["MO", "Макао"],
  ["MK", "Северная Македония"],
  ["MW", "Малави"],
  ["MY", "Малайзия"],
  ["ML", "Мали"],
  ["MV", "Мальдивы"],
  ["MT", "Мальта"],
  ["MA", "Марокко"],
  ["MQ", "Мартиника"],
  ["MH", "Маршалловы Острова"],
  ["MX", "Мексика"],
  ["FM", "Микронезия"],
  ["MZ", "Мозамбик"],
  ["MD", "Молдавия"],
  ["MC", "Монако"],
  ["MN", "Монголия"],
  ["MS", "Монтсеррат"],
  ["MM", "Мьянма"],
  ["NA", "Намибия"],
  ["NR", "Науру"],
  ["NP", "Непал"],
  ["NE", "Нигер"],
  ["NG", "Нигерия"],
  ["NL", "Нидерланды"],
  ["NI", "Никарагуа"],
  ["NU", "Ниуэ"],
  ["NZ", "Новая Зеландия"],
  ["NC", "Новая Каледония"],
  ["NO", "Норвегия"],
  ["AE", "ОАЭ"],
  ["OM", "Оман"],
  ["BV", "Остров Буве"],
  ["IM", "Остров Мэн"],
  ["NF", "Остров Норфолк"],
  ["CX", "Остров Рождества"],
  ["SH", "Острова Святой Елены, Вознесения и Тристан-да-Кунья"],
  ["KY", "Острова Кайман"],
  ["CK", "Острова Кука"],
  ["TC", "Острова Тёркс и Кайкос"],
  ["PK", "Пакистан"],
  ["PW", "Палау"],
  ["PS", "Палестина"],
  ["PA", "Панама"],
  ["PG", "Папуа — Новая Гвинея"],
  ["PY", "Парагвай"],
  ["PE", "Перу"],
  ["PN", "Острова Питкэрн"],
  ["PL", "Польша"],
  ["PT", "Португалия"],
  ["PR", "Пуэрто-Рико"],
  ["RE", "Реюньон"],
  ["RU", "Россия"],
  ["RW", "Руанда"],
  ["RO", "Румыния"],
  ["SV", "Сальвадор"],
  ["WS", "Самоа"],
  ["SM", "Сан-Марино"],
  ["ST", "Сан-Томе и Принсипи"],
  ["SA", "Саудовская Аравия"],
  ["SZ", "Эсватини"],
  ["MP", "Северные Марианские острова"],
  ["SC", "Сейшелы"],
  ["BL", "Сен-Бартелеми"],
  ["MF", "Сен-Мартен (французская часть)"],
  ["PM", "Сен-Пьер и Микелон"],
  ["SN", "Сенегал"],
  ["VC", "Сент-Винсент и Гренадины"],
  ["KN", "Сент-Китс и Невис"],
  ["LC", "Сент-Люсия"],
  ["RS", "Сербия"],
  ["SG", "Сингапур"],
  ["SX", "Синт-Мартен (нидерландская часть)"],
  ["SY", "Сирия"],
  ["SK", "Словакия"],
  ["SI", "Словения"],
  ["SB", "Соломоновы Острова"],
  ["SO", "Сомали"],
  ["SD", "Судан"],
  ["SR", "Суринам"],
  ["US", "США"],
  ["SL", "Сьерра-Леоне"],
  ["TJ", "Таджикистан"],
  ["TH", "Таиланд"],
  ["TZ", "Танзания"],
  ["TL", "Восточный Тимор"],
  ["TG", "Того"],
  ["TK", "Токелау"],
  ["TO", "Тонга"],
  ["TT", "Тринидад и Тобаго"],
  ["TV", "Тувалу"],
  ["TN", "Тунис"],
  ["TM", "Туркмения"],
  ["TR", "Турция"],
  ["UG", "Уганда"],
  ["UZ", "Узбекистан"],
  ["UA", "Украина"],
  ["WF", "Уоллис и Футуна"],
  ["UY", "Уругвай"],
  ["FO", "Фарерские острова"],
  ["FJ", "Фиджи"],
  ["PH", "Филиппины"],
  ["FI", "Финляндия"],
  ["FK", "Фолклендские острова"],
  ["FR", "Франция"],
  ["GF", "Французская Гвиана"],
  ["PF", "Французская Полинезия"],
  ["TF", "Французские Южные и Антарктические территории"],
  ["HM", "Остров Херд и острова Макдональд"],
  ["HR", "Хорватия"],
  ["CF", "ЦАР"],
  ["TD", "Чад"],
  ["ME", "Черногория"],
  ["CZ", "Чехия"],
  ["CL", "Чили"],
  ["CH", "Швейцария"],
  ["SE", "Швеция"],
  ["SJ", "Шпицберген и Ян-Майен"],
  ["LK", "Шри-Ланка"],
  ["EC", "Эквадор"],
  ["GQ", "Экваториальная Гвинея"],
  ["ER", "Эритрея"],
  ["EE", "Эстония"],
  ["ET", "Эфиопия"],
  ["ZA", "ЮАР"],
  ["GS", "Южная Георгия и Южные Сандвичевы Острова"],
  ["KR", "Республика Корея"],
  ["SS", "Южный Судан"],
  ["JM", "Ямайка"],
  ["JP", "Япония"],
] as const;

function buildCountries(): readonly Country[] {
  const built = COUNTRY_NAMES.map(([code, name]) => ({
    code,
    name,
    flag: flagFromCode(code),
  }));
  // sort alphabetically by russian name using locale-aware compare so
  // "Ё" and "Й" land where they belong
  built.sort((a, b) => a.name.localeCompare(b.name, "ru"));
  return built;
}

export const COUNTRIES: readonly Country[] = buildCountries();

const _BY_CODE: ReadonlyMap<string, Country> = new Map(
  COUNTRIES.map((c) => [c.code, c]),
);

// Look up a country by alpha-2 code (case-insensitive). Returns
// ``null`` if the code is not in our static list — call-sites should
// gracefully degrade (e.g. hide the flag chip) rather than render a
// placeholder.
export function countryFromCode(code: string | null | undefined): Country | null {
  if (!code) return null;
  return _BY_CODE.get(code.toUpperCase()) ?? null;
}
