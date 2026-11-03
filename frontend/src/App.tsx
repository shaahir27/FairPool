import { Component, lazy, Suspense, type ReactNode } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import { RequireAuth } from "./shared";

// Load a workspace when it is visited, instead of downloading every screen at login.
const AuditPage = lazy(() => import("./audit").then((m) => ({ default: m.AuditPage })));
const BuyerLayout = lazy(() => import("./buyer/BuyerLayout").then((m) => ({ default: m.BuyerLayout })));
const DiscoverPage = lazy(() => import("./buyer/discover/DiscoverPage").then((m) => ({ default: m.DiscoverPage })));
const PoolPage = lazy(() => import("./buyer/lobby/PoolPage").then((m) => ({ default: m.PoolPage })));
const LoginPage = lazy(() => import("./buyer/pages").then((m) => ({ default: m.LoginPage })));
const RegisterPage = lazy(() => import("./buyer/signup").then((m) => ({ default: m.RegisterPage })));
const SignupConnectedPage = lazy(() => import("./buyer/signup").then((m) => ({ default: m.SignupConnectedPage })));
const SignupDetailsPage = lazy(() => import("./buyer/signup").then((m) => ({ default: m.SignupDetailsPage })));
const AddressesPage = lazy(() => import("./buyer/AddressesPage").then((m) => ({ default: m.AddressesPage })));
const AgentSettingsPage = lazy(() => import("./buyer/pages").then((m) => ({ default: m.AgentSettingsPage })));
const BuyerOrderPage = lazy(() => import("./buyer/pages").then((m) => ({ default: m.BuyerOrderPage })));
const MyPoolsPage = lazy(() => import("./buyer/pages").then((m) => ({ default: m.MyPoolsPage })));
const OrdersPage = lazy(() => import("./buyer/pages").then((m) => ({ default: m.OrdersPage })));
const PayPalSettingsPage = lazy(() => import("./buyer/pages").then((m) => ({ default: m.PayPalSettingsPage })));
const OfferCheckoutPage = lazy(() => import("./checkout").then((m) => ({ default: m.OfferCheckoutPage })));
const MerchantLayout = lazy(() => import("./merchant").then((m) => ({ default: m.MerchantLayout })));
const BidsPage = lazy(() => import("./merchant").then((m) => ({ default: m.BidsPage })));
const DemandPage = lazy(() => import("./merchant").then((m) => ({ default: m.DemandPage })));
const DeveloperPage = lazy(() => import("./merchant").then((m) => ({ default: m.DeveloperPage })));
const ProfilePage = lazy(() => import("./merchant").then((m) => ({ default: m.ProfilePage })));
const FulfillmentPage = lazy(() => import("./merchant-fulfillment").then((m) => ({ default: m.FulfillmentPage })));
const OpsPage = lazy(() => import("./ops").then((m) => ({ default: m.OpsPage })));

export class RouteLoadBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() { return { failed: true }; }

  render() {
    if (this.state.failed) return <main className="route-loading" role="alert">
      <h1 className="shop-title">This page could not be loaded</h1>
      <p>Check your connection, then reload to try again.</p>
      <button type="button" className="button-primary" onClick={() => window.location.reload()}>Reload page</button>
    </main>;
    return this.props.children;
  }
}

/**
 * Workspace routes plus the browser-bound PayPal signup steps (CR-6).
 */
export function AppRoutes() {
  return (
    <RouteLoadBoundary>
    <Suspense fallback={<div className="route-loading" role="status" aria-label="Loading page"><p>Opening FairPool…</p><div className="skeleton" /></div>}>
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
    </Suspense>
    </RouteLoadBoundary>
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
