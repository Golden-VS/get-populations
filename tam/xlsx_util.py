"""Kleine Excel-hulpjes voor template en uitvoer."""
import math

from openpyxl.utils import get_column_letter

MAX_WIDTH = 80   # bovengrens zodat een enkele lange kolom het blad niet onleesbaar maakt


def _split_column_blocks(ws) -> None:
    """Excel bewaart gelijke kolommen soms als een blok (bv. A:B). Splits zulke blokken in
    losse kolommen met dezelfde breedte, zodat een latere aanpassing van een kolom geen
    overlappende definities oplevert."""
    for letter, dim in list(ws.column_dimensions.items()):
        if dim.min and dim.max and dim.max > dim.min:
            first, last, width = dim.min, dim.max, dim.width
            dim.max = first
            for idx in range(first + 1, last + 1):
                other = ws.column_dimensions[get_column_letter(idx)]
                other.min = other.max = idx
                if width:
                    other.width = width


def sync_tables(ws) -> None:
    """Houd Excel-tabellen (Opmaken als tabel) gelijk met het blad: bereik tot de laatste
    kolom/rij en kolomnamen gelijk aan de kopregel. Anders weigert Excel het bestand."""
    from openpyxl.worksheet.table import TableColumn

    if not ws.tables:
        return
    header = [c.value for c in ws[1]]
    while header and header[-1] in (None, ''):
        header.pop()
    ref = f'A1:{get_column_letter(len(header))}{max(ws.max_row, 2)}'
    for table in ws.tables.values():
        table.ref = ref
        if table.autoFilter is not None:
            table.autoFilter.ref = ref
        table.tableColumns = [TableColumn(id=i + 1, name=str(h) if h is not None else f'Kolom{i + 1}')
                              for i, h in enumerate(header)]


def autofit_columns(ws, quantile: float = 0.8, skip: set | None = None) -> None:
    """Zet elke kolombreedte zo dat minstens `quantile` van de gevulde waarden past,
    en nooit smaller dan de kop. Kolommen in `skip` (letters) houden hun breedte."""
    skip = skip or set()
    _split_column_blocks(ws)
    for col_idx, cells in enumerate(ws.iter_cols(values_only=True), start=1):
        letter = get_column_letter(col_idx)
        if letter in skip or not cells:
            continue
        header = len(str(cells[0])) if cells[0] is not None else 0
        lengths = sorted(len(str(v)) for v in cells[1:] if v is not None and str(v) != '')
        fit = 0
        if lengths:
            fit = lengths[max(0, math.ceil(quantile * len(lengths)) - 1)]
        dim = ws.column_dimensions[letter]
        dim.min = dim.max = col_idx   # nooit een blok over meerdere kolommen (Excel weigert overlap)
        dim.width = min(max(header, fit, 6) + 2, MAX_WIDTH)


def write_instructions(wb, rows: list, title: str = 'instructies') -> None:
    """(Her)bouw een instructieblad als eerste tabblad en maak het actief. `rows` is een
    lijst (kop, tekst); koppen zonder inspringing worden vet, de eerste rij groter."""
    from openpyxl.styles import Alignment, Font

    if title in wb.sheetnames:
        del wb[title]
    ws = wb.create_sheet(title, 0)
    for left, right in rows:
        ws.append([left, right])
        row = ws.max_row
        ws.cell(row, 1).alignment = Alignment(vertical='top')
        ws.cell(row, 2).alignment = Alignment(wrap_text=True, vertical='top')
        if left and not left.startswith('  '):
            ws.cell(row, 1).font = Font(bold=True, size=14 if row == 1 else 11)
    ws.column_dimensions['A'].width = 26
    ws.column_dimensions['B'].width = 100
    wb.active = 0
