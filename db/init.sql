-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- Users table
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    student_id VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    name VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Seats table
CREATE TABLE seats (
    id SERIAL PRIMARY KEY,
    branch VARCHAR(50) NOT NULL,
    area VARCHAR(50),
    has_power BOOLEAN DEFAULT false,
    has_monitor BOOLEAN DEFAULT false,
    status VARCHAR(20) DEFAULT 'AVAILABLE',
    created_at TIMESTAMP DEFAULT NOW(),
    CHECK (status IN ('AVAILABLE', 'OCCUPIED', 'MAINTENANCE'))
);

-- Create index for faster seat queries
CREATE INDEX idx_seats_branch ON seats(branch);
CREATE INDEX idx_seats_status ON seats(status);
CREATE INDEX idx_seats_filters ON seats(branch, has_power, has_monitor, status);

-- Reservations table
CREATE TABLE reservations (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    seat_id INTEGER NOT NULL REFERENCES seats(id) ON DELETE CASCADE,
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP NOT NULL,
    status VARCHAR(20) DEFAULT 'CONFIRMED',
    created_at TIMESTAMP DEFAULT NOW(),
    checked_in_at TIMESTAMP,
    CHECK (status IN ('CONFIRMED', 'CHECKED_IN', 'COMPLETED', 'CANCELLED', 'NO_SHOW')),
    CHECK (end_time > start_time)
);

-- Create exclusion constraint to prevent double bookings
-- Only active reservations (not CANCELLED or NO_SHOW) should block time slots
ALTER TABLE reservations
ADD CONSTRAINT reservations_no_overlap
EXCLUDE USING gist (
    seat_id WITH =,
    tsrange(start_time, end_time) WITH &&
)
WHERE (status NOT IN ('CANCELLED', 'NO_SHOW'));

-- Create indexes for faster reservation queries
CREATE INDEX idx_reservations_user ON reservations(user_id);
CREATE INDEX idx_reservations_seat ON reservations(seat_id);
CREATE INDEX idx_reservations_time ON reservations(start_time, end_time);
CREATE INDEX idx_reservations_status ON reservations(status);
CREATE INDEX idx_reservations_checkin ON reservations(status, start_time, checked_in_at)
    WHERE status = 'CONFIRMED' AND checked_in_at IS NULL;

-- Waitlist table
CREATE TABLE waitlist (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    seat_id INTEGER REFERENCES seats(id) ON DELETE CASCADE,
    branch VARCHAR(50),
    desired_time TIMESTAMP,
    notified_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Create index for waitlist queries
CREATE INDEX idx_waitlist_user ON waitlist(user_id);
CREATE INDEX idx_waitlist_seat ON waitlist(seat_id) WHERE seat_id IS NOT NULL;
CREATE INDEX idx_waitlist_branch ON waitlist(branch) WHERE branch IS NOT NULL;

-- Audit log table for tracking changes
CREATE TABLE audit_log (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    action VARCHAR(50) NOT NULL,
    entity_type VARCHAR(50) NOT NULL,
    entity_id INTEGER,
    details JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_audit_user ON audit_log(user_id);
CREATE INDEX idx_audit_time ON audit_log(created_at);
