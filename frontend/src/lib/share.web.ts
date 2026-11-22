/** Web: "save" downloads the MP4; "share" uses the browser share sheet when it can share files,
 * otherwise copies the (time-limited) link. */

async function blobOf(url: string): Promise<Blob> {
  // no-store: the <video> tag already fetched this URL without CORS; reusing that cached copy
  // (no Access-Control-Allow-Origin header) makes the browser block this read.
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) throw new Error(`Download failed (${res.status})`);
  return res.blob();
}

export async function saveToGallery(url: string, name: string): Promise<string> {
  const href = URL.createObjectURL(await blobOf(url));
  const a = document.createElement('a');
  a.href = href;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(href), 10_000);
  return 'Downloaded';
}

export async function shareVideo(url: string, name: string): Promise<string | null> {
  const nav = navigator as Navigator & { canShare?: (d: ShareData) => boolean };
  if (nav.share) {
    const file = new File([await blobOf(url)], name, { type: 'video/mp4' });
    if (nav.canShare?.({ files: [file] })) {
      await nav.share({ files: [file], title: 'My reel' });
      return null;
    }
  }
  await navigator.clipboard.writeText(url);
  return 'Link copied - it works for about an hour';
}
