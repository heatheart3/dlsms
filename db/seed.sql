-- Insert test users (password: "password123" hashed with bcrypt)
-- Hash generated with: bcrypt.hashpw("password123".encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
INSERT INTO users (student_id, password_hash, name) VALUES
('S2021001', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyYqVr/1Ry7q', 'Alice Johnson'),
('S2021002', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyYqVr/1Ry7q', 'Bob Smith'),
('S2021003', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyYqVr/1Ry7q', 'Charlie Brown'),
('S2021004', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyYqVr/1Ry7q', 'Diana Prince'),
('S2021005', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyYqVr/1Ry7q', 'Eve Adams'),
('S2021006', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyYqVr/1Ry7q', 'Frank Miller'),
('S2021007', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyYqVr/1Ry7q', 'Grace Hopper'),
('S2021008', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyYqVr/1Ry7q', 'Henry Ford'),
('S2021009', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyYqVr/1Ry7q', 'Ivy Chen'),
('S2021010', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyYqVr/1Ry7q', 'Jack Wilson');

-- Insert seats for Main Library
INSERT INTO seats (branch, area, has_power, has_monitor, status) VALUES
-- Main Library - Silent Study Zone (15 seats)
('Main Library', 'Silent Study Zone', true, false, 'AVAILABLE'),
('Main Library', 'Silent Study Zone', true, false, 'AVAILABLE'),
('Main Library', 'Silent Study Zone', true, false, 'AVAILABLE'),
('Main Library', 'Silent Study Zone', true, true, 'AVAILABLE'),
('Main Library', 'Silent Study Zone', true, true, 'AVAILABLE'),
('Main Library', 'Silent Study Zone', false, false, 'AVAILABLE'),
('Main Library', 'Silent Study Zone', false, false, 'AVAILABLE'),
('Main Library', 'Silent Study Zone', false, false, 'AVAILABLE'),
('Main Library', 'Silent Study Zone', true, false, 'AVAILABLE'),
('Main Library', 'Silent Study Zone', true, false, 'AVAILABLE'),
('Main Library', 'Silent Study Zone', true, true, 'AVAILABLE'),
('Main Library', 'Silent Study Zone', false, false, 'AVAILABLE'),
('Main Library', 'Silent Study Zone', true, false, 'AVAILABLE'),
('Main Library', 'Silent Study Zone', true, false, 'AVAILABLE'),
('Main Library', 'Silent Study Zone', true, true, 'AVAILABLE'),

-- Main Library - Group Study Zone (10 seats)
('Main Library', 'Group Study Zone', true, true, 'AVAILABLE'),
('Main Library', 'Group Study Zone', true, true, 'AVAILABLE'),
('Main Library', 'Group Study Zone', true, true, 'AVAILABLE'),
('Main Library', 'Group Study Zone', true, false, 'AVAILABLE'),
('Main Library', 'Group Study Zone', true, false, 'AVAILABLE'),
('Main Library', 'Group Study Zone', true, true, 'AVAILABLE'),
('Main Library', 'Group Study Zone', false, false, 'AVAILABLE'),
('Main Library', 'Group Study Zone', false, false, 'AVAILABLE'),
('Main Library', 'Group Study Zone', true, false, 'AVAILABLE'),
('Main Library', 'Group Study Zone', true, false, 'AVAILABLE'),

-- Science Library (12 seats)
('Science Library', 'Research Zone', true, true, 'AVAILABLE'),
('Science Library', 'Research Zone', true, true, 'AVAILABLE'),
('Science Library', 'Research Zone', true, true, 'AVAILABLE'),
('Science Library', 'Research Zone', true, true, 'AVAILABLE'),
('Science Library', 'Research Zone', true, false, 'AVAILABLE'),
('Science Library', 'Reading Room', true, false, 'AVAILABLE'),
('Science Library', 'Reading Room', true, false, 'AVAILABLE'),
('Science Library', 'Reading Room', false, false, 'AVAILABLE'),
('Science Library', 'Reading Room', false, false, 'AVAILABLE'),
('Science Library', 'Reading Room', true, true, 'AVAILABLE'),
('Science Library', 'Quiet Zone', true, false, 'AVAILABLE'),
('Science Library', 'Quiet Zone', true, false, 'AVAILABLE'),

-- Engineering Library (13 seats)
('Engineering Library', 'Computer Lab', true, true, 'AVAILABLE'),
('Engineering Library', 'Computer Lab', true, true, 'AVAILABLE'),
('Engineering Library', 'Computer Lab', true, true, 'AVAILABLE'),
('Engineering Library', 'Computer Lab', true, true, 'AVAILABLE'),
('Engineering Library', 'Computer Lab', true, true, 'AVAILABLE'),
('Engineering Library', 'Computer Lab', true, true, 'AVAILABLE'),
('Engineering Library', 'Study Desks', true, false, 'AVAILABLE'),
('Engineering Library', 'Study Desks', true, false, 'AVAILABLE'),
('Engineering Library', 'Study Desks', true, false, 'AVAILABLE'),
('Engineering Library', 'Study Desks', false, false, 'AVAILABLE'),
('Engineering Library', 'Collaborative Space', true, true, 'AVAILABLE'),
('Engineering Library', 'Collaborative Space', true, true, 'AVAILABLE'),
('Engineering Library', 'Collaborative Space', true, false, 'AVAILABLE');

-- Insert some sample reservations for testing
-- These are for today and near future
INSERT INTO reservations (user_id, seat_id, start_time, end_time, status) VALUES
(1, 1, NOW() + INTERVAL '1 hour', NOW() + INTERVAL '3 hours', 'CONFIRMED'),
(2, 2, NOW() + INTERVAL '2 hours', NOW() + INTERVAL '4 hours', 'CONFIRMED'),
(3, 15, NOW() + INTERVAL '30 minutes', NOW() + INTERVAL '2 hours', 'CONFIRMED'),
(4, 26, NOW() - INTERVAL '10 minutes', NOW() + INTERVAL '2 hours', 'CONFIRMED'),
(5, 30, NOW() + INTERVAL '4 hours', NOW() + INTERVAL '6 hours', 'CONFIRMED');

-- Insert some completed reservations (for history)
INSERT INTO reservations (user_id, seat_id, start_time, end_time, status, checked_in_at) VALUES
(1, 5, NOW() - INTERVAL '2 days', NOW() - INTERVAL '2 days' + INTERVAL '2 hours', 'COMPLETED', NOW() - INTERVAL '2 days' + INTERVAL '5 minutes'),
(2, 10, NOW() - INTERVAL '1 day', NOW() - INTERVAL '1 day' + INTERVAL '3 hours', 'COMPLETED', NOW() - INTERVAL '1 day' + INTERVAL '10 minutes'),
(3, 20, NOW() - INTERVAL '1 day', NOW() - INTERVAL '1 day' + INTERVAL '1 hour', 'NO_SHOW', NULL);

-- Insert some waitlist entries
INSERT INTO waitlist (user_id, seat_id, desired_time) VALUES
(6, 1, NOW() + INTERVAL '3 hours'),
(7, 2, NOW() + INTERVAL '4 hours'),
(8, NULL, NOW() + INTERVAL '2 hours');
