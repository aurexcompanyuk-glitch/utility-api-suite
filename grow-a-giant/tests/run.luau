--[[
	Offline tests for the pure game math. Run from the grow-a-giant folder:

	    luau tests/run.luau

	(Install the standalone Luau CLI from https://github.com/luau-lang/luau/releases.)
	These cover the parts where a bug would silently wreck balance or saves;
	everything that touches Roblox APIs is tested by playing in Studio.
]]

local Config = require("../src/shared/Config")
local Digestion = require("../src/shared/Digestion")
local Format = require("../src/shared/Format")
local GrowthMath = require("../src/shared/GrowthMath")

local passed, failed = 0, 0

local function test(name: string, fn: () -> ())
	local ok, err = pcall(fn)
	if ok then
		passed += 1
	else
		failed += 1
		print("FAIL  " .. name .. "\n      " .. tostring(err))
	end
end

local function near(a: number, b: number, eps: number?)
	assert(math.abs(a - b) <= (eps or 1e-6), string.format("expected %s, got %s", tostring(b), tostring(a)))
end

local function eq(a: any, b: any)
	assert(a == b, string.format("expected %s, got %s", tostring(b), tostring(a)))
end

-- Growth curve ---------------------------------------------------------------

test("height starts at BaseHeight", function()
	near(GrowthMath.heightFromMass(0), GrowthMath.BaseHeight)
end)

test("height keeps climbing with no ceiling", function()
	local last = GrowthMath.heightFromMass(0)
	for _, mass in { 10, 1e3, 1e6, 1e9, 1e12, 1e15 } do
		local h = GrowthMath.heightFromMass(mass)
		assert(h > last, "height did not increase at mass " .. mass)
		last = h
	end
end)

test("visual scale never exceeds the cap, even at absurd heights", function()
	near(GrowthMath.visualScale(GrowthMath.BaseHeight), 1)
	for _, mass in { 1e6, 1e12, 1e100 } do
		local s = GrowthMath.visualScale(GrowthMath.heightFromMass(mass))
		assert(s <= GrowthMath.MaxVisualScale, "scale " .. s .. " over cap")
		assert(s >= 1)
	end
end)

test("negative mass is treated as zero", function()
	near(GrowthMath.heightFromMass(-50), GrowthMath.BaseHeight)
end)

test("income rises with height", function()
	near(GrowthMath.incomePerSecond(GrowthMath.BaseHeight), GrowthMath.BaseIncome)
	assert(GrowthMath.incomePerSecond(50) > GrowthMath.incomePerSecond(20))
end)

-- Digestion ------------------------------------------------------------------

local foods = Config.FoodsById
local apple = foods.apple

test("one full digest gives exactly the food's mass", function()
	local gained, left = Digestion.advance({ { foodId = "apple", remaining = apple.digestSeconds } }, apple.digestSeconds, foods)
	near(gained, apple.mass)
	eq(#left, 0)
end)

test("1-second ticks add up to the same as one big step", function()
	local stomach = { { foodId = "apple", remaining = apple.digestSeconds }, { foodId = "bread", remaining = foods.bread.digestSeconds } }
	local total = 0
	local s = stomach
	for _ = 1, 100 do
		local g
		g, s = Digestion.advance(s, 1, foods)
		total += g
	end
	local bulk = Digestion.advance(stomach, 100, foods)
	near(total, bulk, 1e-6)
	near(total, apple.mass + foods.bread.mass, 1e-6)
end)

test("partial digest gives proportional mass", function()
	local gained, left = Digestion.advance({ { foodId = "burger", remaining = 60 } }, 15, foods)
	near(gained, foods.burger.mass * 15 / foods.burger.digestSeconds)
	eq(#left, 1)
	near(left[1].remaining, 45)
end)

test("offline time beyond the stomach contents is not over-counted", function()
	local gained = Digestion.advance({ { foodId = "apple", remaining = 5 } }, 86400, foods)
	near(gained, apple.mass * 5 / apple.digestSeconds)
end)

test("unknown foods are dropped instead of crashing", function()
	local gained, left = Digestion.advance({ { foodId = "deleted_food", remaining = 10 } }, 5, foods)
	eq(gained, 0)
	eq(#left, 0)
end)

test("negative time does nothing", function()
	local gained, left = Digestion.advance({ { foodId = "apple", remaining = 5 } }, -100, foods)
	eq(gained, 0)
	near(left[1].remaining, 5)
end)

test("input stomach is not mutated", function()
	local stomach = { { foodId = "apple", remaining = 5 } }
	Digestion.advance(stomach, 3, foods)
	eq(stomach[1].remaining, 5)
end)

-- Config sanity --------------------------------------------------------------

test("every food is valid and better foods are better value", function()
	local lastRatio = 0
	local seen = {}
	for _, food in Config.Foods do
		assert(not seen[food.id], "duplicate food id " .. food.id)
		seen[food.id] = true
		assert(food.price > 0 and food.mass > 0 and food.digestSeconds > 0, food.id .. " has a non-positive value")
		local ratio = food.mass / food.price
		assert(ratio >= lastRatio, food.id .. " is worse value than the food before it")
		lastRatio = ratio
	end
end)

-- Formatting -----------------------------------------------------------------

test("number formatting", function()
	eq(Format.number(0), "0")
	eq(Format.number(999), "999")
	eq(Format.number(1000), "1K")
	eq(Format.number(1500), "1.5K")
	eq(Format.number(12345), "12.3K")
	eq(Format.number(100000), "100K")
	eq(Format.number(250000), "250K")
	eq(Format.number(1e6), "1M")
	eq(Format.number(2.5e9), "2.5B")
	eq(Format.number(-1500), "-1.5K")
	eq(Format.number(0 / 0), "0")
end)

test("duration formatting", function()
	eq(Format.duration(5), "5s")
	eq(Format.duration(65), "1m 05s")
	eq(Format.duration(3700), "1h 01m")
end)

print(string.format("%d passed, %d failed", passed, failed))
if failed > 0 then
	error("tests failed")
end
