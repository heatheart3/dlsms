# Distributed Library Seat Management System (DL-SMS)

**Group 10 | Danhua Zhao • Muhan Zhang | Fall 2025**

A production-ready distributed system for managing library seat reservations with both REST and gRPC architectures. This system demonstrates microservices design, conflict detection, real-time availability tracking, and automated seat release mechanisms.

---

## Quick Start

```bash
# REST Architecture
cp .env.example .env  # Already done if .env exists
docker compose --profile rest up -d
# Access: http://localhost:8080

# gRPC Architecture
docker compose --profile rest down
docker compose --profile grpc up -d
# Access: localhost:9090

# Run Tests
./test_rest_e2e.sh
python3 grpc/client_test.py

# Run Benchmarks
# Option A (hey-based):
./scripts/run_rest_benchmark.sh   # requires a local 'hey' that forwards headers correctly
./scripts/run_grpc_benchmark.sh   # requires 'ghz'

# Option B (ab-based, recommended if your 'hey' drops Authorization headers):
./scripts/benchmark.sh            # uses ApacheBench (ab) and curl; no 'hey' needed

python3 scripts/generate_graphs.py
```

## Team

- **Danhua Zhao**
- **Muhan Zhang**

**Group 10**, Fall 2025

## Final Deliverables

- ✅ **Source code:** 53 files, 7,000+ lines
- ✅ **Two architectures:** REST (8 nodes) + gRPC (6 nodes with load balancing)
- ✅ **All 5 features implemented and tested**
- ✅ **Performance benchmarks and graphs:**
  - REST: 2,479 RPS, 23.6ms P95 latency
  - gRPC: 1,155 RPS, 1,410ms P95 latency (connection pool bottleneck)
- ✅ **Final report:** [report/final_report.md](/Users/muhanzhang/Documents/coding/project2/dlsms/report/final_report.md)
- ✅ **Presentation:** [slides/SLIDES.md](/Users/muhanzhang/Documents/coding/project2/dlsms/slides/SLIDES.md)

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [API Documentation](#api-documentation)
- [Testing](#testing)
- [Performance Benchmarking](#performance-benchmarking)
- [Project Structure](#project-structure)

## Features

### Core Functionality

1. **User Authentication & JWT Authorization**
   - Secure login/registration with bcrypt password hashing
   - JWT token generation and validation
   - Token-based API access control

2. **Smart Seat Discovery**
   - Real-time seat availability tracking
   - Advanced filtering (branch, area, power, monitor)
   - Redis caching for performance optimization
   - Time-slot based availability queries

3. **Intelligent Reservation Management**
   - Conflict detection using PostgreSQL exclusion constraints
   - Only one reservation per seat per time slot
   - Atomic reservation creation with row-level locking
   - Reservation status lifecycle (CONFIRMED → CHECKED_IN → COMPLETED)

4. **Automated Check-in & Release**
   - Grace period for late check-ins (default: 15 minutes)
   - Background worker automatically marks NO_SHOW reservations
   - Automatic completion of past reservations
   - Real-time cache invalidation

5. **Waitlist & Notifications**
   - User waitlist for popular seats/branches
   - SSE (Server-Sent Events) notification stream
   - Priority-based notification system
   - Waitlist management API

## Architecture

### REST Architecture (Microservices)

```
┌─────────┐
│ Client  │
└────┬────┘
     │
┌────▼──────────┐
│   Gateway     │ :8080 - JWT validation, request routing
└────┬──────────┘
     │
     ├─────► Auth Service      :8081 - Authentication & JWT
     ├─────► Seat Service      :8082 - Seat discovery & availability
     ├─────► Reservation       :8083 - Booking & check-in
     ├─────► Notify Service    :8084 - Waitlist & notifications
     └─────► Check-in Worker         - Background NO_SHOW processing
                │
        ┌───────┴────────┐
        │                │
    PostgreSQL      Redis
    :5433          :6379
```

### gRPC Architecture (Load Balanced)

```
┌─────────┐
│ Client  │
└────┬────┘
     │
┌────▼────────────────────────────┐
│  Nginx Load Balancer :9090      │
│  (Round-robin distribution)     │
└────┬───────┬────────┬────────────┘
     │       │        │
     │       │        │
┌────▼──┐  ┌─▼────┐  ┌▼─────┐
│ App 1 │  │ App 2│  │ App 3│
│ :9090 │  │ :9090│  │ :9090│
└───┬───┘  └──┬───┘  └──┬───┘
    └─────────┼─────────┘
              │
      ┌───────┴────────┐
      │                │
  PostgreSQL      Redis
  :5433          :6379

Each App contains:
- AuthService
- SeatService
- ReservationService
- NotifyService
- Background Worker Thread
```

## Prerequisites

- Docker and Docker Compose
- Python 3.9+ (for local testing)
- curl and jq (for REST API testing)
- Optional: Apache Bench (ab) for performance testing

## Quick Start

### 1. Clone and Setup

```bash
cd /Users/muhanzhang/Documents/coding/project2/dlsms
cp .env.example .env
```

### 2. Start REST Architecture

```bash
# Start all REST microservices
docker-compose --profile rest up -d

# Wait for services to be healthy (about 30 seconds)
docker-compose ps

# Services will be available at:
# - Gateway: http://localhost:8080
# - Auth: http://localhost:8081
# - Seat: http://localhost:8082
# - Reservation: http://localhost:8083
# - Notify: http://localhost:8084
# - PostgreSQL: localhost:5433
# - Redis: localhost:6379
```

### 3. Start gRPC Architecture

```bash
# Stop REST services first
docker-compose --profile rest down

# Start gRPC service
docker-compose --profile grpc up -d

# Wait for services to be healthy
docker-compose ps

# gRPC server will be available at:
# - localhost:9090
```

### 4. Verify Installation

```bash
# For REST
curl http://localhost:8080/healthz

# For gRPC
docker-compose logs grpc-app | grep "started on port 9090"
```

## API Documentation

### REST API Endpoints

#### Authentication

```bash
# Login
POST /auth/login
Content-Type: application/json
{
  "student_id": "S2021001",
  "password": "password123"
}

Response: {
  "token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "user_id": 1,
  "student_id": "S2021001",
  "name": "Alice Johnson"
}

# Register
POST /auth/register
Content-Type: application/json
{
  "student_id": "S2021011",
  "password": "newpassword",
  "name": "New User"
}
```

#### Seat Discovery

```bash
# Get all available seats
GET /seats?available_only=true
Authorization: Bearer {token}

# Filter by branch
GET /seats?branch=Main Library&available_only=true
Authorization: Bearer {token}

# Filter by amenities
GET /seats?has_power=true&has_monitor=true
Authorization: Bearer {token}

# Check availability for specific time
GET /seats?start_time=2025-10-11T14:00:00&end_time=2025-10-11T16:00:00
Authorization: Bearer {token}

# Get specific seat
GET /seats/{seat_id}
Authorization: Bearer {token}

# Get all branches
GET /branches
Authorization: Bearer {token}
```

#### Reservations

```bash
# Create reservation
POST /reservations
Authorization: Bearer {token}
Content-Type: application/json
{
  "seat_id": 1,
  "start_time": "2025-10-11T14:00:00",
  "end_time": "2025-10-11T16:00:00"
}

# Get my reservations
GET /reservations/mine?upcoming_only=true
Authorization: Bearer {token}

# Get specific reservation
GET /reservations/{reservation_id}
Authorization: Bearer {token}

# Check in
POST /reservations/{reservation_id}/checkin
Authorization: Bearer {token}

# Cancel reservation
DELETE /reservations/{reservation_id}
Authorization: Bearer {token}
```

#### Waitlist

```bash
# Add to waitlist
POST /waitlist
Authorization: Bearer {token}
Content-Type: application/json
{
  "seat_id": 1,
  "desired_time": "2025-10-11T14:00:00"
}

# Get my waitlist entries
GET /waitlist/mine
Authorization: Bearer {token}

# Remove from waitlist
DELETE /waitlist/{waitlist_id}
Authorization: Bearer {token}

# Stream notifications (SSE)
GET /notifications/stream
Authorization: Bearer {token}
```

### gRPC API

See `grpc/protos/library.proto` for full service definitions.

#### Key Services

- **AuthService**: Login, Register, Verify
- **SeatService**: GetSeats, GetSeat, CheckAvailability, GetBranches
- **ReservationService**: CreateReservation, GetReservation, CheckIn, CancelReservation, GetUserReservations
- **NotifyService**: AddToWaitlist, GetUserWaitlist, RemoveFromWaitlist, NotifyUsers

## Testing

### Test REST API

```bash
# Make scripts executable
chmod +x scripts/test_rest.sh

# Run comprehensive REST tests
./scripts/test_rest.sh
```

Tests include:
- ✓ Login authentication
- ✓ Seat discovery with filters
- ✓ Reservation creation
- ✓ Conflict detection (409 error)
- ✓ Check-in flow
- ✓ Reservation cancellation
- ✓ Waitlist operations

### Test gRPC API

```bash
# Install Python dependencies
pip install grpcio grpcio-tools

# Make scripts executable
chmod +x scripts/test_grpc.sh

# Run gRPC tests
./scripts/test_grpc.sh
```

### Manual Testing Examples

#### REST

```bash
# 1. Login
TOKEN=$(curl -s -X POST http://localhost:8080/auth/login \
  -H "Content-Type: application/json" \
  -d '{"student_id":"S2021001","password":"password123"}' | jq -r '.token')

# 2. Get available seats
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8080/seats?branch=Main%20Library&has_power=true"

# 3. Create reservation
curl -X POST http://localhost:8080/reservations \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "seat_id": 10,
    "start_time": "2025-10-11T14:00:00",
    "end_time": "2025-10-11T16:00:00"
  }'
```

#### gRPC

```bash
# Compile protos and run client
cd grpc
python -m grpc_tools.protoc -I./protos --python_out=. --grpc_python_out=. ./protos/library.proto
python client_test.py
```

## Performance Benchmarking

### Reproduction Notes

- Seed users: `S2021001`–`S2021010` with password `password123` (from database seed). Always use uppercase student IDs.
- Get a JWT via the gateway and pass it in the Authorization header:
  ```bash
  TOKEN=$(curl -s -X POST http://localhost:8080/auth/login \
    -H 'Content-Type: application/json' \
    -d '{"student_id":"S2021001","password":"password123"}' | jq -r .token)
  # Quick check
  curl -s -H "Authorization: Bearer $TOKEN" 'http://localhost:8080/seats?available_only=true' | jq '.count'
  ```
- Tooling caveat: some `hey` builds may not forward custom headers reliably on certain platforms. If you see 401 responses during REST benchmarks, prefer the `ab`-based script:
  ```bash
  ./scripts/benchmark.sh   # uses ApacheBench (ab) + curl
  ```

### One-Click Reproduction

```bash
# Runs REST e2e tests, gRPC client tests, ghz benchmarks (c=50/100/200),
# saves raw outputs under bench/results/runs/<timestamp>.
./scripts/reproduce_all.sh

# Same as above, but also refreshes bench/performance_comparison.csv
# and regenerates figures/ with the new baseline.
./scripts/reproduce_all.sh --update-baseline
```

Dependencies: Docker, `curl`, `jq`, `ghz`, and `python3` available on the host. `hey` is not required for the one‑click flow.

> ⚠️ The script starts by running `docker compose down --volumes` to ensure a clean seed.
>    Any existing containers/volumes for this project will be removed.

If you previously ran an older version of the stack (or used a different `.env`), run the following once from the
repository root to wipe stale containers/volumes before starting:

```bash
docker compose down --volumes --remove-orphans
cp .env.example .env  # ensure canonical credentials are in place
```

#### Host prerequisites (macOS/Homebrew)

The script calls local Python to run `grpc/client_test.py` and therefore needs a Python environment with `grpcio`, `grpcio-tools`, and `psycopg2-binary`. One way to prepare it:

```bash
# Install tooling (only once)
brew install python@3.11 libpq ghz jq
# Optional: ab for REST benchmarks without hey
brew install httpd   # provides 'ab'
echo 'export PATH="/opt/homebrew/opt/libpq/bin:$PATH"' >> ~/.zprofile
source ~/.zprofile

# Create / activate venv (regenerate if you already had one)
/opt/homebrew/opt/python@3.11/bin/python3.11 -m venv .venv
source .venv/bin/activate
export PATH="/opt/homebrew/opt/libpq/bin:$PATH"  # ensure pg_config is visible

# Install Python deps needed by the reproduction script
python3.11 -m pip install --upgrade pip wheel setuptools
python3.11 -m pip install -r grpc/app/requirements.txt

# Run the workflow
./scripts/reproduce_all.sh          # or add --update-baseline if desired
```

(If you prefer not to configure the host environment, you can follow the Docker commands below and run each step inside the containers.)

### Manual Benchmark Workflow (optional)

```bash
# Install Apache Bench (if not installed)
# macOS: brew install httpd
# Linux: apt-get install apache2-utils

# Make scripts executable
chmod +x scripts/benchmark.sh
chmod +x scripts/generate_plots.py

# Run benchmarks
./scripts/benchmark.sh

# Generate performance plots
python3 scripts/generate_plots.py
```

### Benchmark Results

Typical performance metrics (varies by hardware):

| Operation | REST (req/s) | Latency (ms) |
|-----------|--------------|--------------|
| Seat Discovery | 250-300 | 15-20 |
| Branches (cached) | 400-500 | 5-8 |
| User Reservations | 150-200 | 25-30 |
| Create Reservation | 80-100 | 40-50 |

### Conflict Detection Test

The system correctly handles concurrent reservations:
- 10 simultaneous requests for the same seat/time
- Result: 1 success, 9 conflicts (409 status)
- Demonstrates proper transaction isolation

## Project Structure

```
dlsms/
├── docker-compose.yml          # Multi-profile orchestration
├── .env.example                # Environment configuration template
├── README.md                   # This file
│
├── rest/                       # REST Microservices
│   ├── gateway/               # API Gateway (port 8080)
│   │   ├── app.py            # Routing & JWT validation
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   ├── auth/                  # Authentication Service (port 8081)
│   │   ├── app.py            # Login, register, JWT generation
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   ├── seat/                  # Seat Service (port 8082)
│   │   ├── app.py            # Seat discovery & availability
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   ├── reservation/           # Reservation Service (port 8083)
│   │   ├── app.py            # Booking, check-in, cancellation
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   ├── notify/                # Notification Service (port 8084)
│   │   ├── app.py            # Waitlist & SSE notifications
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   └── checkin_worker/        # Background Worker
│       ├── worker.py          # NO_SHOW processing
│       ├── Dockerfile
│       └── requirements.txt
│
├── grpc/                       # gRPC Monolithic Service
│   ├── protos/
│   │   └── library.proto      # Service definitions
│   ├── app/
│   │   ├── server.py          # All services + background worker
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   └── client_test.py         # Test client
│
├── db/                         # Database
│   ├── init.sql               # Schema with exclusion constraints
│   └── seed.sql               # 50 seats, 10 users, sample data
│
├── scripts/                    # Testing & Benchmarking
│   ├── reproduce_all.sh       # One-click reproduction (tests + benchmarks + graphs)
│   ├── test_rest.sh           # REST API comprehensive tests
│   ├── test_grpc.sh           # gRPC API tests
│   ├── benchmark.sh           # Performance benchmarks
│   └── generate_plots.py      # Visualization generation
│
├── bench/                      # Benchmark results
├── report/                     # Documentation
├── slides/                     # Presentations
└── figures/                    # Performance plots
```

## Database Schema

### Key Tables

**users**: Student authentication
- id, student_id, password_hash, name

**seats**: Library seating inventory
- id, branch, area, has_power, has_monitor, status

**reservations**: Booking records with conflict prevention
- id, user_id, seat_id, start_time, end_time, status, checked_in_at
- EXCLUDE constraint prevents overlapping active reservations

**waitlist**: User waiting queues
- id, user_id, seat_id, branch, desired_time, notified_at

### Sample Data

- **10 users**: S2021001-S2021010 (password: "password123")
- **50 seats** across 3 branches:
  - Main Library: 25 seats (15 silent, 10 group)
  - Science Library: 12 seats (research, reading, quiet)
  - Engineering Library: 13 seats (6 with monitors in computer lab)

## Key Design Decisions

### 1. Conflict Prevention

**PostgreSQL Exclusion Constraint**:
```sql
EXCLUDE USING gist (
    seat_id WITH =,
    tsrange(start_time, end_time) WITH &&
)
WHERE (status NOT IN ('CANCELLED', 'NO_SHOW'));
```

- Guarantees only one active reservation per seat/time
- Database-level enforcement (race condition proof)
- Works with concurrent requests

### 2. Cache Strategy

**Redis Caching**:
- Seat availability: 30s TTL
- Branch statistics: 5min TTL
- Invalidated on reservation changes
- Improves read performance 5-6x

### 3. Background Processing

**Check-in Worker**:
- Runs every 60 seconds
- Grace period: 15 minutes (configurable)
- Automatically marks NO_SHOW and COMPLETED
- Invalidates caches for affected seats

### 4. Service Communication

**REST**: HTTP/JSON via gateway
- Simple, widely compatible
- Easy debugging with curl
- HTTP/1.1 overhead

**gRPC**: Protocol Buffers
- Efficient binary protocol
- Type-safe contracts
- Better performance for high-throughput

## Common Operations

### View Logs

```bash
# REST services
docker-compose logs -f gateway
docker-compose logs -f auth
docker-compose logs -f checkin_worker

# gRPC service
docker-compose logs -f grpc-app

# Database
docker-compose logs -f postgres
```

### Reset Database

```bash
docker-compose down -v
docker-compose --profile rest up -d
```

### Debug Connection Issues

```bash
# Check service health
docker-compose ps

# Test database connection
docker-compose exec postgres psql -U dlsms -d dlsms -c "SELECT COUNT(*) FROM seats;"

# Test Redis
docker-compose exec redis redis-cli ping
```

## Environment Variables

Key configuration options in `.env`:

```bash
# Database
DATABASE_URL=postgresql://dlsms:dlsms123@postgres:5432/dlsms

# Redis
REDIS_URL=redis://redis:6379/0

# JWT
JWT_SECRET=your-secret-key-change-in-production
JWT_EXPIRATION_HOURS=24

# Check-in
GRACE_MINUTES=15

# gRPC concurrency guard
DB_MAX_CONCURRENT=60
```

## Troubleshooting

### Services won't start
- Check Docker daemon is running
- Verify port availability (8080-8084, 9090, 5433, 6379)
- Review logs: `docker-compose logs`

### Database connection errors
- Wait for PostgreSQL to be healthy: `docker-compose ps`
- Check credentials in `.env`
- Verify init scripts ran: `docker-compose logs postgres`

### Token errors (401)
- Verify JWT_SECRET matches across services
- Check token expiration (default 24 hours)
- Ensure Authorization header format: `Bearer {token}`
- If 401 occurs only when using `hey` under concurrency, verify a single request via `curl` works, then switch to `./scripts/benchmark.sh` (ab‑based) for REST benchmarks.

### Reservation conflicts not working
- Verify btree_gist extension loaded
- Check exclusion constraint: `\d+ reservations` in psql
- Review reservation status values

## Performance Tuning

### REST API
- Adjust worker count in Dockerfiles: `--workers 4`
- Tune Redis cache TTL values in seat/app.py
- Configure database connection pooling

### gRPC
- Modify ThreadPoolExecutor workers: `max_workers=100` (align with connection pool)
- Tune gRPC channel options / keep-alives for long-lived streams
- Adjust `DB_MAX_CONCURRENT` if Postgres capacity changes
- Enable gRPC compression for large responses

### Database
- Add indexes for frequent queries
- Tune PostgreSQL shared_buffers
- Enable query logging for optimization

## Security Considerations

**Production Checklist**:
- [ ] Change JWT_SECRET to strong random value
- [ ] Use HTTPS/TLS for all connections
- [ ] Enable gRPC TLS with certificates
- [ ] Implement rate limiting on gateway
- [ ] Use PostgreSQL SSL connections
- [ ] Set Redis password authentication
- [ ] Rotate JWT tokens regularly
- [ ] Add input validation and sanitization
- [ ] Enable CORS with whitelist
- [ ] Implement request logging and monitoring

## License

This project is for educational purposes.

## Contributors

- Muhan Zhang - Initial implementation
- Danhua Zhao - Initial implementation

## Support

For issues or questions:
1. Check logs: `docker-compose logs [service]`
2. Review README troubleshooting section
3. Verify database schema and seed data
4. Test with provided scripts

---

**Built with**: Python, Flask, gRPC, PostgreSQL, Redis, Docker
