"""
seed_data.py
Populates Redis database with initial sample donor records for testing and demonstration.
Usage:
    python seed_data.py          # Seeds 10 donors (skips duplicates)
    python seed_data.py --reset  # Flushes db=0 first, then seeds
"""

import sys
import redis
import redis_client

SAMPLE_DONORS = [
    {
        "name": "Ramesh Kumar",
        "age": 28,
        "group": "O+",
        "city": "Coimbatore",
        "mobile": "9876500001",
        "last_donated": "2026-01-15",
    },
    {
        "name": "Priya Sharma",
        "age": 24,
        "group": "A+",
        "city": "Chennai",
        "mobile": "9876500002",
        "last_donated": "2026-03-01",
    },
    {
        "name": "Karthik Raja",
        "age": 35,
        "group": "B+",
        "city": "Coimbatore",
        "mobile": "9876500003",
        "last_donated": "2025-11-20",
    },
    {
        "name": "Ananya Rao",
        "age": 22,
        "group": "O-",
        "city": "Madurai",
        "mobile": "9876500004",
        "last_donated": "Never",
    },
    {
        "name": "Suresh Babu",
        "age": 42,
        "group": "AB+",
        "city": "Chennai",
        "mobile": "9876500005",
        "last_donated": "2026-02-10",
    },
    {
        "name": "Deepa Sundaram",
        "age": 31,
        "group": "B+",
        "city": "Coimbatore",
        "mobile": "9876500006",
        "last_donated": "2026-03-20",
    },
    {
        "name": "Vignesh Murugan",
        "age": 29,
        "group": "A+",
        "city": "Salem",
        "mobile": "9876500007",
        "last_donated": "Never",
    },
    {
        "name": "Meera Natarajan",
        "age": 26,
        "group": "O+",
        "city": "Tiruppur",
        "mobile": "9876500008",
        "last_donated": "2025-12-05",
    },
    {
        "name": "Arun Prakash",
        "age": 38,
        "group": "B-",
        "city": "Chennai",
        "mobile": "9876500009",
        "last_donated": "2026-01-25",
    },
    {
        "name": "Kavitha Selvam",
        "age": 27,
        "group": "O+",
        "city": "Coimbatore",
        "mobile": "9876500010",
        "last_donated": "Never",
    },
]


def seed():
    try:
        redis_client.ping()
    except (redis.exceptions.ConnectionError, redis.exceptions.ResponseError) as err:
        print(f"\n[ERROR] Cannot connect to Redis on localhost:6379: {err}")
        print("Please start Redis server before seeding: redis-server\n")
        sys.exit(1)

    # Optional database reset
    if "--reset" in sys.argv:
        print("[RESET] Flushing database db=0...")
        # FLUSHDB: Clears all keys in the selected Redis database for a clean start.
        redis_client.r.flushdb()
        print("Database flushed successfully.")

    created_ids = []
    skipped = 0

    print("\n--- Seeding Blood Donor Data ---")
    for idx, donor_data in enumerate(SAMPLE_DONORS, start=1):
        mobile = donor_data["mobile"]
        if redis_client.mobile_exists(mobile):
            print(f"Skipping donor '{donor_data['name']}' ({mobile}): Mobile already registered.")
            skipped += 1
            continue

        donor_id = redis_client.create_donor(donor_data)
        created_ids.append(donor_id)
        print(f"[{idx}/10] Created donor #{donor_id}: {donor_data['name']} ({donor_data['group']}, {donor_data['city']})")

    # Mark two of the newly created donors unavailable so the TTL lock is visible immediately
    if len(created_ids) >= 2:
        donor_lock_1 = created_ids[1]  # Second created donor
        donor_lock_2 = created_ids[5] if len(created_ids) > 5 else created_ids[-1]
        redis_client.mark_unavailable(donor_lock_1)
        redis_client.mark_unavailable(donor_lock_2)
        print(f"\n[TTL LOCK] Donors #{donor_lock_1} and #{donor_lock_2} marked unavailable (90-day cooldown active).")

    stats = redis_client.get_stats()
    print("\n--- Seeding Complete ---")
    print(f"Total donors in database: {stats['total']}")
    print(f"Skipped existing: {skipped}")
    print(f"Total keys in Redis: {stats['keys']}")
    print("Done.\n")


if __name__ == "__main__":
    seed()
