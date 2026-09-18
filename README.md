![Proton Wineland](wineland-banner.png)

What is Proton Wineland?
-------------------------

Proton Wineland aims to solve Linux gaming problems through complete solutions
rather than accumulating hacks and workarounds for individual games. Its goal
is to address issues that are genuinely solvable when the necessary time and
care are invested.

The project began with the lack of robust Wayland support. Since then, it has
grown beyond launchers to address broader compatibility, rendering, input, and
media issues across games and applications.

While upstream compatibility was an early consideration, it should not limit
what the project can achieve. Proton Wineland's focus is the quality of the
solution and the experience it delivers to Linux gamers.


What does Proton Wineland offer over other Proton versions?
-----------------------------------------------------------

Proton Wineland is not intended to change how every game runs. Its advantages
are most noticeable when a game or launcher runs into Wayland problems
that other Proton versions may work around only partially.

It can provide:

- More reliable Windows game launchers, including Chromium and CEF
  applications such as Battle.net, Ubisoft Connect, Rockstar Games Launcher,
  and the native Windows Steam client.

- Better fullscreen and borderless window behaviour, including minimising,
  maximising, restoring, Alt+Tab, and switching monitors, particularly with
  multiple monitors and mixed scaling.

- Correct rendering for overlays, popups, login windows, and other content
  created by a separate Windows process from the visible game window.

- Improved video and media playback compatibility in applications that use
  Windows Media Foundation.

- More accurate mouse and keyboard behaviour when a game is fullscreen, scaled,
  or moved between monitors.

- Better integration with Wayland desktops, including Windows tray icons,
  application menus, and compatible HDR and colour management paths.

These improvements work automatically where they are applicable. They are
intended to solve underlying compatibility problems rather than require
environment variables or launch options tailored to each game.

These benefits depend on the game, GPU driver, compositor, and desktop setup.
A game that already works well with another Proton version may not show a
visible difference.


What does it improve?
----------------------

Proton Wineland aims to make Windows games and their supporting applications
feel at home on a Wayland desktop. It improves launcher compatibility,
fullscreen behaviour, and common window actions such as minimising, maximising,
restoring, and moving games between monitors. It also works to improve video
and media playback, and the rendering of overlays or companion windows,
including cases where those windows are created by a separate process.


What does it not promise?
-------------------------

No Proton version can guarantee that every game will work perfectly. Not every
problem originates in Proton or can be solved within Wine. Issues may also come
from the game itself, graphics drivers, the desktop compositor, or another part
of the Linux graphics stack.


Is it experimental?
-------------------

Yes, but "experimental" does not mean inherently unstable. Proton Wineland
takes a different approach from the usual pattern of relying on environment
variables, command line parameters, and Wine workarounds for individual titles.

Where possible, it aims to solve the underlying problem in a durable way. This
does not mean the project has no bugs, including in newly added areas, but being
experimental does not mean deliberately sacrificing stability. In some
situations, it may even be more stable than other Proton versions.


How is artificial intelligence used?
------------------------------------

AI tools are a regular part of Proton Wineland's development process. I use
them to analyse logs, investigate problems, review changes, and help fix or
generate code when I consider that appropriate.

Before delivery, every commit goes through a review assisted by AI. I examine
the findings and decide whether the suggested changes are technically sound
and suitable for the project. When they are, I may let the AI modify the code
and then review the result again.

AI does not replace engineering judgement, testing, or responsibility for the
code that is delivered. Used thoughtfully, however, it is a valuable software
development tool that can accelerate investigation and help identify problems
that might otherwise be missed.


How do I activate the Wayland features?
----------------------------------------

You do not need to enable anything manually. Proton Wineland enables Wayland by
default by setting `PROTON_ENABLE_WAYLAND=1`, so games and supporting
applications run through Wayland automatically.


How is the initial monitor selected?
------------------------------------

At launch, Proton reads KDE's or GNOME's configured primary monitor, niri's
focused monitor, or COSMIC's preferred display for X11 games. COSMIC's preference
is reused for native Wayland games. This does not switch them to Xwayland.
The query runs once, does not change desktop settings, and leaves Wine's default
unchanged if the desktop is unsupported or no unambiguous answer is available.

An explicit `WAYLANDDRV_PRIMARY_MONITOR` always takes precedence, for example:

```sh
WAYLANDDRV_PRIMARY_MONITOR=DP-2 %command%
```


How do I disable window slicing?
--------------------------------

Slicing clips GPU-rendered content to shaped windows and complex child-window
regions. To disable it for a game or launcher, use:

```sh
PROTON_WAYLAND_SLICING=0 %command%
```

Each affected buffer then uses a single rectangular surface. This also disables
the four-pixel shape approximation, while preserving the original input region.
Non-rectangular visual clipping is lost, so rectangular edges or child-window
overlap may appear. Slicing is enabled by default. Remove the option or set it
to `1` to restore it. Restart the game after changing this setting.


How do I resize a game's cursor?
--------------------------------

For custom bitmap cursors supplied through Wine, set a size multiplier in the
Steam launch options, for example:

```sh
PROTON_WAYLAND_CURSOR_SCALE=2 %command%
```

This doubles the cursor size without changing game resolution or mouse
sensitivity. Fractional values from `0.25` to `8` are supported. The default is
`1`, and invalid values leave the default unchanged. The setting is read when
Wine initializes the Wayland pointer and requires cursor viewport scaling
support from the compositor.

Cursor shapes provided by the compositor, including the Steam overlay cursor,
keep their desktop size. Cursors drawn into the game image cannot be
resized by this option.


How do I enable the HUD with PROTON_HUD?
---------------------------------------

Set a preset in Steam's launch options:

```sh
PROTON_HUD=3 %command%
```

| Level | Information |
| --- | --- |
| `1` | FPS, 1% and 0.1% lows, and window system. |
| `2` | Adds GPU and CPU load, power, temperature, and Proton and GPU driver versions. |
| `3` | Adds GPU and CPU clocks and VRAM usage. |
| `4` | Adds presentation latency timings above level 3. |
| `5` | All HUD elements except `systeminfo`, arranged on the left. |

Levels 1 to 4 use centred horizontal rows, with window system information at
the bottom. HDR and direct scanout (DSO) status appear when available.

Press **Ctrl+Shift+O** to hide or show the HUD. Visibility updates once per
second, including while hidden. The shortcut uses `DXVK_HUD`, whether set
directly or generated by `PROTON_HUD`. An unset, empty or `0` value disables
the shortcut. An empty HUD does not poll for visibility.
Append `hide` to start with the HUD hidden, for example
`PROTON_HUD=3,hide %command%`, then press Ctrl+Shift+O to show it.

This extends the existing DXVK HUD, which VKD3D Proton also uses for Direct3D
12 games. Wine samples CPU and GPU telemetry once per second in background
threads when requested. Available readings depend on hardware, drivers, and
permissions.

Append DXVK HUD options after the preset to customise it, for example:

```sh
PROTON_HUD=3,scale=1.25,-gpu.temp %command%
```

An explicit `DXVK_HUD` takes precedence. See the [DXVK HUD options](dxvk/README.md#hud)
for individual metrics, layout, and appearance settings.

### What do the presentation latency readings measure?

`PROTON_HUD=4` adds these readings for DXVK and VKD3D Proton when the driver and
presentation stack support `VK_EXT_present_timing`. All four are displayed in
milliseconds. They use three timestamps:

- `T0` is recorded by us shortly before calling `vkQueuePresentKHR`.
  In VKD3D Proton this happens on the command queue's submission thread.
  Time queued between the application's DXGI `Present()` call and that point is excluded.
- `T1` is the Vulkan driver's `QUEUE_OPERATIONS_END` timestamp.
- `T2` is the Vulkan driver's `FIRST_PIXEL_OUT` timestamp when available.

The driver supplies the event timestamps through Vulkan presentation-timing
reports. We do not take new timestamps when the reports arrive. A report arriving
several frames later does not add to the measured latency. First pixel out means
data leaving the presentation engine toward the display, not pixels already visible.

The original timing source depends on the driver and presentation stack. Mesa's
Wayland implementation gets first pixel out from the compositor's presentation
feedback. On KWin's DRM backend this normally comes from the kernel page-flip
completion timestamp for the frame containing the game's image, not a measurement
of the display's pixel response. Other drivers can obtain timing differently.

| HUD label | Calculation | Meaning |
| --- | --- | --- |
| Queue latency | `T1 - T0` | Submission work, dependency waits, and queued presentation work. |
| Output latency | `T2 - T1` | Downstream presentation processing and waiting, which can include compositor work. |
| Present latency | `T2 - T0` | Total of the two stages for the same frame. |
| Output interval | `T2(current frame) - T2(previous frame)` | Spacing between consecutive frames reaching output. |

Output interval can be lower than Present latency because several frames can be
in flight. A frame can take 20 ms to reach output while frames emerge every 8 ms.
These readings do not measure total CPU or GPU rendering time or full input latency.

If first pixel out is unavailable, the latency endpoint falls back to first pixel
visible, then request dequeued. The last fallback does not confirm display output.
Output interval stays unavailable without consecutive first pixel out measurements.
Text refreshes every 500 ms using the latest valid readings, not an average.
Individual fields may come from different frames.

Wine disables presentation timing for surfaces eligible for its managed dmabuf
path, including cross-process presentation. Those surfaces can show `--` even
when the host driver supports the extension. This is a Wine presentation-path
limitation rather than missing driver support.

The configuration keywords remain `latency.queue`, `latency.display`,
`latency.present`, and `latency.interval`. See the
[measurement details and timeline](dxvk/README.md#presentation-latency-measurements).


How do I use OptiScaler nightlies?
---------------------------------

Use `PROTON_USE_OPTISCALER=1` for stable releases. For the latest official
nightly, set this Steam launch option:

```sh
PROTON_USE_OPTISCALER=nightly %command%
```

To pin a specific nightly:

```sh
PROTON_USE_OPTISCALER=nightly-20260906 %command%
```

Nightlies are downloaded from
[OptiScaler's official releases](https://github.com/optiscaler/OptiScaler-nightly/releases)
and verified before installation. Updates are checked at launch, not during
gameplay. Previous INI files are saved as `.ini.old`, and
`PROTON_OPTISCALER_CONFIG` is reapplied. Switch back to `1` to use stable again.

Nightlies also fetch the latest official NVIDIA Streamline runtime for the
frame-generation combinations that require it. Its DLLs and licence notices
are installed under `umu/OptiScaler/streamline`, with links to the existing
managed DLSS DLLs instead of duplicate copies. Private nightly libraries stay
under `OptiScaler`. The entry DLL and INI stay in `umu`.

Nightlies use their bundled XeSS and FidelityFX libraries instead of fetching
extra standalone copies. Explicit upscaler upgrades remain available. Existing
installer-owned duplicates are removed only when unchanged. Modified files
and custom library paths are preserved.

The first Streamline download is the full SDK archive (currently about 276 MB).
The installed runtime is about 10 MB. Downloads are verified and cached, and a
failed update keeps the previous installation without disabling OptiScaler.
Stable OptiScaler installations do not fetch Streamline automatically.


What is the relationship to CachyOS Proton?
-------------------------------------------

Proton Wineland is currently based on CachyOS Proton. Proton is made up of many
components, with Wine being only one of them. Most Proton Wineland changes are
made to Wine, while CachyOS Proton provides the surrounding build, integration,
and runtime framework.

Early on, Proton Wineland was regularly rebased onto the latest CachyOS
branches. As its Wayland work expanded, rebasing the Wine component became
increasingly difficult. Repeatedly resolving the growing number of conflicts
began to destabilise the codebase, so Proton Wineland now maintains its Wine
work independently and selectively picks compatible upstream and bleeding edge
changes.

An early possibility was contributing the Wineland changes directly to CachyOS.
As the project grew in scope and followed its own technical direction,
independent development became the better fit. This gives Proton Wineland room
to pursue broader solutions when they can improve the Proton experience.

CachyOS has its own development priorities and established relationships with
the Wine development process. Proton Wineland complements that work with an
independent focus. I have great respect for the CachyOS maintainers and
developers, and value their tremendous work.


Original Proton documentation
-----------------------------

The original Proton documentation, including build instructions, is available
in [README_PROTON.md](README_PROTON.md).
