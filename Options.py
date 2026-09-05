from dataclasses import dataclass
from Options import Toggle, Range, DeathLink, PerGameCommonOptions


class CoinChecks(Toggle):
    """If enabled, collecting coins also grants checks (every X coins
    accumulated across the whole game, see coin_check_interval). Covers
    every coin collected during the entire run, not just a handful of
    milestones."""
    display_name = "Coin Checks"


class CoinCheckInterval(Range):
    """How many accumulated coins (total across the run) are needed to
    trigger a check, if Coin Checks is enabled."""
    display_name = "Coin Check Interval"
    range_start = 10
    range_end = 100
    default = 50


class OneUpChecks(Toggle):
    """If enabled, getting an extra life (1-Up) inside a level (not the
    ones granted by the multiworld) also sends a check."""
    display_name = "1-Up Checks"
    default = True


class MushroomGating(Toggle):
    """If enabled, Mario can't stay Super until 'Progressive Mushroom' is
    received from the multiworld. Picking up a mushroom before that
    instantly shrinks you back down."""
    display_name = "Mushroom Gating"
    default = True


class FireFlowerGating(Toggle):
    """If enabled, Mario can't stay Fiery until 'Progressive Fire Flower'
    is received from the multiworld. Picking up a fire flower before that
    instantly reverts you to Super (or Small, if Mushroom Gating also
    blocks that)."""
    display_name = "Fire Flower Gating"
    default = True


class StarGating(Toggle):
    """If enabled, star invincibility is cancelled instantly if you grab a
    star before receiving 'Progressive Star' from the multiworld."""
    display_name = "Star Gating"
    default = True


class ButtonBGating(Toggle):
    """If enabled, Mario's horizontal speed is softly capped to walking
    pace until 'Progressive Button B' is received from the multiworld
    (running requires holding B). This is a best-effort correction, not a
    perfectly solid block -- brief bursts of extra speed may still slip
    through between checks."""
    display_name = "Button B Gating"
    default = False


class KillChecks(Toggle):
    """If enabled, stomping enemies also grants checks (every X stomp
    kills accumulated across the whole game, see kill_check_interval).
    NOTE: this only counts kills via stomping (jumping on enemies) --
    fireballs and shell hits aren't tracked by the game's own counters,
    so this is an approximation, not an exact lifetime kill count."""
    display_name = "Kill Checks"


class KillCheckInterval(Range):
    """How many stomp kills (total across the run) are needed to trigger a
    check, if Kill Checks is enabled."""
    display_name = "Kill Check Interval"
    range_start = 1
    range_end = 20
    default = 5


class NoHitChecks(Toggle):
    """If enabled, clearing a level without ever losing your power-up
    (taking no damage) grants an extra check for that level."""
    display_name = "No-Hit Checks"


class TrapLink(Toggle):
    """If enabled, any trap (Shrink Trap, Ice Trap, Death Trap) you receive
    is also triggered for every other player who also has Trap Link on."""
    display_name = "Trap Link"


class RandomizeAllWorlds(Toggle):
    """If enabled, all 8 worlds are generated (32 levels).
    If disabled, only World 1 is used (quick test/MVP mode)."""
    display_name = "Randomize All Worlds"
    default = True


@dataclass
class SMB1Options(PerGameCommonOptions):
    randomize_all_worlds: RandomizeAllWorlds
    coin_checks: CoinChecks
    coin_check_interval: CoinCheckInterval
    oneup_checks: OneUpChecks
    kill_checks: KillChecks
    kill_check_interval: KillCheckInterval
    no_hit_checks: NoHitChecks
    mushroom_gating: MushroomGating
    fire_flower_gating: FireFlowerGating
    star_gating: StarGating
    button_b_gating: ButtonBGating
    trap_link: TrapLink
    death_link: DeathLink
