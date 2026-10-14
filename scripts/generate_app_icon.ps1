# Rebuild the Windows/Electron icons from the original FLUX mark, preserving alpha.
# Run from any directory: powershell -File scripts/generate_app_icon.ps1
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -ReferencedAssemblies System.Drawing -TypeDefinition @'
using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.IO;

public static class FluxAppIcon {
    public static void Build(string source, string png, string ico) {
        using (var mark = new Bitmap(source)) {
            int left = mark.Width, top = mark.Height, right = -1, bottom = -1;
            for (int y = 0; y < mark.Height; y++)
                for (int x = 0; x < mark.Width; x++)
                    if (mark.GetPixel(x, y).A > 0) {
                        left = Math.Min(left, x); top = Math.Min(top, y);
                        right = Math.Max(right, x); bottom = Math.Max(bottom, y);
                    }
            if (right < left) throw new InvalidDataException("The logo is fully transparent.");
            var bounds = new Rectangle(left, top, right - left + 1, bottom - top + 1);
            using (var tile = new Bitmap(1024, 1024, PixelFormat.Format32bppArgb)) {
                using (var g = Graphics.FromImage(tile)) {
                    g.Clear(Color.Transparent);
                    g.SmoothingMode = SmoothingMode.AntiAlias;
                    g.InterpolationMode = InterpolationMode.HighQualityBicubic;
                    g.PixelOffsetMode = PixelOffsetMode.HighQuality;
                    using (var path = new GraphicsPath()) {
                        const int d = 328; // 16% corner radius
                        path.AddArc(0, 0, d, d, 180, 90);
                        path.AddArc(1024-d, 0, d, d, 270, 90);
                        path.AddArc(1024-d, 1024-d, d, d, 0, 90);
                        path.AddArc(0, 1024-d, d, d, 90, 90);
                        path.CloseFigure();
                        g.FillPath(Brushes.Black, path);
                    }
                    float scale = 758f / Math.Max(bounds.Width, bounds.Height);
                    float w = bounds.Width * scale, h = bounds.Height * scale;
                    g.DrawImage(mark, new RectangleF((1024-w)/2, (1024-h)/2, w, h), bounds, GraphicsUnit.Pixel);
                }
                tile.Save(png, ImageFormat.Png);
                int[] sizes = {16, 24, 32, 48, 64, 128, 256};
                byte[][] images = new byte[sizes.Length][];
                for (int i = 0; i < sizes.Length; i++) {
                    using (var small = new Bitmap(sizes[i], sizes[i], PixelFormat.Format32bppArgb)) {
                        using (var g = Graphics.FromImage(small)) {
                            g.InterpolationMode = InterpolationMode.HighQualityBicubic;
                            g.PixelOffsetMode = PixelOffsetMode.HighQuality;
                            g.DrawImage(tile, new Rectangle(0, 0, sizes[i], sizes[i]));
                        }
                        using (var ms = new MemoryStream()) {
                            small.Save(ms, ImageFormat.Png);
                            images[i] = ms.ToArray();
                        }
                    }
                }
                using (var writer = new BinaryWriter(File.Create(ico))) {
                    writer.Write((ushort)0); writer.Write((ushort)1); writer.Write((ushort)sizes.Length);
                    uint offset = (uint)(6 + 16 * sizes.Length);
                    for (int i = 0; i < sizes.Length; i++) {
                        writer.Write((byte)(sizes[i] == 256 ? 0 : sizes[i]));
                        writer.Write((byte)(sizes[i] == 256 ? 0 : sizes[i]));
                        writer.Write((byte)0); writer.Write((byte)0);
                        writer.Write((ushort)1); writer.Write((ushort)32);
                        writer.Write((uint)images[i].Length); writer.Write(offset);
                        offset += (uint)images[i].Length;
                    }
                    foreach (var bytes in images) writer.Write(bytes);
                }
            }
        }
    }
}
'@
[FluxAppIcon]::Build((Join-Path $PSScriptRoot 'logo-source.png'), (Join-Path $PSScriptRoot 'icon.png'), (Join-Path $PSScriptRoot 'icon.ico'))
Write-Output 'FLUX icon.png and icon.ico rebuilt (7 Windows sizes).'
