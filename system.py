from flask import Flask, render_template, request, redirect, url_for, session, flash, abort
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import date
import csv
import io
import os

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


class BaseEntity:
    def __init__(self, entity_id):
        self.id = entity_id


class User(BaseEntity):
    def __init__(self, user_id, username, password, role="student"):
        super().__init__(user_id)
        self.username = username
        self.password_hash = generate_password_hash(password)
        self.role = role

    def verify_password(self, password):
        return check_password_hash(self.password_hash, password)


class Player(BaseEntity):
    def __init__(self, player_id, first_name, surname, age, gender, course, set_name, year, sport, position, owner_id):
        super().__init__(player_id)
        self.first_name = first_name.strip()
        self.surname = surname.strip()
        self.age = int(age)
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
        self.last_submission_date = date(2026, 9, 30)
        self._create_admin()

    def _create_admin(self):
        self.add_user(
            os.environ.get("ADMIN_USERNAME", "admin_zaide"),
            os.environ.get("ADMIN_PASSWORD", "admin123"),
            "admin",
        )

    def add_user(self, username, password, role="student"):
        username = (username or "").strip()
        if not username:
            raise ValueError("Username is required.")
        if any(user.username.lower() == username.lower() for user in self.users):
            raise ValueError("Username already exists.")
        if len(password or "") < 6:
            raise ValueError("Password must be at least 6 characters.")
        # CKCM admin accounts use the explicit admin_ username convention.
        # This also makes newly registered admin_<name> accounts behave as admins.
        if username.lower().startswith("admin_"):
            role = "admin"
        user = User(self.next_user_id, username, password, role)
        self.next_user_id += 1
        self.users.append(user)
        return user

    def authenticate(self, username, password):
        username = (username or "").strip()
        user = next((u for u in self.users if u.username.lower() == username.lower()), None)
        return user if user and user.verify_password(password or "") else None

    def get_user(self, user_id):
        return next((u for u in self.users if u.id == user_id), None)

    def get_player(self, player_id):
        return next((p for p in self.players if p.id == player_id), None)

    def player_for_owner(self, owner_id):
        return next((p for p in self.players if p.owner_id == owner_id), None)

    def add_player(self, **data):
        owner_id = data["owner_id"]
        if self.player_for_owner(owner_id):
            raise ValueError("This account already has a player profile.")
        self._validate_player(data)
        player = Player(
            self.next_player_id,
            data["first_name"], data["surname"], data["age"], data["gender"],
            data["course"], data["set_name"], data["year"], data["sport"],
            data["position"], owner_id,
        )
        self.next_player_id += 1
        self.players.append(player)
        return player

    def update_player(self, player_id, **data):
        player = self.get_player(player_id)
        if not player:
            raise ValueError("Player not found.")
        self._validate_player(data)
        player.first_name = data["first_name"].strip()
        player.surname = data["surname"].strip()
        player.age = int(data["age"])
        player.gender = data["gender"]
        player.course = data["course"].strip()
        player.set_name = data["set_name"].strip()
        player.year = data["year"]
        player.sport = data["sport"]
        player.position = data["position"]
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
        if user.username.lower() == os.environ.get("ADMIN_USERNAME", "admin_zaide").lower():
            raise ValueError("The main admin account cannot be deleted.")
        self.users.remove(user)
        self.players[:] = [p for p in self.players if p.owner_id != user_id]
        return user

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
    def _validate_player(data):
        required = ["first_name", "surname", "age", "gender", "course", "set_name", "year", "sport", "position"]
        if any(not str(data.get(key, "")).strip() for key in required):
            raise ValueError("Please complete all fields.")
        try:
            age = int(data["age"])
        except (TypeError, ValueError):
            raise ValueError("Age must be a number.")
        if age < 10 or age > 99:
            raise ValueError("Age must be between 10 and 99.")
        if data["gender"] not in {"Male", "Female"}:
            raise ValueError("Select Male or Female.")
        if data["sport"] not in SPORTS:
            raise ValueError("Select a valid sport.")
        if data["position"] not in SPORTS[data["sport"]]["positions"]:
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


@app.context_processor
def inject_globals():
    user = current_user()
    return {
        "current_user": user,
        "sports": SPORTS,
        "system_deadline": system.last_submission_date,
        "my_player": system.player_for_owner(user.id) if user else None,
        "is_admin": is_admin_user(user),
        "today": date.today(),
        "system": system,
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user():
        return redirect(url_for("admin_dashboard" if is_admin_user(current_user()) else "student_home"))
    if request.method == "POST":
        try:
            if request.form.get("password", "") != request.form.get("confirm_password", ""):
                raise ValueError("Passwords do not match.")
            user = system.add_user(request.form.get("username", ""), request.form.get("password", ""))
            session["user_id"] = user.id
            return redirect(url_for("student_home"))
        except ValueError as exc:
            flash(str(exc), "error")
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("admin_dashboard" if is_admin_user(current_user()) else "student_home"))
    if request.method == "POST":
        user = system.authenticate(request.form.get("username", ""), request.form.get("password", ""))
        if not user:
            flash("Invalid username or password.", "error")
        else:
            session["user_id"] = user.id
            return redirect(url_for("admin_dashboard" if is_admin_user(user) else "student_home"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/student")
@login_required
def student_home():
    if is_admin_user(current_user()):
        return redirect(url_for("admin_dashboard"))
    return render_template("student.html")


@app.route("/settings")
@login_required
def settings():
    return render_template("settings.html")


@app.route("/sports")
@login_required
def sports_home():
    return render_template("sports.html")


@app.route("/dashboard")
@login_required
@admin_required
def dashboard():
    return render_template("dashboard.html")


@app.route("/player/new")
@login_required
def new_player_start():
    if is_admin_user(current_user()):
        return redirect(url_for("admin_players"))
    if system.player_for_owner(current_user().id):
        return redirect(url_for("edit_my_player"))
    return render_template("choose_sport.html")


@app.route("/player/new/<sport>", methods=["GET", "POST"])
@login_required
def new_player(sport):
    user = current_user()
    if is_admin_user(user):
        return redirect(url_for("admin_players"))
    if sport not in SPORTS:
        abort(404)
    if system.player_for_owner(user.id):
        return redirect(url_for("edit_my_player"))
    if request.method == "POST":
        try:
            if date.today() > system.last_submission_date:
                raise ValueError("The submission date has passed.")
            player = system.add_player(
                first_name=request.form.get("first_name", ""),
                surname=request.form.get("surname", ""),
                age=request.form.get("age", ""),
                gender=request.form.get("gender", ""),
                course=request.form.get("course", ""),
                set_name=request.form.get("set_name", ""),
                year=request.form.get("year", ""),
                sport=sport,
                position=request.form.get("position", ""),
                owner_id=user.id,
            )
            return redirect(url_for("sport_roster", sport=player.sport))
        except ValueError as exc:
            flash(str(exc), "error")
    return render_template("player_form.html", player=None, title="Player profile", sport=sport, info=SPORTS[sport])


@app.route("/player/me/edit", methods=["GET", "POST"])
@login_required
def edit_my_player():
    player = system.player_for_owner(current_user().id)
    if not player:
        return redirect(url_for("new_player_start"))
    return edit_player(player.id)


@app.route("/player/<int:player_id>/edit", methods=["GET", "POST"])
@login_required
def edit_player(player_id):
    player = system.get_player(player_id)
    if not player:
        abort(404)
    user = current_user()
    if not is_admin_user(user) and player.owner_id != user.id:
        abort(403)
    if request.method == "POST":
        try:
            system.update_player(
                player_id,
                first_name=request.form.get("first_name", ""),
                surname=request.form.get("surname", ""),
                age=request.form.get("age", ""),
                gender=request.form.get("gender", ""),
                course=request.form.get("course", ""),
                set_name=request.form.get("set_name", ""),
                year=request.form.get("year", ""),
                sport=request.form.get("sport", ""),
                position=request.form.get("position", ""),
            )
            destination = url_for("admin_players") if is_admin_user(user) else url_for("student_home")
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
    if request.method == "POST":
        action = request.form.get("action", "")
        try:
            if action == "add":
                system.add_user(
                    request.form.get("username", ""),
                    request.form.get("password", ""),
                    request.form.get("role", "student"),
                )
                flash("User account added.", "success")
            elif action == "role":
                user = system.get_user(int(request.form.get("user_id", "0")))
                if not user:
                    raise ValueError("User not found.")
                if user.id == current_user().id:
                    raise ValueError("You cannot change your own role here.")
                user.role = "admin" if request.form.get("role") == "admin" or user.username.lower().startswith("admin_") else "student"
                flash("User role updated.", "success")
            elif action == "delete":
                user_id = int(request.form.get("user_id", "0"))
                if user_id == current_user().id:
                    raise ValueError("You cannot delete your own account.")
                system.delete_user(user_id)
                flash("User account removed.", "success")
        except (ValueError, TypeError) as exc:
            flash(str(exc), "error")
    return render_template("admin_users.html", users=system.users)


@app.route("/admin/players")
@login_required
@admin_required
def admin_players():
    players = sorted(system.players, key=lambda p: (p.surname.lower(), p.first_name.lower()))
    return render_template("admin_players.html", players=players)


@app.route("/admin/reports/export")
@login_required
@admin_required
def export_player_report():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["First Name", "Surname", "Age", "Gender", "Course", "Set", "Year", "Sport", "Position", "Owner Username"])
    for player in sorted(system.players, key=lambda p: (p.surname.lower(), p.first_name.lower())):
        owner = system.get_user(player.owner_id)
        writer.writerow([
            player.first_name, player.surname, player.age, player.gender, player.course,
            player.set_name, player.year, SPORTS[player.sport]["name"], player.position,
            owner.username if owner else "",
        ])
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
@admin_required
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
