/**
 * Public surface of the `shared` area.
 *
 * Other areas import shared code only from this file (scaffold section 5.8).
 * `shared` itself imports no other area.
 */
export { API_BASE_URL, api } from "./api/client";
export type { ApiComponents, ApiPaths } from "./api/client";
export { AreaLayout } from "./components/AreaLayout";
export type { AreaTab, AreaUtilityLink } from "./components/AreaLayout";
export { AuthLayout } from "./components/AuthLayout";
export { HonestyLabels } from "./components/HonestyLabels";
export { PlaceholderPage } from "./components/PlaceholderPage";
export { PublicLayout } from "./components/PublicLayout";
export { formatCents, formatDateTime } from "./lib/format";
export { HONESTY_LABELS } from "./lib/labels";
export type { HonestyLabelKind } from "./lib/labels";
