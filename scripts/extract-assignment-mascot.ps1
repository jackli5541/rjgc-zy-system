param([string]$SourcePath)
Add-Type -AssemblyName System.Drawing
Add-Type -ReferencedAssemblies System.Drawing.Common, System.Drawing.Primitives, System.Private.Windows.GdiPlus, System.Private.Windows.Core, System.Collections -TypeDefinition @'
using System;
using System.Drawing;
using System.Drawing.Imaging;
using System.Collections.Generic;
public static class MascotExtractor {
  public static void Extract(string input, string output) {
    using (var source = new Bitmap(input))
    using (var result = new Bitmap(source.Width, source.Height)) {
      int w = source.Width, h = source.Height;
      var removed = new bool[w * h];
      var visited = new bool[w * h];
      var queue = new Queue<int>();
      for (int x = 0; x < w; x++) { queue.Enqueue(x); queue.Enqueue((h - 1) * w + x); }
      for (int y = 0; y < h; y++) { queue.Enqueue(y * w); queue.Enqueue(y * w + w - 1); }
      // Flood only bright neutral background connected to the border.
      while (queue.Count > 0) {
        int i = queue.Dequeue();
        if (visited[i]) continue;
        visited[i] = true;
        int x = i % w, y = i / w;
        var c = source.GetPixel(x, y);
        int max = Math.Max(c.R, Math.Max(c.G, c.B));
        int min = Math.Min(c.R, Math.Min(c.G, c.B));
        if (max - min > 28 || min < 105) continue;
        removed[i] = true;
        if (x > 0) queue.Enqueue(i - 1);
        if (x < w - 1) queue.Enqueue(i + 1);
        if (y > 0) queue.Enqueue(i - w);
        if (y < h - 1) queue.Enqueue(i + w);
      }
      for (int y = 0; y < h; y++)
        for (int x = 0; x < w; x++)
          if (!removed[y * w + x]) result.SetPixel(x, y, source.GetPixel(x, y));
      using (var cropped = result.Clone(new Rectangle(230, 30, 610, 880), PixelFormat.Format32bppArgb))
        cropped.Save(output, ImageFormat.Png);
    }
  }
}
'@
if (-not $SourcePath) { throw 'Specify -SourcePath for the source image.' }
[MascotExtractor]::Extract($SourcePath, (Join-Path $PSScriptRoot '../frontend/public/assignment-mascot.png'))
