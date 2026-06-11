# ios-native lens

## key
ios-native

## fire-when
Swift source present (`*.swift`) AND an Xcode project / SwiftPM manifest detected (`*.xcodeproj`, `*.xcworkspace`, `Package.swift`, `*.pbxproj`). Also fires on iOS config files: `Info.plist` (ATS / `NSAppTransportSecurity`), `PrivacyInfo.xcprivacy`, `*.entitlements`. Content markers: `import SwiftUI`, `import UIKit`, `import CoreData`, `import CryptoKit`, `@State`, `@StateObject`, `@MainActor`, `kSecAttrAccessible`.

## checklist
Audit this iOS / Swift file for iOS-specific defects. Preserve these exact categories and severities (MUST-FIX = blocking, SHOULD-FIX = important, NIT = minor). Confidence HIGH / MEDIUM / LOW, with LOW phrased as a question. Layer is `structural`.

- **state-ownership:** `@State` is reserved for view-local state only; cross-view / shared state must use `@StateObject` / `@ObservedObject` / `@Binding`. Misuse → SHOULD-FIX.
- **core-data-threading:** Core Data mutations on a background context must use `perform` / `performAndWait`; reads must cross the correct context, and UI reads must be on the main (view) context. Violations → MUST-FIX.
- **keychain:** `kSecAttrAccessible` must be set to a sane class (`AfterFirstUnlockThisDeviceOnly` or `WhenUnlockedThisDeviceOnly`). Any `Always*` accessibility (e.g. `kSecAttrAccessibleAlways`) → MUST-FIX.
- **crypto:** No hardcoded crypto keys, no MD5 / SHA1 used for security, no ECB mode, no hand-rolled crypto (CryptoKit / CommonCrypto misuse). → MUST-FIX.
- **ats:** `NSAppTransportSecurity.NSAllowsArbitraryLoads = true` (in Info.plist) → MUST-FIX.
- **privacy-manifest:** Use of an iOS-17+ "required reason" API without listing its reason in `PrivacyInfo.xcprivacy` → SHOULD-FIX.
- **main-thread:** Network / disk / Core Data work performed on `MainActor` (main thread) without offloading via `await Task.detached` (or equivalent) → SHOULD-FIX.
- **sendable:** Types that cross actor boundaries lacking `Sendable` / `@unchecked Sendable` conformance → SHOULD-FIX.

Hard rule (no exceptions): hardcoded crypto keys, `Always*` Keychain accessibility, and ATS arbitrary loads are always MUST-FIX. For each finding give Evidence as `{file}:{line} — {snippet}` and a specific Recommendation.
