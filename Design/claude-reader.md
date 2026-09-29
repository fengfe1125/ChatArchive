# Claude archive reading workspace

Native macOS implementation of the archived Claude Mac desktop reading workflow.

Reference: Claude Help Center artifact/version workflow; current signed-in UI unavailable. This is a reconstruction, not a verified pixel-identical copy of a particular release.

Structure: persistent 248 pt sidebar, flexible conversation column (720 pt reading measure), optional resizable right artifact panel (min 360 pt). Sidebar offers search, chats, starred, projects/Code, artifacts, archived and archive settings. Conversation title/menu sits above the reading column. Warm off-white background; darker warm sidebar; understated separators; 16 pt body with serif assistant prose. No decorative animation; respect native reduced-motion setting.

Interactions: message-level alternate-answer arrows; collapsed thinking/tools; copy; attachment/source preview; artifact preview/source/version/fullscreen/download; reversible local rename/archive/star; history search; Code position persistence; scroll-to-bottom; message navigation rail; automatic forward pagination; missing-body collection. Original records remain immutable. Local metadata changes are labelled as such.

Artifacts run in an opaque sandboxed iframe in ephemeral WKWebView, with CSP denying network, objects, forms, navigation and parent access. No host message bridge. Only embedded scripts/styles and data images are allowed. Original HTML can be saved through a native Save panel. Unavailable external resources are not fetched.

No fake generation, model switching, upload or publish controls: continuation delegates to the existing Codex handoff flow. Missing exported data is stated explicitly.
