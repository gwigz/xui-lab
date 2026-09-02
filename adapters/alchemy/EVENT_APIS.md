# Alchemy event API inventory

This reference covers the `LLEventAPI` instances registered in the no-login
`xui-lab` runtime at Alchemy commit
`4e60607d684a4fde253a61129647f4dbd5fa32f5`.

After capability installation, the runtime reports the exposed subset in
`diagnostics.eventApis`. The `test-floater.json` scenario asserts that `UI`,
`LLFloaterReg`, and `LLWindow` are present. To list the exposed operations from
a run, use:

```sh
jq '[.[] | select(.command.op == "diagnostics") |
  .response.result.eventApis | to_entries[] |
  {api: .key, operations: [.value.operations[].name]}]' \
  artifacts/event-api/test_floater/event-trace.json
```

Registration proves that the linker retained an API object. It does not prove
that the normal application owner or its state exists. The status column uses
these terms:

- **Local**: The operation uses state that the lab initializes. It does not
  require login, world state, or a network service.
- **Subject**: The operation is local only for a compatible registered
  subject, control, notification template, or deterministic inventory fixture.
- **Unavailable**: The operation requires a normal viewer subsystem or an
  external service that the lab does not initialize.

| API | Local or subject operations | Unavailable operations |
| --- | --- | --- |
| `GroupChat` | None | `leaveGroupChat`, `sendGroupIM`, `startGroupChat` require a logged-in group session. |
| `LLAgent` | None | All registered agent, camera, animation, nearby-object, sit, teleport, touch, and autopilot operations require normal agent or world state. |
| `LLAppViewer` | None | `forceQuit` and `requestQuit` dereference the absent `LLAppViewer` application owner. |
| `LLAppearance` | None | `detachItems`, `getOutfitItems`, `getOutfitsList`, `wearItems`, and `wearOutfit` require logged-in appearance and inventory services. |
| `LLChatBar` | None | `sendChat` requires an agent circuit and world session. |
| `LLCommandDispatcher` | **Local:** `enumerate`. | `dispatch` is command-dependent. Registered URL commands can require login, world state, network access, or external URL handling. |
| `LLFloaterAbout` | None | `getInfo` dereferences the absent `LLAppViewer` application owner. |
| `LLFloaterReg` | **Local:** `getBuildMap`, `instanceVisible`. **Subject:** `showInstance`, `hideInstance`, `toggleInstance`, `toggleInstanceOrBringToFront`, and `clickButton` work for a registered lab subject. A button callback can still require an unavailable service. | None at the registry boundary. |
| `LLInventory` | **Local:** `getAssetTypeNames`, `getFolderTypeNames`. **Subject:** `collectDescendantsIf`, `getBasicFolderID`, `getDirectDescendants`, and `getItemsInfo` use the real `gInventory` model after the lab installs a deterministic inventory fixture. | None for read-only access to the installed fixture. |
| `LLMediaAPI` | **Subject:** `getMediaInfo` returns local control state for an existing `LLMediaCtrl`. | `getMediaText` requires a running media plugin. `getPluginsList` requires the normal `LLViewerMedia` service. |
| `LLNotifications` | **Local:** `cancel`, `forward`, `ignore`, `listChannelNotifications`, `listChannels`, and `respond` use the initialized notification singleton. **Subject:** `requestAdd` is local only when the selected notification template and its callbacks do not require external state. | None at the notification registry boundary. |
| `LLPipeline` | None | All render-type, render-feature, and debug-display operations target `gPipeline`. The lab renders LLUI directly and does not initialize the normal scene pipeline. |
| `LLStartUp` | **Local:** `getStateTable`. `postStartupState` posts the lab's unchanged startup state and has no application lifecycle behind it. | None, but `postStartupState` cannot advance the lab lifecycle. |
| `LLTeleportHandler` | None | `teleport` requires a logged-in agent and world connection. |
| `LLToolMgr` | None | `openBuildFloater` and `selectTool` require the normal tool manager, selection manager, and world state. |
| `LLURLDispatcher` | None | `dispatch`, `dispatchFromTextEditor`, and `dispatchRightClick` can invoke login, world, network, or external URL boundaries. |
| `UI` | **Local:** `getValue`. **Subject:** `setSelectedByValue` works for an existing `LLComboBox`. `call` is local only for a callback whose implementation has no external dependency. | None at the commit-callback registry boundary. |
| `LLWindow` | **Local:** `getInfo`, `getPaths`, `getSubtree`, `mouseDown`, `mouseDoubleClick`, `mouseUp`, `mouseMove`, and `mouseScroll` use the lab's `LLWindowCallbacks` host. | Keyboard, text, clipboard, and keybinding operations remain unexposed until the lab supplies and proves their platform dependencies. |
| `XUILab` | **Local:** `initialize`, `installCapabilities`, `frames`, `stable`, `resize`, `capture`, `reload`, `diagnostics`, and `shutdown`. **Subject:** `query` and `input` are exposed only when the subject installs their required capabilities. | None. |

## Runtime bridge

The parent keeps the JSON-lines process boundary. The runtime parses each JSON
object into LLSD and posts it to the `XUILab` event pump. Operations that need a
reply use a temporary event pump named by the request's `reply` field.

`XUILab.installCapabilities` returns metadata only for the APIs and operations
that the subject can use with its installed capabilities. The runtime derives
the metadata from `LLEventAPI::getMetadata()` instead of maintaining a second
operation schema.

`LLWindowListener` accepts `LLWindowCallbacks*`. Both `LLViewerWindow` and the
lab window host implement that interface, so the lab reuses path resolution,
tree inspection, coordinate synthesis, event replies, and input dispatch
without constructing the viewer application. The `test-floater.json` scenario
proves `LLWindow.getSubtree`, `LLWindow.mouseDown`, `LLWindow.mouseUp`,
`UI.getValue`, and `LLFloaterReg` show and hide behavior in one process.

The bridge follows `LLLeapListener` for request and reply pumps and for API
metadata. It does not instantiate `LLLeap` or launch the controller as a LEAP
child. The parent remains responsible for process lifetime, timeouts, and
failure artifacts.
