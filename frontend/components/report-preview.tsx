"use client";

import React, { useEffect, useId, useRef } from "react";

type Block =
  | { type: "heading"; level: number; text: string }
  | { type: "paragraph"; lines: string[] }
  | { type: "quote"; lines: string[] }
  | { type: "list"; ordered: boolean; lines: string[] }
  | { type: "code"; language: string; lines: string[] }
  | { type: "table"; rows: string[][] };

export function ReportPreview({ content }: { content: string }) {
  const blocks = parseMarkdown(content);
  return (
    <article className="report-preview">
      {blocks.map((block, index) => (
        <React.Fragment key={`${block.type}-${index}`}>{renderBlock(block, index)}</React.Fragment>
      ))}
    </article>
  );
}

function parseMarkdown(content: string): Block[] {
  const lines = content.replace(/\r\n/g, "\n").split("\n");
  const blocks: Block[] = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }
    if (line.startsWith("```")) {
      const language = line.replace(/^```/, "").trim().toLowerCase();
      const code: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].startsWith("```")) {
        code.push(lines[index]);
        index += 1;
      }
      blocks.push({ type: "code", language, lines: code });
      index += 1;
      continue;
    }
    if (line.startsWith("|") && index + 1 < lines.length && /^\|\s*-+/.test(lines[index + 1])) {
      const rows: string[][] = [];
      while (index < lines.length && lines[index].startsWith("|")) {
        if (!/^\|\s*:?-+/.test(lines[index])) {
          rows.push(splitTableRow(lines[index]));
        }
        index += 1;
      }
      blocks.push({ type: "table", rows });
      continue;
    }
    const heading = line.match(/^(#{1,3})\s+(.*)$/);
    if (heading) {
      blocks.push({ type: "heading", level: heading[1].length, text: heading[2] });
      index += 1;
      continue;
    }
    if (line.startsWith(">")) {
      const quote: string[] = [];
      while (index < lines.length && lines[index].startsWith(">")) {
        quote.push(lines[index].replace(/^>\s?/, ""));
        index += 1;
      }
      blocks.push({ type: "quote", lines: quote });
      continue;
    }
    if (/^\s*-\s+/.test(line) || /^\s*\d+\.\s+/.test(line)) {
      const ordered = /^\s*\d+\.\s+/.test(line);
      const items: string[] = [];
      while (index < lines.length && (ordered ? /^\s*\d+\.\s+/.test(lines[index]) : /^\s*-\s+/.test(lines[index]))) {
        items.push(lines[index].replace(ordered ? /^\s*\d+\.\s+/ : /^\s*-\s+/, ""));
        index += 1;
      }
      blocks.push({ type: "list", ordered, lines: items });
      continue;
    }
    const paragraph: string[] = [];
    while (
      index < lines.length &&
      lines[index].trim() &&
      !lines[index].startsWith("```") &&
      !lines[index].startsWith("|") &&
      !lines[index].startsWith(">") &&
      !/^(#{1,3})\s+/.test(lines[index]) &&
      !/^\s*-\s+/.test(lines[index]) &&
      !/^\s*\d+\.\s+/.test(lines[index])
    ) {
      paragraph.push(lines[index]);
      index += 1;
    }
    blocks.push({ type: "paragraph", lines: paragraph });
  }
  return blocks;
}

function renderBlock(block: Block, index: number) {
  if (block.type === "heading") {
    const HeadingTag = `h${block.level}` as keyof JSX.IntrinsicElements;
    return <HeadingTag>{renderInline(block.text)}</HeadingTag>;
  }
  if (block.type === "quote") {
    return (
      <section className="report-tldr">
        {block.lines.map((line, lineIndex) => (
          <p key={lineIndex}>{renderInline(line)}</p>
        ))}
      </section>
    );
  }
  if (block.type === "list") {
    const ListTag = block.ordered ? "ol" : "ul";
    return (
      <ListTag>
        {block.lines.map((line, lineIndex) => (
          <li key={lineIndex}>{renderInline(line)}</li>
        ))}
      </ListTag>
    );
  }
  if (block.type === "code") {
    if (block.language === "mermaid") {
      return <MermaidDiagram source={block.lines.join("\n")} />;
    }
    return <pre>{block.lines.join("\n")}</pre>;
  }
  if (block.type === "table") {
    const [head, ...body] = block.rows;
    return (
      <div className="report-table-wrap">
        <table>
          {head ? (
            <thead>
              <tr>
                {head.map((cell, cellIndex) => (
                  <th key={cellIndex}>{renderInline(cell)}</th>
                ))}
              </tr>
            </thead>
          ) : null}
          <tbody>
            {body.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {row.map((cell, cellIndex) => (
                  <td key={cellIndex}>{renderInline(cell.replace(/<br>/g, "\n"))}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  return (
    <p key={index}>
      {block.lines.map((line, lineIndex) => (
        <React.Fragment key={lineIndex}>
          {lineIndex > 0 ? <br /> : null}
          {renderInline(line)}
        </React.Fragment>
      ))}
    </p>
  );
}

function MermaidDiagram({ source }: { source: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const rawId = useId();
  const diagramId = `mermaid-${rawId.replace(/[^a-zA-Z0-9_-]/g, "")}`;

  useEffect(() => {
    let cancelled = false;
    import("mermaid")
      .then((mod) => {
        const mermaid = mod.default;
        mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "default" });
        return mermaid.render(diagramId, source);
      })
      .then(({ svg }) => {
        if (!cancelled && ref.current) {
          ref.current.innerHTML = svg;
        }
      })
      .catch((error) => {
        if (!cancelled && ref.current) {
          ref.current.textContent = `${source}\n\nMermaid render failed: ${error.message}`;
        }
      });
    return () => {
      cancelled = true;
    };
  }, [diagramId, source]);

  return (
    <div className="mermaid-diagram" ref={ref}>
      <pre>{source}</pre>
    </div>
  );
}

function splitTableRow(line: string): string[] {
  return line
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split(/(?<!\\)\|/)
    .map((cell) => cell.replace(/\\\|/g, "|").trim());
}

function renderInline(text: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g).filter(Boolean);
  parts.forEach((part, index) => {
    if (part.startsWith("`") && part.endsWith("`")) {
      nodes.push(<code key={index}>{part.slice(1, -1)}</code>);
    } else if (part.startsWith("**") && part.endsWith("**")) {
      nodes.push(<strong key={index}>{part.slice(2, -2)}</strong>);
    } else {
      nodes.push(part);
    }
  });
  return nodes;
}
