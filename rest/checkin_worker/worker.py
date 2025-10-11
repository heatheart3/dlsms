import os
import time
import psycopg2
import redis
from datetime import datetime, timedelta
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.getenv('DATABASE_URL')
REDIS_URL = os.getenv('REDIS_URL')
GRACE_MINUTES = int(os.getenv('GRACE_MINUTES', '15'))
CHECK_INTERVAL = 60

redis_client = redis.from_url(REDIS_URL, decode_responses=True)

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def invalidate_seat_cache(seat_id):
    try:
        redis_client.delete(f"seat:{seat_id}")
        keys = redis_client.keys(f"seats:*")
        for key in keys:
            redis_client.delete(key)
    except Exception as e:
        print(f"Cache invalidation error: {e}")

def process_no_shows():
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        grace_threshold = datetime.utcnow() - timedelta(minutes=GRACE_MINUTES)

        cur.execute('''
            SELECT id, user_id, seat_id, start_time, end_time
            FROM reservations
            WHERE status = 'CONFIRMED'
            AND checked_in_at IS NULL
            AND start_time <= %s
        ''', (grace_threshold,))

        no_show_reservations = cur.fetchall()

        if no_show_reservations:
            print(f"Found {len(no_show_reservations)} no-show reservations to process")

            for reservation in no_show_reservations:
                try:
                    cur.execute('''
                        UPDATE reservations
                        SET status = 'NO_SHOW'
                        WHERE id = %s
                    ''', (reservation['id'],))

                    conn.commit()

                    print(f"Marked reservation {reservation['id']} as NO_SHOW (user: {reservation['user_id']}, seat: {reservation['seat_id']})")

                    invalidate_seat_cache(reservation['seat_id'])

                except Exception as e:
                    print(f"Error processing reservation {reservation['id']}: {e}")
                    conn.rollback()

        cur.close()
        conn.close()

        return len(no_show_reservations)

    except Exception as e:
        print(f"Error in process_no_shows: {e}")
        return 0

def complete_past_reservations():
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute('''
            SELECT id, seat_id
            FROM reservations
            WHERE status = 'CHECKED_IN'
            AND end_time < NOW()
        ''')

        completed_reservations = cur.fetchall()

        if completed_reservations:
            print(f"Found {len(completed_reservations)} reservations to complete")

            for reservation in completed_reservations:
                try:
                    cur.execute('''
                        UPDATE reservations
                        SET status = 'COMPLETED'
                        WHERE id = %s
                    ''', (reservation['id'],))

                    conn.commit()

                    print(f"Marked reservation {reservation['id']} as COMPLETED")

                    invalidate_seat_cache(reservation['seat_id'])

                except Exception as e:
                    print(f"Error completing reservation {reservation['id']}: {e}")
                    conn.rollback()

        cur.close()
        conn.close()

        return len(completed_reservations)

    except Exception as e:
        print(f"Error in complete_past_reservations: {e}")
        return 0

def main():
    print(f"Check-in worker started with grace period of {GRACE_MINUTES} minutes")
    print(f"Checking every {CHECK_INTERVAL} seconds")

    while True:
        try:
            print(f"\n[{datetime.utcnow().isoformat()}] Running check...")

            no_shows = process_no_shows()
            completed = complete_past_reservations()

            print(f"Processed {no_shows} no-shows and {completed} completions")

        except Exception as e:
            print(f"Error in main loop: {e}")

        time.sleep(CHECK_INTERVAL)

if __name__ == '__main__':
    time.sleep(10)
    main()
