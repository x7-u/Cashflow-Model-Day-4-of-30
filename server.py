"""Day 4. Cash Flow Forecasting Model, local Flask server.

Pure-local: bound to 127.0.0.1:1004 by default. Day-N port convention,
each day binds to port 1000 + N. Day 4 = 1004.

Routes:
  GET  /                         renders index.html, sets CSRF cookie
  POST /api/analyse              workbook upload, returns base forecast JSON
  POST /api/scenario             takes run_id + free text, returns scenario JSON
  GET  /api/status               environment + sample availability
  GET  /api/runs                 cost log + cached run flags
  GET  /api/runs/<run_id>        re-open a cached run
  GET  /api/download/<filename>  serve a file from outputs/
  POST /api/shutdown             debug-only clean stop
  GET  /favicon.ico              static SVG icon

Same hardening as Days 1, 2, 3: 5 MB upload cap, secure_filename and
safe_join, single-flight semaphore on /api/analyse and /api/scenario,
CSRF double-submit cookie, generic 500 to client and full traceback in
logs/server.log.
"""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import secrets
import sys
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cost_log import CostLog
from csv_writer import write_csv_pair
from excel_writer import write_workbook
from flask import Flask, abort, jsonify, make_response, render_template, request, send_file
from pipeline import analyse, run_scenario, scenario_to_dict, to_dict
from run_cache import RunCache
from werkzeug.utils import safe_join, secure_filename

from shared.config import DEEPSEEK_API_KEY

HERE = Path(__file__).resolve().parent
SAMPLE_DIR = HERE / "sample_data"
OUTPUTS = HERE / "outputs"
UPLOADS = HERE / "uploads"
LOGS = HERE / "logs"

SAMPLES: dict[str, tuple[str, str]] = {
    "services": (
        "sample_services.xlsx",
        "Acme Consulting Ltd. Steady receipts, monthly payroll, quarterly VAT, ends positive.",
    ),
    "seasonal": (
        "sample_seasonal.xlsx",
        "TechRetail Ltd. W1 to W8 lean, W9 to W13 receipts spike. Demos runway calc.",
    ),
    "distress": (
        "sample_distress.xlsx",
        "PreFund Holdings Ltd. Squeeze in W7 to W11. Showcase for the AI scenario engine.",
    ),
}

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
ALLOWED_EXTS = {".xlsx"}
CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"

app = Flask(
    __name__,
    template_folder=str(HERE / "templates"),
    static_folder=str(HERE / "static"),
)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES

_analyse_lock = threading.Lock()
_cost_log = CostLog(OUTPUTS / "runs.jsonl")
_run_cache = RunCache(OUTPUTS / "runs")


# ---- Logging ---------------------------------------------------------

LOGS.mkdir(parents=True, exist_ok=True)
_handler = logging.handlers.RotatingFileHandler(
    LOGS / "server.log", maxBytes=512_000, backupCount=3, encoding="utf-8",
)
_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[_handler, logging.StreamHandler()])
log = logging.getLogger("day04.server")


# ---- Helpers ---------------------------------------------------------

def _env_key_ok() -> bool:
    return bool(DEEPSEEK_API_KEY) and not DEEPSEEK_API_KEY.startswith("sk-placeholder")


def _ensure_csrf_cookie(resp):
    if not request.cookies.get(CSRF_COOKIE_NAME):
        resp.set_cookie(
            CSRF_COOKIE_NAME, secrets.token_urlsafe(24),
            samesite="Strict", httponly=False, secure=False, max_age=24 * 3600,
        )
    return resp


def _csrf_check() -> bool:
    cookie = request.cookies.get(CSRF_COOKIE_NAME, "")
    header = request.headers.get(CSRF_HEADER_NAME, "")
    return bool(cookie) and secrets.compare_digest(cookie, header)


def _samples_for_template():
    out = []
    for sid, (fname, label) in SAMPLES.items():
        if (SAMPLE_DIR / fname).exists():
            out.append({"id": sid, "filename": fname, "label": label})
    return out


def _cost_log_dict() -> dict:
    s = _cost_log.summary()
    return {
        "runs": s.runs,
        "cost_usd_total": s.cost_usd_total,
        "rows_total": s.rows_total,
        "last_run_at": s.last_run_at,
        "cost_usd_30d": s.cost_usd_30d,
        "runs_30d": s.runs_30d,
    }


# ---- Routes ----------------------------------------------------------

@app.route("/")
def index():
    resp = make_response(render_template(
        "index.html",
        env_key_ok=_env_key_ok(),
        samples=_samples_for_template(),
        max_upload_mb=MAX_UPLOAD_BYTES // (1024 * 1024),
    ))
    return _ensure_csrf_cookie(resp)


@app.route("/api/status")
def status():
    return jsonify(
        env_key_ok=_env_key_ok(),
        samples=_samples_for_template(),
        max_upload_mb=MAX_UPLOAD_BYTES // (1024 * 1024),
        cost_log=_cost_log_dict(),
    )


@app.route("/api/runs")
def runs_list():
    entries = _cost_log.entries(limit=200)
    out = []
    for e in entries:
        eid = e.get("id")
        cached = bool(eid) and (_run_cache.root / f"{eid}.json").is_file()
        out.append({**e, "cached": cached})
    return jsonify(entries=out, summary=_cost_log_dict())


@app.route("/api/runs/<run_id>")
def run_get(run_id: str):
    if not run_id or len(run_id) > 64 or not run_id.replace("-", "").isalnum():
        return jsonify(error="Invalid run id."), 400
    payload = _run_cache.get(run_id)
    if payload is None:
        return jsonify(error="Run not cached. Older runs are evicted."), 404
    return jsonify(payload)


@app.route("/api/runs/<run_id>", methods=["DELETE"])
def run_delete(run_id: str):
    if not _csrf_check():
        return jsonify(error="CSRF token missing or invalid. Refresh the page."), 403
    if not run_id or len(run_id) > 64 or not run_id.replace("-", "").isalnum():
        return jsonify(error="Invalid run id."), 400
    if _run_cache.remove(run_id):
        return jsonify(removed=run_id)
    return jsonify(error="Not cached."), 404


@app.route("/api/analyse", methods=["POST"])
def api_analyse():
    if not _csrf_check():
        return jsonify(error="CSRF token missing or invalid. Refresh the page."), 403
    if not _analyse_lock.acquire(blocking=False):
        return jsonify(error="Another analysis is already in flight. Wait for it to finish."), 429

    started = time.time()
    try:
        use_samples = request.form.get("use_samples") == "true"
        sample_id = (request.form.get("sample_id") or "").strip()
        skip_ai = request.form.get("skip_ai") == "true"
        api_key_override = (request.form.get("api_key") or "").strip() or None
        model_choice = (request.form.get("model") or "").strip() or None

        if use_samples:
            if sample_id not in SAMPLES:
                return jsonify(error=f"Unknown sample id: '{sample_id}'."), 400
            fname, _ = SAMPLES[sample_id]
            sample_path = SAMPLE_DIR / fname
            if not sample_path.exists():
                return jsonify(error=f"Sample file missing on disk: {fname}."), 500
            file_bytes = sample_path.read_bytes()
            display_name = fname
        else:
            upload = request.files.get("file")
            if upload is None or not upload.filename:
                return jsonify(error="No file uploaded. Pick an .xlsx workbook."), 400
            safe_name = secure_filename(upload.filename) or "upload.xlsx"
            ext = Path(safe_name).suffix.lower()
            if ext not in ALLOWED_EXTS:
                return jsonify(error=f"Unsupported file type: {ext} (only .xlsx is supported)."), 400
            file_bytes = upload.read()
            UPLOADS.mkdir(parents=True, exist_ok=True)
            (UPLOADS / f"{uuid.uuid4().hex[:8]}_{safe_name}").write_bytes(file_bytes)
            display_name = safe_name

        try:
            result = analyse(
                file_bytes=file_bytes, source_filename=display_name,
                skip_ai=skip_ai, model=model_choice, api_key=api_key_override,
            )
        except ValueError as e:
            log.warning("analyse validation error: %s", e)
            return jsonify(error=str(e)), 400

        # Always write the deterministic outputs.
        xlsx_path = write_workbook(result, OUTPUTS)
        weekly_csv, lines_csv = write_csv_pair(result, OUTPUTS)

        elapsed_ms = int((time.time() - started) * 1000)
        commentary = result.commentary
        ai_cost = (commentary.cost_usd if commentary else 0.0)
        ai_model = (commentary.model if commentary and commentary.model else "(deterministic)")
        ai_skipped = bool(commentary.skipped) if commentary else True
        log_entry = _cost_log.append(
            company=result.metadata.company,
            period_label=result.metadata.period_label,
            rows=len(result.lines),
            cost_usd=ai_cost,
            model=ai_model,
            skipped=ai_skipped,
            elapsed_ms=elapsed_ms,
            source_filename=display_name,
            total_variance=result.headline.cumulative_net,
            total_variance_pct=None,
            rag_red=result.headline.rag_counts.get("red", 0),
        )
        log.info(
            "analyse OK lines=%d ms=%d closing=%.2f runway=%s",
            len(result.lines), elapsed_ms,
            result.headline.closing_balance,
            result.headline.runway_weeks,
        )

        body = to_dict(result)
        body.update(
            xlsx_filename=xlsx_path.name,
            weekly_csv_filename=weekly_csv.name,
            lines_csv_filename=lines_csv.name,
            elapsed_ms=elapsed_ms,
            cost_usd=round(ai_cost, 6),
            cost_log=_cost_log_dict(),
            run_id=log_entry["id"],
        )
        try:
            _run_cache.save(log_entry["id"], body)
        except Exception:
            log.exception("failed to cache run %s", log_entry["id"])
        return jsonify(body)
    except Exception:
        log.exception("analyse unexpected error")
        return jsonify(
            error="Server error during analysis. See logs/server.log for details."
        ), 500
    finally:
        _analyse_lock.release()


@app.route("/api/scenario", methods=["POST"])
def api_scenario():
    if not _csrf_check():
        return jsonify(error="CSRF token missing or invalid. Refresh the page."), 403
    if not _analyse_lock.acquire(blocking=False):
        return jsonify(error="Another analysis is in flight. Wait for it to finish."), 429

    started = time.time()
    try:
        run_id = (request.form.get("run_id") or "").strip()
        user_prompt = (request.form.get("prompt") or "").strip()
        skip_ai = request.form.get("skip_ai") == "true"
        api_key_override = (request.form.get("api_key") or "").strip() or None
        model_choice = (request.form.get("model") or "").strip() or None

        if not run_id or not user_prompt:
            return jsonify(error="Need run_id and prompt."), 400
        if len(user_prompt) > 1000:
            return jsonify(error="Prompt too long (max 1000 chars)."), 400

        cached = _run_cache.get(run_id)
        if cached is None:
            return jsonify(error="Base run not cached. Re-run the analysis."), 404

        # Reconstruct the base AnalysisResult from the cached dict.
        try:
            base = _result_from_dict(cached)
        except Exception as e:
            log.exception("failed to reconstruct base run %s", run_id)
            return jsonify(error=f"Could not reconstruct run: {e}"), 500

        scenario = run_scenario(
            base=base, user_prompt=user_prompt,
            model=model_choice, api_key=api_key_override, skip_ai=skip_ai,
        )

        elapsed_ms = int((time.time() - started) * 1000)
        cost = scenario.commentary.cost_usd
        _cost_log.append(
            company=base.metadata.company,
            period_label=base.metadata.period_label,
            rows=len(scenario.scenario.lines),
            cost_usd=cost,
            model=scenario.commentary.model or "deepseek-chat",
            skipped=scenario.commentary.skipped,
            elapsed_ms=elapsed_ms,
            source_filename=base.source_filename,
            total_variance=scenario.scenario.headline.cumulative_net,
            total_variance_pct=None,
            rag_red=scenario.scenario.headline.rag_counts.get("red", 0),
        )
        log.info(
            "scenario OK ai=%s ms=%d cost_usd=%.6f shock=%s",
            not skip_ai, elapsed_ms, cost, scenario.shock.type,
        )

        # Write the scenario workbook (overrides the deterministic xlsx with a
        # scenario-augmented one). Keep the previous xlsx intact for download.
        xlsx_path = write_workbook(scenario.scenario, OUTPUTS, scenario=scenario)
        body = scenario_to_dict(scenario)
        body.update(
            xlsx_filename=xlsx_path.name,
            elapsed_ms=elapsed_ms,
            cost_log=_cost_log_dict(),
        )
        return jsonify(body)
    except Exception:
        log.exception("scenario unexpected error")
        return jsonify(
            error="Server error during scenario. See logs/server.log for details."
        ), 500
    finally:
        _analyse_lock.release()


@app.errorhandler(413)
def _too_large(_e):
    return jsonify(error=f"Upload exceeds {MAX_UPLOAD_BYTES // 1024 // 1024} MB limit."), 413


@app.route("/api/download/<path:filename>")
def download(filename: str):
    safe = secure_filename(filename) or ""
    if not safe:
        abort(400)
    full = safe_join(str(OUTPUTS), safe)
    if not full or not Path(full).is_file():
        return jsonify(error=f"Not found: {safe}"), 404
    return send_file(full, as_attachment=True, download_name=safe)


@app.route("/api/shutdown", methods=["POST"])
def shutdown():
    if not (app.debug or os.getenv("DAY04_ALLOW_SHUTDOWN") == "1"):
        return jsonify(error="Shutdown not enabled. Run with --debug or DAY04_ALLOW_SHUTDOWN=1."), 403
    if not _csrf_check():
        return jsonify(error="CSRF token missing."), 403
    threading.Thread(target=lambda: (time.sleep(0.2), os._exit(0)), daemon=True).start()
    return jsonify(stopped=True)


@app.route("/favicon.ico")
def favicon():
    p = HERE / "static" / "favicon.svg"
    if p.exists():
        return send_file(p)
    return ("", 204)


# ---- Reconstruction helper ------------------------------------------

def _result_from_dict(d: dict):
    """Turn the cached JSON dict back into an AnalysisResult.

    We need the lines, metadata and headline to drive the scenario engine.
    The weeks list is recomputed from the lines so a stale cache stays
    consistent.
    """
    import datetime as dt

    from cashflow_maths import (
        compute_weeks,
        headline_stats,
        resolve_buffer,
    )
    from cashflow_schema import CashflowLine, CashflowMetadata
    from pipeline import AnalysisResult

    md = d["metadata"]
    metadata = CashflowMetadata(
        company=md["company"],
        currency=md["currency"],
        opening_balance=float(md["opening_balance"]),
        start_date=dt.date.fromisoformat(md["start_date"]),
        period_label=md["period_label"],
        buffer_amount=md.get("buffer_amount"),
    )
    lines = [
        CashflowLine(
            name=line["name"], type=line["type"], category=line["category"],
            amounts=list(line["amounts"]), source=line.get("source", "forecast"),
        )
        for line in d["lines"]
    ]
    weeks = compute_weeks(lines, metadata)
    buffer = resolve_buffer(lines, metadata)
    headline = headline_stats(weeks, metadata, buffer=buffer)
    from pipeline import Commentary
    cdict = d.get("commentary") or None
    commentary = None
    if cdict:
        commentary = Commentary(
            headline=cdict.get("headline", ""),
            summary=cdict.get("summary", ""),
            interpretation=cdict.get("interpretation", ""),
            actions=list(cdict.get("actions", [])),
            cost_usd=float(cdict.get("cost_usd", 0.0)),
            input_tokens=int(cdict.get("input_tokens", 0)),
            output_tokens=int(cdict.get("output_tokens", 0)),
            cache_hit_tokens=int(cdict.get("cache_hit_tokens", 0)),
            model=cdict.get("model", ""),
            skipped=bool(cdict.get("skipped", False)),
            error=cdict.get("error"),
        )
    return AnalysisResult(
        metadata=metadata, lines=lines, weeks=weeks, headline=headline,
        type_totals=d.get("type_totals", {}),
        category_totals=d.get("category_totals", {}),
        warnings=list(d.get("warnings", [])),
        source_filename=d.get("source_filename", ""),
        elapsed_ms=int(d.get("elapsed_ms", 0)),
        commentary=commentary,
    )


# ---- CLI -------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.getenv("DAY04_PORT", "1004")))
    parser.add_argument(
        "--host", default="127.0.0.1",
        help="Loopback by default. Keep it that way unless you know why.",
    )
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    print()
    print("  Day 4. Cash Flow Forecasting Model")
    print(f"  Local URL:  http://{args.host}:{args.port}/")
    print("  Press Ctrl+C to stop.")
    print()
    app.run(host=args.host, port=args.port, debug=args.debug, use_reloader=args.debug)


if __name__ == "__main__":
    main()
