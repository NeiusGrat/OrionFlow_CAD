import { Fragment, type ReactNode } from "react";

/**
 * Markdown, rendered to React elements.
 *
 * The panel used to handle `**bold**` and nothing else, which was fine while
 * the only prose came from our own narrative generator. It is not fine now: the
 * unified agent answers questions and writes reviews, and a model asked for a
 * manufacturability review replies in headings, lists and back-ticked
 * dimensions. Rendering those as literal asterisks made a good answer look
 * broken.
 *
 * Written out rather than pulled in as a dependency for one reason that
 * matters: **no `dangerouslySetInnerHTML`**. Every node here is a React element
 * built from parsed text, so a model that emits a `<script>` tag — or a part
 * name that happens to contain one — renders as characters on the screen and
 * can never become markup. A markdown library plus a sanitiser would be two
 * dependencies and one more thing that has to be kept correct.
 *
 * Supports what LLM prose actually uses: headings, bold, italic, inline code,
 * fenced code, ordered and unordered lists, blockquotes, rules and links.
 * Anything else falls through as text, which is always a safe reading.
 */

/* ─────────────────────────── inline ─────────────────────────── */

/** `code`, **bold**, *italic*, [link](href) — innermost first. */
function inline(text: string, keyBase: string): ReactNode[] {
    const out: ReactNode[] = [];
    // Code is matched first and its contents are never re-parsed, so a
    // dimension like `a*b` inside back-ticks does not turn into italics.
    const pattern =
        /(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|(__[^_\n]+__)|(\*[^*\n]+\*)|(\[[^\]\n]+\]\([^)\s]+\))/g;

    let last = 0;
    let m: RegExpExecArray | null;
    let i = 0;

    while ((m = pattern.exec(text)) !== null) {
        if (m.index > last) out.push(text.slice(last, m.index));
        const tok = m[0];
        const key = `${keyBase}-i${i++}`;

        if (tok.startsWith("`")) {
            out.push(<code key={key}>{tok.slice(1, -1)}</code>);
        } else if (tok.startsWith("**") || tok.startsWith("__")) {
            out.push(<strong key={key}>{tok.slice(2, -2)}</strong>);
        } else if (tok.startsWith("[")) {
            const split = tok.indexOf("](");
            const label = tok.slice(1, split);
            const href = tok.slice(split + 2, -1);
            // Only http(s) and relative hrefs are honoured. A `javascript:` URL
            // in model output renders as plain text rather than as a link.
            const safe = /^(https?:\/\/|\/|#)/i.test(href);
            out.push(
                safe ? (
                    <a key={key} href={href} target="_blank" rel="noopener noreferrer">
                        {label}
                    </a>
                ) : (
                    <Fragment key={key}>{tok}</Fragment>
                ),
            );
        } else {
            out.push(<em key={key}>{tok.slice(1, -1)}</em>);
        }
        last = m.index + tok.length;
    }
    if (last < text.length) out.push(text.slice(last));
    return out;
}

/* ─────────────────────────── blocks ─────────────────────────── */

type Block =
    | { kind: "p"; lines: string[] }
    | { kind: "h"; level: number; text: string }
    | { kind: "ul"; items: string[] }
    | { kind: "ol"; items: string[] }
    | { kind: "quote"; lines: string[] }
    | { kind: "code"; lang: string; lines: string[] }
    | { kind: "hr" };

function parse(src: string): Block[] {
    const lines = src.replace(/\r\n?/g, "\n").split("\n");
    const blocks: Block[] = [];
    let i = 0;

    const last = () => blocks[blocks.length - 1];

    while (i < lines.length) {
        const line = lines[i];

        // Fenced code. An unterminated fence runs to the end rather than being
        // dropped — a stream cut mid-block still shows what arrived.
        const fence = line.match(/^\s*```+\s*([\w+-]*)\s*$/);
        if (fence) {
            const body: string[] = [];
            i++;
            while (i < lines.length && !/^\s*```+\s*$/.test(lines[i])) body.push(lines[i++]);
            i++;
            blocks.push({ kind: "code", lang: fence[1] || "", lines: body });
            continue;
        }

        if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
            blocks.push({ kind: "hr" });
            i++;
            continue;
        }

        const heading = line.match(/^(#{1,6})\s+(.*)$/);
        if (heading) {
            blocks.push({ kind: "h", level: heading[1].length, text: heading[2].trim() });
            i++;
            continue;
        }

        const bullet = line.match(/^\s*[-*+]\s+(.*)$/);
        if (bullet) {
            const prev = last();
            if (prev?.kind === "ul") prev.items.push(bullet[1]);
            else blocks.push({ kind: "ul", items: [bullet[1]] });
            i++;
            continue;
        }

        const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/);
        if (numbered) {
            const prev = last();
            if (prev?.kind === "ol") prev.items.push(numbered[1]);
            else blocks.push({ kind: "ol", items: [numbered[1]] });
            i++;
            continue;
        }

        const quote = line.match(/^\s*>\s?(.*)$/);
        if (quote) {
            const prev = last();
            if (prev?.kind === "quote") prev.lines.push(quote[1]);
            else blocks.push({ kind: "quote", lines: [quote[1]] });
            i++;
            continue;
        }

        if (!line.trim()) {
            // A blank line closes whatever was open.
            if (last()?.kind === "p") blocks.push({ kind: "p", lines: [] });
            i++;
            continue;
        }

        const prev = last();
        if (prev?.kind === "p" && prev.lines.length) prev.lines.push(line);
        else blocks.push({ kind: "p", lines: [line] });
        i++;
    }

    return blocks.filter((b) => b.kind !== "p" || b.lines.length > 0);
}

export default function Markdown({ text }: { text: string }) {
    if (!text?.trim()) return null;
    const blocks = parse(text);

    return (
        <div className="of-md">
            {blocks.map((b, n) => {
                const key = `b${n}`;
                switch (b.kind) {
                    case "h": {
                        // Everything renders as an h3: this is prose inside a
                        // panel, not a document, and a real h1 here would
                        // outrank the studio's own headings for a screen
                        // reader walking the page.
                        return (
                            <h3 key={key} aria-level={Math.min(b.level + 2, 6)} role="heading">
                                {inline(b.text, key)}
                            </h3>
                        );
                    }
                    case "ul":
                        return (
                            <ul key={key}>
                                {b.items.map((it, j) => (
                                    <li key={j}>{inline(it, `${key}-${j}`)}</li>
                                ))}
                            </ul>
                        );
                    case "ol":
                        return (
                            <ol key={key}>
                                {b.items.map((it, j) => (
                                    <li key={j}>{inline(it, `${key}-${j}`)}</li>
                                ))}
                            </ol>
                        );
                    case "quote":
                        return (
                            <blockquote key={key}>{inline(b.lines.join(" "), key)}</blockquote>
                        );
                    case "code":
                        return (
                            <pre key={key} className="studio-scroll">
                                <code>{b.lines.join("\n")}</code>
                            </pre>
                        );
                    case "hr":
                        return <hr key={key} />;
                    default:
                        return <p key={key}>{inline(b.lines.join(" "), key)}</p>;
                }
            })}
        </div>
    );
}
