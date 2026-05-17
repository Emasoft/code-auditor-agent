import Foundation

class NetworkManager {
    static let shared = NetworkManager()

    // Strong references to closures — they capture self → retain cycle.
    var completionHandlers: [String: (Data?) -> Void] = [:]

    func fetch(_ url: URL, completion: @escaping (Data?) -> Void) {
        completionHandlers[url.absoluteString] = completion
        // Plain HTTP allowed because ATS exception is set in Info.plist:
        // NSAllowsArbitraryLoads = true
        URLSession.shared.dataTask(with: url) { data, _, _ in
            completion(data)
        }.resume()
    }
}
