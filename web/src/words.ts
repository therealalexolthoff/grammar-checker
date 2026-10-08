// Words in a piece of writing, counted the simple way: runs of non-space.
export function wordCount(text: string): number {
  return text.split(/\s+/).filter(Boolean).length;
}
