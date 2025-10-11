#!/bin/bash

# gRPC Scale-out Benchmark Script
# Tests performance with 1, 3, and 5 instances

set -e

RESULTS_DIR="/Users/muhanzhang/Documents/coding/project2/dlsms/bench/results"
mkdir -p "$RESULTS_DIR"

PROTO_FILE="/Users/muhanzhang/Documents/coding/project2/dlsms/grpc/protos/library.proto"

echo "=== gRPC Scale-out Performance Benchmarks ==="
echo ""

# Test with 1 instance (baseline - already done)
echo "[1/3] Testing with 1 instance (baseline)..."
echo "  Using existing results from grpc_seats_c100.txt"

# Test with 3 instances
echo ""
echo "[2/3] Testing with 3 instances..."
docker compose --profile grpc up -d --scale grpc-app=3
sleep 10

echo "  Running benchmark..."
ghz --insecure \
    --proto="$PROTO_FILE" \
    --call=library.SeatService.GetSeats \
    -d '{"available_only": true}' \
    -c 100 \
    -z 30s \
    localhost:9090 > "$RESULTS_DIR/grpc_scaleout_3instances.txt"

echo "  Results saved"

# Test with 5 instances
echo ""
echo "[3/3] Testing with 5 instances..."
docker compose --profile grpc up -d --scale grpc-app=5
sleep 10

echo "  Running benchmark..."
ghz --insecure \
    --proto="$PROTO_FILE" \
    --call=library.SeatService.GetSeats \
    -d '{"available_only": true}' \
    -c 100 \
    -z 30s \
    localhost:9090 > "$RESULTS_DIR/grpc_scaleout_5instances.txt"

echo "  Results saved"

# Reset to 1 instance
echo ""
echo "Resetting to 1 instance..."
docker compose --profile grpc up -d --scale grpc-app=1

echo ""
echo "=== gRPC Scale-out Benchmarks Complete ==="
echo "Results saved in: $RESULTS_DIR"
