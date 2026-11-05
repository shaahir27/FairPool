import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const transport = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), remove: vi.fn() }));
vi.mock("../src/shared/api/client", () => ({
  api: {
    GET: transport.get,
    POST: transport.post,
    PUT: transport.put,
    DELETE: transport.remove,
  },
  API_BASE_URL: "http://localhost:8000",
}));

import { DeveloperPage } from "../src/merchant/developer/DeveloperPage";

const KEY = {
  id: "key-one",
  name: "pricing-bot",
  key_prefix: "fpm_abc123",
  scopes: ["lots:read", "bids:read"],
  last_used_at: null,
  revoked_at: null,
};

function show() {
  return render(
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }} initialEntries={["/merchant/developer"]}>
      <DeveloperPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  transport.get.mockReset();
  transport.post.mockReset();
  transport.put.mockReset();
  transport.remove.mockReset();
  transport.get.mockResolvedValue({ data: { items: [KEY] } });
  Object.assign(navigator, {
    clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
  });
});

describe("Developer API", () => {
  it("lists key prefixes only and never a secret", async () => {
    show();
    expect(await screen.findByText("fpm_abc123")).toBeInTheDocument();
    expect(screen.queryByText(/fpm_abc123_secret/)).not.toBeInTheDocument();
    expect(screen.getByText("120 requests per minute per key.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Merchant API OpenAPI document" })).toHaveAttribute(
      "href",
      "/merchant-api/v1/openapi.json",
    );
  });

  it("shows a new secret once, with a copy action and a warning", async () => {
    transport.post.mockResolvedValue({
      data: {
        id: "key-two",
        name: "bid-writer",
        key: "fpm_newprefix_secretvalue",
        scopes: ["lots:read", "bids:read", "bids:write"],
      },
    });
    show();
    await screen.findByText("fpm_abc123");

    fireEvent.change(screen.getByLabelText("Key name"), { target: { value: "bid-writer" } });
    fireEvent.click(screen.getByLabelText(/Submit bids/));
    fireEvent.click(screen.getByRole("button", { name: "Create key" }));

    expect(await screen.findByText("fpm_newprefix_secretvalue")).toBeInTheDocument();
    expect(screen.getByText(/shown once\. Store it now/)).toBeInTheDocument();
    expect(screen.getByText(/cannot show it again/)).toBeInTheDocument();

    const [, init] = transport.post.mock.calls[0] ?? [];
    expect(transport.post.mock.calls[0]?.[0]).toBe("/api/v1/merchant/api-keys");
    expect(init?.body).toEqual({
      name: "bid-writer",
      scopes: ["lots:read", "bids:read", "bids:write"],
    });

    fireEvent.click(screen.getByRole("button", { name: "Copy key" }));
    await waitFor(() =>
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith("fpm_newprefix_secretvalue"),
    );
    expect(await screen.findByRole("button", { name: "Key copied" })).toBeInTheDocument();
  });

  it("asks before revoking a key and then marks it revoked", async () => {
    transport.remove.mockResolvedValue({ data: null });
    show();
    await screen.findByText("fpm_abc123");

    fireEvent.click(screen.getByRole("button", { name: "Revoke pricing-bot" }));
    expect(screen.getByText("Revoke this key? Requests using it will fail immediately.")).toBeInTheDocument();
    expect(transport.remove).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Confirm revoke" }));

    await waitFor(() =>
      expect(transport.remove).toHaveBeenCalledWith("/api/v1/merchant/api-keys/{key_id}", {
        params: { path: { key_id: "key-one" } },
      }),
    );
    expect(await screen.findByText("Revoked")).toBeInTheDocument();
    // The DELETE returns no timestamp; the page must not invent one from the browser clock.
    expect(screen.queryByText(/^Revoked /)).not.toBeInTheDocument();
  });
});
