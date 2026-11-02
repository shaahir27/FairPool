import { BrowserRouter, Route, Routes } from "react-router-dom";

import { AuditPage } from "./audit";
import { RequireAuth } from "./shared";
import { SignupConnectedPage, SignupDetailsPage } from "./buyer/signup";
import { AddressesPage } from "./buyer/AddressesPage";
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
 * Workspace routes plus the browser-bound PayPal signup steps (CR-6).
 */
export function AppRoutes() {
  return (
    <Routes>
      <Route path="/audit/:poolId" element={<AuditPage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/register/connected" element={<SignupConnectedPage />} />
      <Route path="/register/details" element={<SignupDetailsPage />} />

      <Route
        element={
          <RequireAuth>
            <BuyerLayout />
          </RequireAuth>
        }
      >
        <Route path="/" element={<DiscoverPage />} />
        <Route path="/my-pools" element={<MyPoolsPage />} />
        <Route path="/orders" element={<OrdersPage />} />
        <Route path="/orders/:buyerOrderId" element={<BuyerOrderPage />} />
        <Route path="/pools/:poolId" element={<PoolPage />} />
        <Route path="/settings/paypal" element={<PayPalSettingsPage />} />
        <Route path="/settings/addresses" element={<AddressesPage />} />
        <Route path="/settings/agents" element={<AgentSettingsPage />} />
      </Route>

      <Route
        path="/offers/:buyerOrderId"
        element={
          <RequireAuth>
            <OfferCheckoutPage />
          </RequireAuth>
        }
      />

      <Route
        element={
          <RequireAuth>
            <MerchantLayout />
          </RequireAuth>
        }
      >
        <Route path="/merchant/demand" element={<DemandPage />} />
        <Route path="/merchant/bids" element={<BidsPage />} />
        <Route path="/merchant/fulfillment" element={<FulfillmentPage />} />
        <Route path="/merchant/developer" element={<DeveloperPage />} />
        <Route path="/merchant/profile" element={<ProfilePage />} />
      </Route>

      <Route
        path="/ops/*"
        element={
          <RequireAuth>
            <OpsPage />
          </RequireAuth>
        }
      />
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
