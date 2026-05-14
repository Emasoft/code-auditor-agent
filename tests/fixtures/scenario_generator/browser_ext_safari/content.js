// Safari content script — communicates with SafariExtensionHandler via
// safari.extension.dispatchMessage.

safari.self.addEventListener("message", function (event) {
  if (event.name === "ping") {
    safari.extension.dispatchMessage("pong", { ts: Date.now() });
  }
});

document.addEventListener("DOMContentLoaded", function () {
  safari.extension.dispatchMessage("page-ready", { title: document.title });
});
