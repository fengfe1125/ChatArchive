<p align="center">
  <img src="Design/app-icon-1024.png" alt="ChatArchive icon" width="112" />
</p>

# ChatArchive

**Keep your Claude conversations. Read them on your Mac.**

ChatArchive (聊天档案) is a native macOS app for backing up, browsing, and organizing Claude account exports and Claude Code conversations. Keep a readable copy on your own disk, find an old answer, revisit a saved artifact, or prepare a conversation to continue in Codex.

**English** · [简体中文](README.zh-CN.md)

[Download for Mac](https://github.com/fengfe1125/ChatArchive/releases/latest) · [Release notes](https://github.com/fengfe1125/ChatArchive/releases) · [Report an issue](https://github.com/fengfe1125/ChatArchive/issues)

**Requirements:** Apple Silicon · macOS 15 or later. The current app interface is in Simplified Chinese.

## What you can do

- **Bring your history together.** Browse Claude account exports in Chat and project-based Claude Code conversations in Code. Search across both sources.
- **Read without repeated clicks.** Scroll up or down to load more messages automatically. Use the message rail to preview and jump to a specific message, including one that has not loaded yet.
- **Keep context intact.** Switch between saved conversation branches and answer versions. Expand saved thinking, tool records, and extracted attachment text when available.
- **Revisit artifacts.** Open saved HTML artifacts in a side panel, try their embedded interactions, inspect the source, switch versions, or save the HTML.
- **Organize locally.** Rename, star, and archive conversations. Records without exported body text live in a separate collection, outside the regular chat list.
- **Take your history with you.** Export readable Markdown or complete records. Optionally prepare a handoff to Codex; Codex is not required for backup or reading.

## Get started

1. [Download the latest DMG](https://github.com/fengfe1125/ChatArchive/releases/latest) and drag **聊天档案** into **Applications**.
2. Open the app and select your source files.
3. Choose a backup folder on your Mac or an external drive. The app copies and verifies the files before indexing them.
4. Choose **Chat** or **Code** to start reading.

Existing archives can be opened with **直接打开已有档案** (“Open an existing archive”). Interrupted backup jobs can be resumed from the setup screen.

The current release is ad-hoc signed, without Developer ID signing or Apple notarization. macOS may block its first launch. Compatibility on another Mac and Gatekeeper behavior have not been independently verified.

### Supported sources

| Source | What to select |
| --- | --- |
| Claude account export | Official export ZIP files, keeping names such as `conversations-000.zip`. Include `frames-000.zip` for saved artifacts. No manual extraction is needed. |
| Claude Code | A directory containing `projects`, usually `~/.claude`, or an existing Code backup. |
| Export download manifest | A manifest JSON and a destination folder. Downloads retain the ZIP files and record SHA-256 hashes; expired links require a new manifest or manually downloaded ZIPs. |

New backups are stored as separate batches. You can move a complete new-format archive to another disk; reading its copied contents does not require the original source to stay connected. Opening a legacy Code backup directly keeps references to that backup, so use the copy workflow when preparing a portable archive.

## Your files stay yours

- Original backup records are read-only. Local names, stars, and archive status are stored separately.
- Missing titles use a label based on available message text, attachment names, or dates. Missing body text and attachment files are marked explicitly; the app cannot recreate content absent from an export.
- Artifact previews run in an isolated WebKit sandbox with network access blocked. Embedded scripts can support local interactions; external dependencies may not work. Preview state is temporary and is not written back to the saved artifact.
- Reading a saved command does not execute it. Codex handoff is an explicit action and requires a configured Codex installation. Existing Codex conversations can retain absolute handoff paths even if you later move the archive.
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
| `Engine/` | Backup, indexing, reading, export, and Codex handoff |
| `Tests/` | Python and native Swift regression tests |
| `scripts/` | App and DMG packaging |
| `Design/` | App icon assets and interface notes |

Generated packages and private validation files are excluded from source control. For bugs, [open an issue](https://github.com/fengfe1125/ChatArchive/issues) with your app version, macOS version, and reproduction steps. Redact private conversation text and download links before attaching examples.
