import { describe, expect, it } from "vitest";

import { formatPrice, percentOff, rupeesToPaise } from "./format";

describe("formatPrice", () => {
  it("formats paise as rupees with Indian digit grouping", () => {
    expect(formatPrice(5999900)).toBe("₹59,999");
    expect(formatPrice(11490000)).toBe("₹1,14,900");
  });

  it("keeps paise when the amount is not whole rupees", () => {
    expect(formatPrice(12345)).toBe("₹123.45");
  });
});

describe("helpers", () => {
  it("converts rupees to integer paise without float drift", () => {
    expect(rupeesToPaise(19.99)).toBe(1999);
  });

  it("computes discount percent only when MRP is higher", () => {
    expect(percentOff(7500, 10000)).toBe(25);
    expect(percentOff(10000, 10000)).toBeNull();
    expect(percentOff(10000, null)).toBeNull();
  });
});
