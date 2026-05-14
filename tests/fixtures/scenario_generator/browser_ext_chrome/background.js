// Background service worker entry for the extension.
// Handles messages from content scripts and the popup.

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  // Dispatch on message type and reply via sendResponse.
  if (message && message.type === "ping") {
    sendResponse({ ok: true, pong: Date.now() });
    return true;
  }
  return false;
});

chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.local.set({ installedAt: Date.now() });
});
