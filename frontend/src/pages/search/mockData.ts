import type { UserCardDto, CategoryDto, ServiceDto } from "@/api/types";

export const MOCK_USERS: UserCardDto[] = [
  { id: 991, user_id: 111, username: "garant_deal", display_name: "Garant Pro", photo_url: null, banner_url: null, deposit: 1500, description: "", prefix: "admin", is_admin: true, is_arbiter: false, rating: 5.0, reviews_count: 85, deals_count: 142, online: true, country: "US", admin: 1, good: 85, bad: 0, deals_success: 142, deals_failed: 0, deals_arbitrage: 0, deals_sum: 15000, forums: [] },
  { id: 992, user_id: 222, username: "crypto_change", display_name: "Crypto Swap", photo_url: null, banner_url: null, deposit: 5000, description: "", prefix: "vip", is_admin: false, is_arbiter: false, rating: 4.9, reviews_count: 64, deals_count: 98, online: true, country: "AE", admin: 0, good: 64, bad: 0, deals_success: 95, deals_failed: 3, deals_arbitrage: 0, deals_sum: 50000, forums: [] },
  { id: 993, user_id: 333, username: "agency_tg", display_name: "TG Agency", photo_url: null, banner_url: null, deposit: 500, description: "", prefix: null, is_admin: false, is_arbiter: false, rating: 4.8, reviews_count: 22, deals_count: 37, online: false, country: "RU", admin: 0, good: 22, bad: 0, deals_success: 35, deals_failed: 2, deals_arbitrage: 0, deals_sum: 1200, forums: [] },
  { id: 994, user_id: 444, username: "dev_bot", display_name: "Bot Developer", photo_url: null, banner_url: null, deposit: 0, description: "", prefix: null, is_admin: false, is_arbiter: false, rating: 4.7, reviews_count: 15, deals_count: 29, online: true, country: "UA", admin: 0, good: 15, bad: 0, deals_success: 28, deals_failed: 1, deals_arbitrage: 0, deals_sum: 3500, forums: [] },
  { id: 995, user_id: 555, username: "escrow_helper", display_name: "Escrow Helper", photo_url: null, banner_url: null, deposit: 2500, description: "", prefix: "arbiter", is_admin: false, is_arbiter: true, rating: 5.0, reviews_count: 110, deals_count: 231, online: false, country: "GB", admin: 0, good: 110, bad: 0, deals_success: 230, deals_failed: 1, deals_arbitrage: 5, deals_sum: 45000, forums: [] },
];

export const MOCK_CATEGORIES: CategoryDto[] = [
  { id: 901, name: "Социальные сети", slug: "social", icon_key: "more-horizontal", services_count: 24 },
  { id: 902, name: "Криптовалюта", slug: "crypto", icon_key: "bitcoin", services_count: 42 },
  { id: 903, name: "Разработка ботов", slug: "bots", icon_key: "key", services_count: 18 },
  { id: 904, name: "Реклама и пиар", slug: "ads", icon_key: "plane", services_count: 31 },
  { id: 905, name: "UI/UX Дизайн", slug: "design", icon_key: "palette", services_count: 12 },
  { id: 906, name: "Финансовые услуги", slug: "finance", icon_key: "wallet", services_count: 15 },
];

export const MOCK_SERVICES: ServiceDto[] = [
  { id: 981, title: "Продажа готового Telegram канала (15к саб)", description: "Канал с живой аудиторией, тематика IT/Бизнес. Чистый доход от рекламы в месяц около 200$. Передача прав полностью через официального гаранта бота.", price: 450, currency: "USD", status: "active", owner_username: "social_seller", created_at: "2026-01-01T00:00:00Z", category: { id: 901, name: "Социальные сети", slug: "social", icon_key: "more-horizontal", services_count: 24 } },
  { id: 982, title: "Быстрый обмен USDT на рубли (СБП/Тинькофф)", description: "Обмениваю чистый USDT TRC20 на рубли. Минималка от 100$. Чистые резервы. Время проведения сделки в среднем 5 минут.", price: 100, currency: "USD", status: "active", owner_username: "swift_change", created_at: "2026-01-01T00:00:00Z", category: { id: 902, name: "Криптовалюта", slug: "crypto", icon_key: "bitcoin", services_count: 42 } },
  { id: 983, title: "Разработка Telegram Mini App под ключ", description: "Качественная разработка мини-приложений (TMA) любой сложности. Стек: React/TypeScript/FastAPI. Сроки от 7 дней.", price: 800, currency: "USD", status: "active", owner_username: "tma_dev", created_at: "2026-01-01T00:00:00Z", category: { id: 903, name: "Разработка ботов", slug: "bots", icon_key: "key", services_count: 18 } },
  { id: 984, title: "Дизайн аватарок и баннеров для каналов", description: "Оформление вашего Telegram канала, создание уникальных аватарок, баннеров и обложек для постов в едином стиле.", price: 50, currency: "USD", status: "active", owner_username: "pixel_pro", created_at: "2026-01-01T00:00:00Z", category: { id: 905, name: "UI/UX Дизайн", slug: "design", icon_key: "palette", services_count: 12 } },
];
