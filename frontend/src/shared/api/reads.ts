import { QueryClient, useIsFetching, useQuery } from "@tanstack/react-query";

type Read<T> = (signal: AbortSignal) => Promise<{ data?: T; error?: unknown }>;
const FRESH_MS = 15_000;

// Private data stays in memory and is discarded whenever the session changes.
export const readClient = new QueryClient({
  defaultOptions: { queries: { staleTime: FRESH_MS, gcTime: 300_000, retry: false, refetchOnWindowFocus: true } },
});

function options<T>(key: string, read: Read<T>, staleTime = FRESH_MS) {
  return {
    queryKey: [key], staleTime,
    queryFn: async ({ signal }: { signal: AbortSignal }): Promise<T> => {
      const result = await read(signal);
      if (result.error || result.data === undefined) throw result.error ?? new Error("Read unavailable");
      return result.data;
    },
  };
}

export function useApiRead<T>(key: string, read: Read<T>, config: { enabled?: boolean; staleTime?: number } = {}) {
  return useQuery<T, unknown>({ ...options(key, read, config.staleTime), enabled: config.enabled ?? true }, readClient);
}

export function prefetchRead<T>(key: string, read: Read<T>, staleTime?: number): Promise<void> {
  return readClient.prefetchQuery(options(key, read, staleTime));
}

export function resetReadCache(): void { readClient.clear(); }

export async function refreshReads(): Promise<void> {
  // A pre-write response must never replace the post-write result (I13).
  await readClient.cancelQueries();
  void readClient.invalidateQueries();
}

export function useRefreshingReads(): number {
  return useIsFetching({ predicate: (query) => query.state.data !== undefined }, readClient);
}
