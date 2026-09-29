import Foundation
import Darwin

/// Read one newline-delimited readiness frame; the child keeps stdout open afterward.
/// Foundation's read(upToCount:) may wait to fill its buffer on macOS pipes.
func readStartupLine(_ handle: FileHandle, timeout: TimeInterval = 10) throws -> Data {
    let deadline = ProcessInfo.processInfo.systemUptime + timeout
    var received = Data()
    while ProcessInfo.processInfo.systemUptime < deadline {
        let remaining = deadline - ProcessInfo.processInfo.systemUptime
        var descriptor = pollfd(fd: handle.fileDescriptor, events: Int16(POLLIN), revents: 0)
        let result = Darwin.poll(&descriptor, 1, Int32(max(1, remaining * 1000)))
        if result < 0 {
            if errno == EINTR { continue }
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno))
        }
        if result == 0 { break }
        var buffer = [UInt8](repeating: 0, count: 1024)
        let count = Darwin.read(handle.fileDescriptor, &buffer, buffer.count)
        if count < 0 {
            if errno == EINTR { continue }
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno))
        }
        guard count > 0 else {
            throw NSError(domain: "Engine", code: 2, userInfo: [NSLocalizedDescriptionKey: "数据引擎在启动完成前退出，请重新检测。"])
        }
        received.append(contentsOf: buffer.prefix(count))
        if let newline = received.firstIndex(of: 10) { return Data(received[..<newline]) }
        guard received.count <= 65536 else {
            throw NSError(domain: "Engine", code: 3, userInfo: [NSLocalizedDescriptionKey: "数据引擎返回了无效的启动消息。"])
        }
    }
    throw NSError(domain: "Engine", code: 4, userInfo: [NSLocalizedDescriptionKey: "数据引擎启动超过 10 秒，请点击重新检测重试。"])
}
