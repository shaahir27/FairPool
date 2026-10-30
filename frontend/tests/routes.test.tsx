import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { AppRoutes } from "../src/App";

function renderAt(path: string) {
  return render(
    <MemoryRouter
      initialEntries={[path]}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <AppRoutes />
    </MemoryRouter>,
  );
}

describe("route smoke", () => {
  it("renders the Discover and Join placeholder at /", () => {
    renderAt("/");

    expect(
      screen.getByRole("heading", { level: 1, name: "Discover and Join" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Phase 1 placeholder/i)).toBeInTheDocument();
    expect(screen.getByText("T06B05")).toBeInTheDocument();
    expect(
      screen.getByRole("navigation", { name: "Buyer workspace tabs" }),
    ).toBeInTheDocument();
    expect(screen.getByText("SANDBOX")).toBeInTheDocument();
  });

  it("renders the merchant Demand Board placeholder", () => {
    renderAt("/merchant/demand");

    expect(
      screen.getByRole("heading", { level: 1, name: "Demand Board" }),
    ).toBeInTheDocument();
    expect(screen.getByText("T08B01")).toBeInTheDocument();
    expect(
      screen.getByRole("navigation", { name: "Merchant workspace tabs" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Fulfillment" }),
    ).toBeInTheDocument();
  });
});
