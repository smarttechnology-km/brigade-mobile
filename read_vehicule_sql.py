#!/usr/bin/env python3
"""Read-only preview of vehicule.sql (a phpMyAdmin/MySQL dump).

Does NOT touch any database — it only parses the .sql text and prints a
summary: tables found, their columns, row counts, and a few sample rows
per table. Useful to inspect the legacy data before deciding what (if
anything) to import.

Usage:
    python3 read_vehicule_sql.py [path/to/vehicule.sql] [--samples N]
    python3 read_vehicule_sql.py --html apercu.html   # génère une page à ouvrir dans le navigateur
"""
import argparse
import json
import re
import sys
from pathlib import Path


def parse_create_tables(sql_text):
    """Return {table_name: [column_name, ...]} from CREATE TABLE statements."""
    tables = {}
    for m in re.finditer(
        r"CREATE TABLE(?:\s+IF NOT EXISTS)?\s+`(\w+)`\s*\((.*?)\n\)\s*(?:ENGINE|;)",
        sql_text,
        re.S,
    ):
        name, body = m.group(1), m.group(2)
        # Column lines look like: `Col_name` type ... ,  — grab the backticked names in order.
        cols = re.findall(r"^\s*[,]?\s*`(\w+)`", body, re.M)
        if cols:
            tables[name] = cols
    return tables


def split_top_level_tuples(values_blob):
    """Split a VALUES (a,b), (c,d), ... blob into a list of raw tuple bodies (without the parens)."""
    tuples = []
    depth = 0
    current = []
    in_string = False
    i, n = 0, len(values_blob)
    while i < n:
        ch = values_blob[i]
        if in_string:
            if ch == "\\" and i + 1 < n:
                current.append(values_blob[i : i + 2])
                i += 2
                continue
            if ch == "'":
                in_string = False
            current.append(ch)
        else:
            if ch == "'":
                in_string = True
                current.append(ch)
            elif ch == "(":
                depth += 1
                if depth > 1:
                    current.append(ch)
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    tuples.append("".join(current))
                    current = []
                else:
                    current.append(ch)
            else:
                if depth >= 1:
                    current.append(ch)
        i += 1
    return tuples


def split_fields(tuple_body):
    """Split one tuple's raw body into individual field literal strings."""
    fields = []
    current = []
    in_string = False
    i, n = 0, len(tuple_body)
    while i < n:
        ch = tuple_body[i]
        if in_string:
            if ch == "\\" and i + 1 < n:
                current.append(tuple_body[i : i + 2])
                i += 2
                continue
            if ch == "'":
                in_string = False
                current.append(ch)
                i += 1
                continue
            current.append(ch)
        else:
            if ch == "'":
                in_string = True
                current.append(ch)
            elif ch == ",":
                fields.append("".join(current).strip())
                current = []
            else:
                current.append(ch)
        i += 1
    if current:
        fields.append("".join(current).strip())
    return fields


def unquote(field):
    field = field.strip()
    if field.upper() == "NULL":
        return None
    if field.startswith("'") and field.endswith("'") and len(field) >= 2:
        inner = field[1:-1]
        inner = inner.replace("\\'", "'").replace('\\"', '"').replace("\\\\", "\\")
        return inner
    return field


def iter_insert_statements(sql_text):
    """Yield (table_name, values_blob) for every INSERT INTO ... VALUES ...; statement."""
    for m in re.finditer(
        r"INSERT INTO\s+`(\w+)`\s*\([^)]*\)\s*VALUES\s*(.*?);\s*(?:\n|$)",
        sql_text,
        re.S,
    ):
        yield m.group(1), m.group(2)


def build_html(path, size_mb, tables, row_counts, all_rows):
    """Return a standalone HTML page (no server needed) to browse the parsed tables."""
    payload = {
        name: {"columns": cols, "rows": all_rows.get(name, [])}
        for name, cols in tables.items()
    }
    data_json = json.dumps(payload, ensure_ascii=False)

    tabs_html = "\n".join(
        f'<button class="tab{" active" if i == 0 else ""}" data-table="{name}">'
        f'{name} <span class="count">{row_counts.get(name, 0)}</span></button>'
        for i, name in enumerate(tables)
    )

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<title>Aperçu vehicule.sql</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Arial, sans-serif; margin: 0; background: #f4f5f7; color: #1a1a1a; }}
  header {{ background: #003399; color: #fff; padding: 14px 20px; }}
  header h1 {{ margin: 0; font-size: 18px; }}
  header .sub {{ font-size: 12px; opacity: .85; margin-top: 2px; }}
  .tabs {{ display: flex; gap: 6px; padding: 10px 20px; background: #fff; border-bottom: 1px solid #ddd; flex-wrap: wrap; }}
  .tab {{ border: 1px solid #ccd; background: #eef1fb; color: #003399; padding: 6px 14px; border-radius: 20px; cursor: pointer; font-size: 13px; }}
  .tab.active {{ background: #003399; color: #fff; }}
  .count {{ opacity: .7; font-size: 11px; }}
  .toolbar {{ padding: 12px 20px; display: flex; gap: 10px; align-items: center; background: #fff; }}
  .toolbar input {{ flex: 1; max-width: 420px; padding: 7px 10px; border: 1px solid #ccc; border-radius: 6px; font-size: 13px; }}
  .toolbar .info {{ font-size: 12px; color: #555; }}
  .table-wrap {{ margin: 0 20px 20px; background: #fff; border-radius: 8px; overflow: auto; max-height: 70vh; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
  table {{ border-collapse: collapse; width: 100%; font-size: 12.5px; white-space: nowrap; }}
  th, td {{ border-bottom: 1px solid #eee; padding: 6px 10px; text-align: left; }}
  th {{ position: sticky; top: 0; background: #f0f2f8; color: #003399; z-index: 1; }}
  tr:hover td {{ background: #f7f9ff; }}
  .pager {{ display: flex; gap: 8px; align-items: center; padding: 10px 20px 20px; font-size: 13px; }}
  .pager button {{ padding: 5px 12px; border: 1px solid #ccc; background: #fff; border-radius: 6px; cursor: pointer; }}
  .pager button:disabled {{ opacity: .4; cursor: default; }}
  .null {{ color: #bbb; font-style: italic; }}
</style>
</head>
<body>
<header>
  <h1>Aperçu de {path.name}</h1>
  <div class="sub">{size_mb:.2f} Mo — {len(tables)} table(s) — lecture seule, rien n'a été écrit en base</div>
</header>
<div class="tabs">{tabs_html}</div>
<div class="toolbar">
  <input id="search" type="text" placeholder="Rechercher (toutes colonnes)...">
  <span class="info" id="info"></span>
</div>
<div class="table-wrap"><table><thead><tr id="thead-row"></tr></thead><tbody id="tbody"></tbody></table></div>
<div class="pager">
  <button id="prev">&larr; Précédent</button>
  <span id="page-label"></span>
  <button id="next">Suivant &rarr;</button>
</div>
<script>
const DATA = {data_json};
const TABLES = Object.keys(DATA);
const PAGE_SIZE = 200;
let current = TABLES[0];
let filtered = [];
let page = 0;

function esc(v) {{
  if (v === null || v === undefined) return '<span class="null">NULL</span>';
  return String(v).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}}

function renderHead() {{
  const cols = DATA[current].columns;
  document.getElementById('thead-row').innerHTML = cols.map(c => `<th>${{esc(c)}}</th>`).join('');
}}

function applyFilter() {{
  const q = document.getElementById('search').value.trim().toLowerCase();
  const rows = DATA[current].rows;
  filtered = !q ? rows : rows.filter(r => r.some(v => v !== null && String(v).toLowerCase().includes(q)));
  page = 0;
  renderPage();
}}

function renderPage() {{
  const start = page * PAGE_SIZE;
  const slice = filtered.slice(start, start + PAGE_SIZE);
  document.getElementById('tbody').innerHTML = slice.map(r => `<tr>${{r.map(v => `<td>${{esc(v)}}</td>`).join('')}}</tr>`).join('');
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  document.getElementById('page-label').textContent = `Page ${{page + 1}} / ${{totalPages}} (${{filtered.length}} lignes)`;
  document.getElementById('info').textContent = `${{filtered.length}} / ${{DATA[current].rows.length}} lignes affichées`;
  document.getElementById('prev').disabled = page === 0;
  document.getElementById('next').disabled = start + PAGE_SIZE >= filtered.length;
}}

function selectTable(name) {{
  current = name;
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.table === name));
  document.getElementById('search').value = '';
  renderHead();
  applyFilter();
}}

document.querySelectorAll('.tab').forEach(t => t.addEventListener('click', () => selectTable(t.dataset.table)));
document.getElementById('search').addEventListener('input', applyFilter);
document.getElementById('prev').addEventListener('click', () => {{ if (page > 0) {{ page--; renderPage(); }} }});
document.getElementById('next').addEventListener('click', () => {{ if ((page+1) * PAGE_SIZE < filtered.length) {{ page++; renderPage(); }} }});

renderHead();
applyFilter();
</script>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default="vehicule.sql", help="Path to the .sql dump")
    parser.add_argument("--samples", type=int, default=3, help="Sample rows to show per table (console output)")
    parser.add_argument("--html", metavar="OUT.html", help="Écrit aussi une page HTML consultable dans un navigateur")
    args = parser.parse_args()

    path = Path(args.path)
    if not path.exists():
        print(f"Fichier introuvable : {path}", file=sys.stderr)
        sys.exit(1)

    sql_text = path.read_text(encoding="utf-8", errors="replace")
    size_mb = path.stat().st_size / (1024 * 1024)

    tables = parse_create_tables(sql_text)

    row_counts = {name: 0 for name in tables}
    all_rows = {name: [] for name in tables}

    for table, values_blob in iter_insert_statements(sql_text):
        if table not in tables:
            continue
        for tuple_body in split_top_level_tuples(values_blob):
            row_counts[table] += 1
            fields = [unquote(f) for f in split_fields(tuple_body)]
            all_rows[table].append(fields)

    print(f"Fichier : {path} ({size_mb:.2f} Mo)")
    print(f"Tables trouvées : {len(tables)}")
    print("=" * 70)

    for name, cols in tables.items():
        print(f"\nTable `{name}`")
        print(f"  Colonnes ({len(cols)}) : {', '.join(cols)}")
        print(f"  Lignes    : {row_counts.get(name, 0)}")
        for i, row in enumerate(all_rows.get(name, [])[: args.samples], 1):
            preview = dict(zip(cols, row))
            print(f"  Exemple {i}: {preview}")

    print("\n" + "=" * 70)
    print("Aperçu terminé — aucune donnée n'a été écrite en base.")

    if args.html:
        out_path = Path(args.html)
        html = build_html(path, size_mb, tables, row_counts, all_rows)
        out_path.write_text(html, encoding="utf-8")
        print(f"\nPage HTML générée : {out_path.resolve()}")
        print(f"Ouvre-la avec :  open {out_path}")


if __name__ == "__main__":
    main()


'python3 read_vehicule_sql.py --html apercu.html'
'open apercu.html'