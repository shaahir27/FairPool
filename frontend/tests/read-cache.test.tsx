import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { api, readClient, prefetchRead, resetSessionCache, useApiRead } from "../src/shared";

type Item = { title: string };
type Load = (signal: AbortSignal) => Promise<{data?: Item; error?: unknown}>;
function View({ resource, load }: { resource: string; load: Load }) {
  const result = useApiRead(resource, load);
  return <><p>{result.data?.title ?? (result.isError ? "Read failed" : "Loading")}</p>
    <output>{result.isFetching && result.data ? "Updating" : ""}</output>
    <button onClick={() => void result.refetch()}>Refresh</button></>;
}
afterEach(() => { vi.unstubAllGlobals(); });

it.each(["buyer", "merchant", "admin"])("retains %s records on return without another fresh read", async (role) => {
  const load = vi.fn<Load>().mockResolvedValue({data: {title: `${role} records`}});
  const first = render(<View resource={role} load={load} />);
  await screen.findByText(`${role} records`);
  first.unmount();
  render(<View resource={role} load={load} />);
  expect(screen.getByText(`${role} records`)).toBeInTheDocument();
  expect(load).toHaveBeenCalledTimes(1);
});

it("retains stale content while fetching the new snapshot in the background", async () => {
  readClient.setQueryData(["catalogue"], {title: "Previous catalogue"}, {updatedAt: Date.now() - 60_000});
  let finish!: (value: {data: Item}) => void;
  const load = vi.fn<Load>(() => new Promise((resolve) => {finish = resolve;}));
  render(<View resource="catalogue" load={load} />);
  expect(screen.getByText("Previous catalogue")).toBeInTheDocument();
  expect(screen.queryByText("Loading")).toBeNull();
  expect(screen.getByText("Updating")).toBeInTheDocument();
  await act(async () => {finish({data: {title: "New catalogue"}});});
  expect(await screen.findByText("New catalogue")).toBeInTheDocument();
});

it("deduplicates an in-flight prefetch and the mounted screen", async () => {
  let finish!: (value: {data: Item}) => void;
  const load = vi.fn<Load>(() => new Promise((resolve) => {finish = resolve;}));
  const warm = prefetchRead("pool", load);
  render(<View resource="pool" load={load} />);
  expect(load).toHaveBeenCalledTimes(1);
  await act(async () => {finish({data: {title: "Prefetched pool"}}); await warm;});
  expect(await screen.findByText("Prefetched pool")).toBeInTheDocument();
});

it("does not substitute another pool's data while a new pool loads", async () => {
  const load = vi.fn<Load>().mockResolvedValueOnce({data: {title: "First pool"}}).mockReturnValue(new Promise(() => {}));
  const view = render(<View resource="pool/1" load={load} />);
  await screen.findByText("First pool");
  view.rerender(<View resource="pool/2" load={load} />);
  expect(screen.queryByText("First pool")).toBeNull();
  expect(screen.getByText("Loading")).toBeInTheDocument();
});

it("does not cache a failed response as data or hide it behind automatic retries", async () => {
  const load = vi.fn<Load>().mockResolvedValueOnce({error: {error: {code: "REQUEST_FAILED"}}}).mockResolvedValue({data: {title: "Recovered"}});
  render(<View resource="records" load={load} />);
  await screen.findByText("Read failed");
  expect(load).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByText("Refresh"));
  expect(await screen.findByText("Recovered")).toBeInTheDocument();
});

it("clears private records on session change and ignores a late response from the old session", async () => {
  let finish!: (value: {data: Item}) => void;
  const warm = prefetchRead<Item>("private", () => new Promise((resolve) => {finish = resolve;}));
  resetSessionCache("out");
  const load = vi.fn<Load>().mockResolvedValue({data: {title: "New account"}});
  render(<View resource="private" load={load} />);
  await screen.findByText("New account");
  await act(async () => {finish({data: {title: "Previous account"}}); await warm;});
  expect(screen.queryByText("Previous account")).toBeNull();
  expect(readClient.getQueryData(["private"])).toEqual({title: "New account"});
});

it("refreshes mounted reads after an API write", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({})));
  const load = vi.fn<Load>().mockResolvedValueOnce({data: {title: "Before write"}}).mockResolvedValue({data: {title: "After write"}});
  render(<View resource="mutable" load={load} />);
  await screen.findByText("Before write");
  await act(async () => {await api.POST("/api/v1/auth/logout", {fetch: async () => Response.json({})});});
  await waitFor(() => expect(screen.getByText("After write")).toBeInTheDocument());
});
