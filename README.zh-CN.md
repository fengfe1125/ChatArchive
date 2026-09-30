<p align="center">
  <img src="Design/app-icon-1024.png" alt="聊天档案图标" width="112" />
</p>

# ChatArchive · 聊天档案

**换电脑、换账号，把需要的聊天带过去。**

换电脑或换账号时，有些聊天还需要继续，有些已经用不上。聊天档案让你先备份、阅读和筛选 Claude 与 Claude Code 的记录，再把需要的对话带到 Claude Code 或 Codex，或为新的 Claude 聊天准备续聊资料。其余记录留在本地档案里，以后仍可翻看。

[English](README.md) · **简体中文**

[下载 Mac 版](https://github.com/fengfe1125/ChatArchive/releases/latest) · [更新记录](https://github.com/fengfe1125/ChatArchive/releases) · [反馈问题](https://github.com/fengfe1125/ChatArchive/issues)

**运行要求：** Apple 芯片 Mac · macOS 15 及以上。目前应用界面为简体中文。

## 选择需要的内容，再迁移

- **先留一份备份。** 换电脑或换账号前，将 Claude 账号导出与 Claude Code 历史保存在自己的磁盘上。
- **找出还需要的聊天。** 搜索、阅读旧对话，查看分支和保存的作品，再决定哪些要继续使用。
- **只带走选中的对话。** 可以选择一条或多条，导入 Claude Code、Codex，或为新的 Claude 聊天准备资料。
- **其他记录仍可保留。** 没选中的聊天留在本地档案里；筛选和导入不会删除或改写备份原文。

当前源码版本为 **1.2.2**，GitHub 最新发布的安装包为 **1.1.4**。下文的 Claude 续聊目的地已包含在源码版本中，尚未发布新的 DMG。

## 开始使用

1. [下载最新版 DMG](https://github.com/fengfe1125/ChatArchive/releases/latest)，将 **聊天档案** 拖入 **Applications**。
2. 打开应用，选择聊天来源。
3. 选择本机或外置盘上的备份目录。应用先复制并校验文件，再建立索引。
4. 在 **Chat** 或 **Code** 中阅读，选出需要带走的聊天。
5. 点击 **继续这段聊天…**，选择目的地，并在目标工具中使用你准备继续使用的账号。

换到另一台 Mac 时，复制完整的档案目录，通过 **直接打开已有档案** 打开，再选择需要继续的聊天。备份中断后，可从来源向导恢复任务。

当前发布采用 ad-hoc 临时签名，尚未使用 Developer ID 签名或通过 Apple 公证，macOS 可能阻止首次打开。其他 Mac 的兼容性与 Gatekeeper 行为尚未独立验证。

### 支持哪些来源

| 来源 | 选择的内容 |
| --- | --- |
| Claude 账号导出 | 官方导出 ZIP，保留 `conversations-000.zip` 等原始名称。有作品时一并提供 `frames-000.zip`，无需手动解压。 |
| Claude Code | 包含 `projects` 的目录，通常为 `~/.claude`，也支持已有 Code 备份。 |
| 官方导出下载清单 | manifest JSON 和下载位置。保留下载的 ZIP 并记录 SHA-256；链接失效时需要新清单，或手动下载 ZIP。 |

每次新备份都会生成独立批次。完整的新格式档案可以移到其他磁盘，读取已复制的内容不要求原始来源继续连接。直接打开旧格式 Code 备份时，会保留对原备份的引用；需要搬迁时，请使用复制备份流程。

## 继续这段聊天

从阅读页、聊天菜单或多选操作点击 **继续这段聊天…**，选择目的地。应用记住上次选择，三个目的地的状态独立保存。

| 目的地 | 操作与完成状态 |
| --- | --- |
| Codex | 沿用现有交接方式创建续聊会话；已存在的会话跳过。 |
| Claude 网页／桌面聊天 | 生成 `transcript.md`、续聊提示和哈希清单，显示 **已准备资料**。打开 Claude 新聊天后，手动上传正文、粘贴提示并发送。应用不会自动上传，也不会导回账号历史列表。 |
| Claude Code | Code 历史通过 JSONL 副本恢复并分叉为新会话；Chat 历史通过交接资料新建会话。完成后保存会话 ID 和恢复命令。需要 2.1.285 或更新版本，并在终端完成登录。 |

Chat 续聊使用阅读页选中的分支；批量默认使用最近结束的分支。显示“全部原始分支”时，请先选一个分支。正文保持完整，附件仅保留已有提取文本和缺失说明；长资料可能需要在 Claude 中按片段上传。思考、工具和系统记录保留在原始档案中，不放入普通续聊正文。

Claude Code 自动导入会发送上下文并使用账号额度。首轮禁用 hooks、自定义扩展和 MCP；Code 恢复不允许工具调用，Chat 交接仅允许读取资料。模型使用 CLI 默认设置。失败或中断后先核对任务中保存的资料与会话 ID，不自动创建第二份不确定的会话；可在设置里查看任务结果并恢复。普通 Claude 的状态仅证明本地资料已准备好。

Claude 桌面与 CLI 使用独立的会话列表。单条导入默认勾选**完成后在 Claude 桌面打开**，并记住选择；批量导入在结果中逐条打开。**复制桌面打开命令**会复制带 `--desktop` 的命令。导入完成后，点击结果中的**在 Claude Code 桌面打开**，会将已保存的会话及历史打开到桌面 Code 页；**复制终端续聊命令**用于在终端继续。桌面的恢复选择器可能不显示自动导入创建的会话，直接打开按钮使用与 `claude --desktop --resume <id>` 相同的本机交接入口。

[Claude 官方导出限制](https://support.claude.com/en/articles/9450526-export-your-claude-data) · [Claude Code CLI](https://code.claude.com/docs/en/cli-reference)

## 数据如何保存

- **原始记录只读。** 本地名称、收藏和归档状态单独保存，不改写备份原文。
- **缺失内容明确标注。** 没有标题时，根据现有消息、附件名或日期生成可辨认的名称；缺少正文或附件本体时保留提示，不能重建导出中没有的内容。
- **作品隔离预览。** HTML 在禁止网络访问的 WebKit 沙盒中运行，内嵌脚本可支持本地交互，外部依赖可能无法使用。预览状态仅临时保留，不写回原始作品。
- **历史命令不会自动执行。** 创建续聊会话是独立操作，需要配置好目标工具。已创建的会话可能仍引用当时交接资料的绝对路径，移动档案不会自动改写这些引用。
- **下载清单也属于私人资料。** 清单可能包含私密下载链接，请和备份一起妥善保存。

聊天档案是独立的历史阅读工具，并非 Claude 官方客户端。它不提供在线 Claude 生成，也不完整重建登录后的桌面客户端。导出未记录当时选中的分支时，默认展示最后结束的分支。

## 从源码构建

应用使用 **SwiftUI / AppKit** 构建界面，随包提供 **Python 3.12** 数据引擎，并使用 **WebKit** 预览作品。

需要 Xcode 命令行工具、用于运行构建脚本的 Python 3，以及可重定位的 Apple 芯片 CPython 3.12 运行环境：

```sh
export ARCHIVE_PYTHON_RUNTIME="/absolute/path/to/standalone-python"
python3 scripts/package.py --dmg
```

运行环境目录必须包含 `bin/python3.12` 和 `lib/python3.12`。未设置环境变量时，脚本会查找开发机的 Codex 运行环境缓存，这个默认位置在你的机器上可能不存在。打包时会检查二进制，拒绝依赖 Homebrew 或用户目录中的动态库。

构建输出为 `dist/聊天档案.app` 与 `dist/聊天档案.dmg`。安装包包含 Python 解释器、标准库及许可文件，不包含 `site-packages` 或私人聊天档案。Python 许可位于 App 内 `Contents/Resources/Python/lib/python3.12/LICENSE.txt`。

可以用 Xcode 打开 `Package.swift` 开发 Swift 源码；完整运行仍需打包脚本组装 Resources。数据引擎仅监听随机本机回环端口，使用每次启动生成的令牌与 CSRF 检查，退出应用时结束。

### 测试

```sh
PYTHONPATH=Engine python3 -m unittest discover -s Tests -v
```

原生回归测试覆盖快速切换会话、消息定位、失败重试及重复分页请求：

```sh
swiftc -module-cache-path /tmp/chatarchive-module-cache \
  -swift-version 5 -parse-as-library -framework SwiftUI -framework AppKit \
  Sources/Models.swift Sources/StartupHandshake.swift Tests/SessionLoadingTests.swift \
  -o /tmp/chatarchive-selection-tests
/tmp/chatarchive-selection-tests --preview-archive /tmp/test
```

### 项目目录

| 目录 | 内容 |
| --- | --- |
| `Sources/` | 原生 macOS 界面与应用状态 |
| `Engine/` | 备份、索引、阅读、导出与多目的地交接 |
| `Tests/` | Python 与原生 Swift 回归测试 |
| `scripts/` | App 与 DMG 打包 |
| `Design/` | 图标素材与界面说明 |

生成的安装包与私人验证文件不会进入源码仓库。遇到问题可以[提交 Issue](https://github.com/fengfe1125/ChatArchive/issues)，附上应用版本、macOS 版本和复现步骤；示例中的私人对话与下载链接请先脱敏。
