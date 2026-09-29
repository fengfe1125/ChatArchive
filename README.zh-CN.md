<p align="center">
  <img src="Design/app-icon-1024.png" alt="聊天档案图标" width="112" />
</p>

# ChatArchive · 聊天档案

**把 Claude 聊天留在自己的 Mac 上，随时翻看。**

聊天档案是一款原生 macOS 应用，用来备份、阅读和整理 Claude 账号导出与 Claude Code 会话。你可以在自己的磁盘上保留一份可阅读的记录，找回以前的回答，打开保存的作品，或准备交接资料，在 Codex 中继续讨论。

[English](README.md) · **简体中文**

[下载 Mac 版](https://github.com/fengfe1125/ChatArchive/releases/latest) · [更新记录](https://github.com/fengfe1125/ChatArchive/releases) · [反馈问题](https://github.com/fengfe1125/ChatArchive/issues)

**运行要求：** Apple 芯片 Mac · macOS 15 及以上。目前应用界面为简体中文。

## 可以做什么

- **集中查看两种聊天。** Chat 展示账号导出的对话，Code 按项目查看 Claude Code 会话，搜索覆盖两个来源。
- **连续阅读。** 上滑自动加载更早消息，下滑自动加载后续消息，不用反复点击。右侧定位条可以预览摘要，跳到任意一条消息，包括尚未加载的内容。
- **保留对话上下文。** 切换备份中的分支和回答版本；按需展开已保存的思考、工具记录和附件提取文本。
- **重新打开作品。** 在侧边面板预览保存的 HTML 作品，使用内嵌交互、查看代码、切换历史版本或保存 HTML。
- **在本地整理。** 重命名、收藏、归档对话。导出缺少正文的记录集中到独立入口，默认聊天列表不再混入空记录。
- **导出或继续讨论。** 导出阅读版 Markdown 或完整记录，也可准备 Codex 交接资料。没有安装 Codex，仍然可以备份和阅读。

## 开始使用

1. [下载最新版 DMG](https://github.com/fengfe1125/ChatArchive/releases/latest)，将 **聊天档案** 拖入 **Applications**。
2. 打开应用，选择聊天来源。
3. 选择本机或外置盘上的备份目录。应用先复制并校验文件，再建立索引。
4. 切换 **Chat** 或 **Code** 开始阅读。

已有档案可以通过 **直接打开已有档案** 打开。备份中断后，可从来源向导恢复任务。

当前发布采用 ad-hoc 临时签名，尚未使用 Developer ID 签名或通过 Apple 公证，macOS 可能阻止首次打开。其他 Mac 的兼容性与 Gatekeeper 行为尚未独立验证。

### 支持哪些来源

| 来源 | 选择的内容 |
| --- | --- |
| Claude 账号导出 | 官方导出 ZIP，保留 `conversations-000.zip` 等原始名称。有作品时一并提供 `frames-000.zip`，无需手动解压。 |
| Claude Code | 包含 `projects` 的目录，通常为 `~/.claude`，也支持已有 Code 备份。 |
| 官方导出下载清单 | manifest JSON 和下载位置。保留下载的 ZIP 并记录 SHA-256；链接失效时需要新清单，或手动下载 ZIP。 |

每次新备份都会生成独立批次。完整的新格式档案可以移到其他磁盘，读取已复制的内容不要求原始来源继续连接。直接打开旧格式 Code 备份时，会保留对原备份的引用；需要搬迁时，请使用复制备份流程。

## 数据如何保存

- **原始记录只读。** 本地名称、收藏和归档状态单独保存，不改写备份原文。
- **缺失内容明确标注。** 没有标题时，根据现有消息、附件名或日期生成可辨认的名称；缺少正文或附件本体时保留提示，不能重建导出中没有的内容。
- **作品隔离预览。** HTML 在禁止网络访问的 WebKit 沙盒中运行，内嵌脚本可支持本地交互，外部依赖可能无法使用。预览状态仅临时保留，不写回原始作品。
- **历史命令不会自动执行。** 转到 Codex 是独立操作，需要配置好 Codex。已创建的 Codex 会话可能仍引用当时交接资料的绝对路径，移动档案不会自动改写这些引用。
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
| `Engine/` | 备份、索引、阅读、导出与 Codex 交接 |
| `Tests/` | Python 与原生 Swift 回归测试 |
| `scripts/` | App 与 DMG 打包 |
| `Design/` | 图标素材与界面说明 |

生成的安装包与私人验证文件不会进入源码仓库。遇到问题可以[提交 Issue](https://github.com/fengfe1125/ChatArchive/issues)，附上应用版本、macOS 版本和复现步骤；示例中的私人对话与下载链接请先脱敏。
