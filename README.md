# ChatArchive

聊天档案 · macOS

A local-first native macOS reader for Claude account exports and Claude Code archives. Requires Apple Silicon and macOS 15 or later.

[Download the latest release](https://github.com/fengfe1125/ChatArchive/releases/latest) · [下载最新版本](https://github.com/fengfe1125/ChatArchive/releases/latest)

SwiftUI / AppKit 原生聊天档案阅读器。支持 Apple 芯片与 macOS 15 及以上。全部聊天原文留在用户选择的档案位置。

## 打开

从 Releases 下载 DMG，将“聊天档案”拖入 Applications。当前版本采用 ad-hoc 签名，未进行 Apple 公证，macOS 可能阻止首次打开。自行构建的输出位于 `dist/聊天档案.app`。首次打开依次进行环境检测、选择来源、选择备份位置和复制校验。Codex 未安装或未登录，不影响备份和阅读。

- 本机来源：选择包含 `projects` 的 Claude Code 目录（通常是 `~/.claude`），或旧备份目录。
- 账号来源：选择官方导出的 ZIP，保留 `conversations-000.zip` 等原始名称。
- 默认使用 Codex 数据目录下的 `chat-archive`，也可更改为本机/外置盘目录；每次生成独立的 `聊天档案-日期-编号` 批次。
- 备份取消、中断或部分失败会保留任务；首次页可恢复，或在新批次中重试。
- “直接打开已有档案”支持新格式档案；旧格式 Code 备份会另行询问工作数据存放目录，不写原文。
- 若旧备份需要同时接入账号 ZIP，先在来源页添加 conversations ZIP，再直接打开 Code 备份。

## 阅读与导入

Chat 浏览账号聊天；Code 展开项目查看会话。搜索覆盖两个来源。右侧检查器提供文件、Write、真实 Edit 片段和原始记录。默认正文隐藏工具和思考内容。会话整行可点击；加载期间显示进度，失败可重试。超长正文和附件分段读取，每段最多 12,000 字符，每页最多 8 段；超长正文按纯文本显示，原始记录和 Markdown 导出保留完整内容。

会话菜单提供标记、单条 Markdown 导出和 Codex 导入；侧栏多选菜单提供批量操作。设置中可导出全部、核对导入状态、迁移旧网站 `data` 目录的 `reviews.json` 和 `imports.json`。

Codex 导入会先说明所选交接内容由已登录 Codex 读取，现有会话跳过；没有可恢复正文的条目不会创建线程。官方 `/import` 仍需用户在终端选择确认。近期批次限同一项目及最多 50 条；清理仅影响本工具创建且哈希未变的暂存副本。

新档案的源文件位置使用相对路径，整份档案可随磁盘搬到另一台 Mac。原始来源未连接不影响已复制档案阅读。旧格式“直接打开”保留对原备份位置的引用；如果需要迁移，请选择复制备份。已创建的 Codex 会话引用导入时的绝对交接路径，不会自动改写旧会话。

## 构建

使用 Xcode 工具链执行：

```sh
python3 scripts/package.py --dmg
```

脚本通过 `ARCHIVE_PYTHON_RUNTIME` 接收可重定位 CPython 3.12 运行环境目录；当前开发机默认采用本地已提供的独立 CPython 3.12.14。运行环境仅打包解释器、标准库及许可证，不包含 site-packages、测试档案或原网站数据。标准库许可见 App 内 `Contents/Resources/Python/lib/python3.12/LICENSE.txt`。

`Package.swift` 可用 Xcode 打开查看/开发 Swift 源码；完整应用运行需要上述打包脚本提供 Resources。

仅监听随机 `127.0.0.1` 端口，使用每次启动生成的令牌和 CSRF 检查。没有网页嵌入或远程 UI。退出 App 会结束后台进程。原始 HTML、代码和命令均作为文字，不执行。

## 验证与分发边界

```sh
PYTHONPATH=Engine python3 -m unittest discover -s Tests -v
```

会话切换回归测试覆盖快速 A → B → A 切换、失败重试和重复分页请求：

```sh
swiftc -module-cache-path /tmp/claude-archive-module-cache -swift-version 5 -parse-as-library -framework SwiftUI -framework AppKit Sources/Models.swift Sources/StartupHandshake.swift Tests/SessionLoadingTests.swift -o /tmp/chatarchive-selection-tests
/tmp/chatarchive-selection-tests --preview-archive /tmp/test
```

私人档案回归记录与本机验证脚本不包含在公开源码或安装包中。

本机构建采用 ad-hoc 签名，尚无 Developer ID 签名或 Apple 公证。部署目标 15.0 和运行环境二进制兼容性检查不等同于 macOS 15 或另一台 Mac 实测通过。跨机器 Gatekeeper 行为、真实安装与续聊需分别验收。

## 官方账号导出下载
来源向导选择 manifest JSON 和下载位置。创建独立下载目录，保留清单与 ZIP，记录 SHA-256。无需手动解压，备份后自动从 ZIP 读取并建立聊天索引。失败项可从原下载目录恢复；一次性链接已失效或需要浏览器登录时需新清单或手动下载 ZIP。清单含私密下载链接，请保留在自己的档案盘。

## 项目目录

- `Sources/`：原生 SwiftUI / AppKit App。
- `Engine/`：随 App 打包的 Python 数据引擎。
- `Tests/`、`scripts/`：测试、构建及验证。
- `Design/`：图标源文件和导出。
- `dist/`：当前 App 和 DMG 安装包。
- `.validation/`：历史测试报告、截图和小型测试数据，禁止提交或分发。


### 账号聊天阅读（1.0.7）

Chat 按原始消息父子关系读取分支，可切换分支或查看全部记录；导出未记录原界面选中状态时，默认展示最后结束的分支。思考、工具调用及结果提供折叠入口，长内容继续分段。原始系统附加上下文仍可在“原始记录”中查看。

“作品库”读取 `frames-000.zip` 中的作品及历史版本，提供文字阅读版，不运行备份 HTML 的脚本。没有原始标题的聊天优先用首条提问命名，其次使用附件名或日期与短编号；这类替代名称不是恢复出的原始标题。标题、正文、附件本体在导出中缺失时会保留明确提示。
