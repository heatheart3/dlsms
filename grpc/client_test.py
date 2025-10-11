#!/usr/bin/env python3
import grpc
import library_pb2
import library_pb2_grpc
from datetime import datetime, timedelta

def run_tests():
    channel = grpc.insecure_channel('localhost:9090')

    auth_stub = library_pb2_grpc.AuthServiceStub(channel)
    seat_stub = library_pb2_grpc.SeatServiceStub(channel)
    reservation_stub = library_pb2_grpc.ReservationServiceStub(channel)
    notify_stub = library_pb2_grpc.NotifyServiceStub(channel)

    print("=" * 50)
    print("Testing gRPC Library Management System")
    print("=" * 50)

    print("\n1. Testing Authentication - Login")
    try:
        login_response = auth_stub.Login(library_pb2.LoginRequest(
            student_id='S2021001',
            password='password123'
        ))
        print(f"  Login successful!")
        print(f"  User ID: {login_response.user_id}")
        print(f"  Name: {login_response.name}")
        print(f"  Token: {login_response.token[:50]}...")
        token = login_response.token
        user_id = login_response.user_id
    except grpc.RpcError as e:
        print(f"  Login failed: {e.details()}")
        return

    print("\n2. Testing Seat Discovery - Get All Seats")
    try:
        seats_response = seat_stub.GetSeats(library_pb2.GetSeatsRequest(
            available_only=True
        ))
        print(f"  Found {seats_response.count} available seats")
        if seats_response.count > 0:
            seat = seats_response.seats[0]
            print(f"  First seat: ID={seat.id}, Branch={seat.branch}, Area={seat.area}")
    except grpc.RpcError as e:
        print(f"  Error: {e.details()}")

    print("\n3. Testing Seat Discovery - Filter by Branch and Power")
    try:
        seats_response = seat_stub.GetSeats(library_pb2.GetSeatsRequest(
            branch='Main Library',
            has_power=True,
            available_only=True
        ))
        print(f"  Found {seats_response.count} seats in Main Library with power")
        for i, seat in enumerate(seats_response.seats[:3]):
            print(f"  Seat {i+1}: ID={seat.id}, Area={seat.area}, Monitor={seat.has_monitor}")
    except grpc.RpcError as e:
        print(f"  Error: {e.details()}")

    print("\n4. Testing Branches")
    try:
        branches_response = seat_stub.GetBranches(library_pb2.GetBranchesRequest())
        print(f"  Found {len(branches_response.branches)} branches:")
        for branch in branches_response.branches:
            print(f"    {branch.branch}: {branch.total_seats} total, {branch.power_seats} with power")
    except grpc.RpcError as e:
        print(f"  Error: {e.details()}")

    print("\n5. Testing Reservation Creation")
    start_time = (datetime.utcnow() + timedelta(hours=1)).isoformat()
    end_time = (datetime.utcnow() + timedelta(hours=3)).isoformat()

    try:
        available_seats = seat_stub.GetSeats(library_pb2.GetSeatsRequest(
            available_only=True,
            start_time=start_time,
            end_time=end_time
        ))

        if available_seats.count > 0:
            test_seat_id = available_seats.seats[0].id

            reservation_response = reservation_stub.CreateReservation(
                library_pb2.CreateReservationRequest(
                    user_id=user_id,
                    seat_id=test_seat_id,
                    start_time=start_time,
                    end_time=end_time
                )
            )
            print(f"  Reservation created successfully!")
            print(f"  Reservation ID: {reservation_response.reservation.id}")
            print(f"  Seat ID: {reservation_response.reservation.seat_id}")
            print(f"  Status: {reservation_response.reservation.status}")
            reservation_id = reservation_response.reservation.id

            print("\n6. Testing Conflict Detection - Attempt Double Booking")
            try:
                duplicate_response = reservation_stub.CreateReservation(
                    library_pb2.CreateReservationRequest(
                        user_id=user_id,
                        seat_id=test_seat_id,
                        start_time=start_time,
                        end_time=end_time
                    )
                )
                print("  ERROR: Should have failed with conflict!")
            except grpc.RpcError as e:
                if e.code() == grpc.StatusCode.ALREADY_EXISTS:
                    print(f"  Conflict detected correctly: {e.details()}")
                else:
                    print(f"  Unexpected error: {e.details()}")

            print("\n7. Testing Get Reservation")
            try:
                get_res_response = reservation_stub.GetReservation(
                    library_pb2.GetReservationRequest(reservation_id=reservation_id)
                )
                print(f"  Reservation details:")
                print(f"    ID: {get_res_response.reservation.id}")
                print(f"    Branch: {get_res_response.reservation.branch}")
                print(f"    Area: {get_res_response.reservation.area}")
                print(f"    Status: {get_res_response.reservation.status}")
            except grpc.RpcError as e:
                print(f"  Error: {e.details()}")

            print("\n8. Testing Get User Reservations")
            try:
                user_res_response = reservation_stub.GetUserReservations(
                    library_pb2.GetUserReservationsRequest(
                        user_id=user_id,
                        upcoming_only=True
                    )
                )
                print(f"  User has {user_res_response.count} upcoming reservations")
                for res in user_res_response.reservations[:3]:
                    print(f"    Reservation {res.id}: Seat {res.seat_id}, Status: {res.status}")
            except grpc.RpcError as e:
                print(f"  Error: {e.details()}")

            print("\n9. Testing Reservation Cancellation")
            try:
                cancel_response = reservation_stub.CancelReservation(
                    library_pb2.CancelReservationRequest(reservation_id=reservation_id)
                )
                print(f"  Reservation cancelled successfully!")
                print(f"  New status: {cancel_response.reservation.status}")
            except grpc.RpcError as e:
                print(f"  Error: {e.details()}")
        else:
            print("  No available seats to test reservation")
    except grpc.RpcError as e:
        print(f"  Error: {e.details()}")

    print("\n10. Testing Waitlist")
    try:
        waitlist_response = notify_stub.AddToWaitlist(
            library_pb2.AddToWaitlistRequest(
                user_id=user_id,
                seat_id=1,
                desired_time=start_time
            )
        )
        print(f"  Added to waitlist successfully!")
        print(f"  Waitlist entry ID: {waitlist_response.entry.id}")
        waitlist_id = waitlist_response.entry.id

        get_waitlist_response = notify_stub.GetUserWaitlist(
            library_pb2.GetUserWaitlistRequest(user_id=user_id)
        )
        print(f"  User has {get_waitlist_response.count} waitlist entries")

        remove_response = notify_stub.RemoveFromWaitlist(
            library_pb2.RemoveFromWaitlistRequest(waitlist_id=waitlist_id)
        )
        print(f"  Removed from waitlist: {remove_response.message}")
    except grpc.RpcError as e:
        print(f"  Error: {e.details()}")

    print("\n11. Testing Check-in (with current reservation)")
    start_now = datetime.utcnow().isoformat()
    end_later = (datetime.utcnow() + timedelta(hours=2)).isoformat()

    try:
        available_seats = seat_stub.GetSeats(library_pb2.GetSeatsRequest(
            available_only=True,
            start_time=start_now,
            end_time=end_later
        ))

        if available_seats.count > 0:
            test_seat_id = available_seats.seats[0].id

            reservation_response = reservation_stub.CreateReservation(
                library_pb2.CreateReservationRequest(
                    user_id=user_id,
                    seat_id=test_seat_id,
                    start_time=start_now,
                    end_time=end_later
                )
            )
            print(f"  Created reservation for immediate check-in: ID={reservation_response.reservation.id}")

            checkin_response = reservation_stub.CheckIn(
                library_pb2.CheckInRequest(reservation_id=reservation_response.reservation.id)
            )
            print(f"  Checked in successfully!")
            print(f"  Status: {checkin_response.reservation.status}")
            print(f"  Checked in at: {checkin_response.reservation.checked_in_at}")
        else:
            print("  No available seats for check-in test")
    except grpc.RpcError as e:
        print(f"  Error: {e.details()}")

    print("\n" + "=" * 50)
    print("All tests completed!")
    print("=" * 50)

    channel.close()

if __name__ == '__main__':
    run_tests()
