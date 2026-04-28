from __future__ import annotations

import html
import io
import re
import textwrap
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.object_store import ObjectStore
from app.models.db import ReportExport, utcnow
from app.services.diagram_service import DiagramService
from app.services.job_service import JobService
from app.services.report_service import ReportService


class ReportExportService:
    def __init__(self, db: Session, object_store: ObjectStore | None = None) -> None:
        self.db = db
        self.object_store = object_store or ObjectStore()

    def list_for_report(self, report_id: str) -> list[ReportExport]:
        return list(
            self.db.scalars(
                select(ReportExport).where(ReportExport.report_id == report_id).order_by(ReportExport.created_at.desc())
            ).all()
        )

    def get(self, export_id: str) -> ReportExport | None:
        return self.db.get(ReportExport, export_id)

    def create_export(self, report_id: str, export_format: str, created_by: str | None = None) -> ReportExport:
        export, should_run = self.request_export_job(report_id, export_format, created_by)
        if should_run:
            self.run_export(export.id)
        refreshed = self.get(export.id)
        return refreshed or export

    def request_export(self, report_id: str, export_format: str, created_by: str | None = None) -> ReportExport:
        export, _ = self.request_export_job(report_id, export_format, created_by)
        return export

    def request_export_job(self, report_id: str, export_format: str, created_by: str | None = None) -> tuple[ReportExport, bool]:
        if export_format != "pdf":
            raise HTTPException(status_code=422, detail="Only pdf exports are supported")
        report_service = ReportService(self.db, self.object_store)
        report = report_service.get(report_id)
        if report is None:
            raise HTTPException(status_code=404, detail="Report not found")
        export = self.db.scalar(select(ReportExport).where(ReportExport.report_id == report_id, ReportExport.format == export_format))
        if export is not None and export.status == "success" and export.object_path:
            return export, False
        if export is not None and export.status == "running":
            return export, False
        if export is None:
            export = ReportExport(report_id=report_id, format=export_format, created_by=created_by)
        export.status = "running"
        export.error = None
        export.object_path = None
        export.content_hash = None
        export.updated_at = utcnow()
        self.db.add(export)
        self.db.commit()
        self.db.refresh(export)
        return export, True

    def run_export(self, export_id: str) -> ReportExport | None:
        export = self.get(export_id)
        if export is None:
            return None
        report_service = ReportService(self.db, self.object_store)
        report = report_service.get(export.report_id)
        if report is None:
            export.status = "failed"
            export.error = "Report not found"
            export.updated_at = utcnow()
            self.db.add(export)
            self.db.commit()
            self.db.refresh(export)
            return export
        job_service = JobService(self.db)
        job = job_service.start(report.case_id, "report_export_worker", {"report_id": report.id, "format": export.format})
        try:
            content = report_service.get_content(report)
            markdown = content if isinstance(content, str) else report_service.get_content(report)
            if not isinstance(markdown, str):
                markdown = html.escape(str(markdown))
            diagrams = DiagramService(self.db, self.object_store).generate_for_case(report.case_id, report.id, created_by="report_export_worker")
            markdown = self._sync_diagram_section(markdown, DiagramService(self.db, self.object_store).markdown_for_diagrams(diagrams))
            html_report = self._markdown_to_html(markdown, report_title=f"Report v{report.version}")
            pdf_bytes, metadata = self._render_pdf(html_report)
            object_key = f"cases/{report.case_id}/reports/report_v{report.version}.pdf"
            object_uri = self.object_store.put_bytes(pdf_bytes, object_key, "application/pdf")
            export.status = "success"
            export.object_path = object_uri
            export.content_hash = self.object_store.sha256_bytes(pdf_bytes)
            export.metadata_json = metadata | {"source_report_id": report.id, "generated_at": datetime.now(timezone.utc).isoformat()}
            export.updated_at = utcnow()
            self.db.add(export)
            self.db.commit()
            self.db.refresh(export)
            job_service.finish(job, "success", output={"export_id": export.id, "object_path": object_uri, "renderer": metadata.get("renderer")})
            return export
        except Exception as exc:
            export.status = "failed"
            export.error = str(exc)
            export.updated_at = utcnow()
            self.db.add(export)
            self.db.commit()
            self.db.refresh(export)
            job_service.finish(job, "failed", error=str(exc), output={"export_id": export.id})
            return export

    @staticmethod
    def run_export_background(export_id: str) -> None:
        db = SessionLocal()
        try:
            ReportExportService(db).run_export(export_id)
        finally:
            db.close()

    def _sync_diagram_section(self, markdown: str, diagram_markdown: str) -> str:
        replacement = f"## 4. 数据流图\n\n{diagram_markdown}\n\n"
        match = re.search(r"^## 4\. 数据流图\s*$", markdown, flags=re.MULTILINE)
        if not match:
            anchor = re.search(r"^## 5\. 根因分析\s*$", markdown, flags=re.MULTILINE)
            if anchor:
                return f"{markdown[:anchor.start()]}{replacement}{markdown[anchor.start():]}"
            return f"{markdown.rstrip()}\n\n{replacement}"
        next_section = re.search(r"^## 5\. 根因分析\s*$", markdown[match.end():], flags=re.MULTILINE)
        if not next_section:
            return f"{markdown[:match.start()]}{replacement}"
        end = match.end() + next_section.start()
        return f"{markdown[:match.start()]}{replacement}{markdown[end:]}"

    def download_bytes(self, export_id: str) -> tuple[ReportExport, bytes]:
        export = self.get(export_id)
        if export is None:
            raise HTTPException(status_code=404, detail="Report export not found")
        if export.status != "success" or not export.object_path:
            raise HTTPException(status_code=409, detail=f"Report export is {export.status}")
        return export, self.object_store.get_bytes(export.object_path)

    def _render_pdf(self, html_report: str) -> tuple[bytes, dict[str, Any]]:
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                page = browser.new_page(viewport={"width": 1280, "height": 1600})
                page.set_content(html_report, wait_until="networkidle", timeout=30000)
                try:
                    page.wait_for_function("() => window.__mermaidRendered === true", timeout=5000)
                except Exception:
                    pass
                pdf = page.pdf(
                    format="A4",
                    print_background=True,
                    margin={"top": "18mm", "right": "14mm", "bottom": "18mm", "left": "14mm"},
                    display_header_footer=True,
                    header_template='<div style="font-size:9px;color:#667;margin-left:14mm;">On-chain RCA Workbench</div>',
                    footer_template='<div style="font-size:9px;color:#667;margin:0 14mm;width:100%;text-align:right;"><span class="pageNumber"></span>/<span class="totalPages"></span></div>',
                )
                browser.close()
                return pdf, {"renderer": "playwright-chromium", "mermaid": "browser"}
        except Exception as exc:
            pdf = self._fallback_pdf("PDF renderer fallback", f"Chromium/Playwright unavailable: {exc}")
            return pdf, {"renderer": "fallback-minimal", "warning": str(exc)}

    def _markdown_to_html(self, markdown: str, report_title: str) -> str:
        blocks: list[str] = []
        lines = markdown.replace("\r\n", "\n").split("\n")
        index = 0
        while index < len(lines):
            line = lines[index]
            if not line.strip():
                index += 1
                continue
            if line.startswith("```"):
                language = line.strip().removeprefix("```").strip()
                code: list[str] = []
                index += 1
                while index < len(lines) and not lines[index].startswith("```"):
                    code.append(lines[index])
                    index += 1
                index += 1
                escaped = html.escape("\n".join(code))
                if language == "mermaid":
                    blocks.append(f'<pre class="mermaid">{escaped}</pre>')
                else:
                    blocks.append(f"<pre><code>{escaped}</code></pre>")
                continue
            heading = re.match(r"^(#{1,3})\s+(.*)$", line)
            if heading:
                level = len(heading.group(1))
                blocks.append(f"<h{level}>{self._inline(heading.group(2))}</h{level}>")
                index += 1
                continue
            if line.startswith("|") and index + 1 < len(lines) and re.match(r"^\|\s*:?-+", lines[index + 1]):
                rows: list[list[str]] = []
                while index < len(lines) and lines[index].startswith("|"):
                    if not re.match(r"^\|\s*:?-+", lines[index]):
                        rows.append([self._inline(cell.strip()) for cell in lines[index].strip("|").split("|")])
                    index += 1
                head, body = rows[0], rows[1:]
                blocks.append("<table><thead><tr>" + "".join(f"<th>{cell}</th>" for cell in head) + "</tr></thead><tbody>")
                for row in body:
                    blocks.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>")
                blocks.append("</tbody></table>")
                continue
            if line.startswith(">"):
                quote: list[str] = []
                while index < len(lines) and lines[index].startswith(">"):
                    quote.append(lines[index].lstrip("> "))
                    index += 1
                blocks.append("<section class=\"tldr\">" + "".join(f"<p>{self._inline(item)}</p>" for item in quote) + "</section>")
                continue
            if re.match(r"^\s*(-|\d+\.)\s+", line):
                ordered = bool(re.match(r"^\s*\d+\.\s+", line))
                tag = "ol" if ordered else "ul"
                items: list[str] = []
                pattern = r"^\s*\d+\.\s+" if ordered else r"^\s*-\s+"
                while index < len(lines) and re.match(pattern, lines[index]):
                    items.append(re.sub(pattern, "", lines[index]))
                    index += 1
                blocks.append(f"<{tag}>" + "".join(f"<li>{self._inline(item)}</li>" for item in items) + f"</{tag}>")
                continue
            paragraph: list[str] = []
            while index < len(lines) and lines[index].strip() and not re.match(r"^(#{1,3})\s+|```|>|\||\s*(-|\d+\.)\s+", lines[index]):
                paragraph.append(lines[index])
                index += 1
            blocks.append(f"<p>{self._inline(' '.join(paragraph))}</p>")
        return self._html_shell(report_title, "\n".join(blocks))

    def _html_shell(self, title: str, body: str) -> str:
        return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>{html.escape(title)}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif; color: #17202a; line-height: 1.62; }}
    h1 {{ font-size: 28px; margin: 0 0 18px; }}
    h2 {{ font-size: 20px; margin: 28px 0 12px; padding-bottom: 6px; border-bottom: 1px solid #d8dee6; }}
    h3 {{ font-size: 15px; margin: 18px 0 8px; }}
    p, li {{ font-size: 12px; }}
    code {{ font-family: "SFMono-Regular", Consolas, monospace; background: #eef2f7; padding: 1px 4px; border-radius: 3px; }}
    pre {{ white-space: pre-wrap; word-break: break-word; font-size: 10px; background: #f7f9fc; border: 1px solid #dfe5ee; border-radius: 6px; padding: 10px; }}
    .mermaid {{ background: #fff; }}
    table {{ width: 100%; border-collapse: collapse; margin: 10px 0 16px; font-size: 10px; table-layout: fixed; }}
    th, td {{ border: 1px solid #dfe5ee; padding: 6px; vertical-align: top; word-break: break-word; }}
    th {{ background: #f2f5f9; text-align: left; }}
    .tldr {{ border-left: 3px solid #276ef1; background: #f6f9ff; padding: 8px 12px; }}
  </style>
  <script type="module">
    import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
    mermaid.initialize({{ startOnLoad: false, securityLevel: 'strict', theme: 'default' }});
    mermaid.run().finally(() => {{ window.__mermaidRendered = true; }});
  </script>
</head>
<body>{body}</body>
</html>"""

    def _inline(self, text: str) -> str:
        escaped = html.escape(text)
        escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
        escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
        return escaped

    def _fallback_pdf(self, title: str, message: str) -> bytes:
        content = "\n".join(textwrap.wrap(f"{title}\n{message}", 78))
        stream = f"BT /F1 12 Tf 72 760 Td ({self._pdf_escape(content)}) Tj ET".encode("latin-1", "replace")
        objects = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
        ]
        out = io.BytesIO()
        out.write(b"%PDF-1.4\n")
        offsets = [0]
        for idx, obj in enumerate(objects, start=1):
            offsets.append(out.tell())
            out.write(f"{idx} 0 obj\n".encode("ascii") + obj + b"\nendobj\n")
        xref = out.tell()
        out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
        for offset in offsets[1:]:
            out.write(f"{offset:010d} 00000 n \n".encode("ascii"))
        out.write(f"trailer << /Root 1 0 R /Size {len(objects) + 1} >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii"))
        return out.getvalue()

    def _pdf_escape(self, text: str) -> str:
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").replace("\n", "\\n")
