#!/usr/bin/env python3
"""Cross-check every markdown file in the FairPool docs folder.

Usage (from the repository root):  python tools/validate_docs.py [--docs docs]
Exit code 0 means no errors. Warnings never fail the run.
"""
import argparse, pathlib, re, sys
from collections import defaultdict

ap = argparse.ArgumentParser()
ap.add_argument("--docs", default="docs")
ARGS = ap.parse_args()
ROOT = pathlib.Path(ARGS.docs).resolve()
ERR, WARN = [], []
def err(f, msg): ERR.append(f"ERROR   {f}: {msg}")
def warn(f, msg): WARN.append(f"warning {f}: {msg}")

FILES = sorted(p for p in ROOT.rglob("*.md") if "source" not in p.relative_to(ROOT).parts)
TEXT = {p: p.read_text(encoding="utf-8") for p in FILES}
REL = {p: str(p.relative_to(ROOT)) for p in FILES}
def strip_fences(t): return re.sub(r"```.*?```", "", t, flags=re.S)

# ---------------------------------------------------------------- ID families
FAM = {
 "I": (r"(?<![A-Za-z0-9_-])I(1[0-5]|[1-9])(?![A-Za-z0-9_])", range(1,16), "I{}"),
 "V": (r"(?<![A-Za-z0-9_-])V(1[0-3]|[1-9])(?![A-Za-z0-9_])", range(1,14), "V{}"),
 "P": (r"(?<![A-Za-z0-9_-])P([1-7])(?![A-Za-z0-9_])", range(1,8), "P{}"),
 "G": (r"(?<![A-Za-z0-9_-])G(1[0-7]|[1-9])(?![A-Za-z0-9_])", range(1,18), "G{}"),
 "R": (r"(?<![A-Za-z0-9_-])R([1-9])(?![A-Za-z0-9_])", range(1,10), "R{}"),
 "F": (r"(?<![A-Za-z0-9_-])F(30|[12][0-9]|[1-9])(?![A-Za-z0-9_])", range(1,31), "F{}"),
 "D": (r"(?<![A-Za-z0-9_-])D(1[01]|[1-9])(?![A-Za-z0-9_])", range(1,12), "D{}"),
 "S": (r"(?<![A-Za-z0-9_-])S(1[0-3]|[1-9])(?![A-Za-z0-9_])", range(1,14), "S{}"),
 "N": (r"(?<![A-Za-z0-9_-])N(1[0-4]|[1-9])(?![A-Za-z0-9_])", range(1,15), "N{}"),
 "DEP": (r"(?<![A-Za-z0-9_-])DEP-([1-4])(?![A-Za-z0-9_])", range(1,5), "DEP-{}"),
 "INT": (r"(?<![A-Za-z0-9_-])INT-([1-9])(?![A-Za-z0-9_])", range(1,10), "INT-{}"),
 "BD": (r"(?<![A-Za-z0-9_-])BD-(\d\d)(?![A-Za-z0-9_])", range(1,19), "BD-{:02d}"),
 "PT": (r"(?<![A-Za-z0-9_-])PT-(\d\d)(?![A-Za-z0-9_])", range(1,17), "PT-{:02d}"),
 "C": (r"(?<![A-Za-z0-9_-])C-(\d\d)(?![A-Za-z0-9_])", range(1,19), "C-{:02d}"),
 "HO": (r"(?<![A-Za-z0-9_-])HO-(1[0-3]|[1-9])(?![A-Za-z0-9_])", range(1,14), "HO-{}"),
 "IT": (r"(?<![A-Za-z0-9_-])IT-(1[01]|[0-9])(?![A-Za-z0-9_])", range(0,12), "IT-{}"),
 "IG": (r"(?<![A-Za-z0-9_-])IG-(1[01]|[0-9])(?![A-Za-z0-9_])", range(0,12), "IG-{}"),
 "PH": (r"(?<![A-Za-z0-9_-])PH(1[01]|[0-9])(?![A-Za-z0-9_])", range(0,12), "PH{}"),
 "PS": (r"(?<![A-Za-z0-9_-])PS-(\d\d)(?![A-Za-z0-9_])", range(1,10), "PS-{:02d}"),
 "ES": (r"(?<![A-Za-z0-9_-])ES-(\d\d)(?![A-Za-z0-9_])", range(1,4), "ES-{:02d}"),
 "LS": (r"(?<![A-Za-z0-9_-])LS-(\d\d)(?![A-Za-z0-9_])", range(1,14), "LS-{:02d}"),
 "BO": (r"(?<![A-Za-z0-9_-])BO-(\d\d)(?![A-Za-z0-9_])", range(1,28), "BO-{:02d}"),
 "BS": (r"(?<![A-Za-z0-9_-])BS-(\d\d)(?![A-Za-z0-9_])", range(1,13), "BS-{:02d}"),
}
TASK_RE = r"(?<![A-Za-z0-9_-])(T\d\d[ABX]\d\d)(?![A-Za-z0-9_])"
FR_RE = r"(?<![A-Za-z0-9_])(FR-[A-Z]{2}-\d\d)(?![A-Za-z0-9_])"
ALL_ID_RE = [re.compile(v[0]) for v in FAM.values()] + [re.compile(TASK_RE), re.compile(FR_RE)]
def full_id(m): return m.group(0)

DEFS = set()
def first_cell_token(line):
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    if not cells: return None
    c = re.sub(r"[*`]", "", cells[0]).strip()
    return c.split()[0].rstrip(":") if c else None
for p, t in TEXT.items():
    for line in t.splitlines():
        if line.startswith("|"):
            tok = first_cell_token(line)
            if tok: DEFS.add(tok)
        m = re.match(r"#{2,4}\s+([A-Za-z0-9-]+):?", line)
        if m: DEFS.add(m.group(1))
    for m in re.finditer(r"\{id:\s*([A-Z]{2}-\d\d),", t): DEFS.add(m.group(1))
# registry range rows define families by range text; every member of a family must appear as a definition
for fam, (rx, rng, fmt) in FAM.items():
    for n in rng:
        ident = fmt.format(n)
        if ident not in DEFS: err("registry", f"{ident} is never defined in a table row, heading or YAML id")

used = defaultdict(set)
for p, t in TEXT.items():
    body = t
    for rx in ALL_ID_RE:
        for m in rx.finditer(body):
            ident = m.group(0) if rx.pattern not in (TASK_RE, FR_RE) else m.group(1)
            used[ident].add(REL[p])
for ident, files in sorted(used.items()):
    if ident not in DEFS:
        err(",".join(sorted(files)), f"{ident} is used but not defined")

# ---------------------------------------------------------------- forbidden leftovers
FORBID = [(r"\bTBD\b", "TBD"), (r"\blorem ipsum\b", "lorem ipsum"), (r"\bIG-(1a|2a)\b", "old gate IG-1a or IG-2a"),
          (r"\bIT-(1a|2a)\b", "old test IT-1a or IT-2a"), (r"(?<![A-Za-z0-9_-])T\d[ABX]\d\d(?![A-Za-z0-9_])", "old-style task ID"),
          (r"\bnine operations\b", "nine operations (the Merchant Agent API has ten)"), (r"\bTODO\b(?! without)", "TODO")]
for p, t in TEXT.items():
    for rx, label in FORBID:
        for m in re.finditer(rx, t):
            line = t.count("\n", 0, m.start()) + 1
            if label == "TODO" and (REL[p] == "progress.md" or "no new TODO" in t.splitlines()[line-1]): continue  # TODO is a status value in progress.md
            err(f"{REL[p]}:{line}", f"forbidden text: {label}")

# ---------------------------------------------------------------- links and file references
KNOWN_MISSING = {"system-design.md"}
for p, t in TEXT.items():
    for m in re.finditer(r"\]\(([^)#\s]+)(#[^)]*)?\)", strip_fences(t)):
        tgt = m.group(1)
        if tgt.startswith(("http", "mailto")): continue
        if not (p.parent / tgt).resolve().exists(): err(REL[p], f"broken link {tgt}")
    for m in re.finditer(r"`((?:docs/)?(?:contracts/)?[A-Za-z0-9_./-]+\.(?:md|json))`", strip_fences(t)):
        ref = m.group(1)
        if not (ref.startswith("docs/") or ref.startswith("contracts/")): continue
        r = ref[5:] if ref.startswith("docs/") else ref
        if r in KNOWN_MISSING or r.startswith("source/") or "<" in r: continue
        if not (ROOT / r).exists(): err(REL[p], f"references missing file {ref}")

# ---------------------------------------------------------------- table well-formedness
for p, t in TEXT.items():
    in_fence = False; block = []
    def flush():
        global block
        if len(block) >= 2:
            def cells(l): return len(re.split(r"(?<!\\)\|", l.strip())) - 2
            n = cells(block[0][1])
            for ln, l in block:
                if cells(l) != n: err(f"{REL[p]}:{ln}", f"table row has {cells(l)} cells, header has {n}")
        block = []
    for i, line in enumerate(t.splitlines(), 1):
        if line.strip().startswith("```"): in_fence = not in_fence
        if not in_fence and line.startswith("|"): block.append((i, line))
        else: flush()
    flush()

# ---------------------------------------------------------------- enums vs state machines
def table_rows(text, header_start):
    out = []; on = False
    for line in text.splitlines():
        if line.startswith(header_start): on = True; continue
        if on:
            if not line.startswith("|"): break
            if set(line.replace("|", "").strip()) <= set("-: "): continue
            out.append([c.strip() for c in line.strip().strip("|").split("|")])
    return out
dbp = ROOT / "contracts/db-schema.md"; smp = ROOT / "contracts/state-machines.md"; dpp = ROOT / "contracts/domain-ports.md"
ENUM = {}
if dbp.exists():
    for r in table_rows(TEXT[dbp], "| Enum | Values |"): ENUM[r[0]] = [v.strip() for v in r[1].split(",")]
JOBS = set()
if dpp.exists():
    for line in TEXT[dpp].splitlines():
        m = re.match(r"\|\s*([a-z]+\.[a-z_]+)\s*\|", line)
        if m: JOBS.add(m.group(1))
if smp.exists():
    t = TEXT[smp]
    blocks = re.findall(r"```yaml\n(.*?)```", t, flags=re.S)
    MAP = {"pool": "pool_status", "entry": "entry_status", "lot": "lot_status", "buyer_order": "buyer_order_status", "bid": "bid_status"}
    for b in blocks:
        name = b.splitlines()[0].rstrip(":")
        states = re.search(r"states:\s*\[(.*?)\]", b).group(1).replace(" ", "").split(",")
        init = re.search(r"initial:\s*(\w+)", b).group(1)
        if name in MAP and set(states) != set(ENUM.get(MAP[name], [])):
            err("contracts", f"{name} states in state-machines.md differ from enum {MAP[name]} in db-schema.md: {set(states) ^ set(ENUM.get(MAP[name], []))}")
        edges = defaultdict(set); seen_ids = set()
        for line in b.splitlines():
            m = re.search(r"\{id:\s*([A-Z]{2}-\d\d),\s*from:\s*\[(.*?)\],\s*to:\s*(\w+),", line)
            if not m: continue
            tid, frm, to = m.group(1), [x.strip() for x in m.group(2).split(",")], m.group(3)
            if tid in seen_ids: err("state-machines.md", f"duplicate transition id {tid}")
            seen_ids.add(tid)
            for s in frm + [to]:
                if s not in states: err("state-machines.md", f"{tid}: unknown state {s}")
            for s in frm: edges[s].add(to)
            for k in re.findall(r"job:([a-z]+\.[a-z_]+)", line):
                if k not in JOBS: err("state-machines.md", f"{tid}: job kind {k} is not in domain-ports.md")
            for k in re.findall(r"ledger:([A-Z_]+)", line):
                if k not in ENUM.get("ledger_kind", []): err("state-machines.md", f"{tid}: ledger kind {k} not in ledger_kind")
        reach, stack = {init}, [init]
        while stack:
            for n in edges[stack.pop()]:
                if n not in reach: reach.add(n); stack.append(n)
        for s in states:
            if s not in reach: err("state-machines.md", f"{name}: state {s} is unreachable from {init}")
# job kinds mentioned with a job: prefix anywhere
for p, t in TEXT.items():
    for k in re.findall(r"job:([a-z]+\.[a-z_]+)", t):
        if JOBS and k not in JOBS: err(REL[p], f"job kind {k} is not in domain-ports.md")

# ---------------------------------------------------------------- environment variables
cfgp = ROOT / "contracts/config-and-errors.md"
ENV = set(); ERRCODES = set()
if cfgp.exists():
    for line in TEXT[cfgp].splitlines():
        m = re.match(r"\|\s*`([A-Z][A-Z0-9_]+)`\s*\|", line)
        if m: ENV.add(m.group(1))
        m = re.match(r"\|\s*([A-Z][A-Z0-9_]+)\s*\|\s*\d{3}\s*\|", line)
        if m: ERRCODES.add(m.group(1))
PFX = ("PAYPAL_", "PAYMENT_", "AI_", "BEACON_", "DRAND_", "REQUIRE_", "TIMING_", "CAPTURE_", "WORKER_", "RECONCILER_", "WEBHOOKS_", "MOCK_", "DEDUPE_",
       "SEARCH_", "ELASTIC", "SHIPMENT_", "MCP_", "MERCHANT_API_", "ZAPIER_", "SIMILARITY_", "SINGLE_", "ALLOWED_", "ADDRESS_", "RECEIPT_", "HMAC_", "SECRET_",
       "DATABASE_", "ANTHROPIC_", "APP_", "CORS_", "PUBLIC_", "FRONTEND_", "LOG_", "RATE_", "AUTHORIZE_", "PLATFORM_")
for p, t in TEXT.items():
    for m in re.finditer(r"`([A-Z][A-Z0-9_]{3,})`", t):
        v = m.group(1)
        if v.startswith(PFX) and v not in ENV and v not in ERRCODES and v not in ENUM.get("payment_router", []):
            if v.endswith("_") or v == "RATE_TABLE" or v.startswith(("PAYPAL_UNAVAILABLE", "PAYPAL_LINK_")): continue  # prefix mentions and the tax.mode value are not variables
            err(REL[p], f"`{v}` looks like an environment variable but is not in config-and-errors.md")

# ---------------------------------------------------------------- API endpoints
apip = ROOT / "contracts/api.md"
EP = {}
if apip.exists():
    for line in TEXT[apip].splitlines():
        m = re.match(r"\|\s*(GET|POST|PUT|DELETE|PATCH)\s*\|\s*(/[^|\s]*)\s*\|\s*(A|B|AB)\s*\|\s*(\w+)\s*\|", line)
        if m:
            k = (m.group(1), m.group(2))
            if k in EP: err("api.md", f"duplicate endpoint {k}")
            EP[k] = (m.group(3), m.group(4))
    AUTHS = {"public", "session", "merchant", "admin", "agent", "merchant_key", "webhook"}
    for k, (o, a) in EP.items():
        if a not in AUTHS: err("api.md", f"{k}: unknown auth mode {a}")
    ops = re.findall(r"\|\s*(\w+)\s*\|\s*(GET|POST|PUT|DELETE)\s+(/merchant-api/v1[^|\s]*)\s*\|\s*([a-z:]+)\s*\|", TEXT[apip])
    if len(ops) != 10: err("api.md", f"Merchant Agent API table has {len(ops)} operations, expected 10")
    mk = [k for k, v in EP.items() if v[1] == "merchant_key"]
    if len(mk) != len(ops): err("api.md", f"{len(mk)} merchant_key endpoints but {len(ops)} operations")
    for oid, mth, path, scope in ops:
        if (mth, path) not in EP: err("api.md", f"operation {oid} {mth} {path} missing from the endpoint table")
    if len(ops) > 20: err("api.md", "more than 20 operations exceeds the APIMatic plan limit")
    norm = lambda s: re.sub(r"\{[^}]*\}", "{}", s.split("?")[0].rstrip("/"))
    EPN = {norm(k[1]) for k in EP}
    for p, t in TEXT.items():
        for m in re.finditer(r"`(?:GET|POST|PUT|DELETE)?\s*(/(?:api/v1|agent/v1|merchant-api/v1|webhooks|health|ready|mcp)[^`\s]*)`", strip_fences(t)):
            s = norm(m.group(1))
            if "..." in s or "*" in s or "<" in s: continue
            if s in {"/merchant-api/v1/openapi.json", "/webhooks-event-types"}: continue  # sub-app schema document; PayPal's own path
            if s in EPN or any(e.startswith(s + "/") for e in EPN): continue
            warn(REL[p], f"endpoint path {m.group(1)} not in the endpoint table")

# ---------------------------------------------------------------- tasks, phases, gates
planp = ROOT / "implementation-plan.md"; teamp = ROOT / "team-split.md"; progp = ROOT / "progress.md"
TASKS = {}
if planp.exists():
    for line in TEXT[planp].splitlines():
        m = re.match(r"\|\s*(T\d\d[ABX]\d\d)\s*\|\s*(A|B|AB)\s*\|\s*([SMLX]+)\s*\|\s*([^|]*)\|\s*([^|]*)\|", line)
        if m:
            tid = m.group(1)
            if tid in TASKS: err("implementation-plan.md", f"duplicate task row {tid}")
            deps = [] if m.group(4).strip() == "none" else [d.strip() for d in m.group(4).split(",")]
            TASKS[tid] = dict(owner=m.group(2), size=m.group(3), deps=deps, title=m.group(5).strip(), phase=int(tid[1:3]))
    for tid, d in TASKS.items():
        letter = tid[3]
        if (letter == "X") != (d["owner"] == "AB") or (letter in "AB" and letter != d["owner"]):
            err("implementation-plan.md", f"{tid}: owner {d['owner']} does not match the ID letter")
        for dep in d["deps"]:
            if dep not in TASKS: err("implementation-plan.md", f"{tid}: unknown dependency {dep}"); continue
            e = TASKS[dep]
            if e["phase"] > d["phase"]: err("implementation-plan.md", f"{tid} depends on later-phase task {dep}")
            elif e["phase"] == d["phase"] and not (e["owner"] == d["owner"] or "AB" in (e["owner"], d["owner"]) or dep == "T00A01"):
                err("implementation-plan.md", f"{tid} ({d['owner']}) has a same-phase cross-owner dependency on {dep}")
    # cycle check
    state = {}
    def dfs(n, path):
        if state.get(n) == 1: err("implementation-plan.md", f"dependency cycle through {n}"); return
        if state.get(n) == 2: return
        state[n] = 1
        for x in TASKS[n]["deps"]:
            if x in TASKS: dfs(x, path + [n])
        state[n] = 2
    for n in TASKS: dfs(n, [])
    blocks = re.findall(r"^### (T\d\d[ABX]\d\d):", TEXT[planp], flags=re.M)
    if set(blocks) != set(TASKS): err("implementation-plan.md", f"task blocks and summary rows differ: {set(blocks) ^ set(TASKS)}")
    # requirement coverage
    specp = ROOT / "product-spec.md"
    FRS = set(re.findall(r"^\|\s*(FR-[A-Z]{2}-\d\d)\s*\|", TEXT[specp], flags=re.M)) if specp.exists() else set()
    covered = defaultdict(set)
    for blk in re.split(r"^### ", TEXT[planp], flags=re.M)[1:]:
        m = re.match(r"(T\d\d[ABX]\d\d):", blk)
        if not m: continue
        r = re.search(r"\*\*Requirements and invariants:\*\* (.*)", blk)
        if r:
            for fr in re.findall(FR_RE, r.group(1)): covered[fr].add(m.group(1))
    for fr in sorted(FRS - set(covered)): err("implementation-plan.md", f"requirement {fr} is not covered by any task")
    for fr in covered:
        if fr not in FRS: err("implementation-plan.md", f"task cites unknown requirement {fr}")
    # gates (no calendar dates: a gate is identified by its number, tag and phase)
    G = {}
    for line in TEXT[planp].splitlines():
        m = re.match(r"\|\s*IG-(\d+)\s*\|\s*`ig-(\d+)`\s*\|\s*PH(\d+)\s*\|", line)
        if m:
            n = int(m.group(1))
            if int(m.group(2)) != n: err("implementation-plan.md", f"IG-{n}: tag mismatch")
            if int(m.group(3)) != n: err("implementation-plan.md", f"IG-{n} is listed after PH{m.group(3)}")
            G[n] = n
    if sorted(G) != list(range(12)): err("implementation-plan.md", f"gate rows found for {sorted(G)}, expected 0 to 11")
    # consistency with team split and progress
    for other, name in ((teamp, "team-split.md"), (progp, "progress.md")):
        if not other.exists(): continue
        ids = set(re.findall(r"(?<![A-Za-z0-9_-])(T\d\d[ABX]\d\d)(?![A-Za-z0-9_])", TEXT[other]))
        if ids != set(TASKS): err(name, f"task IDs differ from the plan: {sorted(ids ^ set(TASKS))[:8]}")
        for n in G:
            if not re.search(rf"^\|\s*IG-{n}\s*\|", TEXT[other], flags=re.M): err(name, f"no table row for gate IG-{n}")
    if progp.exists():
        rows = re.findall(r"^\|\s*(T\d\d[ABX]\d\d)\s*\|\s*(A|B|AB)\s*\|\s*([SMLX]+)\s*\|\s*(TODO|IN PROGRESS|IN REVIEW|DONE|BLOCKED|DEFERRED[^|]*)\s*\|", TEXT[progp], flags=re.M)
        if {r[0] for r in rows} != set(TASKS): err("progress.md", "task status rows do not cover exactly the planned tasks")
        for tid, o, s, _ in rows:
            if tid in TASKS and (TASKS[tid]["owner"] != o or TASKS[tid]["size"] != s): err("progress.md", f"{tid}: owner or size differs from the plan")
    # IT definitions
    tsp = ROOT / "testing-strategy.md"
    if tsp.exists():
        its = set(int(x) for x in re.findall(r"^\|\s*IT-(\d+)\s*\|", TEXT[tsp], flags=re.M))
        if its != set(range(12)): err("testing-strategy.md", f"IT rows found for {sorted(its)}, expected 0 to 11")

# ---------------------------------------------------------------- ownership consistency (CODEOWNERS vs team split)
scp = ROOT / "scaffold.md"
if scp.exists() and "platform/" in TEXT[scp].replace("`platform`", ""):
    warn("scaffold.md", "mentions platform/ (the package is named infra)")

# ---------------------------------------------------------------- report
for w in WARN: print(w)
for e in ERR: print(e)
print(f"\nfiles checked: {len(FILES)}   errors: {len(ERR)}   warnings: {len(WARN)}")
sys.exit(1 if ERR else 0)
