import type { DeliveryAddress } from "../lib/address";

const fields = [
  ["name", "Recipient name", "name", 120],
  ["line1", "Street address", "address-line1", 200],
  ["line2", "Apartment, suite, etc. (optional)", "address-line2", 200],
  ["city", "City", "address-level2", 120],
  ["region", "State / region", "address-level1", 100],
  ["postal_code", "Postal code", "postal-code", 32],
  ["country_code", "Country code", "country", 2],
] as const;

export function DeliveryAddressFields({ value, onChange, prefix = "delivery" }: {
  value: DeliveryAddress; onChange: (value: DeliveryAddress) => void; prefix?: string;
}) {
  return <div className="delivery-grid">{fields.map(([key, label, autoComplete, maxLength]) => <label key={key} className={["name", "line1", "line2"].includes(key) ? "delivery-wide" : ""}>
    <span>{label}</span><input id={`${prefix}-${key}`} className="form-input" autoComplete={`section-${prefix} shipping ${autoComplete}`} required={key !== "line2"} maxLength={maxLength} pattern={key === "country_code" ? "[A-Za-z]{2}" : key === "line2" ? undefined : ".*\\S.*"} value={value[key] ?? ""} onChange={(event) => onChange({ ...value, [key]: key === "country_code" ? event.target.value.toUpperCase() : event.target.value })} />
    {key === "country_code" ? <span className="signup-help">Two letters, for example US.</span> : null}
  </label>)}</div>;
}
