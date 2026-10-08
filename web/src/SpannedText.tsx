// A piece of text with its error spans highlighted and labelled by code.
// Used on both sides: the teacher's review screen and the student's results.
type Span = { start: number; end: number; code: string; meaning?: string };

export default function SpannedText({ text, spans }: { text: string; spans: Span[] }) {
  const sorted = [...spans].sort((a, b) => a.start - b.start);
  const pieces: React.ReactNode[] = [];
  let at = 0;
  sorted.forEach((span, i) => {
    if (span.start > at) pieces.push(text.slice(at, span.start));
    pieces.push(
      <mark key={i} className="span" title={span.meaning}>
        {text.slice(span.start, span.end)}
        <span className="code">{span.code}</span>
      </mark>,
    );
    at = span.end;
  });
  pieces.push(text.slice(at));
  return <p className="spanned">{pieces}</p>;
}
