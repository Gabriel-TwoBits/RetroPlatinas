"""explore.Explorer's checkpoints, without the emulator."""

import explore
import plan as plans


class Clock:
    def __init__(self):
        self.now = 0

    def time(self):
        return self.now


def explorer_on(clock, saved, tick_seconds):
    """An Explorer with no emulator: each rollout takes `tick_seconds` and finds nothing."""

    def rollout(_cell):
        clock.now += tick_seconds

    explorer = explore.Explorer.__new__(explore.Explorer)
    explorer.checkpoint = lambda moves, quits: saved.append((moves, quits))
    explorer.archive = {"deep": {"plan": b"\x01", "quits": ()}}
    explorer.deepest = lambda: "deep"
    explorer._pick = lambda: "deep"
    explorer.rollout = rollout
    explorer._report = lambda _iteration, _elapsed: None
    return explorer


def test_a_search_saves_its_deepest_route_every_checkpoint_interval(monkeypatch):
    clock, saved = Clock(), []
    monkeypatch.setattr(explore, "time", clock)
    explorer = explorer_on(clock, saved, explore.CHECKPOINT_SECONDS)
    iterations = 3

    explorer.run(iterations, seconds=iterations * explore.CHECKPOINT_SECONDS + 1)

    assert saved == [(b"\x01", ())] * iterations


def test_a_search_within_the_interval_saves_nothing(monkeypatch):
    clock, saved = Clock(), []
    monkeypatch.setattr(explore, "time", clock)

    explorer_on(clock, saved, 1).run(2, seconds=explore.CHECKPOINT_SECONDS)

    assert saved == []


def test_saving_a_plan_leaves_no_partial_file(tmp_path):
    target = tmp_path / "route.json"
    plan = plans.Plan("start", "core", "build", False, ["up"], [[1, 0]])

    plans.save(plan, target)

    assert plans.load(target) == plan
    assert [path.name for path in tmp_path.iterdir()] == [target.name]
