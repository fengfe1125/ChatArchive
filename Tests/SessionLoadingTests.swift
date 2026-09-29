import Foundation

@MainActor final class FakeEngine: ArchiveEngine {
    var requests:[(String, CheckedContinuation<[String:Any], Error>)] = []
    func start() async throws {}
    func stop() {}
    func call(_ path:String,_ body:[String:Any]?) async throws -> [String:Any] {
        try await withCheckedThrowingContinuation { requests.append((path,$0)) }
    }
    func finish(_ index:Int,_ text:String) { requests[index].1.resume(returning:["items":[["role":"assistant","text":text]],"next_offset":NSNull()]) }
}
@main struct SessionLoadingTests {
    @MainActor static func main() async throws {
        let engine=FakeEngine()
        // preview mode prevents test selection from changing user defaults.
        let subject=ArchiveModel(engine:engine)
        func row(_ id:String)->ChatSession {
            ChatSession(id:id,source:"code",title:id,project:"test",last_at:nil,status:"new",valid_hash:true,content_available:true,visible_turns:1,review:nil,destination_thread_id:nil)
        }
        let first=Task { try await subject.openSession(row("A")) }
        while engine.requests.count<1 { await Task.yield() }
        let second=Task { try await subject.openSession(row("B")) }
        while engine.requests.count<2 { await Task.yield() }
        let third=Task { try await subject.openSession(row("A")) }
        while engine.requests.count<3 { await Task.yield() }
        engine.finish(2,"latest A");try await third.value
        engine.finish(0,"stale A");try await first.value
        engine.finish(1,"stale B");try await second.value
        precondition(subject.messages.map(\.text)==["latest A"], "Late A response overwrote or duplicated the current A selection")
        let failing=Task { try await subject.openSession(row("C")) }
        while engine.requests.count<4 { await Task.yield() }
        engine.requests[3].1.resume(throwing: URLError(.timedOut));try await failing.value
        precondition(subject.messageError != nil && subject.messageNext==0 && !subject.loadingMessages)
        let retry=Task { try await subject.moreMessages() }
        while engine.requests.count<5 { await Task.yield() }
        try await subject.moreMessages()
        precondition(engine.requests.count==5, "Duplicate pagination request")
        engine.finish(4,"retried C");try await retry.value
        precondition(subject.messages.map(\.text)==["retried C"] && subject.messageError==nil && !subject.loadingMessages)
        let jump=Task { try await subject.jumpToMessage(80) }
        while engine.requests.count<6 { await Task.yield() }
        precondition(engine.requests[5].0.contains("offset=80"))
        let newer=Task { try await subject.jumpToMessage(120) }
        while engine.requests.count<7 { await Task.yield() }
        engine.finish(6,"target 120");try await newer.value
        engine.finish(5,"stale target 80");try await jump.value
        precondition(subject.messages.first?.index==120 && subject.messages.first?.text=="target 120")
        let previous=Task {try await subject.earlierMessages()}
        while engine.requests.count<8{await Task.yield()}
        try await subject.earlierMessages()
        precondition(engine.requests.count==8,"Duplicate earlier-page request")
        precondition(engine.requests[7].0.contains("offset=116"))
        engine.requests[7].1.resume(returning:["items":(0..<4).map{["role":"assistant","text":"previous \($0)"]},"next_offset":120])
        try await previous.value
        precondition(subject.messages.map(\.index)==[116,117,118,119,120])
        precondition(subject.messages.last?.text=="target 120" && subject.messageNext==nil,"Prepending replaced current content or changed forward cursor")
        let stalePrevious=Task{try await subject.earlierMessages()}
        while engine.requests.count<9{await Task.yield()}
        let other=Task{try await subject.openSession(row("D"))}
        while engine.requests.count<10{await Task.yield()}
        engine.finish(9,"new D");try await other.value
        engine.finish(8,"stale history");try await stalePrevious.value
        precondition(subject.messages.map(\.text)==["new D"])
        print("PASS: rapid A → B → A ignores stale responses; failed pages retry; duplicate page requests suppressed; rapid navigation keeps latest target")
    }
}
