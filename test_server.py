"""Run with python -m unittest -v. Uses a temporary database, never live rooms."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

tmp = tempfile.TemporaryDirectory()
os.environ["GAME_DB"] = str(Path(tmp.name) / "test.sqlite3")
spec = importlib.util.spec_from_file_location("room_server", Path(__file__).with_name("server.py"))
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class RoomsTest(unittest.TestCase):
    def setUp(self):
        self.client = server.app.test_client()
        server.attempts.clear()

    def pair(self):
        host = self.client.post("/api/rooms", json={}).get_json()
        code = host["state"]["code"]
        guest = self.client.post(f"/api/rooms/{code}/join", json={}).get_json()
        return code, {"X": host["token"], "O": guest["token"]}

    def test_standalone_entrypoint_and_server_files_are_not_public(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Mängi kahe telefoniga", response.get_data(as_text=True))
        self.assertIn("location.origin", response.get_data(as_text=True))
        self.assertNotIn("__PORT_", response.get_data(as_text=True))
        response.close()
        self.assertEqual(self.client.get("/server.py").status_code, 404)
        self.assertEqual(self.client.get("/requirements.txt").status_code, 404)
        self.assertEqual(self.client.get("/rooms.sqlite3").status_code, 404)

    def command(self, code, tokens, mark, **kwargs):
        return self.client.post(
            f"/api/rooms/{code}", json=kwargs,
            headers={"Authorization": "Bearer " + tokens[mark]},
        )

    def test_no_access_without_player_token(self):
        code, _ = self.pair()
        self.assertEqual(self.client.get(f"/api/rooms/{code}").status_code, 403)
        self.assertEqual(self.client.post(f"/api/rooms/{code}", json={"action": "move"}).status_code, 403)
        self.assertEqual(self.client.post(f"/api/rooms/{code}/join", json={}).status_code, 409)
        self.assertEqual(self.client.post("/api/rooms/ZZZZZZ/join", json={}).status_code, 404)

    def test_turns_indices_occupied_and_stale_round(self):
        code, tokens = self.pair()
        self.assertEqual(self.command(code, tokens, "O", action="move", round=1, index=0).status_code, 409)
        for index in [-1, 9, True, None, "0"]:
            self.assertEqual(self.command(code, tokens, "X", action="move", round=1, index=index).status_code, 400)
        self.assertEqual(self.command(code, tokens, "X", action="move", round=99, index=0).status_code, 409)
        self.assertEqual(self.command(code, tokens, "X", action="move", round=1, index=0).status_code, 200)
        self.assertEqual(self.command(code, tokens, "O", action="move", round=1, index=0).status_code, 409)

    def test_every_winning_line_for_both_players(self):
        for mark in ("X", "O"):
            for line in server.LINES:
                with self.subTest(mark=mark, line=line):
                    code, tokens = self.pair()
                    others = [i for i in range(9) if i not in line]
                    triple = next(
                        (a, b, c)
                        for a in others for b in others for c in others
                        if len({a, b, c}) == 3
                        and not any(set(l).issubset({a, b, c}) for l in server.LINES)
                    )
                    if mark == "X":
                        moves = [line[0], triple[0], line[1], triple[1], line[2]]
                    else:
                        moves = [triple[0], line[0], triple[1], line[1], triple[2], line[2]]
                    for step, index in enumerate(moves):
                        result = self.command(code, tokens, "X" if step % 2 == 0 else "O",
                                              action="move", round=1, index=index)
                        self.assertEqual(result.status_code, 200)
                    state = result.get_json()["state"]
                    self.assertEqual(state["winner"], mark)
                    self.assertEqual(state["winLine"], list(line))
                    self.assertEqual(state["scores"][mark], 1)
                    # No replay after victory, no double score increments.
                    self.assertEqual(self.command(code, tokens, mark, action="move", round=1, index=8).status_code, 409)

    def test_draw_and_ninth_move_win(self):
        for moves, winner in [
            ([0, 1, 2, 4, 3, 5, 7, 6, 8], None),
            ([2, 1, 5, 3, 0, 4, 7, 6, 8], "X"),
        ]:
            code, tokens = self.pair()
            for step, index in enumerate(moves):
                response = self.command(code, tokens, "X" if step % 2 == 0 else "O",
                                        action="move", round=1, index=index)
                self.assertEqual(response.status_code, 200)
            state = response.get_json()["state"]
            self.assertTrue(state["finished"])
            self.assertEqual(state["winner"], winner)
            self.assertEqual(state["scores"]["D"], 0 if winner else 1)

    def test_two_votes_required_and_old_round_rejected(self):
        code, tokens = self.pair()
        response = self.command(code, tokens, "X", action="restart", round=1)
        self.assertEqual(response.get_json()["state"]["restartVotes"], ["X"])
        self.assertEqual(self.command(code, tokens, "X", action="move", round=1, index=0).status_code, 409)
        response = self.command(code, tokens, "X", action="restart", round=1)
        self.assertEqual(response.get_json()["state"]["round"], 1)
        response = self.command(code, tokens, "O", action="restart", round=1)
        self.assertEqual(response.get_json()["state"]["round"], 2)
        self.assertEqual(response.get_json()["state"]["restartVotes"], [])
        self.assertEqual(self.command(code, tokens, "X", action="move", round=1, index=0).status_code, 409)

    def test_wait_for_guest_leave_and_room_isolation(self):
        host = self.client.post("/api/rooms", json={}).get_json()
        code = host["state"]["code"]
        tokens = {"X": host["token"]}
        self.assertEqual(self.command(code, tokens, "X", action="move", round=1, index=0).status_code, 409)
        code2, tokens2 = self.pair()
        self.assertEqual(self.command(code2, tokens, "X", action="move", round=1, index=0).status_code, 403)
        self.command(code2, tokens2, "O", action="leave")
        self.assertEqual(self.command(code2, tokens2, "X", action="move", round=1, index=0).status_code, 410)
        self.assertEqual(self.client.post(f"/api/rooms/{code2}/join", json={}).status_code, 410)


if __name__ == "__main__":
    unittest.main()
