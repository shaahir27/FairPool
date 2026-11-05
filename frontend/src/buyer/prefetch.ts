import { prefetchWorkspace, resetReadCache } from "../shared";

export const resetBuyerPrefetch = resetReadCache;

export function prefetchBuyer(to: string): void {
  prefetchWorkspace(to);
  if (to === "/discover") void import("./discover/DiscoverPage").catch(() => {});
  else if (to === "/my-pools") void import("./my-pools/MyPoolsPage").catch(() => {});
  else if (to.startsWith("/pools/")) void import("./lobby/PoolPage").catch(() => {});
  else if (to === "/orders") void import("./orders/OrdersPage").catch(() => {});
}
