--[[
	The core loop: buy food -> feed the Giant -> food digests into mass ->
	mass sets height -> height pays cash.

	The server is the only place any of this is decided. The client only asks
	("buy 3 apples", "feed an apple"); every request is type-checked,
	rate-limited and validated against the player's real data before anything
	changes, so an exploiter firing remotes by hand gets nothing extra.
]]

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")

local Shared = ReplicatedStorage.Shared
local Config = require(Shared.Config)
local Digestion = require(Shared.Digestion)
local Format = require(Shared.Format)
local GrowthMath = require(Shared.GrowthMath)

local DataService = require(script.Parent.DataService)
local PlotService = require(script.Parent.PlotService)

local Remotes = ReplicatedStorage.Remotes

local GameService = {}

local profiles: { [Player]: DataService.Profile } = {}

---------------------------------------------------------------------------
-- Helpers
---------------------------------------------------------------------------

local function notify(player: Player, message: string, kind: string?)
	Remotes.Notify:FireClient(player, message, kind or "info")
end

local function heightOf(data: DataService.Data): number
	return GrowthMath.heightFromMass(data.mass)
end

-- Allows `limit` requests per `window` seconds per player per remote.
local function makeRateLimiter(limit: number, window: number)
	local buckets: { [Player]: { count: number, start: number } } = {}
	Players.PlayerRemoving:Connect(function(player)
		buckets[player] = nil
	end)
	return function(player: Player): boolean
		local now = os.clock()
		local bucket = buckets[player]
		if not bucket or now - bucket.start >= window then
			buckets[player] = { count = 1, start = now }
			return true
		end
		bucket.count += 1
		return bucket.count <= limit
	end
end

local function updateLeaderstats(player: Player, data: DataService.Data)
	local stats = player:FindFirstChild("leaderstats")
	if not stats then
		return
	end
	-- Height is a number (in whole meters) so the player list sorts by it.
	(stats:FindFirstChild("Height") :: IntValue).Value = math.floor(heightOf(data));
	(stats:FindFirstChild("Cash") :: StringValue).Value = Format.cash(data.cash)
end

local function sync(player: Player)
	local profile = profiles[player]
	if not profile then
		return
	end
	local data = profile.data
	local height = heightOf(data)
	Remotes.StateSync:FireClient(player, {
		cash = data.cash,
		mass = data.mass,
		height = height,
		income = GrowthMath.incomePerSecond(height),
		inventory = data.inventory,
		stomach = data.stomach,
		stomachSlots = Config.StomachSlots,
		saving = profile.canSave,
	})
	updateLeaderstats(player, data)
	PlotService.updateGiant(player, height)
end

---------------------------------------------------------------------------
-- Remote handlers (all input is untrusted)
---------------------------------------------------------------------------

local canBuy = makeRateLimiter(10, 1)
local canFeed = makeRateLimiter(10, 1)

local function onBuyFood(player: Player, foodId: unknown, amount: unknown)
	if not canBuy(player) then
		return
	end
	local profile = profiles[player]
	if not profile then
		return
	end
	if type(foodId) ~= "string" or type(amount) ~= "number" then
		return
	end
	local food = Config.FoodsById[foodId]
	-- amount ~= amount rejects NaN; the floor check rejects 1.5 and inf.
	if not food or amount ~= amount or amount < 1 or amount > Config.MaxBuyPerRequest or amount % 1 ~= 0 then
		return
	end

	local data = profile.data
	local owned = data.inventory[foodId] or 0
	amount = math.min(amount, Config.MaxInventoryPerFood - owned)
	if amount < 1 then
		notify(player, "You can't carry any more " .. food.name .. ".", "error")
		return
	end

	local cost = food.price * amount
	if data.cash < cost then
		notify(player, "Not enough cash.", "error")
		return
	end

	data.cash -= cost
	data.inventory[foodId] = owned + amount
	sync(player)
end

local function onFeedFood(player: Player, foodId: unknown)
	if not canFeed(player) then
		return
	end
	local profile = profiles[player]
	if not profile or type(foodId) ~= "string" then
		return
	end
	local food = Config.FoodsById[foodId]
	if not food then
		return
	end

	local data = profile.data
	local owned = data.inventory[foodId] or 0
	if owned < 1 then
		notify(player, "You don't have any " .. food.name .. ".", "error")
		return
	end
	if #data.stomach >= Config.StomachSlots then
		notify(player, "Your Giant's stomach is full. Wait for it to digest!", "error")
		return
	end

	data.inventory[foodId] = if owned == 1 then nil else owned - 1
	table.insert(data.stomach, { foodId = foodId, remaining = food.digestSeconds })
	sync(player)
end

---------------------------------------------------------------------------
-- Player lifecycle
---------------------------------------------------------------------------

local function moveToPlot(player: Player, character: Model)
	local spawnAt = PlotService.spawnCFrame(player)
	if not spawnAt then
		return
	end
	character:WaitForChild("HumanoidRootPart", 10)
	if character.Parent then
		character:PivotTo(spawnAt)
	end
end

local function onPlayerAdded(player: Player)
	local stats = Instance.new("Folder")
	stats.Name = "leaderstats"
	local heightStat = Instance.new("IntValue")
	heightStat.Name = "Height"
	heightStat.Parent = stats
	local cashStat = Instance.new("StringValue")
	cashStat.Name = "Cash"
	cashStat.Value = "..."
	cashStat.Parent = stats
	stats.Parent = player

	if not PlotService.assign(player) then
		player:Kick("This server is full, please join another one.")
		return
	end
	player.CharacterAdded:Connect(function(character)
		moveToPlot(player, character)
	end)
	if player.Character then
		task.spawn(moveToPlot, player, player.Character)
	end

	local profile = DataService.load(player)
	if not player.Parent then
		-- Left while loading: hand the lock straight back.
		DataService.save(player, profile, true)
		return
	end

	-- Catch up on digestion that happened while the player was away.
	local data = profile.data
	local away = math.clamp(os.time() - data.lastSeen, 0, Config.MaxOfflineSeconds)
	local gained, stomach = Digestion.advance(data.stomach, away, Config.FoodsById)
	data.mass += gained
	data.stomach = stomach
	data.lastSeen = os.time()

	profiles[player] = profile
	if gained > 0 then
		notify(player, string.format("Welcome back! Your Giant digested %s mass while you were away.", Format.number(gained)), "success")
	end
	if not profile.canSave then
		notify(player, "Saving is unavailable right now. Progress this session won't be kept.", "error")
	end
	sync(player)
end

local function onPlayerRemoving(player: Player)
	local profile = profiles[player]
	profiles[player] = nil
	PlotService.release(player)
	if profile then
		DataService.save(player, profile, true)
	end
end

---------------------------------------------------------------------------
-- Main loop
---------------------------------------------------------------------------

local function tick(dt: number)
	for player, profile in profiles do
		local data = profile.data
		local gained, stomach = Digestion.advance(data.stomach, dt, Config.FoodsById)
		data.mass += gained
		data.stomach = stomach
		data.cash += GrowthMath.incomePerSecond(heightOf(data)) * dt
		sync(player)
	end
end

function GameService.init()
	Remotes.BuyFood.OnServerEvent:Connect(onBuyFood)
	Remotes.FeedFood.OnServerEvent:Connect(onFeedFood)
	Remotes.ClientReady.OnServerEvent:Connect(sync)

	Players.PlayerAdded:Connect(onPlayerAdded)
	Players.PlayerRemoving:Connect(onPlayerRemoving)
	for _, player in Players:GetPlayers() do
		task.spawn(onPlayerAdded, player)
	end

	task.spawn(function()
		local last = os.clock()
		while true do
			task.wait(Config.TickSeconds)
			local now = os.clock()
			tick(now - last)
			last = now
		end
	end)

	task.spawn(function()
		while true do
			task.wait(Config.AutosaveSeconds)
			for player, profile in profiles do
				task.spawn(DataService.save, player, profile)
			end
		end
	end)

	-- Testing shortcuts, only in Studio. From the Studio command bar while
	-- playing (server view):  _G.GiantCheat("YourName", 1e6, 1e5)
	if RunService:IsStudio() then
		_G.GiantCheat = function(name: string, cash: number?, mass: number?)
			local player = Players:FindFirstChild(name) :: Player?
			local profile = player and profiles[player]
			if not player or not profile then
				warn("No loaded player named " .. tostring(name))
				return
			end
			profile.data.cash += cash or 0
			profile.data.mass += mass or 0
			sync(player)
		end
	end

	game:BindToClose(function()
		local pending = 0
		for player, profile in profiles do
			pending += 1
			task.spawn(function()
				DataService.save(player, profile, true)
				pending -= 1
			end)
		end
		local deadline = os.clock() + 25
		while pending > 0 and os.clock() < deadline do
			task.wait(0.1)
		end
	end)
end

return GameService
