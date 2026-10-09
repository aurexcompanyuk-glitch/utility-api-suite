# Steal a Dragon: build prompt

Paste everything between the lines into Claude Code (in Terminal on the Mac),
with Roblox Studio open on a **new Baseplate place** and the Studio MCP connected.
Build one phase at a time and test in Studio before saying "go to Phase 2".

---

You are building a Roblox game called **Steal a Dragon** directly in the open
Roblox Studio place, using the Studio MCP tools. It copies the structure of the
popular "Steal an Egg" games: a safe base area, a red line, and a long wild map
beyond it where eggs get rarer the further you go and other players can steal
the egg you're carrying. Our twist: eggs hatch into dragons, and your best
dragon becomes your mount.

## Rules for how you build
- All game logic runs on the server. The client only sends requests ("pick up
  this egg", "shove", "buy speed"). The server checks every request: argument
  types, distance, cooldowns, cash, and whether the player is in the safe zone.
- Put every balance number in one `ModuleScript` called `Config` in
  `ReplicatedStorage`, so I can tune the game without touching the logic.
- Save with DataStoreService. Use session locking, retries, autosave every 60 s,
  save on leave and in `BindToClose`. If saving fails, warn the player in the HUD.
- No paid random items. Robux never buys eggs or dragons.
- No AFK reward machines (no treadmills that pay out for standing still).
  Speed is bought with cash.
- Use simple, clean, chunky low-poly parts for now. Each zone needs its own
  colour and ground material so it reads at a glance.
- After each phase, give me a short checklist of what to test in Studio.

## Map layout (one long strip, roughly 160 studs wide)
```
 SAFE ZONE   8 player bases side by side (each about 40x40)
 =========== RED LINE (glowing red strip + "SAFE ZONE" sign) ===========
 Zone 1  Forest      Common      0-150 studs past the line
 Zone 2  Swamp       Uncommon    150-300
 Zone 3  Desert      Rare        300-450
 Zone 4  Ice Caves   Epic        450-600
 Zone 5  Volcano     Legendary   600-750
 Zone 6  Storm Peaks Mythic      750-900
 Zone 7  Shadow Rift Secret      900-1050
 Zone 8  Celestial   Celestial   1050-1200 (the furthest point)
```
- Put a big sign at the start of each zone with its name and recommended speed.
- Walls run along both long sides, so the only way is forward and back.

## Each player base (safe zone)
- A **Pen** with 10 dragon slots (pedestals) at the start. More slots cost cash.
- A **Hatchery** pad: walk onto it while carrying an egg to start hatching.
- A **Speed shop** board: "+1 Speed" button.
- A cash-collect pad that banks the base's earned cash when stepped on, like
  Steal an Egg.
- The player's name and total income shown on a sign above the base.

## Eggs and dragons (Config)
| Tier | Zone | Income/s | Hatch time | Carry slowdown |
|---|---|---|---|---|
| Common | Forest | 1 | 5 s | 0% |
| Uncommon | Swamp | 6 | 10 s | 5% |
| Rare | Desert | 35 | 20 s | 10% |
| Epic | Ice Caves | 200 | 40 s | 15% |
| Legendary | Volcano | 1,200 | 60 s | 20% |
| Mythic | Storm Peaks | 7,500 | 90 s | 25% |
| Secret | Shadow Rift | 50,000 | 120 s | 30% |
| Celestial | Celestial | 350,000 | 180 s | 35% |

- Each tier has 3 dragon species (24 in total). Give them fun names, e.g.
  Leafwing, Mossback and Sproutling for Common, up to Starwyrm for Celestial.
  Each species gets its own colour scheme.
- Each zone has 6-10 egg spawn points and keeps up to 6 eggs on the ground.
  An egg respawns 8 s after one is taken.
- When an egg spawns there's a 10% chance it's one tier higher than the zone
  (a "Lucky" egg, with a sparkle effect).
- Legendary or higher eggs show a server-wide banner: "A MYTHIC EGG appeared in
  STORM PEAKS!"

## Speed (Config)
- Everyone starts at WalkSpeed 16. "+1 Speed" costs `50 * 1.35^level`.
- Recommended speed per zone: 16, 20, 25, 30, 36, 42, 50, 58.
- The server sets the player's WalkSpeed from their saved speed. Carrying an egg
  lowers it by that egg's carry slowdown.
- Anti-exploit: the server tracks each player's position and pulls them back if
  they move much faster than their allowed speed.

## Phase 1: core loop (build this now)
1. Build the map, the 8 bases and the red line. Assign each joining player a
   base and spawn them there.
2. Spawn eggs in each zone, with tier names floating above them.
3. Picking up an egg: walk up and use a ProximityPrompt ("Hold E, 0.5 s").
   You can carry 1 egg; it sits above your head and slows you.
4. Crossing back over the red line into your own base with an egg, then
   stepping on the Hatchery, hatches it after its hatch time (with a
   countdown). The dragon appears on a free pen slot, standing and idling.
5. Dragons earn income every second into the base's cash pile. The collect pad
   banks it.
6. A Speed shop, pen slot purchase and a "Sell dragon" option (for 5x its
   income/s).
7. HUD: cash, income/s, speed, carried egg, and toast messages.
8. Leaderstats: Cash and Best Dragon.
9. Saving: cash, speed level, pen slots, dragons.
10. A Studio-only cheat function `_G.DragonCheat(name, cash, speed)` for testing.

## Phase 2: danger and stealing
1. **Guardians.** Each zone has a Guardian Dragon NPC that patrols. When you
   pick up an egg in its zone, it chases you at that zone's recommended speed
   plus 2. If it touches you, you get flung, the egg drops where you stood,
   and the egg returns to its zone after 10 s. Guardians never cross into the
   previous zone, and never cross the red line.
2. **Stealing from players.** Outside the safe zone, any player can press F (or
   tap a Shove button on mobile) to shove someone within 8 studs (cooldown 3 s).
   If the shoved player is carrying an egg, it drops for anyone to grab.
3. **Fair-play rules:**
   - After losing an egg you get 5 s of steal immunity (shown with a shield bubble).
   - Players with fewer than 3 rebirths and less than 20 speed can't be shoved in
     Zones 1-2.
   - Nobody can be shoved, and no egg can be taken, inside the safe zone. Bases
     can never be raided.
4. Effects and sounds for pickup, shove, flung, steal and hatch.

## Phase 3: dragons, rebirth, shop
1. **Mount.** Players pick one dragon from their pen as their mount. In the wild
   zones they ride it on the ground (no flying), and it adds a speed bonus by
   tier (+0 to +10). The rider model sits on the dragon.
2. **Rebirth** (max 15): needs a Legendary or higher dragon plus cash
   (`1M * 4^rebirth`). It resets cash, speed and dragons, and gives a permanent
   +50% income per rebirth plus a new base colour.
3. **Robux store** (MarketplaceService, with a `ProcessReceipt` that records each
   purchase ID so nothing is granted twice):
   - Developer products: Cash Bag, Cash Crate, Cash Vault (each gives a number of
     minutes of the player's current income).
   - Game passes: 2x Speed Boost (+25% speed), VIP (gold base and a chat tag),
     Rainbow Trail.
4. Polish: a tutorial arrow for new players pointing at the first egg, then the
   Hatchery, then the Speed shop.

Start with Phase 1 only. When it's done, give me the test checklist and wait.

---
