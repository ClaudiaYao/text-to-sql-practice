import type { ReactNode } from "react";

// Minimal, dependency-free renderer for the LLM's answer text: **bold**, `code` and "- " / "* " bullets.
// It only builds React elements (never HTML strings), so model output cannot inject markup.

const INLINE = /(\*\*[^*\n]+\*\*|`[^`\n]+`)/g;

function renderInline(text: string): ReactNode[] {
  return text.split(INLINE).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      return <strong key={i} className="font-semibold text-white">{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
      return <code key={i} className="px-1 py-0.5 rounded bg-gray-800 text-indigo-200 text-[0.85em]">{part.slice(1, -1)}</code>;
    }
    return part;
  });
}

const BULLET = /^\s*[-*]\s+(.*)$/;

export default function AnswerText({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let bullets: string[] = [];
  let paragraph: string[] = [];

  const flushParagraph = () => {
    if (paragraph.length) {
      blocks.push(<p key={blocks.length}>{renderInline(paragraph.join("\n"))}</p>);
      paragraph = [];
    }
  };
  const flushBullets = () => {
    if (bullets.length) {
      blocks.push(
        <ul key={blocks.length} className="list-disc pl-5 space-y-0.5">
          {bullets.map((b, i) => <li key={i}>{renderInline(b)}</li>)}
        </ul>,
      );
      bullets = [];
    }
  };

  for (const line of text.split("\n")) {
    const m = BULLET.exec(line);
    if (m) {
      flushParagraph();
      bullets.push(m[1]);
    } else if (line.trim() === "") {
      flushParagraph();
      flushBullets();
    } else {
      flushBullets();
      paragraph.push(line);
    }
  }
  flushParagraph();
  flushBullets();

  return <div className="space-y-2">{blocks}</div>;
}
