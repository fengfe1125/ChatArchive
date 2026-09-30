import Foundation

@MainActor final class ImportEngine:ArchiveEngine {
    var requests:[(String,[String:Any]?)] = []
    var pending:CheckedContinuation<[String:Any],Error>?
    var pause=false
    var jobResult:[String:Any]=["status":"completed","results":[],"errors":[]]
    func start() async throws {}
    func stop() {}
    func call(_ path:String,_ body:[String:Any]?) async throws->[String:Any] {
        requests.append((path,body))
        if path == "/native/import" {
            if pause{return try await withCheckedThrowingContinuation{pending=$0}}
            return ["job_id":"job"]
        }
        if path.hasPrefix("/api/job"){return jobResult}
        if path.hasPrefix("/native/library"){return ["items":[],"total":0]}
        return [:]
    }
}

@main struct ImportDestinationTests {
    @MainActor static func main() async throws {
        let engine=ImportEngine(),subject=ArchiveModel(engine:ImportEngine())
        let model=ArchiveModel(engine:engine)
        let old:[String:Any]=["id":"account:1","source":"account","title":"History","project":"",
                             "status":"present","valid_hash":true,"visible_turns":1,"destination_thread_id":"codex-id"]
        let legacy=try decode(ChatSession.self,old)
        precondition(legacy.imports==nil && legacy.statusName(for:.codex)=="已在 Codex")
        precondition(legacy.statusName(for:.claudeCode)=="未导入")
        var row=old;row["imports"]=["claude_chat":["status":"prepared"],"claude_code":["status":"present","session_id":"code-id"]]
        let updated=try decode(ChatSession.self,row)
        precondition(updated.statusName(for:.claudeChat)=="已准备资料" && updated.statusName(for:.claudeCode)=="已在 Claude Code")
        let sid="11111111-2222-4333-8444-555555555555"
        var restored:[String:Any]=["destination":"claude_code","status":"completed","session_id":sid,"session_path":"/test/project with spaces/\(sid).jsonl"]
        let desktopURL=claudeDesktopResumeURL(restored)!
        precondition(desktopURL.scheme=="claude" && desktopURL.host=="resume")
        precondition(URLComponents(url:desktopURL,resolvingAgainstBaseURL:false)?.queryItems==[URLQueryItem(name:"session",value:sid)])
        restored["status"]="existing";precondition(claudeDesktopResumeURL(restored)==desktopURL)
        restored["status"]="needs_review";precondition(claudeDesktopResumeURL(restored)==nil)
        restored["status"]="completed";restored["session_id"]="bad&session=other";precondition(claudeDesktopResumeURL(restored)==nil)
        restored["session_id"]=sid;restored["destination"]="codex";precondition(claudeDesktopResumeURL(restored)==nil)
        restored["destination"]="claude_code";restored.removeValue(forKey:"session_path");precondition(claudeDesktopResumeURL(restored)==nil)
        restored["session_path"]="/test/\(sid).jsonl";restored["cwd"]="/test/project ' $(literal)";restored["executable"]="/test/bin with spaces/claude"
        precondition(claudeDesktopResumeCommand(restored)=="cd '/test/project '\\'' $(literal)' && '/test/bin with spaces/claude' --desktop --resume '\(sid)'")
        let desktopEngine=ImportEngine(),desktopModel=ArchiveModel(engine:ImportEngine())
        let autoModel=ArchiveModel(engine:desktopEngine)
        var opened:[URL]=[];autoModel.openDesktopURL={opened.append($0);return true}
        desktopEngine.jobResult=["status":"completed","results":[restored],"errors":[]]
        autoModel.importDestination = .claudeCode;autoModel.openClaudeDesktopAfterImport=true
        autoModel.beginImport(["code:1"]);try await autoModel.submitImport();precondition(opened==[desktopURL])
        autoModel.openClaudeDesktopAfterImport=false;try await autoModel.submitImport();precondition(opened.count==1)
        autoModel.openClaudeDesktopAfterImport=true;autoModel.beginImport(["code:1","code:2"]);try await autoModel.submitImport();precondition(opened.count==1)
        autoModel.beginImport(["code:1"]);autoModel.importDestination = .claudeChat;try await autoModel.submitImport();precondition(opened.count==1)
        autoModel.importDestination = .claudeCode;autoModel.openDesktopURL={_ in false};try await autoModel.submitImport();precondition(autoModel.error?.contains("会话已创建")==true)
        desktopModel.openDesktopURL={_ in preconditionFailure("unconfirmed session must not open")}
        desktopModel.importDestination = .claudeCode;desktopModel.beginImport(["code:1"]);try await desktopModel.submitImport()
        model.importDestination = .codex
        model.readingBranches["account:1"]="branch-1"
        model.beginImport(["account:1"])
        precondition(model.pendingBranches==["account:1":"branch-1"])
        model.importDestination = .claudeChat
        precondition(model.importBody["destination"] as? String == "claude_chat")
        try await model.submitImport()
        precondition(engine.requests[0].1?["branches"] as? [String:String] == ["account:1":"branch-1"])
        precondition(!model.confirmImport && !model.taskRunning)
        model.beginImport(["account:1","code:2"])
        precondition(model.pendingBranches.isEmpty && model.pendingImports.count==2)
        model.restoreImport(["ids":["account:1"],"branches":["account:1":"old-branch"],"destination":"claude_code"])
        precondition(model.importDestination == .claudeCode && model.pendingBranches["account:1"]=="old-branch")
        model.restoreImport(["ids":["code:2"]])
        precondition(model.importDestination == .codex && model.pendingBranches.isEmpty)
        model.filterDestination = .claudeChat;model.statusFilter="prepared"
        try await model.loadSessions()
        precondition(engine.requests.last!.0.contains("destination=claude%5Fchat") || engine.requests.last!.0.contains("destination=claude_chat"))
        engine.pause=true
        let first=Task{try await model.submitImport()}
        while engine.pending==nil{await Task.yield()}
        let count=engine.requests.count
        do{try await model.submitImport();preconditionFailure("duplicate job was accepted")}catch{}
        precondition(engine.requests.count==count)
        model.beginImport(["unexpected"])
        precondition(model.pendingImports==["code:2"])
        engine.pending?.resume(returning:["job_id":"job"])
        try await first.value
        subject.beginImport(["A"],branch:"all")
        precondition(subject.pendingBranches==["A":"all"])
        print("PASS: destination selection, legacy decoding, branch capture, batch reset, target filtering, job recovery and duplicate-submit protection")
    }
}
