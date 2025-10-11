# DL-SMS Deployment Guide

Complete guide for deploying the Distributed Library Seat Management System.

## Table of Contents
1. [Prerequisites](#prerequisites)
2. [Initial Setup](#initial-setup)
3. [REST Architecture Deployment](#rest-architecture-deployment)
4. [gRPC Architecture Deployment](#grpc-architecture-deployment)
5. [Verification](#verification)
6. [Troubleshooting](#troubleshooting)
7. [Monitoring](#monitoring)
8. [Maintenance](#maintenance)

---

## Prerequisites

### Required Software
- Docker Desktop 4.0+ (or Docker Engine 20.10+)
- Docker Compose 2.0+
- 4GB+ RAM available
- 2GB+ disk space

### Optional Tools
- curl (for API testing)
- jq (for JSON formatting)
- ab (Apache Bench - for performance testing)
- Python 3.9+ (for local gRPC client testing)

### Check Prerequisites
```bash
# Check Docker
docker --version
# Expected: Docker version 20.10.0 or higher

# Check Docker Compose
docker-compose --version
# Expected: Docker Compose version 2.0.0 or higher

# Check Docker is running
docker ps
# Should not error

# Check available RAM
docker info | grep "Total Memory"
# Should show at least 4GB
```

---

## Initial Setup

### 1. Navigate to Project Directory
```bash
cd /Users/muhanzhang/Documents/coding/project2/dlsms
```

### 2. Create Environment File
```bash
cp .env.example .env
```

### 3. (Optional) Customize Environment Variables
```bash
nano .env  # or use your preferred editor
```

Key variables to consider changing:
- `JWT_SECRET` - Change to a strong random string for production
- `GRACE_MINUTES` - Adjust check-in grace period (default: 15)
- `JWT_EXPIRATION_HOURS` - Token validity period (default: 24)

### 4. Make Scripts Executable
```bash
chmod +x scripts/*.sh
chmod +x grpc/client_test.py
```

---

## REST Architecture Deployment

### Step 1: Start Services
```bash
docker-compose --profile rest up -d
```

This command will:
1. Pull required images (postgres:15, redis:7-alpine, python:3.9-slim)
2. Build service images (gateway, auth, seat, reservation, notify, checkin_worker)
3. Create network and volumes
4. Start all services in background

### Step 2: Monitor Startup
```bash
# Watch logs in real-time
docker-compose logs -f

# Or check specific service
docker-compose logs -f gateway

# Press Ctrl+C to exit log view
```

Wait for these messages:
- PostgreSQL: `database system is ready to accept connections`
- Redis: `Ready to accept connections`
- Gateway: `Booting worker with pid`
- Auth: `Booting worker with pid`
- Seat: `Booting worker with pid`
- Reservation: `Booting worker with pid`
- Notify: `Booting worker with pid`
- Check-in Worker: `Check-in worker started with grace period`

### Step 3: Verify Service Health
```bash
# Check all containers are running
docker-compose ps

# Should show:
# - postgres (healthy)
# - redis (healthy)
# - gateway (running, healthy)
# - auth (running, healthy)
# - seat (running, healthy)
# - reservation (running, healthy)
# - notify (running, healthy)
# - checkin_worker (running)

# Test gateway health
curl http://localhost:8080/healthz
# Expected: {"status":"healthy","service":"gateway"}
```

### Step 4: Test Authentication
```bash
# Login
curl -X POST http://localhost:8080/auth/login \
  -H "Content-Type: application/json" \
  -d '{"student_id":"S2021001","password":"password123"}' | jq '.'

# Should return:
# {
#   "token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
#   "user_id": 1,
#   "student_id": "S2021001",
#   "name": "Alice Johnson"
# }
```

### Step 5: Run Comprehensive Tests
```bash
./scripts/test_rest.sh
```

Expected output:
- ✓ Health check passes
- ✓ Login successful
- ✓ Seats discovered
- ✓ Reservation created
- ✓ Conflict detected (409)
- ✓ Check-in successful
- ✓ Waitlist added

---

## gRPC Architecture Deployment

### Step 1: Stop REST Services (if running)
```bash
docker-compose --profile rest down
```

### Step 2: Start gRPC Service
```bash
docker-compose --profile grpc up -d
```

This will:
1. Start PostgreSQL and Redis (shared with REST)
2. Build gRPC server image
3. Compile protobuf definitions
4. Start gRPC server with background worker

### Step 3: Monitor Startup
```bash
docker-compose logs -f grpc-app
```

Wait for:
- `gRPC server started on port 9090`
- `Background worker started with grace period of 15 minutes`

### Step 4: Install gRPC Client Tools
```bash
pip install grpcio grpcio-tools
```

### Step 5: Compile Proto Files
```bash
cd grpc
python -m grpc_tools.protoc -I./protos --python_out=. --grpc_python_out=. ./protos/library.proto
cd ..
```

### Step 6: Run gRPC Tests
```bash
./scripts/test_grpc.sh
```

Or manually:
```bash
cd grpc
python client_test.py
```

Expected output:
- ✓ Login successful
- ✓ Seats retrieved
- ✓ Reservation created
- ✓ Conflict detected
- ✓ Check-in successful
- ✓ Waitlist operations work

---

## Verification

### Database Verification
```bash
# Connect to PostgreSQL
docker-compose exec postgres psql -U dlsms -d dlsms

# Check tables
\dt

# Expected tables:
# - users
# - seats
# - reservations
# - waitlist
# - audit_log

# Check seat count
SELECT COUNT(*) FROM seats;
# Expected: 50

# Check user count
SELECT COUNT(*) FROM users;
# Expected: 10

# Exit
\q
```

### Redis Verification
```bash
# Connect to Redis
docker-compose exec redis redis-cli

# Check connection
PING
# Expected: PONG

# Check keys (may be empty initially)
KEYS *

# Exit
exit
```

### Service Health Check (REST)
```bash
# Gateway
curl http://localhost:8080/healthz

# Auth (directly)
curl http://localhost:8081/healthz

# Seat (directly)
curl http://localhost:8082/healthz

# Reservation (directly)
curl http://localhost:8083/healthz

# Notify (directly)
curl http://localhost:8084/healthz
```

### Check Background Worker
```bash
# View worker logs
docker-compose logs checkin_worker

# Should show periodic checks every 60 seconds
# [timestamp] Running check...
# Processed X no-shows and Y completions
```

---

## Troubleshooting

### Services Won't Start

**Problem**: Docker compose fails to start
```bash
# Check Docker daemon
docker ps
# If error, restart Docker Desktop

# Check port conflicts
lsof -i :8080,8081,8082,8083,8084,9090,5433,6379
# Kill any conflicting processes

# Check disk space
df -h
# Ensure at least 2GB free

# Check memory
docker info | grep "Total Memory"
# Ensure at least 4GB available
```

### Database Connection Errors

**Problem**: Services can't connect to PostgreSQL
```bash
# Check PostgreSQL health
docker-compose ps postgres
# Should show "healthy"

# Check PostgreSQL logs
docker-compose logs postgres | tail -50

# Verify database exists
docker-compose exec postgres psql -U dlsms -l

# Restart PostgreSQL
docker-compose restart postgres
```

### JWT Token Errors (401)

**Problem**: Authentication fails
```bash
# Check JWT_SECRET consistency
docker-compose exec gateway env | grep JWT_SECRET
docker-compose exec auth env | grep JWT_SECRET
# Should match

# Get fresh token
TOKEN=$(curl -s -X POST http://localhost:8080/auth/login \
  -H "Content-Type: application/json" \
  -d '{"student_id":"S2021001","password":"password123"}' | jq -r '.token')

echo $TOKEN
# Should not be empty or "null"

# Verify token format (should have 3 parts separated by dots)
echo $TOKEN | awk -F. '{print NF}'
# Expected: 3
```

### Reservation Conflicts Not Working

**Problem**: Can book same seat twice
```bash
# Check exclusion constraint exists
docker-compose exec postgres psql -U dlsms -d dlsms -c "\d+ reservations"

# Look for: reservations_no_overlap exclusion constraint

# Check btree_gist extension
docker-compose exec postgres psql -U dlsms -d dlsms -c "\dx"

# Should show btree_gist

# If missing, recreate database
docker-compose down -v
docker-compose --profile rest up -d
```

### gRPC Connection Errors

**Problem**: gRPC client can't connect
```bash
# Check gRPC server is running
docker-compose ps grpc-app
# Should show "running"

# Check port is exposed
docker-compose port grpc-app 9090
# Should show: 0.0.0.0:9090

# Check logs
docker-compose logs grpc-app | grep "started on port"

# Test with grpcurl (if installed)
grpcurl -plaintext localhost:9090 list
```

### Complete Reset

**Problem**: Need to start fresh
```bash
# Stop all services
docker-compose --profile rest down
docker-compose --profile grpc down

# Remove volumes (deletes database data)
docker-compose down -v

# Remove all images (forces rebuild)
docker-compose down --rmi all

# Restart
docker-compose --profile rest up -d --build
```

---

## Monitoring

### View Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f gateway
docker-compose logs -f auth
docker-compose logs -f seat
docker-compose logs -f reservation
docker-compose logs -f notify
docker-compose logs -f checkin_worker
docker-compose logs -f grpc-app

# Last N lines
docker-compose logs --tail=100 gateway

# Since timestamp
docker-compose logs --since 2025-10-11T10:00:00 gateway
```

### Resource Usage

```bash
# Container stats (live view)
docker stats

# Shows:
# - CPU usage
# - Memory usage
# - Network I/O
# - Disk I/O
```

### Database Monitoring

```bash
# Active connections
docker-compose exec postgres psql -U dlsms -d dlsms -c "SELECT count(*) FROM pg_stat_activity;"

# Table sizes
docker-compose exec postgres psql -U dlsms -d dlsms -c "
SELECT tablename, pg_size_pretty(pg_total_relation_size(tablename::text)) AS size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(tablename::text) DESC;
"

# Recent reservations
docker-compose exec postgres psql -U dlsms -d dlsms -c "
SELECT id, seat_id, status, start_time, checked_in_at
FROM reservations
ORDER BY created_at DESC
LIMIT 10;
"
```

### Redis Monitoring

```bash
# Memory usage
docker-compose exec redis redis-cli INFO memory | grep "used_memory_human"

# Number of keys
docker-compose exec redis redis-cli DBSIZE

# Cache hit rate
docker-compose exec redis redis-cli INFO stats | grep "keyspace_hits\|keyspace_misses"
```

---

## Maintenance

### Backup Database

```bash
# Create backup directory
mkdir -p backups

# Backup database
docker-compose exec postgres pg_dump -U dlsms -d dlsms > backups/dlsms_$(date +%Y%m%d_%H%M%S).sql

# Verify backup
ls -lh backups/
```

### Restore Database

```bash
# Stop services
docker-compose --profile rest down

# Start only database
docker-compose up -d postgres

# Wait for PostgreSQL to be ready
docker-compose exec postgres pg_isready

# Restore
cat backups/dlsms_20251011_030000.sql | docker-compose exec -T postgres psql -U dlsms -d dlsms

# Restart services
docker-compose --profile rest up -d
```

### Clear Redis Cache

```bash
# Clear all cache
docker-compose exec redis redis-cli FLUSHALL

# Clear specific pattern
docker-compose exec redis redis-cli --scan --pattern "seats:*" | xargs docker-compose exec redis redis-cli DEL
```

### Update Services

```bash
# Pull latest code changes (if applicable)
git pull

# Rebuild and restart services
docker-compose --profile rest down
docker-compose --profile rest up -d --build

# Or for specific service
docker-compose up -d --build gateway
```

### Log Rotation

```bash
# Configure Docker logging in docker-compose.yml
services:
  gateway:
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

### Scale Services (for load testing)

```bash
# Scale seat service to 3 instances
docker-compose --profile rest up -d --scale seat=3

# View scaled instances
docker-compose ps seat

# Note: Requires load balancer configuration in gateway
```

---

## Performance Optimization

### Database Tuning

```bash
# Connect to PostgreSQL
docker-compose exec postgres psql -U dlsms -d dlsms

# Analyze tables
ANALYZE users;
ANALYZE seats;
ANALYZE reservations;
ANALYZE waitlist;

# Check index usage
SELECT schemaname, tablename, indexname, idx_scan
FROM pg_stat_user_indexes
ORDER BY idx_scan;

# Vacuum database
VACUUM ANALYZE;
```

### Redis Optimization

```bash
# Check fragmentation
docker-compose exec redis redis-cli INFO memory | grep "mem_fragmentation_ratio"

# If ratio > 1.5, consider restart
docker-compose restart redis
```

### Application Tuning

Edit Dockerfiles to adjust worker count:
```dockerfile
# From: CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "4", ...]
# To: CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "8", ...]
```

Then rebuild:
```bash
docker-compose up -d --build gateway
```

---

## Security Hardening

### Production Checklist

- [ ] Change `JWT_SECRET` to strong random value (32+ characters)
- [ ] Change database passwords in `.env`
- [ ] Enable Redis password authentication
- [ ] Use HTTPS/TLS for external connections
- [ ] Enable gRPC TLS with certificates
- [ ] Implement rate limiting on gateway
- [ ] Enable PostgreSQL SSL connections
- [ ] Restrict Docker network access
- [ ] Set up firewall rules
- [ ] Enable audit logging
- [ ] Rotate JWT tokens regularly
- [ ] Set up monitoring alerts
- [ ] Configure log aggregation
- [ ] Implement backup schedule

### Generate Strong Secrets

```bash
# Generate JWT secret
openssl rand -base64 32

# Generate database password
openssl rand -base64 24
```

Update `.env` with new values and restart:
```bash
docker-compose --profile rest down
docker-compose --profile rest up -d
```

---

## Shutdown

### Graceful Shutdown (REST)
```bash
docker-compose --profile rest down
```

### Graceful Shutdown (gRPC)
```bash
docker-compose --profile grpc down
```

### Complete Cleanup (removes volumes)
```bash
docker-compose --profile rest down -v
docker-compose --profile grpc down -v
```

### Remove Everything
```bash
# Stop and remove containers, networks, volumes, and images
docker-compose --profile rest down -v --rmi all
docker-compose --profile grpc down -v --rmi all
```

---

## Support

For issues:
1. Check logs: `docker-compose logs [service]`
2. Review this troubleshooting guide
3. Check README.md for architecture details
4. Verify prerequisites are met
5. Try complete reset

For questions about:
- **Architecture**: See ARCHITECTURE.md
- **Quick start**: See QUICKSTART.md
- **API usage**: See README.md
- **Testing**: See scripts/test_*.sh

---

**Deployment successful!**

Your DL-SMS instance is now running and ready to handle library seat reservations.
