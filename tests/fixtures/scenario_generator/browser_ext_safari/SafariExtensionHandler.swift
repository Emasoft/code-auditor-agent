// Safari App Extension principal class.
//
// Subclass of SFSafariExtensionHandler — overrides the lifecycle entry
// points the host invokes when toolbar/content events occur.

import SafariServices

class SafariExtensionHandler: SFSafariExtensionHandler {
    override func messageReceived(withName messageName: String, from page: SFSafariPage, userInfo: [String : Any]?) {
        // Route content-script messages to the appropriate handler.
        page.getPropertiesWithCompletionHandler { _ in }
    }

    override func toolbarItemClicked(in window: SFSafariWindow) {
        // User clicked the extension's toolbar item.
        window.getActiveTab { _ in }
    }

    override func validateToolbarItem(in window: SFSafariWindow, validationHandler: @escaping ((Bool, String) -> Void)) {
        validationHandler(true, "")
    }
}
