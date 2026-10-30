# Flat delivered bids (BID_PRICING_MODE=flat_delivered)

Status: adopted by the owner on Oct 29, 2026. The idea in the update ("avoid dynamic shipping and tax math at close") is already how the design works: shipping is a merchant-supplied table and tax is a rate table or included, both computed locally with integer math, never from an external API. This rule goes one step further so each lot has one number to compare.

## Rule

- Lots are per delivery zone (FR-LT-05); zones come from the pool template and the server resolves a buyer's region to a zone. No search engine is involved in grouping.
- In `flat_delivered` mode a bid for a lot is one **delivered price per tier**: shipping, handling and tax are included. The bid must set `tax.mode = INCLUDED` and `shipping_cents_by_zone` omitted or all zero. Any other bid is rejected at review with `VALIDATION_ERROR` and a message the merchant can fix: "Bids must be one delivered price per lot, shipping and tax included."
- The buyer's total is then `item_price_cents`, and `shipping_cents` and `tax_cents` are 0 in `awards.totals`. The formulas and vectors in `fairness-and-hashing.md` still hold (the shipping and tax terms are zero).
- Eligibility is the single integer comparison `item_price_cents <= max_total_cents` per buyer; the tier choice is unchanged (FR-AU-05).
- The merchant remains responsible for the tax implications of a tax-included price; FairPool's tax is simulated and labelled (FR-AU-02). The buyer-facing text says "delivered price, tax and shipping included".

`BID_PRICING_MODE=itemised` keeps the earlier behaviour (per-zone shipping table and tax mode) for a later release.

## Tests

- A bid with shipping or `RATE_TABLE` tax is rejected in flat mode and accepted in itemised mode.
- `awards.totals` has zero shipping and tax in flat mode, and totals equal the item price.
- Checking 3,000 caps against one price is a single set-based query and finishes within the existing allocation test budget (PT-07).
