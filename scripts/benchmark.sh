#!/bin/bash

set -e

RESULTS_DIR="/Users/muhanzhang/Documents/coding/project2/dlsms/bench"
REST_URL="http://localhost:8080"
GRPC_HOST="localhost:9090"

mkdir -p "$RESULTS_DIR"

echo "=================================================="
echo "Performance Benchmarking - DL-SMS"
echo "=================================================="

echo -e "\nGetting authentication token..."
TOKEN=$(curl -s -X POST "$REST_URL/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"student_id": "S2021001", "password": "password123"}' | jq -r '.token')

if [ "$TOKEN" == "null" ] || [ -z "$TOKEN" ]; then
    echo "ERROR: Failed to get token"
    exit 1
fi

echo "Token obtained"

echo -e "\n1. Benchmarking REST API - Seat Discovery"
echo "Running 1000 requests with 10 concurrent connections..."
ab -n 1000 -c 10 -H "Authorization: Bearer $TOKEN" \
  "$REST_URL/seats?branch=Main%20Library&available_only=true" \
  > "$RESULTS_DIR/rest_seat_discovery.txt" 2>&1

echo "Results saved to $RESULTS_DIR/rest_seat_discovery.txt"
grep "Requests per second" "$RESULTS_DIR/rest_seat_discovery.txt" || echo "Check results file for details"

echo -e "\n2. Benchmarking REST API - Get Branches (with Redis cache)"
echo "Running 2000 requests with 20 concurrent connections..."
ab -n 2000 -c 20 -H "Authorization: Bearer $TOKEN" \
  "$REST_URL/branches" \
  > "$RESULTS_DIR/rest_branches_cached.txt" 2>&1

echo "Results saved to $RESULTS_DIR/rest_branches_cached.txt"
grep "Requests per second" "$RESULTS_DIR/rest_branches_cached.txt" || echo "Check results file for details"

echo -e "\n3. Benchmarking REST API - User Reservations"
echo "Running 500 requests with 5 concurrent connections..."
ab -n 500 -c 5 -H "Authorization: Bearer $TOKEN" \
  "$REST_URL/reservations/mine" \
  > "$RESULTS_DIR/rest_user_reservations.txt" 2>&1

echo "Results saved to $RESULTS_DIR/rest_user_reservations.txt"
grep "Requests per second" "$RESULTS_DIR/rest_user_reservations.txt" || echo "Check results file for details"

echo -e "\n4. Benchmarking REST API - Reservation Creation (write operation)"
echo "Running 100 requests with 1 concurrent connection..."

START_TIME=$(date -u -v+5H +"%Y-%m-%dT%H:%M:%S" 2>/dev/null || date -u -d "+5 hours" +"%Y-%m-%dT%H:%M:%S")
END_TIME=$(date -u -v+7H +"%Y-%m-%dT%H:%M:%S" 2>/dev/null || date -u -d "+7 hours" +"%Y-%m-%dT%H:%M:%S")

for i in {1..100}; do
    SEAT_ID=$((10 + ($i % 40)))
    START_OFFSET=$(($i * 10))
    curl -s -X POST "$REST_URL/reservations" \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      -d "{
        \"seat_id\": $SEAT_ID,
        \"start_time\": \"$(date -u -v+${START_OFFSET}H +"%Y-%m-%dT%H:%M:%S" 2>/dev/null || date -u -d "+${START_OFFSET} hours" +"%Y-%m-%dT%H:%M:%S")\",
        \"end_time\": \"$(date -u -v+$((START_OFFSET + 2))H +"%Y-%m-%dT%H:%M:%S" 2>/dev/null || date -u -d "+$((START_OFFSET + 2)) hours" +"%Y-%m-%dT%H:%M:%S")\"
      }" > /dev/null 2>&1
done

echo "Created 100 reservations for benchmarking"

echo -e "\n5. Testing Concurrent Reservation Conflicts"
echo "Attempting 10 simultaneous reservations for the same seat/time..."

START_TIME=$(date -u -v+100H +"%Y-%m-%dT%H:%M:%S" 2>/dev/null || date -u -d "+100 hours" +"%Y-%m-%dT%H:%M:%S")
END_TIME=$(date -u -v+102H +"%Y-%m-%dT%H:%M:%S" 2>/dev/null || date -u -d "+102 hours" +"%Y-%m-%dT%H:%M:%S")

for i in {1..10}; do
    (curl -s -X POST "$REST_URL/reservations" \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      -d "{
        \"seat_id\": 25,
        \"start_time\": \"$START_TIME\",
        \"end_time\": \"$END_TIME\"
      }" | jq -r '.id // .error' &)
done

wait

echo -e "\nExpected: Only 1 success, 9 conflicts"

echo -e "\n6. Performance Summary"
echo "=========================================="
echo "REST Seat Discovery:"
grep "Requests per second" "$RESULTS_DIR/rest_seat_discovery.txt" | head -1
grep "Time per request" "$RESULTS_DIR/rest_seat_discovery.txt" | head -1

echo -e "\nREST Branches (cached):"
grep "Requests per second" "$RESULTS_DIR/rest_branches_cached.txt" | head -1
grep "Time per request" "$RESULTS_DIR/rest_branches_cached.txt" | head -1

echo -e "\nREST User Reservations:"
grep "Requests per second" "$RESULTS_DIR/rest_user_reservations.txt" | head -1
grep "Time per request" "$RESULTS_DIR/rest_user_reservations.txt" | head -1

echo -e "\n=================================================="
echo "Benchmarking completed!"
echo "Results saved in: $RESULTS_DIR"
echo "=================================================="

echo -e "\nNote: For gRPC benchmarking, use ghz tool:"
echo "  ghz --insecure --proto ./grpc/protos/library.proto --call library.SeatService/GetSeats -d '{\"available_only\":true}' localhost:9090"
