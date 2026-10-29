/**
 * The device's offline store (FR-PW3, FR-PW4), in IndexedDB:
 *  - kv: cached screens' data and the signed-in user, so the app opens without a connection
 *  - queue: changes made offline, waiting to be sent in order
 *  - blobs: photos and scans waiting to upload
 * Sign-out wipes all of it (FR-PW12). Without IndexedDB (unit tests, some private windows)
 * the same API keeps everything in memory for the session.
 */

const DB_NAME = "sces";
const STORES = ["kv", "queue", "blobs"] as const;
type Store = (typeof STORES)[number];

let opening: Promise<IDBDatabase | null> | null = null;
const memory: Record<Store, Map<string, unknown>> = { kv: new Map(), queue: new Map(), blobs: new Map() };

function open(): Promise<IDBDatabase | null> {
  if (opening) return opening;
  opening = new Promise((resolve) => {
    if (typeof indexedDB === "undefined") return resolve(null);
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => {
      for (const name of STORES) if (!request.result.objectStoreNames.contains(name)) request.result.createObjectStore(name);
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => resolve(null);
    request.onblocked = () => resolve(null);
  });
  return opening;
}

function run<T>(store: Store, mode: IDBTransactionMode, body: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return open().then(
    (db) =>
      new Promise<T>((resolve, reject) => {
        if (!db) throw new Error("no indexeddb");
        const tx = db.transaction(store, mode);
        const request = body(tx.objectStore(store));
        tx.oncomplete = () => resolve(request.result);
        tx.onerror = () => reject(tx.error);
        tx.onabort = () => reject(tx.error);
      }),
  );
}

async function available(): Promise<boolean> {
  return (await open()) !== null;
}

export async function get<T>(store: Store, key: string): Promise<T | undefined> {
  if (!(await available())) return memory[store].get(key) as T | undefined;
  return (await run(store, "readonly", (s) => s.get(key))) as T | undefined;
}

export async function put(store: Store, key: string, value: unknown): Promise<void> {
  if (!(await available())) {
    memory[store].set(key, value);
    return;
  }
  await run(store, "readwrite", (s) => s.put(value, key));
}

export async function del(store: Store, key: string): Promise<void> {
  if (!(await available())) {
    memory[store].delete(key);
    return;
  }
  await run(store, "readwrite", (s) => s.delete(key));
}

export async function all<T>(store: Store): Promise<T[]> {
  if (!(await available())) return [...memory[store].values()] as T[];
  return (await run(store, "readonly", (s) => s.getAll())) as T[];
}

/** FR-PW12: everything this device holds for the user. */
export async function wipe(): Promise<void> {
  for (const store of STORES) memory[store].clear();
  if (await available()) {
    for (const store of STORES) await run(store, "readwrite", (s) => s.clear());
  }
}
