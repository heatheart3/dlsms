#!/usr/bin/env bash

# Reproduce DL-SMS functional tests and benchmarks.
# Usage:
#   ./scripts/reproduce_all.sh              # run tests/benchmarks, keep baseline untouched
#   ./scripts/reproduce_all.sh --update-baseline  # also refresh canonical results + graphs

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

RESULT_DIR="$ROOT_DIR/bench/results"
RUNS_DIR="$RESULT_DIR/runs"
FIGURES_DIR="$ROOT_DIR/figures"
PROTO_PATH="$ROOT_DIR/grpc/protos/library.proto"
GHZ_TARGET="localhost:9090"

REST_HEALTH_URL="http://localhost:8080/healthz"

REQUIRED_CMDS=(docker ghz python3 jq curl)

function usage() {
    cat <<'EOF'
Usage: reproduce_all.sh [--update-baseline]

Actions:
  1. Runs REST end-to-end tests (Docker compose profile: rest)
  2. Runs gRPC client smoke tests + ghz benchmarks @ concurrency 50/100/200
  3. Stores raw ghz outputs under bench/results/runs/<timestamp>/
  4. Generates a per-run summary CSV

Options:
  --update-baseline, -u   Overwrite bench/results/grpc_seats_c*.txt,
                          refresh bench/performance_comparison.csv,
                          and regenerate figures/.
  -h, --help              Show this help.
EOF
}

UPDATE_BASELINE=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --update-baseline|-u)
            UPDATE_BASELINE=true
            shift
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage
            exit 1
            ;;
    esac
done

for cmd in "${REQUIRED_CMDS[@]}"; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "✗ Missing required command: $cmd" >&2
        exit 1
    fi
done

if [ ! -f "$ROOT_DIR/.env" ]; then
    echo "→ .env not found. Copying from .env.example..."
    cp "$ROOT_DIR/.env.example" "$ROOT_DIR/.env"
fi

set -a
source "$ROOT_DIR/.env"
set +a

echo "→ Ensuring clean Docker state (removing previous containers/volumes)..."
docker compose down --volumes >/dev/null 2>&1 || true

RUN_TS="$(date -u '+%Y%m%dT%H%M%SZ')"
RUN_DIR="$RUNS_DIR/$RUN_TS"
RUN_SUMMARY="$RUN_DIR/grpc_performance.csv"

mkdir -p "$RESULT_DIR" "$FIGURES_DIR" "$RUN_DIR"

function cleanup() {
    echo "→ Shutting down Docker profiles..."
    docker compose --profile rest down >/dev/null 2>&1 || true
    docker compose --profile grpc down >/dev/null 2>&1 || true
    docker compose down --volumes >/dev/null 2>&1 || true
}
trap cleanup EXIT

function wait_for_postgres() {
    docker compose exec -T postgres bash -c "until pg_isready -U \"$POSTGRES_USER\" >/dev/null 2>&1; do sleep 1; done"
}

function reset_database() {
    echo "→ Resetting PostgreSQL schema and seed data ..."
    docker compose up -d postgres >/dev/null 2>&1
    wait_for_postgres
    docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<'SQL'
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
GRANT ALL ON SCHEMA public TO dlsms;
GRANT ALL ON SCHEMA public TO public;
SQL
    docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f /docker-entrypoint-initdb.d/01-init.sql >/dev/null
    docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f /docker-entrypoint-initdb.d/02-seed.sql >/dev/null
    docker compose stop postgres >/dev/null 2>&1 || true
}

function wait_for_http() {
    local url="$1"
    local name="$2"
    local retries=45

    echo "→ Waiting for $name at $url ..."
    until curl -fsS "$url" >/dev/null 2>&1; do
        ((retries--)) || { echo "✗ Timeout while waiting for $name"; exit 1; }
        sleep 2
    done
    echo "✓ $name is ready"
}

function wait_for_grpc() {
    echo "→ Waiting for gRPC service on $GHZ_TARGET ..."
    python3 - <<'PY'
import sys
import time
import grpc

sys.path.append("grpc")
import library_pb2  # noqa: E402
import library_pb2_grpc  # noqa: E402

deadline = time.time() + 120
attempt = 0

while time.time() < deadline:
    attempt += 1
    try:
        channel = grpc.insecure_channel("localhost:9090")
        grpc.channel_ready_future(channel).result(timeout=3)
        stub = library_pb2_grpc.SeatServiceStub(channel)
        stub.GetSeats(library_pb2.GetSeatsRequest(available_only=True))
        print("✓ gRPC service is ready (attempt {})".format(attempt))
        sys.exit(0)
    except Exception:
        time.sleep(2)

print("✗ Timed out waiting for gRPC service", file=sys.stderr)
sys.exit(1)
PY
}

function warm_grpc_cache() {
    echo "→ Warming gRPC cache ..."
    python3 - <<'PY'
import sys
sys.path.append("grpc")
import grpc
import library_pb2
import library_pb2_grpc

channel = grpc.insecure_channel("localhost:9090")
stub = library_pb2_grpc.SeatServiceStub(channel)
for _ in range(3):
    stub.GetSeats(library_pb2.GetSeatsRequest(available_only=True))
PY
}

function run_rest_suite() {
    echo "=== REST architecture ==="
    docker compose --profile rest up -d --build
    wait_for_http "$REST_HEALTH_URL" "REST gateway"
    ./test_rest_e2e.sh
    docker compose --profile rest down
}

function run_grpc_suite() {
    echo "=== gRPC architecture ==="
    docker compose --profile grpc up -d --build
    wait_for_grpc
    warm_grpc_cache
    python3 grpc/client_test.py

    for concurrency in 50 100 200; do
        echo "→ Running ghz benchmark at concurrency=$concurrency ..."
        ghz --insecure \
            --proto="$PROTO_PATH" \
            --call=library.SeatService.GetSeats \
            -d '{"available_only": true}' \
            -c "$concurrency" \
            -z 30s \
            "$GHZ_TARGET" > "$RUN_DIR/grpc_seats_c${concurrency}.txt"
    done

    docker compose --profile grpc down
}

function update_performance_csv() {
    local src_dir="$1"
    local dest_csv="$2"
    local mode="$3"  # "baseline" or "run"

    python3 - "$src_dir" "$dest_csv" "$mode" <<'PY'
import csv
import re
import sys
from pathlib import Path

src_dir = Path(sys.argv[1])
dest_csv = Path(sys.argv[2])
mode = sys.argv[3]

patterns = {
    "count": re.compile(r"Count:\s+(\d+)"),
    "rps": re.compile(r"Requests/sec:\s+([0-9.]+)"),
    "avg": re.compile(r"Average:\s+([0-9.]+)\s+ms"),
    "p50": re.compile(r"50 % in ([0-9.]+) ms"),
    "p95": re.compile(r"95 % in ([0-9.]+) ms"),
    "p99": re.compile(r"99 % in ([0-9.]+) ms"),
}

error_pattern = re.compile(r"\[(?:Unavailable|Internal|Unknown|Canceled)\]\s+(\d+)")
ok_pattern = re.compile(r"\[OK\]\s+(\d+)")

def parse_metrics(path: Path):
    text = path.read_text()
    rps = float(patterns["rps"].search(text).group(1))
    avg = float(patterns["avg"].search(text).group(1))
    p50 = float(patterns["p50"].search(text).group(1))
    p95 = float(patterns["p95"].search(text).group(1))
    p99 = float(patterns["p99"].search(text).group(1))
    total = int(patterns["count"].search(text).group(1))
    ok = sum(int(m.group(1)) for m in ok_pattern.finditer(text))
    errors = sum(int(m.group(1)) for m in error_pattern.finditer(text))
    success_rate = 100.0 * ok / (ok + errors) if (ok + errors) else 0.0
    return {
        "Total_Requests": total,
        "Requests_per_sec": rps,
        "Avg_Latency_ms": avg,
        "P50_ms": p50,
        "P95_ms": p95,
        "P99_ms": p99,
        "Success_Rate": success_rate,
        "OK_Count": ok,
        "Error_Count": errors,
    }

metrics = {}
for concurrency in (50, 100, 200):
    path = src_dir / f"grpc_seats_c{concurrency}.txt"
    if path.exists():
        metrics[concurrency] = parse_metrics(path)

if not metrics:
    print("No gRPC results found in", src_dir, file=sys.stderr)
    sys.exit(1)

if mode == "baseline":
    csv_path = dest_csv
    rows = []
    with csv_path.open(newline="") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames
        for row in reader:
            if row["architecture"] == "gRPC":
                concurrency = int(row["concurrency"])
                if concurrency in metrics:
                    m = metrics[concurrency]
                    row["rps"] = f"{m['Requests_per_sec']:.2f}"
                    row["p50_ms"] = f"{m['P50_ms']:.2f}"
                    row["p95_ms"] = f"{m['P95_ms']:.2f}"
                    row["p99_ms"] = f"{m['P99_ms']:.2f}"
                    row["success_rate"] = f"{m['Success_Rate']:.2f}"
                    if concurrency == 50:
                        row["notes"] = "Cache-primed; DB_MAX_CONCURRENT=60"
                    elif concurrency == 100:
                        row["notes"] = "3 instances × 100 pool slots with semaphore"
                    elif concurrency == 200:
                        row["notes"] = "Residual nginx GOAWAY (~6.9% Unavailable)"
            rows.append(row)
    with csv_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)
else:
    header = [
        "architecture",
        "concurrency",
        "rps",
        "p50_ms",
        "p95_ms",
        "p99_ms",
        "success_rate",
        "ok_count",
        "error_count",
    ]
    rows = []
    for concurrency in sorted(metrics):
        m = metrics[concurrency]
        rows.append({
            "architecture": "gRPC",
            "concurrency": concurrency,
            "rps": f"{m['Requests_per_sec']:.2f}",
            "p50_ms": f"{m['P50_ms']:.2f}",
            "p95_ms": f"{m['P95_ms']:.2f}",
            "p99_ms": f"{m['P99_ms']:.2f}",
            "success_rate": f"{m['Success_Rate']:.2f}",
            "ok_count": str(m['OK_Count']),
            "error_count": str(m['Error_Count']),
        })
    with dest_csv.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)
PY
}

function generate_graphs() {
    echo "→ Generating figures ..."
    python3 scripts/generate_graphs.py
}

echo ">>> Starting DL-SMS one-click reproduction"
reset_database
run_rest_suite
run_grpc_suite
update_performance_csv "$RUN_DIR" "$RUN_SUMMARY" "run"

if $UPDATE_BASELINE; then
    echo "→ Updating gRPC baseline artifacts..."
    for concurrency in 50 100 200; do
        cp "$RUN_DIR/grpc_seats_c${concurrency}.txt" "$RESULT_DIR/grpc_seats_c${concurrency}.txt"
    done
    update_performance_csv "$RUN_DIR" "$ROOT_DIR/bench/performance_comparison.csv" "baseline"
    generate_graphs
fi

echo "✓ Reproduction complete."
echo "  REST test logs: $ROOT_DIR/bench/logs"
echo "  This run:       $RUN_DIR"
echo "  Run summary:    $RUN_SUMMARY"
if $UPDATE_BASELINE; then
    echo "  Baseline:       bench/results/grpc_seats_c{50,100,200}.txt"
    echo "  Graphs:         $FIGURES_DIR"
else
    echo "  Baseline unchanged (use --update-baseline to refresh canonical results)."
fi
