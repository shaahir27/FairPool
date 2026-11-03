import { type CSSProperties, useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";

import { Brand, PoolMark } from "../shared";
import "./landing.css";

const STEPS = [
  ["Join for free", "Say what you want and the most you will pay. AI helps structure your request, and you confirm the details. In the saved-payment flow, you also consent and save your PayPal wallet. Joining reserves no funds."],
  ["A published rule gives out places", "When time is up, places are filled in an order set by a rule published in advance. Everyone beyond the available places joins an ordered waitlist, and each buyer gets a receipt for their own place."],
  ["Merchants bid in sealed auctions", "Merchants send their best delivered price for the group without seeing each other’s bids. The lowest price that meets the rules wins, and a tie is settled by a published rule."],
  ["Payment follows your consent", "With saved-payment consent, FairPool charges selected buyers automatically after the award, within the maximum they set. FairPool enforces that maximum; PayPal’s save-wallet screen shows no purchase amount. In the approval-at-checkout fallback, you review and approve the exact total on PayPal."],
  ["The order goes ahead only when enough people pay", "The merchant sets a minimum number of completed payments. If the group reaches it, the order goes ahead. If the deadline passes without enough completed payments, FairPool starts full refunds for completed payments and releases any uncaptured holds. You can track their status in Orders."],
] as const;

const SAY = "On your own, you take the price you are given. Together, merchants compete to give your group their best.".split(" ");
const at = (t: number) => ({ "--t": t }) as CSSProperties;

function Rings() {
  return (
    <div className="rr">
      {[70, 112, 154, 196, 238].map((radius, ring) => {
        const seats = 12 + ring * 4;
        return (
          <div key={radius} className="seat-ring" style={{ "--i": ring, "--t": (60 + ring * 18) + "s", "--dir": ring % 2 ? "reverse" : "normal" } as CSSProperties}>
            <svg viewBox="0 0 520 520" aria-hidden="true">
              <circle cx="260" cy="260" r={radius} className="orb" />
              {Array.from({ length: seats }, (_, index) => {
                const angle = index * Math.PI * 2 / seats + ring * .18;
                const marked = index % 7 === 0;
                return <circle key={index} cx={260 + radius * Math.cos(angle)} cy={260 + radius * Math.sin(angle)}
                  r={marked ? 5.5 : 3} className={marked ? "seat" : "pp"} style={marked ? { "--d": (ring * .6 + index * .25) + "s" } as CSSProperties : undefined} />;
              })}
            </svg>
          </div>
        );
      })}
    </div>
  );
}

const prefersReducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Pointer, idle sway and scroll steer the 3D pool through CSS variables; no React state per frame. */
function usePoolMotion(ref: { current: HTMLElement | null }) {
  useEffect(() => {
    const el = ref.current;
    if (!el || prefersReducedMotion()) return;
    let tx = 0, ty = 0, cx = 0, cy = 0, raf = 0;
    const frame = (t: number) => {
      cx += (tx - cx) * .06;
      cy += (ty - cy) * .06;
      const p = Math.min(1, window.scrollY / 700);
      el.style.setProperty("--rz", `${(cx * 24 + Math.sin(t / 2600) * 6 + p * 50).toFixed(2)}deg`);
      el.style.setProperty("--rx", `${(cy * -10 + p * 8).toFixed(2)}deg`);
      el.style.setProperty("--sc", (1 - p * .14).toFixed(3));
      el.style.setProperty("--sp", p.toFixed(3));
      raf = requestAnimationFrame(frame);
    };
    const move = (e: PointerEvent) => {
      if (e.pointerType === "touch") return;
      tx = e.clientX / window.innerWidth - .5;
      ty = e.clientY / window.innerHeight - .5;
    };
    const io = new IntersectionObserver(([entry]) => {
      cancelAnimationFrame(raf);
      if (entry?.isIntersecting) raf = requestAnimationFrame(frame);
    });
    io.observe(el);
    window.addEventListener("pointermove", move, { passive: true });
    return () => { io.disconnect(); cancelAnimationFrame(raf); window.removeEventListener("pointermove", move); };
  }, [ref]);
}

function useInView<T extends Element>() {
  const ref = useRef<T>(null);
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(([entry]) => {
      if (entry?.isIntersecting) { setSeen(true); io.disconnect(); }
    }, { threshold: .3 });
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return [ref, seen] as const;
}

export default function LandingPage() {
  const { hash } = useLocation();
  const [scene, setScene] = useState(0);
  const [scrolled, setScrolled] = useState(false);
  const poolRef = useRef<HTMLDivElement>(null);
  const [receiptRef, receiptSeen] = useInView<HTMLDivElement>();
  usePoolMotion(poolRef);
  const rootRef = useRef<HTMLDivElement>(null);
  const navRef = useRef<HTMLElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const stepsRef = useRef<HTMLOListElement>(null);
  const sayRef = useRef<HTMLParagraphElement>(null);
  const orbitRef = useRef<HTMLDivElement>(null);
  const panelRefs = useRef<(HTMLDivElement | null)[]>([]);
  const panel = (index: number) => ({
    className: scene === index ? `pn p${index} on` : `pn p${index}`,
    ref: (el: HTMLDivElement | null) => { panelRefs.current[index] = el; },
  });

  // One scroll loop turns scroll position into CSS variables. Visuals read the variables,
  // so React re-renders only when the active step changes, never per frame.
  useEffect(() => {
    const reduced = prefersReducedMotion();
    const stacked = window.matchMedia("(max-width: 980px)");
    const clamp = (v: number) => Math.min(1, Math.max(0, v));
    const entering = Array.from(rootRef.current?.querySelectorAll<HTMLElement>("[data-enter]") ?? []);
    let raf = 0;
    const update = () => {
      raf = 0;
      const vh = window.innerHeight;
      navRef.current?.style.setProperty("--pg", String(clamp(window.scrollY / Math.max(1, document.documentElement.scrollHeight - vh))));
      const stage = stageRef.current, list = stepsRef.current;
      if (stage && list && list.children.length) {
        const bottom = stage.getBoundingClientRect().bottom;
        const focus = stacked.matches ? bottom + (vh - bottom) * .4 : vh * .5;
        const rects = Array.from(list.children, (el) => el.getBoundingClientRect());
        let index = 0;
        rects.forEach((r, j) => { if (focus >= r.top) index = j; });
        const current = rects[index];
        if (!current) return;
        const s = clamp((focus - current.top) / current.height);
        const progress = String((index + s) / STEPS.length);
        list.style.setProperty("--p", progress);
        stage.style.setProperty("--p", progress);
        panelRefs.current.forEach((el, j) => {
          if (!el) return;
          const local = reduced || j < index ? 1 : j > index ? 0 : s;
          el.style.setProperty("--s", local.toFixed(3));
          el.style.setProperty("--n", String(Math.round((j === 0 ? 40 : 20) * clamp(local * (j === 0 ? 1.6 : 1.4)))));
        });
        setScene((prev) => (prev === index ? prev : index));
      }
      sayRef.current?.style.setProperty("--r", reduced ? "1" : clamp((vh * .85 - sayRef.current.getBoundingClientRect().top) / (vh * .5)).toFixed(3));
      // Each marked element gets its own 0 to 1 "arrival" value as it rises into view.
      entering.forEach((el) => el.style.setProperty("--c", reduced ? "1" : clamp((vh * .94 - el.getBoundingClientRect().top) / (vh * .36)).toFixed(3)));
      const orbit = orbitRef.current;
      if (orbit && !reduced) {
        const box = orbit.parentElement!.getBoundingClientRect();
        const r = clamp((vh - box.top) / (vh + box.height));
        orbit.style.setProperty("--rz", `${(r * 80).toFixed(1)}deg`);
        orbit.style.setProperty("--sc", (1.3 - r * .3).toFixed(3));
      }
    };
    const schedule = () => { if (!raf) raf = requestAnimationFrame(update); };
    update();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    return () => { cancelAnimationFrame(raf); window.removeEventListener("scroll", schedule); window.removeEventListener("resize", schedule); };
  }, []);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);


  useEffect(() => {
    if (hash) document.getElementById(hash.slice(1))?.scrollIntoView();
    else document.documentElement.scrollTop = 0;
  }, [hash]);

  return (
    <div className="landing" ref={rootRef}>
      <a className="skip-link" href="#top">Skip to content</a>
      <svg width="0" height="0" className="symbols" aria-hidden="true">
      <symbol id="ck" viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5"/></symbol>
      <symbol id="ar" viewBox="0 0 24 24"><path d="M5 12h14M13 6l6 6-6 6"/></symbol>
      <symbol id="ci" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/></symbol>
      <symbol id="i1" viewBox="0 0 24 24"><path d="M4 4h7l9 9-7 7-9-9z"/><circle cx="8" cy="8" r="1.2"/></symbol>
      <symbol id="i2" viewBox="0 0 24 24"><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M8.5 12l2.5 2.5 4.5-5"/></symbol>
      <symbol id="i4" viewBox="0 0 24 24"><path d="M9 7L4 12l5 5"/><path d="M4 12h10a6 6 0 010 8h-3"/></symbol>
      <symbol id="i5" viewBox="0 0 24 24"><path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5L18 18M18 6l-2.5 2.5M8.5 15.5L6 18"/></symbol>
      </svg>

      <header className={scrolled ? "nav scrolled" : "nav"} ref={navRef}>
        <a className="landing-brand" href="#top" aria-label="FairPool home"><Brand /></a>
        <nav className="links" aria-label="Page sections"><a href="#how">How it works</a><a href="#trust">What you can count on</a><a href="#who">Buyers and merchants</a><a href="#status">Where we are</a></nav>
        <Link className="btn p" to="/login">Join a pool</Link>
      </header>

      <main id="top" tabIndex={-1}>
      <section className="hero dk" aria-labelledby="h1">
        <div className="wrap hg">
          <div>
            <h1 id="h1"><span className="ln" style={{ "--k": 0 } as CSSProperties}><span>Buy together.</span></span><span className="ln" style={{ "--k": 1 } as CSSProperties}><span>Let merchants compete for your group.</span></span></h1>
            <p className="lead">Join buyers looking for the same product. Merchants bid for the group. Set your maximum total and choose whether to give payment permission when you join.</p>
            <div className="cta">
              <Link className="btn p" to="/login">Join a pool <svg className="icon" aria-hidden="true"><use href="#ar" /></svg></Link>
              <Link className="btn s" to="/login?role=merchant">Open merchant area</Link>
            </div>
            <ul className="hero-facts" aria-label="Key facts">
              <li><svg className="icon" aria-hidden="true"><use href="#ck" /></svg>Free to join</li>
              <li><svg className="icon" aria-hidden="true"><use href="#ck" /></svg>No funds reserved when joining</li>
            </ul>
            <p className="hero-sandbox">PayPal Sandbox demo. No real money moves.</p>
          </div>
          <div className="pool" ref={poolRef} role="img" aria-label="Rings of seats around the FairPool mark, showing many buyers in one pool">
            <div className="scene"><Rings /><div className="core"><PoolMark /></div></div>

          </div>
        </div>
      </section>

      <section className="say" aria-label="The idea">
        <div className="wrap">
          <p className="say-t" ref={sayRef}>
            {SAY.map((word, index) => <span key={index} style={{ "--w": index } as CSSProperties}>{word} </span>)}
          </p>
        </div>
      </section>

      <section className="sec" id="how" aria-labelledby="how-h">
        <div className="wrap">
          <h2 id="how-h">How a pool works</h2>
          <p className="lead">Follow an example pool from the first buyer request to a funded order. Scroll to move through it.</p>
          <div className="story">
            <ol className="steps" ref={stepsRef}>
              {STEPS.map(([title, description], index) => (
                <li key={title} className={scene === index ? "step on" : scene > index ? "step done" : "step"} aria-current={scene === index ? "step" : undefined}>
                  <h3 className="sh"><em aria-hidden="true">{index + 1}</em>{title}</h3>
                  <div className="sd"><p>{description}</p></div>
                </li>
              ))}
            </ol>
            <div className="stage" ref={stageRef} aria-hidden="true">
              <div className="seg">{STEPS.map((_, i) => <i key={i} style={{ "--i": i } as CSSProperties} />)}</div>
              <div className="sth"><div><p>Example pool</p><strong>Walnut standing desk</strong></div><span className="pill">Illustration</span></div>
              <div {...panel(0)}><p className="pl">What do you want?</p><div className="fld2"><span className="type">Walnut standing desk, 140 cm</span></div><p className="pl sc" style={at(.25)}>Your maximum total</p><div className="fld2 sc" style={at(.3)}>$<b>320</b></div><div className="cnt sc" style={at(.4)}><b className="num" /><span>people already in this pool</span></div><div className="ok sc" style={at(.8)}><svg className="icon" aria-hidden="true"><use href="#ck" /></svg>Joined. No payment hold.</div></div>
              <div {...panel(1)}><p className="pl">Places are filled in a published order</p><div className="seats">{Array.from({ length: 40 }, (_, index) => <i key={index} className={index === 6 ? "s me" : index < 24 ? "s" : undefined} style={{ "--k": index } as CSSProperties} />)}</div><div className="row sc" style={at(.5)}><span><b>24</b>places</span><span><b>16</b>on the waitlist</span></div><div className="ok sc" style={at(.85)}><svg className="icon" aria-hidden="true"><use href="#ck" /></svg>You hold place 7. Receipt saved.</div></div>
              <div {...panel(2)}><p className="pl">Sealed bids, delivered price per desk</p>
                <div className="bid" style={{ "--w": "97.5", "--k": "0" } as CSSProperties}><span>Merchant A</span><i></i><b>$312</b></div><div className="bid" style={{ "--w": "93", "--k": "1" } as CSSProperties}><span>Merchant B</span><i></i><b>$298</b></div><div className="bid w" style={{ "--w": "89", "--k": "2" } as CSSProperties}><span>Merchant C</span><i></i><b>$284</b></div><div className="bid" style={{ "--w": "95", "--k": "3" } as CSSProperties}><span>Merchant D</span><i></i><b>$305</b></div>
                <p className="note sc" style={at(.75)}>Merchant C offers the lowest price that meets the rules, so the group goes to Merchant C.</p></div>
              <div {...panel(3)}><div className="sum"><dl><div className="sc" style={at(.1)}><dt>Merchant</dt><dd>Merchant C</dd></div><div className="sc" style={at(.25)}><dt>Product</dt><dd>Walnut standing desk, 140 cm</dd></div><div className="sc" style={at(.4)}><dt>Your maximum</dt><dd>$320</dd></div></dl><div className="tot sc" style={at(.6)}><span>Your total</span><b>$284</b></div><div className="cap sc" style={at(.7)}><i /></div><p className="capl sc" style={at(.7)}>$284 of your $320 maximum</p></div><p className="note sc" style={at(.85)}>Saved-payment flow: charged after award, within your maximum. Checkout fallback: approve the exact total on PayPal.</p></div>
              <div {...panel(4)}><p className="pl">Merchant’s minimum</p><div className="fund"><svg viewBox="0 0 124 124" aria-hidden="true"><circle className="tr" cx="62" cy="62" r="52" /><circle className="rg" cx="62" cy="62" r="52" /><path className="fund-check" d="m43 63 13 13 27-29" /></svg><div><b><em className="num" /> of 20</b><span>completed payments from different buyers</span></div></div><div className="ok sc" style={at(.85)}><svg className="icon" aria-hidden="true"><use href="#ck" /></svg>Minimum reached. The order goes ahead.</div><p className="note sc" style={at(.92)}>If the minimum is missed by the deadline, full refunds and hold releases are started. Track their status in Orders.</p></div>
            </div>
          </div>
        </div>
      </section>

      <section className="sec" id="trust" aria-labelledby="t-h">
        <div className="wrap trust">
          <div><h2 id="t-h">What you can count on</h2>
            <ul className="prom">
              <li className="pr" data-enter><span className="ic"><svg className="icon" aria-hidden="true"><use href="#i1"/></svg></span><div><h3>Free to join</h3><p>Joining costs nothing and puts no hold on your PayPal account.</p></div></li>
              <li className="pr" data-enter><span className="ic"><svg className="icon" aria-hidden="true"><use href="#i2"/></svg></span><div><h3>Your maximum, your consent</h3><p>You set the maximum delivered total, including shipping and tax. With your saved-payment consent, FairPool charges the awarded total automatically, only within that maximum.</p></div></li>
              <li className="pr" data-enter><span className="ic"><svg className="icon" aria-hidden="true"><use href="#i4"/></svg></span><div><h3>Refunds if the group falls short</h3><p>If the group misses its minimum by the deadline, FairPool starts full refunds for completed payments and releases uncaptured holds. Orders shows the status, including any refund needing attention.</p></div></li>
              <li className="pr" data-enter><span className="ic"><svg className="icon" aria-hidden="true"><use href="#i5"/></svg></span><div><h3>AI types, you decide</h3><p>AI turns your words into a clear request and you check every detail. Fixed rules make each decision. AI cannot approve, charge or refund a payment.</p></div></li>
            </ul></div>
          <div><div className={receiptSeen ? "rc in" : "rc"} ref={receiptRef}>
            <div className="rch"><span>Entry receipt</span><span className="pill">Sample values</span></div>
            <dl><div className="rw" style={{"--k": "0"} as CSSProperties}><dt>Pool</dt><dd>Walnut standing desk</dd></div><div className="rw" style={{"--k": "1"} as CSSProperties}><dt>Entry fingerprint</dt><dd className="m">a91f…c27e</dd></div><div className="rw" style={{"--k": "2"} as CSSProperties}><dt>Public seed</dt><dd className="m">3be0…71d4</dd></div><div className="rw" style={{"--k": "3"} as CSSProperties}><dt>Order of places</dt><dd>Recomputed from list and seed</dd></div></dl>
            <div className="stamp"><svg className="icon" aria-hidden="true"><use href="#ck"/></svg>Sample place: 7 of 24</div>
            <p className="note">The published list and seed make the allocation order auditable. They do not prove that every eligible entry was included.</p>
          </div></div>
        </div>
      </section>

      <section className="sec" id="who" aria-labelledby="who-h">
        <div className="wrap">
          <h2 id="who-h">Made for both sides of the deal</h2>
          <div className="sides">
            <article className="side b" data-enter><h3>For buyers</h3><p>A whole group asking together gives merchants a reason to bid, and you stay in control.</p>
              <ul><li><svg className="icon" aria-hidden="true"><use href="#ck"/></svg>Set the most you are willing to pay</li><li><svg className="icon" aria-hidden="true"><use href="#ck"/></svg>Join for free, with no payment hold</li><li><svg className="icon" aria-hidden="true"><use href="#ck"/></svg>Consent before saving payment permission</li><li><svg className="icon" aria-hidden="true"><use href="#ck"/></svg>Get a receipt you can check</li></ul>
              <Link className="btn p" to="/login">Join a pool <svg className="icon" aria-hidden="true"><use href="#ar"/></svg></Link></article>
            <article className="side m dk" data-enter><h3>For merchants</h3><p>See real demand from a whole group, and win it with your best price.</p>
              <ul><li><svg className="icon" aria-hidden="true"><use href="#ck"/></svg>Find open group demand in one place</li><li><svg className="icon" aria-hidden="true"><use href="#ck"/></svg>Send one sealed bid for each group order</li><li><svg className="icon" aria-hidden="true"><use href="#ck"/></svg>Paste a quote, then confirm the details</li><li><svg className="icon" aria-hidden="true"><use href="#ck"/></svg>Fulfil only once enough buyers have paid</li></ul>
              <Link className="btn s" to="/login?role=merchant">Open merchant area <svg className="icon" aria-hidden="true"><use href="#ar"/></svg></Link></article>
          </div>
        </div>
      </section>

      <section className="sec status" id="status" aria-labelledby="s-h">
        <div className="wrap">
          <h2 id="s-h">Where we are today</h2>
          <p className="lead">FairPool is a working demo built for the PayPal AI Hackathon. It runs on the PayPal Sandbox with demo data, so no real money moves.</p>
          <div className="cols">
            <div><h3>Working in the demo</h3><ul><li className="on" data-enter><svg className="icon" aria-hidden="true"><use href="#ck"/></svg>Joining pools for free</li><li className="on" data-enter><svg className="icon" aria-hidden="true"><use href="#ck"/></svg>Places given by a published rule, with receipts</li><li className="on" data-enter><svg className="icon" aria-hidden="true"><use href="#ck"/></svg>Sealed merchant bids and awards</li><li className="on" data-enter><svg className="icon" aria-hidden="true"><use href="#ck"/></svg>Consented Sandbox payments and refund handling</li></ul></div>
            <div><h3>Sandbox limits</h3><ul><li className="soon" data-enter><svg className="icon" aria-hidden="true"><use href="#ci"/></svg>Merchant identities and demand are for demonstration</li><li className="soon" data-enter><svg className="icon" aria-hidden="true"><use href="#ci"/></svg>No real orders ship from this demo</li><li className="soon" data-enter><svg className="icon" aria-hidden="true"><use href="#ci"/></svg>Live payments are outside the demo</li></ul></div>
          </div>
          <div className="know"><p><b>Good to know.</b> Demo payments are in US dollars from US PayPal Sandbox accounts.</p><p>In the demo, one test seller receives payments for the winning merchant. The winning merchant’s name is still shown; settlement to that merchant is outside PayPal.</p></div>
        </div>
      </section>

      <section className="end dk" aria-labelledby="e-h">
        <div className="end-orbit" ref={orbitRef} aria-hidden="true"><Rings /></div>
        <div className="wrap"><h2 id="e-h">See a pool for yourself</h2><p className="lead">Sign in to join a pool or open the merchant workspace.</p>
        <div className="cta"><Link className="btn p" to="/login">Join a pool <svg className="icon" aria-hidden="true"><use href="#ar"/></svg></Link><Link className="btn s" to="/login?role=merchant">Open merchant area</Link></div></div>
      </section>
      </main>

      <footer className="dk"><div className="wrap">
        <div><a className="landing-brand" href="#top" aria-label="FairPool home"><Brand /></a>
        <p style={{"marginTop": "14px"}}>Built for the PayPal AI Hackathon. Runs on the PayPal Sandbox with demo data. No real money moves.</p></div>
        <nav aria-label="Footer"><Link to="/login">Buyer sign in</Link><Link to="/login?role=merchant">Merchant sign in</Link></nav>
      </div></footer>
    </div>
  );
}