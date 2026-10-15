# Blood Donor Locator

Fast, reliable blood donor discovery application built with Python Flask and Redis in-memory database.

---

## 1. Important Windows Folder Placement Note

> [!IMPORTANT]
> **Windows Path Best Practices**:
> - Clone or place this project in a **non-system path** or dedicated workspace directory (for example, `E:\Projects\blood_donor_locator` or `C:\Dev\blood_donor_locator`).
> - **Avoid spaces** anywhere in the directory path (e.g., avoid paths like `C:\Users\John Doe\My Documents\...`).
> - **Do NOT** place this project inside `C:\xampp\htdocs\` or `C:\wamp64\www\`. This is a native Python/Flask and Redis standalone application; running it under Apache/XAMPP will cause port conflicts and virtualenv path issues.

---

## 2. Setup & Installation Instructions

### Prerequisites
1. **Python 3.10+** (Python 3.10, 3.11, 3.12, 3.13, or 3.14).
2. **Redis Server** (Redis 5.0+ or Memurai on Windows) running on port `6379`.

### Step 1: Start Redis Server
Ensure your local Redis server is running:
```powershell
# If installed as a Windows service:
Start-Service Redis

# Or if running redis-server directly:
redis-server
```
Verify connectivity:
```powershell
redis-cli ping
# Expected output: PONG
```

### Step 2: Create and Activate Virtual Environment
Open PowerShell or Command Prompt inside the project folder:
```powershell
cd blood_donor_locator
python -m venv venv
.\venv\Scripts\Activate.ps1
```

### Step 3: Install Required Dependencies
```powershell
pip install -r requirements.txt
```
*(Dependencies: `flask>=3.0`, `redis>=5.0`)*

### Step 4: Populate Seed Data
Load 10 initial sample donors across multiple blood groups and cities:
```powershell
# Reset existing db=0 and insert 10 sample donors (with 2 donors locked):
python seed_data.py --reset

# Or seed without resetting (skips existing mobile numbers):
python seed_data.py
```

### Step 5: Run the Flask Web Application
```powershell
python app.py
```
Open your browser and navigate to:
**[http://127.0.0.1:5000](http://127.0.0.1:5000)**

---

## 3. Redis NoSQL Schema Architecture

Redis is the **sole** data store for this project. No relational tables, SQLite, MySQL, or ORM libraries are used. Relational concepts are modeled using Redis Hashes, Sets, and Strings.

| Purpose | Key Pattern | Type | Commands Used | Design Rationale |
| :--- | :--- | :--- | :--- | :--- |
| **Donor profile** | `donor:<id>` | **Hash** | `HSET`, `HGETALL`, `DEL` | Represents an individual record as a field-value dictionary (`name`, `age`, `group`, `city`, `mobile`, `last_donated`) with O(1) field access. |
| **Group+City index** | `group:<bloodgroup>:<city>` | **Set** | `SADD`, `SMEMBERS`, `SREM`, `SCARD` | Secondary index allowing O(1) membership lookups and instant group+city filtering without scanning full tables. |
| **ID generator** | `donor:next_id` | **String** | `INCR` | Atomic sequential integer counter avoiding concurrency race conditions during donor ID creation. |
| **OTP store** | `otp:<mobile>` | **String + TTL** | `SETEX (300)`, `GET`, `DEL`, `TTL` | Stores 6-digit verification code with a 5-minute (300s) auto-expiring TTL; deleted on verification for single use. |
| **Eligibility lock** | `unavailable:<id>` | **String + TTL** | `SETEX (7776000)`, `EXISTS` | 90-day (7,776,000s) cooldown lock set after donation. Presence denotes ineligibility. |
| **Duplicate check** | `mobiles` | **Set** | `SADD`, `SISMEMBER`, `SREM` | Global Set of all registered phone numbers providing instant O(1) duplicate checks. |
| **Search counter** | `stats:requests` | **String** | `INCR`, `GET` | Global numeric counter incremented on every donor search query. |

---

## 4. Back-End Verification via `redis-cli`

During laboratory evaluation and viva, run these commands in `redis-cli` to inspect live data structures:

```bash
# 1. View all donor Hash keys currently in database
KEYS donor:*

# 2. Inspect all field-value pairs of Donor #1
HGETALL donor:1

# 3. Retrieve all donor IDs indexed under B+ blood group in Coimbatore
SMEMBERS group:B+:Coimbatore

# 4. Check the remaining live TTL of an OTP during verification
TTL otp:9876543210

# 5. Get the total number of O+ donors registered in Coimbatore without reading all items
SCARD group:O+:Coimbatore

# 6. View the total search queries performed
GET stats:requests

# 7. Check total number of keys stored in Redis db=0
DBSIZE
```

---

## 5. CRUD to Redis Command Mapping

| CRUD Operation | Application Workflow | Redis Command(s) | Data Type | Justification / Viva Notes |
| :--- | :--- | :--- | :--- | :--- |
| **CREATE** | Generate unique Donor ID | `INCR donor:next_id` | String | Atomic increment eliminates race conditions when multiple users register simultaneously. |
| **CREATE** | Store donor profile fields | `HSET donor:<id>` | Hash | Memory-efficient key-value map representing a structured entity record. |
| **CREATE** | Add to secondary index | `SADD group:<bg>:<city> <id>` | Set | Unordered unique collection allowing O(1) addition and fast index union/intersection. |
| **CREATE** | Enforce mobile uniqueness | `SADD mobiles <mobile>` | Set | Set membership test `SISMEMBER` runs in O(1) time prior to registration. |
| **READ** | Retrieve donor profile | `HGETALL donor:<id>` | Hash | Fetches entire profile mapping in a single round-trip. |
| **READ** | Query matching donors | `SMEMBERS group:<bg>:<city>` | Set | Retrieves all member IDs belonging to the composite index. |
| **READ** | Check donation eligibility | `EXISTS unavailable:<id>` | String | Checks presence of 90-day cooldown key (`1` = locked, `0` = eligible). |
| **READ** | Iterate all donors (Admin) | `SCAN_ITER donor:*` | Hash | Cursor-based iteration avoids blocking Redis compared to `KEYS *`. |
| **READ** | Aggregated group counts | `SCARD group:<bg>:<city>` | Set | O(1) cardinality measurement without transporting data across the network. |
| **UPDATE** | Edit profile attributes | `HSET donor:<id>` | Hash | Overwrites updated attributes while keeping unchanged fields intact. |
| **UPDATE** | Relocate index on group/city change | `SREM group:<old> <id>`<br>`SADD group:<new> <id>` | Set | **Manual Secondary Index Maintenance**: Redis does not have triggers or foreign keys; indices must be manually updated in MULTI/EXEC. |
| **DELETE** | Remove profile and index keys | `DEL donor:<id>`<br>`SREM group:<bg>:<city> <id>`<br>`SREM mobiles <mobile>`<br>`DEL unavailable:<id>` | Hash, Set, String | Atomic MULTI/EXEC execution cleans up primary profile, secondary indices, uniqueness Set, and locks with **zero orphan keys**. |

---

## 6. Step-by-Step TTL Expiry Demonstration for the Viva

Examiners frequently request live proof of Redis TTL-based expiration and data integrity. Follow these steps:

### Scenario A: OTP Key Expiration (5-minute TTL)
1. Open the application at `http://127.0.0.1:5000/register`.
2. Fill in the form: Name: `Test Expiry`, Age: `25`, Group: `O+`, City: `Coimbatore`, Mobile: `9988776655`.
3. Click **Proceed to OTP Verification**.
4. In your terminal running Flask, note the simulated SMS output:
   ```text
   [SIMULATED SMS] OTP for mobile 9988776655 is: 482910
   ```
5. In another terminal, open `redis-cli` and check the key:
   ```bash
   TTL otp:9988776655
   # Returns ~295 (seconds remaining)
   GET otp:9988776655
   # Returns "482910"
   ```
6. **Force the key to expire immediately in `redis-cli`**:
   ```bash
   EXPIRE otp:9988776655 1
   ```
7. Wait 2 seconds and check the TTL again:
   ```bash
   TTL otp:9988776655
   # Returns -2 (key expired and automatically purged from memory by Redis)
   ```
8. In the browser, type `482910` and submit the verification form.
9. **Result**: The application rejects the submission with the flash error:
   > *"OTP expired. Please register again."*
   The session is cleared and the user is redirected back to `/register`.
10. Verify in `redis-cli` that no donor was created:
    ```bash
    SISMEMBER mobiles 9988776655
    # Returns 0 (mobile was never registered)
    ```

### Scenario B: 90-Day Donation Cooldown Lock
1. Go to `http://127.0.0.1:5000/admin`.
2. Find an **Available** donor (e.g., Donor #1) and click **Donated**.
3. Notice Donor #1's badge changes to <span style="color:red; font-weight:bold;">Unavailable (Cooldown)</span> and the **Donated** button becomes disabled.
4. Verify the lock in `redis-cli`:
   ```bash
   EXISTS unavailable:1
   # Returns 1 (key exists)
   TTL unavailable:1
   # Returns ~7775990 (seconds remaining out of 90 days)
   ```
5. If you manually delete or expire the lock:
   ```bash
   DEL unavailable:1
   ```
   Refresh `/admin` or `/search`: Donor #1 immediately returns to **Available** status!
