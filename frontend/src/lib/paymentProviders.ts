export const UNKNOWN_PAYMENT_PROVIDER_LABEL = "Провайдер неизвестен";

export function formatPaymentProvider(value: unknown): string {
  if (value === "cryptobot") return "CryptoBot";
  if (value === "crystalpay") return "Crystalpay";
  return UNKNOWN_PAYMENT_PROVIDER_LABEL;
}
