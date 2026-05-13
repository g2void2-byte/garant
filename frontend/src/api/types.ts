export interface CategoryDto {
  id: number;
  slug: string;
  name: string;
  icon_key: string;
  services_count: number;
}

export interface ServiceDto {
  id: number;
  owner_username: string;
  title: string;
  description: string;
  price: number;
  currency: string;
  status: string;
  category: CategoryDto;
  created_at?: string | null;
}

export interface UserCardDto {
  id: number;
  user_id: number;
  username: string;
  balance: number;
  admin: number;
  prefix: "admin" | "arbiter" | null;
  good: number;
  bad: number;
  deposit: number;
  rating: number;
  reviews_count: number;
  deals_count: number;
  deals_sum: number;
  online: boolean;
  banner_url?: string | null;
  description: string;
  forums: { name?: string; url?: string }[];
}

export interface DealDto {
  id: number;
  buyer: string;
  seller: string;
  sum: number;
  description: string;
  pay_comission: string;
  status: string;
  confirm_buyer: boolean;
  confirm_seller: boolean;
  role: "buyer" | "seller";
  created_at: string | null;
}

export interface ReviewDto {
  id: number;
  deal_id: number | null;
  author_username: string;
  target_username: string;
  rating: number;
  text: string;
  created_at: string;
}

export interface NotificationDto {
  id: number;
  type: "deals" | "deposits" | "system" | string;
  title: string;
  body: string;
  payload: Record<string, unknown>;
  is_read: boolean;
  created_at: string;
}

export interface NotificationCountersDto {
  all: number;
  deals: number;
  deposits: number;
  system: number;
  unread: number;
}

export interface SupportPersonDto {
  id: number;
  user_id: number;
  username: string;
  admin: number;
  prefix: "admin" | "arbiter";
}

export interface InvoiceDto {
  invoice_id: string | number;
  pay_url: string;
  amount: number;
  asset: string;
}

export interface DepositDto {
  id: number;
  amount: number;
  status: string;
  created_at: string;
  released_at: string | null;
}
