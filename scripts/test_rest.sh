#!/bin/bash

set -e

BASE_URL="http://localhost:8080"
TOKEN=""
USER_ID=""
RESERVATION_ID=""

echo "=================================================="
echo "Testing REST API - DL-SMS"
echo "=================================================="

echo -e "\n1. Testing Health Check"
curl -s -X GET "$BASE_URL/healthz" | jq '.'

echo -e "\n2. Testing Login"
LOGIN_RESPONSE=$(curl -s -X POST "$BASE_URL/auth/login" \
  -H "Content-Type: application/json" \
  -d '{
    "student_id": "S2021001",
    "password": "password123"
  }')

echo "$LOGIN_RESPONSE" | jq '.'

TOKEN=$(echo "$LOGIN_RESPONSE" | jq -r '.token')
USER_ID=$(echo "$LOGIN_RESPONSE" | jq -r '.user_id')

if [ "$TOKEN" == "null" ] || [ -z "$TOKEN" ]; then
    echo "ERROR: Failed to get token"
    exit 1
fi

echo "Token obtained: ${TOKEN:0:50}..."
echo "User ID: $USER_ID"

echo -e "\n3. Testing Seat Discovery - Get All Available Seats"
curl -s -X GET "$BASE_URL/seats?available_only=true" \
  -H "Authorization: Bearer $TOKEN" | jq '.seats[:3]'

echo -e "\n4. Testing Seat Discovery - Filter by Branch"
curl -s -X GET "$BASE_URL/seats?branch=Main%20Library&available_only=true" \
  -H "Authorization: Bearer $TOKEN" | jq '{count: .count, seats: .seats[:3]}'

echo -e "\n5. Testing Seat Discovery - Filter by Power"
curl -s -X GET "$BASE_URL/seats?has_power=true&available_only=true" \
  -H "Authorization: Bearer $TOKEN" | jq '{count: .count, seats: .seats[:3]}'

echo -e "\n6. Testing Get Branches"
curl -s -X GET "$BASE_URL/branches" \
  -H "Authorization: Bearer $TOKEN" | jq '.'

echo -e "\n7. Testing Reservation Creation"
START_TIME=$(date -u -v+1H +"%Y-%m-%dT%H:%M:%S" 2>/dev/null || date -u -d "+1 hour" +"%Y-%m-%dT%H:%M:%S")
END_TIME=$(date -u -v+3H +"%Y-%m-%dT%H:%M:%S" 2>/dev/null || date -u -d "+3 hours" +"%Y-%m-%dT%H:%M:%S")

echo "Start time: $START_TIME"
echo "End time: $END_TIME"

RESERVATION_RESPONSE=$(curl -s -X POST "$BASE_URL/reservations" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"seat_id\": 10,
    \"start_time\": \"$START_TIME\",
    \"end_time\": \"$END_TIME\"
  }")

echo "$RESERVATION_RESPONSE" | jq '.'

RESERVATION_ID=$(echo "$RESERVATION_RESPONSE" | jq -r '.id')

if [ "$RESERVATION_ID" != "null" ] && [ -n "$RESERVATION_ID" ]; then
    echo "Reservation created: ID=$RESERVATION_ID"
else
    echo "Note: Seat might already be reserved, trying another seat..."

    RESERVATION_RESPONSE=$(curl -s -X POST "$BASE_URL/reservations" \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      -d "{
        \"seat_id\": 15,
        \"start_time\": \"$START_TIME\",
        \"end_time\": \"$END_TIME\"
      }")

    echo "$RESERVATION_RESPONSE" | jq '.'
    RESERVATION_ID=$(echo "$RESERVATION_RESPONSE" | jq -r '.id')
fi

echo -e "\n8. Testing Conflict Detection - Attempt Double Booking"
CONFLICT_RESPONSE=$(curl -s -X POST "$BASE_URL/reservations" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"seat_id\": 10,
    \"start_time\": \"$START_TIME\",
    \"end_time\": \"$END_TIME\"
  }")

echo "$CONFLICT_RESPONSE" | jq '.'
echo "Expected: 409 Conflict error"

echo -e "\n9. Testing Get My Reservations"
curl -s -X GET "$BASE_URL/reservations/mine?upcoming_only=true" \
  -H "Authorization: Bearer $TOKEN" | jq '{count: .count, reservations: .reservations[:3]}'

if [ "$RESERVATION_ID" != "null" ] && [ -n "$RESERVATION_ID" ]; then
    echo -e "\n10. Testing Get Specific Reservation"
    curl -s -X GET "$BASE_URL/reservations/$RESERVATION_ID" \
      -H "Authorization: Bearer $TOKEN" | jq '.'

    echo -e "\n11. Testing Reservation Cancellation"
    curl -s -X DELETE "$BASE_URL/reservations/$RESERVATION_ID" \
      -H "Authorization: Bearer $TOKEN" | jq '.'
fi

echo -e "\n12. Testing Check-in Flow"
START_NOW=$(date -u +"%Y-%m-%dT%H:%M:%S")
END_LATER=$(date -u -v+2H +"%Y-%m-%dT%H:%M:%S" 2>/dev/null || date -u -d "+2 hours" +"%Y-%m-%dT%H:%M:%S")

CHECKIN_RESERVATION=$(curl -s -X POST "$BASE_URL/reservations" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"seat_id\": 20,
    \"start_time\": \"$START_NOW\",
    \"end_time\": \"$END_LATER\"
  }")

echo "$CHECKIN_RESERVATION" | jq '.'

CHECKIN_RES_ID=$(echo "$CHECKIN_RESERVATION" | jq -r '.id')

if [ "$CHECKIN_RES_ID" != "null" ] && [ -n "$CHECKIN_RES_ID" ]; then
    echo "Created reservation for check-in: ID=$CHECKIN_RES_ID"

    echo -e "\n13. Testing Check-in"
    curl -s -X POST "$BASE_URL/reservations/$CHECKIN_RES_ID/checkin" \
      -H "Authorization: Bearer $TOKEN" | jq '.'
fi

echo -e "\n14. Testing Waitlist"
curl -s -X POST "$BASE_URL/waitlist" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"seat_id\": 1,
    \"desired_time\": \"$START_TIME\"
  }" | jq '.'

echo -e "\n15. Testing Get My Waitlist"
curl -s -X GET "$BASE_URL/waitlist/mine" \
  -H "Authorization: Bearer $TOKEN" | jq '.'

echo -e "\n=================================================="
echo "All REST API tests completed!"
echo "=================================================="
