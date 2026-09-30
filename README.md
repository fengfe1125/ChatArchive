<p align="center">
  <img src="Design/app-icon-1024.png" alt="ChatArchive icon" width="112" />
</p>

# ChatArchive

**Switch computers or accounts. Bring the conversations you need.**

ChatArchive (聊天档案) helps you choose which Claude and Claude Code conversations to carry over when switching computers or accounts. Browse a local backup, select the conversations you still need, and continue them in Claude Code or Codex, or prepare files for a new Claude chat. The rest can stay in your archive.

**English** · [简体中文](README.zh-CN.md)

[Download for Mac](https://github.com/fengfe1125/ChatArchive/releases/latest) · [Release notes](https://github.com/fengfe1125/ChatArchive/releases) · [Report an issue](https://github.com/fengfe1125/ChatArchive/issues)

**Requirements:** Apple Silicon · macOS 15 or later. The current app interface is in Simplified Chinese.

## Choose what to carry over

- **Save a local copy.** Back up Claude account exports and Claude Code history before changing computers or accounts.
- **Find what matters.** Read and search old conversations, review their branches and saved artifacts, and choose the ones you want to keep working on.
- **Move selected conversations.** Continue one conversation or select several for a batch. Pick Claude Code, Codex, or files for a new Claude chat as the destination.
- **Keep the rest available.** Unselected conversations stay in the local archive for reading later. Selection does not delete or rewrite the original records.

The current release is **[1.2.2](https://github.com/fengfe1125/ChatArchive/releases/tag/v1.2.2)**, including all three continuation destinations and direct opening in Claude Code Desktop.

## Get started

1. [Download the latest DMG](https://github.com/fengfe1125/ChatArchive/releases/latest) and drag **聊天档案** into **Applications**.
2. Open the app and select your source files.
3. Choose a backup folder on your Mac or an external drive. The app copies and verifies the files before indexing them.
4. Browse **Chat** or **Code**, then select the conversations you want to carry over.
5. Choose **继续这段聊天…** (“Continue this conversation”) and a destination. Use the account you want to continue with in the destination tool.

When moving to another Mac, copy the complete archive folder and open it with **直接打开已有档案** (“Open an existing archive”). You can then choose the conversations to continue. Interrupted backup jobs can be resumed from the setup screen.

The current release is ad-hoc signed, without Developer ID signing or Apple notarization. macOS may block its first launch. Compatibility on another Mac and Gatekeeper behavior have not been independently verified.

### Supported sources

| Source | What to select |
| --- | --- |
| Claude account export | Official export ZIP files, keeping names such as `conversations-000.zip`. Include `frames-000.zip` for saved artifacts. No manual extraction is needed. |
| Claude Code | A directory containing `projects`, usually `~/.claude`, or an existing Code backup. |
| Export download manifest | A manifest JSON and a destination folder. Downloads retain the ZIP files and record SHA-256 hashes; expired links require a new manifest or manually downloaded ZIPs. |

New backups are stored as separate batches. You can move a complete new-format archive to another disk; reading its copied contents does not require the original source to stay connected. Opening a legacy Code backup directly keeps references to that backup, so use the copy workflow when preparing a portable archive.

## Continue a conversation

Choose **继续这段聊天…** (“Continue this conversation”) from the reader, conversation menu, or multiple-selection controls. The app remembers your last destination and tracks each destination separately.

| Destination | Result |
| --- | --- |
| Codex | Creates a conversation using the existing handoff flow; existing conversations are skipped. |
| Claude web / desktop chat | Prepares `transcript.md`, a continuation prompt, and a hash manifest. Open a new Claude chat, upload the transcript, paste the prompt, and send it yourself. **Prepared** means the local files are ready, not that account history was imported. |
| Claude Code | Forks Code history from a JSONL copy, or creates a new session from Chat handoff files. Saves the real session ID and a resume command. Requires version 2.1.285 or newer and terminal login. |

Chat handoffs use the branch selected in the reader; batches use the most recently ended branch. Select a single branch before continuing from the “all original branches” view. Transcripts retain complete readable text, extracted attachment text, and missing-file labels. Large files may need to be uploaded in sections. Thinking, tool, and system records remain in the source archive rather than the readable handoff.

Automatic Claude Code imports send context and use your account allowance. The first turn disables hooks, custom extensions, and MCP. Code restoration has no tools; Chat handoffs allow only reading the handoff files. The CLI's default model is retained. Failed or interrupted creation is checked against the saved files and session ID before retrying; ambiguous attempts are marked for review rather than creating duplicates. View past results or resume jobs in Settings.

Claude Desktop and the CLI keep separate session lists. For a single conversation, **完成后在 Claude 桌面打开** (“Open in Claude Desktop when finished”) is enabled by default and remembers your choice. Batch imports offer a separate open button for each result. **复制桌面打开命令** copies a command with `--desktop`. After import, click **在 Claude Code 桌面打开** (“Open in Claude Code Desktop”) in the result to open the saved session and its history in the desktop Code tab. **复制终端续聊命令** copies a command for continuing in the terminal. The desktop resume picker can omit sessions created by automated CLI imports; the direct open button uses the same local handoff as `claude --desktop --resume <id>`.

[Claude export limitations](https://support.claude.com/en/articles/9450526-export-your-claude-data) · [Claude Code CLI](https://code.claude.com/docs/en/cli-reference)

## Your files stay yours

- Original backup records are read-only. Local names, stars, and archive status are stored separately.
- Missing titles use a label based on available message text, attachment names, or dates. Missing body text and attachment files are marked explicitly; the app cannot recreate content absent from an export.
- Artifact previews run in an isolated WebKit sandbox with network access blocked. Embedded scripts can support local interactions; external dependencies may not work. Preview state is temporary and is not written back to the saved artifact.
- Reading a saved command does not execute it. Creating a continuation session is an explicit action and requires the target tool to be configured. Existing sessions can retain absolute handoff paths even if you later move the archive.
- Export manifests may contain private download links. Keep them with your private backup files.

ChatArchive is an independent archive reader, not an official Claude client. It does not provide live Claude generation or recreate the signed-in desktop app in full. If an export does not identify its active branch, the reader defaults to the branch that ended most recently.

## Build from source

The app uses **SwiftUI and AppKit**, with a bundled **Python 3.12** data engine and **WebKit** for artifact previews.

You need the Xcode command-line tools, Python 3 to run the build script, and a relocatable Apple Silicon CPython 3.12 runtime:

```sh
export ARCHIVE_PYTHON_RUNTIME="/absolute/path/to/standalone-python"
python3 scripts/package.py --dmg
```

The runtime directory must contain `bin/python3.12` and `lib/python3.12`. Without the environment variable, the script looks in the developer's local Codex runtime cache; that default may not exist on your machine. The build rejects Homebrew and user-directory dynamic library dependencies in the packaged binaries.

Outputs: `dist/聊天档案.app` and `dist/聊天档案.dmg`. The package includes the Python interpreter, standard library, and license, but excludes `site-packages` and private archives. The Python license is included at `Contents/Resources/Python/lib/python3.12/LICENSE.txt`.

`Package.swift` can be opened in Xcode for Swift development. Running the complete app requires the resources assembled by the packaging script. The data engine listens only on a random loopback port, uses a per-launch token and CSRF checks, and stops when the app exits.

### Tests

```sh
PYTHONPATH=Engine python3 -m unittest discover -s Tests -v
```

Native regression tests cover rapid conversation switching, message navigation, failed-page retry, and duplicate-request suppression:

```sh
swiftc -module-cache-path /tmp/chatarchive-module-cache \
  -swift-version 5 -parse-as-library -framework SwiftUI -framework AppKit \
  Sources/Models.swift Sources/StartupHandshake.swift Tests/SessionLoadingTests.swift \
  -o /tmp/chatarchive-selection-tests
/tmp/chatarchive-selection-tests --preview-archive /tmp/test
```

### Project layout

| Directory | Contents |
| --- | --- |
| `Sources/` | Native macOS interface and application state |
| `Engine/` | Backup, indexing, reading, export, and destination handoffs |
| `Tests/` | Python and native Swift regression tests |
| `scripts/` | App and DMG packaging |
| `Design/` | App icon assets and interface notes |

Generated packages and private validation files are excluded from source control. For bugs, [open an issue](https://github.com/fengfe1125/ChatArchive/issues) with your app version, macOS version, and reproduction steps. Redact private conversation text and download links before attaching examples.
