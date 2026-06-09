type BrowserStorageName = "localStorage" | "sessionStorage";

function getBrowserStorage(name: BrowserStorageName): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return window[name] ?? null;
  } catch {
    return null;
  }
}

function getStorageItem(name: BrowserStorageName, key: string): string | null {
  const storage = getBrowserStorage(name);
  if (!storage) return null;
  try {
    return storage.getItem(key);
  } catch {
    return null;
  }
}

function setStorageItem(name: BrowserStorageName, key: string, value: string): boolean {
  const storage = getBrowserStorage(name);
  if (!storage) return false;
  try {
    storage.setItem(key, value);
    return true;
  } catch {
    return false;
  }
}

function removeStorageItem(name: BrowserStorageName, key: string): boolean {
  const storage = getBrowserStorage(name);
  if (!storage) return false;
  try {
    storage.removeItem(key);
    return true;
  } catch {
    return false;
  }
}

export function safeLocalStorageGet(key: string): string | null {
  return getStorageItem("localStorage", key);
}

export function safeLocalStorageSet(key: string, value: string): boolean {
  return setStorageItem("localStorage", key, value);
}

export function safeLocalStorageRemove(key: string): boolean {
  return removeStorageItem("localStorage", key);
}

export function safeSessionStorageGet(key: string): string | null {
  return getStorageItem("sessionStorage", key);
}

export function safeSessionStorageSet(key: string, value: string): boolean {
  return setStorageItem("sessionStorage", key, value);
}

export function safeSessionStorageRemove(key: string): boolean {
  return removeStorageItem("sessionStorage", key);
}
