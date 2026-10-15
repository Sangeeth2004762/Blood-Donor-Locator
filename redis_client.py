"""
redis_client.py
Connection setup and dedicated Redis operations for Blood Donor Locator.
Strictly encapsulates all NoSQL data interactions using redis-py.
Every Redis call is annotated with the command name and data type rationale.
"""

import datetime
import redis

# Redis constants required by application schema
BLOOD_GROUPS = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]
CITIES = ["Coimbatore", "Chennai", "Madurai", "Salem", "Tiruppur"]
OTP_TTL = 300  # 5 minutes in seconds
ELIGIBILITY_TTL = 90 * 24 * 60 * 60  # 90 days in seconds (7,776,000)

# Connect to Redis localhost:6379, db=0, decode_responses=True
# Uses protocol=2 fallback to ensure compatibility with Redis 5.x on Windows
try:
    r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True, protocol=2)
except TypeError:
    r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)


def ping():
    """Verify live connectivity to the Redis server."""
    # PING: Command to check Redis server availability and connection health.
    return r.ping()


def store_otp(mobile, otp):
    """Store simulated 6-digit OTP with 300-second self-expiring TTL."""
    # SETEX: Store 6-digit OTP as a String with 300s TTL for auto-expiration and memory efficiency.
    return r.setex(f"otp:{mobile}", OTP_TTL, str(otp))


def get_otp_ttl(mobile):
    """Retrieve remaining TTL in seconds for pending OTP verification."""
    # TTL: Retrieve remaining lifespan in seconds of the OTP String key to seed the live countdown.
    return r.ttl(f"otp:{mobile}")


def verify_otp(mobile, otp):
    """
    Validate supplied OTP against stored value.
    Returns: 'ok', 'expired', or 'mismatch'.
    On 'ok', key is immediately deleted to enforce one-time use.
    """
    key = f"otp:{mobile}"
    # GET: Fetch OTP String value to compare with user input.
    stored_otp = r.get(key)
    if stored_otp is None:
        return "expired"
    if str(stored_otp).strip() != str(otp).strip():
        return "mismatch"
    # DEL: Delete OTP String key on successful match to enforce strict one-time use.
    r.delete(key)
    return "ok"


def mobile_exists(mobile):
    """Check if mobile number is already registered in the system."""
    # SISMEMBER: Check presence in Set in O(1) time to enforce unique mobile numbers across donors.
    return bool(r.sismember("mobiles", str(mobile).strip()))


def create_donor(data):
    """
    Generate sequential donor ID and atomically store profile Hash and Set indexes.
    Uses MULTI/EXEC transaction pipeline for atomicity.
    """
    # INCR: Atomically increment String counter to generate unique sequential donor ID.
    donor_id = r.incr("donor:next_id")

    # Multi-key write using atomic transaction pipeline
    pipe = r.pipeline(transaction=True)
    # HSET: Store donor profile attributes as a Redis Hash entity representing a record.
    pipe.hset(
        f"donor:{donor_id}",
        mapping={
            "name": str(data["name"]).strip(),
            "age": str(data["age"]).strip(),
            "group": str(data["group"]).strip(),
            "city": str(data["city"]).strip(),
            "mobile": str(data["mobile"]).strip(),
            "last_donated": str(data.get("last_donated", "Never")).strip(),
        },
    )
    # SADD: Add donor ID to Set secondary index partitioned by blood group and city.
    pipe.sadd(f"group:{data['group']}:{data['city']}", donor_id)
    # SADD: Add mobile number to Set to guarantee uniqueness and block duplicates.
    pipe.sadd("mobiles", str(data["mobile"]).strip())
    pipe.execute()
    return donor_id


def get_donor(donor_id):
    """Retrieve donor Hash profile, attaching calculated ID and eligibility status."""
    # HGETALL: Retrieve all field-value pairs of the donor profile Hash.
    donor = r.hgetall(f"donor:{donor_id}")
    if not donor:
        return None
    donor["id"] = str(donor_id)
    donor["eligible"] = not is_unavailable(donor_id)
    return donor


def search_donors(blood_group, city):
    """
    Search donors matching blood group and city via Set index.
    Increments search counter and queries eligibility status for each member.
    """
    # INCR: Increment search requests String counter to track global system usage.
    r.incr("stats:requests")
    key = f"group:{blood_group}:{city}"
    # SMEMBERS: Retrieve all donor IDs belonging to this blood group and city Set index.
    donor_ids = r.smembers(key)
    donors = []
    for d_id in donor_ids:
        # HGETALL: Retrieve donor profile Hash fields for each matched ID.
        d = r.hgetall(f"donor:{d_id}")
        if d:
            d["id"] = str(d_id)
            # EXISTS: Check whether the 90-day temporary lock String key exists to determine donor eligibility.
            d["eligible"] = not bool(r.exists(f"unavailable:{d_id}"))
            donors.append(d)
    donors.sort(key=lambda x: int(x["id"]))
    return donors, key


def get_all_donors():
    """
    Retrieve all donors by iterating over donor keys using scan_iter.
    Skips the non-numeric donor:next_id counter key.
    """
    donors = []
    # SCAN_ITER: Cursor-based iteration over donor Hash keys avoiding full-table server blocking.
    for key in r.scan_iter("donor:*"):
        suffix = key.split(":")[-1]
        if suffix.isdigit():
            # HGETALL: Retrieve donor profile Hash fields for each active donor record.
            d = r.hgetall(key)
            if d:
                d["id"] = suffix
                # EXISTS: Check whether temporary lock String key exists to flag eligibility status.
                d["eligible"] = not bool(r.exists(f"unavailable:{suffix}"))
                donors.append(d)
    donors.sort(key=lambda x: int(x["id"]))
    return donors


def update_donor(donor_id, data):
    """
    Update donor Hash fields.
    Performs manual secondary index maintenance if group or city changed.
    """
    # HGETALL: Retrieve current donor Hash to inspect existing blood group and city index values.
    old_donor = r.hgetall(f"donor:{donor_id}")
    if not old_donor:
        return False

    old_group = old_donor.get("group")
    old_city = old_donor.get("city")
    new_group = str(data.get("group", old_group)).strip()
    new_city = str(data.get("city", old_city)).strip()

    # Multi-key write using atomic transaction pipeline
    pipe = r.pipeline(transaction=True)
    # HSET: Overwrite modified donor profile fields within the Hash.
    pipe.hset(
        f"donor:{donor_id}",
        mapping={
            "name": str(data["name"]).strip(),
            "age": str(data["age"]).strip(),
            "group": new_group,
            "city": new_city,
            "last_donated": old_donor.get("last_donated", "Never"),
        },
    )

    # Manual secondary index maintenance: Redis lacks automated secondary index updates.
    if old_group != new_group or old_city != new_city:
        # SREM: Remove donor ID from old group+city Set index during manual secondary index maintenance.
        pipe.srem(f"group:{old_group}:{old_city}", donor_id)
        # SADD: Add donor ID to new group+city Set index during manual secondary index maintenance.
        pipe.sadd(f"group:{new_group}:{new_city}", donor_id)

    pipe.execute()
    return True


def mark_unavailable(donor_id):
    """
    Record today's date in last_donated and set 90-day auto-expiring lock key.
    """
    today_iso = datetime.date.today().isoformat()
    # Multi-key write using atomic transaction pipeline
    pipe = r.pipeline(transaction=True)
    # HSET: Update last_donated date string inside the donor Hash.
    pipe.hset(f"donor:{donor_id}", "last_donated", today_iso)
    # SETEX: Set 90-day auto-expiring String lock marking donor ineligible until TTL elapses.
    pipe.setex(f"unavailable:{donor_id}", ELIGIBILITY_TTL, "1")
    pipe.execute()


def is_unavailable(donor_id):
    """Check if donor is currently under 90-day donation cooldown."""
    # EXISTS: Check whether temporary lock String key exists (1 if ineligible, 0 if eligible).
    return bool(r.exists(f"unavailable:{donor_id}"))


def delete_donor(donor_id):
    """
    Delete donor Hash and clean up group Set index, mobiles Set, and lock key.
    Prevents orphan keys across Redis.
    """
    # HGETALL: Retrieve donor Hash fields to identify associated secondary Set indexes and mobile number.
    donor = r.hgetall(f"donor:{donor_id}")
    # Multi-key write using atomic transaction pipeline
    pipe = r.pipeline(transaction=True)
    # DEL: Delete donor profile Hash completely.
    pipe.delete(f"donor:{donor_id}")
    if donor:
        # SREM: Remove donor ID from group+city Set index to eliminate orphaned index entries.
        pipe.srem(f"group:{donor['group']}:{donor['city']}", donor_id)
        # SREM: Remove mobile number from Set to permit re-registration in the future.
        pipe.srem("mobiles", donor["mobile"])
    # DEL: Delete donor's temporary eligibility lock String key if present.
    pipe.delete(f"unavailable:{donor_id}")
    pipe.execute()
    return True


def get_stats():
    """
    Calculate aggregate statistics across Redis database:
    - total donors
    - per_group donor counts (SCARD summed over cities)
    - max donors in any group (for relative progress bars)
    - requests (search count)
    - keys (DBSIZE)
    """
    per_group = {}
    for bg in BLOOD_GROUPS:
        # SCARD: Get cardinality of Set to count donors per blood group and city without fetching elements.
        count = sum(r.scard(f"group:{bg}:{city}") for city in CITIES)
        per_group[bg] = count

    total_donors = sum(per_group.values())
    max_count = max(per_group.values()) if per_group else 0
    # GET: Retrieve search request counter String value.
    req_raw = r.get("stats:requests")
    requests = int(req_raw) if req_raw else 0
    # DBSIZE: Return total count of all keys currently stored in Redis db=0.
    total_keys = r.dbsize()

    return {
        "total": total_donors,
        "per_group": per_group,
        "max": max_count,
        "requests": requests,
        "keys": total_keys,
    }
