import SwiftUI
import WebKit
import AppKit

// The original document lives in an opaque iframe with no host API or network.
struct ArtifactWebPreview:NSViewRepresentable {
    let html:String
    func makeCoordinator()->Coordinator{Coordinator()}
    func makeNSView(context:Context)->WKWebView {
        let config=WKWebViewConfiguration()
        config.websiteDataStore = .nonPersistent()
        let view=WKWebView(frame:.zero,configuration:config)
        view.navigationDelegate=context.coordinator
        return view
    }
    func updateNSView(_ view:WKWebView,context:Context) {
        guard context.coordinator.lastHTML != html else{return}
        context.coordinator.lastHTML=html
        let policy="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; media-src data: blob:; font-src data:; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'"
        let compatibility = """
        <script>
        document.addEventListener('click',function(event){
          const anchor=event.target.closest && event.target.closest('a[href^="#"]');
          if(!anchor)return;
          event.preventDefault();
          const key=anchor.getAttribute('href').slice(1);
          const target=document.getElementById(decodeURIComponent(key));
          if(target)target.scrollIntoView({behavior:'auto',block:'start'});
        },true);
        for(const name of ['localStorage','sessionStorage']){
          try{void window[name].length;}catch(error){
            const values=new Map();
            const storage={getItem:k=>values.has(String(k))?values.get(String(k)):null,setItem:(k,v)=>values.set(String(k),String(v)),removeItem:k=>values.delete(String(k)),clear:()=>values.clear(),key:i=>Array.from(values.keys())[i]||null,get length(){return values.size}};
            Object.defineProperty(window,name,{value:storage});
          }
        }
        </script>
        """
        let document="<meta http-equiv=\"Content-Security-Policy\" content=\"\(policy)\">"+compatibility+html
        let escaped=document.replacingOccurrences(of:"&",with:"&amp;").replacingOccurrences(of:"\"",with:"&quot;").replacingOccurrences(of:"<",with:"&lt;").replacingOccurrences(of:">",with:"&gt;")
        let wrapper="<html><head><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; frame-src about:;\"><style>html,body,iframe{margin:0;width:100%;height:100%;border:0;display:block}</style></head><body><iframe title=\"作品预览\" sandbox=\"allow-scripts\" srcdoc=\"\(escaped)\"></iframe></body></html>"
        view.loadHTMLString(wrapper,baseURL:nil)
    }
    final class Coordinator:NSObject,WKNavigationDelegate {
        var lastHTML:String?
        func webView(_ webView:WKWebView,decidePolicyFor action:WKNavigationAction,decisionHandler:@escaping(WKNavigationActionPolicy)->Void){
            let url=action.request.url
            decisionHandler(url?.scheme == "about" ? .allow : .cancel)
        }
    }
}

struct ArtifactPanel:View {
    @EnvironmentObject var model:ArchiveModel
    let artifact:SavedArtifact
    var close:()->Void
    @State private var version=""
    @State private var mode=0
    @State private var html=""
    @State private var error:String?
    @State private var loading=false
    @State private var expanded=false
    var body:some View {
        VStack(spacing:0) {
            HStack(spacing:12){Image(systemName:"doc.richtext").foregroundStyle(.secondary);Text(artifact.title).font(.headline).lineLimit(1);Spacer();Button{expanded=true}label:{Image(systemName:"arrow.up.left.and.arrow.down.right")}.help("展开预览");Button(action:close){Image(systemName:"xmark")}.help("关闭作品")}.buttonStyle(.plain).padding(18)
            HStack{Picker("显示",selection:$mode){Text("预览").tag(0);Text("代码").tag(1)}.pickerStyle(.segmented).frame(width:145);Spacer();Menu{Button("复制 HTML"){copyText(html)};Button("保存 HTML…"){save()}}label:{Image(systemName:"square.and.arrow.down")}.disabled(html.isEmpty)}.padding(.horizontal,16).padding(.bottom,12)
            Divider()
            ZStack {
                if mode==0 {ArtifactWebPreview(html:html)}else{NativeCodeText(text:html)}
                if loading{ProgressView("正在打开作品…").padding().background(.regularMaterial,in:RoundedRectangle(cornerRadius:12))}
                if let error{Text(error).foregroundStyle(.red).padding()}
            }
            Divider()
            HStack{Picker("版本",selection:$version){Text("当前版本").tag("");ForEach(Array(artifact.versions.enumerated()),id:\.element.id){i,v in Text("版本 \(artifact.versions.count-i) · \(v.id)").tag(v.id)}}.labelsHidden();Spacer();Text("本地预览").font(.caption).foregroundStyle(.secondary)}.padding(12)
        }.background(Color(nsColor:.windowBackgroundColor))
        .task(id:artifact.id+"/"+version){await load()}
        .sheet(isPresented:$expanded){VStack{HStack{Text(artifact.title).font(.headline);Spacer();Button("完成"){expanded=false}}.padding();ArtifactWebPreview(html:html)}.frame(minWidth:900,minHeight:700)}
    }
    @MainActor func load() async {
        let chosen=version;loading=true;error=nil
        defer{if chosen==version{loading=false}}
        do{let result=try await model.engine.call("/native/artifact-preview?id=\(model.escape(artifact.id))&version=\(model.escape(chosen))");guard chosen==version,!Task.isCancelled else{return};html=result["html"] as? String ?? ""}catch{if chosen==version{self.error=error.localizedDescription}}
    }
    func save(){let panel=NSSavePanel();panel.nameFieldStringValue=String(artifact.title.prefix(80)).replacingOccurrences(of:"/",with:"-")+".html";panel.allowedContentTypes=[.html];if panel.runModal() == .OK,let url=panel.url{do{try html.write(to:url,atomically:true,encoding:.utf8)}catch{self.error=error.localizedDescription}}}
}
