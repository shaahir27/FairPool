import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import postcss from "postcss";
import { describe, expect, it } from "vitest";

// Source-color checks complement browser QA; media hover rules are included so a
// later desktop override cannot silently erase a button's label contrast.
const css = postcss.parse(readFileSync(resolve("src/index.css"), "utf8"));
const tokens = new Map<string, string>();
css.walkDecls(/^--/, (decl) => { tokens.set(decl.prop, decl.value); });
const landing = postcss.parse(readFileSync(resolve("src/landing/landing.css"), "utf8"));
landing.walkDecls(/^--/, (decl) => { tokens.set(decl.prop, decl.value); });
type RGB = [number, number, number];

function rgb(value: string): RGB {
  let resolved = value;
  while (/var\(--[\w-]+\)/.test(resolved)) {
    resolved = resolved.replace(/var\((--[\w-]+)\)/g, (_, name: string) => tokens.get(name) ?? "");
  }
  const mixed = resolved.match(/^color-mix\(in srgb, rgb\(([^)]+)\), rgb\(([^)]+)\) (\d+)%\)$/);
  if (mixed) {
    const a = rgb(`rgb(${mixed[1]})`), b = rgb(`rgb(${mixed[2]})`);
    const weight = Number(mixed[3]) / 100;
    return a.map((channel, i) => channel * (1 - weight) + b[i]! * weight) as RGB;
  }
  const channels = resolved.replace(/^rgb\(|\)$/g, "").trim().split(/\s+/).map(Number);
  if (channels.length !== 3 || channels.some((channel) => !Number.isFinite(channel))) {
    throw new Error(`Unsupported color in contrast check: ${value}`);
  }
  return channels as RGB;
}

function luminance(color: RGB): number {
  const linear = color.map((v) => v / 255).map((v) => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4);
  return linear[0]! * .2126 + linear[1]! * .7152 + linear[2]! * .0722;
}

function contrast(a: string, b: string): number {
  const [dark, light] = [luminance(rgb(a)), luminance(rgb(b))].sort((x, y) => x - y);
  return (light! + .05) / (dark! + .05);
}

function buttonColors(state: string): Map<string, string> {
  const declarations = new Map<string, string>();
  const accepted = [".button-primary", `.button-primary:not(:disabled):${state}`];
  css.walkRules((rule) => {
    if (rule.selectors.some((selector) => accepted.includes(selector))) {
      rule.walkDecls((decl) => { declarations.set(decl.prop, decl.value); });
    }
  });
  return declarations;
}

describe("palette readability", () => {
  it("keeps the landing winning bid readable on the blue field", () => {
    let foreground = "";
    landing.walkRules((rule) => {
      if (rule.selectors.includes(":where(.landing) .stage .bid.w")) {
        rule.walkDecls("color", (decl) => { foreground = decl.value; });
      }
    });
    expect(contrast(foreground, "var(--fld)")).toBeGreaterThanOrEqual(4.5);
  });
  it.each(["default", "hover", "focus-visible", "active"])("keeps the primary button label readable in the %s state", (state) => {
    const declarations = buttonColors(state);
    expect(contrast(declarations.get("color")!, declarations.get("background")!)).toBeGreaterThanOrEqual(4.5);
  });

  it("keeps the label fixed and readable throughout the hover color transition", () => {
    const rest = buttonColors("default"), hover = buttonColors("hover");
    expect(hover.get("color")).toBe(rest.get("color"));
    const start = rgb(rest.get("background")!), end = rgb(hover.get("background")!);
    for (const progress of [0, .25, .5, .75, 1]) {
      const fill = start.map((channel, index) => channel + (end[index]! - channel) * progress);
      expect(contrast(rest.get("color")!, `rgb(${fill.join(" ")})`)).toBeGreaterThanOrEqual(4.5);
    }
  });

  it.each([
    ["ink", "surface"], ["muted", "surface"], ["muted", "card"],
    ["on-field", "brand-field"], ["field-muted", "field-band"], ["field-muted", "brand-field"],
    ["ink", "product-screen"], ["muted", "tint"],
    ["muted", "product-warm"], ["muted", "coral-tint"],
  ])("keeps %s readable on %s", (foreground, background) => {
    expect(contrast(tokens.get(`--color-${foreground}`)!, tokens.get(`--color-${background}`)!)).toBeGreaterThanOrEqual(4.5);
  });
});
