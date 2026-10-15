"""
app.py
Flask routing and form validation layer for Blood Donor Locator.
Contains NO direct Redis calls; all persistence is delegated to redis_client.py.
Handles session management, HTTP error codes, and flash messaging.
"""

import random
import re
from flask import Flask, flash, redirect, render_template, request, session, url_for
import redis.exceptions

import redis_client
from redis_client import BLOOD_GROUPS, CITIES

app = Flask(__name__)
app.secret_key = "blood_donor_locator_secret_key_secure_session"

# Validation Regex patterns
NAME_REGEX = re.compile(r"^[A-Za-z .]{2,50}$")
MOBILE_REGEX = re.compile(r"^[0-9]{10}$")


def validate_donor_form(form, check_mobile_unique=True):
    """Server-side validation for donor registration and update forms."""
    errors = {}
    name = form.get("name", "").strip()
    age_raw = form.get("age", "").strip()
    group = form.get("group", "").strip()
    city = form.get("city", "").strip()
    mobile = form.get("mobile", "").strip()

    # Name validation
    if not name or not NAME_REGEX.match(name):
        errors["name"] = "Name must be 2 to 50 characters long and contain only letters, dots, or spaces."

    # Age validation (18-60)
    try:
        age = int(age_raw)
        if age < 18 or age > 60:
            errors["age"] = "Age must be between 18 and 60 years."
    except (ValueError, TypeError):
        errors["age"] = "Age must be a valid integer between 18 and 60."

    # Blood group validation
    if group not in BLOOD_GROUPS:
        errors["group"] = f"Select a valid blood group from: {', '.join(BLOOD_GROUPS)}."

    # City validation
    if city not in CITIES:
        errors["city"] = f"Select a valid city from: {', '.join(CITIES)}."

    # Mobile validation (only for new registration)
    if check_mobile_unique:
        if not mobile or not MOBILE_REGEX.match(mobile):
            errors["mobile"] = "Mobile number must be exactly 10 digits."
        elif redis_client.mobile_exists(mobile):
            errors["mobile"] = "This mobile number is already registered with an existing donor."

    return errors


@app.route("/")
def index():
    """Home page with three primary Bootstrap navigation cards."""
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Donor registration route with client and server-side validation + OTP simulation."""
    if request.method == "POST":
        errors = validate_donor_form(request.form, check_mobile_unique=True)
        if errors:
            flash("Please correct the errors in the registration form.", "danger")
            return (
                render_template(
                    "register.html",
                    blood_groups=BLOOD_GROUPS,
                    cities=CITIES,
                    form_data=request.form,
                    errors=errors,
                ),
                400,
            )

        # Generate 6-digit numeric OTP
        mobile = request.form["mobile"].strip()
        otp = f"{random.randint(100000, 999999):06d}"

        # Store OTP with 300s TTL in Redis
        redis_client.store_otp(mobile, otp)

        # Retain validated form data in Flask session pending verification
        session["pending_donor"] = {
            "name": request.form["name"].strip(),
            "age": int(request.form["age"].strip()),
            "group": request.form["group"].strip(),
            "city": request.form["city"].strip(),
            "mobile": mobile,
        }

        # Simulated SMS output to server console
        print("\n" + "=" * 50, flush=True)
        print(f"[SIMULATED SMS] OTP for mobile {mobile} is: {otp}", flush=True)
        print("=" * 50 + "\n", flush=True)

        flash(
            f"OTP sent to {mobile}. Please enter the 6-digit verification code.",
            "info",
        )
        return redirect(url_for("verify"))

    return render_template(
        "register.html",
        blood_groups=BLOOD_GROUPS,
        cities=CITIES,
        form_data={},
        errors={},
    )


@app.route("/verify", methods=["GET", "POST"])
def verify():
    """Verify 6-digit OTP with live TTL countdown and single-use enforcement."""
    pending = session.get("pending_donor")
    if not pending:
        flash("No pending registration found. Please register first.", "warning")
        return redirect(url_for("register"))

    mobile = pending["mobile"]

    if request.method == "POST":
        entered_otp = request.form.get("otp", "").strip()
        result = redis_client.verify_otp(mobile, entered_otp)

        if result == "ok":
            donor_id = redis_client.create_donor(pending)
            session.pop("pending_donor", None)
            flash(
                f"Registration successful! Your Donor ID is #{donor_id}.",
                "success",
            )
            return redirect(url_for("search"))
        elif result == "expired":
            session.pop("pending_donor", None)
            flash("OTP expired. Please register again.", "danger")
            return redirect(url_for("register"))
        else:  # mismatch
            flash("Invalid OTP entered. Please try again.", "danger")
            ttl = redis_client.get_otp_ttl(mobile)
            return (
                render_template("verify.html", mobile=mobile, ttl=max(0, ttl)),
                400,
            )

    ttl = redis_client.get_otp_ttl(mobile)
    if ttl <= 0:
        session.pop("pending_donor", None)
        flash("OTP expired. Please register again.", "danger")
        return redirect(url_for("register"))

    return render_template("verify.html", mobile=mobile, ttl=ttl)


@app.route("/search", methods=["GET", "POST"])
def search():
    """Query donors by blood group and city using Redis Set index."""
    if request.method == "POST":
        group = request.form.get("group", "").strip()
        city = request.form.get("city", "").strip()

        if group not in BLOOD_GROUPS or city not in CITIES:
            flash("Please select a valid blood group and city to search.", "warning")
            return redirect(url_for("search"))

        donors, search_key = redis_client.search_donors(group, city)
        return render_template(
            "results.html",
            donors=donors,
            search_key=search_key,
            group=group,
            city=city,
        )

    return render_template(
        "search.html",
        blood_groups=BLOOD_GROUPS,
        cities=CITIES,
    )


@app.route("/update/<donor_id>", methods=["GET", "POST"])
def update(donor_id):
    """Update donor profile with manual secondary index maintenance in Redis."""
    donor = redis_client.get_donor(donor_id)
    if not donor:
        flash(f"Donor #{donor_id} not found.", "danger")
        return redirect(url_for("admin"))

    if request.method == "POST":
        errors = validate_donor_form(request.form, check_mobile_unique=False)
        if errors:
            flash("Please correct the errors in the update form.", "danger")
            # Preserve existing mobile since it is immutable
            temp_donor = dict(request.form)
            temp_donor["id"] = donor_id
            temp_donor["mobile"] = donor["mobile"]
            return (
                render_template(
                    "update.html",
                    donor=temp_donor,
                    blood_groups=BLOOD_GROUPS,
                    cities=CITIES,
                    errors=errors,
                ),
                400,
            )

        redis_client.update_donor(donor_id, request.form)
        flash(f"Donor #{donor_id} profile updated successfully.", "success")
        return redirect(url_for("admin"))

    return render_template(
        "update.html",
        donor=donor,
        blood_groups=BLOOD_GROUPS,
        cities=CITIES,
        errors={},
    )


@app.route("/delete/<donor_id>", methods=["POST"])
def delete(donor_id):
    """Delete donor profile, clearing Hash, Set indexes, mobile, and TTL lock."""
    redis_client.delete_donor(donor_id)
    flash(f"Donor #{donor_id} deleted successfully.", "success")
    return redirect(url_for("admin"))


@app.route("/donate/<donor_id>", methods=["POST"])
def donate(donor_id):
    """Record donation date and set 90-day auto-expiring eligibility lock."""
    donor = redis_client.get_donor(donor_id)
    if not donor:
        flash(f"Donor #{donor_id} not found.", "danger")
        return redirect(url_for("admin"))

    if not donor.get("eligible", True):
        flash(
            f"Donor #{donor_id} has recently donated and is currently in the 90-day cooldown period.",
            "warning",
        )
        return redirect(url_for("admin"))

    redis_client.mark_unavailable(donor_id)
    flash(
        f"Donation recorded for Donor #{donor_id}! Donor marked unavailable for 90 days.",
        "success",
    )
    return redirect(url_for("admin"))


@app.route("/admin")
def admin():
    """Administrative dashboard displaying key metrics, blood group progress bars, and donor roster."""
    stats = redis_client.get_stats()
    donors = redis_client.get_all_donors()
    return render_template("admin.html", stats=stats, donors=donors)


@app.errorhandler(redis.exceptions.ConnectionError)
def handle_redis_connection_error(error):
    """Handle unreachable Redis connection gracefully with 503 error page."""
    return (
        render_template(
            "error.html",
            error_message="Cannot connect to Redis on localhost:6379",
            start_command="redis-server",
        ),
        503,
    )


if __name__ == "__main__":
    # Host on 127.0.0.1:5000 as specified
    app.run(host="127.0.0.1", port=5000, debug=True)
