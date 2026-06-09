import { describe, expect, it } from "vitest";
import { formatPaymentProvider } from "./paymentProviders";

describe("formatPaymentProvider", () => {
  it("labels known payment providers", () => {
    expect(formatPaymentProvider("cryptobot")).toBe("CryptoBot");
    expect(formatPaymentProvider("crystalpay")).toBe("Crystalpay");
  });

  it("renders unknown runtime providers as neutral", () => {
    expect(formatPaymentProvider("provider_reconciled")).toBe("Провайдер неизвестен");
    expect(formatPaymentProvider(" cryptobot ")).toBe("Провайдер неизвестен");
    expect(formatPaymentProvider(null)).toBe("Провайдер неизвестен");
  });
});
