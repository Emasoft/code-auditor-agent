// Background script (Firefox WebExtensions API).

browser.runtime.onMessage.addListener((message, sender) => {
  if (message && message.type === "ping") {
    return Promise.resolve({ ok: true, pong: Date.now() });
  }
  return Promise.resolve({ ok: false });
});

browser.runtime.onInstalled.addListener(() => {
  browser.storage.local.set({ installedAt: Date.now() });
});
