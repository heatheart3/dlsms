# DL-SMS Quick Start Guide

This guide will get you up and running with the Distributed Library Seat Management System in under 5 minutes.

## Prerequisites

- Docker Desktop installed and running
- Terminal/Command Line access

## Start REST Architecture (Recommended for Testing)

### 1. Navigate to project directory
```bash
cd /Users/muhanzhang/Documents/coding/project2/dlsms
```

### 2. Create environment file
```bash
cp .env.example .env
```

### 3. Start services
```bash
docker-compose --profile rest up -d
```

### 4. Wait for services to be ready (~30 seconds)
```bash
# Watch services start up
docker-compose ps

# Check logs
docker-compose logs -f
```

### 5. Test the API

#### Get a token
```bash
curl -X POST http://localhost:8080/auth/login \
  -H "Content-Type: application/json" \
  -d '{"student_id":"S2021001","password":"password123"}' | jq '.'
```

Save the token from response:
```bash
TOKEN="eyJ0eXAiOiJKV1QiLCJhbGc..."
```

#### View available seats
```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8080/seats?branch=Main%20Library&has_power=true" | jq '.'
```

#### Create a reservation
```bash
curl -X POST http://localhost:8080/reservations \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "seat_id": 10,
    "start_time": "2025-10-11T14:00:00",
    "end_time": "2025-10-11T16:00:00"
  }' | jq '.'
```

#### View your reservations
```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8080/reservations/mine" | jq '.'
```

## Start gRPC Architecture

### 1. Stop REST services (if running)
```bash
docker-compose --profile rest down
```

### 2. Start gRPC service
```bash
docker-compose --profile grpc up -d
```

### 3. Run gRPC client tests
```bash
# Install Python dependencies
pip install grpcio grpcio-tools

# Run tests
cd grpc
python -m grpc_tools.protoc -I./protos --python_out=. --grpc_python_out=. ./protos/library.proto
python client_test.py
```

## Run Comprehensive Tests

### REST API Tests
```bash
./scripts/test_rest.sh
```

### gRPC API Tests
```bash
./scripts/test_grpc.sh
```

## Available Test Users

All users have password: `password123`

- S2021001 - Alice Johnson
- S2021002 - Bob Smith
- S2021003 - Charlie Brown
- S2021004 - Diana Prince
- S2021005 - Eve Adams
- S2021006 - Frank Miller
- S2021007 - Grace Hopper
- S2021008 - Henry Ford
- S2021009 - Ivy Chen
- S2021010 - Jack Wilson

## Service Endpoints

### REST Architecture
- **Gateway**: http://localhost:8080
- **Auth**: http://localhost:8081
- **Seat**: http://localhost:8082
- **Reservation**: http://localhost:8083
- **Notify**: http://localhost:8084

### gRPC Architecture
- **gRPC Server**: localhost:9090

### Databases
- **PostgreSQL**: localhost:5433
  - Username: dlsms
  - Password: dlsms123
  - Database: dlsms
- **Redis**: localhost:6379

## Common Commands

### View logs
```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f gateway
docker-compose logs -f grpc-app
```

### Stop services
```bash
# REST
docker-compose --profile rest down

# gRPC
docker-compose --profile grpc down
```

### Reset database
```bash
docker-compose down -v
docker-compose --profile rest up -d
```

### Access database
```bash
docker-compose exec postgres psql -U dlsms -d dlsms
```

### Access Redis
```bash
docker-compose exec redis redis-cli
```

## Test Scenarios

### Scenario 1: Book a Seat
1. Login to get token
2. Find available seats in Main Library with power
3. Create reservation for 2 hours from now
4. View your reservations
5. Check in to the reservation (if time slot is current)

### Scenario 2: Conflict Detection
1. Create a reservation for seat 10 at 2pm-4pm
2. Try to create another reservation for seat 10 at 3pm-5pm
3. Should receive 409 Conflict error

### Scenario 3: Auto-Release
1. Create a reservation starting 20 minutes ago
2. Don't check in
3. Wait for check-in worker (runs every minute)
4. After 15 minute grace period, status becomes NO_SHOW

### Scenario 4: Waitlist
1. Add yourself to waitlist for a specific seat
2. View your waitlist entries
3. When seat becomes available, you'll be notified

## Troubleshooting

### Services won't start
```bash
# Check Docker is running
docker ps

# Check port conflicts
lsof -i :8080,8081,8082,8083,8084,9090,5433,6379

# Restart Docker Desktop
```

### Database connection errors
```bash
# Wait longer for PostgreSQL to initialize
docker-compose logs postgres

# Check database is ready
docker-compose exec postgres pg_isready
```

### Token errors (401)
```bash
# Get a fresh token
curl -X POST http://localhost:8080/auth/login \
  -H "Content-Type: application/json" \
  -d '{"student_id":"S2021001","password":"password123"}' | jq -r '.token'
```

### Clear everything and restart
```bash
# Stop and remove all containers, networks, and volumes
docker-compose --profile rest down -v
docker-compose --profile grpc down -v

# Restart
docker-compose --profile rest up -d
```

## Next Steps

1. **Explore the API**: Try different filters and operations
2. **Run benchmarks**: `./scripts/benchmark.sh`
3. **Generate plots**: `python3 scripts/generate_plots.py`
4. **Read full documentation**: See README.md
5. **Inspect database**: Connect to PostgreSQL and explore schema
6. **Modify code**: Edit services and rebuild with `docker-compose up -d --build`

## Performance Tips

- Redis caching improves seat discovery by 5-6x
- Use `available_only=true` for faster queries
- Specify time ranges for seat availability checks
- Background worker runs every 60 seconds

## Support

Check the main README.md for:
- Complete API documentation
- Architecture details
- Database schema
- Security considerations
- Production deployment guide

Happy coding!
