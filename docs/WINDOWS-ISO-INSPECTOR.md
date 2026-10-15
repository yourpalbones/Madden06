# Windows ISO Inspector: how to run it

`tools/windows/Inspect-MaddenIso.ps1` reads your Madden NFL 06 PS2 disc image and produces an
inventory, a research report and small transfer packages for the cloud development session.

**The ISO is never modified.** It is opened read-only (`FileAccess.Read`, `FileShare.Read`) and is
not mounted. The script checks the ISO's size and last-modified time before and after the run and
reports the result.

## Requirements

* Windows 10 or 11, using the built-in **Windows PowerShell 5.1**. PowerShell 7 also works.
* Nothing to install. The ISO9660 reader is compiled from C# source embedded in the script.
* About 50 MB of free disk space for the first run. Extracting large archives later needs more.
* The ISO at `C:\Game Files\Madden NFL 06 (USA).iso`. Any other path can be passed with `-IsoPath`.

## Step 1: download the tools

1. Open https://github.com/yourpalbones/Madden06 in your browser while logged in.
2. Click **Code → Download ZIP**.
3. Extract the zip to a folder, for example `C:\Game Files\Madden06Tools\`.
   The script is then at `C:\Game Files\Madden06Tools\Madden06-main\tools\windows\Inspect-MaddenIso.ps1`.

## Step 2: run it

**Option A, double-click.** Open the `tools\windows` folder and double-click **`Run-Inspector.cmd`**.
A console window opens, runs the inspection and waits for a key press at the end.

**Option B, PowerShell.** Open the Start menu, type `PowerShell` and open **Windows PowerShell**, then:

```powershell
cd "C:\Game Files\Madden06Tools\Madden06-main\tools\windows"
powershell -ExecutionPolicy Bypass -File .\Inspect-MaddenIso.ps1
```

`-ExecutionPolicy Bypass` applies to this one command only. It does not change your system settings.
If Windows says the file is blocked because it came from the internet, run
`Unblock-File .\Inspect-MaddenIso.ps1` once, or use Option A.

A first run takes a few minutes. Most of the time goes into computing SHA-256 hashes of every file
on the disc (about 4 GB of reading). Add `-SkipHashes` for a quicker run.

## What it creates

Everything goes under `C:\Game Files\Madden06Research\`:

| Folder / file | Contents |
|---|---|
| `inventory\files.csv` | Every file on the disc: path, size, sector (LBA), detected format, entropy, first 32 bytes, SHA-256 |
| `inventory\directories.csv` | Every directory with its sector |
| `inventory\lba_map.csv` | Physical layout of the disc in sector order, with gaps (needed later for ISO rebuilding) |
| `inventory\archive_chunks.csv` | Chunk layout (`TERF`/`DIR1`/`COMP`/`DATA`…) of every EA TERF `.DAT` archive |
| `inventory\archive_entries.csv` | Table of contents of every TERF/BIGF archive: offsets, sizes, compression algorithm, inner format; nested archives included |
| `inventory\textures.csv` | Images listed inside uncompressed SHPS (EA SSH) or TIM2 containers |
| `inventory\disc.json` | Volume descriptors, SYSTEM.CNF, boot executable name |
| `reports\research_report.md` | Human-readable summary with candidate portrait, roster and texture files |
| `samples\heads\…` | The first 4 KB of every file, used to identify formats |
| `extracted\…` | Full copies of `SYSTEM.CNF`, the boot executable and any `-Extract` files |
| `packages\drop-001-metadata.zip` | inventory + reports. Technical metadata only |
| `packages\drop-001-gamedata.zip` | head samples + extracted files. **Contains copyrighted game data, so keep it private** |
| `packages\drop-001.manifest.json` | SHA-256 of each package |

## Step 3: send the results to the cloud session

See [TRANSFER-WORKFLOW.md](TRANSFER-WORKFLOW.md).

## Later runs: extracting specific files

Once the inventory shows where the portraits and roster data live, the cloud session will ask for
specific files. For example:

```powershell
powershell -ExecutionPolicy Bypass -File .\Inspect-MaddenIso.ps1 -SkipHashes -Extract "UIS_*.DAT,*.DB"
```

Put several patterns in **one quoted string separated by commas**. This form works from PowerShell,
from `cmd.exe` and through `Run-Inspector.cmd`. Each run creates the next `drop-NNN` package
automatically. Patterns match either the file name (`UIS_PLYR.DAT`) or the full disc path
(`/DATA/UIS_PLYR.DAT`). They are not case-sensitive.

## All options

| Option | Meaning |
|---|---|
| `-IsoPath <path>` | ISO location (default `C:\Game Files\Madden NFL 06 (USA).iso`) |
| `-OutputRoot <path>` | Research folder (default `C:\Game Files\Madden06Research`) |
| `-Extract "<patterns>"` | Copy matching files out in full, e.g. `-Extract "UIS_*.DAT,TEMPLATE.DAT"` |
| `-ListOnly` | Only print the file list to the console |
| `-HeadBytes <n>` | Bytes saved per file in `samples\heads` (default 4096; `0` disables) |
| `-SkipHashes` | Skip per-file SHA-256 (extracted files are still hashed) |
| `-HashIso` | Also hash the whole ISO (to compare with the Redump database) |
| `-NoBootElf` | Do not copy the PS2 boot executable |
| `-NoPackage` | Do not build zip packages |
| `-DropName <name>` | Package name instead of the next `drop-NNN` |
| `-MaxPartMB <n>` | Split packages into parts of at most this size (default 1900 MB) |
| `-Offline` | Skip the anonymous GitHub check of whether the repository is private |
| `-UploadWithGh` | Upload packages to a **draft** release with the GitHub CLI. Refused unless the repository is private |

## Troubleshooting

* **"The ISO was not found"**: check the exact file name, including spaces and parentheses, or pass `-IsoPath`.
* **"No ISO9660 volume descriptor found"**: the file is not a plain ISO. `.bin/.cue` 2352-byte images
  are supported, but compressed formats (`.cso`, `.chd`, `.7z`) must be decompressed first.
* **Red text about `Add-Type`**: please copy the whole error into the chat. It means the embedded
  reader did not compile on your PowerShell version, which the cloud session can fix.
* **Very slow**: add `-SkipHashes`.
