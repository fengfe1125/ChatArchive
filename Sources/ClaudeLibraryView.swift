import SwiftUI
import AppKit

struct ClaudeLibraryView:View {
    @EnvironmentObject var model:ArchiveModel
    @Environment(\.colorScheme) private var scheme
    @State private var sidebar=true
    @State private var artifacts:[SavedArtifact]=[]
    @State private var selectedArtifact:SavedArtifact?
    @State private var screen="chats"
    @State private var renameTarget:ChatSession?
    @State private var renameText=""
    @State private var filtering=false
    @FocusState private var searchFocused:Bool
    var paper:Color{scheme == .dark ? Color(nsColor:.textBackgroundColor) : Color(red:0.975,green:0.968,blue:0.949)}
    var sidePaper:Color{scheme == .dark ? Color(nsColor:.windowBackgroundColor) : Color(red:0.94,green:0.933,blue:0.915)}
    var body:some View {
        HSplitView {
            if sidebar{sidebarView.frame(minWidth:220,idealWidth:250,maxWidth:310)}
            VStack(spacing:0){
                HStack(spacing:14){
                    Button{sidebar.toggle()}label:{Image(systemName:"sidebar.left")}.help("显示或隐藏侧栏")
                    HStack(spacing:4){modeButton("Chat","account");modeButton("Code","code")}.padding(4).background(Color.primary.opacity(0.045),in:Capsule())
                    Spacer()
                    if let active=model.active,screen != "artifacts" {
                        Text(active.title).font(.system(size:14,weight:.medium)).lineLimit(1).frame(maxWidth:380)
                        Menu{sessionActions(active)}label:{Image(systemName:"chevron.down")}.menuStyle(.borderlessButton).fixedSize()
                    }
                    Spacer()
                    Button{if selectedArtifact != nil{selectedArtifact=nil}else{screen="artifacts"}}label:{Image(systemName:"square.stack")}.help("作品")
                    Button{model.inspector.toggle();if model.inspector{model.perform{try await model.loadDetails()}}}label:{Image(systemName:"sidebar.right")}.help("代码与原始记录").disabled(model.active==nil)
                }.buttonStyle(.plain).padding(.horizontal,20).frame(height:56)
                Divider().opacity(0.35)
                if screen=="artifacts" {artifactGallery}
                else if let active=model.active {
                    if active.source=="account" {AccountTranscriptView(sessionID:active.id,onArtifact:{selectedArtifact=$0}).id(active.id)}
                    else {ConversationView().id(active.id)}
                } else {ContentUnavailableView("你的对话，都在这里",systemImage:"bubble.left.and.bubble.right",description:Text("从左侧选择聊天，或搜索备份中的内容。"))}
            }.frame(minWidth:430,maxWidth:.infinity,maxHeight:.infinity).background(paper)
            if let selectedArtifact{ArtifactPanel(artifact:selectedArtifact,close:{self.selectedArtifact=nil}).id(selectedArtifact.id).frame(minWidth:360,idealWidth:500,maxWidth:.infinity)}
        }
        .background(paper)
        .inspector(isPresented:$model.inspector){InspectorView().inspectorColumnWidth(min:300,ideal:420,max:650)}
        .sheet(isPresented:$filtering){FilterView(isPresented:$filtering).environmentObject(model)}
        .alert("重命名聊天",isPresented:Binding(get:{renameTarget != nil},set:{if !$0{renameTarget=nil}})) {
            TextField("标题",text:$renameText)
            Button("取消",role:.cancel){renameTarget=nil}
            Button("保存"){if let row=renameTarget{update(row,title:renameText)};renameTarget=nil}.disabled(renameText.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty)
        } message:{Text("名称仅保存在本地档案中，原始备份保持不变。")}
        .task {do{let data=try await model.engine.call("/native/artifacts");artifacts=try decode([SavedArtifact].self,data["items"] ?? [])}catch{model.error=error.localizedDescription}}
        .task(id:model.query){do{try await Task.sleep(for:.milliseconds(250));try Task.checkCancellation();model.page=1;try await model.loadSessions()}catch is CancellationError{}catch{model.error=error.localizedDescription}}
        .onReceive(NotificationCenter.default.publisher(for:.archiveSearch)){_ in sidebar=true;searchFocused=true}
    }
    var sidebarView:some View {
        VStack(alignment:.leading,spacing:0){
            HStack{Text("Claude").font(.system(size:25,weight:.medium,design:.serif));Text("档案").font(.caption).foregroundStyle(.secondary);Spacer();Button{sidebar=false}label:{Image(systemName:"sidebar.left")}.buttonStyle(.plain)}.padding(.horizontal,18).padding(.top,20).padding(.bottom,24)
            VStack(spacing:3){
                navigation("搜索聊天","magnifyingglass",selected:searchFocused){searchFocused=true}
                navigation("聊天","bubble.left",selected:screen=="chats" && model.libraryScope=="chats"){scope("chats")}
                navigation("收藏","star",selected:model.libraryScope=="starred" && screen != "artifacts"){scope("starred")}
                navigation("项目","folder",selected:model.surface=="code" && screen != "artifacts"){switchMode("code")}
                navigation("作品","square.stack",selected:screen=="artifacts"){screen="artifacts"}
            }.padding(.horizontal,10)
            HStack{Image(systemName:"magnifyingglass").foregroundStyle(.secondary);TextField("搜索所有对话",text:$model.query).textFieldStyle(.plain).focused($searchFocused);if !model.query.isEmpty{Button{model.query=""}label:{Image(systemName:"xmark.circle.fill")}.buttonStyle(.plain).foregroundStyle(.secondary)}}.padding(10).background(Color.primary.opacity(0.035),in:RoundedRectangle(cornerRadius:8)).padding(12)
            HStack{Text(model.libraryScope=="missing" ? "缺失正文" : model.libraryScope=="archived" ? "已归档" : model.query.isEmpty ? "最近聊天" : "搜索结果").font(.caption).foregroundStyle(.secondary);Spacer();Button{filtering=true}label:{Image(systemName:"line.3.horizontal.decrease")}.buttonStyle(.plain).help("筛选")}.padding(.horizontal,18).padding(.bottom,8)
            ScrollView{
                LazyVStack(alignment:.leading,spacing:3){
                    if model.surface=="code" && model.query.isEmpty {
                        ForEach(model.projects.filter{$0.source=="code"},id:\.path){project in
                            VStack(alignment:.leading,spacing:3){
                                Button{
                                    model.project=model.project==project.path ? "" : project.path
                                    model.sessions=[];model.total=0;model.page=1
                                    model.perform{try await model.loadSessions()}
                                }label:{
                                    HStack(spacing:8){
                                        Image(systemName:model.project==project.path ? "chevron.down" : "chevron.right").font(.system(size:10,weight:.semibold)).foregroundStyle(.secondary).frame(width:12)
                                        Text(folderName(project.path)).font(.system(size:13,weight:.medium)).lineLimit(1)
                                        Spacer(minLength:0)
                                    }.padding(.horizontal,8).padding(.vertical,10).frame(maxWidth:.infinity,alignment:.leading).contentShape(Rectangle())
                                }.buttonStyle(.plain).help(project.path).accessibilityLabel(folderName(project.path)).accessibilityValue(model.project==project.path ? "已展开" : "已折叠")
                                if model.project==project.path{rows.padding(.leading,12)}
                            }
                        }
                    }else{rows}
                    if model.loadingSessions{ProgressView().controlSize(.small).frame(maxWidth:.infinity).padding(12)}
                    if model.sessions.count<model.total{Button("加载更多"){model.page+=1;model.perform{try await model.loadSessions(append:true)}}.buttonStyle(.plain).font(.caption).padding(10)}
                }.padding(.horizontal,10)
            }
            Spacer(minLength:0)
            Divider().padding(.horizontal,12)
            navigation("缺失正文","doc.questionmark",selected:model.libraryScope=="missing"){
                screen="chats";selectedArtifact=nil;model.libraryScope="missing";model.surface="account";model.switchSurface()
            }.padding(.horizontal,10).padding(.top,8)
            navigation("已归档","archivebox",selected:model.libraryScope=="archived"){scope("archived")}.padding(.horizontal,10).padding(.top,8)
            HStack{Circle().fill(Color(red:0.72,green:0.42,blue:0.29)).frame(width:28,height:28).overlay(Text("本").font(.caption).foregroundStyle(.white));VStack(alignment:.leading){Text("本地档案").font(.callout);Text("\(model.counts.values.reduce(0,+)) 条对话").font(.caption2).foregroundStyle(.secondary)};Spacer();SettingsLink{Image(systemName:"gearshape")}.buttonStyle(.plain)}.padding(16)
        }.background(sidePaper)
    }
    @ViewBuilder var rows:some View {
        ForEach(model.sessions){row in
            Button{screen="chats";model.selectSession(row)}label:{
                HStack(spacing:8){VStack(alignment:.leading,spacing:4){Text(row.title).font(.system(size:13)).lineLimit(1);if row.content_available==false{Text("导出缺少正文").font(.system(size:10)).foregroundStyle(.secondary)}};Spacer(minLength:0);if row.review=="useful"{Image(systemName:"star.fill").font(.system(size:10)).foregroundStyle(.secondary)}}
                .padding(.horizontal,10).padding(.vertical,9).frame(maxWidth:.infinity,alignment:.leading).background(model.active?.id==row.id && screen != "artifacts" ? Color.primary.opacity(0.08):.clear,in:RoundedRectangle(cornerRadius:7)).contentShape(Rectangle())
            }.buttonStyle(.plain).help(row.title).contextMenu{sessionActions(row)}
        }
        if model.sessions.isEmpty && !model.loadingSessions{Text("没有符合条件的聊天").font(.caption).foregroundStyle(.secondary).padding(10)}
    }
    var artifactGallery:some View {
        ScrollView{VStack(alignment:.leading,spacing:24){Text("作品").font(.system(size:32,design:.serif));Text("备份中的文档、网页与交互作品").foregroundStyle(.secondary);LazyVGrid(columns:[GridItem(.adaptive(minimum:220),spacing:16)],spacing:16){ForEach(artifacts){item in Button{selectedArtifact=item}label:{VStack(alignment:.leading,spacing:16){Image(systemName:"doc.richtext").font(.title2).foregroundStyle(.secondary);Text(item.title).font(.headline).lineLimit(2);Spacer();Text("\(item.versions.count) 个版本").font(.caption).foregroundStyle(.secondary)}.padding(20).frame(maxWidth:.infinity,minHeight:150,alignment:.leading).background(Color.primary.opacity(0.035),in:RoundedRectangle(cornerRadius:12)).overlay(RoundedRectangle(cornerRadius:12).stroke(Color.primary.opacity(0.09)))}.buttonStyle(.plain)}};if artifacts.isEmpty{Text("当前档案没有 frames 作品包。").foregroundStyle(.secondary)}}.padding(36).frame(maxWidth:1050,alignment:.leading)}
    }
    func navigation(_ text:String,_ icon:String,selected:Bool,action:@escaping()->Void)->some View{Button(action:action){Label(text,systemImage:icon).font(.system(size:14)).frame(maxWidth:.infinity,alignment:.leading).padding(.horizontal,12).padding(.vertical,9).background(selected ? Color.primary.opacity(0.065):.clear,in:RoundedRectangle(cornerRadius:8)).contentShape(Rectangle())}.buttonStyle(.plain)}
    func modeButton(_ text:String,_ value:String)->some View{Button{switchMode(value)}label:{Text(text).font(.system(size:13,weight:.medium)).padding(.horizontal,16).padding(.vertical,6).background(model.surface==value ? paper:.clear,in:Capsule())}.buttonStyle(.plain)}
    func switchMode(_ source:String){screen="chats";selectedArtifact=nil;model.libraryScope="chats";if model.surface != source{model.surface=source;model.switchSurface()}else{scope("chats")}}
    func scope(_ value:String){screen="chats";model.libraryScope=value;model.page=1;model.perform{try await model.loadSessions()}}
    @ViewBuilder func sessionActions(_ row:ChatSession)->some View {
        Button("重命名…"){renameText=row.title;renameTarget=row}
        Button(row.review=="useful" ? "取消收藏" : "收藏"){model.perform{_=try await model.engine.call("/api/archive/review",["id":row.id,"review":row.review=="useful" ? "" : "useful"]);try await model.loadSessions()}}
        Button(model.libraryScope=="archived" ? "恢复到聊天" : "归档"){update(row,archived:model.libraryScope != "archived")}
        Divider()
        Button("导出 Markdown…"){model.export(ids:[row.id],mode:"readable")}
        Button("导出完整记录…"){model.export(ids:[row.id],mode:"complete")}
        Button("在 Codex 中继续…"){model.pendingImports=[row.id];model.confirmImport=true}.disabled(!row.readable || model.taskRunning)
        if row.source=="code"{Button("官方 /import…"){model.perform{try await model.stageSelection([row.id])}}}
        Button("查看原始记录"){model.perform{try await model.openSession(row);model.detailMode=1;model.inspector=true;try await model.loadDetails()}}
    }
    func update(_ row:ChatSession,title:String?=nil,archived:Bool?=nil){model.perform{var body:[String:Any]=["id":row.id];if let title{body["title"]=title};if let archived{body["archived"]=archived};let updated=try await model.engine.call("/native/library/update",body);if model.active?.id==row.id{model.active=try decode(ChatSession.self,updated)};try await model.loadSessions()}}
}
