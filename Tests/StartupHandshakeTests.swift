import Foundation

@main struct StartupHandshakeTests {
    static func main() throws {
        // Keep writer open: a short readiness frame must not wait for EOF or 4096 bytes.
        let short = Pipe()
        let frame = Data("{\"port\":1234,\"token\":\"test\"}\n".utf8)
        try short.fileHandleForWriting.write(contentsOf: frame)
        let started = ProcessInfo.processInfo.systemUptime
        let result = try readStartupLine(short.fileHandleForReading, timeout: 1)
        precondition(result == frame.dropLast())
        precondition(ProcessInfo.processInfo.systemUptime - started < 0.5)
        // A frame can be split across multiple pipe writes.
        let split = Pipe()
        try split.fileHandleForWriting.write(contentsOf: Data("{\"port\":".utf8))
        DispatchQueue.global().asyncAfter(deadline: .now() + 0.05) {
            try? split.fileHandleForWriting.write(contentsOf: Data("1234}\n".utf8))
        }
        let splitResult = try readStartupLine(split.fileHandleForReading, timeout: 1)
        precondition(splitResult == Data("{\"port\":1234}".utf8))
        let silent = Pipe()
        do { _ = try readStartupLine(silent.fileHandleForReading, timeout: 0.1); fatalError("expected timeout") }
        catch { precondition((error as NSError).code == 4) }
        let exited = Pipe()
        try exited.fileHandleForWriting.close()
        do { _ = try readStartupLine(exited.fileHandleForReading, timeout: 1); fatalError("expected EOF error") }
        catch { precondition((error as NSError).code == 2) }
        print("PASS: short open pipe, fragmented frame, timeout, early exit")
    }
}
