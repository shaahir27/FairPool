import { useEffect, useRef, useState } from "react";

import { api, type ApiComponents, type DeliveryAddress, Notice } from "../shared";

type CheckoutConfig = ApiComponents["schemas"]["CheckoutConfigResponse"];
type ApiFailure = { code: string; message: string };
type Phase = "loading" | "ready" | "fallback";

type OneTimeSession = {
  start: (
    options: { presentationMode: "auto" },
    order: Promise<{ orderId: string }>,
  ) => Promise<unknown>;
};
type PayPalInstance = {
  findEligibleMethods: (options: { currencyCode: string }) => Promise<
    { isEligible?: (method: string) => boolean } | null | undefined
  >;
  createPayPalOneTimePaymentSession: (callbacks: {
    onApprove: (data: { orderId?: string | null }) => void | Promise<void>;
    onCancel: () => void | Promise<void>;
    onError: (reason: unknown) => void;
  }) => OneTimeSession;
};
type PayPalGlobal = {
  createInstance: (options: Record<string, unknown>) => Promise<PayPalInstance>;
};

function paypalGlobal(): PayPalGlobal | null {
  const candidate = (window as unknown as { paypal?: unknown }).paypal;
  if (candidate && typeof (candidate as PayPalGlobal).createInstance === "function") {
    return candidate as PayPalGlobal;
  }
  return null;
}

/**
 * Load the v6 core script once. The custom element and session API appear only
 * after this resolves, so nothing else may run before it.
 */
function loadSdk(url: string): Promise<PayPalGlobal> {
  const existing = paypalGlobal();
  if (existing) return Promise.resolve(existing);
  return new Promise((resolve, reject) => {
    let script = document.querySelector<HTMLScriptElement>(`script[data-paypal-sdk="${url}"]`);
    const settle = () => {
      const sdk = paypalGlobal();
      if (sdk) resolve(sdk);
      else reject(new Error("SDK_UNAVAILABLE"));
    };
    const fail = () => reject(new Error("SDK_LOAD_FAILED"));
    if (script) {
      script.addEventListener("load", settle);
      script.addEventListener("error", fail);
      return;
    }
    script = document.createElement("script");
    script.src = url;
    script.async = true;
    script.dataset.paypalSdk = url;
    script.addEventListener("load", settle);
    script.addEventListener("error", fail);
    document.head.appendChild(script);
  });
}

function fallbackMessage(reason: unknown): string {
  if (reason instanceof Error && reason.message === "PAYPAL_NOT_ELIGIBLE") {
    return "PayPal's inline button is not available for this checkout, so the standard PayPal page is used.";
  }
  return "The inline PayPal button could not load, so the standard PayPal page is used.";
}

function codeOf(failure: unknown): ApiFailure {
  const envelope = failure as { error?: { code?: string; message?: string } } | undefined;
  return {
    code: envelope?.error?.code ?? "REQUEST_FAILED",
    message: envelope?.error?.message ?? "The request could not be completed. Please try again.",
  };
}

export function PayPalButton({
  config,
  buyerOrderId,
  shipping,
  disabled = false,
  ensureShipping,
  onRefresh,
  onFallback,
}: {
  config: CheckoutConfig;
  buyerOrderId: string;
  shipping: DeliveryAddress;
  disabled?: boolean;
  /** Returns false after showing the incomplete-address message. */
  ensureShipping: () => boolean;
  onRefresh: () => void;
  onFallback: (message: string) => void;
}) {
  const [phase, setPhase] = useState<Phase>("loading");
  const [error, setError] = useState<ApiFailure | null>(null);
  const instance = useRef<PayPalInstance | null>(null);
  const host = useRef<HTMLDivElement>(null);
  const startRef = useRef<() => void>(() => {});
  const fallback = useRef(onFallback);
  fallback.current = onFallback;

  useEffect(() => {
    let live = true;
    const init = async () => {
      try {
        const sdk = await loadSdk(config.sdk_url);
        const base = { components: config.components, pageType: config.page_type };
        let created: PayPalInstance;
        if (config.sdk_auth === "client_token") {
          const { data, error: failure } = await api.GET("/api/v1/checkout/client-token");
          if (failure || !data?.client_token) throw new Error("TOKEN_UNAVAILABLE");
          created = await sdk.createInstance({ ...base, clientToken: data.client_token });
        } else {
          created = await sdk.createInstance({ ...base, clientId: config.client_id });
        }
        const methods = await created.findEligibleMethods({ currencyCode: config.currency });
        // api.md section 4.1: the button is shown only when PayPal itself is eligible.
        if (methods?.isEligible?.("paypal") !== true) throw new Error("PAYPAL_NOT_ELIGIBLE");
        if (!live) return;
        instance.current = created;
        setPhase("ready");
      } catch (reason) {
        if (!live) return;
        setPhase("fallback");
        fallback.current(fallbackMessage(reason));
      }
    };
    void init();
    return () => {
      live = false;
    };
  }, [config]);

  const approve = async (data: { orderId?: string | null }) => {
    const orderId = data?.orderId;
    if (!orderId) {
      setError({ code: "PAYPAL_SDK_ERROR", message: "PayPal did not return an order ID, so nothing was sent for approval." });
      return;
    }
    // INT-7: the browser posts the order ID only; the server fetches and verifies
    // the order from PayPal, then authorizes. No amount ever leaves this page.
    const { error: failure } = await api.POST("/api/v1/offers/{buyer_order_id}/approved", {
      params: { path: { buyer_order_id: buyerOrderId } },
      body: { paypal_order_id: orderId },
    });
    if (failure) {
      setError(codeOf(failure));
      return;
    }
    onRefresh();
  };

  const cancel = async () => {
    const { error: failure } = await api.POST("/api/v1/offers/{buyer_order_id}/cancelled", {
      params: { path: { buyer_order_id: buyerOrderId } },
      body: {},
    });
    if (failure) {
      setError(codeOf(failure));
      return;
    }
    onRefresh();
  };

  const sdkError = (reason: unknown) => {
    // api.md section 4.1: show a retry and log the SDK error code, never the payload.
    const code =
      typeof reason === "object" && reason !== null && "code" in reason
        ? String((reason as { code?: unknown }).code)
        : "UNKNOWN";
    console.error(`PayPal SDK error: ${code}`);
    setError({ code: "PAYPAL_SDK_ERROR", message: "PayPal's window could not open. Try again." });
  };

  const createOrder = async (): Promise<{ orderId: string }> => {
    const { data, error: failure } = await api.POST("/api/v1/offers/{buyer_order_id}/continue", {
      params: { path: { buyer_order_id: buyerOrderId } },
      // I3, INT-7: the browser sends the shipping address only. The server reads
      // every amount from the award snapshot.
      body: { shipping },
    });
    if (failure || !data?.paypal_order_id) {
      const detail = codeOf(failure);
      setError(detail);
      throw new Error(detail.code);
    }
    return { orderId: data.paypal_order_id };
  };

  const start = () => {
    const sdk = instance.current;
    if (disabled || phase !== "ready" || !sdk) return;
    if (!ensureShipping()) return;
    setError(null);
    try {
      const session = sdk.createPayPalOneTimePaymentSession({
        onApprove: approve,
        onCancel: cancel,
        onError: sdkError,
      });
      void session.start({ presentationMode: "auto" }, createOrder()).catch(() => {
        setError((previous) => previous ?? {
          code: "PAYPAL_SDK_ERROR",
          message: "PayPal did not complete the approval. Nothing was charged.",
        });
      });
    } catch {
      setError({ code: "PAYPAL_SDK_ERROR", message: "PayPal's window could not open. Try again." });
    }
  };
  startRef.current = () => start();

  useEffect(() => {
    const container = host.current;
    if (phase !== "ready" || !container) return;
    const button = document.createElement("paypal-button");
    button.setAttribute("type", "pay");
    button.setAttribute("aria-label", "PayPal");
    button.className = "checkout-paypal-button";
    button.style.width = "100%";
    button.style.minHeight = "48px";
    if (disabled) button.setAttribute("aria-disabled", "true");
    const onClick = () => startRef.current();
    button.addEventListener("click", onClick);
    container.appendChild(button);
    return () => {
      button.removeEventListener("click", onClick);
      button.remove();
    };
  }, [phase, disabled]);

  if (phase === "fallback") return null;

  return (
    <div className="grid gap-3">
      {phase === "loading" ? (
        <p className="py-2 text-xs text-muted" role="status">
          Preparing the PayPal button…
        </p>
      ) : null}
      <div ref={host} className="checkout-paypal-host w-full" />
      {error ? (
        <Notice kind="error" code={error.code}>
          {error.message}
        </Notice>
      ) : null}
    </div>
  );
}
