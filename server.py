"""Authoritative two-device game rooms. No personal data or external services."""
import hashlib
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from collections import defaultdict, deque
from contextlib import closing, contextmanager
from pathlib import Path

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

app = Flask(__name__, static_folder="public", static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = 4096
DB = Path(os.environ.get("GAME_DB", str(Path(__file__).with_name("rooms.sqlite3"))))
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
LINES = ((0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6),
         (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6))
TTL = 24 * 60 * 60
rate_lock = threading.Lock()
attempts = defaultdict(deque)


def fail(message, status=400):
    response = jsonify(error=message)
    response.status_code = status
    return response


@app.after_request
def headers(response):
    response.headers["Cache-Control"] = "no-store"
    # The public frontend calls this API on the same origin. No wildcard CORS.
    # Rooms still require their own unguessable player token.
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.before_request
def cors_preflight():
    if request.method == "OPTIONS":
        return "", 204
    if request.method == "POST" and not request.is_json:
        return fail("Päring peab kasutama JSON-vormingut.", 415)


@app.errorhandler(HTTPException)
def http_error(error):
    return fail("Vigane päring. Proovi uuesti.", error.code)


def budget(key, maximum, period):
    now = time.time()
    with rate_lock:
        if len(attempts) > 5000:
            for old in list(attempts):
                if not attempts[old] or attempts[old][-1] < now - 600:
                    del attempts[old]
        entries = attempts[key]
        while entries and entries[0] < now - period:
            entries.popleft()
        if len(entries) >= maximum:
            return True
        entries.append(now)
    return False


def limited():
    # Never trust client-supplied X-Visitor-Id/X-Forwarded-For as a quota key.
    # Behind a proxy multiple users may share one network quota; the independent
    # server-wide cap remains effective even when socket peers differ.
    peer = hashlib.sha256((request.remote_addr or "unknown").encode()).hexdigest()
    return budget("room-global", 300, 600) or budget("room-peer:" + peer, 100, 600)


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


@contextmanager
def transaction():
    connection = sqlite3.connect(DB, timeout=10)
    try:
        connection.execute("BEGIN IMMEDIATE")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


with sqlite3.connect(DB) as connection:
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS rooms (code TEXT PRIMARY KEY, data TEXT NOT NULL, expires REAL NOT NULL)"
    )


def load(connection, code):
    if not re.fullmatch(r"[A-Z2-9]{6}", code):
        return None
    row = connection.execute(
        "SELECT data FROM rooms WHERE code=? AND expires>?", (code, time.time())
    ).fetchone()
    return json.loads(row[0]) if row else None


def save(connection, code, room):
    connection.execute(
        "UPDATE rooms SET data=? WHERE code=?", (json.dumps(room), code)
    )


def player(room):
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    if not token or len(token) > 256:
        return None
    digest = token_hash(token)
    for mark in ("X", "O"):
        stored = room["tokens"][mark]
        if stored and secrets.compare_digest(stored, digest):
            return mark
    return None


def view(code, room, mark):
    other = "O" if mark == "X" else "X"
    return dict(
        code=code, you=mark, board=room["board"], turn=room["turn"],
        joined=room["tokens"]["O"] is not None, winner=room["winner"],
        winLine=room["winLine"], finished=room["finished"],
        scores=room["scores"], round=room["round"], version=room["version"],
        restartVotes=room["restartVotes"], left=room["left"],
        opponentOnline=room["seen"][other] > time.time() - 20,
        expiresAt=room["expires"],
    )


@app.get("/api/health")
def health():
    return jsonify(ok=True)


@app.get("/")
def index():
    return app.send_static_file("index.html")


@app.post("/api/rooms")
def create_room():
    if limited():
        return fail("Liiga palju katseid. Proovi mõne minuti pärast.", 429)
    token = secrets.token_urlsafe(32)
    now = time.time()
    with transaction() as connection:
        connection.execute("DELETE FROM rooms WHERE expires<=?", (now,))
        if connection.execute("SELECT count(*) FROM rooms").fetchone()[0] >= 2000:
            return fail("Mängutoad on hetkel täis. Proovi hiljem.", 429)
        while True:
            code = "".join(secrets.choice(ALPHABET) for _ in range(6))
            if not connection.execute("SELECT 1 FROM rooms WHERE code=?", (code,)).fetchone():
                break
        room = dict(
            tokens={"X": token_hash(token), "O": None}, board=[None] * 9,
            turn="X", winner=None, winLine=[], finished=False,
            scores={"X": 0, "O": 0, "D": 0}, round=1, version=1,
            restartVotes=[], left=None, seen={"X": now, "O": 0}, expires=now + TTL,
        )
        connection.execute(
            "INSERT INTO rooms VALUES(?,?,?)", (code, json.dumps(room), room["expires"])
        )
    return jsonify(token=token, state=view(code, room, "X")), 201


@app.post("/api/rooms/<code>/join")
def join_room(code):
    if limited():
        return fail("Liiga palju katseid. Kontrolli toakoodi ja proovi hiljem.", 429)
    token = secrets.token_urlsafe(32)
    with transaction() as connection:
        room = load(connection, code)
        if not room:
            return fail("Sellist tuba ei leitud või see on aegunud.", 404)
        if room["left"]:
            return fail("See tuba on suletud. Loo uus mängutuba.", 410)
        if room["tokens"]["O"]:
            return fail("Selles toas on juba kaks mängijat.", 409)
        room["tokens"]["O"] = token_hash(token)
        room["seen"]["O"] = time.time()
        room["version"] += 1
        save(connection, code, room)
    return jsonify(token=token, state=view(code, room, "O"))


@app.route("/api/rooms/<code>", methods=["GET", "POST"])
def room_request(code):
    # Polling is a read transaction. Presence is refreshed at most once every
    # eight seconds per player, not on every near-secondly poll.
    with closing(sqlite3.connect(DB, timeout=10)) as connection:
        room = load(connection, code)
    if not room:
        return fail("Mängutuba on aegunud või seda ei leitud.", 404)
    mark = player(room)
    if not mark:
        return fail("Mängutuppa pääsemiseks on vaja mängija luba.", 403)
    digest = room["tokens"][mark]
    if budget("player:" + digest, 180, 60) or budget("game-global", 6000, 60):
        return fail("Liiga palju päringuid. Oota hetk ja proovi uuesti.", 429)
    if request.method == "GET" and room["seen"][mark] > time.time() - 8:
        return jsonify(state=view(code, room, mark))
    with transaction() as connection:
        room = load(connection, code)
        if not room:
            return fail("Mängutuba on aegunud või seda ei leitud.", 404)
        mark = player(room)
        if not mark:
            return fail("Mängutuppa pääsemiseks on vaja mängija luba.", 403)
        room["seen"][mark] = time.time()
        if request.method == "GET":
            save(connection, code, room)
            return jsonify(state=view(code, room, mark))
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return fail("Vigane päring.")
        action = data.get("action")
        if action == "leave":
            if not room["left"]:
                room["left"] = mark
                room["version"] += 1
        else:
            if room["left"]:
                return fail("Mängija lahkus toast. Loo uus mängutuba.", 410)
            if not room["tokens"]["O"]:
                return fail("Oota teise mängija liitumist.", 409)
            if type(data.get("round")) is not int or data["round"] != room["round"]:
                return fail("Voor on muutunud. Mängulaud uuendatakse.", 409)
            if action == "move":
                index = data.get("index")
                if type(index) is not int or index not in range(9):
                    return fail("Vigane ruudu number.")
                if room["finished"]:
                    return fail("Voor on läbi. Alustage uut mängu.", 409)
                if room["restartVotes"]:
                    return fail("Oota uue vooru kinnitamist.", 409)
                if room["turn"] != mark:
                    return fail("Praegu on vastasmängija käik.", 409)
                if room["board"][index] is not None:
                    return fail("See ruut on juba hõivatud.", 409)
                room["board"][index] = mark
                line = next(
                    (list(line) for line in LINES if all(room["board"][i] == mark for i in line)),
                    [],
                )
                if line:
                    room["winner"] = mark
                    room["winLine"] = line
                    room["finished"] = True
                    room["scores"][mark] += 1
                elif all(room["board"]):
                    room["finished"] = True
                    room["scores"]["D"] += 1
                else:
                    room["turn"] = "O" if mark == "X" else "X"
                room["version"] += 1
            elif action == "restart":
                if mark not in room["restartVotes"]:
                    room["restartVotes"].append(mark)
                    room["version"] += 1
                if len(room["restartVotes"]) == 2:
                    room.update(
                        board=[None] * 9, turn="X", winner=None, winLine=[],
                        finished=False, restartVotes=[], round=room["round"] + 1,
                    )
            else:
                return fail("Tundmatu tegevus.")
        save(connection, code, room)
        return jsonify(state=view(code, room, mark))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8787, threaded=True)
