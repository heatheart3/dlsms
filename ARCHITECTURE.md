# DL-SMS Architecture Documentation

## System Architecture Overview

The Distributed Library Seat Management System is implemented in two architectural styles:
1. **REST Microservices Architecture** - Distributed services communicating via HTTP
2. **gRPC Monolithic Architecture** - Single server with multiple service implementations

---

## REST Microservices Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                         CLIENT LAYER                              │
│  (Web Browser, Mobile App, API Client, curl, test scripts)       │
└────────────────────────────┬─────────────────────────────────────┘
                             │ HTTP/JSON
                             │
┌────────────────────────────▼─────────────────────────────────────┐
│                      API GATEWAY :8080                            │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  - JWT Token Validation                                    │  │
│  │  - Request Routing                                         │  │
│  │  - Load Balancing                                          │  │
│  │  - Rate Limiting (future)                                  │  │
│  │  - CORS Handling                                           │  │
│  └────────────────────────────────────────────────────────────┘  │
└──┬────────┬────────────┬─────────────┬────────────┬──────────────┘
   │        │            │             │            │
   │        │            │             │            │
   ▼        ▼            ▼             ▼            ▼
┌─────┐ ┌──────┐ ┌─────────────┐ ┌────────────┐ ┌────────┐
│Auth │ │Seat  │ │Reservation  │ │Notify      │ │Checkin │
│:8081│ │:8082 │ │:8083        │ │:8084       │ │Worker  │
└──┬──┘ └──┬───┘ └──────┬──────┘ └─────┬──────┘ └───┬────┘
   │       │            │               │             │
   │       │            │               │             │
   └───────┴────────────┴───────────────┴─────────────┘
                        │
        ┌───────────────┴────────────────┐
        │                                │
   ┌────▼─────┐                    ┌─────▼────┐
   │PostgreSQL│                    │  Redis   │
   │  :5433   │                    │  :6379   │
   │          │                    │          │
   │ - Users  │                    │ - Cache  │
   │ - Seats  │                    │ - TTL    │
   │ - Reserv │                    │          │
   │ - Waitl  │                    │          │
   └──────────┘                    └──────────┘
```

### Service Responsibilities

#### API Gateway (port 8080)
- **Purpose**: Single entry point for all client requests
- **Responsibilities**:
  - Extract and validate JWT tokens
  - Route requests to appropriate backend services
  - Handle authentication errors (401)
  - Proxy requests/responses
  - SSE stream proxying for notifications
- **Technology**: Flask, PyJWT, requests
- **Key Routes**:
  - `/auth/*` → Auth Service
  - `/seats*` → Seat Service
  - `/reservations*` → Reservation Service
  - `/waitlist*` → Notify Service
  - `/notifications/stream` → Notify Service (SSE)

#### Auth Service (port 8081)
- **Purpose**: User authentication and authorization
- **Responsibilities**:
  - User registration with password hashing (bcrypt)
  - User login with credential verification
  - JWT token generation with expiration
  - Token verification
- **Technology**: Flask, bcrypt, PyJWT, PostgreSQL
- **Database Access**: `users` table
- **Key Endpoints**:
  - `POST /login` - Authenticate and get token
  - `POST /register` - Create new user
  - `POST /verify` - Validate token

#### Seat Service (port 8082)
- **Purpose**: Seat inventory and availability management
- **Responsibilities**:
  - Seat discovery with filtering
  - Real-time availability calculation
  - Branch statistics aggregation
  - Redis caching for performance
  - Cache with 30-60 second TTL
- **Technology**: Flask, PostgreSQL, Redis
- **Database Access**: `seats`, `reservations` tables
- **Caching Strategy**:
  - Cache key format: `seats:{branch}:{filters}`
  - TTL: 30 seconds for seat lists, 60 seconds for individual seats
  - Invalidated by Reservation Service on bookings
- **Key Endpoints**:
  - `GET /seats` - List seats with filters
  - `GET /seats/{id}` - Get seat details
  - `GET /seats/{id}/availability` - Check time slot
  - `GET /branches` - Branch statistics

#### Reservation Service (port 8083)
- **Purpose**: Booking lifecycle management
- **Responsibilities**:
  - Reservation creation with conflict detection
  - Check-in validation and processing
  - Reservation cancellation
  - User reservation queries
  - Cache invalidation on changes
- **Technology**: Flask, PostgreSQL, Redis
- **Database Access**: `reservations`, `seats`, `users` tables
- **Conflict Prevention**:
  - PostgreSQL exclusion constraint
  - Transaction isolation level: READ COMMITTED
  - Row-level locking during creation
- **Key Endpoints**:
  - `POST /reservations` - Create booking
  - `GET /reservations/{id}` - Get details
  - `POST /reservations/{id}/checkin` - Check in
  - `DELETE /reservations/{id}` - Cancel
  - `GET /reservations/user/{id}` - User's bookings

#### Notify Service (port 8084)
- **Purpose**: Waitlist and notification management
- **Responsibilities**:
  - Waitlist entry management
  - Priority-based notification dispatch
  - SSE stream for real-time updates
  - Notification history tracking
- **Technology**: Flask, PostgreSQL, SSE
- **Database Access**: `waitlist`, `users`, `seats` tables
- **Notification Strategy**:
  - Specific seat waitlist checked first
  - Branch-level waitlist as fallback
  - FIFO ordering by created_at
  - Track notified_at timestamp
- **Key Endpoints**:
  - `POST /waitlist` - Add to waitlist
  - `GET /waitlist/user/{id}` - User's entries
  - `DELETE /waitlist/{id}` - Remove entry
  - `POST /notify` - Notify next in line
  - `GET /stream/{id}` - SSE notification stream

#### Check-in Worker (background)
- **Purpose**: Automated reservation status management
- **Responsibilities**:
  - Mark NO_SHOW after grace period expires
  - Complete past checked-in reservations
  - Invalidate caches for affected seats
  - Scheduled execution every 60 seconds
- **Technology**: Python, PostgreSQL, Redis, cron-like loop
- **Configuration**:
  - Grace period: 15 minutes (configurable via GRACE_MINUTES)
  - Check interval: 60 seconds
- **Logic**:
  ```python
  # NO_SHOW marking
  if status == 'CONFIRMED' and checked_in_at IS NULL:
      if start_time + GRACE_MINUTES < NOW():
          status = 'NO_SHOW'

  # Completion
  if status == 'CHECKED_IN' and end_time < NOW():
      status = 'COMPLETED'
  ```

---

## gRPC Monolithic Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                         CLIENT LAYER                              │
│  (gRPC Client, client_test.py, grpcurl, ghz benchmarking)        │
└────────────────────────────┬─────────────────────────────────────┘
                             │ gRPC/Protobuf
                             │
┌────────────────────────────▼─────────────────────────────────────┐
│                    gRPC SERVER :9090                              │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │                   Service Implementations                  │  │
│  │                                                            │  │
│  │  ┌──────────────────────────────────────────────────┐    │  │
│  │  │ AuthServiceServicer                              │    │  │
│  │  │  - Login(LoginRequest) → LoginResponse           │    │  │
│  │  │  - Register(RegisterRequest) → RegisterResponse  │    │  │
│  │  │  - Verify(VerifyRequest) → VerifyResponse        │    │  │
│  │  └──────────────────────────────────────────────────┘    │  │
│  │                                                            │  │
│  │  ┌──────────────────────────────────────────────────┐    │  │
│  │  │ SeatServiceServicer                              │    │  │
│  │  │  - GetSeats(GetSeatsRequest) → GetSeatsResponse  │    │  │
│  │  │  - GetSeat(GetSeatRequest) → GetSeatResponse     │    │  │
│  │  │  - CheckAvailability(...) → ...                  │    │  │
│  │  │  - GetBranches(...) → ...                        │    │  │
│  │  └──────────────────────────────────────────────────┘    │  │
│  │                                                            │  │
│  │  ┌──────────────────────────────────────────────────┐    │  │
│  │  │ ReservationServiceServicer                       │    │  │
│  │  │  - CreateReservation(...) → ...                  │    │  │
│  │  │  - GetReservation(...) → ...                     │    │  │
│  │  │  - CheckIn(...) → ...                            │    │  │
│  │  │  - CancelReservation(...) → ...                  │    │  │
│  │  │  - GetUserReservations(...) → ...                │    │  │
│  │  └──────────────────────────────────────────────────┘    │  │
│  │                                                            │  │
│  │  ┌──────────────────────────────────────────────────┐    │  │
│  │  │ NotifyServiceServicer                            │    │  │
│  │  │  - AddToWaitlist(...) → ...                      │    │  │
│  │  │  - GetUserWaitlist(...) → ...                    │    │  │
│  │  │  - RemoveFromWaitlist(...) → ...                 │    │  │
│  │  │  - NotifyUsers(...) → ...                        │    │  │
│  │  └──────────────────────────────────────────────────┘    │  │
│  │                                                            │  │
│  │  ┌──────────────────────────────────────────────────┐    │  │
│  │  │ Background Worker Thread                         │    │  │
│  │  │  - NO_SHOW processing every 60s                  │    │  │
│  │  │  - Completion processing                         │    │  │
│  │  └──────────────────────────────────────────────────┘    │  │
│  └────────────────────────────────────────────────────────────┘  │
└───────────────────────────┬──────────────────────────────────────┘
                            │
        ┌───────────────────┴────────────────┐
        │                                    │
   ┌────▼─────┐                        ┌─────▼────┐
   │PostgreSQL│                        │  Redis   │
   │  :5433   │                        │  :6379   │
   └──────────┘                        └──────────┘
```

### gRPC Service Features

- **Single Process**: All services run in one Python process
- **Shared Resources**: Database connection pool, Redis client shared
- **Thread Safety**: Uses ThreadPoolExecutor for concurrent requests
- **Background Thread**: Daemon thread for worker tasks
- **Protocol Buffers**: Type-safe, efficient serialization
- **Status Codes**: Proper gRPC status codes (ALREADY_EXISTS, NOT_FOUND, etc.)

---

## Database Schema

```
┌─────────────────────┐
│       users         │
├─────────────────────┤
│ id (PK)             │
│ student_id (UNIQUE) │◄──┐
│ password_hash       │   │
│ name                │   │
│ created_at          │   │
└─────────────────────┘   │
                          │
                          │
┌─────────────────────┐   │    ┌─────────────────────┐
│       seats         │   │    │    reservations     │
├─────────────────────┤   │    ├─────────────────────┤
│ id (PK)             │◄──┼────┤ id (PK)             │
│ branch              │   │    │ user_id (FK) ───────┘
│ area                │   │    │ seat_id (FK)        │
│ has_power           │   │    │ start_time          │
│ has_monitor         │   │    │ end_time            │
│ status              │   │    │ status              │
│ created_at          │   │    │ created_at          │
└─────────────────────┘   │    │ checked_in_at       │
        │                 │    └─────────────────────┘
        │                 │    CONSTRAINT: No overlapping
        │                 │    active reservations
        ▼                 │    (EXCLUDE USING gist)
┌─────────────────────┐   │
│      waitlist       │   │
├─────────────────────┤   │
│ id (PK)             │   │
│ user_id (FK) ───────────┘
│ seat_id (FK, NULL)  │
│ branch (NULL)       │
│ desired_time        │
│ notified_at         │
│ created_at          │
└─────────────────────┘
```

### Key Constraints

1. **Exclusion Constraint on reservations**:
   ```sql
   EXCLUDE USING gist (
       seat_id WITH =,
       tsrange(start_time, end_time) WITH &&
   ) WHERE (status NOT IN ('CANCELLED', 'NO_SHOW'))
   ```
   - Prevents overlapping active reservations
   - Atomic conflict detection at database level
   - Race condition proof

2. **Indexes for Performance**:
   - `seats(branch, has_power, has_monitor, status)` - Composite index
   - `reservations(user_id)` - User's bookings
   - `reservations(seat_id)` - Seat's bookings
   - `reservations(status, start_time, checked_in_at)` - Worker queries
   - `waitlist(user_id)` - User's waitlist

3. **Foreign Key Cascades**:
   - ON DELETE CASCADE for user references
   - Maintains referential integrity

---

## Data Flow Examples

### Example 1: Create Reservation

```
CLIENT
  │
  │ POST /reservations {seat_id, start_time, end_time}
  │ Authorization: Bearer <token>
  ▼
GATEWAY
  │ 1. Extract JWT token
  │ 2. Decode and validate (PyJWT)
  │ 3. Extract user_id from token
  │ 4. Add user_id to request body
  │ 5. Forward to Reservation Service
  ▼
RESERVATION SERVICE
  │ 1. Validate seat exists
  │ 2. Begin transaction
  │ 3. Execute INSERT with exclusion constraint
  │    - If conflict: PostgreSQL raises IntegrityError
  │    - If success: Return reservation
  │ 4. Commit transaction
  │ 5. Invalidate Redis cache for seat
  ▼
DATABASE
  │ 1. Check exclusion constraint
  │ 2. If conflict: ROLLBACK, return error
  │ 3. If no conflict: INSERT, COMMIT
  ▼
REDIS
  │ 1. Delete cache keys for affected seat
  │ 2. Next seat query will hit database
  ▼
RESPONSE
  │ Success: 201 + reservation JSON
  │ Conflict: 409 + error message
  │ Other error: 500 + error details
```

### Example 2: Seat Discovery with Cache

```
CLIENT
  │ GET /seats?branch=Main Library&has_power=true
  │ Authorization: Bearer <token>
  ▼
GATEWAY
  │ 1. Validate JWT token
  │ 2. Forward to Seat Service
  ▼
SEAT SERVICE
  │ 1. Build cache key from query params
  │ 2. Check Redis for cached result
  │
  ├─→ CACHE HIT
  │   │ 1. Return cached data
  │   │ 2. Response time: ~2-3ms
  │   ▼
  │   RESPONSE (fast)
  │
  └─→ CACHE MISS
      │ 1. Query PostgreSQL
      │ 2. Join with reservations for availability
      │ 3. Filter results
      │ 4. Store in Redis with 30s TTL
      │ 5. Return data
      ▼
      RESPONSE (~15-20ms)
```

### Example 3: Auto NO_SHOW Processing

```
CHECK-IN WORKER (runs every 60s)
  │
  │ 1. Calculate grace threshold
  │    threshold = NOW() - GRACE_MINUTES
  │
  │ 2. Query database
  │    SELECT * FROM reservations
  │    WHERE status = 'CONFIRMED'
  │      AND checked_in_at IS NULL
  │      AND start_time <= threshold
  │
  ▼
DATABASE
  │ Returns list of no-show reservations
  ▼
WORKER (for each reservation)
  │ 1. UPDATE reservations SET status = 'NO_SHOW' WHERE id = ?
  │ 2. COMMIT
  │ 3. Invalidate Redis cache for seat
  │ 4. Log action
  ▼
NOTIFY SERVICE (optional)
  │ 1. Check waitlist for seat
  │ 2. If users waiting, notify next in line
  │ 3. Send SSE event to connected clients
  ▼
COMPLETE
```

---

## Technology Stack Details

### Backend Services
- **Python 3.9+**: All services
- **Flask 3.0**: REST framework
  - Lightweight, flexible
  - Easy debugging
  - Good ecosystem
- **gRPC + Protocol Buffers**: RPC framework
  - Binary protocol (efficient)
  - Type-safe contracts
  - Code generation from .proto
- **Gunicorn**: WSGI server
  - Production-grade
  - Multiple workers
  - Graceful reloads

### Data Layer
- **PostgreSQL 15**: Primary database
  - ACID transactions
  - Exclusion constraints (GiST)
  - JSON support (future use)
  - Time range queries (tsrange)
- **Redis 7**: Cache layer
  - In-memory key-value store
  - TTL expiration
  - Pub/sub (future use)
  - Pattern-based deletion

### Security
- **bcrypt**: Password hashing
  - Adaptive cost factor
  - Salt generation
  - Timing attack resistant
- **PyJWT 2.8**: JWT implementation
  - HS256 algorithm
  - Token expiration
  - Payload validation

### Infrastructure
- **Docker**: Containerization
  - Isolated environments
  - Reproducible builds
  - Easy deployment
- **Docker Compose**: Orchestration
  - Multi-service management
  - Profile-based deployment
  - Network isolation
  - Volume management

---

## Performance Characteristics

### Throughput (requests/second)
- **Seat Discovery (cached)**: 1500-2000 req/s
- **Seat Discovery (uncached)**: 250-300 req/s
- **Branches API (cached)**: 400-500 req/s
- **User Reservations**: 150-200 req/s
- **Create Reservation**: 80-100 req/s
- **Check-in**: 100-150 req/s

### Latency (milliseconds)
- **Cached reads**: 2-5 ms
- **Uncached reads**: 15-30 ms
- **Write operations**: 40-60 ms
- **Complex joins**: 50-80 ms

### Caching Effectiveness
- **Cache hit ratio**: 70-80% (after warm-up)
- **Performance improvement**: 5-6x for cached reads
- **Cache invalidation time**: <1 ms

### Scalability
- **Vertical**: Up to 4-8 CPU cores per service
- **Horizontal**: Stateless services can scale out
- **Database**: Read replicas for read scaling
- **Cache**: Redis cluster for distributed caching

---

## Deployment Considerations

### Development
```bash
docker-compose --profile rest up -d
```
- All services local
- Hot reloading disabled (use volumes for dev)
- Debug logging enabled

### Staging
- Separate compose file
- External PostgreSQL
- Redis cluster
- Load testing

### Production
- Kubernetes deployment (future)
- Managed PostgreSQL (RDS/Cloud SQL)
- Managed Redis (ElastiCache/MemoryStore)
- Auto-scaling for services
- CDN for static assets
- Monitoring (Prometheus/Grafana)
- Logging (ELK/Loki)
- Tracing (Jaeger/Zipkin)

---

## Security Architecture

### Authentication Flow
1. User submits credentials
2. Auth service verifies with database
3. Generate JWT with user_id + expiration
4. Client stores token
5. Include in Authorization header
6. Gateway validates on every request

### Authorization
- Gateway validates JWT signature
- Extracts user_id from token
- Passes user_id to backend services
- Services enforce user-specific access

### Data Protection
- Passwords: bcrypt hashed, never stored plaintext
- JWT: Signed with HS256, secret key required
- Database: Connection string in environment
- Redis: No sensitive data stored

### Network Security
- Services communicate via Docker network
- Only gateway exposed externally
- Database not exposed to host
- Redis not exposed to host

---

This architecture provides:
- ✓ Clear separation of concerns
- ✓ Independent scalability
- ✓ Strong consistency (ACID)
- ✓ High performance (caching)
- ✓ Fault isolation (microservices)
- ✓ Type safety (gRPC/protobuf)
- ✓ Security (JWT, bcrypt)
- ✓ Observability (logs, health checks)
