import SwiftUI
import AppKit
import UniformTypeIdentifiers

struct ChatSession: Identifiable, Decodable, Hashable {
    let id: String; let source: String; let title: String; let project: String
    let last_at: String?; let status: String; let valid_hash: Bool
    let content_available: Bool?; let visible_turns: Int; let review: String?
    let destination_thread_id: String?
    var readable: Bool { valid_hash && content_available != false }
    var statusName: String { ["new":"未导入","present":"已在 Codex","archived":"已归档","missing":"目标会话缺失","changed":"内容有更新","needs_review":"需核对"][status] ?? status }
}
struct Message: Decodable, Identifiable {
    var id: String { "\(index)" }; var index = 0
    let role: String; let text: String; let media: [Media]?
    let continuation: Bool?; let plain: Bool?; let segmented: Bool?
    let message_id:String?; let versions:[MessageVersion]?; let version_index:Int?
    enum CodingKeys: String, CodingKey { case role,text,media,continuation,plain,segmented,message_id,versions,version_index }
}
struct MessageVersion:Decodable,Identifiable {let id:String;let title:String;let message_id:String}
struct Media: Decodable { let name: String?; let text: String?; let type:String? }
struct CodeItem: Decodable, Identifiable { let id: String; let title: String; let origin: String; let completeness: String; let line: Int? }
struct SourceItem: Identifiable { var id: String { path }; let path: String; let count: Int; let bytes: Int64; let modified: Double; var kind = "code"; var zipCount = 0; var selected = true
    var summary:String { kind == "account" ? "Chat · 账号聊天导出 · \(zipCount) 个 ZIP" : (kind == "mixed" ? "Chat + Code · \(count) 条 Code · \(zipCount) 个 ZIP" : "Code · \(count) 条会话") } }
struct Project: Decodable, Hashable { let source: String; let path: String; let count: Int }
struct RawRecord: Decodable, Identifiable { var id: Int { line }; let line: Int; let type: String; let summary: String }
func decode<T: Decodable>(_ type: T.Type, _ value: Any) throws -> T { try JSONDecoder().decode(type, from: JSONSerialization.data(withJSONObject:value)) }
func bytes(_ value: Int64) -> String { ByteCountFormatter.string(fromByteCount:value,countStyle:.file) }
func folderName(_ path: String) -> String { URL(fileURLWithPath:path).lastPathComponent }
func chooseFolder(_ title: String) -> URL? { let p=NSOpenPanel();p.title=title;p.canChooseDirectories=true;p.canChooseFiles=false;p.canCreateDirectories=true;return p.runModal() == .OK ? p.url : nil }
func chooseFiles(_ title: String, zip: Bool=false) -> [URL] { let p=NSOpenPanel();p.title=title;p.canChooseDirectories=false;p.canChooseFiles=true;p.allowsMultipleSelection=zip;if zip {p.allowedContentTypes=[.zip]};return p.runModal() == .OK ? p.urls : [] }
func copyText(_ value: String) { NSPasteboard.general.clearContents();NSPasteboard.general.setString(value,forType:.string) }

@MainActor protocol ArchiveEngine: AnyObject {
    func start() async throws
    func call(_ path: String, _ body: [String:Any]?) async throws -> [String:Any]
    func stop()
}
extension ArchiveEngine {
    func call(_ path:String) async throws -> [String:Any] { try await call(path,nil) }
}
@MainActor final class Engine: ObservableObject, ArchiveEngine {
    private var process: Process?; private var input: Pipe?
    private var base=""; private var token=""
    let session = URLSession(configuration: .ephemeral)
    func start() async throws {
        if process?.isRunning == true && !base.isEmpty { return }
        guard let resources=Bundle.main.resourceURL else {throw CocoaError(.fileNoSuchFile)}
        let p=Process(), output=Pipe(), stdin=Pipe(), error=Pipe()
        p.executableURL=resources.appendingPathComponent("Python/bin/python3.12")
        p.arguments=["-u",resources.appendingPathComponent("Engine/native_server.py").path]
        var env=ProcessInfo.processInfo.environment
        env["PYTHONHOME"]=resources.appendingPathComponent("Python").path;env["PYTHONDONTWRITEBYTECODE"]="1"
        env["PATH"]=[NSHomeDirectory()+"/.npm-global/bin",NSHomeDirectory()+"/.local/bin","/opt/homebrew/bin","/usr/local/bin","/usr/bin","/bin"].joined(separator:":")
        p.environment=env;p.standardOutput=output;p.standardInput=stdin;p.standardError=error
        error.fileHandleForReading.readabilityHandler={ handle in _=handle.availableData }
        try p.run();process=p;input=stdin
        let data: Data
        do { data = try await Task.detached { try readStartupLine(output.fileHandleForReading) }.value }
        catch { stop(); throw error }
        guard let ready=try JSONSerialization.jsonObject(with:data) as? [String:Any],let port=ready["port"] as? Int,let key=ready["token"] as? String else {throw NSError(domain:"Engine",code:1,userInfo:[NSLocalizedDescriptionKey:"数据引擎启动失败"])}
        base="http://127.0.0.1:\(port)";token=key
    }
    func call(_ path: String, _ body: [String:Any]?=nil) async throws -> [String:Any] {
        guard let url=URL(string:base+path) else {throw URLError(.badURL)}
        var request=URLRequest(url:url);request.timeoutInterval=300
        request.setValue("import_token=\(token)",forHTTPHeaderField:"Cookie")
        if let body {request.httpMethod="POST";request.httpBody=try JSONSerialization.data(withJSONObject:body);request.setValue("application/json",forHTTPHeaderField:"Content-Type");request.setValue(token,forHTTPHeaderField:"X-CSRF-Token");request.setValue(base,forHTTPHeaderField:"Origin")}
        let (data,response)=try await session.data(for:request)
        let object=try JSONSerialization.jsonObject(with:data) as? [String:Any] ?? [:]
        if (response as? HTTPURLResponse)?.statusCode != 200 {throw NSError(domain:"Archive",code:1,userInfo:[NSLocalizedDescriptionKey:object["error"] as? String ?? "请求失败"])}
        return object
    }
    func stop() {try? input?.fileHandleForWriting.close();if let process,process.isRunning {process.terminate()};process=nil;base="";token=""}
}

@MainActor final class ArchiveModel: ObservableObject {
    static let shared=ArchiveModel()
    let engine:any ArchiveEngine
    init(engine:(any ArchiveEngine)?=nil) { self.engine=engine ?? Engine() }
    var previewPath:String? {let a=ProcessInfo.processInfo.arguments;guard let i=a.firstIndex(of:"--preview-archive"),i+1<a.count else{return nil};return a[i+1]}
    @Published var detecting=false; @Published var loading=true; @Published var busy=false; @Published var error: String?
    @Published var downloading=false; @Published var downloadMessage=""; @Published var downloadRoot="";
    @Published var scanningSources=false; @Published var sourceScanMessage=""
    @Published var codex:[String:String]=[:]; @Published var sources:[SourceItem]=[]
    @Published var destination=""; @Published var freeSpace:Int64=0
    @Published var setup=true; @Published var step=0; @Published var archivePath=""
    @Published var offline=false; @Published var sourceChanged=false
    @Published var backup:[String:Any]=[:]; @Published var backupID=""
    @Published var surface="account"; @Published var projects:[Project]=[]
    @Published var sessions:[ChatSession]=[]; @Published var selection=Set<String>()
    @Published var active:ChatSession?; @Published var messages:[Message]=[]
    @Published var loadingMessages=false; @Published var messageError:String?
    @Published var loadingSessions=false
    private var selectionGeneration=0
    private var selectionTask:Task<Void,Never>?
    @Published var codeItems:[CodeItem]=[]; @Published var raw:[RawRecord]=[]
    @Published var rawText:[Int:String]=[:]; @Published var rawNext:[Int:Int]=[:]
    @Published var inspector=false; @Published var detailMode=0
    @Published var selectedCode:String?; @Published var codeContent=""; @Published var before:String?; @Published var after:String?
    @Published var codeMetadata=""; @Published var query=""; @Published var project=""
    @Published var statusFilter=""; @Published var reviewFilter=""; @Published var codeFilter=""
    @Published var dateFrom=""; @Published var dateTo=""
    @Published var libraryScope="chats"
    @Published var page=1; @Published var total=0; @Published var counts:[String:Int]=[:]
    @Published var messageNext:Int?; @Published var rawPageNext:Int?
    @Published var task:[String:Any]=[:]; @Published var taskVisible=false
    @Published var pendingImports:[String]=[]; @Published var confirmImport=false
    @Published var stage:[String:Any]=[:]; @Published var showStage=false
    @Published var restoredJobs:[[String:Any]]=[]
    var scrollIDs:[String:String]=[:]
    var lastBySurface:[String:String]=[:]; var requestSerial=0
    var sourcePaths:[String] { sources.filter(\.selected).map(\.path) }
    var taskRunning:Bool {task["status"] as? String == "running" || backup["status"] as? String == "running"}
    func perform(_ work: @escaping @MainActor () async throws -> Void) {Task {do {try await work()} catch {self.error=error.localizedDescription}}}
    func bootstrap() async {
        do {
            try await engine.start()
            loading=false
            // Environment checks are useful, but must never block the archive UI.
            perform { try await self.detect() }
            scrollIDs=UserDefaults.standard.dictionary(forKey:"scrollPositions") as? [String:String] ?? [:]
            lastBySurface=UserDefaults.standard.dictionary(forKey:"lastBySurface") as? [String:String] ?? [:]
            let previous=previewPath ?? UserDefaults.standard.string(forKey:"archivePath") ?? ""
            if !previous.isEmpty { try await open(previous) }
        } catch { self.error=error.localizedDescription }
        loading=false
    }
    func detect(_ path: String="") async throws {
        guard !detecting else { return }
        detecting=true
        defer { detecting=false }
        try await engine.start()
        let result=try await engine.call("/native/detect",["codex":path.isEmpty ? UserDefaults.standard.string(forKey:"codexPath") ?? "" : path])
        codex=result["codex"] as? [String:String] ?? [:]
        if !path.isEmpty {UserDefaults.standard.set(path,forKey:"codexPath")}
        for row in result["sources"] as? [[String:Any]] ?? [] {addSourceRow(row)}
    }
    func addSourceRow(_ row:[String:Any]) {guard let path=row["path"] as? String,!sources.contains(where:{$0.path==path}) else{return};sources.append(SourceItem(path:path,count:row["sessions"] as? Int ?? 0,bytes:(row["bytes"] as? NSNumber)?.int64Value ?? 0,modified:row["modified"] as? Double ?? 0,kind:row["kind"] as? String ?? "code",zipCount:row["zip_count"] as? Int ?? 0))}
    func addSource(_ url:URL) {perform {
        self.scanningSources=true
        defer {self.scanningSources=false}
        let result=try await self.engine.call("/native/discover",["path":url.path])
        for row in result["sources"] as? [[String:Any]] ?? [] {self.addSourceRow(row)}
        self.sourceScanMessage=([result["message"] as? String ?? ""]+(result["warnings"] as? [String] ?? [])).joined(separator:"\n")
    }}
    func downloadExport(resume:Bool=false) {
        guard !downloading else{return}
        let manifest:String;let destination:String
        if resume {
            guard let folder=chooseFolder("选择上次下载的 Claude账号导出 文件夹") else{return}
            destination=folder.path;manifest=folder.appendingPathComponent("manifest.json").path
        } else {
            guard let file=chooseFiles("选择 Claude 官方导出的 manifest JSON 清单").first,
                  let folder=chooseFolder("选择 ZIP 下载保存位置") else{return}
            manifest=file.path;destination=folder.path
        }
        perform {
            self.downloading=true
            defer {self.downloading=false}
            let result=try await self.engine.call("/native/download/start",["manifest":manifest,"destination":destination,"resume":resume])
            let id=result["id"] as? String ?? ""
            self.downloadRoot=result["root"] as? String ?? ""
            while true {
                let state=try await self.engine.call("/native/download?id=\(id)")
                self.downloadMessage=state["message"] as? String ?? "准备下载…"
                if let files=state["files"] as? [[String:Any]],let current=files.last {
                    self.downloadMessage += "\n"+(current["filename"] as? String ?? "")+" · "+bytes((current["bytes"] as? NSNumber)?.int64Value ?? 0)
                }
                if state["status"] as? String != "running" {
                    if state["status"] as? String == "completed" {self.addSource(URL(fileURLWithPath:self.downloadRoot))}
                    break
                }
                try await Task.sleep(for:.seconds(1))
            }
        }
    }
    func useCodexDestination() async throws {
        let value=try await engine.call("/native/destination/default",["sources":sourcePaths])
        destination=value["path"] as? String ?? "";freeSpace=(value["free"] as? NSNumber)?.int64Value ?? 0
    }
    func nextSetupStep() {
        if step==1 {perform {if self.destination.isEmpty {try await self.useCodexDestination()};self.step=2}}
        else {step+=1}
    }
    func pickDestination() {guard let url=chooseFolder("选择聊天备份保存位置") else{return};perform {let value=try await self.engine.call("/native/destination",["path":url.path,"sources":self.sourcePaths]);self.destination=url.path;self.freeSpace=(value["free"] as? NSNumber)?.int64Value ?? 0}}
    func startBackup(resume:String?=nil) async throws {
        var body:[String:Any]=["sources":sourcePaths,"destination":destination];if let resume {body=["resume":resume]}
        let value=try await engine.call("/native/backup/start",body);backupID=value["id"] as? String ?? "";UserDefaults.standard.set(value["root"],forKey:"pendingBackup");step=3
        repeat {backup=try await engine.call("/native/backup?id=\(escape(backupID))");if backup["status"] as? String != "running" && backup["status"] as? String != "pending" {break};try await Task.sleep(for:.milliseconds(350))} while true
        if backup["status"] as? String == "completed" {UserDefaults.standard.removeObject(forKey:"pendingBackup")}
    }
    func open(_ path:String,workspace:String?=nil,account:String?=nil) async throws {
        guard FileManager.default.fileExists(atPath:path) else{archivePath=path;offline=true;setup=false;return}
        var body:[String:Any]=["path":path];if let workspace {body["workspace"]=workspace};if let account {body["account"]=account}
        busy=true;defer{busy=false}
        let value=try await engine.call("/native/open",body);archivePath=value["root"] as? String ?? path
        if previewPath==nil{UserDefaults.standard.set(archivePath,forKey:"archivePath")};restoredJobs=value["jobs"] as? [[String:Any]] ?? [];sourceChanged=value["source_changes"] as? Bool ?? false
        setup=false;offline=false;active=nil;selection=[];page=1;project="";query=""
        try await loadInfo();try await loadSessions()
        if let id=UserDefaults.standard.string(forKey:"active-"+archivePath) {let row=try? await engine.call("/native/session?id=\(escape(id))");if let row,let session=try? decode(ChatSession.self,row){surface=session.source;try await openSession(session)}}
    }
    func closeArchive() {
        guard !taskRunning else{error="请等待当前任务结束";return}
        if previewPath==nil{UserDefaults.standard.removeObject(forKey:"archivePath")}
        selectionGeneration+=1;selectionTask?.cancel();loadingMessages=false
        archivePath="";active=nil;sessions=[];messages=[];selection=[];setup=true;offline=false;step=0
    }
    func chooseArchive() {
        guard !taskRunning else{error="请等待任务结束后切换档案";return}
        guard let source=chooseFolder("选择已有档案或 Claude Code 备份") else{return}
        if FileManager.default.fileExists(atPath:source.appendingPathComponent("archive.json").path) {perform{try await self.open(source.path)}}
        else {guard let work=chooseFolder("选择索引、整理状态和交接资料的保存位置") else{return};let account=sources.first(where:{$0.path.hasSuffix("conversations-000.zip")}).map{URL(fileURLWithPath:$0.path).deletingLastPathComponent().path};perform{try await self.open(source.path,workspace:work.path,account:account)}}
    }
    func loadInfo() async throws {let info=try await engine.call("/api/archive/info");projects=try decode([Project].self,info["projects"] ?? []);counts=["account":info["account"] as? Int ?? 0,"code":info["code"] as? Int ?? 0]}
    func escape(_ value:String)->String {value.addingPercentEncoding(withAllowedCharacters:CharacterSet.alphanumerics) ?? ""}
    func loadSessions(append:Bool=false) async throws {
        requestSerial+=1;let serial=requestSerial
        loadingSessions=true
        defer {if serial==requestSerial {loadingSessions=false}}
        let values=["source":query.isEmpty ? surface : "","project":query.isEmpty ? project : "","query":query,"status":statusFilter,"review":reviewFilter,"code":codeFilter,"from":dateFrom,"to":dateTo,"page":String(page),"scope":libraryScope]
        let data=try await engine.call("/native/library?"+values.map{"\($0.key)=\(escape($0.value))"}.joined(separator:"&"))
        guard serial==requestSerial else{return};let rows=try decode([ChatSession].self,data["items"] ?? []);sessions=append ? sessions+rows : rows;total=data["total"] as? Int ?? 0
    }
    func switchSurface() {
        selectionGeneration+=1;let generation=selectionGeneration;let target=surface
        selectionTask?.cancel();loadingMessages=false;messageError=nil
        page=1;project="";query="";active=nil;messages=[];sessions=[]
        perform {
            try await self.loadSessions()
            guard self.surface==target,self.selectionGeneration==generation,self.active==nil else{return}
            if let id=self.lastBySurface[target],let row=try? await self.engine.call("/native/session?id=\(self.escape(id))") {
                guard self.surface==target,self.selectionGeneration==generation,self.active==nil else{return}
                try await self.openSession(decode(ChatSession.self,row))
            }
        }
    }
    func selectSession(_ row:ChatSession) {
        guard active?.id != row.id else{return}
        selectionTask?.cancel()
        selectionTask=Task {do {try await openSession(row)} catch is CancellationError {} catch {self.error=error.localizedDescription}}
    }
    func openSession(_ row:ChatSession) async throws {
        selectionGeneration+=1;let generation=selectionGeneration
        loadingMessages=false;messageError=nil;inspector=false
        active=row;surface=row.source;lastBySurface[row.source]=row.id;if previewPath==nil{UserDefaults.standard.set(row.id,forKey:"active-"+archivePath);UserDefaults.standard.set(lastBySurface,forKey:"lastBySurface")}
        messages=[];codeItems=[];raw=[];rawText=[:];rawNext=[:];codeContent="";codeMetadata="";before=nil;after=nil;selectedCode=nil;messageNext=0;rawPageNext=0
        if row.source == "code" {try await moreMessages()}
        guard generation==selectionGeneration,!Task.isCancelled else{return}
    }
    func moreMessages() async throws {
        guard !loadingMessages,let id=active?.id,let offset=messageNext else{return}
        let generation=selectionGeneration
        loadingMessages=true;messageError=nil
        defer {if generation==selectionGeneration {loadingMessages=false}}
        do {
            let data=try await engine.call("/native/messages?id=\(escape(id))&offset=\(offset)")
            guard generation==selectionGeneration,!Task.isCancelled else{return}
            var items=try decode([Message].self,data["items"] ?? [])
            for i in items.indices{items[i].index=offset+i}
            messages+=items;messageNext=data["next_offset"] as? Int
        } catch {
            guard generation==selectionGeneration,!Task.isCancelled else{return}
            messageError=error.localizedDescription
        }
    }
    func earlierMessages() async throws {
        guard !loadingMessages,let id=active?.id,let first=messages.first?.index,first>0 else{return}
        let generation=selectionGeneration;let offset=max(0,first-4)
        loadingMessages=true;messageError=nil
        defer{if generation==selectionGeneration{loadingMessages=false}}
        do{
            let data=try await engine.call("/native/messages?id=\(escape(id))&offset=\(offset)")
            guard generation==selectionGeneration,!Task.isCancelled else{return}
            var items=try decode([Message].self,data["items"] ?? [])
            for i in items.indices{items[i].index=offset+i}
            messages=items.filter{$0.index<first}+messages
        }catch{if generation==selectionGeneration && !Task.isCancelled{messageError=error.localizedDescription}}
    }
    func jumpToMessage(_ offset:Int) async throws {
        guard let id=active?.id else{return}
        selectionGeneration+=1;let generation=selectionGeneration
        loadingMessages=true;messageError=nil
        defer{if generation==selectionGeneration{loadingMessages=false}}
        do{
            let data=try await engine.call("/native/messages?id=\(escape(id))&offset=\(offset)")
            guard generation==selectionGeneration,!Task.isCancelled else{return}
            var items=try decode([Message].self,data["items"] ?? [])
            for i in items.indices{items[i].index=offset+i}
            messages=items;messageNext=data["next_offset"] as? Int
        }catch{if generation==selectionGeneration{messageError=error.localizedDescription}}
    }
    func loadDetails() async throws {guard let id=active?.id else{return};if detailMode==0{let data=try await engine.call("/api/archive/code?id=\(escape(id))");guard active?.id==id else{return};codeItems=try decode([CodeItem].self,data["items"] ?? [])}else if raw.isEmpty{try await moreRaw()}}
    func selectCode(_ item:CodeItem) async throws {guard let id=active?.id else{return};selectedCode=item.id;let value=try await engine.call("/api/archive/code/content?id=\(escape(id))&item=\(escape(item.id))");guard active?.id==id,selectedCode==item.id else{return};codeContent=value["content"] as? String ?? "";before=value["before"] as? String;after=value["after"] as? String;codeMetadata="\(item.title)\n\(item.origin) · \(item.completeness) · 源记录 \(item.line.map(String.init) ?? "—")"}
    func moreRaw() async throws {guard let id=active?.id,let offset=rawPageNext else{return};let value=try await engine.call("/api/archive/raw?id=\(escape(id))&offset=\(offset)");guard active?.id==id else{return};raw+=try decode([RawRecord].self,value["items"] ?? []);rawPageNext=value["next_offset"] as? Int}
    func expandRaw(_ line:Int) async throws {guard let id=active?.id else{return};let offset=rawNext[line] ?? 0;if rawText[line] != nil && rawNext[line]==nil{return};let value=try await engine.call("/api/archive/raw/content?id=\(escape(id))&line=\(line)&offset=\(offset)");guard active?.id==id else{return};rawText[line,default:""]+=value["content"] as? String ?? "";rawNext[line]=value["next_offset"] as? Int}
    func review(_ value:String) async throws {guard let id=active?.id else{return};_=try await engine.call("/api/archive/review",["id":id,"review":value]);active=try decode(ChatSession.self,await engine.call("/native/session?id=\(escape(id))"));try await loadSessions()}
    func export(ids:[String]?,mode:String) {guard let dest=chooseFolder("选择 Markdown 导出位置") else{return};perform {var body:[String:Any]=["mode":mode,"destination":dest.path];body["ids"]=ids as Any? ?? NSNull();try await self.job("/native/export",body)}}
    func job(_ path:String,_ body:[String:Any]) async throws {guard !taskRunning else{throw NSError(domain:"Task",code:1,userInfo:[NSLocalizedDescriptionKey:"已有任务正在运行"])};let result=try await engine.call(path,body);let id=result["job_id"] as? String ?? "";taskVisible=true;repeat{task=try await engine.call("/api/job?id=\(id)");if task["status"] as? String != "running" {break};try await Task.sleep(for:.seconds(1))}while true;try await loadSessions();if let active{let value=try await engine.call("/native/session?id=\(escape(active.id))");self.active=try decode(ChatSession.self,value)}}
    func stageSelection(_ ids:[String]) async throws {guard ids.allSatisfy({$0.hasPrefix("code:")}) else{throw NSError(domain:"Stage",code:1,userInfo:[NSLocalizedDescriptionKey:"官方导入仅支持 Claude Code"])};let value=try await engine.call("/api/stage",["ids":ids.map{String($0.dropFirst(5))}]);stage=try await engine.call("/api/stage");stage["results"]=value["items"];showStage=true}
}
