import os
import psycopg2
from datetime import datetime
from flask import Flask, request, jsonify, Response
from psycopg2.extras import RealDictCursor
import json
import time
import threading

app = Flask(__name__)

DATABASE_URL = os.getenv('DATABASE_URL')

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

active_streams = {}

def send_notification(user_id, notification_data):
    if user_id in active_streams:
        try:
            stream = active_streams[user_id]
            stream['queue'].append(notification_data)
        except Exception as e:
            print(f"Error sending notification to user {user_id}: {e}")

@app.route('/healthz', methods=['GET'])
def health():
    try:
        conn = get_db_connection()
        conn.close()
        return jsonify({'status': 'healthy'}), 200
    except Exception as e:
        return jsonify({'status': 'unhealthy', 'error': str(e)}), 500

@app.route('/waitlist', methods=['POST'])
def add_to_waitlist():
    try:
        data = request.get_json()

        if not data or 'user_id' not in data:
            return jsonify({'error': 'user_id is required'}), 400

        user_id = data['user_id']
        seat_id = data.get('seat_id')
        branch = data.get('branch')
        desired_time = data.get('desired_time')

        if not seat_id and not branch:
            return jsonify({'error': 'Either seat_id or branch must be provided'}), 400

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute('''
            INSERT INTO waitlist (user_id, seat_id, branch, desired_time)
            VALUES (%s, %s, %s, %s)
            RETURNING id, user_id, seat_id, branch, desired_time, created_at
        ''', (user_id, seat_id, branch, desired_time))

        waitlist_entry = cur.fetchone()
        conn.commit()

        cur.close()
        conn.close()

        return jsonify(dict(waitlist_entry)), 201

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/waitlist/user/<int:user_id>', methods=['GET'])
def get_user_waitlist(user_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute('''
            SELECT w.*, s.branch as seat_branch, s.area
            FROM waitlist w
            LEFT JOIN seats s ON w.seat_id = s.id
            WHERE w.user_id = %s
            ORDER BY w.created_at DESC
        ''', (user_id,))

        waitlist_entries = cur.fetchall()
        cur.close()
        conn.close()

        return jsonify({
            'waitlist': [dict(e) for e in waitlist_entries],
            'count': len(waitlist_entries)
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/waitlist/<int:waitlist_id>', methods=['DELETE'])
def remove_from_waitlist(waitlist_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute('DELETE FROM waitlist WHERE id = %s RETURNING id', (waitlist_id,))
        deleted = cur.fetchone()

        if not deleted:
            cur.close()
            conn.close()
            return jsonify({'error': 'Waitlist entry not found'}), 404

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({'message': 'Removed from waitlist', 'id': deleted['id']}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/notify', methods=['POST'])
def notify_users():
    try:
        data = request.get_json()

        if not data or 'seat_id' not in data:
            return jsonify({'error': 'seat_id is required'}), 400

        seat_id = data['seat_id']
        message = data.get('message', 'A seat has become available')

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute('''
            SELECT w.*, u.student_id, u.name
            FROM waitlist w
            JOIN users u ON w.user_id = u.id
            WHERE w.seat_id = %s AND w.notified_at IS NULL
            ORDER BY w.created_at
            LIMIT 1
        ''', (seat_id,))

        waitlist_entry = cur.fetchone()

        if not waitlist_entry:
            cur.execute('''
                SELECT w.*, u.student_id, u.name, s.branch
                FROM waitlist w
                JOIN users u ON w.user_id = u.id
                JOIN seats s ON s.id = %s
                WHERE w.branch = s.branch AND w.seat_id IS NULL AND w.notified_at IS NULL
                ORDER BY w.created_at
                LIMIT 1
            ''', (seat_id,))

            waitlist_entry = cur.fetchone()

        if waitlist_entry:
            cur.execute('''
                UPDATE waitlist
                SET notified_at = NOW()
                WHERE id = %s
            ''', (waitlist_entry['id'],))

            conn.commit()

            notification_data = {
                'type': 'seat_available',
                'seat_id': seat_id,
                'message': message,
                'timestamp': datetime.utcnow().isoformat()
            }

            send_notification(waitlist_entry['user_id'], notification_data)

            cur.close()
            conn.close()

            return jsonify({
                'notified': True,
                'user_id': waitlist_entry['user_id'],
                'student_id': waitlist_entry['student_id'],
                'message': message
            }), 200
        else:
            cur.close()
            conn.close()

            return jsonify({
                'notified': False,
                'message': 'No users in waitlist for this seat'
            }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/stream/<int:user_id>')
def stream_notifications(user_id):
    def event_stream():
        queue = []
        active_streams[user_id] = {'queue': queue}

        try:
            yield f"data: {json.dumps({'type': 'connected', 'user_id': user_id})}\n\n"

            while True:
                if queue:
                    notification = queue.pop(0)
                    yield f"data: {json.dumps(notification)}\n\n"
                else:
                    yield f": keepalive\n\n"

                time.sleep(1)

        except GeneratorExit:
            if user_id in active_streams:
                del active_streams[user_id]

    return Response(event_stream(), mimetype='text/event-stream')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8084, debug=False, threaded=True)
