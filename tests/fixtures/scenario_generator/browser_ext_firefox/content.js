// Content script (Firefox WebExtensions API).

browser.runtime.onMessage.addListener((message, sender) => {
  if (message && message.type === "getTitle") {
    return Promise.resolve({ title: document.title });
  }
  return Promise.resolve(null);
});
