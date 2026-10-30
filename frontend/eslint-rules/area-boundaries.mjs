/**
 * Area-boundary rule for the FairPool frontend (scaffold section 5 rule 8).
 *
 * The seven areas under `frontend/src/` may import one another only through
 * the target area's `index.ts`; `shared` may not import an area at all. The
 * server-side `tools/check_imports.py` enforces the same rule for validation.
 */

const AREAS = new Set([
  "shared",
  "buyer",
  "merchant",
  "merchant-fulfillment",
  "checkout",
  "ops",
  "audit",
]);

/**
 * @param {string} filename
 * @returns {{ srcRoot: string, area: string | null } | null}
 */
function locate(filename) {
  const normalized = filename.replace(/\\/g, "/").replace(/[?#].*$/, "");
  const marker = "/src/";
  const markerIndex = normalized.lastIndexOf(marker);
  if (markerIndex >= 0) {
    const srcRoot = normalized.slice(0, markerIndex + marker.length - 1);
    const rest = normalized.slice(markerIndex + marker.length);
    const first = rest.split("/")[0] ?? "";
    return { srcRoot, area: AREAS.has(first) ? first : null };
  }
  if (normalized.startsWith("src/")) {
    const first = normalized.slice("src/".length).split("/")[0] ?? "";
    return { srcRoot: "src", area: AREAS.has(first) ? first : null };
  }
  return null;
}

/**
 * @param {{ srcRoot: string, area: string | null } | null} source
 * @param {string} filename
 * @param {string} specifier
 * @returns {string | null}
 */
function resolveTarget(source, filename, specifier) {
  if (!source) return null;
  const cleaned = specifier.replace(/[?#].*$/, "");
  if (cleaned.startsWith("@/")) {
    return `${source.srcRoot}/${cleaned.slice(2)}`.replace(/\/+/g, "/");
  }
  if (!cleaned.startsWith(".")) return null;
  const base = filename.replace(/\\/g, "/").replace(/[?#].*$/, "");
  const directory = base.slice(0, base.lastIndexOf("/"));
  const parts = `${directory}/${cleaned}`.split("/");
  /** @type {string[]} */
  const stack = [];
  for (const part of parts) {
    if (part === "" || part === ".") continue;
    if (part === "..") {
      stack.pop();
      continue;
    }
    stack.push(part);
  }
  return stack.join("/");
}

/**
 * @param {string} srcRoot
 * @param {string} target
 * @returns {string | null}
 */
function targetArea(srcRoot, target) {
  if (target === srcRoot) return null;
  const prefix = `${srcRoot}/`;
  if (!target.startsWith(prefix)) return null;
  const first = target.slice(prefix.length).split("/")[0] ?? "";
  return AREAS.has(first) ? first : null;
}

/**
 * @param {string} srcRoot
 * @param {string} area
 * @param {string} target
 * @returns {boolean}
 */
function isAreaIndex(srcRoot, area, target) {
  const root = `${srcRoot}/${area}`;
  return target === root || target === `${root}/index` || target === `${root}/index.ts`;
}

/** @type {import("eslint").Rule.RuleModule} */
export const areaBoundariesRule = {
  meta: {
    type: "problem",
    docs: {
      description:
        "Areas import other areas only through index.ts; shared imports no area.",
    },
    messages: {
      sharedImport:
        "'shared' may import no area; found an import of area '{{target}}'.",
      deepImport:
        "Area '{{source}}' may import area '{{target}}' only through '{{target}}/index.ts' (scaffold section 5.8).",
    },
    schema: [],
  },

  create(context) {
    const filename = context.filename;
    const source = locate(filename);

    /** @param {string} specifier @param {import("estree").Node} node */
    function check(specifier, node) {
      if (!source || !source.area) return;
      const target = resolveTarget(source, filename, specifier);
      if (!target) return;
      const area = targetArea(source.srcRoot, target);
      if (!area || area === source.area) return;

      if (source.area === "shared") {
        context.report({
          node,
          messageId: "sharedImport",
          data: { target: area },
        });
        return;
      }
      if (!isAreaIndex(source.srcRoot, area, target)) {
        context.report({
          node,
          messageId: "deepImport",
          data: { source: source.area, target: area },
        });
      }
    }

    return {
      ImportDeclaration(node) {
        if (typeof node.source.value === "string") {
          check(node.source.value, node.source);
        }
      },
      ExportNamedDeclaration(node) {
        if (node.source && typeof node.source.value === "string") {
          check(node.source.value, node.source);
        }
      },
      ExportAllDeclaration(node) {
        if (typeof node.source.value === "string") {
          check(node.source.value, node.source);
        }
      },
      ImportExpression(node) {
        if (node.source.type === "Literal" && typeof node.source.value === "string") {
          check(node.source.value, node.source);
        }
      },
    };
  },
};

const plugin = {
  meta: { name: "fairpool" },
  rules: {
    "area-boundaries": areaBoundariesRule,
  },
};

export default plugin;
