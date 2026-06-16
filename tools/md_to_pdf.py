"""
md_to_pdf.py
============
Rendert een Markdown-bestand naar een opgemaakte PDF (de "marked up view").
Pure Python (markdown + reportlab), geen systeembibliotheken nodig.

Ondersteunt de Markdown-subset die in onze docs voorkomt: kopjes (#, ##, ###),
alinea's, fenced code blocks (```), pipe-tabellen, opsommingen (- ), blockquotes
(> ), en inline **vet**, `code` en [links](url).

GEBRUIK:
    python tools/md_to_pdf.py doc/MANUAL.md doc/MANUAL.pdf
"""

import re
import sys
from html import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    ListFlowable, ListItem, Paragraph, Preformatted, SimpleDocTemplate,
    Spacer, Table, TableStyle,
)

CODE_BG = colors.HexColor('#f4f4f4')
HEADER_BG = colors.HexColor('#34495e')
HEADER_FG = colors.white
ROW_ALT = colors.HexColor('#f7f9fa')
GRID = colors.HexColor('#cccccc')
LINK = colors.HexColor('#1a5276')


def _styles():
    ss = getSampleStyleSheet()
    base = ss['BodyText']
    base.fontName = 'Helvetica'
    base.fontSize = 9.5
    base.leading = 13
    base.spaceAfter = 6
    base.alignment = TA_LEFT
    out = {'body': base}
    out['h1'] = ParagraphStyle('h1', parent=base, fontName='Helvetica-Bold',
                               fontSize=19, leading=23, spaceBefore=4, spaceAfter=10)
    out['h2'] = ParagraphStyle('h2', parent=base, fontName='Helvetica-Bold',
                               fontSize=14, leading=18, spaceBefore=14, spaceAfter=6,
                               textColor=HEADER_BG)
    out['h3'] = ParagraphStyle('h3', parent=base, fontName='Helvetica-Bold',
                               fontSize=11.5, leading=15, spaceBefore=9, spaceAfter=4)
    out['cell'] = ParagraphStyle('cell', parent=base, fontSize=8.3, leading=11,
                                 spaceAfter=0)
    out['cellh'] = ParagraphStyle('cellh', parent=out['cell'],
                                  fontName='Helvetica-Bold', textColor=HEADER_FG)
    out['quote'] = ParagraphStyle('quote', parent=base, leftIndent=10,
                                  borderColor=GRID, textColor=colors.HexColor('#555555'),
                                  fontName='Helvetica-Oblique')
    out['code'] = ParagraphStyle('code', parent=base, fontName='Courier',
                                 fontSize=8, leading=10.5, backColor=CODE_BG,
                                 borderPadding=6, spaceBefore=2, spaceAfter=8,
                                 leftIndent=2, textColor=colors.HexColor('#222222'))
    return out


def inline(md):
    """Markdown inline -> reportlab mini-HTML (escaped)."""
    # Beschermen: code spans eerst eruit halen zodat ** binnen `..` niet matcht.
    spans = []

    def stash(m):
        spans.append(m.group(1))
        return f'\x00{len(spans) - 1}\x00'

    md = re.sub(r'`([^`]+)`', stash, md)
    md = escape(md)
    md = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', md)
    md = re.sub(r'\[([^\]]+)\]\((https?://[^)]+)\)',
                rf'<a href="\2" color="#1a5276"><u>\1</u></a>', md)

    def unstash(m):
        code = escape(spans[int(m.group(1))])
        return (f'<font face="Courier" size="8" backColor="#f0f0f0"> {code} </font>')

    md = re.sub(r'\x00(\d+)\x00', unstash, md)
    return md


def build(md_path, pdf_path):
    lines = open(md_path, encoding='utf-8').read().split('\n')
    S = _styles()
    flow = []
    i = 0
    n = len(lines)

    while i < n:
        ln = lines[i]

        # fenced code block
        if ln.lstrip().startswith('```'):
            i += 1
            buf = []
            while i < n and not lines[i].lstrip().startswith('```'):
                buf.append(lines[i])
                i += 1
            i += 1  # closing fence
            flow.append(Preformatted('\n'.join(buf) or ' ', S['code']))
            continue

        # table block
        if ln.strip().startswith('|') and i + 1 < n and re.match(r'^\s*\|[\s:|-]+\|\s*$', lines[i + 1]):
            rows = []
            header = [c.strip() for c in ln.strip().strip('|').split('|')]
            i += 2  # header + separator
            while i < n and lines[i].strip().startswith('|'):
                rows.append([c.strip() for c in lines[i].strip().strip('|').split('|')])
                i += 1
            flow.append(_table(header, rows, S))
            flow.append(Spacer(1, 6))
            continue

        # headings
        m = re.match(r'^(#{1,3})\s+(.*)$', ln)
        if m:
            lvl = len(m.group(1))
            flow.append(Paragraph(inline(m.group(2)), S[f'h{lvl}']))
            i += 1
            continue

        # blockquote (possibly multi-line)
        if ln.startswith('>'):
            buf = []
            while i < n and lines[i].startswith('>'):
                buf.append(lines[i].lstrip('>').strip())
                i += 1
            flow.append(Paragraph(inline(' '.join(buf)), S['quote']))
            continue

        # bullet list
        if re.match(r'^\s*[-*]\s+', ln):
            items = []
            while i < n and re.match(r'^\s*[-*]\s+', lines[i]):
                items.append(ListItem(Paragraph(inline(re.sub(r'^\s*[-*]\s+', '', lines[i])),
                                                S['body']), leftIndent=12))
                i += 1
            flow.append(ListFlowable(items, bulletType='bullet', start='•',
                                     leftIndent=10))
            continue

        # horizontal rule
        if re.match(r'^\s*---+\s*$', ln):
            flow.append(Spacer(1, 4))
            i += 1
            continue

        # blank
        if not ln.strip():
            i += 1
            continue

        # paragraph (join until blank/structural line)
        buf = [ln]
        i += 1
        while i < n and lines[i].strip() and not re.match(
                r'^(#{1,3}\s|>|\s*[-*]\s|\s*\||```)', lines[i]):
            buf.append(lines[i])
            i += 1
        flow.append(Paragraph(inline(' '.join(buf)), S['body']))

    doc = SimpleDocTemplate(pdf_path, pagesize=A4,
                            leftMargin=1.8 * cm, rightMargin=1.8 * cm,
                            topMargin=1.6 * cm, bottomMargin=1.6 * cm,
                            title='Account Enrichment - Manual')
    doc.build(flow)


def _table(header, rows, S):
    ncols = len(header)

    def fix(r):
        r = (r + [''] * ncols)[:ncols]
        return r

    data = [[Paragraph(inline(c), S['cellh']) for c in fix(header)]]
    for r in rows:
        data.append([Paragraph(inline(c), S['cell']) for c in fix(r)])

    t = Table(data, repeatRows=1, hAlign='LEFT')
    style = [
        ('BACKGROUND', (0, 0), (-1, 0), HEADER_BG),
        ('GRID', (0, 0), (-1, -1), 0.5, GRID),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]
    for ri in range(1, len(data)):
        if ri % 2 == 0:
            style.append(('BACKGROUND', (0, ri), (-1, ri), ROW_ALT))
    t.setStyle(TableStyle(style))
    return t


if __name__ == '__main__':
    src = sys.argv[1] if len(sys.argv) > 1 else 'doc/MANUAL.md'
    dst = sys.argv[2] if len(sys.argv) > 2 else 'doc/MANUAL.pdf'
    build(src, dst)
    print(f'wrote {dst}')
