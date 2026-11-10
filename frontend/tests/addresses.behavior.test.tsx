import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

const transport = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), remove: vi.fn() }));
vi.mock("../src/shared/api/client", () => ({ api: { GET: transport.get, POST: transport.post, PUT: transport.put, DELETE: transport.remove }, API_BASE_URL: "http://localhost:8000" }));
import { resetSessionCache, readClient } from "../src/shared";
import { AddressesPage } from "../src/buyer/AddressesPage";

const address = { name: "Pool Buyer", line1: "12 Test Lane", line2: "", city: "Test City", region: "CA", postal_code: "90210", country_code: "US" };
beforeEach(() => {
  vi.clearAllMocks();
  transport.get.mockResolvedValue({ data: { addresses: [{ id: "saved-one", address, is_default: true }] } });
});

it("lets a buyer edit a saved address and saves the changed fields", async () => {
  transport.put.mockResolvedValue({ data: { id: "saved-one", address: { ...address, city: "New City" }, is_default: true } });
  render(<AddressesPage />);
  fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
  expect(screen.getByLabelText("Street address")).toHaveValue("12 Test Lane");
  fireEvent.change(screen.getByLabelText("City"), { target: { value: "New City" } });
  fireEvent.click(screen.getByRole("button", { name: "Save address" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Address saved");
  expect(transport.put).toHaveBeenCalledWith("/api/v1/me/addresses/{address_id}", { params: { path: { address_id: "saved-one" } }, body: { address: { ...address, city: "New City" }, is_default: true } });
});

it("retains edits when saving fails", async () => {
  transport.put.mockRejectedValue(new TypeError("network unavailable"));
  render(<AddressesPage />);
  fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
  fireEvent.change(screen.getByLabelText("City"), { target: { value: "New City" } });
  fireEvent.click(screen.getByRole("button", { name: "Save address" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Your changes are still here"));
  expect(screen.getByLabelText("City")).toHaveValue("New City");
});

it("opens a focused address form from Add address without crowding the saved list", async () => {
  render(<AddressesPage />);
  await screen.findByText("Pool Buyer");
  expect(screen.queryByLabelText("Street address")).toBeNull();
  fireEvent.click(screen.getByRole("button", {name: "Add address"}));
  expect(screen.getByLabelText("Street address")).toBeInTheDocument();
  expect(screen.getByRole("heading", {name: "Add an address"})).toHaveFocus();
});


it("ignores an old account's saved address after switching accounts", async () => {
  resetSessionCache("in");
  let finish!: (value: unknown) => void;
  transport.put.mockReturnValue(new Promise((resolve) => {finish = resolve;}));
  const first = render(<AddressesPage />);
  fireEvent.click(await screen.findByRole("button", {name: "Edit"}));
  fireEvent.click(screen.getByRole("button", {name: "Save address"}));
  first.unmount();
  resetSessionCache("out");
  transport.get.mockResolvedValue({data: {addresses: [{id: "other-address", address: {...address, name: "Another buyer"}, is_default: true}]}});
  render(<AddressesPage />);
  await screen.findByText("Another buyer");
  await act(async () => {finish({data: {id: "saved-one", address, is_default: true}});});
  expect(screen.queryByText("Pool Buyer")).toBeNull();
  expect(screen.getByText("Another buyer")).toBeInTheDocument();
  const cached = readClient.getQueryData<{addresses: {id: string}[]}>(["/api/v1/me/addresses"]);
  expect(cached?.addresses.map((item) => item.id)).toEqual(["other-address"]);
});
