/** The money rule `api.md` fixes for every USD amount the browser accepts. */
const USD_AMOUNT = /^(\d+)(?:\.(\d{1,2}))?$/;

/**
 * Dollars-and-cents text to integer cents, without ever holding a float (BD-14, I3).
 * The regex is the contracted one, so anything else is refused before it is treated as
 * money, and the arithmetic stays on parsed integers.
 */
export function usdToCents(value: string): number | null {
  const match = USD_AMOUNT.exec(value.trim());
  if (!match) return null;
  const centsText = match[2];
  const dollars = Number.parseInt(match[1] ?? "", 10);
  const cents = centsText ? Number.parseInt(centsText.padEnd(2, "0"), 10) : 0;
  return dollars * 100 + cents;
}
