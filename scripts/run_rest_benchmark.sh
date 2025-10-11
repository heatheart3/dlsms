#!/bin/bash

# REST Performance Benchmark Script
# Runs hey benchmarks with different concurrency levels

set -e

RESULTS_DIR="/Users/muhanzhang/Documents/coding/project2/dlsms/bench/results"
mkdir -p "$RESULTS_DIR"

echo "=== REST Architecture Performance Benchmarks ==="
echo "Getting authentication token..."

# Get token
TOKEN=$(curl -s -X POST http://localhost:8080/auth/login \
  -H "Content-Type: application/json" \
  -d '{"student_id":"S2021001","password":"password123"}' | \
  grep -o '"token":"[^"]*' | cut -d'"' -f4)

if [ -z "$TOKEN" ]; then
    echo "ERROR: Failed to get authentication token"
    exit 1
fi

echo "Token obtained: ${TOKEN:0:20}..."
echo ""

# Benchmark function
run_benchmark() {
    local concurrency=$1
    local output_file=$2

    echo "Running benchmark with concurrency=$concurrency..."
    hey -z 30s -c $concurrency \
        -H "Authorization: Bearer $TOKEN" \
        http://localhost:8080/seats > "$output_file"

    echo "  Results saved to: $output_file"
}

# Run benchmarks with different concurrency levels
echo "[1/3] Benchmarking with 50 concurrent connections..."
run_benchmark 50 "$RESULTS_DIR/rest_seats_c50.txt"

echo ""
echo "[2/3] Benchmarking with 100 concurrent connections..."
run_benchmark 100 "$RESULTS_DIR/rest_seats_c100.txt"

echo ""
echo "[3/3] Benchmarking with 200 concurrent connections..."
run_benchmark 200 "$RESULTS_DIR/rest_seats_c200.txt"

echo ""
echo "=== REST Benchmarks Complete ==="
echo "Results saved in: $RESULTS_DIR"
