// swift-tools-version: 6.0
import PackageDescription
let package = Package(name: "ClaudeArchive", platforms: [.macOS(.v15)], products: [.executable(name: "ClaudeArchive", targets: ["ClaudeArchive"])], targets: [.executableTarget(name: "ClaudeArchive", path: "Sources", swiftSettings: [.swiftLanguageMode(.v5)])])
