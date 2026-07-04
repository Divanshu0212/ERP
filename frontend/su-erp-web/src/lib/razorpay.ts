// Razorpay Checkout.js integration helpers.
//
// The frontend never sees `key_secret`; the public `key_id` arrives in each
// backend response (razorpay-order / checkout). These helpers lazily inject the
// Checkout.js script once and open the hosted widget, forwarding the
// razorpay_* fields back to the caller on success.

const CHECKOUT_SRC = "https://checkout.razorpay.com/v1/checkout.js";

/** Razorpay handler response, forwarded to the backend for verification. */
export interface RazorpayHandlerResponse {
  razorpay_order_id: string;
  razorpay_payment_id: string;
  razorpay_signature: string;
}

interface RazorpayOptions {
  key: string;
  amount: number;
  currency: string;
  order_id: string;
  name: string;
  description?: string;
  handler: (response: RazorpayHandlerResponse) => void;
  prefill?: { email?: string };
  theme?: { color?: string };
  modal?: { ondismiss?: () => void };
}

interface RazorpayInstance {
  open: () => void;
}

interface RazorpayConstructor {
  new (options: RazorpayOptions): RazorpayInstance;
}

declare global {
  interface Window {
    Razorpay?: RazorpayConstructor;
  }
}

let loadPromise: Promise<void> | null = null;

/**
 * Inject the Checkout.js script tag once and resolve when `window.Razorpay`
 * is available. Subsequent calls reuse the same in-flight/settled promise.
 * Rejects if the script fails to load.
 */
export function loadRazorpayCheckout(): Promise<void> {
  if (typeof window !== "undefined" && window.Razorpay) {
    return Promise.resolve();
  }
  if (loadPromise) return loadPromise;

  loadPromise = new Promise<void>((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(
      `script[src="${CHECKOUT_SRC}"]`,
    );

    const onLoaded = () => {
      if (window.Razorpay) resolve();
      else reject(new Error("Razorpay checkout failed to initialize."));
    };
    const onError = () => {
      loadPromise = null;
      reject(new Error("Failed to load Razorpay checkout."));
    };

    if (existing) {
      existing.addEventListener("load", onLoaded, { once: true });
      existing.addEventListener("error", onError, { once: true });
      // Script tag present but possibly already loaded.
      if (window.Razorpay) resolve();
      return;
    }

    const script = document.createElement("script");
    script.src = CHECKOUT_SRC;
    script.async = true;
    script.addEventListener("load", onLoaded, { once: true });
    script.addEventListener("error", onError, { once: true });
    document.head.appendChild(script);
  });

  return loadPromise;
}

/** Convert a decimal-rupee amount (number or string) to integer paise. */
export function toPaise(amount: number | string): number {
  const rupees = typeof amount === "number" ? amount : parseFloat(amount);
  return Math.round(rupees * 100);
}

export interface OpenCheckoutOptions {
  keyId: string;
  orderId: string;
  amountPaise: number;
  currency: string;
  name: string;
  description?: string;
  prefillEmail?: string;
  onSuccess: (res: RazorpayHandlerResponse) => void;
  onDismiss: () => void;
  onError?: (msg: string) => void;
}

/**
 * Load Checkout.js (if needed) then construct and open the Razorpay widget.
 * `onSuccess` fires with the razorpay_* fields; `onDismiss` fires when the user
 * closes the modal without paying; `onError` fires if the script/widget fails.
 */
export async function openRazorpayCheckout(opts: OpenCheckoutOptions): Promise<void> {
  try {
    await loadRazorpayCheckout();
  } catch (e) {
    opts.onError?.(e instanceof Error ? e.message : "Failed to load Razorpay.");
    return;
  }

  const Ctor = window.Razorpay;
  if (!Ctor) {
    opts.onError?.("Razorpay checkout is unavailable.");
    return;
  }

  const rzp = new Ctor({
    key: opts.keyId,
    amount: opts.amountPaise,
    currency: opts.currency,
    order_id: opts.orderId,
    name: opts.name,
    description: opts.description,
    handler: (response) => opts.onSuccess(response),
    prefill: opts.prefillEmail ? { email: opts.prefillEmail } : undefined,
    theme: { color: "#4f46e5" },
    modal: { ondismiss: () => opts.onDismiss() },
  });
  rzp.open();
}
