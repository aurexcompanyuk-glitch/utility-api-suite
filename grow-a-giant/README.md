# Grow a Giant (Roblox)

Buy food, feed your Giant, watch it digest (even while you're offline), grow
taller, earn more cash.

**Status: Phase 1 (core loop) only.** Collecting, stealing, events, the crown
and monetization come in later phases.

> **The design spec isn't in this repo yet.** `GROW_A_GIANT_SPEC.md` was not
> included when this was built, so Phase 1 follows the design summary
> (core loop, log-curve growth, server-checked actions). Put the spec in this
> folder and commit it, and later phases will follow it exactly. Anything in
> Phase 1 that differs from the spec can then be fixed against it.

## What Phase 1 includes

| Piece | Where |
|---|---|
| 7 foods, from Apple ($10) to Golden Steak ($750K) | `src/shared/Config.luau` |
| Growth curve: height climbs forever, the model's size caps at 12× | `src/shared/GrowthMath.luau` |
| Digestion (live and offline, up to 24 h), 4 stomach slots | `src/shared/Digestion.luau` |
| Saving with session locking, retries and safe fallback | `src/server/Services/DataService.luau` |
| 8 plots in a ring, blocky placeholder Giant with height label | `src/server/Services/PlotService.luau` |
| Buy/feed remotes (type-checked, rate-limited, validated), income tick, leaderboard | `src/server/Services/GameService.luau` |
| HUD: cash, income, height, food shop, stomach, toasts | `src/client/Hud.luau` |

The client never changes cash or mass itself. It asks the server, and the
server checks the request against the player's real data.

## One-time setup

1. Install **Roblox Studio**.
2. Install **Rokit** (https://github.com/rojo-rbx/rokit), then in this folder run:
   ```
   rokit install
   ```
   This installs the pinned versions of `rojo`, `wally` and `selene` from `rokit.toml`.
3. Install the Rojo Studio plugin: `rojo plugin install` (or search "Rojo" in the
   Creator Store inside Studio).
4. `wally install` — Phase 1 has no packages, so this just confirms Wally works.

## Testing Phase 1 in Studio

**Start a session**

1. In this folder run `rojo serve`.
2. Open Studio, create a new **Baseplate** place.
3. Plugins tab → **Rojo** → **Connect**. `ServerScriptService.Server`,
   `ReplicatedStorage.Shared`/`Remotes` and `StarterPlayerScripts.Client` appear.
4. Saving needs DataStores: **File → Publish to Roblox** once, then
   **Home → Game Settings → Security → Enable Studio Access to API Services**.
   (Skip this and the game still runs, with a red "Saving unavailable" warning.)
5. Press **Play** (F5).

**Checklist**

- [ ] You spawn on a sand plot facing a blocky Giant labelled with your name and `10.0m`.
- [ ] Top bar shows `$50`, `+1/s`, and the height. Cash goes up every second.
- [ ] Buy an Apple. Cash drops by $10 and "Owned: 1" appears.
- [ ] Feed it. It shows in the first stomach slot with a filling bar and a countdown.
- [ ] As it digests, the height rises, the Giant grows, and income goes up.
- [ ] Feed 4 items, then try a 5th: "stomach is full" message.
- [ ] Try to buy something you can't afford: "Not enough cash".
- [ ] The player list (Tab) shows Height and Cash.

**Offline digestion and saving** (needs step 4 above)

- [ ] Feed a Bread (30 s digest), note your height, stop the game right away.
- [ ] Wait 30 seconds, press Play again: a "Welcome back!" toast, the bread is
      gone from the stomach, and your height is higher than when you left.

**Growth cap**

- [ ] While playing, switch the command bar (View → Command Bar) to the
      **Server** view and run `_G.GiantCheat("YourName", 0, 1e9)`. Height jumps to
      ~400 m but the Giant stops at 12× size and stays on its plot. Try `1e15`:
      the number keeps growing, the model doesn't. (`_G.GiantCheat` only exists in Studio.)

**Exploit check**

- [ ] With the command bar in the **Client** view, run each of these. None should give you anything:
  ```lua
  game.ReplicatedStorage.Remotes.BuyFood:FireServer("goldsteak", 1)  -- "Not enough cash"
  game.ReplicatedStorage.Remotes.BuyFood:FireServer("apple", -50)
  game.ReplicatedStorage.Remotes.BuyFood:FireServer("apple", 0/0)
  game.ReplicatedStorage.Remotes.FeedFood:FireServer("cake")        -- "You don't have any Cake"
  ```

**Multiplayer**

- [ ] Test tab → Clients and Servers → 2 Players → Start. Each player gets their
      own plot and Giant; both labels are visible.

## Tuning

All balance numbers are in `src/shared/Config.luau` (foods, stomach slots,
offline cap) and `src/shared/GrowthMath.luau` (growth curve, size cap, income).

## Offline checks (no Studio needed)

```
luau tests/run.luau        # growth curve, digestion and formatting tests
rojo build -o test.rbxlx   # confirms the project tree builds
```

## Swapping in real Giant art

Replace `buildGiantModel` in `PlotService.luau`. Any model works if its
`PrimaryPart` sits at the feet, because scaling happens around that point.
