"""Which achievement sets a loaded disc serves, following RAWeb's `ResolveAchievementSetsAction`.

A core hash serves the core set and the bonus and challenge subsets the player opted into; a
specialty hash adds that specialty set to them; an exclusive hash serves its set alone.
"""

from dataclasses import dataclass

from apps.games.models import (
    OPT_IN_SET_TYPES,
    SET_TYPE_BONUS,
    SET_TYPE_CHALLENGE,
    SET_TYPE_EXCLUSIVE,
    SET_TYPE_SPECIALTY,
    Game,
)

# Sets are served core first, then specialty, challenge and bonus, as RAWeb sorts them; an
# exclusive set is always served alone.
SET_TYPE_ORDER = {
    None: 0,
    SET_TYPE_SPECIALTY: 1,
    SET_TYPE_CHALLENGE: 2,
    SET_TYPE_BONUS: 3,
}


@dataclass(frozen=True)
class ServedSets:
    """`core` names the load (top-level GameId, title, console and icon), `sets` are served in
    order, and `rich_presence` is the game whose script the emulator runs."""

    core: Game
    sets: list[Game]
    rich_presence: Game


def session_game(hash_game):
    """The game a session on `hash_game`'s disc is recorded on: the parent of a bonus or
    challenge subset, else the game itself (RAWeb's `ResolveRootGameFromGameAndGameHashAction`)."""
    if hash_game.set_type in OPT_IN_SET_TYPES:
        return hash_game.parent_game
    else:
        return hash_game


def _opted_in_subsets(user, core):
    return list(
        Game.objects.select_related("console").filter(
            parent_game=core,
            set_type__in=OPT_IN_SET_TYPES,
            set_preferences__user=user,
            set_preferences__opted_in=True,
        )
    )


def _ordered(sets):
    return sorted(sets, key=lambda game: (SET_TYPE_ORDER[game.set_type], game.pk))


def _own_rich_presence(game, core):
    """`game` when it has a rich presence script of its own, else `core`."""
    if game.rich_presence_patch:
        return game
    else:
        return core


def sets_for_hash(user, hash_game):
    """The sets the disc `hash_game` is linked to serves `user`."""
    loaded = session_game(hash_game)
    if loaded.set_type is None:
        return ServedSets(
            core=loaded,
            sets=_ordered([loaded, *_opted_in_subsets(user, loaded)]),
            rich_presence=loaded,
        )
    elif loaded.set_type == SET_TYPE_SPECIALTY:
        core = loaded.parent_game
        return ServedSets(
            core=core,
            sets=_ordered([core, loaded, *_opted_in_subsets(user, core)]),
            rich_presence=_own_rich_presence(loaded, core),
        )
    elif loaded.set_type == SET_TYPE_EXCLUSIVE:
        core = loaded.parent_game
        return ServedSets(core=core, sets=[loaded], rich_presence=_own_rich_presence(loaded, core))
    else:
        raise ValueError(f"Game {loaded.pk} has unknown set type {loaded.set_type!r}")


def sets_for_game(game):
    """The legacy load by game id alone: that game's set only, served as a core set."""
    return ServedSets(core=game, sets=[game], rich_presence=game)
