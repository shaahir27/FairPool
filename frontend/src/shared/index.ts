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
export { DeliveryAddressFields } from "./components/DeliveryAddressFields";
export { EMPTY_DELIVERY_ADDRESS } from "./lib/address";
export type { DeliveryAddress } from "./lib/address";
export { HonestyLabels } from "./components/HonestyLabels";
export { PlaceholderPage } from "./components/PlaceholderPage";
export { RequireAuth } from "./components/RequireAuth";
export { accountState, resetSessionCache, sessionState, setAccount, workspaceHome, workspaceRole } from "./lib/session";
export type { Account } from "./lib/session";
export { PublicLayout } from "./components/PublicLayout";
export { AuthAside } from "./components/AuthAside";
export { Brand, PoolMark } from "./components/Brand";
export { LoadingScreen } from "./components/LoadingScreen";
export { Icon } from "./components/Icon";
export { FieldError, Notice } from "./components/Notice";
export { StatusPill } from "./components/StatusPill";
export { getCsrfToken, setCsrfToken } from "./lib/csrf";
export { envelope, honestyKinds, productName, shortId } from "./lib/display";
export { formatCents, formatDateTime } from "./lib/format";
export { startRouteTransition, useCountdown } from "./lib/motion";
export {
  BUYER_ORDER_STATUS,
  LOT_STATUS,
  REJECT_REASON_LABELS,
  statusStyle,
  TERMINAL_BUYER_ORDER_STATUSES,
} from "./lib/status";
export type { StatusStyle, StatusTone } from "./lib/status";
export { HONESTY_LABELS } from "./lib/labels";
export type { HonestyLabelKind } from "./lib/labels";
export { ProductArt } from "./components/ProductArt";
