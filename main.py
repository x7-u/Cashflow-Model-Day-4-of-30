"""Day 4. CLI entry for the cash flow forecasting model.

Usage:
    python main.py --input sample_data/sample_services.xlsx
    python main.py --input ./my_forecast.xlsx --scenario "what if revenue drops 20% for 3 weeks?"
    python main.py --input ./my_forecast.xlsx --no-ai

Outputs land in ./outputs/. Skipping AI keeps the run fully deterministic.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for p in (str(HERE), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from csv_writer import write_csv_pair
from excel_writer import write_workbook
from pipeline import analyse, run_scenario

OUTPUTS = HERE / "outputs"


def main() -> int:
    parser = argparse.ArgumentParser(description="Cash Flow Forecasting Model (Day 4)")
    parser.add_argument("--input", "-i", required=True, help="Path to a forecast .xlsx workbook")
    parser.add_argument("--scenario", "-s", default=None,
                        help="Free-text scenario question. If omitted, only the base run is produced.")
    parser.add_argument("--no-ai", action="store_true", help="Skip the DeepSeek scenario call")
    parser.add_argument("--model", default=None,
                        help="Override the default model (e.g. deepseek-chat, deepseek-reasoner)")
    parser.add_argument("--api-key", default=None,
                        help="Override DEEPSEEK_API_KEY for this run only (not persisted)")
    args = parser.parse_args()

    in_path = Path(args.input).expanduser().resolve()
    if not in_path.is_file():
        print(f"Input not found: {in_path}", file=sys.stderr)
        return 2
    if in_path.suffix.lower() != ".xlsx":
        print(f"Input must be an .xlsx workbook (got {in_path.suffix}).", file=sys.stderr)
        return 2

    try:
        result = analyse(
            path=in_path, source_filename=in_path.name,
            skip_ai=args.no_ai, model=args.model, api_key=args.api_key,
        )
    except ValueError as e:
        print(f"Validation error: {e}", file=sys.stderr)
        return 1

    h = result.headline
    print()
    print(f"  Company:  {result.metadata.company}")
    print(f"  Period:   {result.metadata.period_label}")
    print(f"  Lines:    {len(result.lines)}")
    print(f"  Opening:  GBP {h.opening_balance:>12,.2f}")
    print(f"  Closing:  GBP {h.closing_balance:>12,.2f}")
    print(f"  Min:      GBP {h.min_balance:>12,.2f} (W{h.min_balance_week})")
    print(f"  Max:      GBP {h.max_balance:>12,.2f} (W{h.max_balance_week})")
    print(f"  Runway:   {('beyond horizon' if h.runway_weeks is None else f'W{h.runway_weeks}')}")
    print(f"  Buffer:   GBP {h.buffer_used:>12,.2f}")
    print(f"  Net:      GBP {h.cumulative_net:>12,.2f}")
    if result.warnings:
        print(f"  Warnings: {len(result.warnings)}")
        for w in result.warnings[:5]:
            print(f"    . {w}")

    if result.commentary and not result.commentary.skipped:
        bc = result.commentary
        if bc.error:
            print(f"  AI:       error. {bc.error}")
        else:
            print(f"  AI:       ${bc.cost_usd:.4f}, {bc.input_tokens} in / {bc.output_tokens} out, {bc.model}")
            print(f"  Headline: {bc.headline}")

    scenario = None
    if args.scenario:
        print()
        print(f"  Scenario: {args.scenario}")
        scenario = run_scenario(
            base=result, user_prompt=args.scenario,
            model=args.model, api_key=args.api_key, skip_ai=args.no_ai,
        )
        sc = scenario.commentary
        if sc.skipped:
            print("  AI:       skipped (deterministic only)")
        elif sc.error:
            print(f"  AI:       error. {sc.error}")
        else:
            print(f"  AI:       ${sc.cost_usd:.4f}, {sc.input_tokens} in / {sc.output_tokens} out, {sc.model}")
            print(f"  Headline: {sc.headline}")
            if sc.interpretation:
                print(f"  Reading:  {sc.interpretation}")

    xlsx_path = write_workbook(
        result if scenario is None else scenario.scenario,
        OUTPUTS,
        scenario=scenario,
    )
    weekly_csv, lines_csv = write_csv_pair(result, OUTPUTS)

    print()
    print(f"  Wrote: {xlsx_path.name}")
    print(f"         {weekly_csv.name}")
    print(f"         {lines_csv.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
