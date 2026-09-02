# Alchemy event API inventory

After capability installation, the runtime reports the exposed subset in
`diagnostics.eventApis` and in the `installCapabilities` response. To list the
operations installed for the Python test-floater scenario, use:

```sh
jq '[.[] | select(.command.op == "installCapabilities") |
  .response.result.eventApis | to_entries[] |
  {api: .key, operations: [.value.operations[].name]}]' \
  artifacts/test_floater/event-trace.json
```

Registration proves that the linker retained an API object. It does not prove
that the normal application owner or its state exists. The status column uses
the following terms:

- `Local` operations use state that the lab initializes. They do not
  require login, world state, or a network service.
- `Subject` operations work only for a compatible registered
  subject, control, notification template, or deterministic inventory fixture.
- `Unavailable` operations require a normal viewer subsystem or an
  external service that the lab does not initialize.

| API | Local or subject operations | Unavailable operations |
| --- | --- | --- |
| `GroupChat` | None | `leaveGroupChat`, `sendGroupIM`, `startGroupChat` require a logged-in group session. |
| `LLAgent` | None | All registered agent, camera, animation, nearby-object, sit, teleport, touch, and autopilot operations require normal agent or world state. |
| `LLAppViewer` | None | `forceQuit` and `requestQuit` dereference the absent `LLAppViewer` application owner. |
| `LLAppearance` | None | `detachItems`, `getOutfitItems`, `getOutfitsList`, `wearItems`, and `wearOutfit` require logged-in appearance and inventory services. |
| `LLChatBar` | None | `sendChat` requires an agent circuit and world session. |
| `LLCommandDispatcher` | `enumerate` is local. | `dispatch` is command-dependent. Registered URL commands can require login, world state, network access, or external URL handling. |
| `LLFloaterAbout` | None | `getInfo` dereferences the absent `LLAppViewer` application owner. |
| `LLFloaterReg` | `getBuildMap` and `instanceVisible` are local. `showInstance`, `hideInstance`, `toggleInstance`, `toggleInstanceOrBringToFront`, and `clickButton` work for a registered lab subject. A button callback can still require an unavailable service. | None at the registry boundary. |
| `LLInventory` | `getAssetTypeNames` and `getFolderTypeNames` are local. `collectDescendantsIf`, `getBasicFolderID`, `getDirectDescendants`, and `getItemsInfo` use the real `gInventory` model after the lab installs a deterministic inventory fixture. | None for read-only access to the installed fixture. |
| `LLMediaAPI` | `getMediaInfo` returns local control state for an existing `LLMediaCtrl`. | `getMediaText` requires a running media plugin. `getPluginsList` requires the normal `LLViewerMedia` service. |
| `LLNotifications` | `cancel`, `forward`, `ignore`, `listChannelNotifications`, `listChannels`, and `respond` use the initialized notification singleton. `requestAdd` is local only when the selected notification template and its callbacks do not require external state. | None at the notification registry boundary. |
| `LLPipeline` | None | All render-type, render-feature, and debug-display operations target `gPipeline`. The lab renders LLUI directly and does not initialize the normal scene pipeline. |
| `LLStartUp` | `getStateTable` is local. `postStartupState` posts the lab's unchanged startup state and has no application lifecycle behind it. | None, but `postStartupState` cannot advance the lab lifecycle. |
| `LLTeleportHandler` | None | `teleport` requires a logged-in agent and world connection. |
| `LLToolMgr` | None | `openBuildFloater` and `selectTool` require the normal tool manager, selection manager, and world state. |
| `LLURLDispatcher` | None | `dispatch`, `dispatchFromTextEditor`, and `dispatchRightClick` can invoke login, world, network, or external URL boundaries. |
| `UI` | `getValue` is local. `setSelectedByValue` works for an existing `LLComboBox`. `call` is local only for a callback whose implementation has no external dependency. | None at the commit-callback registry boundary. |
| `LLWindow` | `getInfo`, `getPaths`, `getSubtree`, `mouseDown`, `mouseDoubleClick`, `mouseUp`, `mouseMove`, and `mouseScroll` use the lab's `LLWindowCallbacks` host. | Keyboard, text, clipboard, and keybinding operations remain unexposed until the lab supplies and proves their platform dependencies. |
| `XUILab` | `initialize`, `installCapabilities`, `frames`, `stable`, `resizeViewport`, `resizeSubject`, `capture`, `reload`, `diagnostics`, and `shutdown` are local. `query` and `input` are exposed only when the subject installs their required capabilities. The `input` operation supports wheel scrolling, raw pointer drag, and semantic drag-and-drop. | None. |

## Runtime bridge

The parent keeps the JSON-lines process boundary. The runtime parses each JSON
object into LLSD and posts it to the `XUILab` event pump. Operations that need a
reply use a temporary event pump named by the request's `reply` field.

`XUILab.installCapabilities` returns metadata only for the APIs and operations
that the subject can use with its installed capabilities. The runtime derives
the metadata from `LLEventAPI::getMetadata()` instead of maintaining a second
operation schema.

`LLWindowListener` accepts `LLWindowCallbacks*`. Both `LLViewerWindow` and the
lab window host implement that interface. The lab reuses path resolution, tree
inspection, coordinate synthesis, event replies, and input dispatch without
constructing the viewer application. The Python test-floater scenario opens the
registered production floater and proves `LLWindow.getSubtree`,
`LLWindow.mouseDown`, and `LLWindow.mouseUp` in one process. The
`input_gestures` scenario proves `LLWindow.mouseScroll` and production
`LLView::handleDragAndDrop` dispatch.

The bridge follows `LLLeapListener` for request and reply pumps and for API
metadata. It does not instantiate `LLLeap` or launch the controller as a LEAP
child. The parent remains responsible for process lifetime, timeouts, and
failure artifacts.
