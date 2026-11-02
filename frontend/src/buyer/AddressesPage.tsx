import { type FormEvent, useEffect, useState } from "react";
import { api, type ApiComponents, DeliveryAddressFields, EMPTY_DELIVERY_ADDRESS, Icon, Notice } from "../shared";

type SavedAddress = ApiComponents["schemas"]["SavedAddressResponse"];

export function AddressesPage() {
  const [addresses, setAddresses] = useState<SavedAddress[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);
  const [address, setAddress] = useState(EMPTY_DELIVERY_ADDRESS);
  const [isDefault, setDefault] = useState(false);
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    setLoading(true);
    void api.GET("/api/v1/me/addresses").then(({ data, error: failure }) => {
      if (!live) return;
      if (failure || !data) setError("We couldn’t load your addresses. Try again.");
      else { setAddresses(data.addresses); setError(""); }
    }).catch(() => { if (live) setError("Check your connection and try again."); }).finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [attempt]);
  function reset() { setEditing(null); setAddress(EMPTY_DELIVERY_ADDRESS); setDefault(false); }
  async function save(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setError(""); setSaved(false);
    try {
      const body = { address, is_default: isDefault };
      const result = editing ? await api.PUT("/api/v1/me/addresses/{address_id}", { params: { path: { address_id: editing } }, body }) : await api.POST("/api/v1/me/addresses", { body });
      if (result.error || !result.data) { setError("We couldn’t save this address. Check the fields and try again."); return; }
      const item = result.data;
      setAddresses((previous) => [...previous.filter((row) => row.id !== item.id).map((row) => item.is_default ? { ...row, is_default: false } : row), item]);
      reset(); setSaved(true);
    } catch { setError("Check your connection and try again. Your changes are still here."); }
    finally { setBusy(false); }
  }
  async function remove(id: string) {
    if (busy) return;
    setBusy(true); setError(""); setSaved(false);
    try {
      const result = await api.DELETE("/api/v1/me/addresses/{address_id}", { params: { path: { address_id: id } } });
      if (result.error) { setError("We couldn’t remove this address. Try again."); return; }
      if (editing === id) reset();
      setRemoving(null); setAttempt((value) => value + 1);
    } catch { setError("Check your connection and try again."); }
    finally { setBusy(false); }
  }
  return <section className="address-book">
    <div className="shop-heading"><h1 className="shop-title">Delivery addresses</h1><p className="shop-copy">Keep your usual destinations ready for checkout. Updating an address here won’t change an order you’ve already placed.</p></div>
    {error ? <Notice kind="error">{error} <button type="button" className="signup-back" onClick={() => setAttempt((value) => value + 1)}>Reload addresses</button></Notice> : null}
    {saved ? <p className="address-saved" role="status"><Icon name="check" />Address saved.</p> : null}
    <div className="address-book-layout">
      <section className="panel address-list" aria-label="Saved addresses">
        <h2>Your addresses</h2>
        {loading ? <p role="status">Loading your addresses…</p> : addresses.length === 0 ? <p className="shop-copy">No saved addresses yet. Add your first delivery address to get started.</p> : addresses.map((item) => <article key={item.id} className="address-entry">
          <div className="address-entry-heading"><strong>{item.address.name}</strong>{item.is_default ? <span className="address-default">Default</span> : null}</div>
          <address>{item.address.line1}<br />{item.address.line2 ? <>{item.address.line2}<br /></> : null}{item.address.city}, {item.address.region} {item.address.postal_code}<br />{item.address.country_code}</address>
          <div className="address-actions"><button type="button" className="signup-back" disabled={busy} onClick={() => { setEditing(item.id); setAddress(item.address); setDefault(item.is_default); setSaved(false); }}>Edit</button><button type="button" className="signup-back" disabled={busy} onClick={() => setRemoving(item.id)}>Remove</button></div>
          {removing === item.id ? <div className="address-remove"><p>Remove this saved address?</p><button type="button" className="button-secondary" disabled={busy} onClick={() => void remove(item.id)}>Remove address</button><button type="button" className="signup-back" disabled={busy} onClick={() => setRemoving(null)}>Keep address</button></div> : null}
        </article>)}
      </section>
      <section className="panel address-editor" aria-labelledby="address-editor-title"><h2 id="address-editor-title">{editing ? "Edit address" : "Add an address"}</h2><p className="shop-copy">Use the recipient’s name and full delivery address.</p>
        <form className="auth-fields" onSubmit={(event) => void save(event)}>
          <DeliveryAddressFields value={address} onChange={setAddress} prefix="address-book" />
          <label className="address-checkbox"><input type="checkbox" checked={isDefault} disabled={!!editing && addresses.some((item) => item.id === editing && item.is_default)} onChange={(event) => setDefault(event.target.checked)} />Use as my default delivery address</label>
          {editing && addresses.some((item) => item.id === editing && item.is_default) ? <p className="signup-help">To change your default, edit another saved address and make it the default.</p> : null}
          <div className="address-actions"><button type="submit" className="button-primary" disabled={busy}>{busy ? "Saving…" : "Save address"}</button>{editing ? <button type="button" className="button-secondary" disabled={busy} onClick={reset}>Cancel editing</button> : null}</div>
        </form>
      </section>
    </div>
  </section>;
}
