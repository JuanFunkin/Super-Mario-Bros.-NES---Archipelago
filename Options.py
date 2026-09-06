from dataclasses import dataclass
from Options import Toggle, Range, Choice, DeathLink, PerGameCommonOptions


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


class Goal(Choice):
    """What you need to do to complete your goal.
    - beat_the_game: reach the end of World 8, same as usual.
    - no_hit_run: reach the end without ever taking a single hit in ANY
      level of the entire run. If you take damage at any point, the goal
      won't trigger even once you reach the end -- you'd need a clean run
      all the way through.
    - no_skips: reach the end having actually played through every single
      level -- skipping any of them via a warp zone means the goal won't
      trigger even if you reach the end."""
    display_name = "Goal"
    option_beat_the_game = 0
    option_no_hit_run = 1
    option_no_skips = 2
    default = 0


class LevelShuffle(Toggle):
    """EXPERIMENTAL. If enabled, clearing a level sends you to a random
    other level instead of the vanilla next one -- e.g. clearing 1-1 might
    send you straight to 4-3. The 32 levels are shuffled into one fixed
    order for your seed (so you'll eventually play all of them once,
    finishing with the real World 8 castle). This works by rewriting the
    game's internal level-select RAM, not by patching the ROM, so it's a
    bit less rock-solid than everything else in this world -- expect the
    occasional rough edge."""
    display_name = "Level Shuffle"
    default = False


class TrapLink(Toggle):
    """If enabled, any trap (Shrink Trap, Ice Trap, Death Trap) you receive
    is also triggered for every other player who also has Trap Link on."""
    display_name = "Trap Link"


@dataclass
class SMB1Options(PerGameCommonOptions):
    goal: Goal
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
    level_shuffle: LevelShuffle
    death_link: DeathLink
