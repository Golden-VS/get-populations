"""Maakt doc/TAM_WHITESPACE_OVERVIEW.pdf: uitleg van 2 pagina's voor niet-technische lezers.

Gebruik: venv/bin/python tools/make_tam_overview_pdf.py
Alle getallen in het voorbeeld zijn fictief; geen bedrijfs- of productnamen.
"""
from pathlib import Path

from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

OUT = Path(__file__).resolve().parents[1] / 'doc' / 'TAM_WHITESPACE_OVERVIEW.pdf'

NAVY = colors.HexColor('#1F3A5F')
BLACK_SPACE = colors.HexColor('#3A3A3A')
WHITE_SPACE = colors.HexColor('#F2F2F2')
ACCENT = colors.HexColor('#DDEBF7')
GREEN = colors.HexColor('#E2EFDA')

ss = getSampleStyleSheet()
H1 = ParagraphStyle('H1', parent=ss['Title'], fontSize=17, leading=21, textColor=NAVY,
                    alignment=TA_LEFT, spaceAfter=2)
SUB = ParagraphStyle('SUB', parent=ss['Normal'], fontSize=10, leading=13,
                     textColor=colors.HexColor('#555555'), spaceAfter=6)
H2 = ParagraphStyle('H2', parent=ss['Heading2'], fontSize=12, leading=15, textColor=NAVY,
                    spaceBefore=6, spaceAfter=3)
BODY = ParagraphStyle('BODY', parent=ss['Normal'], fontSize=9.3, leading=12.3)
SMALL = ParagraphStyle('SMALL', parent=BODY, fontSize=8, leading=10,
                       textColor=colors.HexColor('#555555'))
CELL = ParagraphStyle('CELL', parent=BODY, fontSize=8.6, leading=11)
CELLB = ParagraphStyle('CELLB', parent=CELL, fontName='Helvetica-Bold')


def p(text, style=BODY):
    return Paragraph(text, style)


def flow_diagram(width):
    """Vijf stappen als blokken met pijlen."""
    steps = [
        ('1. Choose the', 'market', 'Business'),
        ('2. List all possible', 'customers', 'Automatic'),
        ('3. Find who is', 'already a customer', 'Automatic + check'),
        ('4. Add contract', 'revenue', 'Power BI'),
        ('5. Show black and', 'white space in EUR', 'Power BI'),
    ]
    h = 30 * mm
    d = Drawing(width, h)
    gap = 5 * mm
    box_w = (width - gap * (len(steps) - 1)) / len(steps)
    box_h = 17 * mm
    y = 9 * mm
    for i, (l1, l2, who) in enumerate(steps):
        x = i * (box_w + gap)
        d.add(Rect(x, y, box_w, box_h, rx=3, ry=3, fillColor=ACCENT, strokeColor=NAVY,
                   strokeWidth=0.8))
        d.add(String(x + box_w / 2, y + box_h - 7 * mm, l1, fontName='Helvetica-Bold',
                     fontSize=7.6, fillColor=NAVY, textAnchor='middle'))
        d.add(String(x + box_w / 2, y + box_h - 11 * mm, l2, fontName='Helvetica-Bold',
                     fontSize=7.6, fillColor=NAVY, textAnchor='middle'))
        d.add(String(x + box_w / 2, y - 5 * mm, who, fontName='Helvetica-Oblique',
                     fontSize=7, fillColor=colors.HexColor('#555555'), textAnchor='middle'))
        if i < len(steps) - 1:
            ax = x + box_w + 0.6 * mm
            ay = y + box_h / 2
            d.add(Line(ax, ay, ax + gap - 2.2 * mm, ay, strokeColor=NAVY, strokeWidth=1))
            d.add(Polygon([ax + gap - 2.4 * mm, ay + 1.4 * mm, ax + gap - 0.6 * mm, ay,
                           ax + gap - 2.4 * mm, ay - 1.4 * mm], fillColor=NAVY,
                          strokeColor=NAVY))
    return d


def space_bar(width):
    """Balk die de TAM verdeelt in black space en white space (voorbeeld)."""
    d = Drawing(width, 16 * mm)
    total, black = 530, 384
    bw = width * black / total
    y = 4 * mm
    d.add(Rect(0, y, bw, 8 * mm, fillColor=BLACK_SPACE, strokeColor=BLACK_SPACE))
    d.add(Rect(bw, y, width - bw, 8 * mm, fillColor=WHITE_SPACE, strokeColor=colors.grey,
               strokeWidth=0.5))
    d.add(String(bw / 2, y + 2.8 * mm, 'Black space: 384 organisations already pay',
                 fontName='Helvetica-Bold', fontSize=8, fillColor=colors.white,
                 textAnchor='middle'))
    d.add(String(bw + (width - bw) / 2, y + 2.8 * mm, 'White space: 146 to win',
                 fontName='Helvetica-Bold', fontSize=8, fillColor=BLACK_SPACE,
                 textAnchor='middle'))
    d.add(String(0, y + 9.5 * mm, 'Example: total addressable market (TAM) for core product X '
                 'in one country = 530 organisations', fontName='Helvetica', fontSize=7.6,
                 fillColor=colors.HexColor('#555555')))
    return d


def build():
    doc = SimpleDocTemplate(str(OUT), pagesize=A4, leftMargin=17 * mm, rightMargin=17 * mm,
                            topMargin=14 * mm, bottomMargin=13 * mm,
                            title='Black and white space per core product',
                            author='TAM / whitespace project')
    width = A4[0] - 34 * mm
    s = []

    # ---------------------------------------------------------------- pagina 1
    s.append(p('Black space and white space per core product', H1))
    s.append(p('How the Power BI report shows, per sales unit and core product, where we '
               'already sell and where we can still grow, and what that is worth.', SUB))

    s.append(p('The question the report answers', H2))
    s.append(p('For every core product: <b>which government organisations could buy it</b> '
               '(the market), <b>which of them already pay for it</b>, and <b>how much revenue '
               'is still out there</b>. You see this per sales unit, per core product and per '
               'country (Netherlands, Belgium, Germany, the Dutch Caribbean and Suriname).', BODY))

    s.append(p('Five words to know', H2))
    terms = [
        ('TAM', 'Total addressable market: all organisations that could realistically buy '
                'this core product.'),
        ('Black space', 'Organisations in the TAM that already have a recurring contract for '
                        'this core product.'),
        ('White space', 'Organisations in the TAM that do not (yet). This is the growth '
                        'potential.'),
        ('Inhabitants', 'Every organisation carries the number of inhabitants it serves. A '
                        'cooperation of five municipalities serves the inhabitants of all five.'),
        ('ARPU', 'Average revenue per inhabitant we earn today with this core product, used to '
                 'put a euro value on the white space.'),
    ]
    t = Table([[p(f'<b>{a}</b>', CELL), p(b, CELL)] for a, b in terms],
              colWidths=[28 * mm, width - 28 * mm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), ACCENT),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LINEBELOW', (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ('TOPPADDING', (0, 0), (-1, -1), 2.5), ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
    ]))
    s.append(t)

    s.append(p('The flow in five steps', H2))
    s.append(flow_diagram(width))
    steps = [
        ('1. Choose the market.',
         'Per sales unit, core product and country, the business fills in one row in an Excel '
         'template: which kinds of organisations belong to the market (for example '
         'municipalities and inter-municipal cooperations), which kinds to leave out (for example '
         'waste or recreation bodies), and a minimum size (for example at least 10,000 '
         'inhabitants, because smaller ones rarely buy).'),
        ('2. List all possible customers.',
         'A program builds one complete list of government organisations from official public '
         'registers (national statistics offices and government organisation registers), not '
         'from memory or guesswork. Every organisation gets its type and the inhabitants it '
         'serves. It then applies the choices from step 1.'),
        ('3. Find who is already a customer.',
         'Each organisation is linked to our own CRM accounts: first by fixed rules (Chamber of '
         'Commerce number, exact name), then by AI for the harder cases (old names of merged '
         'municipalities, departments, spelling). Every link shows how sure it is; the team '
         'checks the uncertain ones and can correct any link in the template.'),
        ('4. Add contract revenue.',
         'Power BI combines this list with our recurring contract revenue (subscriptions only, '
         'no one-off sales) per account and core product.'),
        ('5. Show black and white space.',
         'Organisations with recurring revenue for the core product are black space, the rest '
         'is white space. Power BI then puts a euro value on the white space (see page 2).'),
    ]
    for head, text in steps:
        s.append(p(f'<b>{head}</b> {text}', BODY))
        s.append(Spacer(1, 2.2))

    s.append(PageBreak())

    # ---------------------------------------------------------------- pagina 2
    s.append(p('What you will see in the report', H2))
    s.append(space_bar(width))
    s.append(Spacer(1, 3))
    s.append(p('Per sales unit and core product (and filterable per country and type of '
               'organisation) the report shows a table like the example below. '
               '<i>All numbers on this page are made up for illustration.</i>', BODY))
    s.append(Spacer(1, 4))

    hdr = ['Sales unit', 'Core product', 'TAM\n(orgs)', 'Black space\n(customers)',
           'White space\n(to win)', 'White space\nvalue / year', 'Winnable\nper year']
    rows = [
        ['Sales unit A', 'Core product X', '530', '384', '146', 'EUR 210,000', 'EUR 21,000'],
        ['Sales unit A', 'Core product Y', '342', '120', '222', 'EUR 480,000', 'EUR 48,000'],
        ['Sales unit B', 'Core product Z', '1,250', '310', '940', 'EUR 1,150,000', 'EUR 115,000'],
    ]
    hdr_style = ParagraphStyle('hdr', parent=CELL, textColor=colors.white)
    data = [[p(f'<b>{h}</b>'.replace('\n', '<br/>'), hdr_style) for h in hdr]] + \
           [[p(c, CELL) for c in r] for r in rows]
    cw = [26 * mm, 28 * mm, 22 * mm, 23 * mm, 21 * mm, 28 * mm]
    cw.append(width - sum(cw))
    t = Table(data, colWidths=cw, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), NAVY),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('BACKGROUND', (3, 1), (3, -1), colors.HexColor('#D9D9D9')),
        ('BACKGROUND', (4, 1), (6, -1), GREEN),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 2.5), ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
    ]))
    s.append(t)
    s.append(Spacer(1, 3))
    s.append(p('You can open each line to see the actual organisations: which ones pay, which '
               'ones do not, and how many inhabitants each serves.', BODY))

    s.append(p('How the euro value is calculated', H2))
    calc = [
        ('White space value',
         'For each organisation in the white space: <b>inhabitants x ARPU per inhabitant x '
         'factor</b>. The ARPU comes from what municipalities pay us today. The factor corrects '
         'for the type of organisation: a province pays far less per inhabitant than a '
         'municipality (for example 10%). The business sets these factors in Power BI.'),
        ('Winnable per year',
         'Customers do not switch every year. We use our own average churn: with 10% churn a '
         'customer stays about 10 years, and we assume the same for competitors. So about '
         '<b>10% of the white space comes up for grabs each year</b>. This is a simple '
         'estimate: as our market share grows, the winnable part shrinks.'),
        ('Cooperations',
         'When a cooperation (for example a shared service centre of five municipalities) holds '
         'the contract, its member municipalities can count as covered, so they do not show up '
         'as white space by mistake.'),
    ]
    t = Table([[p(f'<b>{a}</b>', CELL), p(b, CELL)] for a, b in calc],
              colWidths=[32 * mm, width - 32 * mm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), GREEN),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LINEBELOW', (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    s.append(t)

    s.append(p('Good to know', H2))
    notes = [
        'The list of organisations comes from official registers and is refreshed once a year, '
        'together with a fresh export of our CRM.',
        'Some organisations have no known number of inhabitants (for example cooperations of '
        'provinces or water boards). They are marked, so the report can show them separately '
        'instead of silently leaving them out.',
        'If the report shows a paying customer as white space, the link to our CRM is usually '
        'missing. The team fixes this in the template and the next run picks it up.',
        'Organisations below the minimum size or of an excluded type stay visible with the '
        'reason, so nothing disappears without explanation.',
    ]
    for n in notes:
        s.append(p(f'&bull; {n}', BODY))
        s.append(Spacer(1, 1.5))

    s.append(p('Who does what', H2))
    who = [
        [p('<b>Business</b>', CELL), p('Chooses the market per core product and country (step 1), '
                                       'sets the factors and checks uncertain links.', CELL)],
        [p('<b>Data team</b>', CELL), p('Runs the yearly refresh (registers, CRM export, linking) '
                                        'and delivers one Excel file for Power BI.', CELL)],
        [p('<b>Power BI</b>', CELL), p('Combines the file with recurring revenue and shows black '
                                       'space, white space and their value.', CELL)],
    ]
    t = Table(who, colWidths=[28 * mm, width - 28 * mm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), ACCENT),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LINEBELOW', (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ('TOPPADDING', (0, 0), (-1, -1), 2.5), ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
    ]))
    s.append(KeepTogether(t))

    doc.build(s)
    return OUT


if __name__ == '__main__':
    print(f'geschreven: {build()}')
