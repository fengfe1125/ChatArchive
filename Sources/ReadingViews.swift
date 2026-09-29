import SwiftUI
import AppKit

struct ConversationView:View {
    @EnvironmentObject var model:ArchiveModel
    @State private var position:String?
    var body:some View {
        VStack(spacing:0){
            ScrollView {LazyVStack(alignment:.leading,spacing:26){
                if let row=model.active{Text("\(row.source=="code" ? row.project : "Chat · 未分类") · \(row.last_at?.prefix(10) ?? "时间未知")").font(.caption).foregroundStyle(.secondary).textSelection(.enabled)}
                ForEach(model.messages){message in
                    HStack(alignment:.top){if message.role=="user"{Spacer(minLength:35)};VStack(alignment:.leading,spacing:12){if message.role != "user" && message.continuation != true {Label("Claude",systemImage:"sparkle").foregroundStyle(.secondary).font(.caption)};if message.segmented==true {Text(message.continuation==true ? "长消息 · 续段" : "长消息 · 分段显示").font(.caption).foregroundStyle(.secondary)};if message.plain==true {Text(message.text).textSelection(.enabled)}else{MarkdownBody(text:message.text)};ForEach(Array((message.media ?? []).enumerated()),id:\.offset){_,media in if let text=media.text,!text.isEmpty{DisclosureGroup(media.name ?? "附件提取文本"){Text(text).font(.system(.body,design:.monospaced)).textSelection(.enabled)}}else{Label((media.name ?? "附件")+" · 原附件未包含在备份中",systemImage:"doc.badge.ellipsis").font(.caption).foregroundStyle(.secondary)}};Button(message.segmented==true ? "复制这一段" : "复制",systemImage:"doc.on.doc"){copyText(message.text.isEmpty ? (message.media ?? []).compactMap(\.text).joined(separator:"\n") : message.text)}.labelStyle(.iconOnly).buttonStyle(.borderless).font(.caption).foregroundStyle(.secondary)}.padding(message.role=="user" ? 16 : 0).background(message.role=="user" ? Color(nsColor:.controlBackgroundColor) : .clear,in:RoundedRectangle(cornerRadius:16));if message.role != "user"{Spacer(minLength:0)}}.id(message.id)
                }
                if model.active?.content_available==false {Label("官方导出没有可恢复正文，仍可查看原始元数据。",systemImage:"doc.badge.exclamationmark").foregroundStyle(.secondary)}
                if model.loadingMessages {ProgressView("正在加载对话…").frame(maxWidth:.infinity)}
                if let error=model.messageError {Text(error).font(.callout).foregroundStyle(.red)}
                if model.messageNext != nil && !model.loadingMessages {Button(model.messageError == nil ? "继续加载对话" : "重试加载"){model.perform{try await model.moreMessages()}}.frame(maxWidth:.infinity)}
            }.padding(28).frame(maxWidth:850).frame(maxWidth:.infinity).scrollTargetLayout()}.scrollPosition(id:$position,anchor:.top)
            .onChange(of:position){_,value in if let id=model.active?.id,let value{model.scrollIDs[id]=value;if model.previewPath==nil{UserDefaults.standard.set(model.scrollIDs,forKey:"scrollPositions")}}}
            .onChange(of:model.active?.id){_,id in position=id.flatMap{model.scrollIDs[$0]}}
            Divider()
            HStack{VStack(alignment:.leading,spacing:5){Text("历史档案只读").foregroundStyle(.secondary);Text("原文保存在你选择的档案目录").font(.caption).foregroundStyle(.tertiary)};Spacer();Button {if let row=model.active{model.pendingImports=[row.id];model.confirmImport=true}}label:{Label(["present","archived"].contains(model.active?.status ?? "") ? "已在 Codex" : "导入 Codex 后续聊",systemImage:"arrow.up.right")}.buttonStyle(.borderedProminent).disabled(model.active?.readable != true || ["present","archived"].contains(model.active?.status ?? "") || model.taskRunning)}.padding(20)
        }.background(Color(nsColor:.textBackgroundColor))
    }
}
struct MarkdownBlock:Identifiable {let id:Int;let kind:String;let text:String;let language:String}
func markdownBlocks(_ text:String)->[MarkdownBlock] {
    let lines=text.components(separatedBy:"\n");var output:[MarkdownBlock]=[];var index=0;var paragraph:[String]=[]
    func append(_ kind:String,_ value:String,_ language:String=""){output.append(MarkdownBlock(id:output.count,kind:kind,text:value,language:language))}
    func flush(){if !paragraph.isEmpty{append("text",paragraph.joined(separator:"\n"));paragraph=[]}}
    while index<lines.count {let line=lines[index],trim=line.trimmingCharacters(in:.whitespaces)
        if trim.hasPrefix("```") || trim.hasPrefix("~~~") {flush();let delimiter=String(trim.prefix(while:{$0==trim.first!}));let language=String(trim.dropFirst(delimiter.count));index+=1;var code:[String]=[];while index<lines.count && !lines[index].trimmingCharacters(in:.whitespaces).hasPrefix(delimiter){code.append(lines[index]);index+=1};append("code",code.joined(separator:"\n"),language)}
        else if trim.hasPrefix("#") && trim.contains(" "){flush();let count=trim.prefix(while:{$0=="#"}).count;append("h\(min(count,3))",String(trim.dropFirst(count)).trimmingCharacters(in:.whitespaces))}
        else if index+1<lines.count && line.contains("|") && lines[index+1].contains("---"){flush();var table=[line];index+=2;while index<lines.count && lines[index].contains("|") {table.append(lines[index]);index+=1};index-=1;append("table",table.joined(separator:"\n"))}
        else if trim.isEmpty{flush()}
        else if trim=="---" || trim=="***"{flush();append("rule","")}
        else if trim.hasPrefix("> "){flush();append("quote",String(trim.dropFirst(2)))}
        else{paragraph.append(line)}
        index+=1
    };flush();return output
}
struct MarkdownBody:View {
    let text:String
    var body:some View {VStack(alignment:.leading,spacing:14){ForEach(markdownBlocks(text)){block in switch block.kind {
        case "code":VStack(alignment:.leading,spacing:8){HStack{Text(block.language.isEmpty ? "代码" : block.language).font(.caption).foregroundStyle(.secondary);Spacer();Button("复制"){copyText(block.text)}.buttonStyle(.borderless).font(.caption)};ScrollView(.horizontal){Text(block.text).font(.system(size:12,design:.monospaced)).textSelection(.enabled).fixedSize(horizontal:true,vertical:false)}}.padding(12).background(Color(nsColor:.controlBackgroundColor),in:RoundedRectangle(cornerRadius:8))
        case "h1":inline(block.text).font(.title2.bold())
        case "h2":inline(block.text).font(.title3.bold())
        case "h3":inline(block.text).font(.headline)
        case "quote":HStack{Rectangle().fill(.secondary.opacity(0.3)).frame(width:3);inline(block.text).foregroundStyle(.secondary)}.fixedSize(horizontal:false,vertical:true)
        case "rule":Divider()
        case "table":ScrollView(.horizontal){Grid(alignment:.leading,horizontalSpacing:18,verticalSpacing:10){ForEach(Array(block.text.components(separatedBy:"\n").enumerated()),id:\.offset){row,line in GridRow{ForEach(Array(tableCells(line).enumerated()),id:\.offset){_,cell in inline(cell).fontWeight(row==0 ? .semibold : .regular).frame(minWidth:80,alignment:.leading)}};Divider()}}}.font(.callout)
        default:inline(block.text).lineSpacing(5)
    }}}.frame(maxWidth:.infinity,alignment:.leading).textSelection(.enabled)}
    func inline(_ value:String)->Text {Text((try? AttributedString(markdown:value,options:.init(interpretedSyntax:.inlineOnlyPreservingWhitespace))) ?? AttributedString(value))}
    func tableCells(_ line:String)->[String]{var cells=line.components(separatedBy:"|");if cells.first?.trimmingCharacters(in:.whitespaces).isEmpty==true{cells.removeFirst()};if cells.last?.trimmingCharacters(in:.whitespaces).isEmpty==true{cells.removeLast()};return cells.map{$0.trimmingCharacters(in:.whitespaces)}}
}

struct NativeCodeText:NSViewRepresentable {
    let text:String;var tint:NSColor = .textBackgroundColor
    func makeNSView(context:Context)->NSScrollView {let scroll=NSScrollView();scroll.hasVerticalScroller=true;scroll.hasHorizontalScroller=true;scroll.autohidesScrollers=true;let view=NSTextView();view.isEditable=false;view.isSelectable=true;view.isRichText=false;view.font = .monospacedSystemFont(ofSize:12,weight:.regular);view.textContainerInset=NSSize(width:12,height:12);view.isHorizontallyResizable=true;view.isVerticallyResizable=true;view.autoresizingMask=[.width];view.textContainer?.widthTracksTextView=false;view.textContainer?.containerSize=NSSize(width:CGFloat.greatestFiniteMagnitude,height:CGFloat.greatestFiniteMagnitude);scroll.documentView=view;return scroll}
    func updateNSView(_ scroll:NSScrollView,context:Context){guard let view=scroll.documentView as? NSTextView else{return};let numbered=text.components(separatedBy:"\n").enumerated().map{String(format:"%4d  ",$0.offset+1)+$0.element}.joined(separator:"\n");if view.string != numbered{view.string=numbered;view.scrollToBeginningOfDocument(nil)};view.textColor = .textColor;view.backgroundColor=tint;view.insertionPointColor = .textColor}
}
struct InspectorView:View {
    @EnvironmentObject var model:ArchiveModel
    var groups:[String:[CodeItem]]{Dictionary(grouping:model.codeItems,by:{$0.origin=="chat" ? "聊天代码块" : $0.title})}
    var body:some View {VStack(spacing:0){Picker("检查器",selection:$model.detailMode){Text("代码与文件").tag(0);Text("原始记录").tag(1)}.pickerStyle(.segmented).padding(12).onChange(of:model.detailMode){_,_ in model.perform{try await model.loadDetails()}}
        if model.detailMode==0 {
            List{ForEach(groups.keys.sorted(),id:\.self){key in DisclosureGroup(key=="聊天代码块" ? key : folderName(key)){ForEach(groups[key] ?? []){item in Button {model.perform{try await model.selectCode(item)}}label:{VStack(alignment:.leading,spacing:3){Text(item.origin=="chat" ? item.title : "\(item.origin) · 记录 \(item.line ?? 0)");Text(item.completeness).font(.caption).foregroundStyle(.secondary)}}.buttonStyle(.plain).listRowBackground(model.selectedCode==item.id ? Color.accentColor.opacity(0.15):Color.clear)}}.help(key)}}.frame(minHeight:120,idealHeight:190,maxHeight:240)
            Divider();Text(model.codeMetadata.isEmpty ? "选择文件或代码块" : model.codeMetadata).font(.caption).foregroundStyle(.secondary).textSelection(.enabled).frame(maxWidth:.infinity,alignment:.leading).padding(12)
            if let before=model.before,let after=model.after {VSplitView{VStack(alignment:.leading,spacing:0){Text("原片段").font(.caption.bold()).padding(8);NativeCodeText(text:before,tint:NSColor.systemRed.withAlphaComponent(0.07))};VStack(alignment:.leading,spacing:0){Text("新片段").font(.caption.bold()).padding(8);NativeCodeText(text:after,tint:NSColor.systemGreen.withAlphaComponent(0.07))}}}else{NativeCodeText(text:model.codeContent)}
            Button("复制代码原文"){copyText(model.codeContent)}.disabled(model.codeContent.isEmpty).padding(8)
        }else{ScrollView{LazyVStack(alignment:.leading,spacing:12){Text("源文件记录；展开后按块加载，不执行任何历史内容。").font(.caption).foregroundStyle(.secondary);ForEach(model.raw){row in DisclosureGroup {if let text=model.rawText[row.line]{Text(text).font(.system(.caption,design:.monospaced)).textSelection(.enabled);if model.rawNext[row.line] != nil {Button("继续加载此记录"){model.perform{try await model.expandRaw(row.line)}}}}else{ProgressView().task{model.perform{try await model.expandRaw(row.line)}}}}label:{Text("记录 \(row.line) · \(row.type)").font(.callout)};Divider()};if model.rawPageNext != nil {Button("加载更多原始记录"){model.perform{try await model.moreRaw()}}}}.padding(14)}}
    }}
}
struct FilterView:View {
    @EnvironmentObject var model:ArchiveModel;@Binding var isPresented:Bool
    var body:some View {VStack{Text("筛选聊天").font(.headline);Form{Picker("导入状态",selection:$model.statusFilter){Text("全部").tag("");Text("未导入").tag("new");Text("已在 Codex").tag("present");Text("已归档").tag("archived");Text("目标缺失").tag("missing");Text("内容更新").tag("changed");Text("需核对").tag("needs_review")};Picker("整理标记",selection:$model.reviewFilter){Text("全部").tag("");Text("有用").tag("useful");Text("待定").tag("later");Text("忽略").tag("ignore")};Picker("内容",selection:$model.codeFilter){Text("全部").tag("");Text("有代码块").tag("blocks");Text("有文件改动").tag("files")};TextField("开始日期 YYYY-MM-DD",text:$model.dateFrom);TextField("结束日期 YYYY-MM-DD",text:$model.dateTo)}.formStyle(.grouped);HStack{Button("重置"){model.statusFilter="";model.reviewFilter="";model.codeFilter="";model.dateFrom="";model.dateTo=""};Spacer();Button("应用"){isPresented=false;model.page=1;model.perform{try await model.loadSessions()}}.buttonStyle(.borderedProminent)}}.padding(20).frame(width:420,height:400)}
}
struct SettingsView:View {
    @EnvironmentObject var model:ArchiveModel
    var body:some View {Form{Section("档案位置"){Text(model.archivePath.isEmpty ? "尚未创建档案" : model.archivePath).font(.caption).textSelection(.enabled);HStack{Button("打开其他档案…"){model.chooseArchive()};Button("关闭档案"){model.closeArchive()};Button("新建备份…"){if !model.taskRunning{model.setup=true;model.step=0;NSApp.activate(ignoringOtherApps:true)}}}.disabled(model.taskRunning);if !model.archivePath.isEmpty{Button("在 Finder 显示"){NSWorkspace.shared.selectFile(nil,inFileViewerRootedAtPath:model.archivePath)}};Text("更换位置不会移动旧档案。已有 Codex 会话仍引用当时的交接路径。").font(.caption).foregroundStyle(.secondary)}
        Section("Codex"){LabeledContent("状态",value:model.codex["login"] ?? "待检查");Button("重新检测"){model.perform{try await model.detect()}};Button("指定程序…"){if let url=chooseFiles("选择 Codex 程序").first{model.perform{try await model.detect(url.path)}}}}
        if !model.setup{Section("导出与迁移"){Button("全部聊天 · 阅读版 Markdown…"){model.export(ids:nil,mode:"readable")};Button("全部聊天 · 完整记录版…"){model.export(ids:nil,mode:"complete")};Button("迁移旧网站的整理与导入记录…"){if let url=chooseFolder("选择旧网站 data 目录"){model.perform{_=try await model.engine.call("/native/migrate",["path":url.path]);try await model.loadSessions()}}};Button("核对 Codex 状态"){model.perform{_=try await model.engine.call("/api/reconcile",[:]);try await model.loadSessions()}};Button("查看官方导入暂存"){model.perform{model.stage=try await model.engine.call("/api/stage");model.showStage=true}}}}
        if !model.restoredJobs.isEmpty{Section("历史导入任务"){ForEach(Array(model.restoredJobs.enumerated()),id:\.offset){_,job in HStack{Text("\(job["completed"] as? Int ?? 0) / \(job["total"] as? Int ?? 0) · \(job["status"] as? String ?? "")");Spacer();Button("核对并恢复"){model.pendingImports=job["ids"] as? [String] ?? [];model.confirmImport=true}}}}}
    }.formStyle(.grouped)}
}
struct TaskView:View {
    @EnvironmentObject var model:ArchiveModel
    var body:some View {VStack(alignment:.leading,spacing:15){Text(model.task["status"] as? String == "running" ? "正在处理" : "处理结果").font(.title2);ProgressView(value:Double(model.task["completed"] as? Int ?? 0),total:Double(max(1,model.task["total"] as? Int ?? 1)));Text("\(model.task["completed"] as? Int ?? 0) / \(model.task["total"] as? Int ?? 0) 条");ScrollView{VStack(alignment:.leading,spacing:12){ForEach(Array((model.task["results"] as? [[String:Any]] ?? []).enumerated()),id:\.offset){_,row in if let directory=row["directory"] as? String {Text("已导出 \(row["count"] as? Int ?? 0) 条");Button("在 Finder 打开导出"){NSWorkspace.shared.selectFile(nil,inFileViewerRootedAtPath:directory)}}else{Text("\(row["status"] as? String ?? "完成") · \(row["thread_id"] as? String ?? "")").textSelection(.enabled)}};ForEach(Array((model.task["errors"] as? [[String:Any]] ?? []).enumerated()),id:\.offset){_,row in Text((row["id"] as? String ?? "")+"\n"+(row["error"] as? String ?? "失败")).foregroundStyle(.red).textSelection(.enabled)}}};HStack{Spacer();Button("收起"){model.taskVisible=false}}}.padding(24).frame(width:570,height:400)}
}
struct StageView:View {
    @EnvironmentObject var model:ArchiveModel
    var body:some View {VStack(alignment:.leading,spacing:16){Text("近期官方导入").font(.title2);Text("在终端进入以下项目目录，运行 codex，再输入 /import 选择已暂存会话。每批最多 50 条，同批必须属于同一项目。");Text(model.stage["cwd"] as? String ?? "尚无暂存").font(.system(.caption,design:.monospaced)).textSelection(.enabled);Button("复制终端命令"){let cwd=(model.stage["cwd"] as? String ?? "").replacingOccurrences(of:"'",with:"'\\''");copyText("codex -C '\(cwd)'")};ForEach(Array((model.stage["results"] as? [[String:Any]] ?? []).enumerated()),id:\.offset){_,r in Text("\(r["status"] as? String ?? "") · \(r["reason"] as? String ?? r["error"] as? String ?? "")").font(.caption)};Text("只清理本工具创建且哈希未变化的副本。").font(.caption).foregroundStyle(.secondary);HStack{Button("核对结果"){model.perform{_=try await model.engine.call("/api/reconcile",[:]);try await model.loadSessions()}};Button("清理暂存"){model.perform{_=try await model.engine.call("/api/stage/cleanup",[:]);model.stage=try await model.engine.call("/api/stage")}};Spacer();Button("完成"){model.showStage=false}}}.padding(24).frame(width:570)}
}
