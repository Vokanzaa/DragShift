# DragShift — local file tools

## Custom build 1.1.0+files.12

**Install:** [Windows installer](https://github.com/Vokanzaa/DragShift/releases/latest/download/DragShift-Setup.exe) · [all desktop packages and release version](https://github.com/Vokanzaa/DragShift/releases/latest).

**Source:** [main branch](https://github.com/Vokanzaa/DragShift/tree/main) · [source ZIP](https://github.com/Vokanzaa/DragShift/archive/refs/heads/main.zip). Source downloads contain code; choose a packaged application above to install and use it. While a new release is building, main can be newer than the published package. The release page identifies the packaged version.

New in files.12: only real file drags can reveal the radial menu; plain Shift, text drags and drawing gestures stay in the active app. New in files.11: shared image settings now process the entire selected series for crop, Edit, backgrounds, annotations, redaction and metadata removal. Resize and compression also use transactional batch completion. **553 local source tests passed.** Releases are published only after the complete native desktop build matrix succeeds.

Files.10 added direct distortion keyframes with absolute strength, editable random variations, independent audio distortion, clearer preview/export ranges and faster default-size frame processing. Its local source suite passed **517 tests**.

This local extension is based on [llamaboi55/DragShift](https://github.com/llamaboi55/DragShift), upstream commit `88abe0cf392b80ad2db805ef12b020c76a6cf458` retrieved on 2026-10-19. It is not an official upstream release. The custom Windows package adds video, audio, experimental Datamosh and archive workflows to the original Shift-drag radial menu, with neutral matte glass.

The distribution uses `DragShift-Files-Setup.exe`, `DragShift-Files-Source.zip` and the Russian `DragShift-Руководство.md`; the installer targets Windows x64. Upstream GitHub releases do not contain these local additions. The files.9 Windows package was built, installed in Russian, and passed both self-test modes in English and Russian. Native package checks passed for **Windows, Linux, Apple Silicon and Intel Mac** in the [files.9 desktop run](https://github.com/Vokanzaa/DragShift/actions/runs/40294171055) (`442c6f8`). Linux also passed all **19 installed XFCE file-manager scenarios**. The local source suite passed **408 tests**.

The Windows installer offers **Русский / English**. The selected language is saved for the application, including radial menus, tools, settings and standard Qt dialogs. macOS/Linux follow the system language initially. Change it in **Settings → Language**, then restart; `DRAGSHIFT_LANGUAGE=ru` or `en` overrides it for a launch.

## Start and convert

Launch DragShift once; it stays in the system tray. There is no standalone file queue or upload window.

1. Begin dragging a file in Explorer or on the desktop.
2. Press **Shift**, then drop it on a menu sector.
3. Tap **Shift** again while dragging to switch between **Convert** and **Tools**.

Choose a format in **Convert**, or an operation in **Tools**. Editors open only after choosing a tool. Several files of the same type can be dragged together. The tray icon opens its control menu, with **Settings…**, **How to use** and **Quit DragShift**. The per-user installer can add Explorer's **DragShift…** and **Send to → DragShift** entries, which also use the radial menu. Ctrl or Alt can replace Shift in Settings.

For nonadjacent files in a Windows Explorer folder, select them with Ctrl, release Ctrl, then **tap and release Shift without clicking**. A click radial menu opens for that exact selection. Holding Shift while clicking a file retains Explorer's normal range-selection behavior. The tap shortcut requires at least two items in an Explorer folder and a Shift trigger; it does not read desktop selection and refuses ambiguous tabbed views. Normal file dragging works on every supported platform and uses the final dropped file list. The global modifier/mouse gesture is validated against a native local-file drag before showing the ring. Plain Shift, typing, drawing, text selection and web-link drags do not reveal tools. The drag probe does not take keyboard focus or grab the mouse. macOS retains the stationary Finder handoff only when its file-drag pasteboard changed during the current mouse gesture; old clipboard/drag data and inactive Explorer selections cannot open tools.

## Supported workflows

| Input | Output formats | Tools |
|---|---|---|
| Images: PNG, JPG/JPEG, WebP, HEIC/HEIF, AVIF, TIFF, BMP, GIF, ICO | PNG, JPG, WebP, HEIC, AVIF, TIFF, BMP, GIF, ICO, PDF | Compress, resize, crop, colour/light edits, annotate, redact, add background, view/remove metadata, Liquid Rescale distortion, lenticular interlace/print projects |
| Video: MP4, MKV, MOV, AVI, WebM, M4V, WMV, FLV, TS/MTS/M2TS, MPEG/MPG, 3GP, OGV, VOB | MP4, MKV, MOV, WebM, AVI, animated GIF, MP3, WAV | Trim, compress, resize, crop/rotate/mirror, speed, colour, mute, PNG frame, metadata, Datamosh, Liquid Rescale distortion, Audio extraction |
| Audio: MP3, WAV, FLAC, M4A/M4B, AAC, OGG/OGA, Opus, AIFF/AIF, WMA, APE, ALAC, AMR | MP3, WAV, FLAC, M4A, AAC, OGG, Opus, AIFF | Trim, edit, normalize, fade, compress, reverse, metadata |
| Archives: ZIP, 7Z, RAR, TAR | ZIP, 7Z, TAR | Contents, extract into a new folder |
| PDF | JPG/PNG per page, DOCX, TXT | Compress, split, rotate, merge, password protection, extract images, metadata |
| Word DOCX | PDF, TXT | Conversion |
| Text: TXT, MD, CSV, LOG, JSON, XML, HTML/HTM | PDF, DOCX | Plain-text conversion |

Available decoders and encoders determine whether a particular file is readable. Unsupported extensions have no conversion actions in the radial menu. This is not a general Office, spreadsheet, slide, OCR or 3D converter. Text formats are imported as text, without evaluating HTML, Markdown or spreadsheet formulas. Animated GIF editing preserves composited frames, frame durations, transparency and loop metadata. Converting an animated GIF to PNG, JPG, WebP, HEIC, TIFF, AVIF, BMP or ICO extracts every composited frame into a new uniquely named folder beside the original GIF (`name Frames/frame-000001.ext`, etc.). This destination follows the GIF even if ordinary exports use a subfolder. GIF editing itself retains the animated GIF. GIF also offers MP4 and WebM conversion with its original animation, without a generated camera effect.

GIF-to-video conversion chooses a frame grid compatible with its centisecond delays (at least 30 fps, up to 100 fps) instead of dropping very short source frames. Telegram's separate profile is capped at 30 fps by its specification, so faster animations necessarily lose temporal detail there.

Numeric slider values are editable with the keyboard; Enter confirms the value without exporting. Open tools accept local-file drops: source editors replace the current input, while Melt/audio sequence lists append files. Drop onto either Melt preview to replace that clip. Sequence rows can be reordered by dragging or with the up/down buttons. Pack accepts additional files and folders.

For a selected image series, **Crop, Edit, Add BG, Annotate, Redact, Metadata, Compress and Resize** open one editor. Its preview shows the first source; saving applies the shared settings to every selected file. Crop/hidden areas and annotations scale proportionally to each correctly oriented canvas; fixed crop ratios stay fixed. Identical-size inputs keep the exact same coordinates. Edits preserve GIF animation and produce separate new results. A multi-image drop replaces the selected series. Background **Copy preview** copies the first result to the clipboard. Cancellation or a later failure rolls back earlier new results from that batch.

DOCX → PDF uses Microsoft Word when available, otherwise a basic local renderer. PDF → DOCX rebuilds paragraphs and images. Complex layouts, fonts, tables, headers, charts and scanned pages may not reproduce accurately; scanned text is not recognized with OCR.

Video editing requires FFmpeg 7 or newer. Packaged builds include a compatible full engine; Linux uses a static build verified against its provider's checksum instead of the older Debian system engine.

## Video and Datamosh

MP4/MKV/MOV use H.264 and AAC, WebM uses VP9 and Opus, and AVI uses MPEG-4 video. GIF exports from video use 12 fps and an edge up to 640 px. Video edits save a new MP4. Speed ranges from 0.25× to 4× and preserves audio pitch. Editing retains every source frame and variable frame intervals; speed scales those intervals. Edited MP4s disable B-frame reordering to preserve final-frame timing, which can increase file size at the same quality. The frame preview updates with rotation, centre crop, mirror and colour settings using the same filters as export. Trim has two range handles synchronized with its start/end numeric fields; the frame slider also allows scrubbing.

**Tools → Resize** opens a crop frame with draggable edges/corners, numeric Left/Right/Top/Bottom amounts, output Width/Height in pixels and Keep proportions. Scrub to inspect another frame. Crop coordinates follow the displayed orientation and square-pixel geometry; export uses the same crop, preserves audio and writes a new MP4. Output dimensions are rounded to even pixels, 16–7680. In a batch the same relative crop and output size apply to every video.

**Tools → Audio** extracts the first audio track from a video into any supported audio output format. **Mute** saves an MP4 without audio; **Frame** saves a full-resolution PNG.

For a classic Melt transition, open **Tools → Datamosh**. With two videos, the familiar A/B controls select the last seconds of A and first seconds of B, transition duration, intensity, size, fps and audio. **Melt** is the only effect. **Render preview** makes a short 480 px sample around the cut.

For a series, select **Edit a video sequence on the timeline**, or drop three or more videos together (2–16 clips). Drag clip centres to reorder; drag their edges or edit Source start/end to trim. Position the playhead on the ruler and choose **Split at playhead**. Each Melt badge selects that boundary's independent duration, intensity and on/off setting. A split inside one continuous source starts with its added effect off. Preview renders the selected boundary only.

The classic renderer edits FFglitch motion vectors and removes the bridge I-frame. It does not mix a clean-video overlay into the result. Retained recovery frames restore ordinary footage after the transition; keep at least two clean frames in each following clip. Audio segments are joined with silence for missing tracks, and removed frames are compensated at their original timeline positions. The final MP4 is H.264. Datamosh is experimental and depends on source motion. Audio glitch remains inside this same dialog with an intensity control and optional time shapes.

## Lenticular preparation and printing

Select two or more images and choose **Tools → Interlace**. Add/drop 2–30 sources in supported image formats, reorder them, crop each source, and choose fill/crop, white-margin fit or stretching. Fitting can be applied to all frames. Set width in millimetres, height or automatic first-image aspect, actual lens pitch (LPI), integer pixels per frame per lens and vertical/horizontal direction. The displayed actual dimensions include whole-lens rounding. A copy grid, gaps and sheet margins also align to complete lenses.

New projects enable **Automatic sampling · about 900 PPI**. Sampling remains an integer number of pixels per frame per lens, so the resulting PPI is the lens pitch multiplied by the frame count and that integer. At 75 LPI with ten frames, the automatic choice is one pixel per frame and **750 PPI**. Changing the integer manually disables automatic sampling; existing saved manual settings remain unchanged until the user enables it.

**Save project…** stores source references, order, fitting/crops and print settings in a portable relative-path `.dshift-print` project. Keep the project with its source images when moving it to another computer. Drop the project onto DragShift to reopen it. **Save interlace** writes a unique lossless TIFF, PNG or BMP plus a `.print.json` sidecar with pixel size, physical size and settings. **Export at printer resolution** resamples using the same deterministic raster path as direct printing, at the specified DPI.

Large TIFF/PNG exports and Windows direct printing generate the raster in row bands, using temporary disk-backed fitted sources instead of allocating the complete sheet in memory. TIFF automatically uses BigTIFF when required by its uncompressed raster size. Each input image is limited to 100 million pixels; generated sheets have a separate limit of 16 billion pixels and 1 million pixels per side. Sufficient temporary and output disk space is required. Printer drivers and the operating system's spooler manage their own memory separately.

A local export check requested a 2000×2000 mm sheet at 75 LPI with ten frames and one pixel per frame per lens. Whole-lens rounding produced a 59,050×59,060 px, 750 PPI BigTIFF: 616,589,313 bytes in 127.29 s, with a sampled process peak of 158.08 MiB. Three strips at the beginning, middle and end were decoded successfully; this was an export benchmark, not a physical print or a full-image decode. Sixty-six targeted tests passed for streaming and small calibrated raster parity.

BMP export also streams row bands. A separate 2000×200 mm, 75 LPI, ten-frame check produced a **59,050×5910 px, 348.99 MP BMP of 1,046,968,374 bytes** in **14.95 s**, with a sampled process peak of **161.98 MiB**. The file length and BMP header matched, three complete scanlines matched the expected pixels, and the native Windows WIC decoder opened the actual file and decoded both opposite corners correctly. Standard BMP output is limited to **4,294,967,295 bytes**, checked before frame preparation; choose TIFF/BigTIFF for larger rasters. BigTIFF requires a compatible reader. These synthetic-file checks do not establish physical print quality or compatibility with every external editor or printer driver.

On **Windows**, **Print…** opens the printer's native settings and sends an explicitly prepared raster one pixel per device pixel, starting at the printable-area origin. There is no fit-to-page stage; oversize rasters are rejected. A Canon MG3200-series 600 dpi control job matched the reference printer command stream byte for byte after excluding its job timestamp. This establishes that tested driver/settings combination, not every printer or optical assembly. Use the intended paper size, orientation, quality and actual calibrated LPI; driver borderless expansion or subsequent scaling can change lens alignment.

The interlace, projects, image fitting, grid and raster export are shared by **Windows/macOS/Linux**. Calibrated native direct printing is currently Windows-only. Printing a saved file from an external editor is not guaranteed to preserve the same raster path or physical scale.

### Liquid Rescale distortion

Choose **Tools → Distort** on a GIF, video or still image. The engine uses ImageMagick with liblqr: content-aware shrink followed by ordinary resize back to the processing canvas, as documented by [OpenDistortBot](https://github.com/rupansh/OpenDistortBot), which credits the author of @DistortBot. No bot source code was copied. The default intensity **40** corresponds to its documented **60×60%** shrink. Zero is unchanged; 95 is the strongest setting. A synthetic frame is pixel-identical to the reference ImageMagick command; the current hosted bot's version/settings are not public, so exact equivalence with that service is not established.

For animated media, click the timeline graph to add a keyframe, or choose a time on the top ruler and **Add keyframe**. Select a point to see that moment in the preview; drag it or type its time and strength (**0–95**). Strength interpolates between points. These are actual intensity values; there is no separate master multiplier. Trimming keeps points anchored to the original source time. **Randomize** creates an editable curve with irregular levels and intervals; **Another variation** generates a different one. Scrubbing, previewing and saving reuse the displayed points. Still images retain a uniform intensity slider and keyboard input.

**Audio distortion** independently controls digital crunch from **0–100**, default **40**. Zero retains the original sound; uncheck **Keep source audio** to mute. Audio processing runs during the final MP4/WebM encode, without an extra media pass. This uses local bit/sample reduction and clipping; the hosted bot's unpublished audio effect is not reproduced exactly.

**Maximum video/image size** caps the longest side at 64–1920 px (default 640), preserving proportions and never enlarging. **Preview frame at** changes the displayed frame. Choose **PNG** to save that frame, or **GIF / MP4 / WebM** to save the **Export start / Export end** range; the output duration is displayed, and **Whole video** resets the range. Preview and export use the same processing canvas and curve. GIF input frames retain their delays and loop count; movie distortion uses the existing regular source-FPS sampling grid, so variable frame intervals are resampled. Video-to-GIF delays are rounded cumulatively to its centisecond timebase. WebM and PNG retain alpha, GIF retains binary transparency, and MP4 uses opaque video. Each frame is distorted independently, so animated distortion can flicker as its content changes.

Drop media into the tool to replace its source. Batch settings use each file's full duration when the range is unchanged, otherwise the same time range is applied to every source. Processing is local and cancellable, uses temporary decoded PNG frames, checks disk space, and publishes unique results only on success. The limit is 15,000 frames (GIF rendering also has a 200-million-pixel memory limit); shorten a long segment or lower its output size. The Windows installer includes the engine; source-only builds need ImageMagick 7 with the **lqr** delegate.

Independent frame jobs use up to eight bounded workers for canvases no larger than 640 px, reserving two logical CPUs; larger canvases retain the previous four-worker/half-CPU limit. Lossless intermediate PNG compression stays enabled. Cancellation stops and joins active engines before removing temporary frames. Preview reuses its decoded source when only strength changes. On this Windows PC, the same 40-second moving synthetic clip (1200 frames, 640×360, strength 40) exported in **78.24 s**, versus **94.90 s** before this change: **17.6% less time**. All processed/encoded frame pixels, timestamps and dry audio matched; sampled peak memory increased from about **173 to 310 MB**. This is one benchmark, not a promised speed on every computer or equivalence with a hosted bot.

### Telegram custom emoji

For GIF or video, choose **Convert → TG Emoji**. Select a segment up to three seconds using the range handles or numeric fields, then choose full-frame fit with transparent padding or a square centre crop. The export uses **WebM / VP9, exactly 100×100, no audio stream, at most 30 fps and 256,000 bytes**. Encoding retries at smaller quality when necessary and verifies the resulting streams, dimensions, duration, fps and size before publishing the file. The segment is preserved as animation; Telegram recommends choosing a seamless loop. [Official requirements](https://core.telegram.org/stickers/webm-vp9-encoding).

## Audio

**Edit** combines trimming, volume in dB, pitch-preserving tempo, reverse, mono, fades, normalization, sample rate and output format. Edits save directly to **Save as**, so WAV or FLAC can be chosen without an intermediate AAC encode. The initial format follows the input when supported; otherwise it is M4A. **Compress** starts with MP3 at 128 kb/s.

**Tools → Transition** blends an ordered series of 2–16 audio files with overlapping linear crossfades. The same tool is available from **Datamosh → Audio file transitions…**. Drop files, reorder them, set overlap duration and output format. Middle clips need room for both incoming and outgoing fades. Export duration equals the sum of clip lengths minus one overlap per cut; the result is stereo at 48 kHz (with encoder-compatible rate selection).

For digital crunch, choose **Datamosh → Audio · Glitch** in the same dialog as video Melt. Drop an audio file or a video with audio, select a segment, intensity and simple time shape, then preview the first ten seconds or save the audio. FFmpeg's `acrusher` reduces bit depth and sample rate, mixed with the original signal according to the selected shape. Zero is the dry signal; this is a separate operation from transitions between audio files. Video input exports its first audio track as an audio file.

Normalization measures the processed signal, then applies FFmpeg's two-pass EBU R128 `loudnorm` at −16 LUFS, −1.5 dBTP and LRA 11. Fades are included in the measurement; a volume gain follows normalization, so a positive gain can exceed that normalization peak target. Silence or material shorter than the measurement gate is exported without invalid infinite measurements.

MP3 supports up to 320 kb/s. OGG uses Vorbis VBR quality 5. WAV/AIFF use 16-bit PCM; FLAC uses lossless compression. Bitrate controls apply to MP3, M4A/AAC and Opus. Opus output uses 48 kHz; explicitly incompatible sample rates are rejected. Automatic rate selection retains the source rate when the encoder supports it. Only the first audio track is exported; cover art, video, subtitles and chapters are excluded. Reverse buffers the selected audio in memory, so trim long material before reversing it.

## Archives, outputs and cancellation

**Tools → Pack** creates one **ZIP** (default) or **7Z** archive from selected files and folders, including mixed file types and unsupported conversion extensions. Start dragging the selection, press Shift, switch to Tools with another Shift press, then drop on Pack and choose the archive format. Folders and unknown file types show the Pack tool directly. Moving the pointer over the hub never switches rings; click menus also accept deliberate hub clicks.

Folder structure, empty folders and modification times are retained. Overlapping selections are included once. Conflicting top-level names and links/junctions are rejected with an explanation. Limits are 100,000 items and 20 GiB of source data. Packing first creates a cancellable temporary copy, so enough free space for that copy and the archive is required.

The archive is saved beside the first remaining top-level selection, or in its parent's DragShift subfolder according to Settings. If that would place the result inside a selected folder, it is saved beside that folder instead. Existing results receive a numbered name. Choosing Pack for an existing archive puts that archive file into a new archive; Convert changes the format of its contents.


Archive conversion uses the local 7-Zip engine. RAR is read-only; RAR creation and encrypted archives are not supported. Contents are inspected before extraction. Unsafe paths, links, special files and colliding names are rejected. Limits are 100,000 listed entries and 20 GiB of declared uncompressed data; extraction also checks free disk space and the actual extracted tree.

Conversions and edits use **Settings → Save results**: beside the original, or in a `DragShift` subfolder. Archive extraction always creates a unique **`<name> Extracted`** folder beside the original archive. Existing results receive a numbered name rather than being replaced.

Video, audio and archive processing runs in background workers with a progress window and **Cancel**. Their batch conversions roll back results from earlier files when a later file fails or the batch is cancelled. Original files are kept. Closing a busy progress window requests cancellation. Result notifications offer **Open**, **Show** and **Undo**; Undo sends newly created results to the Recycle Bin.

All conversion engines process local files; DragShift does not upload media or download an engine during a job. **Listen to original** and result **Open** launch the system's associated app. The glass retains local background snapshots, blur and refraction, with a neutral light tint and simple controls. Snapshots stay in memory for decoration and are not saved or sent. On Windows, native acrylic is the fallback when a snapshot is unavailable.

Windows and editors are visible in ordinary screenshots by default. On Windows, exclusion from capture is limited to the synchronous background grab and is cleared before glass rendering continues; a clean cached backdrop prevents recursive self-capture when a new background cannot be captured safely. `DRAGSHIFT_RECORDING=1` disables even that brief exclusion and reuses the clean backdrop while a window moves. It is not required for ordinary screenshots.

## Run, verify and build from source

Use a Python virtual environment. The Windows dependency snapshot is in `requirements-windows-lock.txt`; the base runtime requirements are in `requirements.txt`.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-windows-lock.txt
.\.venv\Scripts\python.exe -m dragshift
```

Place FFmpeg/FFprobe, FFglitch 0.10.2 (`ffgac` and `ffedit`), 7-Zip, and ImageMagick 7 (`magick`, built with `lqr`) in `bin/`, with their notices. For a Windows 7-Zip sidecar, keep `7z.dll` beside `7z.exe`. Source archives omit these engine binaries; obtain them separately from the sources below.

Engine discovery accepts `DRAGSHIFT_FFMPEG`, `DRAGSHIFT_FFPROBE`, `DRAGSHIFT_FFGAC`, `DRAGSHIFT_FFEDIT`, `DRAGSHIFT_7Z` and `DRAGSHIFT_MAGICK`, then bundled `bin/` and PATH. The archive engine also checks an existing `C:\Program Files\7-Zip\7z.exe` installation.

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m dragshift --selftest
.\.venv\Scripts\python.exe -m dragshift --video-selftest
.\.venv\Scripts\python.exe -m dragshift --files-selftest
.\.venv\Scripts\python.exe -m PyInstaller DragShift.spec --noconfirm
ISCC.exe installer\DragShift.iss
```

The Inno Setup recipe creates `dist/DragShift-Setup.exe`; the local custom distribution names its installer `DragShift-Files-Setup.exe`. Synthetic integration checks exercise real codecs and archive round trips when their engines are installed. Run the self-test switches on the frozen executable too when validating a package. Tests that require optional media engines skip when those engines are absent. The files.9 desktop run linked above includes package creation and bilingual frozen media checks on all four native targets; Linux also passed all 19 installed XFCE file-manager scenarios. Mac packages were checked on macOS 15; earlier system versions have not been validated. Mac packages are ad-hoc signed and have not been notarized with an Apple Developer ID. The local files.9 Windows installer was also installed and checked in both languages.

Release CI uses `python packaging/media_engines.py --stage` before tests: native FFmpeg/FFprobe, FFglitch 0.10.2, 7-Zip, ImageMagick 7.1.2-34 Q16 with PNG/lqr. Windows downloads Gyan essentials and the verified official ImageMagick archive. On Unix, install FFmpeg, 7-Zip, a compiler, make, pkg-config, libpng and liblqr development packages first; the helper builds ImageMagick without external coder modules. macOS selects the complete Homebrew `ffmpeg-full` build on Apple Silicon and `ffmpeg@7` on Intel, with each keg explicitly selected before staging. The Intel helper also stages SDL3 beside the engines for SDL2-compat's dynamic loader. The staging gate checks the actual required encoders, decoder and filters, including Vorbis, VP9, MP3 and audio glitch support. Intel dependencies may require a longer source build. PyInstaller scans ELF/Mach-O engines and relocates their shared-library dependencies. The helper records download hashes in bundled `EngineVersions.json` and fails when required engines/delegates are absent. The workflow checks both languages and actual frozen media operations on Windows, macOS Intel/ARM and Debian 12 jobs. Versioned public releases require all native jobs to succeed and refer to the exact tested commit.

Windows logs are written to `%LOCALAPPDATA%\DragShift\log.txt`. Settings are available from the tray menu; closing an editor leaves the tray app running. A normal launch or second launch only shows a short reminder to use Shift-drag; `--quiet` launches silently.

## Engines and licenses

- [FFmpeg documentation](https://ffmpeg.org/documentation.html), [FFmpeg source](https://github.com/FFmpeg/FFmpeg), and [Gyan Windows builds](https://www.gyan.dev/ffmpeg/builds/).
- [FFglitch documentation](https://ffglitch.org/), [FFglitch 0.10 source repository](https://github.com/ramiropolla/ffglitch-core/tree/ffedit-0.10), and [0.10.2 source archive](https://ffglitch.org/pub/src/ffglitch-0.10.2.tar.xz).
- [7-Zip downloads](https://www.7-zip.org/), [7-Zip source](https://github.com/ip7z/7zip), and [license](https://www.7-zip.org/license.txt).
- [ImageMagick](https://imagemagick.org/), [ImageMagick source](https://github.com/ImageMagick/ImageMagick), and [liblqr](https://github.com/ImageMagick/lqr).
- Application source: upstream [MIT license](LICENSE). Bundled engines and Python dependencies retain their own licenses; see [THIRD_PARTY.md](THIRD_PARTY.md) before redistributing a package.
