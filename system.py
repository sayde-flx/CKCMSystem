from flask import Flask, render_template, request, redirect, url_for, session, flash, abort
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import date, datetime
import csv
import io
import os
import re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "HTML"),
    static_folder=os.path.join(BASE_DIR, "static"),
)
app.secret_key = os.environ.get("SECRET_KEY", "ckcm-development-secret-key")
if app.secret_key == "ckcm-development-secret-key":
    print(
        "WARNING: SECRET_KEY env var is not set. Using an insecure default. "
        "Set SECRET_KEY in Railway's Variables tab before going live.",
        flush=True,
    )
if os.environ.get("ADMIN_PASSWORD") is None:
    print(
        "WARNING: ADMIN_PASSWORD env var is not set. Using an insecure default "
        "admin password. Set ADMIN_USERNAME and ADMIN_PASSWORD in Railway's "
        "Variables tab before going live.",
        flush=True,
    )

# Second, separate admin account. Credentials are intentionally visible here.
# The username must start with "admin_" so it is treated as an admin.
SECOND_ADMIN_USERNAME = "admin_ckcm"
SECOND_ADMIN_PASSWORD = "CKCM@dmin2026"

SPORTS = {
    "basketball": {
        "name": "Basketball",
        "positions": ["Point Guard", "Shooting Guard", "Small Forward", "Power Forward", "Center"],
    },
    "volleyball": {
        "name": "Volleyball",
        "positions": ["Setter", "Outside Hitter", "Opposite Hitter", "Middle Blocker", "Libero"],
    },
    "badminton": {
        "name": "Badminton",
        "positions": ["Singles", "Doubles", "Mixed Doubles"],
    },
    "takraw": {
        "name": "Takraw",
        "positions": ["Tekong", "Feeder", "Striker"],
    },
    "pickleball": {
        "name": "Pickleball",
        "positions": ["Singles", "Doubles", "Mixed Doubles"],
    },
}


def parse_positions(raw):
    """Turn a comma / new-line separated string into a clean, de-duplicated list."""
    seen, result = set(), []
    for part in (raw or "").replace(",", "\n").splitlines():
        name = part.strip()
        if name and name.lower() not in seen:
            seen.add(name.lower())
            result.append(name)
    return result


ROLES = ("student", "coach", "admin")

# Courses offered in the player forms: (code, full name).
# Edit this list to match the programs offered at CKCM. The code is what gets stored.
COURSES = [
    ("BSIT", "BS Information Technology"),
    ("BSCS", "BS Computer Science"),
    ("BSIS", "BS Information Systems"),
    ("BSBA", "BS Business Administration"),
    ("BSA", "BS Accountancy"),
    ("BSHM", "BS Hospitality Management"),
    ("BSTM", "BS Tourism Management"),
    ("BSN", "BS Nursing"),
    ("BSED", "BS Secondary Education"),
    ("BEED", "BS Elementary Education"),
    ("BSCRIM", "BS Criminology"),
    ("BSPSY", "BS Psychology"),
    ("BSCE", "BS Civil Engineering"),
]
COURSE_CODES = {code for code, _ in COURSES}
YEAR_LEVELS = ("1st Year", "2nd Year", "3rd Year", "4th Year")

HEIGHT_MIN_CM, HEIGHT_MAX_CM = 100, 250

# Personal details collected once, when the account is created.
PROFILE_FIELDS = ("first_name", "surname", "age", "gender", "course", "set_name", "year")


class BaseEntity:
    def __init__(self, entity_id):
        self.id = entity_id


class User(BaseEntity):
    def __init__(self, user_id, username, password, role="student"):
        super().__init__(user_id)
        self.username = username
        self.password_hash = generate_password_hash(password)
        self.role = role
        self.profile = None  # personal details dict (see PROFILE_FIELDS), set at registration

    def verify_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def has_full_profile(self):
        """True when the account has every student detail (coaches may only have a few)."""
        return bool(self.profile) and all(key in self.profile for key in PROFILE_FIELDS)


class CoachApplication(BaseEntity):
    """A coach sign-up waiting for admin approval. It is NOT an account until approved."""

    def __init__(self, application_id, username, password_hash, first_name, surname, age, gender):
        super().__init__(application_id)
        self.username = username
        self.password_hash = password_hash
        self.first_name = first_name
        self.surname = surname
        self.age = age
        self.gender = gender
        self.submitted = datetime.now()

    @property
    def full_name(self):
        return f"{self.first_name} {self.surname}"


class Player(BaseEntity):
    def __init__(self, player_id, first_name, surname, age, gender, course, set_name, year, sport, position, owner_id, height=None):
        super().__init__(player_id)
        self.first_name = first_name.strip()
        self.surname = surname.strip()
        self.age = int(age)
        self.height = int(height) if height not in (None, "") else None  # centimetres
        self.gender = gender
        self.course = course.strip()
        self.set_name = set_name.strip()
        self.year = year
        self.sport = sport
        self.position = position
        self.owner_id = owner_id

    @property
    def full_name(self):
        return f"{self.first_name} {self.surname}"


class Announcement(BaseEntity):
    def __init__(self, announcement_id, title, message, author):
        super().__init__(announcement_id)
        self.title = title.strip()
        self.message = message.strip()
        self.author = author
        self.reactions = {}

    @property
    def thumbs_up(self):
        return sum(value == "up" for value in self.reactions.values())

    @property
    def thumbs_down(self):
        return sum(value == "down" for value in self.reactions.values())


class CKCMSportsSystem:
    def __init__(self):
        self.users = []
        self.players = []
        self.announcements = []
        self.next_user_id = 1
        self.next_player_id = 1
        self.next_announcement_id = 1
        self.coach_applications = []
        self.next_application_id = 1
        self.last_submission_date = date(2027, 9, 30)
        self._create_admin()

    def _create_admin(self):
        self.add_user(
            os.environ.get("ADMIN_USERNAME", "admin_zaide"),
            os.environ.get("ADMIN_PASSWORD", "admin123"),
            "admin",
        )
        self.add_user(SECOND_ADMIN_USERNAME, SECOND_ADMIN_PASSWORD, "admin")

    def add_user(self, username, password, role="student", profile=None):
        username = (username or "").strip()
        if not username:
            raise ValueError("Username is required.")
        if any(user.username.lower() == username.lower() for user in self.users):
            raise ValueError("Username already exists.")
        if any(a.username.lower() == username.lower() for a in self.coach_applications):
            raise ValueError("That username is awaiting coach approval.")
        if len(password or "") < 6:
            raise ValueError("Password must be at least 6 characters.")
        # CKCM admin accounts use the explicit admin_ username convention.
        # This also makes newly registered admin_<name> accounts behave as admins.
        if role not in ROLES:
            role = "student"
        if username.lower().startswith("admin_"):
            role = "admin"
        cleaned = self._validate_profile(profile) if profile is not None else None
        user = User(self.next_user_id, username, password, role)
        user.profile = cleaned
        self.next_user_id += 1
        self.users.append(user)
        return user

    def apply_coach(self, username, password, first_name, surname, age, gender):
        """Store a coach application. No account is created until an admin approves it."""
        username = (username or "").strip()
        if not username:
            raise ValueError("Username is required.")
        if username.lower().startswith("admin_"):
            raise ValueError("That username is reserved. Please choose another.")
        if any(u.username.lower() == username.lower() for u in self.users) or any(
            a.username.lower() == username.lower() for a in self.coach_applications
        ):
            raise ValueError("Username already exists.")
        if len(password or "") < 6:
            raise ValueError("Password must be at least 6 characters.")
        first_name, surname = (first_name or "").strip(), (surname or "").strip()
        if not first_name or not surname or not str(age or "").strip() or not gender:
            raise ValueError("Please complete all fields.")
        try:
            age = int(age)
        except (TypeError, ValueError):
            raise ValueError("Age must be a number.")
        if age < 18 or age > 99:
            raise ValueError("Coaches must be between 18 and 99 years old.")
        if gender not in {"Male", "Female"}:
            raise ValueError("Select Male or Female.")
        application = CoachApplication(
            self.next_application_id, username, generate_password_hash(password), first_name, surname, age, gender
        )
        self.next_application_id += 1
        self.coach_applications.append(application)
        return application

    def get_application(self, application_id):
        return next((a for a in self.coach_applications if a.id == application_id), None)

    def pending_application(self, username, password):
        """The waiting application for these credentials, if any (used for a friendly login message)."""
        username = (username or "").strip().lower()
        return next(
            (a for a in self.coach_applications
             if a.username.lower() == username and check_password_hash(a.password_hash, password or "")),
            None,
        )

    def approve_coach(self, application_id):
        application = self.get_application(application_id)
        if not application:
            raise ValueError("Application not found.")
        if any(u.username.lower() == application.username.lower() for u in self.users):
            raise ValueError("Username already exists.")
        user = User(self.next_user_id, application.username, "placeholder", "coach")
        user.password_hash = application.password_hash
        user.profile = {
            "first_name": application.first_name, "surname": application.surname,
            "age": application.age, "gender": application.gender,
        }
        self.next_user_id += 1
        self.users.append(user)
        self.coach_applications.remove(application)
        return user

    def reject_coach(self, application_id):
        application = self.get_application(application_id)
        if not application:
            raise ValueError("Application not found.")
        self.coach_applications.remove(application)
        return application

    def authenticate(self, username, password):
        username = (username or "").strip()
        user = next((u for u in self.users if u.username.lower() == username.lower()), None)
        return user if user and user.verify_password(password or "") else None

    def get_user(self, user_id):
        return next((u for u in self.users if u.id == user_id), None)

    def get_player(self, player_id):
        return next((p for p in self.players if p.id == player_id), None)

    def players_for_owner(self, owner_id):
        """All player profiles (one per sport) registered by an account."""
        return [p for p in self.players if p.owner_id == owner_id]

    def player_for_owner(self, owner_id, sport=None):
        """First profile of an account, or the profile for a specific sport."""
        return next(
            (p for p in self.players if p.owner_id == owner_id and (sport is None or p.sport == sport)),
            None,
        )

    def add_player(self, owner_id, sport, position, height):
        """Register an account in a sport. Personal details come from the account itself."""
        owner = self.get_user(owner_id)
        if not owner or not owner.has_full_profile:
            raise ValueError("Please complete your account details first.")
        self._validate_player_fields(sport, position, height)
        if self.player_for_owner(owner_id, sport):
            raise ValueError("This account is already registered in that sport.")
        pr = owner.profile
        player = Player(
            self.next_player_id,
            pr["first_name"], pr["surname"], pr["age"], pr["gender"],
            pr["course"], pr["set_name"], pr["year"], sport,
            position, owner_id, height,
        )
        self.next_player_id += 1
        self.players.append(player)
        return player

    def set_profile(self, user_id, data, current_course=None):
        """Save an account's personal details and copy them onto all of its player entries."""
        user = self.get_user(user_id)
        if not user:
            raise ValueError("User not found.")
        cleaned = self._validate_profile(data, current_course=current_course)
        user.profile = cleaned
        for p in self.players_for_owner(user_id):
            p.first_name, p.surname, p.age = cleaned["first_name"], cleaned["surname"], cleaned["age"]
            p.gender, p.course, p.set_name, p.year = cleaned["gender"], cleaned["course"], cleaned["set_name"], cleaned["year"]
        return user

    def update_player(self, player_id, position, height, sport=None, profile=None):
        player = self.get_player(player_id)
        if not player:
            raise ValueError("Player not found.")
        sport = sport or player.sport
        self._validate_player_fields(sport, position, height)
        clash = self.player_for_owner(player.owner_id, sport)
        if clash and clash.id != player.id:
            raise ValueError("This account is already registered in that sport.")
        if profile is not None:
            self.set_profile(player.owner_id, profile, current_course=player.course)
        player.sport = sport
        player.position = position
        player.height = int(height)
        return player

    def delete_player(self, player_id):
        player = self.get_player(player_id)
        if not player:
            raise ValueError("Player not found.")
        self.players.remove(player)
        return player

    def delete_user(self, user_id):
        user = self.get_user(user_id)
        if not user:
            raise ValueError("User not found.")
        if user.username.lower() in (
            os.environ.get("ADMIN_USERNAME", "admin_zaide").lower(),
            SECOND_ADMIN_USERNAME.lower(),
        ):
            raise ValueError("The main admin account cannot be deleted.")
        self.users.remove(user)
        self.players[:] = [p for p in self.players if p.owner_id != user_id]
        return user

    def add_sport(self, name, positions_raw):
        name = " ".join((name or "").split())
        if not name:
            raise ValueError("Sport name is required.")
        if len(name) > 40:
            raise ValueError("Sport name is too long (40 characters max).")
        if any(info["name"].lower() == name.lower() for info in SPORTS.values()):
            raise ValueError("That sport already exists.")
        positions = parse_positions(positions_raw)
        if not positions:
            raise ValueError("Add at least one position (separate them with commas or new lines).")
        key = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        if not key:
            raise ValueError("Use letters or numbers in the sport name.")
        base, n = key, 2
        while key in SPORTS:
            key, n = f"{base}-{n}", n + 1
        SPORTS[key] = {"name": name, "positions": positions}
        return key

    def update_sport_positions(self, key, positions_raw):
        if key not in SPORTS:
            raise ValueError("Sport not found.")
        positions = parse_positions(positions_raw)
        if not positions:
            raise ValueError("A sport needs at least one position.")
        lowered = {p.lower() for p in positions}
        for player in self.players_for_sport(key):
            if player.position.lower() not in lowered:
                raise ValueError(
                    f"Cannot remove '{player.position}': {player.full_name} is registered with that position."
                )
        # Keep the exact stored spelling for positions already in use.
        SPORTS[key]["positions"] = positions

    def delete_sport(self, key):
        if key not in SPORTS:
            raise ValueError("Sport not found.")
        count = len(self.players_for_sport(key))
        if count:
            raise ValueError(f"Cannot remove {SPORTS[key]['name']}: {count} player(s) are registered. Move or remove them first.")
        if len(SPORTS) <= 1:
            raise ValueError("At least one sport must remain.")
        del SPORTS[key]

    def players_for_sport(self, sport):
        return sorted(
            [p for p in self.players if p.sport == sport],
            key=lambda p: (p.surname.lower(), p.first_name.lower()),
        )

    def add_announcement(self, title, message, author):
        if not (title or "").strip() or not (message or "").strip():
            raise ValueError("Title and message are required.")
        item = Announcement(self.next_announcement_id, title, message, author)
        self.next_announcement_id += 1
        self.announcements.insert(0, item)
        return item

    def react(self, announcement_id, user_id, reaction):
        if reaction not in {"up", "down"}:
            raise ValueError("Invalid reaction.")
        item = next((a for a in self.announcements if a.id == announcement_id), None)
        if not item:
            raise ValueError("Announcement not found.")
        if item.reactions.get(user_id) == reaction:
            del item.reactions[user_id]
        else:
            item.reactions[user_id] = reaction

    @staticmethod
    def _validate_profile(data, current_course=None):
        data = data or {}
        if any(not str(data.get(key, "")).strip() for key in PROFILE_FIELDS):
            raise ValueError("Please complete all fields.")
        try:
            age = int(data["age"])
        except (TypeError, ValueError):
            raise ValueError("Age must be a number.")
        if age < 10 or age > 99:
            raise ValueError("Age must be between 10 and 99.")
        course = str(data["course"]).strip()
        if course not in COURSE_CODES and course != current_course:
            raise ValueError("Select a course from the list.")
        if data["gender"] not in {"Male", "Female"}:
            raise ValueError("Select Male or Female.")
        if data["year"] not in YEAR_LEVELS:
            raise ValueError("Select a valid year.")
        return {
            "first_name": str(data["first_name"]).strip(),
            "surname": str(data["surname"]).strip(),
            "age": age,
            "gender": data["gender"],
            "course": course,
            "set_name": str(data["set_name"]).strip(),
            "year": data["year"],
        }

    @staticmethod
    def _validate_player_fields(sport, position, height):
        if not str(sport or "").strip() or not str(position or "").strip() or not str(height or "").strip():
            raise ValueError("Please complete all fields.")
        try:
            height = int(height)
        except (TypeError, ValueError):
            raise ValueError("Height must be a whole number in centimetres.")
        if height < HEIGHT_MIN_CM or height > HEIGHT_MAX_CM:
            raise ValueError(f"Height must be between {HEIGHT_MIN_CM} and {HEIGHT_MAX_CM} cm.")
        if sport not in SPORTS:
            raise ValueError("Select a valid sport.")
        if position not in SPORTS[sport]["positions"]:
            raise ValueError("Select a valid position.")


system = CKCMSportsSystem()


def current_user():
    user_id = session.get("user_id")
    return system.get_user(user_id) if user_id else None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            session.clear()
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def is_admin_user(user):
    return bool(user) and (user.role == "admin" or user.username.lower().startswith("admin_"))


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not is_admin_user(user):
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def is_coach_user(user):
    return bool(user) and user.role == "coach" and not is_admin_user(user)


def staff_required(view):
    """Admins and coaches (used for player management)."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not (is_admin_user(user) or is_coach_user(user)):
            abort(403)
        return view(*args, **kwargs)
    return wrapped


@app.context_processor
def inject_globals():
    user = current_user()
    return {
        "current_user": user,
        "sports": SPORTS,
        "courses": COURSES,
        "system_deadline": system.last_submission_date,
        "my_players": system.players_for_owner(user.id) if user else [],
        "my_player_ids": {p.id for p in system.players_for_owner(user.id)} if user else set(),
        "is_admin": is_admin_user(user),
        "is_coach": is_coach_user(user),
        "today": date.today(),
        "system": system,
    }


@app.route("/")
def index():
    return render_template("index.html")


def _profile_from_form():
    return {key: request.form.get(key, "") for key in PROFILE_FIELDS}


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user():
        return redirect(url_for("admin_dashboard" if is_admin_user(current_user()) else "student_home"))
    if request.method == "POST":
        try:
            if request.form.get("password", "") != request.form.get("confirm_password", ""):
                raise ValueError("Passwords do not match.")
            user = system.add_user(request.form.get("username", ""), request.form.get("password", ""), profile=_profile_from_form())
            session["user_id"] = user.id
            flash(f"Welcome to CKCM, {user.username}! Your account is ready.", "success")
            return redirect(url_for("admin_dashboard" if is_admin_user(user) else "student_home"))
        except ValueError as exc:
            flash(str(exc), "error")
    return render_template("register.html", form=request.form)


@app.route("/register/coach", methods=["GET", "POST"])
def register_coach():
    if current_user():
        return redirect(url_for("admin_dashboard" if is_admin_user(current_user()) else "student_home"))
    if request.method == "POST":
        try:
            if request.form.get("password", "") != request.form.get("confirm_password", ""):
                raise ValueError("Passwords do not match.")
            application = system.apply_coach(
                request.form.get("username", ""), request.form.get("password", ""),
                request.form.get("first_name", ""), request.form.get("surname", ""),
                request.form.get("age", ""), request.form.get("gender", ""),
            )
            flash(f"Thanks {application.first_name}! Your coach application was sent. You can sign in once an admin approves it.", "success")
            return redirect(url_for("login"))
        except ValueError as exc:
            flash(str(exc), "error")
    return render_template("register_coach.html", form=request.form)


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("admin_dashboard" if is_admin_user(current_user()) else "student_home"))
    if request.method == "POST":
        user = system.authenticate(request.form.get("username", ""), request.form.get("password", ""))
        if not user and system.pending_application(request.form.get("username", ""), request.form.get("password", "")):
            flash("Your coach application is still waiting for admin approval. You can sign in once it is approved.", "info")
        elif not user:
            flash("Invalid username or password.", "error")
        else:
            session["user_id"] = user.id
            flash(f"Welcome back, {user.username}!", "success")
            return redirect(url_for("admin_dashboard" if is_admin_user(user) else "student_home"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))


@app.route("/student")
@login_required
def student_home():
    if is_admin_user(current_user()):
        return redirect(url_for("admin_dashboard"))
    return render_template("student.html")


@app.route("/account/details", methods=["GET", "POST"])
@login_required
def account_details():
    """Edit the personal details saved on the account (name, age, course, ...)."""
    user = current_user()
    nxt = request.values.get("next", "")
    if not nxt.startswith("/") or nxt.startswith("//"):
        nxt = ""
    if request.method == "POST":
        try:
            system.set_profile(user.id, _profile_from_form(), current_course=(user.profile or {}).get("course"))
            flash("Your details were saved.", "success")
            return redirect(nxt or url_for("admin_dashboard" if is_admin_user(user) else "student_home"))
        except ValueError as exc:
            flash(str(exc), "error")
    return render_template("account_details.html", form=request.form if request.method == "POST" else (user.profile or {}), next=nxt)


@app.route("/profile")
@login_required
def profile():
    return render_template("profile.html")


@app.route("/settings")
@login_required
def settings():
    return render_template("settings.html")


@app.post("/settings/password")
@login_required
def change_password():
    user = current_user()
    current = request.form.get("current_password", "")
    new = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")
    if not user.verify_password(current):
        flash("Your current password is incorrect.", "error")
    elif len(new) < 6:
        flash("New password must be at least 6 characters.", "error")
    elif new != confirm:
        flash("New passwords do not match.", "error")
    elif new == current:
        flash("New password must be different from the current one.", "error")
    else:
        user.password_hash = generate_password_hash(new)
        flash("Password updated successfully.", "success")
    return redirect(url_for("settings") + "#security")


@app.post("/settings/delete-account")
@login_required
def delete_account():
    user = current_user()
    if is_admin_user(user):
        flash("Admin accounts can only be removed from Manage users.", "error")
        return redirect(url_for("settings"))
    if not user.verify_password(request.form.get("password", "")):
        flash("Password is incorrect. Your account was not deleted.", "error")
        return redirect(url_for("settings") + "#danger")
    system.delete_user(user.id)
    session.clear()
    flash("Your account and player profile have been deleted.", "success")
    return redirect(url_for("index"))


@app.route("/sports")
@login_required
def sports_home():
    return render_template("sports.html")


@app.route("/dashboard")
@login_required
@admin_required
def dashboard():
    return render_template("dashboard.html")


@app.post("/dashboard/delete-user")
@login_required
@admin_required
def dashboard_delete_user():
    try:
        user_id = int(request.form.get("user_id", "0"))
        if user_id == current_user().id:
            raise ValueError("You cannot delete your own account.")
        user = system.delete_user(user_id)
        flash(f"Account {user.username} was deleted.", "success")
    except (ValueError, TypeError) as exc:
        flash(str(exc), "error")
    return redirect(url_for("dashboard") + "#accounts")


@app.route("/player/new")
@login_required
def new_player_start():
    if is_admin_user(current_user()):
        return redirect(url_for("admin_players"))
    mine = {p.sport: p for p in system.players_for_owner(current_user().id)}
    return render_template("choose_sport.html", mine=mine)


@app.route("/player/new/<sport>", methods=["GET", "POST"])
@login_required
def new_player(sport):
    user = current_user()
    if is_admin_user(user):
        return redirect(url_for("admin_players"))
    if sport not in SPORTS:
        abort(404)
    existing = system.player_for_owner(user.id, sport)
    if existing:
        flash(f"You are already registered in {SPORTS[sport]['name']}. You can edit your details here.", "info")
        return redirect(url_for("edit_player", player_id=existing.id))
    if not user.has_full_profile:
        flash("Please complete your account details before joining a sport.", "info")
        return redirect(url_for("account_details", next=request.path))
    if request.method == "POST":
        try:
            if date.today() > system.last_submission_date:
                raise ValueError("The submission date has passed.")
            player = system.add_player(
                owner_id=user.id,
                sport=sport,
                position=request.form.get("position", ""),
                height=request.form.get("height", ""),
            )
            flash(f"Profile submitted! You're now on the {SPORTS[player.sport]['name']} roster.", "success")
            return redirect(url_for("sport_roster", sport=player.sport))
        except ValueError as exc:
            flash(str(exc), "error")
    return render_template("player_form.html", title="Player profile", sport=sport, info=SPORTS[sport])


@app.route("/player/me/edit", methods=["GET", "POST"])
@login_required
def edit_my_player():
    mine = system.players_for_owner(current_user().id)
    if len(mine) == 1:
        return edit_player(mine[0].id)
    return redirect(url_for("new_player_start"))


@app.route("/player/<int:player_id>/edit", methods=["GET", "POST"])
@login_required
def edit_player(player_id):
    player = system.get_player(player_id)
    if not player:
        abort(404)
    user = current_user()
    coach = is_coach_user(user)
    if not is_admin_user(user) and not coach and player.owner_id != user.id:
        abort(403)
    if request.method == "POST":
        try:
            staff = is_admin_user(user) or coach
            system.update_player(
                player_id,
                position=request.form.get("position", ""),
                height=request.form.get("height", ""),
                # Only admins can move a player to another sport.
                sport=request.form.get("sport") if is_admin_user(user) else None,
                # Only staff can edit a player's personal details here; players use "My details".
                profile=_profile_from_form() if staff else None,
            )
            flash("Player profile saved successfully.", "success")
            destination = url_for("admin_players") if (is_admin_user(user) or coach) else url_for("student_home")
            return redirect(destination)
        except ValueError as exc:
            flash(str(exc), "error")
    return render_template("edit_player.html", player=player, title="Edit player", info=SPORTS[player.sport])


@app.route("/sport/<sport>")
@login_required
def sport_roster(sport):
    if sport not in SPORTS:
        abort(404)
    rows = system.players_for_sport(sport)
    return render_template(
        "sport.html",
        sport=sport,
        info=SPORTS[sport],
        female=[p for p in rows if p.gender == "Female"],
        male=[p for p in rows if p.gender == "Male"],
    )


@app.route("/announcements")
@login_required
def announcements():
    return render_template("announcements.html", announcements=system.announcements)


@app.post("/announcement/<int:announcement_id>/react")
@login_required
def react_to_announcement(announcement_id):
    if is_admin_user(current_user()):
        return redirect(url_for("admin_announcements"))
    try:
        system.react(announcement_id, current_user().id, request.form.get("reaction", ""))
        flash("Thanks for your feedback!", "success")
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("announcements"))


@app.route("/admin")
@login_required
@admin_required
def admin_dashboard():
    return render_template("admin.html")


@app.route("/admin/users", methods=["GET", "POST"])
@login_required
@admin_required
def admin_users():
    form_values = {"username": "", "role": "student"}
    if request.method == "POST":
        action = request.form.get("action", "")
        try:
            if action == "add":
                if request.form.get("password", "") != request.form.get("confirm_password", ""):
                    raise ValueError("Passwords do not match.")
                new_user = system.add_user(
                    request.form.get("username", ""),
                    request.form.get("password", ""),
                    request.form.get("role", "student"),
                )
                flash(f"Account {new_user.username} added as {'Admin' if is_admin_user(new_user) else 'Student'}.", "success")
                return redirect(url_for("admin_users"))
            elif action == "approve_coach":
                user = system.approve_coach(int(request.form.get("application_id", "0")))
                flash(f"{user.username} was approved as a coach and can now sign in.", "success")
                return redirect(url_for("admin_users"))
            elif action == "reject_coach":
                application = system.reject_coach(int(request.form.get("application_id", "0")))
                flash(f"The coach application from {application.username} was rejected.", "success")
                return redirect(url_for("admin_users"))
            elif action == "role":
                user = system.get_user(int(request.form.get("user_id", "0")))
                if not user:
                    raise ValueError("User not found.")
                if user.id == current_user().id:
                    raise ValueError("You cannot change your own role here.")
                new_role = request.form.get("role", "student")
                if user.username.lower().startswith("admin_"):
                    new_role = "admin"
                elif new_role not in ROLES:
                    new_role = "student"
                user.role = new_role
                flash("User role updated.", "success")
            elif action == "delete":
                user_id = int(request.form.get("user_id", "0"))
                if user_id == current_user().id:
                    raise ValueError("You cannot delete your own account.")
                system.delete_user(user_id)
                flash("User account removed.", "success")
        except (ValueError, TypeError) as exc:
            flash(str(exc), "error")
            if action == "add":
                form_values = {"username": request.form.get("username", ""), "role": request.form.get("role", "student")}
    return render_template("admin_users.html", users=system.users, form_values=form_values)


@app.route("/admin/sports", methods=["GET", "POST"])
@login_required
@admin_required
def admin_sports():
    if request.method == "POST":
        action = request.form.get("action", "")
        try:
            if action == "add":
                key = system.add_sport(request.form.get("name", ""), request.form.get("positions", ""))
                flash(f"{SPORTS[key]['name']} was added.", "success")
            elif action == "positions":
                system.update_sport_positions(request.form.get("sport", ""), request.form.get("positions", ""))
                flash("Positions updated.", "success")
            elif action == "delete":
                name = SPORTS.get(request.form.get("sport", ""), {}).get("name", "Sport")
                system.delete_sport(request.form.get("sport", ""))
                flash(f"{name} was removed.", "success")
        except ValueError as exc:
            flash(str(exc), "error")
        return redirect(url_for("admin_sports"))
    return render_template("admin_sports.html")


@app.route("/admin/players")
@login_required
@staff_required
def admin_players():
    players = sorted(system.players, key=lambda p: (p.surname.lower(), p.first_name.lower()))
    return render_template("admin_players.html", players=players)


REPORT_COLUMNS = ["No.", "First Name", "Surname", "Age", "Height (cm)", "Course / Year", "Set", "Position", "Owner Username"]


def _report_groups():
    """Players grouped as {sport: {department: {gender: [players]}}}.

    Department is the player's course. Everything is sorted so the export
    is stable: sport order, then department A-Z, then Female before Male.
    """
    groups = {}
    for key in SPORTS:
        rows = system.players_for_sport(key)
        by_dept = {}
        for p in rows:
            dept = p.course.strip().upper() or "UNSPECIFIED"
            by_dept.setdefault(dept, {"Female": [], "Male": []})[p.gender].append(p)
        groups[key] = dict(sorted(by_dept.items()))
    return groups


def _report_row(index, p):
    owner = system.get_user(p.owner_id)
    return [index, p.first_name, p.surname, p.age, p.height if p.height else "", f"{p.course} - {p.year}", p.set_name, p.position,
            owner.username if owner else ""]


@app.route("/admin/reports/export")
@login_required
@admin_required
def export_player_report():
    """Excel report: one sheet per sport, split by department, then Female / Male."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    title_font = Font(bold=True, size=14, color="FFFFFF")
    title_fill = PatternFill("solid", fgColor="EA580C")
    dept_font = Font(bold=True, size=12)
    dept_fill = PatternFill("solid", fgColor="FFEDD5")
    gender_font = Font(bold=True, color="C2410C")
    head_font = Font(bold=True)
    head_fill = PatternFill("solid", fgColor="F3F4F6")

    wb = Workbook()
    wb.remove(wb.active)
    summary = wb.create_sheet("Summary")
    summary.append(["Sport", "Female", "Male", "Total"])
    for c in summary[1]:
        c.font = head_font
        c.fill = head_fill

    groups = _report_groups()
    grand_f = grand_m = 0
    for key, depts in groups.items():
        info = SPORTS[key]
        ws = wb.create_sheet(info["name"])
        ws.append([f"{info['name']} - Player Report"])
        ws["A1"].font = title_font
        ws["A1"].fill = title_fill
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(REPORT_COLUMNS))
        ws.append([])
        total_f = total_m = 0
        if not depts:
            ws.append(["No players registered yet."])
        for dept, genders in depts.items():
            ws.append([f"Department: {dept}"])
            r = ws.max_row
            for c in ws[r][:len(REPORT_COLUMNS)]:
                c.fill = dept_fill
                c.font = dept_font
            for gender in ("Female", "Male"):
                rows = genders[gender]
                ws.append([f"{gender} ({len(rows)})"])
                ws.cell(ws.max_row, 1).font = gender_font
                ws.append(REPORT_COLUMNS)
                for c in ws[ws.max_row][:len(REPORT_COLUMNS)]:
                    c.font = head_font
                    c.fill = head_fill
                if rows:
                    for i, p in enumerate(rows, 1):
                        ws.append(_report_row(i, p))
                else:
                    ws.append(["", "No players"])
                ws.append([])
            total_f += len(genders["Female"])
            total_m += len(genders["Male"])
        for col, width in zip("ABCDEFGHI", (6, 16, 18, 7, 12, 24, 10, 18, 20)):
            ws.column_dimensions[col].width = width
        ws.column_dimensions["A"].alignment = Alignment(horizontal="left")
        summary.append([info["name"], total_f, total_m, total_f + total_m])
        grand_f += total_f
        grand_m += total_m
    summary.append(["All sports", grand_f, grand_m, grand_f + grand_m])
    for c in summary[summary.max_row]:
        c.font = head_font
    summary.column_dimensions["A"].width = 20

    buffer = io.BytesIO()
    wb.save(buffer)
    response = app.response_class(
        buffer.getvalue(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response.headers["Content-Disposition"] = "attachment; filename=ckcm_player_report.xlsx"
    return response


@app.route("/admin/reports/export.csv")
@login_required
@admin_required
def export_player_report_csv():
    """CSV version: same split (sport > department > Female/Male) with section rows."""
    output = io.StringIO()
    writer = csv.writer(output)
    for key, depts in _report_groups().items():
        for dept, genders in depts.items():
            for gender in ("Female", "Male"):
                rows = genders[gender]
                if not rows:
                    continue
                writer.writerow([f"{SPORTS[key]['name']} | Department: {dept} | {gender} ({len(rows)})"])
                writer.writerow(REPORT_COLUMNS)
                for i, p in enumerate(rows, 1):
                    writer.writerow(_report_row(i, p))
                writer.writerow([])
    response = app.response_class(output.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=ckcm_player_report.csv"
    return response


@app.route("/admin/deadline", methods=["GET", "POST"])
@login_required
@admin_required
def admin_deadline():
    if request.method == "POST":
        try:
            system.last_submission_date = date.fromisoformat(request.form.get("submission_date", ""))
        except ValueError:
            flash("Select a valid date.", "error")
        else:
            return redirect(url_for("admin_deadline"))
    return render_template("admin_deadline.html")


@app.route("/admin/announcements", methods=["GET", "POST"])
@login_required
@admin_required
def admin_announcements():
    if request.method == "POST":
        try:
            system.add_announcement(
                request.form.get("title", ""),
                request.form.get("message", ""),
                current_user().username,
            )
            return redirect(url_for("admin_announcements"))
        except ValueError as exc:
            flash(str(exc), "error")
    return render_template("admin_announcements.html", announcements=system.announcements)


@app.post("/admin/player/<int:player_id>/delete")
@login_required
@staff_required
def delete_player(player_id):
    try:
        system.delete_player(player_id)
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin_players"))


@app.errorhandler(403)
def forbidden(_):
    return render_template("message.html", title="Access restricted", message="You do not have permission to open this page."), 403


@app.errorhandler(404)
def not_found(_):
    return render_template("message.html", title="Page not found", message="The page does not exist."), 404


if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=debug_mode)
