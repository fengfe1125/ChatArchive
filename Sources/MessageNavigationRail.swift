import SwiftUI

struct MessageLocation:Decodable,Identifiable {
    let id:String
    let offset:Int
    let role:String
    let preview:String
}

/// Separate from transcript layout: navigation loads only a small window of text.
struct MessageNavigationRail:View {
    let items:[MessageLocation]
    let current:String?
    let loading:Bool
    let select:(MessageLocation)->Void
    @State private var hovered:String?
    var body:some View {
        ScrollViewReader{proxy in
            ScrollView(.vertical){
                LazyVStack(spacing:2){
                    ForEach(Array(items.enumerated()),id:\.element.id){ordinal,item in
                        Button{select(item)}label:{
                            Rectangle().fill(Color.primary.opacity(current==item.id ? 0.75 : hovered==item.id ? 0.5 : 0.2))
                                .frame(width:current==item.id || hovered==item.id ? 17:11,height:3)
                                .frame(width:32,height:18).contentShape(Rectangle())
                        }.buttonStyle(.plain).id(item.id)
                            .onHover{hovered=$0 ? item.id:nil}
                            .help("第 \(ordinal+1) 条 · \(item.role=="user" ? "你":"Claude")\n\(item.preview)")
                            .accessibilityLabel("跳到第 \(ordinal+1) 条消息，\(item.role=="user" ? "你":"Claude")：\(item.preview)")
                            .accessibilityValue(current==item.id ? "当前位置":"")
                    }
                }.padding(.vertical,16)
            }.scrollIndicators(.hidden)
                .onChange(of:current){_,value in if let value{proxy.scrollTo(value,anchor:.center)}}
        }.frame(width:36).overlay(alignment:.top){if loading{ProgressView().controlSize(.mini)}}
            .accessibilityLabel("对话定位")
    }
}
