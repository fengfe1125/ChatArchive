import SwiftUI
import AppKit

struct ImportView:View {
    @EnvironmentObject var model:ArchiveModel
    var body:some View {
        VStack(alignment:.leading,spacing:18){
            Text("继续这段聊天").font(.title2)
            Text("已选择 \(model.pendingImports.count) 条聊天").foregroundStyle(.secondary)
            Picker("目的地",selection:$model.importDestination){ForEach(ImportDestination.allCases){Text($0.title).tag($0)}}
            Text(explanation).font(.callout).fixedSize(horizontal:false,vertical:true)
            if model.importDestination == .claudeCode {
                LabeledContent("Claude Code",value:model.claudeCode["version"] ?? "待检测")
                LabeledContent("状态",value:model.claudeCode["interface"] ?? "待检测")
                Button("重新检测"){model.perform{try await model.detectClaude()}}.disabled(model.detecting)
                if model.pendingImports.count==1 {
                    Toggle("完成后在 Claude 桌面打开",isOn:$model.openClaudeDesktopAfterImport)
                }else {
                    Text("批量导入完成后，在每条结果中点击“在 Claude Code 桌面打开”。").font(.caption).foregroundStyle(.secondary)
                }
            }
            if model.importDestination != .codex,model.pendingBranches.values.contains("all"){
                Text("当前显示全部分支，请回到阅读页选择一个分支。").foregroundStyle(.orange)
            }
            HStack{Button("取消"){model.confirmImport=false};Spacer();Button(model.importDestination == .claudeChat ? "准备 Claude 续聊资料" : "创建续聊会话"){model.perform{try await model.submitImport()}}.buttonStyle(.borderedProminent).disabled(model.taskRunning || model.pendingImports.isEmpty || (model.importDestination != .codex && model.pendingBranches.values.contains("all")))}
        }.padding(24).frame(width:530)
    }
    var explanation:String {
        switch model.importDestination {
        case .codex:return "由已登录的 Codex 读取交接内容并创建续聊会话。已有会话会跳过，历史命令不会自动执行。"
        case .claudeChat:return "生成完整聊天正文与续聊提示。你可以在 Claude 网页或桌面端的新聊天中上传正文、粘贴提示并发送。这里完成后显示“已准备资料”。"
        case .claudeCode:return "Code 备份恢复为新的 Claude Code 本机会话；Chat 备份通过交接资料新建会话。可在完成后直接打开 Claude 桌面，或复制命令到终端续聊。首轮会发送上下文并使用账号额度，只确认上下文，历史命令不会自动执行。需要 Claude Code 2.1.285 或更新版本。"
        }
    }
}

struct ImportResultView:View {
    let row:[String:Any]
    @State private var desktopError:String?
    var status:String {
        let value=row["status"] as? String ?? "completed"
        if row["destination"] as? String == "claude_code",["completed","existing"].contains(value){return value == "completed" ? "已创建本机会话" : "已有本机会话"}
        return ["prepared":"已准备资料","completed":"已创建会话","existing":"已有会话","skipped":"已跳过","needs_review":"需核对","creating":"正在创建","ready":"已准备资料"][value] ?? value
    }
    var body:some View {
        VStack(alignment:.leading,spacing:8){
            Text(row["title"] as? String ?? row["id"] as? String ?? "聊天").font(.headline)
            Text(status).foregroundStyle(.secondary)
            if let id=row["session_id"] as? String ?? row["thread_id"] as? String {Text(id).font(.caption.monospaced()).textSelection(.enabled)}
            if let directory=row["directory"] as? String {
                Button("在 Finder 显示资料"){NSWorkspace.shared.selectFile(nil,inFileViewerRootedAtPath:directory)}
            }
            if row["destination"] as? String == "claude_chat" {
                HStack{
                    Button("打开 Claude 网页"){NSWorkspace.shared.open(URL(string:"https://claude.ai/new")!)}
                    if let prompt=row["prompt"] as? String{Button("复制续聊提示"){copyText(prompt)}}
                }
                Text("在新聊天上传 transcript.md，粘贴提示后发送。长聊天可按需要选择片段；完整正文始终保留在资料目录。").font(.caption).foregroundStyle(.secondary)
            }
            if let url=claudeDesktopResumeURL(row) {
                Button("在 Claude Code 桌面打开"){
                    desktopError=NSWorkspace.shared.open(url) ? nil : "无法打开 Claude 桌面应用。请安装 Claude 桌面，或复制命令到终端续聊。"
                }
                Text("本地 CLI 会话不会自动出现在桌面列表。点击打开后，Claude 会将它加入 Code 列表并显示历史消息。").font(.caption).foregroundStyle(.secondary)
            }
            if let command=row["resume_command"] as? String {Button("复制终端续聊命令"){copyText(command)}}
            if let command=claudeDesktopResumeCommand(row){Button("复制桌面打开命令"){copyText(command)}}
            if let desktopError {Text(desktopError).font(.caption).foregroundStyle(.red)}
            if let path=row["session_path"] as? String{Text(path).font(.caption).foregroundStyle(.secondary).textSelection(.enabled)}
        }.frame(maxWidth:.infinity,alignment:.leading)
    }
}
