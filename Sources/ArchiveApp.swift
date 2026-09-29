import SwiftUI
import AppKit

@main struct ArchiveApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    @StateObject private var model=ArchiveModel.shared
    var body: some Scene {
        WindowGroup("聊天档案",id:"main") { RootView().environmentObject(model).frame(minWidth:850,minHeight:600).task {if model.loading {await model.bootstrap()}} }
        .defaultSize(width:1180,height:800)
        .commands {
            CommandGroup(replacing:.newItem) {Button("打开档案…"){model.chooseArchive()}.keyboardShortcut("o");Button("新建备份…"){if !model.taskRunning{model.setup=true;model.step=0}}.keyboardShortcut("n")}
            CommandGroup(after:.textEditing) {Button("搜索聊天"){NotificationCenter.default.post(name:.archiveSearch,object:nil)}.keyboardShortcut("f")}
        }
        Settings { SettingsView().environmentObject(model).frame(width:540).padding(24) }
    }
}
extension Notification.Name {static let archiveSearch=Notification.Name("archiveSearch")}
@MainActor final class AppDelegate:NSObject,NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification:Notification){NSApp.setActivationPolicy(.regular);NSApp.activate(ignoringOtherApps:true)}
    func applicationShouldTerminate(_ sender:NSApplication)->NSApplication.TerminateReply {
        let model=ArchiveModel.shared
        if model.taskRunning {let alert=NSAlert();alert.messageText="任务尚未结束";alert.informativeText="退出会中断当前任务。备份可在下次打开后恢复；Codex 导入将先核对已创建的会话。";alert.addButton(withTitle:"继续等待");alert.addButton(withTitle:"退出并稍后恢复");if alert.runModal() == .alertFirstButtonReturn{return .terminateCancel}}
        model.engine.stop();return .terminateNow
    }
    func applicationWillTerminate(_ notification:Notification){ArchiveModel.shared.engine.stop()}
}

struct RootView:View {
    @EnvironmentObject var model:ArchiveModel
    var body:some View {
        Group {
            if model.loading {VStack(spacing:16){ProgressView();Text("正在启动本机数据引擎…").foregroundStyle(.secondary)}}
            else if model.offline {ContentUnavailableView {Label("档案暂时离线",systemImage:"externaldrive.badge.exclamationmark")} description:{Text(model.archivePath+"\n连接原磁盘，或重新选择档案目录。移动原文后，已有 Codex 交接路径可能需要重新定位。")} actions:{Button("重新连接"){model.perform{try await model.open(model.archivePath)}};Button("重新定位…"){model.chooseArchive()};Button("创建新档案"){model.offline=false;model.setup=true;model.step=0}}}
            else if model.setup {SetupView()}
            else {LibraryView()}
        }
        .overlay(alignment:.top){if model.busy {ProgressView("正在校验与建立索引…").padding().background(.regularMaterial,in:RoundedRectangle(cornerRadius:12)).padding()}}
        .alert("无法完成操作",isPresented:Binding(get:{model.error != nil},set:{if !$0{model.error=nil}})){Button("好"){model.error=nil}} message:{Text(model.error ?? "")}
        .sheet(isPresented:$model.taskVisible){TaskView().environmentObject(model)}
        .sheet(isPresented:$model.showStage){StageView().environmentObject(model)}
        .confirmationDialog("导入 \(model.pendingImports.count) 条聊天到 Codex？",isPresented:$model.confirmImport,titleVisibility:.visible){Button("创建 Codex 续聊会话"){model.perform{try await model.job("/native/import",["ids":model.pendingImports])}}} message:{Text("所选原文将保存在档案目录，并由已登录的 Codex 读取交接内容。已有会话会跳过；备份中的历史命令不会自动执行。")}
    }
}

struct SetupView:View {
    @EnvironmentObject var model:ArchiveModel
    let titles=["检测环境","选择聊天来源","选择备份位置","复制与验证"]
    var body:some View {
        VStack(alignment:.leading,spacing:0){
            HStack{Image(systemName:"tray.full.fill").font(.largeTitle).foregroundStyle(.tint);VStack(alignment:.leading){Text("把聊天留在自己手里").font(.title2.bold());Text("聊天档案 · 本机备份与 Codex 续聊").foregroundStyle(.secondary)};Spacer();if !model.archivePath.isEmpty {Button("返回档案"){model.setup=false}.disabled(model.taskRunning)}}.padding(28)
            HStack{ForEach(0..<4){n in Label(titles[n],systemImage:n<model.step ? "checkmark.circle.fill" : "\(n+1).circle\(n==model.step ? ".fill" : "")").font(.callout).foregroundStyle(n==model.step ? Color.accentColor : Color.secondary);if n<3 {Divider().frame(height:16);Spacer()}}}.padding(.horizontal,30).padding(.bottom,20)
            Divider()
            Form {
                if model.step==0 {
                    Section("Codex 环境") {if model.detecting{ProgressView("正在后台检测，可先继续选择来源…")};LabeledContent("程序",value:model.codex["path"]?.isEmpty==false ? model.codex["path"]! : "未找到");LabeledContent("版本",value:model.codex["version"] ?? "待检查");LabeledContent("登录",value:model.codex["login"] ?? "待检查");LabeledContent("导入接口",value:model.codex["interface"] ?? "待检查");HStack{Button("重新检测"){model.perform{try await model.detect()}};Button("指定 Codex 程序…"){if let url=chooseFiles("选择 Codex 可执行程序").first{model.perform{try await model.detect(url.path)}}}}}
                    Section("发现的聊天来源") {if model.sources.isEmpty{Label("没有发现本机 Claude Code 聊天，可在下一步添加备份或 ZIP。",systemImage:"folder.badge.questionmark").foregroundStyle(.secondary)};ForEach(model.sources){s in LabeledContent(folderName(s.path),value:"\(s.count) 条 · \(bytes(s.bytes))")};Text("检测不会安装软件，也不会创建 Codex 会话。Codex 不可用时仍可备份与阅读。").font(.caption).foregroundStyle(.secondary)}
                    if let pending=UserDefaults.standard.string(forKey:"pendingBackup"),FileManager.default.fileExists(atPath:pending){Section("上次未完成的备份"){Text(pending).font(.caption).textSelection(.enabled);Button("恢复备份"){model.perform{try await model.startBackup(resume:pending)}}}}
                    Section {Button("直接打开已有档案…"){model.chooseArchive()}}
                } else if model.step==1 {
                    Section("勾选要备份的来源") {if model.scanningSources{ProgressView("正在识别文件夹中的聊天备份…")};if !model.sourceScanMessage.isEmpty{Text(model.sourceScanMessage).font(.callout).textSelection(.enabled)};ForEach($model.sources){$source in Toggle(isOn:$source.selected){VStack(alignment:.leading,spacing:5){Text(folderName(source.path));Text(source.path).font(.caption).foregroundStyle(.secondary).textSelection(.enabled);Text("\(source.summary) · \(bytes(source.bytes))"+(source.modified>0 ? " · "+Date(timeIntervalSince1970:source.modified).formatted(date:.abbreviated,time:.omitted) : "")).font(.caption)}}};if model.sources.isEmpty{Text("选择一个文件夹，自动查找其中的 Chat 账号导出与 Code 聊天备份。").foregroundStyle(.secondary)};HStack{Button("选择文件夹并自动检测…"){if let url=chooseFolder("选择可能包含 Chat 或 Code 备份的文件夹"){model.addSource(url)}};Button("添加账号 ZIP…"){for url in chooseFiles("选择 Claude 官方导出 ZIP",zip:true){model.addSource(url)}}}}
                    Section("从 Claude 官方导出清单下载") {
                        Text("在 Claude 申请导出后，选择收到的 manifest JSON 清单。App 下载并校验 ZIP，备份后自动解压读取，无需手动解压。若链接要求登录，请在浏览器下载后添加本地文件夹。").foregroundStyle(.secondary)
                        HStack {Button("选择清单并下载…"){model.downloadExport()};Button("恢复之前的下载…"){model.downloadExport(resume:true)}}.disabled(model.downloading)
                        if model.downloading {ProgressView("正在下载与校验…")}
                        if !model.downloadMessage.isEmpty {Text(model.downloadMessage).textSelection(.enabled)}
                        if !model.downloadRoot.isEmpty {Text(model.downloadRoot).font(.caption).textSelection(.enabled)}
                    }
                    Section {Text("只复制聊天、关联子代理及文件历史。账号导出保留原 ZIP。不会复制登录凭据、应用配置、项目仓库和技能。").foregroundStyle(.secondary);Button("已有备份只建立索引，不再复制…"){model.chooseArchive()}}
                } else if model.step==2 {
                    Section("保存到 Codex 档案目录") {Text("已自动定位 Codex 数据目录。原始备份保存在其中的 chat-archive 文件夹；进入档案后，可选择聊天导入 Codex 会话列表。").foregroundStyle(.secondary);HStack{Button("更改位置…",systemImage:"folder"){model.pickDestination()};Button("使用 Codex 默认位置"){model.perform{try await model.useCodexDestination()}}};if !model.destination.isEmpty{LabeledContent("位置",value:model.destination);LabeledContent("所在磁盘",value:(try? URL(fileURLWithPath:model.destination).resourceValues(forKeys:[.volumeNameKey]).volumeName) ?? "—");LabeledContent("可用空间",value:bytes(model.freeSpace));LabeledContent("预计备份",value:bytes(model.sources.filter(\.selected).reduce(0){$0+$1.bytes}))};Text("将在所选位置创建独立批次，保留原始文件及哈希清单。不会覆盖已有备份。").font(.callout).foregroundStyle(.secondary)}
                } else {
                    Section("备份状态") {Text(backupTitle).font(.headline);LabeledContent("当前阶段",value:model.backup["phase"] as? String ?? "准备");ProgressView(value:Double(model.backup["completed"] as? Int ?? 0),total:Double(max(1,model.backup["total"] as? Int ?? 1)));LabeledContent("已校验文件",value:"\(model.backup["completed"] as? Int ?? 0) / \(model.backup["total"] as? Int ?? 0)");LabeledContent("已校验大小",value:bytes((model.backup["copied_bytes"] as? NSNumber)?.int64Value ?? 0));Text(model.backup["current"] as? String ?? "准备中…").font(.caption).lineLimit(2);Text(model.backup["root"] as? String ?? "").font(.caption).textSelection(.enabled);ForEach(Array((model.backup["errors"] as? [[String:Any]] ?? []).enumerated()),id:\.offset){_,e in Text((e["path"] as? String ?? "")+"："+(e["error"] as? String ?? "失败")).foregroundStyle(.red).font(.caption)}}
                }
            }.formStyle(.grouped)
            Divider()
            HStack{if model.step>0 && model.step<3 {Button("上一步"){model.step-=1}};Spacer();if model.step<2 {Button("继续"){model.nextSetupStep()}.buttonStyle(.borderedProminent).disabled(model.downloading || model.scanningSources || (model.step==1 && model.sourcePaths.isEmpty))}else if model.step==2 {Button("开始备份"){model.perform{try await model.startBackup()}}.buttonStyle(.borderedProminent).disabled(model.destination.isEmpty)}else if model.backup["status"] as? String == "running" {Button("取消并保留进度"){model.perform{_=try await model.engine.call("/native/backup/cancel",["id":model.backupID])}}}else{if model.backup["status"] as? String != "completed"{Button("重试未完成项"){model.perform{try await model.startBackup(resume:model.backup["root"] as? String)}}};Button(model.backup["status"] as? String == "completed" ? "进入聊天档案" : "查看已成功备份的内容"){model.perform{try await model.open(model.backup["root"] as? String ?? "")}}.buttonStyle(.borderedProminent).disabled((model.backup["completed"] as? Int ?? 0)==0)}}.padding(20)
        }
    }
    var backupTitle:String {["running":"正在复制并校验","completed":"备份完成","partial":"部分文件未完成","cancelled":"已取消，可继续恢复"][model.backup["status"] as? String ?? ""] ?? "准备备份"}
}

struct LibraryView:View {
    @EnvironmentObject var model:ArchiveModel
    @State private var visibility:NavigationSplitViewVisibility = .all
    @State private var filtering=false
    @State private var selecting=false
    @FocusState private var searchFocus:Bool
    var body:some View {
        NavigationSplitView(columnVisibility:$visibility){
            VStack(spacing:0){Picker("来源",selection:$model.surface){Text("Chat").tag("account");Text("Code").tag("code")}.pickerStyle(.segmented).padding().onChange(of:model.surface){old,new in if model.active?.source != new {model.switchSurface()}}
                TextField("搜索 Chat 和 Code",text:$model.query).textFieldStyle(.roundedBorder).padding(.horizontal).focused($searchFocus).onChange(of:model.query){_,_ in model.page=1;model.perform{try await Task.sleep(for:.milliseconds(200));try await model.loadSessions()}}
                List {
                    if model.surface=="code" && model.query.isEmpty {
                        ForEach(model.projects.filter{$0.source=="code"},id:\.path){p in DisclosureGroup(isExpanded:Binding(get:{model.project==p.path},set:{open in model.project=open ? p.path : "";model.sessions=[];model.page=1;model.perform{try await model.loadSessions()}})){if model.project==p.path{sessionRows}}label:{HStack{Label(folderName(p.path),systemImage:"folder");Spacer();Text("\(p.count)").foregroundStyle(.tertiary).font(.caption)}.help(p.path)}}
                    }else{Section(model.query.isEmpty ? "最近聊天" : "跨来源搜索结果"){sessionRows}}
                }.listStyle(.sidebar)
                Divider();HStack{Button {filtering=true}label:{Image(systemName:"line.3.horizontal.decrease")}.help("筛选会话");Button {selecting.toggle()}label:{Image(systemName:selecting ? "checkmark.circle.fill" : "checklist")}.help("选择多条");Spacer();if selecting {Text("已选 \(model.selection.count)").font(.caption);Menu {selectionActions}label:{Image(systemName:"ellipsis.circle")}}}.buttonStyle(.borderless).padding(12)
                HStack{SettingsLink{Label("档案设置",systemImage:"gearshape")};Spacer();Text("\(model.counts[model.surface] ?? 0) 条").font(.caption).foregroundStyle(.secondary)}.padding(.horizontal,12).padding(.bottom,12)
            }.navigationSplitViewColumnWidth(min:240,ideal:275,max:380)
        } detail:{
            Group{if let active=model.active {if active.source=="account" {AccountReadingView(sessionID:active.id).id(active.id)}else{ConversationView().id(active.id)}}else{ContentUnavailableView("选择一条聊天",systemImage:model.surface=="code" ? "chevron.left.forwardslash.chevron.right" : "bubble.left.and.bubble.right",description:Text(model.surface=="code" ? "展开项目文件夹，找回对话和文件改动。" : "阅读已保存的 Claude 对话，标记有用的内容。"))}}
                .navigationTitle(model.active?.title ?? (model.surface=="code" ? "Code" : "Chat"))
                .toolbar {
                    ToolbarItemGroup {if model.sourceChanged{Image(systemName:"arrow.triangle.2.circlepath").foregroundStyle(.orange).help("来源有新增或变化，可在设置中新建备份")};Button {model.inspector.toggle();if model.inspector {model.perform{try await model.loadDetails()}}}label:{Label("代码与文件",systemImage:"sidebar.right")}.disabled(model.active==nil);Menu{conversationActions}label:{Label("会话菜单",systemImage:"ellipsis.circle")}.disabled(model.active==nil)}
                }
                .inspector(isPresented:$model.inspector){InspectorView().inspectorColumnWidth(min:300,ideal:430,max:750)}
        }
        .sheet(isPresented:$filtering){FilterView(isPresented:$filtering).environmentObject(model)}
        .onReceive(NotificationCenter.default.publisher(for:.archiveSearch)){_ in visibility = .all;searchFocus=true}
    }
    @ViewBuilder var sessionRows:some View {
        ForEach(model.sessions){row in HStack(alignment:.top,spacing:8){if selecting{Toggle("选择 \(row.title)",isOn:Binding(get:{model.selection.contains(row.id)},set:{if $0{model.selection.insert(row.id)}else{model.selection.remove(row.id)}})).labelsHidden().toggleStyle(.checkbox)};Button {model.selectSession(row)}label:{VStack(alignment:.leading,spacing:4){HStack{Text(row.title).lineLimit(2);if row.review=="useful"{Image(systemName:"star.fill").foregroundStyle(.orange).font(.caption)}};HStack{if !model.query.isEmpty{Text(row.source=="code" ? "Code" : "Chat")};Text(row.content_available==false ? "导出缺少正文" : (row.source=="account" ? String(row.last_at?.prefix(10) ?? "") : row.statusName))}.font(.caption2).foregroundStyle(.secondary)}.frame(maxWidth:.infinity,alignment:.leading).padding(.vertical,3).contentShape(Rectangle())}.buttonStyle(.plain)}.listRowBackground(model.active?.id==row.id ? Color.accentColor.opacity(0.14) : Color.clear)}
        if model.sessions.count<model.total {Button("加载更多（\(model.sessions.count) / \(model.total)）"){model.page+=1;model.perform{try await model.loadSessions(append:true)}}}
        if model.loadingSessions {ProgressView("正在加载列表…")}
        if model.sessions.isEmpty && !model.loadingSessions{Text("没有符合条件的聊天").font(.caption).foregroundStyle(.secondary)}
    }
    @ViewBuilder var conversationActions:some View {
        if let active=model.active {Text(active.statusName);Divider();ForEach([("useful","有用"),("later","待定"),("ignore","忽略"),("","清除标记")],id:\.0){value,title in Button(title){model.perform{try await model.review(value)}}};Divider();Button("查看原始记录"){model.inspector=true;model.detailMode=1;model.perform{try await model.loadDetails()}};Menu("导出当前聊天"){Button("阅读版 Markdown…"){model.export(ids:[active.id],mode:"readable")};Button("完整记录版 Markdown…"){model.export(ids:[active.id],mode:"complete")}};Button("导入 Codex 后续聊…"){model.pendingImports=[active.id];model.confirmImport=true}.disabled(!active.readable);if active.source=="code"{Button("近期官方 /import…"){model.perform{try await model.stageSelection([active.id])}}}}
    }
    @ViewBuilder var selectionActions:some View {Button("导出阅读版…"){model.export(ids:Array(model.selection),mode:"readable")};Button("导出完整记录版…"){model.export(ids:Array(model.selection),mode:"complete")};Button("导入 Codex…"){model.pendingImports=Array(model.selection);model.confirmImport=true};Button("近期官方 /import…"){model.perform{try await model.stageSelection(Array(model.selection))}};Divider();Button("清空选择"){model.selection=[]}}
}
