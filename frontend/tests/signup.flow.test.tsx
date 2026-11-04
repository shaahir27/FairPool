import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

const transport = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("../src/shared/api/client", () => ({
  api: { GET: transport.get, POST: transport.post }, API_BASE_URL: "http://localhost:8000",
}));

import { RegisterPage } from "../src/buyer/pages";
import { SignupConnectedPage, SignupDetailsPage } from "../src/buyer/signup";

beforeEach(() => {
  transport.get.mockReset().mockResolvedValue({ data: { enabled: true, status: "not_started" } });
  transport.post.mockReset();
  sessionStorage.clear();
});

function show() {
  render(<MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><RegisterPage /></MemoryRouter>);
}

async function hydrated() {
  // SignupDetailsPage renders its heading as soon as the status answer says "ready", but
  // it seeds email, name and address in a passive effect that lands a tick later. Typing
  // into or reading those fields before that flush races the effect: the seed can arrive
  // after the keystrokes and erase them. Flushing first is what makes the flow deterministic.
  await act(async () => { await Promise.resolve(); });
}

it("starts signup with PayPal before asking for account details", async () => {
  show();
  expect(await screen.findByRole("button", { name: "Continue with PayPal" })).toBeEnabled();
  expect(screen.queryByLabelText("Password")).toBeNull();
  expect(screen.getByText(/No charge. No hold./)).toBeInTheDocument();
});

it("offers recovery after an account conflict without looping back to details", async () => {
  transport.get.mockResolvedValue({ data: { enabled: true, status: "ready" } });
  render(<MemoryRouter initialEntries={["/register?reason=account_exists"]}><Routes>
    <Route path="/register" element={<RegisterPage />} />
    <Route path="/register/details" element={<p>Unexpected details</p>} />
  </Routes></MemoryRouter>);
  expect(await screen.findByRole("button", { name: "Continue with PayPal" })).toBeEnabled();
  expect(screen.queryByText("Unexpected details")).toBeNull();
});

it("never shows PayPal success from the URL alone", async () => {
  render(<MemoryRouter initialEntries={["/register/connected"]}><Routes>
    <Route path="/register/connected" element={<SignupConnectedPage />} />
    <Route path="/register" element={<p>Connect first</p>} />
  </Routes></MemoryRouter>);
  expect(await screen.findByText("Connect first")).toBeInTheDocument();
  expect(screen.queryByText("You’re connected.")).toBeNull();
});

it("confirms the server-verified connection before continuing automatically", async () => {
  transport.get.mockResolvedValue({ data: { enabled: true, status: "ready" } });
  render(<MemoryRouter initialEntries={["/register/connected"]}><Routes>
    <Route path="/register/connected" element={<SignupConnectedPage />} />
    <Route path="/register/details" element={<p>Account details</p>} />
  </Routes></MemoryRouter>);
  expect(await screen.findByRole("heading", { name: "You’re connected." })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Continue now/ })).toBeInTheDocument();
  expect(await screen.findByText("Account details", {}, { timeout: 3000 })).toBeInTheDocument();
});

it("keeps mismatched passwords out of the account-creation request", async () => {
  transport.get.mockResolvedValue({ data: { enabled: true, status: "ready" } });
  render(<MemoryRouter><SignupDetailsPage /></MemoryRouter>);
  await screen.findByRole("heading", { name: "Make it yours." });
  await hydrated();
  fireEvent.change(screen.getByLabelText("Display name"), { target: { value: "Buyer" } });
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "buyer@example.test" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "a long test password" } });
  fireEvent.change(screen.getByLabelText("Repeat password"), { target: { value: "a different password" } });
  expect(screen.getByText("Your passwords don’t match yet.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Continue to delivery" })).toBeDisabled();
  expect(transport.post).not.toHaveBeenCalled();
});

it("prefills PayPal details while leaving passwords empty and fields editable", async () => {
  transport.get.mockResolvedValue({ data: { enabled: true, status: "ready", prefill: { email: "buyer@example.test", display_name: "Pool Buyer" } } });
  render(<MemoryRouter><SignupDetailsPage /></MemoryRouter>);
  expect(await screen.findByDisplayValue("buyer@example.test")).toBeInTheDocument();
  expect(screen.getByLabelText("Display name")).toHaveValue("Pool Buyer");
  expect(screen.getByLabelText("Password")).toHaveValue("");
  fireEvent.change(screen.getByLabelText("Display name"), { target: { value: "My name" } });
  expect(screen.getByLabelText("Display name")).toHaveValue("My name");
});

it("creates the account and continues with the server-issued session", async () => {
  transport.get.mockResolvedValue({ data: { enabled: true, status: "ready" } });
  transport.post.mockResolvedValue({ data: { csrf_token: "fixture-csrf", user_id: "fixture-buyer" } });
  render(<MemoryRouter initialEntries={["/register/details"]}><Routes>
    <Route path="/register/details" element={<SignupDetailsPage />} />
    <Route path="/discover" element={<p>Your FairPool</p>} />
  </Routes></MemoryRouter>);
  await screen.findByRole("heading", { name: "Make it yours." });
  await hydrated();
  fireEvent.change(screen.getByLabelText("Display name"), { target: { value: "Buyer" } });
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "buyer@example.test" } });
  for (const label of ["Password", "Repeat password"]) fireEvent.change(screen.getByLabelText(label), { target: { value: "a long test password" } });
  fireEvent.click(screen.getByRole("button", { name: "Continue to delivery" }));
  expect(transport.post).not.toHaveBeenCalled();
  expect(await screen.findByRole("heading", { name: "Where should it arrive?" })).toBeInTheDocument();
  for (const [label, value] of [["Street address", "12 Test Lane"], ["City", "Test City"], ["State / region", "CA"], ["Postal code", "90210"]] as const) fireEvent.change(screen.getByLabelText(label), { target: { value } });
  fireEvent.submit(screen.getByRole("button", { name: "Create account" }).closest("form")!);
  expect(await screen.findByText("Your FairPool")).toBeInTheDocument();
  expect(transport.post).toHaveBeenCalledWith("/api/v1/auth/register", { body: {
    email: "buyer@example.test", display_name: "Buyer", password: "a long test password", password_confirm: "a long test password",
    delivery_address: { name: "Buyer", line1: "12 Test Lane", line2: "", city: "Test City", region: "CA", postal_code: "90210", country_code: "US" },
  } });
});

it("recovers when the PayPal connection cannot be started", async () => {
  transport.post.mockRejectedValue(new TypeError("connection unavailable"));
  show();
  fireEvent.click(await screen.findByRole("button", { name: "Continue with PayPal" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/try again/i));
  expect(screen.getByRole("button", { name: "Continue with PayPal" })).toBeEnabled();
});

it("keeps signup open for a second person on a signed-in device", async () => {
  // The duplicate rule is the PayPal account, not the browser, so /register stays
  // usable while someone else holds the live session (owner decision 2026-11-02).
  transport.get.mockImplementation((url: string) => {
    if (url === "/api/v1/me") return Promise.resolve({ data: { user_id: "user-123", email: "signedin@example.test" } });
    return Promise.resolve({ data: { enabled: true, status: "not_started" } });
  });
  render(
    <MemoryRouter initialEntries={["/register"]}>
      <Routes>
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/" element={<p>Home Page</p>} />
      </Routes>
    </MemoryRouter>
  );
  expect(await screen.findByRole("button", { name: /Continue with PayPal/ })).toBeEnabled();
  expect(screen.queryByText("Home Page")).not.toBeInTheDocument();
});

it("restores non-password draft across reconnections without saving passwords", async () => {
  sessionStorage.setItem("fairpool_signup_draft", JSON.stringify({
    email: "drafted@example.test",
    name: "Draft User",
    address: { name: "Draft User", line1: "99 Saved St", line2: "", city: "Draft City", region: "NY", postal_code: "10001", country_code: "US" },
  }));

  transport.get.mockResolvedValue({
    data: {
      enabled: true,
      status: "ready",
      prefill: { email: "paypal@example.test", display_name: "PayPal Name" },
    },
  });

  render(<MemoryRouter><SignupDetailsPage /></MemoryRouter>);
  await screen.findByRole("heading", { name: "Make it yours." });
  await waitFor(() => expect(screen.getByLabelText("Email")).toHaveValue("drafted@example.test"));
  expect(screen.getByLabelText("Display name")).toHaveValue("Draft User");
  expect(screen.getByLabelText("Password")).toHaveValue("");
});

it("clears the draft on successful registration", async () => {
  sessionStorage.setItem("fairpool_signup_draft", JSON.stringify({
    email: "drafted@example.test",
    name: "Draft User",
    address: { name: "Draft User", line1: "99 Saved St", line2: "", city: "Draft City", region: "NY", postal_code: "10001", country_code: "US" },
  }));

  transport.get.mockResolvedValue({ data: { enabled: true, status: "ready" } });
  transport.post.mockResolvedValue({ data: { csrf_token: "fixture-csrf", user_id: "fixture-buyer" } });

  render(<MemoryRouter initialEntries={["/register/details"]}><Routes>
    <Route path="/register/details" element={<SignupDetailsPage />} />
    <Route path="/discover" element={<p>Your FairPool</p>} />
  </Routes></MemoryRouter>);

  await screen.findByRole("heading", { name: "Make it yours." });
  await hydrated();
  for (const label of ["Password", "Repeat password"]) fireEvent.change(screen.getByLabelText(label), { target: { value: "a long test password" } });
  fireEvent.click(screen.getByRole("button", { name: "Continue to delivery" }));
  expect(await screen.findByRole("heading", { name: "Where should it arrive?" })).toBeInTheDocument();
  fireEvent.submit(screen.getByRole("button", { name: "Create account" }).closest("form")!);
  expect(await screen.findByText("Your FairPool")).toBeInTheDocument();
  expect(sessionStorage.getItem("fairpool_signup_draft")).toBeNull();
});
