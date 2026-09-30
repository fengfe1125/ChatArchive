import SwiftUI

struct AccountBranch: Decodable, Identifiable { let id:String; let title:String }
struct SavedArtifact: Decodable, Identifiable { let id:String; let title:String; let versions:[AccountBranch] }

struct AccountReadingView: View {
    @EnvironmentObject var model:ArchiveModel
    let sessionID:String
    @State private var messages:[Message]=[]
    @State private var branches:[AccountBranch]=[]
    @State private var branch=""
    @State private var next:Int?=0
    @State private var loading=false
    @State private var error:String?
    @State private var generation=0
    @State private var showArtifacts=false
    @Environment(\.colorScheme) private var scheme
    var paper:Color {scheme == .dark ? Color(nsColor:.textBackgroundColor) : Color(red:0.98,green:0.97,blue:0.95)}
    var body:some View {
        VStack(spacing:0) {
            HStack {
                if branches.count>1 {
                    Picker("对话分支",selection:$branch) {
                        Text("最近分支").tag("")
                        ForEach(branches){Text($0.title).tag($0.id)}
                        Text("全部记录（含其他分支）").tag("all")
                    }.frame(maxWidth:330)
                    Text("导出未记录当时选中的分支").font(.caption).foregroundStyle(.secondary)
                } else {Text("Claude · 历史对话").font(.caption).foregroundStyle(.secondary)}
                Spacer()
                Button("作品库",systemImage:"square.stack"){showArtifacts=true}
            }.padding(.horizontal,24).padding(.vertical,12)
            Divider().opacity(0.4)
            ScrollView {
                LazyVStack(alignment:.leading,spacing:22) {
                    ForEach(messages){message in
                        AccountMessageView(message:message)
                    }
                    if loading {ProgressView("正在读取…").frame(maxWidth:.infinity)}
                    if let error {Text(error).foregroundStyle(.red)}
                    if next != nil {
                        Button(error == nil ? "继续阅读" : "重试"){Task{await more()}}
                            .frame(maxWidth:.infinity)
                            .disabled(loading)
                            .task(id:next) {if !loading && error == nil {await more()}}
                    }
                    if messages.isEmpty && !loading && error == nil {
                        ContentUnavailableView("此分支没有消息正文",systemImage:"text.bubble",description:Text("原始导出未提供此分支的正文。可查看作品库、切换分支，或从会话菜单核对原始记录。"))
                    }
                }.padding(.vertical,30).padding(.horizontal,32).frame(maxWidth:800).frame(maxWidth:.infinity)
            }
            HStack {Image(systemName:"lock");Text("正在阅读备份");Spacer();Text("思考、工具和附件可展开查看")}.font(.caption).foregroundStyle(.secondary).padding(14)
        }.background(paper)
        .task(id:branch){model.readingBranches[sessionID]=branch;generation+=1;loading=false;messages=[];next=0;error=nil;await more()}
        .sheet(isPresented:$showArtifacts){ArtifactLibraryView().environmentObject(model)}
    }
    @MainActor func more() async {
        guard !loading,let offset=next else{return}
        let token=generation, selected=branch
        loading=true;error=nil
        defer{if token==generation {loading=false}}
        do {
            let result=try await model.engine.call("/native/account-reading?id=\(model.escape(sessionID))&branch=\(model.escape(selected))&offset=\(offset)")
            guard token==generation,!Task.isCancelled else{return}
            var items=try decode([Message].self,result["items"] ?? [])
            for i in items.indices{items[i].index=offset+i}
            messages+=items;next=result["next_offset"] as? Int
            branches=try decode([AccountBranch].self,result["branches"] ?? [])
        } catch is CancellationError {} catch {if token==generation {self.error=error.localizedDescription}}
    }
}

struct AccountMessageView:View {
    let message:Message
    var body:some View {
        HStack(alignment:.top,spacing:12) {
            if message.role=="user"{Spacer(minLength:50)}
            VStack(alignment:.leading,spacing:12) {
                if !message.text.isEmpty {
                    if message.role=="assistant" && message.continuation != true {Label("Claude",systemImage:"sparkle").font(.caption.weight(.medium)).foregroundStyle(.secondary)}
                    if message.plain == true {Text(message.text).textSelection(.enabled)} else {MarkdownBody(text:message.text)}
                    Button("复制",systemImage:"doc.on.doc"){copyText(message.text)}.labelStyle(.iconOnly).buttonStyle(.borderless).foregroundStyle(.secondary)
                }
                ForEach(Array((message.media ?? []).enumerated()),id:\.offset){_,media in
                    if let text=media.text,!text.isEmpty {
                        DisclosureGroup {
                            Text(text).font(.system(size:13,design:.monospaced)).textSelection(.enabled).frame(maxWidth:.infinity,alignment:.leading).padding(.top,10)
                            Button("复制内容"){copyText(text)}.buttonStyle(.borderless)
                        } label:{Label(media.name ?? "附件",systemImage:"doc.text").font(.callout)}
                        .padding(12).background(.quaternary.opacity(0.4),in:RoundedRectangle(cornerRadius:10))
                    } else {Label((media.name ?? "附件")+" · 导出中未包含文件内容",systemImage:"paperclip").font(.callout).foregroundStyle(.secondary)}
                }
            }.padding(message.role=="user" ? 16 : 0)
                .background(message.role=="user" ? Color.primary.opacity(0.055) : .clear,in:RoundedRectangle(cornerRadius:16))
            if message.role != "user"{Spacer(minLength:12)}
        }.frame(maxWidth:.infinity,alignment:.leading)
    }
}

struct ArtifactLibraryView:View {
    @EnvironmentObject var model:ArchiveModel
    @Environment(\.dismiss) private var dismiss
    @State private var items:[SavedArtifact]=[]
    @State private var selected:String?
    @State private var version=""
    @State private var content=""
    @State private var next:Int?
    @State private var error:String?
    @State private var loading=false
    var current:SavedArtifact?{items.first{$0.id==selected}}
    var body:some View {
        VStack(spacing:0) {
            HStack{Text("作品库").font(.title2);Text("整份备份中的作品与历史版本").font(.caption).foregroundStyle(.secondary);Spacer();Button("完成"){dismiss()}}.padding(20)
            Divider()
            HSplitView {
                List(items,selection:$selected){item in Text(item.title).tag(item.id)}.frame(minWidth:210,idealWidth:250,maxWidth:330)
                VStack(alignment:.leading,spacing:12) {
                    if let current {
                        Picker("版本",selection:$version){Text("最新版本").tag("");ForEach(current.versions){Text($0.title+" · "+$0.id).tag($0.id)}}
                        Text("文字阅读版 · 保留原始 HTML 在备份中").font(.caption).foregroundStyle(.secondary)
                        ScrollView{Text(content).textSelection(.enabled).frame(maxWidth:.infinity,alignment:.leading).padding(12)}
                        if next != nil {Button("继续读取作品"){Task{await load(append:true)}}}
                    } else {ContentUnavailableView("选择作品",systemImage:"doc.richtext",description:Text(items.isEmpty ? "当前档案未找到作品，请检查是否备份了 frames ZIP。" : "可阅读已保存的内容并切换版本。"))}
                    if loading{ProgressView()}
                    if let error{Text(error).foregroundStyle(.red)}
                }.padding(20).frame(minWidth:400,maxWidth:.infinity)
            }
        }.frame(width:950,height:680)
        .task {do{let data=try await model.engine.call("/native/artifacts");items=try decode([SavedArtifact].self,data["items"] ?? [])}catch{self.error=error.localizedDescription}}
        .onChange(of:selected){_,_ in version=""}
        .task(id:(selected ?? "")+"/"+version){content="";next=nil;await load()}
    }
    @MainActor func load(append:Bool=false) async {
        guard let id=selected else{return}
        let chosen=version;loading=true;error=nil
        defer{if selected==id && version==chosen{loading=false}}
        do {
            let value=try await model.engine.call("/native/artifacts?id=\(model.escape(id))&version=\(model.escape(chosen))&offset=\(append ? next ?? 0 : 0)")
            guard selected==id,version==chosen,!Task.isCancelled else{return}
            content=(append ? content : "")+(value["content"] as? String ?? "");next=value["next_offset"] as? Int
        }catch{if selected==id,version==chosen{self.error=error.localizedDescription}}
    }
}
