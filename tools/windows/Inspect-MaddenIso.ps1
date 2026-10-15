<#
.SYNOPSIS
    Madden NFL 06 (PS2) ISO inspection and research-extraction utility.

.DESCRIPTION
    Reads the PS2 disc image strictly READ-ONLY (the ISO is opened with
    FileAccess.Read / FileShare.Read and is never mounted or written), parses the
    ISO9660 file system directly (so it can record each file's sector/LBA, which
    Windows mounting does not expose) and produces:

      inventory\files.csv            every file: path, size, LBA, detected format, entropy, header bytes, SHA-256
      inventory\directories.csv      every directory
      inventory\lba_map.csv          on-disc layout ordered by sector, with gaps (needed for ISO rebuilding)
      inventory\archive_chunks.csv   chunk layout of every EA TERF (.DAT) archive
      inventory\archive_entries.csv  table of contents of every TERF / BIGF archive (nested archives included)
      inventory\textures.csv         images found in uncompressed SHPS (EA SSH) / TIM2 containers
      inventory\disc.json            disc metadata (volume descriptors, SYSTEM.CNF, boot file)
      reports\research_report.md     human-readable research report with candidate lists
      samples\heads\...              first N bytes of every file (format research)
      extracted\...                  full copies of selected files (SYSTEM.CNF, boot ELF, -Extract patterns)
      packages\drop-NNN-*.zip        transfer packages + manifest with SHA-256 hashes

    The original ISO is verified unchanged (size + last-write time) at the end of the run.

.PARAMETER IsoPath
    Path to the original disc image. Default: C:\Game Files\Madden NFL 06 (USA).iso

.PARAMETER OutputRoot
    Research directory. Default: C:\Game Files\Madden06Research

.PARAMETER Extract
    Wildcard patterns of files to copy out of the ISO in full, comma-separated in one string,
    e.g. -Extract "UIS_*.DAT,*.DB". Patterns are matched against both the file name and the full
    ISO path (e.g. '/DATA/*.DAT'), case-insensitively.

.PARAMETER ListOnly
    Only print the file listing to the console (no hashing, no packages).

.PARAMETER HeadBytes
    Number of leading bytes of every file saved to samples\heads (0 disables). Default 4096.

.PARAMETER SkipHashes
    Do not compute per-file SHA-256 hashes (faster; hashes are still computed for extracted files).

.PARAMETER HashIso
    Also compute the SHA-256 of the entire ISO image (for comparison with Redump; slow).

.PARAMETER NoBootElf
    Do not copy the PS2 boot executable (named in SYSTEM.CNF) into extracted\.

.PARAMETER NoPackage
    Do not build transfer packages.

.PARAMETER DropName
    Name for this run's transfer package, e.g. drop-002. Default: next free drop-NNN.

.PARAMETER MaxPartMB
    Maximum size of one package zip part in MB. Default 1900 (GitHub release assets are limited to 2 GB).

.PARAMETER Offline
    Skip the (unauthenticated, read-only) GitHub check of whether the project repository is private.

.PARAMETER UploadWithGh
    Upload the packages to a DRAFT release in the project repository using an installed and
    logged-in GitHub CLI (gh). Refused unless the repository is confirmed PRIVATE.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\Inspect-MaddenIso.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\Inspect-MaddenIso.ps1 -SkipHashes -Extract "UIS_*.DAT,TEMPLATE.DAT"
#>
[CmdletBinding(PositionalBinding = $false)]
param(
    [string]   $IsoPath    = 'C:\Game Files\Madden NFL 06 (USA).iso',
    [string]   $OutputRoot = 'C:\Game Files\Madden06Research',
    [string[]] $Extract    = @(),
    [switch]   $ListOnly,
    [int]      $HeadBytes  = 4096,
    [switch]   $SkipHashes,
    [switch]   $HashIso,
    [switch]   $NoBootElf,
    [switch]   $NoPackage,
    [string]   $DropName   = '',
    [int]      $MaxPartMB  = 1900,
    [switch]   $Offline,
    [switch]   $UploadWithGh,
    [string]   $Repository = 'yourpalbones/Madden06'
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$ScriptVersion = '0.1.0'

# Accept "-Extract 'A','B'" (PowerShell array) as well as "-Extract A,B" / "-Extract 'A;B'" (one string,
# which is what arrives through powershell.exe -File and Run-Inspector.cmd).
$Extract = @($Extract | ForEach-Object { $_ -split '[,;]' } | ForEach-Object { $_.Trim().Trim("'", '"') } | Where-Object { $_ })

# ---------------------------------------------------------------------------------------------
# Core reader (C#, compiled once per PowerShell session). Written for C# 5 / .NET Framework 4.5
# so that it compiles under the Windows PowerShell 5.1 that ships with Windows 10/11.
# ---------------------------------------------------------------------------------------------
$CoreSource = @'
using System;
using System.IO;
using System.Text;
using System.Collections.Generic;
using System.Security.Cryptography;

namespace Madden06Research.V1
{
    public class IsoEntry
    {
        public string Path { get; set; }
        public string ParentPath { get; set; }
        public string Name { get; set; }
        public string RawName { get; set; }
        public bool IsDirectory { get; set; }
        public long Lba { get; set; }
        public long Size { get; set; }
        public int Flags { get; set; }
        public int ExtentCount { get; set; }
        public string Recorded { get; set; }
        public long RecordOffset { get; set; }
    }

    public class Signature
    {
        public string Tag { get; set; }
        public string Description { get; set; }
        public Signature(string tag, string description) { Tag = tag; Description = description; }
    }

    public class ArchiveChunk
    {
        public string Container { get; set; }
        public string Type { get; set; }
        public long Offset { get; set; }
        public long Size { get; set; }
    }

    public class ArchiveEntry
    {
        public string Container { get; set; }
        public string EntryPath { get; set; }
        public string Format { get; set; }
        public int Depth { get; set; }
        public int Index { get; set; }
        public string Name { get; set; }
        public long AbsoluteOffset { get; set; }
        public long OffsetInParent { get; set; }
        public long StoredSize { get; set; }
        public long Algorithm { get; set; }
        public long UncompressedSize { get; set; }
        public string Tag { get; set; }
        public string HeadHex { get; set; }
        public string Problem { get; set; }
    }

    public class TextureEntry
    {
        public string Source { get; set; }
        public string Container { get; set; }
        public int Index { get; set; }
        public string Name { get; set; }
        public long Offset { get; set; }
        public string Format { get; set; }
        public int Width { get; set; }
        public int Height { get; set; }
        public string Details { get; set; }
    }

    public class ArchiveScan
    {
        public List<ArchiveChunk> Chunks = new List<ArchiveChunk>();
        public List<ArchiveEntry> Entries = new List<ArchiveEntry>();
        public List<TextureEntry> Textures = new List<TextureEntry>();
        public List<string> Problems = new List<string>();
    }

    /// <summary>Random-access window onto a byte range of an ISO file (or a part of it).</summary>
    public class Window
    {
        private readonly IsoImage iso;
        private readonly IsoEntry entry;
        public long Base { get; private set; }
        public long Length { get; private set; }
        public Window(IsoImage iso, IsoEntry entry, long baseOffset, long length)
        {
            this.iso = iso; this.entry = entry; Base = baseOffset; Length = length;
        }
        public byte[] Read(long offset, int count)
        {
            if (offset < 0 || offset >= Length || count <= 0) return new byte[0];
            long n = Math.Min((long)count, Length - offset);
            byte[] buf = new byte[n];
            int got = iso.ReadExtent(entry.Lba, Base + offset, buf, 0, (int)n);
            if (got < n) { byte[] t = new byte[got]; Array.Copy(buf, t, got); return t; }
            return buf;
        }
        public Window Sub(long offset, long length)
        {
            return new Window(iso, entry, Base + offset, Math.Max(0, Math.Min(length, Length - offset)));
        }
    }

    public sealed class IsoImage : IDisposable
    {
        private FileStream fs;
        public string ImagePath { get; private set; }
        public long ImageLength { get; private set; }
        public int RawSectorSize { get; private set; }
        public int DataOffsetInSector { get; private set; }
        public int LogicalBlockSize { get; private set; }
        public string SystemId { get; private set; }
        public string VolumeId { get; private set; }
        public string VolumeSetId { get; private set; }
        public string PublisherId { get; private set; }
        public string PreparerId { get; private set; }
        public string ApplicationId { get; private set; }
        public string CreationDate { get; private set; }
        public string ModificationDate { get; private set; }
        public long VolumeSpaceSize { get; private set; }
        public long PathTableSize { get; private set; }
        public long PathTableLLba { get; private set; }
        public long PathTableMLba { get; private set; }
        public long RootLba { get; private set; }
        public long RootSize { get; private set; }
        public bool HasJoliet { get; private set; }
        public bool HasUdf { get; private set; }
        public List<string> VolumeDescriptors = new List<string>();
        public List<string> Warnings = new List<string>();

        public IsoImage(string path)
        {
            ImagePath = System.IO.Path.GetFullPath(path);
            // READ-ONLY access. Other programs may read the file at the same time but not write to it.
            fs = new FileStream(ImagePath, FileMode.Open, FileAccess.Read, FileShare.Read, 1 << 16, FileOptions.RandomAccess);
            ImageLength = fs.Length;
            DetectLayout();
            ReadVolumeDescriptors();
        }

        public void Dispose()
        {
            if (fs != null) { fs.Dispose(); fs = null; }
        }

        private int ReadAt(long position, byte[] buffer, int offset, int count)
        {
            if (position >= ImageLength) return 0;
            fs.Position = position;
            int total = 0;
            while (count > 0)
            {
                int r = fs.Read(buffer, offset, count);
                if (r <= 0) break;
                total += r; offset += r; count -= r;
            }
            return total;
        }

        private void DetectLayout()
        {
            int[][] candidates = new int[][] { new int[] { 2048, 0 }, new int[] { 2352, 16 }, new int[] { 2352, 24 } };
            byte[] b = new byte[6];
            foreach (int[] c in candidates)
            {
                long pos = 16L * c[0] + c[1];
                if (ReadAt(pos, b, 0, 6) == 6 && Encoding.ASCII.GetString(b, 1, 5) == "CD001")
                {
                    RawSectorSize = c[0]; DataOffsetInSector = c[1];
                    return;
                }
            }
            throw new InvalidDataException("No ISO9660 volume descriptor found (expected 'CD001' at sector 16). This does not look like an ISO9660 disc image.");
        }

        /// <summary>Reads bytes from an extent starting at logical block 'lba', at byte position 'pos' within it.</summary>
        public int ReadExtent(long lba, long pos, byte[] buffer, int offset, int count)
        {
            if (RawSectorSize == 2048)
                return ReadAt(lba * 2048L + pos, buffer, offset, count);
            int total = 0;
            while (count > 0)
            {
                long blk = lba + pos / 2048;
                int within = (int)(pos % 2048);
                int n = Math.Min(count, 2048 - within);
                int r = ReadAt(blk * RawSectorSize + DataOffsetInSector + within, buffer, offset, n);
                total += r;
                if (r < n) break;
                pos += n; offset += n; count -= n;
            }
            return total;
        }

        public long AbsoluteOffset(long lba, long pos)
        {
            if (RawSectorSize == 2048) return lba * 2048L + pos;
            return (lba + pos / 2048) * RawSectorSize + DataOffsetInSector + (pos % 2048);
        }

        public byte[] ReadBlock(long lba)
        {
            byte[] b = new byte[2048];
            int r = ReadExtent(lba, 0, b, 0, 2048);
            if (r < 2048) Array.Resize(ref b, r);
            return b;
        }

        private static string Str(byte[] b, int off, int len)
        {
            if (off + len > b.Length) return "";
            return Encoding.ASCII.GetString(b, off, len).Trim(new char[] { ' ', '\0' });
        }

        public static long LE32(byte[] b, int o) { return (long)((uint)(b[o] | (b[o + 1] << 8) | (b[o + 2] << 16) | (b[o + 3] << 24))); }
        public static int LE16(byte[] b, int o) { return b[o] | (b[o + 1] << 8); }

        private void ReadVolumeDescriptors()
        {
            bool sawTerminator = false;
            for (long lba = 16; lba < 16 + 128; lba++)
            {
                byte[] b = ReadBlock(lba);
                if (b.Length < 2048) break;
                string id = Encoding.ASCII.GetString(b, 1, 5);
                if (id == "CD001")
                {
                    int type = b[0];
                    if (type == 1 && RootLba == 0)
                    {
                        VolumeDescriptors.Add(string.Format("LBA {0}: Primary Volume Descriptor", lba));
                        SystemId = Str(b, 8, 32);
                        VolumeId = Str(b, 40, 32);
                        VolumeSpaceSize = LE32(b, 80);
                        LogicalBlockSize = LE16(b, 128);
                        PathTableSize = LE32(b, 132);
                        PathTableLLba = LE32(b, 140);
                        PathTableMLba = (long)(((uint)b[148] << 24) | ((uint)b[149] << 16) | ((uint)b[150] << 8) | b[151]);
                        RootLba = LE32(b, 156 + 2);
                        RootSize = LE32(b, 156 + 10);
                        VolumeSetId = Str(b, 190, 128);
                        PublisherId = Str(b, 318, 128);
                        PreparerId = Str(b, 446, 128);
                        ApplicationId = Str(b, 574, 128);
                        CreationDate = Str(b, 813, 17);
                        ModificationDate = Str(b, 830, 17);
                        if (LogicalBlockSize != 2048)
                            Warnings.Add(string.Format("Logical block size is {0}, expected 2048. Results assume 2048.", LogicalBlockSize));
                    }
                    else if (type == 2)
                    {
                        bool joliet = b[88] == 0x25 && b[89] == 0x2F && (b[90] == 0x40 || b[90] == 0x43 || b[90] == 0x45);
                        if (joliet) HasJoliet = true;
                        VolumeDescriptors.Add(string.Format("LBA {0}: Supplementary Volume Descriptor{1}", lba, joliet ? " (Joliet)" : ""));
                    }
                    else if (type == 0) VolumeDescriptors.Add(string.Format("LBA {0}: Boot Record", lba));
                    else if (type == 3) VolumeDescriptors.Add(string.Format("LBA {0}: Volume Partition Descriptor", lba));
                    else if (type == 255) { VolumeDescriptors.Add(string.Format("LBA {0}: Volume Descriptor Set Terminator", lba)); sawTerminator = true; }
                    else VolumeDescriptors.Add(string.Format("LBA {0}: unknown descriptor type {1}", lba, type));
                }
                else if (id == "BEA01" || id == "NSR02" || id == "NSR03" || id == "TEA01")
                {
                    VolumeDescriptors.Add(string.Format("LBA {0}: UDF volume recognition '{1}'", lba, id));
                    if (id == "NSR02" || id == "NSR03") HasUdf = true;
                    if (id == "TEA01") break;
                }
                else if (sawTerminator) break;
                else break;
            }
            if (RootLba == 0) throw new InvalidDataException("No ISO9660 Primary Volume Descriptor found.");
        }

        private static string DirDate(byte[] b, int o)
        {
            if (o + 7 > b.Length) return "";
            int y = 1900 + b[o];
            int tz = (sbyte)b[o + 6] * 15;
            return string.Format("{0:0000}-{1:00}-{2:00} {3:00}:{4:00}:{5:00} UTC{6}{7:00}:{8:00}",
                y, b[o + 1], b[o + 2], b[o + 3], b[o + 4], b[o + 5], tz < 0 ? "-" : "+", Math.Abs(tz) / 60, Math.Abs(tz) % 60);
        }

        public List<IsoEntry> Walk()
        {
            List<IsoEntry> result = new List<IsoEntry>();
            Dictionary<long, bool> visited = new Dictionary<long, bool>();
            Stack<IsoEntry> stack = new Stack<IsoEntry>();
            IsoEntry root = new IsoEntry();
            root.Path = "/"; root.ParentPath = ""; root.Name = ""; root.RawName = ""; root.IsDirectory = true;
            root.Lba = RootLba; root.Size = RootSize; root.Flags = 2; root.ExtentCount = 1; root.Recorded = "";
            root.RecordOffset = AbsoluteOffset(16, 156);
            result.Add(root);
            stack.Push(root);
            while (stack.Count > 0)
            {
                IsoEntry dir = stack.Pop();
                if (visited.ContainsKey(dir.Lba)) { Warnings.Add("Directory visited twice (loop?): " + dir.Path); continue; }
                visited[dir.Lba] = true;
                if (dir.Size <= 0 || dir.Size > 64L * 1024 * 1024) { Warnings.Add("Implausible directory size for " + dir.Path); continue; }
                byte[] data = new byte[dir.Size];
                int got = ReadExtent(dir.Lba, 0, data, 0, data.Length);
                if (got < data.Length) Warnings.Add("Directory extent truncated: " + dir.Path);
                int pos = 0;
                IsoEntry multi = null;
                while (pos < got)
                {
                    int len = data[pos];
                    if (len == 0) { pos = ((pos / 2048) + 1) * 2048; continue; }
                    if (len < 34 || pos + len > got)
                    {
                        Warnings.Add(string.Format("Bad directory record in {0} at +{1}", dir.Path, pos));
                        pos = ((pos / 2048) + 1) * 2048;
                        continue;
                    }
                    int nameLen = data[pos + 32];
                    if (nameLen == 1 && (data[pos + 33] == 0 || data[pos + 33] == 1)) { pos += len; continue; }
                    if (33 + nameLen > len) { Warnings.Add("Bad name length in " + dir.Path); pos += len; continue; }
                    string raw = Encoding.ASCII.GetString(data, pos + 33, nameLen);
                    int flags = data[pos + 25];
                    bool isDir = (flags & 2) != 0;
                    long extent = LE32(data, pos + 2);
                    long size = LE32(data, pos + 10);
                    if (multi != null && multi.RawName == raw)
                    {
                        multi.Size += size; multi.ExtentCount++;
                        if ((flags & 0x80) == 0) multi = null;
                        pos += len;
                        continue;
                    }
                    string name = raw;
                    int semi = name.IndexOf(';');
                    if (semi >= 0) name = name.Substring(0, semi);
                    if (!isDir && name.EndsWith(".")) name = name.Substring(0, name.Length - 1);
                    IsoEntry e = new IsoEntry();
                    e.Name = name; e.RawName = raw; e.IsDirectory = isDir; e.Lba = extent; e.Size = size;
                    e.Flags = flags; e.ExtentCount = 1; e.Recorded = DirDate(data, pos + 18);
                    e.ParentPath = dir.Path;
                    e.Path = (dir.Path == "/" ? "/" : dir.Path + "/") + name;
                    e.RecordOffset = AbsoluteOffset(dir.Lba, pos);
                    result.Add(e);
                    if ((flags & 0x80) != 0) multi = e;
                    if (isDir) stack.Push(e);
                    pos += len;
                }
            }
            foreach (IsoEntry e in result)
                if (e.ExtentCount > 1)
                    Warnings.Add("Multi-extent file (data assumed contiguous): " + e.Path);
            return result;
        }

        public byte[] ReadFile(IsoEntry e, long offset, int count)
        {
            if (offset >= e.Size) return new byte[0];
            int n = (int)Math.Min((long)count, e.Size - offset);
            byte[] b = new byte[n];
            int r = ReadExtent(e.Lba, offset, b, 0, n);
            if (r < n) Array.Resize(ref b, r);
            return b;
        }

        public Window OpenWindow(IsoEntry e)
        {
            return new Window(this, e, 0, e.Size);
        }

        public static string Hex(byte[] h)
        {
            StringBuilder sb = new StringBuilder(h.Length * 2);
            foreach (byte x in h) sb.Append(x.ToString("x2"));
            return sb.ToString();
        }

        public string HashFile(IsoEntry e)
        {
            using (SHA256 sha = SHA256.Create())
            {
                byte[] buf = new byte[1 << 20];
                long pos = 0;
                while (pos < e.Size)
                {
                    int n = (int)Math.Min((long)buf.Length, e.Size - pos);
                    int r = ReadExtent(e.Lba, pos, buf, 0, n);
                    if (r <= 0) throw new IOException("Unexpected end of image while hashing " + e.Path);
                    sha.TransformBlock(buf, 0, r, null, 0);
                    pos += r;
                }
                sha.TransformFinalBlock(new byte[0], 0, 0);
                return Hex(sha.Hash);
            }
        }

        public string HashImage()
        {
            using (SHA256 sha = SHA256.Create())
            {
                byte[] buf = new byte[1 << 20];
                long pos = 0;
                while (pos < ImageLength)
                {
                    int r = ReadAt(pos, buf, 0, (int)Math.Min((long)buf.Length, ImageLength - pos));
                    if (r <= 0) break;
                    sha.TransformBlock(buf, 0, r, null, 0);
                    pos += r;
                }
                sha.TransformFinalBlock(new byte[0], 0, 0);
                return Hex(sha.Hash);
            }
        }

        /// <summary>Copies a range of an ISO file to a new file on disk and returns the SHA-256 of what was written.</summary>
        public string ExtractRange(IsoEntry e, long offset, long count, string destination)
        {
            string full = System.IO.Path.GetFullPath(destination);
            if (string.Equals(full, ImagePath, StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Refusing to write to the source ISO path.");
            string dir = System.IO.Path.GetDirectoryName(full);
            if (!Directory.Exists(dir)) Directory.CreateDirectory(dir);
            count = Math.Max(0, Math.Min(count, e.Size - offset));
            using (SHA256 sha = SHA256.Create())
            using (FileStream o = new FileStream(full, FileMode.Create, FileAccess.Write, FileShare.None))
            {
                byte[] buf = new byte[1 << 20];
                long done = 0;
                while (done < count)
                {
                    int n = (int)Math.Min((long)buf.Length, count - done);
                    int r = ReadExtent(e.Lba, offset + done, buf, 0, n);
                    if (r <= 0) throw new IOException("Unexpected end of image while extracting " + e.Path);
                    o.Write(buf, 0, r);
                    sha.TransformBlock(buf, 0, r, null, 0);
                    done += r;
                }
                sha.TransformFinalBlock(new byte[0], 0, 0);
                return Hex(sha.Hash);
            }
        }

        public string ExtractFile(IsoEntry e, string destination)
        {
            return ExtractRange(e, 0, e.Size, destination);
        }
    }

    public static class Analysis
    {
        private static bool StartsWith(byte[] h, string ascii)
        {
            if (h.Length < ascii.Length) return false;
            for (int i = 0; i < ascii.Length; i++) if (h[i] != (byte)ascii[i]) return false;
            return true;
        }

        private static bool StartsWith(byte[] h, int offset, byte[] sig)
        {
            if (h.Length < offset + sig.Length) return false;
            for (int i = 0; i < sig.Length; i++) if (h[offset + i] != sig[i]) return false;
            return true;
        }

        public static double Entropy(byte[] data)
        {
            if (data.Length == 0) return 0;
            int[] counts = new int[256];
            foreach (byte b in data) counts[b]++;
            double e = 0;
            foreach (int c in counts)
            {
                if (c == 0) continue;
                double p = (double)c / data.Length;
                e -= p * Math.Log(p, 2);
            }
            return Math.Round(e, 3);
        }

        public static string Ascii(byte[] h, int max)
        {
            StringBuilder sb = new StringBuilder();
            for (int i = 0; i < h.Length && i < max; i++) sb.Append(h[i] >= 0x20 && h[i] < 0x7F ? (char)h[i] : '.');
            return sb.ToString();
        }

        public static Signature Identify(byte[] h, string name)
        {
            string ext = "";
            int dot = name.LastIndexOf('.');
            if (dot >= 0) ext = name.Substring(dot + 1).ToUpperInvariant();
            if (h.Length == 0) return new Signature("empty", "Zero-length file");
            if (StartsWith(h, "TERF")) return new Signature("TERF", "EA Tiburon TERF archive (Madden .DAT container)");
            if (h.Length >= 5 && h[0] == 0x44 && h[1] == 0x42 && h[2] == 0x00 && (h[4] == 0 || h[4] == 1))
                return new Signature("TDB", "EA Tiburon database (TDB: rosters/franchise tables)");
            if (StartsWith(h, "SHPS")) return new Signature("SHPS", "EA shape/texture file, PS2 (SSH)");
            if (StartsWith(h, "SHPI")) return new Signature("SHPI", "EA shape/texture file, PC (FSH)");
            if (StartsWith(h, "SHPP")) return new Signature("SHPP", "EA shape/texture file, PS1");
            if (StartsWith(h, "SHPX")) return new Signature("SHPX", "EA shape/texture file, Xbox");
            if (StartsWith(h, "SHPM")) return new Signature("SHPM", "EA shape/texture file (SHPM)");
            if (StartsWith(h, "TIM2")) return new Signature("TIM2", "Sony TIM2 texture");
            if (StartsWith(h, "BIGF")) return new Signature("BIGF", "EA BIG/VIV archive (BIGF)");
            if (StartsWith(h, "BIG4")) return new Signature("BIG4", "EA BIG archive (BIG4)");
            if (StartsWith(h, "BGFA")) return new Signature("BGFA", "EA AST archive (BGFA)");
            if (h.Length >= 2 && (h[0] & 0x3E) == 0x10 && h[1] == 0xFB) return new Signature("REFPACK", "EA RefPack compressed data (10 FB)");
            if (h.Length >= 6 && (h[4] & 0x3E) == 0x10 && h[5] == 0xFB) return new Signature("REFPACK@4", "EA RefPack compressed data after 4-byte prefix");
            if (StartsWith(h, "SCHl") || StartsWith(h, "SHEN") || StartsWith(h, "SHFR") || StartsWith(h, "SHGE") || StartsWith(h, "SHUS"))
                return new Signature("EA-AUDIO", "EA SCHl audio/stream");
            if (StartsWith(h, "MVhd") || StartsWith(h, "MV0K") || StartsWith(h, "MADk") || StartsWith(h, "MADm") || StartsWith(h, "MADe"))
                return new Signature("EA-VIDEO", "EA video (VP6/MAD)");
            if (StartsWith(h, 0, new byte[] { 0x00, 0x00, 0x01, 0xBA })) return new Signature("MPEG-PS", "MPEG program stream (PSS video)");
            if (StartsWith(h, 0, new byte[] { 0x7F, 0x45, 0x4C, 0x46 }))
                return ext == "IRX" ? new Signature("IRX", "PS2 IOP module (ELF)") : new Signature("ELF", "ELF executable (PS2 EE)");
            if (StartsWith(h, "VAGp")) return new Signature("VAG", "Sony VAG ADPCM audio");
            if (StartsWith(h, "IECSsreV") || StartsWith(h, "IECSdheH")) return new Signature("SONY-SND", "Sony sound bank (VAB/HD)");
            if (StartsWith(h, "RIFF")) return new Signature("RIFF", "RIFF container (WAV/AVI)");
            if (StartsWith(h, 0, new byte[] { 0x50, 0x4B, 0x03, 0x04 })) return new Signature("ZIP", "ZIP archive");
            if (StartsWith(h, 0, new byte[] { 0x89, 0x50, 0x4E, 0x47 })) return new Signature("PNG", "PNG image");
            if (StartsWith(h, 0, new byte[] { 0xFF, 0xD8, 0xFF })) return new Signature("JPEG", "JPEG image");
            if (StartsWith(h, "DDS ")) return new Signature("DDS", "DirectDraw Surface texture");
            if (StartsWith(h, "GIF8")) return new Signature("GIF", "GIF image");
            if (StartsWith(h, "BM") && h.Length >= 6 && ext == "BMP") return new Signature("BMP", "Windows bitmap");
            if (StartsWith(h, "Sce") || StartsWith(h, "PS2X")) return new Signature("SONY", "Sony system data");
            bool allZero = true;
            foreach (byte b in h) if (b != 0) { allZero = false; break; }
            if (allZero) return new Signature("zero", "Leading bytes are all zero");
            int printable = 0;
            int lim = Math.Min(h.Length, 512);
            for (int i = 0; i < lim; i++) if ((h[i] >= 0x20 && h[i] < 0x7F) || h[i] == 9 || h[i] == 10 || h[i] == 13) printable++;
            if (lim > 0 && printable == lim) return new Signature("text", "Plain text");
            return new Signature("unknown", "Unrecognized");
        }

        private static long U32(byte[] b, int o, bool be)
        {
            if (o + 4 > b.Length) return -1;
            if (be) return (long)(((uint)b[o] << 24) | ((uint)b[o + 1] << 16) | ((uint)b[o + 2] << 8) | b[o + 3]);
            return IsoImage.LE32(b, o);
        }

        private static int U16(byte[] b, int o, bool be)
        {
            if (o + 2 > b.Length) return -1;
            return be ? ((b[o] << 8) | b[o + 1]) : (b[o] | (b[o + 1] << 8));
        }

        private static bool IsTag(byte[] b, int o)
        {
            if (o + 4 > b.Length) return false;
            for (int i = 0; i < 4; i++) { byte c = b[o + i]; if (c < 0x20 || c > 0x7E) return false; }
            return true;
        }

        /// <summary>Scans a file for TERF/BIGF archives (recursively into stored entries) and SHPS/TIM2 textures.</summary>
        public static ArchiveScan Scan(IsoImage iso, IsoEntry file, int maxDepth)
        {
            ArchiveScan scan = new ArchiveScan();
            Window w = iso.OpenWindow(file);
            ScanWindow(w, file.Path, file.Path, 0, maxDepth, scan);
            return scan;
        }

        private static void ScanWindow(Window w, string isoPath, string label, int depth, int maxDepth, ArchiveScan scan)
        {
            byte[] h = w.Read(0, 16);
            if (h.Length < 4) return;
            if (StartsWith(h, "TERF")) ParseTerf(w, isoPath, label, depth, maxDepth, scan);
            else if (StartsWith(h, "BIGF") || StartsWith(h, "BIG4")) ParseBig(w, isoPath, label, depth, maxDepth, scan);
            else if (StartsWith(h, "SHPS") || StartsWith(h, "SHPI") || StartsWith(h, "SHPP") || StartsWith(h, "SHPX")) ParseShape(w, label, scan);
            else if (StartsWith(h, "TIM2")) ParseTim2(w, label, scan);
        }

        private static ArchiveEntry MakeEntry(Window w, string isoPath, string label, string format, int depth, int index,
                                              long offset, long size, long algo, long xsize, string name)
        {
            ArchiveEntry e = new ArchiveEntry();
            e.Container = label; e.Format = format; e.Depth = depth; e.Index = index; e.Name = name;
            e.EntryPath = label + "#" + index.ToString("D4");
            e.OffsetInParent = offset; e.AbsoluteOffset = w.Base + offset; e.StoredSize = size;
            e.Algorithm = algo; e.UncompressedSize = xsize; e.Problem = "";
            if (offset < 0 || size < 0 || offset + size > w.Length)
            {
                e.Problem = "entry exceeds container bounds";
                e.Tag = ""; e.HeadHex = "";
                return e;
            }
            byte[] head = w.Read(offset, (int)Math.Min(16L, size));
            e.HeadHex = IsoImage.Hex(head);
            e.Tag = Identify(head, name ?? "").Tag;
            return e;
        }

        private static void ParseTerf(Window w, string isoPath, string label, int depth, int maxDepth, ArchiveScan scan)
        {
            byte[] h = w.Read(0, 16);
            if (h.Length < 16) { scan.Problems.Add(label + ": TERF header truncated"); return; }
            long le = U32(h, 4, false), be = U32(h, 4, true);
            bool bigEndian = !(le >= 8 && le <= w.Length) && (be >= 8 && be <= w.Length);
            int files = U16(h, 14, bigEndian);
            if (files < 0 || files > 200000) { scan.Problems.Add(label + ": implausible TERF file count " + files); return; }
            long[] dOff = null, dSize = null, cAlg = null, cX = null;
            long dataBase = -1;
            long off = 0;
            int guard = 0;
            while (off + 8 <= w.Length && guard++ < 512)
            {
                byte[] ch = w.Read(off, 8);
                if (!IsTag(ch, 0)) { scan.Problems.Add(string.Format("{0}: non-text chunk tag at 0x{1:X}", label, off)); break; }
                string type = Encoding.ASCII.GetString(ch, 0, 4);
                long size = U32(ch, 4, bigEndian);
                ArchiveChunk c = new ArchiveChunk();
                c.Container = label; c.Type = type; c.Offset = w.Base + off; c.Size = size;
                scan.Chunks.Add(c);
                if (type == "DIR1" || type == "COMP")
                {
                    byte[] t = w.Read(off + 8, (int)Math.Min((long)files * 8, Math.Max(0, w.Length - off - 8)));
                    long[] a = new long[files], b2 = new long[files];
                    for (int i = 0; i < files && i * 8 + 8 <= t.Length; i++)
                    {
                        a[i] = U32(t, i * 8, bigEndian); b2[i] = U32(t, i * 8 + 4, bigEndian);
                    }
                    if (type == "DIR1") { dOff = a; dSize = b2; } else { cAlg = a; cX = b2; }
                }
                else if (type == "DATA")
                {
                    dataBase = off;
                }
                if (size < 8) { scan.Problems.Add(string.Format("{0}: chunk {1} has size {2} (<8); stopping chunk walk", label, type, size)); break; }
                off += size;
            }
            if (dOff == null) { scan.Problems.Add(label + ": TERF without DIR1 chunk"); return; }
            if (dataBase < 0) { scan.Problems.Add(label + ": TERF without DATA chunk"); return; }
            for (int i = 0; i < files; i++)
            {
                long algo = cAlg != null ? cAlg[i] : 0;
                long xs = cX != null ? cX[i] : 0;
                ArchiveEntry e = MakeEntry(w, isoPath, label, bigEndian ? "TERF-BE" : "TERF", depth, i, dataBase + dOff[i], dSize[i], algo, xs, null);
                scan.Entries.Add(e);
                if (e.Problem == "" && algo == 0 && dSize[i] > 0 && depth < maxDepth)
                    ScanWindow(w.Sub(dataBase + dOff[i], dSize[i]), isoPath, e.EntryPath, depth + 1, maxDepth, scan);
            }
        }

        private static void ParseBig(Window w, string isoPath, string label, int depth, int maxDepth, ArchiveScan scan)
        {
            byte[] h = w.Read(0, 16);
            long count = U32(h, 8, true);
            long tocLen = U32(h, 12, true);
            if (count <= 0 || count > 100000 || tocLen <= 16 || tocLen > w.Length || tocLen > 64L * 1024 * 1024)
            {
                scan.Problems.Add(label + ": BIG header not understood");
                return;
            }
            byte[] toc = w.Read(0, (int)tocLen);
            int p = 16;
            for (int i = 0; i < count; i++)
            {
                if (p + 9 > toc.Length) { scan.Problems.Add(label + ": BIG TOC truncated"); break; }
                long o = U32(toc, p, true), s = U32(toc, p + 4, true);
                p += 8;
                int start = p;
                while (p < toc.Length && toc[p] != 0) p++;
                string name = Encoding.ASCII.GetString(toc, start, p - start);
                p++;
                ArchiveEntry e = MakeEntry(w, isoPath, label, "BIGF", depth, i, o, s, 0, s, name);
                scan.Entries.Add(e);
                if (e.Problem == "" && depth < maxDepth)
                    ScanWindow(w.Sub(o, s), isoPath, e.EntryPath, depth + 1, maxDepth, scan);
            }
        }

        private static void ParseShape(Window w, string label, ArchiveScan scan)
        {
            byte[] h = w.Read(0, 16);
            long count = U32(h, 8, false);
            if (count <= 0 || count > 10000) { scan.Problems.Add(label + ": shape header not understood"); return; }
            byte[] dir = w.Read(16, (int)(count * 8));
            for (int i = 0; i < count && i * 8 + 8 <= dir.Length; i++)
            {
                string nm = Ascii(new byte[] { dir[i * 8], dir[i * 8 + 1], dir[i * 8 + 2], dir[i * 8 + 3] }, 4);
                long o = U32(dir, i * 8 + 4, false);
                byte[] bh = w.Read(o, 16);
                TextureEntry t = new TextureEntry();
                t.Source = label; t.Container = Encoding.ASCII.GetString(h, 0, 4); t.Index = i; t.Name = nm; t.Offset = w.Base + o;
                if (bh.Length >= 16)
                {
                    t.Format = "type 0x" + bh[0].ToString("X2");
                    t.Width = U16(bh, 4, false); t.Height = U16(bh, 6, false);
                    t.Details = "block header " + IsoImage.Hex(bh);
                }
                else t.Details = "block header truncated";
                scan.Textures.Add(t);
            }
        }

        private static void ParseTim2(Window w, string label, ArchiveScan scan)
        {
            byte[] h = w.Read(0, 16);
            int count = U16(h, 6, false);
            long p = h.Length >= 5 && h[5] == 1 ? 128 : 16;
            for (int i = 0; i < count && i < 4096; i++)
            {
                byte[] ph = w.Read(p, 48);
                if (ph.Length < 48) { scan.Problems.Add(label + ": TIM2 picture header truncated"); break; }
                long total = U32(ph, 0, false);
                TextureEntry t = new TextureEntry();
                t.Source = label; t.Container = "TIM2"; t.Index = i; t.Name = ""; t.Offset = w.Base + p;
                t.Width = U16(ph, 0x14, false); t.Height = U16(ph, 0x16, false);
                t.Format = string.Format("clutType 0x{0:X2} imageType 0x{1:X2}", ph[0x12], ph[0x13]);
                t.Details = string.Format("total {0} clut {1} image {2} header {3} clutColors {4} mipmaps {5}",
                    total, U32(ph, 4, false), U32(ph, 8, false), U16(ph, 12, false), U16(ph, 14, false), ph[0x11]);
                scan.Textures.Add(t);
                if (total <= 0) break;
                p += total;
            }
        }
    }
}
'@

# ---------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------
function Write-Step([string] $Message) { Write-Host ''; Write-Host ('==> ' + $Message) -ForegroundColor Cyan }
function Write-Info([string] $Message) { Write-Host ('    ' + $Message) }
function Write-Warn2([string] $Message) { Write-Host ('    WARNING: ' + $Message) -ForegroundColor Yellow }

function New-Dir([string] $Path) {
    if (-not (Test-Path -LiteralPath $Path)) { New-Item -ItemType Directory -Path $Path -Force | Out-Null }
    return $Path
}

function Format-Size([double] $Bytes) {
    if ($Bytes -ge 1GB) { return ('{0:N2} GB' -f ($Bytes / 1GB)) }
    if ($Bytes -ge 1MB) { return ('{0:N2} MB' -f ($Bytes / 1MB)) }
    if ($Bytes -ge 1KB) { return ('{0:N1} KB' -f ($Bytes / 1KB)) }
    return ('{0} B' -f $Bytes)
}

function ConvertTo-LocalPath([string] $Root, [string] $IsoFilePath) {
    $relative = $IsoFilePath.TrimStart('/').Replace('/', [string][System.IO.Path]::DirectorySeparatorChar)
    return [System.IO.Path]::Combine($Root, $relative)
}

function Test-Pattern([object] $Entry, [string[]] $Patterns) {
    foreach ($p in $Patterns) {
        if ([string]::IsNullOrWhiteSpace($p)) { continue }
        if ($Entry.Name -like $p -or $Entry.Path -like $p -or $Entry.Path.TrimStart('/') -like $p) { return $true }
    }
    return $false
}

# Keyword heuristics used only to build candidate lists for the report (never trusted as fact).
$Heuristics = [ordered]@{
    'portrait'  = 'PORT|PLYR|PLAYR|PHOT|PIC|HEAD|FACE|MUG|UIS'
    'database'  = 'ROST|TEMPL|FRAN|STAT|CAREER|LEAG|DRAFT|\.DB$|DB\.|SAVE|DEFLT|DEFAULT'
    'interface' = '^UI|FE_|FRONT|MENU|SCRN|SCREEN'
}

function Get-Category([object] $Row) {
    switch -Regex ($Row.Format) {
        '^TDB$'                 { return 'database' }
        '^(TERF|BIGF|BIG4|BGFA)$' { return 'archive' }
        '^(SHP.|TIM2|PNG|JPEG|DDS|GIF|BMP)$' { return 'texture/image' }
        '^(EA-AUDIO|VAG|SONY-SND|RIFF)$' { return 'audio' }
        '^(EA-VIDEO|MPEG-PS)$'  { return 'video' }
        '^(ELF|IRX)$'           { return 'executable/module' }
        '^REFPACK'              { return 'compressed' }
        '^text$'                { return 'text/config' }
    }
    return 'other'
}

# ---------------------------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------------------------
$started = Get-Date
Write-Host ''
Write-Host ('Madden NFL 06 (PS2) ISO Inspector v{0}' -f $ScriptVersion) -ForegroundColor Green
Write-Host ('PowerShell {0} on {1}' -f $PSVersionTable.PSVersion, [System.Environment]::OSVersion.VersionString)

Write-Step 'Validating the ISO path'
if (-not (Test-Path -LiteralPath $IsoPath -PathType Leaf)) {
    Write-Host ''
    Write-Host ('ERROR: The ISO was not found at: {0}' -f $IsoPath) -ForegroundColor Red
    Write-Host '       Check the path, or pass it explicitly:  -IsoPath "D:\path\to\Madden NFL 06 (USA).iso"' -ForegroundColor Red
    exit 2
}
$isoItem = Get-Item -LiteralPath $IsoPath
$isoFull = $isoItem.FullName
$isoLengthBefore = $isoItem.Length
$isoWriteBefore = $isoItem.LastWriteTimeUtc
Write-Info ('ISO:  {0}' -f $isoFull)
Write-Info ('Size: {0} ({1:N0} bytes)' -f (Format-Size $isoLengthBefore), $isoLengthBefore)
Write-Info ('Last modified (UTC): {0:yyyy-MM-dd HH:mm:ss}' -f $isoWriteBefore)

$outFull = [System.IO.Path]::GetFullPath($OutputRoot)
if ($outFull.TrimEnd('\', '/') -ieq $isoFull) { throw 'OutputRoot must not be the ISO file itself.' }

Write-Step 'Loading the read-only ISO reader'
if (-not ('Madden06Research.V1.IsoImage' -as [type])) {
    Add-Type -TypeDefinition $CoreSource -Language CSharp
}
Write-Info 'OK'

$iso = $null
try {
    $iso = New-Object Madden06Research.V1.IsoImage($isoFull)
    Write-Info ('Layout: {0}-byte sectors (data offset {1}); logical block {2}' -f $iso.RawSectorSize, $iso.DataOffsetInSector, $iso.LogicalBlockSize)
    Write-Info ('Volume ID: "{0}"  System ID: "{1}"' -f $iso.VolumeId, $iso.SystemId)
    Write-Info ('Volume space: {0:N0} blocks ({1}); Joliet: {2}; UDF bridge: {3}' -f $iso.VolumeSpaceSize, (Format-Size ($iso.VolumeSpaceSize * 2048)), $iso.HasJoliet, $iso.HasUdf)

    Write-Step 'Reading the ISO9660 directory tree'
    $entries = $iso.Walk()
    $files = @($entries | Where-Object { -not $_.IsDirectory } | Sort-Object Path)
    $dirs = @($entries | Where-Object { $_.IsDirectory } | Sort-Object Path)
    $totalBytes = ($files | Measure-Object -Property Size -Sum).Sum
    if ($null -eq $totalBytes) { $totalBytes = 0 }
    Write-Info ('{0:N0} files in {1:N0} directories, {2} of file data' -f $files.Count, $dirs.Count, (Format-Size $totalBytes))
    foreach ($w in $iso.Warnings) { Write-Warn2 $w }

    if ($ListOnly) {
        $files | Select-Object Path, Size, Lba | Format-Table -AutoSize | Out-String -Width 200 | Write-Host
        return
    }

    # Output folders
    $dirInventory = New-Dir ([System.IO.Path]::Combine($outFull, 'inventory'))
    $dirReports   = New-Dir ([System.IO.Path]::Combine($outFull, 'reports'))
    $dirExtracted = New-Dir ([System.IO.Path]::Combine($outFull, 'extracted'))
    $dirSamples   = New-Dir ([System.IO.Path]::Combine($outFull, 'samples'))
    $dirPackages  = New-Dir ([System.IO.Path]::Combine($outFull, 'packages'))
    $dirHeads     = [System.IO.Path]::Combine($dirSamples, 'heads')
    Write-Info ('Output: {0}' -f $outFull)

    # SYSTEM.CNF / boot executable
    Write-Step 'Reading SYSTEM.CNF'
    $systemCnfText = ''
    $bootPath = ''
    $cnf = $files | Where-Object { $_.Path -ieq '/SYSTEM.CNF' } | Select-Object -First 1
    if ($null -ne $cnf) {
        $systemCnfText = [System.Text.Encoding]::ASCII.GetString($iso.ReadFile($cnf, 0, 4096))
        foreach ($line in ($systemCnfText -split "`r?`n")) { if ($line.Trim()) { Write-Info $line.Trim() } }
        $m = [regex]::Match($systemCnfText, 'BOOT2\s*=\s*cdrom0:\\?([^;\r\n]+)', 'IgnoreCase')
        if ($m.Success) { $bootPath = '/' + ($m.Groups[1].Value.Trim() -replace '\\', '/') }
    } else {
        Write-Warn2 'SYSTEM.CNF not found in the root directory - this may not be a PS2 disc image.'
    }
    $bootEntry = $null
    if ($bootPath) {
        $bootEntry = $files | Where-Object { $_.Path -ieq $bootPath } | Select-Object -First 1
        if ($null -eq $bootEntry) { Write-Warn2 ('Boot file {0} named in SYSTEM.CNF was not found.' -f $bootPath) }
        else { Write-Info ('Boot executable: {0} ({1})' -f $bootEntry.Path, (Format-Size $bootEntry.Size)) }
    }

    # Per-file analysis
    Write-Step 'Identifying file formats'
    $rows = New-Object System.Collections.Generic.List[object]
    $scans = @{}
    $allChunks = New-Object System.Collections.Generic.List[object]
    $allArchiveEntries = New-Object System.Collections.Generic.List[object]
    $allTextures = New-Object System.Collections.Generic.List[object]
    $archiveProblems = New-Object System.Collections.Generic.List[string]
    $i = 0
    $lastProgress = [DateTime]::MinValue
    foreach ($f in $files) {
        $i++
        if (([DateTime]::Now - $lastProgress).TotalMilliseconds -gt 250) {
            Write-Progress -Activity 'Identifying file formats' -Status $f.Path -PercentComplete ([int](100 * $i / [Math]::Max(1, $files.Count)))
            $lastProgress = [DateTime]::Now
        }
        $head = $iso.ReadFile($f, 0, 65536)
        $sig = [Madden06Research.V1.Analysis]::Identify($head, $f.Name)
        $head32 = New-Object byte[] ([Math]::Min(32, $head.Length))
        [Array]::Copy($head, $head32, $head32.Length)
        $ext = ''
        $dot = $f.Name.LastIndexOf('.')
        if ($dot -ge 0) { $ext = $f.Name.Substring($dot + 1).ToUpperInvariant() }
        $row = [pscustomobject][ordered]@{
            Path         = $f.Path
            Directory    = $f.ParentPath
            Name         = $f.Name
            Extension    = $ext
            Size         = $f.Size
            Lba          = $f.Lba
            Sectors      = [long][Math]::Ceiling($f.Size / 2048.0)
            EndLba       = $f.Lba + [long][Math]::Ceiling($f.Size / 2048.0)
            Recorded     = $f.Recorded
            Format       = $sig.Tag
            Description  = $sig.Description
            Category     = ''
            Hints        = ''
            Entropy64K   = [Madden06Research.V1.Analysis]::Entropy($head)
            HeadHex      = [Madden06Research.V1.IsoImage]::Hex($head32)
            HeadAscii    = [Madden06Research.V1.Analysis]::Ascii($head32, 32)
            ArchiveItems = ''
            Sha256       = ''
            RecordOffset = $f.RecordOffset
        }
        $row.Category = Get-Category $row
        $hints = @()
        foreach ($k in $Heuristics.Keys) { if ($f.Name -match $Heuristics[$k]) { $hints += $k } }
        $row.Hints = ($hints -join ';')
        if ($sig.Tag -in @('TERF', 'BIGF', 'BIG4', 'SHPS', 'SHPI', 'SHPP', 'SHPX', 'TIM2')) {
            $scan = [Madden06Research.V1.Analysis]::Scan($iso, $f, 4)
            $scans[$f.Path] = $scan
            foreach ($c in $scan.Chunks) { $allChunks.Add($c) }
            foreach ($e in $scan.Entries) { $allArchiveEntries.Add($e) }
            foreach ($t in $scan.Textures) { $allTextures.Add($t) }
            foreach ($p in $scan.Problems) { $archiveProblems.Add($p) }
            $row.ArchiveItems = @($scan.Entries | Where-Object { $_.Depth -eq 0 }).Count
        }
        $rows.Add($row)
    }
    Write-Progress -Activity 'Identifying file formats' -Completed
    Write-Info ('Archives parsed: {0}; archive entries listed: {1:N0}; textures listed: {2:N0}' -f $scans.Count, $allArchiveEntries.Count, $allTextures.Count)
    foreach ($p in ($archiveProblems | Select-Object -First 20)) { Write-Warn2 $p }

    # Hashes
    if (-not $SkipHashes) {
        Write-Step ('Computing SHA-256 of all {0:N0} files (reads {1}; use -SkipHashes to skip)' -f $files.Count, (Format-Size $totalBytes))
        $doneBytes = 0
        $i = 0
        foreach ($f in $files) {
            $i++
            if (([DateTime]::Now - $lastProgress).TotalMilliseconds -gt 250) {
                $pct = if ($totalBytes -gt 0) { [int](100 * $doneBytes / $totalBytes) } else { 100 }
                Write-Progress -Activity 'Hashing files (SHA-256)' -Status ('{0} ({1})' -f $f.Path, (Format-Size $f.Size)) -PercentComplete $pct
                $lastProgress = [DateTime]::Now
            }
            $rows[$i - 1].Sha256 = $iso.HashFile($f)
            $doneBytes += $f.Size
        }
        Write-Progress -Activity 'Hashing files (SHA-256)' -Completed
        Write-Info 'Done'
    }

    $isoHash = ''
    if ($HashIso) {
        Write-Step 'Computing SHA-256 of the whole ISO image (this reads the entire file)'
        $isoHash = $iso.HashImage()
        Write-Info $isoHash
    }

    # Head samples
    $headCount = 0
    if ($HeadBytes -gt 0) {
        Write-Step ('Saving the first {0:N0} bytes of every file to samples\heads' -f $HeadBytes)
        foreach ($f in $files) {
            $dest = (ConvertTo-LocalPath $dirHeads $f.Path) + '.head'
            [void]$iso.ExtractRange($f, 0, [Math]::Min([long]$HeadBytes, $f.Size), $dest)
            $headCount++
        }
        Write-Info ('{0:N0} head samples written' -f $headCount)
    }

    # Extraction
    Write-Step 'Extracting selected files'
    $toExtract = New-Object System.Collections.Generic.List[object]
    if ($null -ne $cnf) { $toExtract.Add($cnf) }
    if ($null -ne $bootEntry -and -not $NoBootElf) { $toExtract.Add($bootEntry) }
    if ($Extract.Count -gt 0) {
        foreach ($f in $files) { if ((Test-Pattern $f $Extract) -and -not $toExtract.Contains($f)) { $toExtract.Add($f) } }
        $matched = @($toExtract | Where-Object { Test-Pattern $_ $Extract }).Count
        Write-Info ('Patterns {0} matched {1} file(s)' -f ($Extract -join ', '), $matched)
        if ($matched -eq 0) { Write-Warn2 'No files matched the -Extract patterns. Check inventory\files.csv for exact names.' }
    }
    $extractedRows = New-Object System.Collections.Generic.List[object]
    foreach ($f in $toExtract) {
        $dest = ConvertTo-LocalPath $dirExtracted $f.Path
        Write-Info ('{0}  ({1})' -f $f.Path, (Format-Size $f.Size))
        $sha = $iso.ExtractFile($f, $dest)
        $row = $rows | Where-Object { $_.Path -eq $f.Path } | Select-Object -First 1
        if ($row.Sha256 -and $row.Sha256 -ne $sha) { throw ('Hash mismatch after extracting {0}' -f $f.Path) }
        $row.Sha256 = $sha
        $extractedRows.Add([pscustomobject][ordered]@{ Path = $f.Path; LocalFile = $dest; Size = $f.Size; Sha256 = $sha })
    }

    # LBA map (layout on disc)
    Write-Step 'Writing inventory'
    $layout = New-Object System.Collections.Generic.List[object]
    $layout.Add([pscustomobject]@{ Kind = 'system'; Path = '(system area + volume descriptors)'; Lba = 0; Sectors = 16 + $iso.VolumeDescriptors.Count; Size = (16 + $iso.VolumeDescriptors.Count) * 2048 })
    if ($iso.PathTableLLba -gt 0) { $layout.Add([pscustomobject]@{ Kind = 'pathtable'; Path = '(L path table)'; Lba = $iso.PathTableLLba; Sectors = [long][Math]::Ceiling($iso.PathTableSize / 2048.0); Size = $iso.PathTableSize }) }
    if ($iso.PathTableMLba -gt 0) { $layout.Add([pscustomobject]@{ Kind = 'pathtable'; Path = '(M path table)'; Lba = $iso.PathTableMLba; Sectors = [long][Math]::Ceiling($iso.PathTableSize / 2048.0); Size = $iso.PathTableSize }) }
    foreach ($d in $dirs) { $layout.Add([pscustomobject]@{ Kind = 'directory'; Path = $d.Path; Lba = $d.Lba; Sectors = [long][Math]::Ceiling($d.Size / 2048.0); Size = $d.Size }) }
    # Zero-length files occupy no sectors (their LBA is often 0), so they are left out of the layout.
    foreach ($f in $files) { if ($f.Size -gt 0) { $layout.Add([pscustomobject]@{ Kind = 'file'; Path = $f.Path; Lba = $f.Lba; Sectors = [long][Math]::Ceiling($f.Size / 2048.0); Size = $f.Size }) } }
    $layoutSorted = @($layout | Sort-Object Lba, Path)
    $lbaRows = New-Object System.Collections.Generic.List[object]
    for ($k = 0; $k -lt $layoutSorted.Count; $k++) {
        $cur = $layoutSorted[$k]
        $end = $cur.Lba + [Math]::Max(1, $cur.Sectors)
        $next = if ($k + 1 -lt $layoutSorted.Count) { $layoutSorted[$k + 1].Lba } else { $iso.VolumeSpaceSize }
        $lbaRows.Add([pscustomobject][ordered]@{
            Lba = $cur.Lba; EndLba = $end; Sectors = $cur.Sectors; Size = $cur.Size; Kind = $cur.Kind; Path = $cur.Path
            GapSectorsAfter = ($next - $end)
            SlackBytes = ($cur.Sectors * 2048 - $cur.Size)
        })
    }
    $overlaps = @($lbaRows | Where-Object { $_.GapSectorsAfter -lt 0 -and $_.Kind -eq 'file' })

    $rows | Export-Csv -LiteralPath ([System.IO.Path]::Combine($dirInventory, 'files.csv')) -NoTypeInformation -Encoding UTF8
    $dirs | Select-Object Path, Lba, Size, Recorded, RecordOffset | Export-Csv -LiteralPath ([System.IO.Path]::Combine($dirInventory, 'directories.csv')) -NoTypeInformation -Encoding UTF8
    $lbaRows | Export-Csv -LiteralPath ([System.IO.Path]::Combine($dirInventory, 'lba_map.csv')) -NoTypeInformation -Encoding UTF8
    $allChunks | Export-Csv -LiteralPath ([System.IO.Path]::Combine($dirInventory, 'archive_chunks.csv')) -NoTypeInformation -Encoding UTF8
    $allArchiveEntries | Export-Csv -LiteralPath ([System.IO.Path]::Combine($dirInventory, 'archive_entries.csv')) -NoTypeInformation -Encoding UTF8
    $allTextures | Export-Csv -LiteralPath ([System.IO.Path]::Combine($dirInventory, 'textures.csv')) -NoTypeInformation -Encoding UTF8
    $extractedRows | Select-Object Path, Size, Sha256 | Export-Csv -LiteralPath ([System.IO.Path]::Combine($dirInventory, 'extracted.csv')) -NoTypeInformation -Encoding UTF8

    $disc = [ordered]@{
        tool              = 'Inspect-MaddenIso.ps1'
        toolVersion       = $ScriptVersion
        generatedUtc      = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
        isoFileName       = $isoItem.Name
        isoSize           = $isoLengthBefore
        isoSha256         = $isoHash
        rawSectorSize     = $iso.RawSectorSize
        dataOffset        = $iso.DataOffsetInSector
        logicalBlockSize  = $iso.LogicalBlockSize
        systemId          = $iso.SystemId
        volumeId          = $iso.VolumeId
        volumeSetId       = $iso.VolumeSetId
        publisherId       = $iso.PublisherId
        preparerId        = $iso.PreparerId
        applicationId     = $iso.ApplicationId
        creationDate      = $iso.CreationDate
        modificationDate  = $iso.ModificationDate
        volumeSpaceBlocks = $iso.VolumeSpaceSize
        pathTableSize     = $iso.PathTableSize
        pathTableLLba     = $iso.PathTableLLba
        pathTableMLba     = $iso.PathTableMLba
        rootLba           = $iso.RootLba
        rootSize          = $iso.RootSize
        joliet            = $iso.HasJoliet
        udfBridge         = $iso.HasUdf
        volumeDescriptors = @($iso.VolumeDescriptors)
        warnings          = @($iso.Warnings)
        archiveProblems   = @($archiveProblems)
        systemCnf         = $systemCnfText
        bootFile          = $bootPath
        fileCount         = $files.Count
        directoryCount    = $dirs.Count
        totalFileBytes    = $totalBytes
        lastFileEndLba    = ($lbaRows | Measure-Object -Property EndLba -Maximum).Maximum
    }
    $disc | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath ([System.IO.Path]::Combine($dirInventory, 'disc.json')) -Encoding UTF8
    if ($systemCnfText) { Set-Content -LiteralPath ([System.IO.Path]::Combine($dirReports, 'system_cnf.txt')) -Value $systemCnfText -Encoding ASCII }

    # -----------------------------------------------------------------------------------------
    # Research report
    # -----------------------------------------------------------------------------------------
    Write-Step 'Writing research report'
    $sb = New-Object System.Text.StringBuilder
    function Add-Line([string] $Text = '') { [void]$sb.AppendLine($Text) }
    function Add-Table([object[]] $Items, [string[]] $Columns) {
        if ($Items.Count -eq 0) { Add-Line '_none_'; Add-Line; return }
        Add-Line ('| ' + ($Columns -join ' | ') + ' |')
        Add-Line ('|' + (($Columns | ForEach-Object { '---' }) -join '|') + '|')
        foreach ($it in $Items) {
            $cells = foreach ($c in $Columns) { ([string]$it.$c) -replace '\|', '\|' }
            Add-Line ('| ' + ($cells -join ' | ') + ' |')
        }
        Add-Line
    }

    Add-Line '# Madden NFL 06 (PS2) - ISO research report'
    Add-Line
    Add-Line ('Generated {0} by Inspect-MaddenIso.ps1 v{1} (PowerShell {2}).' -f (Get-Date -Format 'yyyy-MM-dd HH:mm'), $ScriptVersion, $PSVersionTable.PSVersion)
    Add-Line
    Add-Line '## Disc'
    Add-Line
    Add-Line ('* Image file: `{0}` - {1:N0} bytes ({2})' -f $isoItem.Name, $isoLengthBefore, (Format-Size $isoLengthBefore))
    if ($isoHash) { Add-Line ('* Image SHA-256: `{0}`' -f $isoHash) }
    Add-Line ('* Sector layout: {0}-byte raw sectors, data offset {1}, logical block size {2}' -f $iso.RawSectorSize, $iso.DataOffsetInSector, $iso.LogicalBlockSize)
    Add-Line ('* System ID: `{0}`; Volume ID: `{1}`; Volume set: `{2}`' -f $iso.SystemId, $iso.VolumeId, $iso.VolumeSetId)
    Add-Line ('* Publisher: `{0}`; Preparer: `{1}`; Application: `{2}`' -f $iso.PublisherId, $iso.PreparerId, $iso.ApplicationId)
    Add-Line ('* Created: `{0}`; Modified: `{1}`' -f $iso.CreationDate, $iso.ModificationDate)
    Add-Line ('* Volume space: {0:N0} blocks; root directory at LBA {1}; path table {2} bytes at LBA {3}' -f $iso.VolumeSpaceSize, $iso.RootLba, $iso.PathTableSize, $iso.PathTableLLba)
    Add-Line ('* Joliet: {0}; UDF bridge: {1}' -f $iso.HasJoliet, $iso.HasUdf)
    Add-Line ('* Volume descriptors: {0}' -f ($iso.VolumeDescriptors -join '; '))
    Add-Line ('* Boot file (SYSTEM.CNF BOOT2): `{0}`' -f $bootPath)
    Add-Line
    if ($systemCnfText) { Add-Line '```'; Add-Line $systemCnfText.Trim(); Add-Line '```'; Add-Line }

    Add-Line '## Totals'
    Add-Line
    Add-Line ('* {0:N0} files, {1:N0} directories, {2:N0} bytes of file data ({3})' -f $files.Count, $dirs.Count, $totalBytes, (Format-Size $totalBytes))
    Add-Line ('* Last used sector: {0:N0} of {1:N0}' -f $disc.lastFileEndLba, $iso.VolumeSpaceSize)
    Add-Line ('* Overlapping extents: {0}' -f $overlaps.Count)
    Add-Line
    Add-Line '### By detected format'
    Add-Line
    $byFormat = $rows | Group-Object Format | ForEach-Object {
        [pscustomobject]@{ Format = $_.Name; Files = $_.Count; Bytes = ('{0:N0}' -f ($_.Group | Measure-Object Size -Sum).Sum); Example = ($_.Group | Select-Object -First 1).Path }
    } | Sort-Object Files -Descending
    Add-Table @($byFormat) @('Format', 'Files', 'Bytes', 'Example')
    Add-Line '### By extension'
    Add-Line
    $byExt = $rows | Group-Object Extension | ForEach-Object {
        [pscustomobject]@{ Extension = $(if ($_.Name) { $_.Name } else { '(none)' }); Files = $_.Count; Bytes = ('{0:N0}' -f ($_.Group | Measure-Object Size -Sum).Sum); Formats = (($_.Group | Group-Object Format | ForEach-Object { $_.Name }) -join ', ') }
    } | Sort-Object Files -Descending
    Add-Table @($byExt) @('Extension', 'Files', 'Bytes', 'Formats')
    Add-Line '### By directory'
    Add-Line
    $byDir = $rows | Group-Object Directory | ForEach-Object {
        [pscustomobject]@{ Directory = $_.Name; Files = $_.Count; Bytes = ('{0:N0}' -f ($_.Group | Measure-Object Size -Sum).Sum) }
    } | Sort-Object Directory
    Add-Table @($byDir) @('Directory', 'Files', 'Bytes')

    Add-Line '## Largest files'
    Add-Line
    Add-Table @($rows | Sort-Object Size -Descending | Select-Object -First 30 | ForEach-Object { [pscustomobject]@{ Path = $_.Path; Size = ('{0:N0}' -f $_.Size); Lba = $_.Lba; Format = $_.Format; Entropy = $_.Entropy64K } }) @('Path', 'Size', 'Lba', 'Format', 'Entropy')

    Add-Line '## Candidate files (heuristics - unconfirmed)'
    Add-Line
    Add-Line 'Name keywords and header signatures only. Nothing here is a confirmed finding.'
    Add-Line
    foreach ($k in $Heuristics.Keys) {
        Add-Line ('### Name suggests: {0}' -f $k)
        Add-Line
        Add-Table @($rows | Where-Object { ($_.Hints -split ';') -contains $k } | ForEach-Object { [pscustomobject]@{ Path = $_.Path; Size = ('{0:N0}' -f $_.Size); Format = $_.Format; Items = $_.ArchiveItems } }) @('Path', 'Size', 'Format', 'Items')
    }
    foreach ($cat in @('database', 'texture/image', 'archive', 'executable/module', 'compressed')) {
        Add-Line ('### Detected category: {0}' -f $cat)
        Add-Line
        Add-Table @($rows | Where-Object { $_.Category -eq $cat } | ForEach-Object { [pscustomobject]@{ Path = $_.Path; Size = ('{0:N0}' -f $_.Size); Format = $_.Format; Items = $_.ArchiveItems } }) @('Path', 'Size', 'Format', 'Items')
    }

    Add-Line '## Archive contents'
    Add-Line
    if ($scans.Count -eq 0) {
        Add-Line '_No TERF/BIGF/SHPS/TIM2 headers were found at the start of any file._'
        Add-Line
    } else {
        $archSummary = foreach ($key in ($scans.Keys | Sort-Object)) {
            $s = $scans[$key]
            $top = @($s.Entries | Where-Object { $_.Container -eq $key })
            $algos = ($top | Group-Object Algorithm | Sort-Object Name | ForEach-Object { '{0} ({1})' -f $_.Name, $_.Count }) -join ', '
            $tags = ($top | Group-Object Tag | Sort-Object Count -Descending | Select-Object -First 6 | ForEach-Object { '{0} ({1})' -f $_.Name, $_.Count }) -join ', '
            $chunks = (@($s.Chunks | Where-Object { $_.Container -eq $key }) | ForEach-Object { $_.Type }) -join ','
            [pscustomobject]@{ Archive = $key; Entries = $top.Count; Nested = @($s.Entries | Where-Object { $_.Depth -gt 0 }).Count; Chunks = $chunks; Algorithms = $algos; 'Inner formats' = $tags; Textures = $s.Textures.Count; Problems = $s.Problems.Count }
        }
        Add-Line 'Algorithms are the TERF `COMP` values with entry counts in parentheses (0 = stored). Inner formats are detected from the first bytes of each entry.'
        Add-Line
        Add-Table @($archSummary) @('Archive', 'Entries', 'Nested', 'Chunks', 'Algorithms', 'Inner formats', 'Textures', 'Problems')
        $algoTotals = $allArchiveEntries | Group-Object Algorithm | ForEach-Object { [pscustomobject]@{ Algorithm = $_.Name; Entries = $_.Count; 'Stored bytes' = ('{0:N0}' -f ($_.Group | Measure-Object StoredSize -Sum).Sum) } }
        Add-Line '### Compression algorithms (all archives)'
        Add-Line
        Add-Table @($algoTotals) @('Algorithm', 'Entries', 'Stored bytes')
        if ($archiveProblems.Count -gt 0) {
            Add-Line '### Archive parsing problems'
            Add-Line
            foreach ($p in $archiveProblems) { Add-Line ('* ' + $p) }
            Add-Line
        }
    }
    if ($allTextures.Count -gt 0) {
        Add-Line '### Texture containers (first 40)'
        Add-Line
        Add-Table @($allTextures | Select-Object -First 40) @('Source', 'Container', 'Index', 'Name', 'Format', 'Width', 'Height')
    }

    Add-Line '## Disc layout'
    Add-Line
    Add-Line 'Files in sector order with free sectors after each. Gaps matter when a modified file must grow.'
    Add-Line
    Add-Table @($lbaRows | Where-Object { $_.GapSectorsAfter -ne 0 } | Select-Object -First 60) @('Lba', 'EndLba', 'Kind', 'Path', 'Size', 'GapSectorsAfter')
    Add-Line ('Files laid out in alphabetical order: {0}' -f ((@($files | Sort-Object Lba | ForEach-Object { $_.Path }) -join '|') -eq (@($files | Sort-Object Path | ForEach-Object { $_.Path }) -join '|')))
    Add-Line

    if ($iso.Warnings.Count -gt 0) {
        Add-Line '## Warnings'
        Add-Line
        foreach ($w in $iso.Warnings) { Add-Line ('* ' + $w) }
        Add-Line
    }
    Add-Line '## Extracted in this run'
    Add-Line
    Add-Table @($extractedRows | ForEach-Object { [pscustomobject]@{ Path = $_.Path; Size = ('{0:N0}' -f $_.Size); Sha256 = $_.Sha256 } }) @('Path', 'Size', 'Sha256')

    Set-Content -LiteralPath ([System.IO.Path]::Combine($dirReports, 'research_report.md')) -Value $sb.ToString() -Encoding UTF8
    Write-Info ([System.IO.Path]::Combine($dirReports, 'research_report.md'))
}
finally {
    if ($null -ne $iso) { $iso.Dispose() }
}

# ---------------------------------------------------------------------------------------------
# Verify the ISO was not modified
# ---------------------------------------------------------------------------------------------
Write-Step 'Verifying the original ISO is unchanged'
$isoAfter = Get-Item -LiteralPath $isoFull
$unchanged = ($isoAfter.Length -eq $isoLengthBefore) -and ($isoAfter.LastWriteTimeUtc -eq $isoWriteBefore)
if ($unchanged) { Write-Info 'OK - size and last-modified time are identical to before the run.' }
else { Write-Warn2 'The ISO size or timestamp changed during the run. Another program may have modified it.' }
Add-Content -LiteralPath ([System.IO.Path]::Combine($dirReports, 'research_report.md')) -Value ("`r`n## Integrity`r`n`r`n* Original ISO unchanged after run (size + last-write time): {0}`r`n" -f $unchanged) -Encoding UTF8

# ---------------------------------------------------------------------------------------------
# Transfer packages
# ---------------------------------------------------------------------------------------------
$packageFiles = @()
if (-not $NoPackage) {
    Write-Step 'Building transfer packages'
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    if (-not $DropName) {
        $n = 1
        while (@(Get-ChildItem -LiteralPath $dirPackages -Filter ('drop-{0:000}-*' -f $n) -ErrorAction SilentlyContinue).Count -gt 0) { $n++ }
        $DropName = 'drop-{0:000}' -f $n
    }

    function New-ZipParts([string] $BaseName, [object[]] $Items) {
        # $Items: objects with Source (local file) and Entry (path inside the zip). Greedy split by size.
        $limit = [long]$MaxPartMB * 1MB
        $parts = New-Object System.Collections.Generic.List[object]
        $current = New-Object System.Collections.Generic.List[object]
        $size = [long]0
        foreach ($it in $Items) {
            $len = (Get-Item -LiteralPath $it.Source).Length
            if ($len -gt $limit) { Write-Warn2 ('{0} is larger than {1} MB and gets its own part.' -f $it.Entry, $MaxPartMB) }
            if ($current.Count -gt 0 -and ($size + $len) -gt $limit) { $parts.Add($current); $current = New-Object System.Collections.Generic.List[object]; $size = 0 }
            $current.Add($it); $size += $len
        }
        if ($current.Count -gt 0) { $parts.Add($current) }
        $out = @()
        for ($p = 0; $p -lt $parts.Count; $p++) {
            $name = if ($parts.Count -gt 1) { '{0}.part{1:00}.zip' -f $BaseName, ($p + 1) } else { '{0}.zip' -f $BaseName }
            $zipPath = [System.IO.Path]::Combine($dirPackages, $name)
            if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
            $zip = [System.IO.Compression.ZipFile]::Open($zipPath, [System.IO.Compression.ZipArchiveMode]::Create)
            try {
                foreach ($it in $parts[$p]) {
                    [void][System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $it.Source, $it.Entry, [System.IO.Compression.CompressionLevel]::Optimal)
                }
            } finally { $zip.Dispose() }
            $out += $zipPath
        }
        return $out
    }

    function Get-ItemsUnder([string] $Folder, [string] $Prefix) {
        if (-not (Test-Path -LiteralPath $Folder)) { return @() }
        $base = (Get-Item -LiteralPath $Folder).FullName.TrimEnd('\', '/')
        return @(Get-ChildItem -LiteralPath $Folder -Recurse -File | ForEach-Object {
            [pscustomobject]@{ Source = $_.FullName; Entry = ($Prefix + '/' + $_.FullName.Substring($base.Length + 1).Replace('\', '/')) }
        })
    }

    # 1) Metadata package: inventory + reports. Technical metadata only (names, sizes, sectors, short header bytes).
    $metaItems = @(Get-ItemsUnder $dirInventory 'inventory') + @(Get-ItemsUnder $dirReports 'reports')
    $packageFiles += New-ZipParts ('{0}-metadata' -f $DropName) $metaItems

    # 2) Game-data package: head samples + files extracted in this run. Contains copyrighted game data.
    $dataItems = @()
    if ($HeadBytes -gt 0) { $dataItems += @(Get-ItemsUnder $dirHeads 'samples/heads') }
    foreach ($x in $extractedRows) {
        $dataItems += [pscustomobject]@{ Source = $x.LocalFile; Entry = ('extracted' + $x.Path) }
    }
    if ($dataItems.Count -gt 0) { $packageFiles += New-ZipParts ('{0}-gamedata' -f $DropName) $dataItems }

    $manifest = [ordered]@{ drop = $DropName; createdUtc = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'); tool = $ScriptVersion; packages = @() }
    foreach ($pf in $packageFiles) {
        $h = (Get-FileHash -LiteralPath $pf -Algorithm SHA256).Hash.ToLowerInvariant()
        $manifest.packages += [ordered]@{ file = [System.IO.Path]::GetFileName($pf); bytes = (Get-Item -LiteralPath $pf).Length; sha256 = $h; containsGameData = ($pf -like '*-gamedata*') }
        Write-Info ('{0}  {1}  sha256={2}' -f [System.IO.Path]::GetFileName($pf), (Format-Size (Get-Item -LiteralPath $pf).Length), $h)
    }
    $manifestPath = [System.IO.Path]::Combine($dirPackages, ('{0}.manifest.json' -f $DropName))
    $manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    $packageFiles += $manifestPath
}

# ---------------------------------------------------------------------------------------------
# Repository privacy check + optional upload
# ---------------------------------------------------------------------------------------------
$repoVisibility = 'unknown'
if (-not $Offline -and -not $NoPackage) {
    Write-Step ('Checking whether github.com/{0} is private (anonymous read-only request)' -f $Repository)
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
        $resp = Invoke-RestMethod -Uri ('https://api.github.com/repos/{0}' -f $Repository) -Headers @{ 'User-Agent' = 'Madden06-Inspector' } -TimeoutSec 15
        if ($resp.private -eq $false) { $repoVisibility = 'public' }
    } catch {
        $code = $null
        try { $code = [int]$_.Exception.Response.StatusCode } catch { }
        if ($code -eq 404) { $repoVisibility = 'private' } else { Write-Info ('Could not determine visibility: {0}' -f $_.Exception.Message) }
    }
    if ($repoVisibility -eq 'public') {
        Write-Host ''
        Write-Host ('    WARNING: github.com/{0} is PUBLIC. Do NOT upload the *-gamedata* packages there.' -f $Repository) -ForegroundColor Red
        Write-Host '             Make the repository private first (Settings > General > Danger Zone > Change visibility),' -ForegroundColor Red
        Write-Host '             or use a private share link instead (see docs\TRANSFER-WORKFLOW.md).' -ForegroundColor Red
    } elseif ($repoVisibility -eq 'private') {
        Write-Info 'Repository is not publicly visible (good).'
    }
}

if ($UploadWithGh -and $packageFiles.Count -gt 0) {
    Write-Step 'Uploading packages to a draft GitHub release with gh'
    $gh = Get-Command gh -ErrorAction SilentlyContinue
    if ($null -eq $gh) { Write-Warn2 'GitHub CLI (gh) is not installed. Upload the zips manually (see docs\TRANSFER-WORKFLOW.md).' }
    else {
        $isPrivate = (& gh api ('repos/{0}' -f $Repository) --jq '.private' 2>$null)
        if ("$isPrivate".Trim() -ne 'true') {
            Write-Warn2 'Refusing to upload: the repository is not confirmed private (or gh is not logged in).'
        } else {
            & gh release view $DropName --repo $Repository *> $null
            if ($LASTEXITCODE -ne 0) {
                & gh release create $DropName --repo $Repository --draft --title ('Research {0}' -f $DropName) --notes 'Private research transfer package. Delete after the cloud session has downloaded it.' @packageFiles
            } else {
                & gh release upload $DropName --repo $Repository --clobber @packageFiles
            }
            if ($LASTEXITCODE -eq 0) { Write-Info ('Uploaded to draft release "{0}".' -f $DropName) } else { Write-Warn2 'gh reported an error.' }
        }
    }
}

# ---------------------------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------------------------
$elapsed = (Get-Date) - $started
Write-Host ''
Write-Host ('Finished in {0:mm\:ss}.' -f $elapsed) -ForegroundColor Green
Write-Host ('Report:    {0}' -f [System.IO.Path]::Combine([System.IO.Path]::Combine($outFull, 'reports'), 'research_report.md'))
Write-Host ('Inventory: {0}' -f [System.IO.Path]::Combine($outFull, 'inventory'))
if ($packageFiles.Count -gt 0) {
    Write-Host 'Packages to send to the cloud session:'
    foreach ($pf in $packageFiles) { Write-Host ('  {0}' -f $pf) }
}
