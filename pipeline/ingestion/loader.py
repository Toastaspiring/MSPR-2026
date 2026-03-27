#!/usr/bin/env python3
"""
Bronze → Raw ingestion layer.

Scans bronze_data/ and loads every CSV into DuckDB `raw` schema.
Each table gets three metadata columns appended:
  - _source_usine  : e.g. 'Usine_A'
  - _source_file   : e.g. 'M1_Decoupe_Laser.csv'
  - _ingested_at   : load timestamp

Run from project root:
    python pipeline/ingestion/loader.py
"""
import sys
from pathlib import Path

import duckdb
from rich.console import Console
from rich.table import Table
from rich.progress import track

BRONZE_DIR   = Path("bronze_data")
WAREHOUSE_DIR = Path("warehouse")
DB_PATH      = WAREHOUSE_DIR / "industrial.duckdb"

console = Console()


def _table_name(csv_path: Path) -> str:
    """Map  bronze_data/Usine_A/M1_Decoupe_Laser.csv  →  raw.usine_a__m1_decoupe_laser"""
    usine   = csv_path.parent.name.lower().replace("-", "_")   # usine_a
    machine = csv_path.stem.lower()                             # m1_decoupe_laser
    return f"raw.{usine}__{machine}"


def ingest() -> None:
    WAREHOUSE_DIR.mkdir(exist_ok=True)

    csv_files = sorted(BRONZE_DIR.rglob("*.csv"))
    if not csv_files:
        console.print("[red]No CSV files found in bronze_data/[/red]")
        sys.exit(1)

    conn = duckdb.connect(str(DB_PATH))
    conn.execute("CREATE SCHEMA IF NOT EXISTS raw")

    results: list[tuple[str, int, str]] = []

    for csv_path in track(csv_files, description="Ingesting bronze -> raw ..."):
        table = _table_name(csv_path)
        try:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
            conn.execute(f"""
                CREATE TABLE {table} AS
                SELECT *,
                    '{csv_path.parent.name}' AS _source_usine,
                    '{csv_path.name}'        AS _source_file,
                    current_timestamp        AS _ingested_at
                FROM read_csv_auto(
                    '{csv_path.as_posix()}',
                    header      = true,
                    null_padding = true,
                    ignore_errors = true
                )
            """)
            rows = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            results.append((table, rows, "OK"))
        except Exception as exc:
            results.append((table, 0, f"ERROR: {exc}"))

    conn.close()

    # ── Summary ──────────────────────────────────────────────────────────────
    tbl = Table(title="Ingestion Summary", show_header=True, header_style="bold cyan")
    tbl.add_column("Table",  style="cyan",  no_wrap=True)
    tbl.add_column("Rows",   justify="right", style="green")
    tbl.add_column("Status", style="bold")

    errors = 0
    for name, count, status in results:
        color = "green" if status == "OK" else "red"
        tbl.add_row(name, str(count), f"[{color}]{status}[/{color}]")
        if status != "OK":
            errors += 1

    console.print(tbl)

    if errors:
        console.print(f"\n[red]{errors} table(s) failed to load.[/red]")
        sys.exit(1)
    else:
        total_rows = sum(r[1] for r in results)
        console.print(f"\n[green]Done. {len(results)} tables loaded, {total_rows:,} total rows.[/green]")


if __name__ == "__main__":
    ingest()
