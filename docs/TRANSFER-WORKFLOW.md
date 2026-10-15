# Getting research files from your PC to the cloud session

The development session runs in a cloud container. It cannot see `C:\Game Files\`, and the
multi-gigabyte ISO is too big to upload through chat. Instead, the inspector produces small,
targeted packages. Only the files needed for the next technical step are transferred.

## What each package contains

| Package | Contents | Sensitivity |
|---|---|---|
| `drop-NNN-metadata.zip` | File names, sizes, sector numbers, detected formats, archive tables of contents, a few header bytes per file, the report | Technical metadata only, no game assets. Still, send it privately rather than committing it |
| `drop-NNN-gamedata.zip` | First 4 KB of each file, `SYSTEM.CNF`, the boot executable, and any `-Extract` files | **Copyrighted game data. Private channels only. Never commit it to the repository** |
| `drop-NNN.manifest.json` | SHA-256 of every package | Safe anywhere. The cloud session uses it to verify downloads |

## ⚠ Repository visibility

On 2026-10-15 the GitHub API reported **`yourpalbones/Madden06` as PUBLIC**, although the project
brief says it should be private. Nothing has been changed. Visibility is only changed with your
permission. Until you make it private:

* do **not** upload any `gamedata` package to the repository, its releases or its issues
* the inspector prints a red warning if it detects the repository is public

To make it private: repository page → **Settings** → **General** → scroll to **Danger Zone** →
**Change repository visibility** → **Make private**.

## Option 1 (recommended once the repository is private): draft GitHub release

Draft releases are not part of git history. They are visible only to people with write access to the
repository, accept files up to 2 GB each, and can be deleted at any time.

1. Go to https://github.com/yourpalbones/Madden06/releases and click **Draft a new release**.
2. Click **Choose a tag**, type the drop name (for example `drop-001`) and choose **Create new tag on publish**.
   The tag is not created while the release stays a draft.
3. Title: `drop-001`. Drag the zip files and the `manifest.json` from `C:\Game Files\Madden06Research\packages\`
   into the **Attach binaries** box and wait for the uploads to finish.
4. Click **Save draft**. Do **not** click *Publish release*.
5. Tell the cloud session in chat: *"drop-001 is uploaded as a draft release"*.
6. When the session confirms it downloaded and verified the files, delete the draft release.

If you have the GitHub CLI (`gh`) installed and logged in, the inspector can do steps 1–4 for you with
`-UploadWithGh`. It refuses to upload unless the repository is confirmed private.

> Status: the cloud session can read this repository's releases. It cannot create releases itself,
> so the download step has not been tested end-to-end yet. It will be verified on the first real drop,
> and if it fails, use Option 2.

## Option 2: time-limited share link (OneDrive, Google Drive or Dropbox)

1. Upload the zip(s) to your cloud drive.
2. Create a share link that **anyone with the link** can view. If the service offers it, set an
   **expiration date** (one or two days) and allow downloads.
3. Paste the link and the SHA-256 lines printed by the inspector into the chat.
4. The session downloads the file and checks the SHA-256 against the manifest.
5. Delete the link (or the file) once the session confirms.

Share links are unlisted rather than authenticated, so keep them short-lived and never post them publicly.

## Option 3: no upload at all. Run a Claude Code session on your own PC

Claude Code can run directly on your Windows machine, where it can read the ISO and the research
folder itself. Either use the Claude Desktop app, or install Claude Code, open a terminal in
`C:\Game Files\Madden06Research` and run `claude remote-control`. That session then appears in the
Claude Code app and you can continue from there. This is also the most practical way to run the
later ISO-rebuild and PCSX2 test steps.

## Rules the tooling follows

* The original ISO is opened read-only and never mounted, modified or uploaded.
* Packages contain only what the current step needs. The first drop is metadata, 4 KB headers,
  `SYSTEM.CNF` and the boot executable.
* Every package has a SHA-256 in the manifest so corrupted or incomplete transfers are detected.
* Game data is never committed to git. `.gitignore` blocks ISO/DAT/DB/ELF and research folders as a safety net.
