import { BrowserRouter, Route, Routes } from "react-router-dom";

import { AuditPage } from "./audit";
import {
  AgentSettingsPage,
  BuyerLayout,
  BuyerOrderPage,
  DiscoverPage,
  LoginPage,
  MyPoolsPage,
  OrdersPage,
  PayPalSettingsPage,
  PoolPage,
  RegisterPage,
} from "./buyer";
import { OfferCheckoutPage } from "./checkout";
import {
  BidsPage,
  DemandPage,
  DeveloperPage,
  MerchantLayout,
  ProfilePage,
} from "./merchant";
import { FulfillmentPage } from "./merchant-fulfillment";
import { OpsPage } from "./ops";

/**
 * Exactly the seventeen routes in docs/scaffold.md section 12. Layout routes
 * carry no path, so the count of `path` props stays at seventeen.
 */
export function AppRoutes() {
  return (
    <Routes>
      <Route path="/audit/:poolId" element={<AuditPage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />

      <Route element={<BuyerLayout />}>
        <Route path="/" element={<DiscoverPage />} />
        <Route path="/my-pools" element={<MyPoolsPage />} />
        <Route path="/orders" element={<OrdersPage />} />
        <Route path="/orders/:buyerOrderId" element={<BuyerOrderPage />} />
        <Route path="/pools/:poolId" element={<PoolPage />} />
        <Route path="/settings/paypal" element={<PayPalSettingsPage />} />
        <Route path="/settings/agents" element={<AgentSettingsPage />} />
      </Route>

      <Route path="/offers/:buyerOrderId" element={<OfferCheckoutPage />} />

      <Route element={<MerchantLayout />}>
        <Route path="/merchant/demand" element={<DemandPage />} />
        <Route path="/merchant/bids" element={<BidsPage />} />
        <Route path="/merchant/fulfillment" element={<FulfillmentPage />} />
        <Route path="/merchant/developer" element={<DeveloperPage />} />
        <Route path="/merchant/profile" element={<ProfilePage />} />
      </Route>

      <Route path="/ops/*" element={<OpsPage />} />
    </Routes>
  );
}

export default function App() {
  return (
    <BrowserRouter
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <AppRoutes />
    </BrowserRouter>
  );
}
