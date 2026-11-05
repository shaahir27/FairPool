import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useState } from "react";
import { BidFields } from "../src/merchant/demand/BidFields";
import { dollarsToCents } from "../src/merchant/demand/money";

describe("merchant price entry", () => {
  it.each([["129.09", 12909], ["0.01", 1], ["4.", 400], ["4", 400], ["", null], ["-1", null], ["1.001", null], ["1e3", null], ["999999999999999999", null]])("formats %s without float money", (input, cents) => {
    expect(dollarsToCents(String(input))).toBe(cents);
  });

  it("requires explicit correction of parsed shipping and tax instead of silently dropping them", () => {
    const onChange = vi.fn();
    render(<BidFields value={{ tax: {mode: "RATE_TABLE"}, shipping_cents_by_zone: {"US-EAST": 1500}, custom_note: "preserved" }} onChange={onChange} />);
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", {name: "Use shipping and tax included"}));
    expect(onChange).toHaveBeenCalledWith({ tax: {mode: "INCLUDED"}, shipping_cents_by_zone: {"US-EAST": 0}, custom_note: "preserved" });
  });
});

it("keeps the remaining tier's price when an earlier tier is removed", () => {
  function Editor() {
    const [value, setValue] = useState<Record<string, unknown>>({tiers: [{min_qty: 1, item_price_cents: 50000}, {min_qty: 6, item_price_cents: 42010}], tax: {mode: "INCLUDED"}});
    return <BidFields value={value} onChange={setValue} />;
  }
  render(<Editor />);
  fireEvent.click(screen.getByRole("button", {name: "Remove tier 1"}));
  expect(screen.getByLabelText("Delivered price, tier 1 (USD)")).toHaveValue("420.10");
  expect(screen.getByLabelText("Minimum quantity, tier 1")).toHaveValue(6);
});
