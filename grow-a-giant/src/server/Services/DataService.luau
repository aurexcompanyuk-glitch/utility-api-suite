--[[
	Loads and saves each player's data with DataStoreService.

	- Session lock: a save records which server owns the data, so if a player
	  hops servers quickly the new server waits instead of loading stale data
	  and then overwriting newer progress.
	- Retries with backoff on DataStore errors.
	- If DataStores are unavailable (e.g. Studio without "Enable Studio Access
	  to API Services"), the player still gets to play, but nothing is saved
	  and the server never overwrites their real data with a blank profile.
]]

local DataStoreService = game:GetService("DataStoreService")
local RunService = game:GetService("RunService")

local Config = require(game:GetService("ReplicatedStorage").Shared.Config)

local STORE_NAME = "GrowAGiant_PlayerData_v1"
local LOCK_EXPIRY_SECONDS = Config.AutosaveSeconds * 5
local LOAD_ATTEMPTS = 6
local SAVE_ATTEMPTS = 4

export type Data = {
	version: number,
	cash: number,
	mass: number,
	inventory: { [string]: number },
	stomach: { { foodId: string, remaining: number } },
	lastSeen: number,
}

export type Profile = {
	data: Data,
	canSave: boolean, -- false when the store failed to load; never save then
	released: boolean,
}

local DataService = {}

local store: DataStore? = nil
do
	local ok, result = pcall(function()
		return DataStoreService:GetDataStore(STORE_NAME)
	end)
	if ok then
		store = result
	else
		warn("[DataService] DataStores unavailable, progress will not save:", result)
	end
end

local function defaultData(): Data
	return {
		version = 1,
		cash = Config.StartingCash,
		mass = 0,
		inventory = {},
		stomach = {},
		lastSeen = os.time(),
	}
end

-- Fills in any field a saved profile is missing, so adding a field in a
-- later phase never crashes on old saves.
local function reconcile(saved: any): Data
	local data = defaultData()
	if type(saved) ~= "table" then
		return data
	end
	for key, value in saved do
		if data[key] ~= nil and type(value) == type(data[key]) then
			data[key] = value
		end
	end
	return data
end

local function deepCopy<T>(value: T): T
	if type(value) ~= "table" then
		return value
	end
	local copy = {}
	for k, v in value :: any do
		copy[k] = deepCopy(v)
	end
	return copy :: any
end

local function keyFor(userId: number): string
	return "player_" .. userId
end

-- Always returns a profile. If loading failed, canSave is false so the
-- blank fallback data can never overwrite the player's real save.
function DataService.load(player: Player): Profile
	if not store then
		return { data = defaultData(), canSave = false, released = false }
	end

	local key = keyFor(player.UserId)
	local jobId = if RunService:IsStudio() then "studio" else game.JobId

	for attempt = 1, LOAD_ATTEMPTS do
		local lockedElsewhere = false
		local ok, result = pcall(function()
			return store:UpdateAsync(key, function(old)
				local now = os.time()
				if
					type(old) == "table"
					and type(old.lock) == "table"
					and old.lock.jobId ~= jobId
					and now - (old.lock.time or 0) < LOCK_EXPIRY_SECONDS
					and attempt < LOAD_ATTEMPTS -- on the last try, take over a stuck lock
				then
					lockedElsewhere = true
					return nil -- cancel the write and try again shortly
				end
				local data = reconcile(type(old) == "table" and old.data or nil)
				return { data = data, lock = { jobId = jobId, time = now } }
			end)
		end)

		if ok and not lockedElsewhere and type(result) == "table" then
			return { data = reconcile(result.data), canSave = true, released = false }
		end

		if not ok then
			warn(string.format("[DataService] Load attempt %d for %s failed: %s", attempt, player.Name, result))
		end
		if not player.Parent then
			break
		end
		task.wait(if lockedElsewhere then 5 else 2 ^ attempt)
	end

	warn("[DataService] Could not load data for " .. player.Name .. "; playing without saving")
	return { data = defaultData(), canSave = false, released = false }
end

-- release = true when the player is leaving, so the next server can load
-- immediately instead of waiting for the lock to expire.
function DataService.save(player: Player, profile: Profile, release: boolean?): boolean
	if not store or not profile.canSave or profile.released then
		return false
	end
	if release then
		profile.released = true
	end

	local key = keyFor(player.UserId)
	local jobId = if RunService:IsStudio() then "studio" else game.JobId
	profile.data.lastSeen = os.time()
	local snapshot = deepCopy(profile.data)

	for attempt = 1, SAVE_ATTEMPTS do
		local ok, err = pcall(function()
			store:UpdateAsync(key, function(old)
				-- Another server stole the lock (we were stuck): don't clobber it.
				if type(old) == "table" and type(old.lock) == "table" and old.lock.jobId ~= jobId then
					return nil
				end
				return {
					data = snapshot,
					lock = if release then nil else { jobId = jobId, time = os.time() },
				}
			end)
		end)
		if ok then
			return true
		end
		warn(string.format("[DataService] Save attempt %d for %s failed: %s", attempt, player.Name, err))
		task.wait(2 ^ attempt)
	end
	return false
end

return DataService
