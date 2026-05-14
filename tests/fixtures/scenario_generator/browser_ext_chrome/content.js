// Content script injected into matching pages.

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  // Forward DOM-snapshot requests from the popup back to the page.
  if (message && message.type === "getTitle") {
    sendResponse({ title: document.title });
    return true;
  }
  return false;
});

document.addEventListener("DOMContentLoaded", () => {
  chrome.runtime.sendMessage({ type: "page-ready", url: location.href });
});
