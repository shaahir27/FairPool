import { RuleTester } from "eslint";
import { describe, it } from "vitest";

import { areaBoundariesRule } from "../eslint-rules/area-boundaries.mjs";

RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    ecmaVersion: 2022,
    sourceType: "module",
  },
});

ruleTester.run("area-boundaries", areaBoundariesRule, {
  valid: [
    {
      name: "an area imports its own files",
      filename: "src/buyer/pages.tsx",
      code: 'import { BuyerLayout } from "./BuyerLayout";',
    },
    {
      name: "an area imports shared through its index",
      filename: "src/buyer/pages.tsx",
      code: 'import { PlaceholderPage } from "../shared";',
    },
    {
      name: "an area imports another area's index.ts",
      filename: "src/buyer/pages.tsx",
      code: 'import { MerchantLayout } from "../merchant/index.ts";',
    },
    {
      name: "the alias form of an area index is allowed",
      filename: "src/merchant/pages.tsx",
      code: 'import { formatCents } from "@/shared";',
    },
    {
      name: "App.tsx sits outside the areas",
      filename: "src/App.tsx",
      code: 'import { AuditPage } from "./audit";',
    },
    {
      name: "packages are not area imports",
      filename: "src/shared/components/PlaceholderPage.tsx",
      code: 'import { useState } from "react";',
    },
  ],
  invalid: [
    {
      name: "a deep import into another area is reported",
      filename: "src/buyer/pages.tsx",
      code: 'import { DemandPage } from "../merchant/pages";',
      errors: [
        {
          messageId: "deepImport",
          data: { source: "buyer", target: "merchant" },
        },
      ],
    },
    {
      name: "a deep import into shared is reported",
      filename: "src/buyer/pages.tsx",
      code: 'import { PlaceholderPage } from "../shared/components/PlaceholderPage";',
      errors: [
        {
          messageId: "deepImport",
          data: { source: "buyer", target: "shared" },
        },
      ],
    },
    {
      name: "shared may not import an area",
      filename: "src/shared/components/AreaLayout.tsx",
      code: 'import { BuyerLayout } from "../../buyer";',
      errors: [
        {
          messageId: "sharedImport",
          data: { target: "buyer" },
        },
      ],
    },
    {
      name: "re-exporting another area's deep path is reported",
      filename: "src/audit/AuditPage.tsx",
      code: 'export { OpsPage } from "../ops/OpsPage";',
      errors: [
        {
          messageId: "deepImport",
          data: { source: "audit", target: "ops" },
        },
      ],
    },
    {
      name: "dynamic imports are checked too",
      filename: "src/merchant/pages.tsx",
      code: 'const page = import("../buyer/pages");',
      errors: [
        {
          messageId: "deepImport",
          data: { source: "merchant", target: "buyer" },
        },
      ],
    },
    {
      name: "the extension form other than index.ts is reported",
      filename: "src/checkout/OfferCheckoutPage.tsx",
      code: 'import { FulfillmentPage } from "../merchant-fulfillment/index.tsx";',
      errors: [
        {
          messageId: "deepImport",
          data: { source: "checkout", target: "merchant-fulfillment" },
        },
      ],
    },
  ],
});
