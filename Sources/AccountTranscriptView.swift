import SwiftUI

private struct SavedTurn:Identifiable {
    let id:String
    var pieces:[Message]
    var role:String{pieces.first?.role ?? "assistant"}
    var versions:[MessageVersion]{pieces.first?.versions ?? []}
    var versionIndex:Int{pieces.first?.version_index ?? 0}
}

struct AccountTranscriptView:View {
    @EnvironmentObject var model:ArchiveModel
    let sessionID:String
    let onArtifact:(SavedArtifact)->Void
    @State private var messages:[Message]=[]
    @State private var branches:[AccountBranch]=[]
    @State private var related:[SavedArtifact]=[]
    @State private var branch=""
    @State private var previous:Int?
    @State private var next:Int?
    @State private var loading=false
    @State private var error:String?
    @State private var generation=0
    @State private var bottomRequest=0
    @State private var position:String?
    @State private var nearBottom=false
    @State private var locations:[MessageLocation]=[]
    @State private var jumpTarget:String?

    private var turns:[SavedTurn]{
        var result:[SavedTurn]=[]
        for m in messages{let key=m.message_id ?? m.id;if result.last?.id==key{result[result.count-1].pieces.append(m)}else{result.append(SavedTurn(id:key,pieces:[m]))}}
        return result
    }
    var body:some View {
        VStack(spacing:0){
            ScrollViewReader{proxy in
                HStack(spacing:0){
                ScrollView{
                    LazyVStack(alignment:.leading,spacing:28){
                        if previous != nil{Button("显示更早的消息"){Task{await load(offset:previous ?? 0,prepend:true)}}.buttonStyle(.plain).font(.caption).foregroundStyle(.secondary).frame(maxWidth:.infinity).disabled(loading)}
                        if loading && messages.isEmpty{ProgressView("正在读取对话…").frame(maxWidth:.infinity).padding(32)}
                        ForEach(turns){turn in
                            turnView(turn).id(turn.id)
                        }
                        if !related.isEmpty{
                            VStack(alignment:.leading,spacing:8){Text("这段对话中的作品").font(.caption).foregroundStyle(.secondary);ForEach(related){item in Button{onArtifact(item)}label:{HStack{Image(systemName:"doc.richtext").font(.title2);VStack(alignment:.leading,spacing:4){Text(item.title).font(.callout.weight(.medium));Text("点击打开作品").font(.caption).foregroundStyle(.secondary)};Spacer();Image(systemName:"arrow.up.right")}.padding(16).background(Color.primary.opacity(0.035),in:RoundedRectangle(cornerRadius:12)).overlay(RoundedRectangle(cornerRadius:12).stroke(Color.primary.opacity(0.1)))}.buttonStyle(.plain)}}
                        }
                        if let error{Text(error).foregroundStyle(.red);Button("重试"){Task{await load(offset:messages.isEmpty ? -1 : next ?? 0)}}}
                        if loading && !messages.isEmpty{ProgressView().controlSize(.small).frame(maxWidth:.infinity)}
                        if messages.isEmpty && !loading && error==nil{ContentUnavailableView("导出中缺少正文",systemImage:"doc.questionmark",description:Text("这条记录只有标题、时间或附件信息。可从会话菜单核对原始记录。"))}
                        Color.clear.frame(height:1).id("bottom")
                    }.scrollTargetLayout().padding(.horizontal,36).padding(.top,30).padding(.bottom,16).frame(maxWidth:780).frame(maxWidth:.infinity)
                }
                .scrollPosition(id:$position,anchor:.top)
                .onScrollGeometryChange(for:Bool.self){geometry in
                    geometry.contentSize.height-geometry.visibleRect.maxY < 900
                }action:{_,value in nearBottom=value}
                .onChange(of:nearBottom){_,_ in loadAhead()}
                .onChange(of:loading){_,value in if !value{loadAhead()}}
                .onChange(of:jumpTarget){_,value in if let value{proxy.scrollTo(value,anchor:.top)}}
                .onChange(of:bottomRequest){_,_ in proxy.scrollTo("bottom",anchor:.bottom)}
                .overlay(alignment:.bottomTrailing){Button{Task{if next != nil{await load(offset:-1,replace:true)};bottomRequest+=1}}label:{Image(systemName:"arrow.down").frame(width:32,height:32).background(.regularMaterial,in:Circle()).overlay(Circle().stroke(Color.primary.opacity(0.1)))}.buttonStyle(.plain).help("跳到最新消息").padding(18)}
                if !locations.isEmpty{MessageNavigationRail(items:locations,current:locations.contains(where:{$0.id==position}) ? position : messages.last?.message_id,loading:loading){item in
                    Task{await load(offset:item.offset,replace:true);guard messages.first?.index==item.offset else{return};jumpTarget=nil;jumpTarget=item.id;position=item.id}
                }}
                }
            }
            VStack(spacing:8){
                HStack{
                    if branches.count>1{Menu{Button("最近结束的分支"){branch=""};ForEach(branches){b in Button(b.title){branch=b.id}};Divider();Button("全部原始分支"){branch="all"}}label:{Label("\(branches.count) 个分支",systemImage:"arrow.triangle.branch")}.font(.caption).help("导出未保存当时选中的分支，默认选择最后结束的分支")}
                    Spacer();Text("本地历史记录").font(.caption).foregroundStyle(.secondary)
                }
                HStack(alignment:.center,spacing:12){Text("继续这段对话").foregroundStyle(.secondary);Spacer();Button{if let row=model.active{model.pendingImports=[row.id];model.confirmImport=true}}label:{HStack{Text("转到 Codex");Image(systemName:"arrow.up")}.font(.callout).padding(.horizontal,12).padding(.vertical,8).background(Color.primary.opacity(0.07),in:Capsule())}.buttonStyle(.plain).disabled(model.active?.readable != true || model.taskRunning)}.padding(18).background(Color.primary.opacity(0.025),in:RoundedRectangle(cornerRadius:20)).overlay(RoundedRectangle(cornerRadius:20).stroke(Color.primary.opacity(0.12)))
            }.padding(.horizontal,32).padding(.bottom,14).frame(maxWidth:800).frame(maxWidth:.infinity)
        }
        .task(id:branch){
            generation+=1;loading=false;messages=[];locations=[];previous=nil;next=nil;position=nil;jumpTarget=nil
            await load(offset:-1);bottomRequest+=1
            do{let data=try await model.engine.call("/native/reading-navigation?id=\(model.escape(sessionID))&branch=\(model.escape(branch))");try Task.checkCancellation();locations=try decode([MessageLocation].self,data["items"] ?? [])}
            catch is CancellationError{}catch{self.error=error.localizedDescription}
        }
    }
    private func loadAhead(){
        guard nearBottom,!loading,error==nil,let offset=next else{return}
        Task{await load(offset:offset)}
    }
    private func turnView(_ turn:SavedTurn)->some View {
        HStack(alignment:.top){if turn.role=="user"{Spacer(minLength:72)}
            VStack(alignment:.leading,spacing:16){
                if turn.role != "user" {Image(systemName:"asterisk").font(.system(size:22,weight:.medium)).foregroundStyle(Color(red:0.72,green:0.42,blue:0.29))}
                ForEach(turn.pieces){piece in
                    if !piece.text.isEmpty {if piece.plain==true{Text(piece.text).textSelection(.enabled)}else{MarkdownBody(text:piece.text).equatable()}}
                    ForEach(Array((piece.media ?? []).enumerated()),id:\.offset){_,media in mediaView(media)}
                }
                HStack(spacing:14){
                    Button{copyText(turn.pieces.map(\.text).filter{!$0.isEmpty}.joined(separator:"\n\n"))}label:{Image(systemName:"doc.on.doc")}.help("复制已显示的回答")
                    if turn.versions.count>1{
                        Button{branch=turn.versions[turn.versionIndex-1].id}label:{Image(systemName:"chevron.left")}.disabled(turn.versionIndex==0)
                        Text("\(turn.versionIndex+1) / \(turn.versions.count)").monospacedDigit()
                        Button{branch=turn.versions[turn.versionIndex+1].id}label:{Image(systemName:"chevron.right")}.disabled(turn.versionIndex+1>=turn.versions.count)
                    }
                }.font(.system(size:12)).foregroundStyle(.secondary).buttonStyle(.plain)
            }.font(.system(size:16,design:turn.role=="assistant" ? .serif:.default))
                .frame(maxWidth:turn.role=="user" ? 560:.infinity,alignment:.leading)
                .padding(turn.role=="user" ? 18:0)
                .background(turn.role=="user" ? Color.primary.opacity(0.055):.clear,in:RoundedRectangle(cornerRadius:18))

        }
    }
    @ViewBuilder private func mediaView(_ media:Media)->some View {
        if let text=media.text,!text.isEmpty {
            DisclosureGroup{
                ScrollView{Text(text).font(.system(size:12,design:.monospaced)).textSelection(.enabled).frame(maxWidth:.infinity,alignment:.leading).padding(12)}.frame(maxHeight:300)
                Button("复制"){copyText(text)}.buttonStyle(.plain).font(.caption)
            }label:{HStack{Image(systemName:media.type=="thinking" ? "sparkle":"terminal");Text(media.name ?? "附件").lineLimit(1)}}.font(.system(size:13)).foregroundStyle(.secondary).padding(12).background(Color.primary.opacity(0.025),in:RoundedRectangle(cornerRadius:9))
        }else{Label((media.name ?? "附件")+" · 导出未包含文件本体",systemImage:"paperclip").font(.system(size:13)).foregroundStyle(.secondary).padding(12).overlay(RoundedRectangle(cornerRadius:9).stroke(Color.primary.opacity(0.12)))}
    }
    @MainActor private func load(offset:Int,prepend:Bool=false,replace:Bool=false) async {
        if replace{generation+=1}else if loading{return};let token=generation;loading=true;error=nil
        defer{if token==generation{loading=false}}
        do{
            let data=try await model.engine.call("/native/account-reading?id=\(model.escape(sessionID))&branch=\(model.escape(branch))&offset=\(offset)")
            guard generation==token,!Task.isCancelled else{return}
            var items=try decode([Message].self,data["items"] ?? []);let start=data["start_offset"] as? Int ?? 0
            for i in items.indices{items[i].index=start+i}
            if replace{messages=items;previous=data["previous_offset"] as? Int;next=data["next_offset"] as? Int}
            else if prepend{let first=messages.first?.index ?? Int.max;messages=items.filter{$0.index<first}+messages;previous=data["previous_offset"] as? Int}else{messages+=items;next=data["next_offset"] as? Int;if messages.count==items.count{previous=data["previous_offset"] as? Int}}
            branches=try decode([AccountBranch].self,data["branches"] ?? []);related=try decode([SavedArtifact].self,data["artifacts"] ?? [])
        }catch is CancellationError{}catch{if token==generation && !Task.isCancelled{self.error=error.localizedDescription}}
    }
}
