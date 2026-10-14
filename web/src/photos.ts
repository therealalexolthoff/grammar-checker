// Handwriting photos, shared by the teacher's and the student's upload.

// Photos are shrunk to at most this many pixels on the long side before
// upload: plenty to read handwriting, and far less to send to the AI.
const MAX_PHOTO_SIDE = 2000;

// Re-draws a photo on a canvas and saves it as a JPEG. The new file has
// none of the original's metadata (location, camera, time), is the right
// way up, and is no larger than MAX_PHOTO_SIDE. The API strips metadata
// again anyway (api/app/photos.py).
export async function toCleanJpeg(file: File): Promise<Blob> {
  const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
  const scale = Math.min(1, MAX_PHOTO_SIDE / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  canvas.getContext("2d")!.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  return new Promise((resolve, reject) =>
    canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("Could not read that photo."))), "image/jpeg", 0.85),
  );
}

// Pages go up in file-name order: phone photos are numbered as taken.
export function inPageOrder(files: FileList): File[] {
  return [...files].sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));
}

export type PageLink = { page: number; url: string };
