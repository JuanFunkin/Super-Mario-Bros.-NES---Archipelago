import logging
import time
from typing import TYPE_CHECKING, Any, Dict, List, Set

from NetUtils import ClientStatus
from worlds._bizhawk.client import BizHawkClient
from .Locations import LEVEL_TO_LOCATION, build_location_table

if TYPE_CHECKING:
    from worlds._bizhawk.context import BizHawkClientContext

logger = logging.getLogger("Client")

# --- RAM addresses (SMBDIS.ASM, verified against the official disassembly) ---
WORLD_NUMBER = 0x075F
LEVEL_NUMBER = 0x075C
OPER_MODE = 0x0770
PLAYER_STATUS = 0x0756       # 0=small, 1=big, 2=fiery (controls fire/damage state)
PLAYER_SIZE = 0x0754         # 0=big, 1=small (controls the actual sprite/hitbox size)
NUMBER_OF_LIVES = 0x075A
COIN_TALLY = 0x075E          # coins in the current level (0-99, resets every level)
PLAYER_Y_POSITION = 0x00CE   # Mario's Y position on the current screen
PLAYER_X_SPEED = 0x0057      # signed byte, horizontal speed
PLAYER_X_POSITION = 0x0086   # on-screen X position (used for the Ice Trap freeze, more reliable than zeroing speed)
STAR_INVINCIBLE_TIMER = 0x079F
STOMP_CHAIN_COUNTER = 0x0484  # increments by 1 on every successful stomp kill, resets on landing
STAR_FLAG_TASK_CONTROL = 0x0746  # counts 0->5 during a flagpole clear; hits 5 right before LevelNumber advances
WORLD_END_TIMER = 0x07A1         # counts down after touching the axe in a castle; advance happens once it hits 0
WALK_CAP_PX_PER_SEC = 90       # approximate walking-speed cap used for Button B Gating's soft correction

# Real, cross-game Trap Link tag. Other games (OOT, Tunic, Elden Ring, etc.)
# also listen on this same tag, so a trap someone receives in this world can
# now actually reach them, and vice versa. We handle incoming data
# defensively (see on_package) since we can't control how other games'
# clients format their payload.
TRAP_LINK_TAG = "TrapLink"

GAME_MODE_VALUE = 1
VICTORY_MODE_VALUE = 2

# World 8 (index 7) is the true end of the game (Bowser); we distinguish it
# from regular level clears using WorldNumber == 7 and LevelNumber == 3.
FINAL_WORLD = 7
FINAL_LEVEL = 3

ICE_TRAP_DURATION = 3.0       # seconds
STAR_POWER_FRAMES = 0xF0      # ~4 seconds of invincibility when the "Star Power" item is used

TRAP_ITEM_NAMES = {"Shrink Trap", "Ice Trap", "Death Trap"}
BUTTON_B_SPEED_CAP = 0x19  # approximate walking-speed magnitude used by Button B Gating


def _signed(byte: int) -> int:
    return byte - 256 if byte >= 128 else byte


def _unsigned(value: int) -> int:
    return value & 0xFF


class SMB1Client(BizHawkClient):
    game = "Super Mario Bros."
    system = "NES"
    patch_suffix = ".apsmb1"

    last_oper_mode: int = 0
    items_received_count: int = 0

    # last (world, level) pair seen while actually playing (GAME_MODE_VALUE);
    # used to detect level completion by watching for it to change, instead
    # of relying on the exact timing of VictoryMode.
    last_level_pair = None

    # unlocked-ability state (filled by reading ctx.items_received)
    mushroom_unlocked: bool = False
    fire_flower_unlocked: bool = False
    star_unlocked: bool = False
    button_b_unlocked: bool = False

    # internal tracking for coin/1-up checks
    total_coins_seen: int = 0
    last_coin_tally: int = 0
    last_lives: int = 0
    coin_checks_sent: int = 0
    oneup_checks_sent: int = 0
    granting_life_via_ap: bool = False  # avoids counting a life we injected ourselves as a "player 1-up"

    # stomp-kill tracking (approximation: only counts kills via stomping)
    total_kills_seen: int = 0
    last_stomp_chain: int = 0
    kill_checks_sent: int = 0

    # no-hit clear tracking (per level)
    took_damage_this_level: bool = False
    last_player_size: int = 1

    # no-hit RUN tracking (persists across the whole game, for the
    # "no_hit_run" goal -- unlike took_damage_this_level, this never resets
    # between levels)
    ever_took_damage: bool = False
    warned_no_hit_goal_failed: bool = False

    # no_skips goal tracking: every (world, level) pair actually played
    # through and finished, whole game, never reset
    levels_completed: Set = None
    warned_no_skips_goal_failed: bool = False

    # --- Death Link ---
    death_link: bool = False
    pending_death_link: bool = False    # a DeathLink came in from another player, we need to die
    sending_death_link: bool = False    # we already reported our own death, avoids duplicates

    # --- Trap Link ---
    trap_link: bool = False
    pending_traps: List[str] = None     # traps queued up to apply locally (from Trap Link or our own items)
    ice_trap_until: float = 0.0
    ice_trap_x: int = 0
    pending_death_trap: bool = False

    # Level Shuffle: guards against redirecting more than once for the same
    # end-of-level sequence
    level_shuffle_redirect_done: bool = False

    # Button B Gating: soft position-based speed correction (trims only the
    # excess distance since the last check, not a hard freeze)
    walk_cap_last_x: int = 0
    walk_cap_last_time: float = 0.0

    async def validate_rom(self, ctx: "BizHawkClientContext") -> bool:
        from worlds._bizhawk import read, RequestFailedError
        try:
            # The "PRG ROM" domain is addressed from 0 (raw file offset), not
            # from 0x8000 (that's the CPU address, which only applies to the
            # "System Bus" domain).
            rom_check = await read(ctx.bizhawk_ctx, [(0x0, 4, "PRG ROM")])
        except RequestFailedError:
            return False

        # SEI ; CLD ; LDA #%00010000  ->  78 D8 A9 10  (original SMB1 USA)
        if bytes(rom_check[0]) != bytes.fromhex("78d8a910"):
            return False

        ctx.game = self.game
        ctx.items_handling = 0b001
        ctx.want_slot_data = True
        if self.pending_traps is None:
            self.pending_traps = []
        return True

    async def set_auth(self, ctx: "BizHawkClientContext") -> None:
        # Don't override ctx.auth: at this point (before connecting) there
        # is no slot_data yet, so forcing a made-up name here just sends the
        # wrong slot name to the server ("InvalidSlot"). Let the normal
        # client flow (the name you type/configure) go through untouched.
        pass

    def on_package(self, ctx: "BizHawkClientContext", cmd: str, args: Dict[str, Any]) -> None:
        if cmd == "Connected":
            slot_data = args.get("slot_data", {}) or {}
            self.death_link = bool(slot_data.get("death_link", False))
            self.trap_link = bool(slot_data.get("trap_link", False))
        elif cmd == "Bounced":
            try:
                tags = args.get("tags", [])
                data = args.get("data", {}) or {}
                our_name = ctx.slot_info[ctx.slot].name if ctx.slot is not None else None

                if "DeathLink" in tags:
                    # ignore the echo of our own death
                    if data.get("source") != our_name:
                        self.on_deathlink(ctx)

                if TRAP_LINK_TAG in tags and self.trap_link:
                    # ignore the echo of our own trap
                    if data.get("source") != our_name:
                        # Different games format this differently -- accept
                        # a few common shapes defensively instead of
                        # assuming one exact schema (this is also why
                        # everything here is wrapped in try/except: a
                        # malformed payload from someone else's client
                        # should never be able to crash ours).
                        incoming_names = []
                        traps_field = data.get("traps")
                        if isinstance(traps_field, dict):
                            incoming_names.extend(traps_field.keys())
                        elif isinstance(traps_field, list):
                            incoming_names.extend(traps_field)
                        single_trap = data.get("trap")
                        if isinstance(single_trap, str):
                            incoming_names.append(single_trap)

                        for trap_name in incoming_names:
                            if trap_name in TRAP_ITEM_NAMES:
                                if self.pending_traps is None:
                                    self.pending_traps = []
                                self.pending_traps.append(trap_name)
            except Exception:
                logger.debug("Ignored a malformed Bounced package", exc_info=True)

    def on_deathlink(self, ctx: "BizHawkClientContext") -> None:
        ctx.last_death_link = time.time()
        self.pending_death_link = True

    async def send_deathlink(self, ctx: "BizHawkClientContext") -> None:
        self.sending_death_link = True
        ctx.last_death_link = time.time()
        await ctx.send_death("Mario ran out of lives.")

    async def send_traplink(self, ctx: "BizHawkClientContext", trap_name: str) -> None:
        if not self.trap_link:
            return
        our_name = ctx.slot_info[ctx.slot].name if ctx.slot is not None else None
        await ctx.send_msgs([{
            "cmd": "Bounce",
            "tags": [TRAP_LINK_TAG],
            "data": {"time": time.time(), "source": our_name, "traps": {trap_name: 1}},
        }])

    def _refresh_unlocks(self, ctx: "BizHawkClientContext") -> None:
        """Recomputes which abilities are unlocked based on items received so far."""
        self.mushroom_unlocked = False
        self.fire_flower_unlocked = False
        self.star_unlocked = False
        self.button_b_unlocked = False
        for item in ctx.items_received:
            name = ctx.item_names.lookup_in_game(item.item)
            if name == "Progressive Mushroom":
                self.mushroom_unlocked = True
            elif name == "Progressive Fire Flower":
                self.fire_flower_unlocked = True
            elif name == "Progressive Star":
                self.star_unlocked = True
            elif name == "Progressive Button B":
                self.button_b_unlocked = True

    def _apply_trap_writes(self, trap_name: str, player_status: int, x_position: int, writes: list) -> None:
        """Queues the RAM writes needed to apply a trap's effect right now."""
        if trap_name == "Shrink Trap":
            if player_status != 0:
                writes.append((PLAYER_STATUS, bytes([0]), "RAM"))
                writes.append((PLAYER_SIZE, bytes([1]), "RAM"))
        elif trap_name == "Ice Trap":
            self.ice_trap_until = time.time() + ICE_TRAP_DURATION
            self.ice_trap_x = x_position
            logger.info("Ice Trap! Mario is frozen for a few seconds.")
        elif trap_name == "Death Trap":
            self.pending_death_trap = True
            logger.info("Death Trap!")

    async def game_watcher(self, ctx: "BizHawkClientContext") -> None:
        from worlds._bizhawk import read, write
        from .Locations import location_table

        if self.pending_traps is None:
            self.pending_traps = []

        slot_data = ctx.slot_data or {}
        goal = slot_data.get("goal", 0)
        mushroom_gating = slot_data.get("mushroom_gating", True)
        fire_flower_gating = slot_data.get("fire_flower_gating", True)
        star_gating = slot_data.get("star_gating", True)
        button_b_gating = slot_data.get("button_b_gating", False)
        coin_checks_enabled = slot_data.get("coin_checks", False)
        coin_interval = slot_data.get("coin_check_interval", 50)
        oneup_checks_enabled = slot_data.get("oneup_checks", True)
        kill_checks_enabled = slot_data.get("kill_checks", False)
        kill_interval = slot_data.get("kill_check_interval", 5)
        no_hit_checks_enabled = slot_data.get("no_hit_checks", False)

        reads = await read(ctx.bizhawk_ctx, [
            (WORLD_NUMBER, 1, "RAM"),
            (LEVEL_NUMBER, 1, "RAM"),
            (OPER_MODE, 1, "RAM"),
            (PLAYER_STATUS, 1, "RAM"),
            (PLAYER_SIZE, 1, "RAM"),
            (COIN_TALLY, 1, "RAM"),
            (NUMBER_OF_LIVES, 1, "RAM"),
            (STAR_INVINCIBLE_TIMER, 1, "RAM"),
            (PLAYER_X_SPEED, 1, "RAM"),
            (PLAYER_X_POSITION, 1, "RAM"),
            (STOMP_CHAIN_COUNTER, 1, "RAM"),
            (STAR_FLAG_TASK_CONTROL, 1, "RAM"),
            (WORLD_END_TIMER, 1, "RAM"),
        ])
        (world_number, level_number, oper_mode, player_status, player_size, coin_tally,
         lives, star_timer, x_speed_raw, x_position, stomp_chain,
         star_flag_task, world_end_timer) = (r[0] for r in reads)

        writes = []

        # ---------- 0) Death Link ----------
        # Keeps the client's "DeathLink" tag in sync with the YAML option.
        await ctx.update_death_link(self.death_link)

        if "DeathLink" in ctx.tags:
            # a) We received a DeathLink from another player -> kill ourselves.
            #    Trick: push Mario off the bottom of the screen; the game engine
            #    detects the fall and triggers the normal death sequence (loses
            #    a life just like falling into a pit).
            if self.pending_death_link and oper_mode == GAME_MODE_VALUE:
                writes.append((PLAYER_Y_POSITION, bytes([0xF8]), "RAM"))
                self.pending_death_link = False
                self.sending_death_link = True  # avoid re-sending our own deathlink because of this

            # b) Detect our own death (lives went down) -> notify everyone.
            if lives < self.last_lives and not self.sending_death_link \
                    and ctx.last_death_link + 1 < time.time():
                await self.send_deathlink(ctx)
                self.ever_took_damage = True
            elif lives >= self.last_lives:
                # a new life is in progress with no losses: clear the flag for the next death
                self.sending_death_link = False

        # (Trap Link / trap application happens near the end of this
        # function now, after we've read any newly-received items -- see
        # below -- so both "found it myself" and "someone sent it to me"
        # apply in the exact same tick instead of one being delayed.)

        # ---------- 0.7) Level Shuffle: redirect to a random next level ----------
        # IMPORTANT: OperMode does NOT switch to "Victory Mode" for regular
        # level clears (that value is essentially unused outside the very
        # end of the game) -- that was the bug in the first version of this
        # feature. The real signal the game uses internally is different
        # depending on how you cleared the level:
        #   - flagpole: StarFlagTaskControl counts 0 -> 5 over the walk to
        #     the castle; LevelNumber only actually advances once it hits 5.
        #   - castle/axe: WorldEndTimer counts down after touching the axe;
        #     the world/level advance only happens once it reaches 0.
        # So we write our redirect as soon as either counter starts moving
        # (nonzero), well before it reaches the point where the game reads
        # WorldNumber/LevelNumber to load whatever's next.
        end_of_level_in_progress = star_flag_task > 0 or world_end_timer > 0
        if not end_of_level_in_progress:
            self.level_shuffle_redirect_done = False
        elif slot_data.get("level_shuffle", False) and not self.level_shuffle_redirect_done:
            self.level_shuffle_redirect_done = True
            shuffle_order = slot_data.get("level_shuffle_order")
            completed_slot = world_number * 4 + level_number
            if shuffle_order and completed_slot != FINAL_WORLD * 4 + FINAL_LEVEL and completed_slot in shuffle_order:
                pos = shuffle_order.index(completed_slot)
                if pos + 1 < len(shuffle_order):
                    target_slot = shuffle_order[pos + 1]
                    target_world, target_level = divmod(target_slot, 4)
                    if level_number == 3:
                        write_world = (target_world - 1) % 256
                        write_level = level_number  # irrelevant -- forced to 0 by the game regardless
                    else:
                        write_world = target_world
                        write_level = (target_level - 1) % 256
                    writes.append((WORLD_NUMBER, bytes([write_world]), "RAM"))
                    writes.append((LEVEL_NUMBER, bytes([write_level]), "RAM"))
                    logger.info(f"Level Shuffle: redirecting to {target_world + 1}-{target_level + 1}")

        # ---------- 1) Check for level completion ----------
        # We detect this by watching (WorldNumber, LevelNumber) while actually
        # playing (GAME_MODE_VALUE) and firing a check as soon as that pair
        # changes, rather than depending on the exact timing/duration of
        # VictoryMode (flagpole/castle animation), which was unreliable.
        current_pair = (world_number, level_number)
        if oper_mode == GAME_MODE_VALUE:
            if self.last_level_pair is not None and current_pair != self.last_level_pair:
                completed_pair = self.last_level_pair
                if self.levels_completed is None:
                    self.levels_completed = set()
                self.levels_completed.add(completed_pair)
                if completed_pair in LEVEL_TO_LOCATION:
                    location_name = LEVEL_TO_LOCATION[completed_pair]
                    location_id = location_table.get(location_name)
                    if location_id and location_id not in ctx.checked_locations:
                        logger.info(f"Check: {location_name}")
                        await ctx.send_msgs([{"cmd": "LocationChecks", "locations": [location_id]}])

                    if no_hit_checks_enabled and not self.took_damage_this_level:
                        from .Locations import no_hit_location_name
                        no_hit_name = no_hit_location_name(*completed_pair)
                        no_hit_id = location_table.get(no_hit_name)
                        if no_hit_id and no_hit_id not in ctx.checked_locations:
                            logger.info(f"Check: {no_hit_name}")
                            await ctx.send_msgs([{"cmd": "LocationChecks", "locations": [no_hit_id]}])

                # starting a new level: reset the no-hit tracker
                self.took_damage_this_level = False
            self.last_level_pair = current_pair

        # ---------- 2) Ability gating: grabbing a power-up without unlocking it cancels its effect ----------
        gating_forced_shrink_this_tick = False
        if oper_mode == GAME_MODE_VALUE:
            mushroom_ok = (not mushroom_gating) or self.mushroom_unlocked
            fire_flower_ok = (not fire_flower_gating) or self.fire_flower_unlocked

            if player_status == 1 and not mushroom_ok:
                writes.append((PLAYER_STATUS, bytes([0]), "RAM"))
                writes.append((PLAYER_SIZE, bytes([1]), "RAM"))  # 1 = small (this is the one that actually changes the sprite/hitbox)
                gating_forced_shrink_this_tick = True
                logger.info("Ability Gating: mushroom not unlocked, Mario shrinks back down")
            elif player_status == 2 and not fire_flower_ok:
                # without fire flower unlocked, at most stay big (if mushroom
                # isn't allowed either, send straight to small)
                if mushroom_ok:
                    writes.append((PLAYER_STATUS, bytes([1]), "RAM"))
                    writes.append((PLAYER_SIZE, bytes([0]), "RAM"))  # 0 = big
                else:
                    writes.append((PLAYER_STATUS, bytes([0]), "RAM"))
                    writes.append((PLAYER_SIZE, bytes([1]), "RAM"))
                    gating_forced_shrink_this_tick = True
                logger.info("Ability Gating: fire flower not unlocked, Mario's size is adjusted")

            if star_gating and not self.star_unlocked and star_timer != 0:
                writes.append((STAR_INVINCIBLE_TIMER, bytes([0]), "RAM"))
                logger.info("Ability Gating: star not unlocked, invincibility cancelled")

            # Button B Gating: clamping speed directly doesn't work -- the
            # game recalculates it from the held buttons every single frame,
            # far faster than we can poll, so the correction never has any
            # visible effect. What DOES work is measuring how far Mario
            # actually moved between our checks and trimming back just the
            # excess if it's more than a normal walk would cover in that
            # time -- small, incremental correction, not a hard freeze.
            if button_b_gating and not self.button_b_unlocked:
                now = time.time()
                if self.walk_cap_last_time == 0.0:
                    self.walk_cap_last_x = x_position
                    self.walk_cap_last_time = now
                else:
                    dt = min(now - self.walk_cap_last_time, 0.5)
                    diff = ((x_position - self.walk_cap_last_x + 128) % 256) - 128
                    max_allowed = WALK_CAP_PX_PER_SEC * dt
                    if abs(diff) > max_allowed:
                        excess = abs(diff) - max_allowed
                        direction = 1 if diff > 0 else -1
                        corrected_x = (x_position - int(excess) * direction) % 256
                        writes.append((PLAYER_X_POSITION, bytes([corrected_x]), "RAM"))
                        self.walk_cap_last_x = corrected_x
                    else:
                        self.walk_cap_last_x = x_position
                    self.walk_cap_last_time = now
            else:
                self.walk_cap_last_time = 0.0

        # ---------- 2.5) No-Hit Clear tracking ----------
        # PLAYER_SIZE: 0 = big, 1 = small. If it goes from big to small and we
        # didn't just force that ourselves (gating), it's real damage.
        if oper_mode == GAME_MODE_VALUE:
            if player_size == 1 and self.last_player_size == 0 and not gating_forced_shrink_this_tick:
                self.took_damage_this_level = True
                self.ever_took_damage = True
            self.last_player_size = player_size

        # ---------- 3) Coin checks (total accumulated, optional) ----------
        if coin_checks_enabled and oper_mode == GAME_MODE_VALUE:
            # CoinTally resets every level; we detect increments and add them to the total
            if coin_tally != self.last_coin_tally:
                delta = (coin_tally - self.last_coin_tally) % 100  # in case a level reset happened
                self.total_coins_seen += delta
                self.last_coin_tally = coin_tally

            from .Locations import MAX_COIN_CHECKS
            milestones_reached = min(self.total_coins_seen // coin_interval, MAX_COIN_CHECKS)
            while self.coin_checks_sent < milestones_reached:
                self.coin_checks_sent += 1
                location_name = f"Coin Milestone #{self.coin_checks_sent}"
                location_id = location_table.get(location_name)
                if location_id and location_id not in ctx.checked_locations:
                    logger.info(f"Check: {location_name}")
                    await ctx.send_msgs([{"cmd": "LocationChecks", "locations": [location_id]}])

        # ---------- 3.5) Kill checks (stomp kills, total accumulated, optional) ----------
        if kill_checks_enabled and oper_mode == GAME_MODE_VALUE:
            if stomp_chain > self.last_stomp_chain:
                self.total_kills_seen += (stomp_chain - self.last_stomp_chain)
            self.last_stomp_chain = stomp_chain

            from .Locations import MAX_KILL_CHECKS
            kill_milestones_reached = min(self.total_kills_seen // kill_interval, MAX_KILL_CHECKS)
            while self.kill_checks_sent < kill_milestones_reached:
                self.kill_checks_sent += 1
                location_name = f"Stomp Kill Milestone #{self.kill_checks_sent}"
                location_id = location_table.get(location_name)
                if location_id and location_id not in ctx.checked_locations:
                    logger.info(f"Check: {location_name}")
                    await ctx.send_msgs([{"cmd": "LocationChecks", "locations": [location_id]}])

        # ---------- 4) Checks for getting a 1-Up in the level (not the ones AP grants) ----------
        # Only evaluated during real gameplay: outside GAME_MODE_VALUE, the
        # "lives" RAM can pass through transient/garbage values while the game
        # reinitializes memory (starting a run, game over, continue, etc.),
        # which used to be counted as fake 1-Ups.
        if oneup_checks_enabled and oper_mode == GAME_MODE_VALUE:
            delta_lives = lives - self.last_lives
            if delta_lives == 1 and not self.granting_life_via_ap:
                from .Locations import MAX_ONEUP_CHECKS
                if self.oneup_checks_sent < MAX_ONEUP_CHECKS:
                    self.oneup_checks_sent += 1
                    location_name = f"1-Up Get #{self.oneup_checks_sent}"
                    location_id = location_table.get(location_name)
                    if location_id and location_id not in ctx.checked_locations:
                        logger.info(f"Check: {location_name}")
                        await ctx.send_msgs([{"cmd": "LocationChecks", "locations": [location_id]}])
            self.granting_life_via_ap = False

        # always updated (also used by the Death Link logic above)
        self.last_lives = lives

        self.last_oper_mode = oper_mode

        # ---------- 5) Inject received items ----------
        self._refresh_unlocks(ctx)
        if self.items_received_count < len(ctx.items_received):
            item = ctx.items_received[self.items_received_count]
            item_name = ctx.item_names.lookup_in_game(item.item)

            if item_name == "1-Up Mushroom":
                self.granting_life_via_ap = True
                writes.append((NUMBER_OF_LIVES, bytes([min(lives + 1, 99)]), "RAM"))
                self.items_received_count += 1
            elif item_name in ("Progressive Mushroom", "Progressive Fire Flower", "Progressive Star",
                                "Progressive Button B"):
                # no immediate RAM write needed, they just change the gating state
                self.items_received_count += 1
            elif item_name == "Star Power":
                # only actually grants invincibility if star usage is allowed
                # right now; otherwise ability gating would cancel it instantly
                # anyway, so we just consume the item with no effect.
                if oper_mode == GAME_MODE_VALUE and ((not star_gating) or self.star_unlocked):
                    writes.append((STAR_INVINCIBLE_TIMER, bytes([STAR_POWER_FRAMES]), "RAM"))
                    self.items_received_count += 1
                elif oper_mode != GAME_MODE_VALUE:
                    pass  # wait until we're actually in a level to apply it
                else:
                    self.items_received_count += 1
            elif item_name in TRAP_ITEM_NAMES:
                self._apply_trap_writes(item_name, player_status, x_position, writes)
                self.items_received_count += 1
                await self.send_traplink(ctx, item_name)
            else:
                # items with no direct effect implemented yet: mark them as
                # received anyway so they don't block the queue
                self.items_received_count += 1

        # ---------- 5.5) Apply pending trap effects (own items + Trap Link) ----------
        # Placed after item injection on purpose: this way a trap you just
        # found yourself and one sent to you via Trap Link both apply within
        # the same tick, instead of the self-found case lagging a cycle.
        if oper_mode == GAME_MODE_VALUE and self.pending_traps:
            trap_name = self.pending_traps.pop(0)
            self._apply_trap_writes(trap_name, player_status, x_position, writes)

        if self.pending_death_trap and oper_mode == GAME_MODE_VALUE:
            writes.append((PLAYER_Y_POSITION, bytes([0xF8]), "RAM"))
            self.pending_death_trap = False

        if time.time() < self.ice_trap_until:
            # Pin Mario's X position and zero his speed every tick: zeroing
            # speed alone isn't enough because the game recalculates it from
            # held buttons faster than we can poll, so some movement always
            # slips through between checks. Snapping the position back keeps
            # him visibly stuck in place regardless of that.
            writes.append((PLAYER_X_POSITION, bytes([self.ice_trap_x]), "RAM"))
            writes.append((PLAYER_X_SPEED, bytes([0]), "RAM"))

        if writes:
            await write(ctx.bizhawk_ctx, writes)

        # ---------- 6) Goal ----------
        final_world = FINAL_WORLD
        final_level = FINAL_LEVEL
        if oper_mode == VICTORY_MODE_VALUE and world_number == final_world and level_number == final_level:
            if self.levels_completed is None:
                self.levels_completed = set()
            self.levels_completed.add((final_world, final_level))

            # make sure the final level's location is checked off too, not just the goal status
            final_location_name = LEVEL_TO_LOCATION.get((final_world, final_level))
            final_location_id = location_table.get(final_location_name) if final_location_name else None
            if final_location_id and final_location_id not in ctx.checked_locations:
                logger.info(f"Check: {final_location_name}")
                await ctx.send_msgs([{"cmd": "LocationChecks", "locations": [final_location_id]}])

            if not ctx.finished_game:
                if goal == 1 and self.ever_took_damage:
                    # no_hit_run goal, but damage was taken at some point in
                    # this run -- the goal condition wasn't met, even though
                    # you reached the end. Doesn't send CLIENT_GOAL.
                    if not self.warned_no_hit_goal_failed:
                        logger.info(
                            "Reached the end, but your goal is 'No-Hit Run' and you took "
                            "damage earlier in the run -- goal not completed. You'd need "
                            "a clean run through the entire game with no hits."
                        )
                        self.warned_no_hit_goal_failed = True
                elif goal == 2:
                    required_count = (final_world + 1) * 4
                    if len(self.levels_completed) < required_count:
                        if not self.warned_no_skips_goal_failed:
                            missing = required_count - len(self.levels_completed)
                            logger.info(
                                f"Reached the end, but your goal is 'No Skips' and you skipped "
                                f"{missing} level(s) along the way (likely via a warp zone) -- "
                                f"goal not completed. You'd need to play through every level."
                            )
                            self.warned_no_skips_goal_failed = True
                    else:
                        await ctx.send_msgs([{"cmd": "StatusUpdate", "status": ClientStatus.CLIENT_GOAL}])
                        ctx.finished_game = True
                else:
                    await ctx.send_msgs([{"cmd": "StatusUpdate", "status": ClientStatus.CLIENT_GOAL}])
                    ctx.finished_game = True
