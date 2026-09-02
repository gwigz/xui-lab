# Alchemy event API inventory

This reference covers the `LLEventAPI` instances registered in the no-login
`xui-lab` runtime at Alchemy commit
`00070185dbf063ad6d2bebeec241a99b15a5f3b0`.

The runtime reports this inventory in `diagnostics.eventApis`. The
`test-floater.json` scenario asserts that `UI` and `LLFloaterReg` are present.
To list every registered operation from a run, use:

```sh
jq '[.[] | select(.command.op == "diagnostics") |
  .response.result.eventApis | to_entries[] |
  {api: .key, operations: [.value.operations[].name]}]' \
  artifacts/process-boundary/test_floater/event-trace.json
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

`LLWindow` is the most relevant API that is not registered. Its constructor
requires an `LLViewerWindow`, while the lab owns an `LLWindow` and a production
LLUI root without constructing the normal viewer application. `LLViewerWindow`,
`LLViewerControl`, `LLStats`, and `LLGesture` are also absent from the live
inventory. A later bridge must extract or adapt `LLWindow` input and inspection
without forcing the lab to construct `LLViewerWindow`.
