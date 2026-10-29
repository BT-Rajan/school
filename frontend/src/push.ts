/** Web Push on this device (FR-N3): opt in per browser; signing out removes it on the server. */
import { api, ApiError } from "./api";

export function pushSupported(): boolean {
  return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

function keyBytes(base64url: string): Uint8Array {
  const padded = (base64url + "===".slice((base64url.length + 3) % 4)).replace(/-/g, "+").replace(/_/g, "/");
  return Uint8Array.from(atob(padded), (c) => c.charCodeAt(0));
}

/** The server's key, or null when push is not set up for this district. */
export async function serverKey(): Promise<string | null> {
  try {
    return (await api<{ public_key: string }>("/api/push/key")).public_key;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export async function currentSubscription(): Promise<PushSubscription | null> {
  if (!pushSupported()) return null;
  const registration = await navigator.serviceWorker.ready;
  return registration.pushManager.getSubscription();
}

export async function enablePush(key: string): Promise<boolean> {
  if ((await Notification.requestPermission()) !== "granted") return false;
  const registration = await navigator.serviceWorker.ready;
  const subscription =
    (await registration.pushManager.getSubscription()) ??
    (await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(key) }));
  const json = subscription.toJSON();
  await api("/api/push/subscriptions", { method: "POST", body: { endpoint: json.endpoint, keys: json.keys } });
  return true;
}

export async function disablePush(): Promise<void> {
  const subscription = await currentSubscription();
  if (!subscription) return;
  await api("/api/push/subscriptions/remove", { method: "POST", body: { endpoint: subscription.endpoint } }).catch(() => {});
  await subscription.unsubscribe();
}
