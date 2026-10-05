--[[
	Every tunable number for Phase 1 lives here, so balancing the game means
	editing this file and nothing else. The server reads it to decide what is
	allowed; the client reads it only to draw the shop.
]]

export type Food = {
	id: string,
	name: string,
	price: number, -- cash per item
	mass: number, -- mass the Giant gains once the item is fully digested
	digestSeconds: number, -- how long one item takes to digest
	color: Color3?, -- shop swatch (client only; nil when run outside Roblox)
}

local function rgb(r: number, g: number, b: number): Color3?
	-- Color3 doesn't exist when the offline tests run this file.
	if Color3 then
		return Color3.fromRGB(r, g, b)
	end
	return nil
end

local Config = {}

Config.StartingCash = 50
Config.StomachSlots = 4 -- items that can digest at the same time
Config.MaxBuyPerRequest = 100
Config.MaxInventoryPerFood = 9999

-- Food keeps digesting while you're offline, up to this long.
Config.MaxOfflineSeconds = 24 * 60 * 60

-- How often the server advances digestion and pays income.
Config.TickSeconds = 1
Config.AutosaveSeconds = 60

-- Each step up is more mass per cash, but takes longer to digest, so a better
-- food is always worth buying yet the stomach stays the bottleneck.
Config.Foods = {
	{ id = "apple", name = "Apple", price = 10, mass = 10, digestSeconds = 15, color = rgb(220, 60, 60) },
	{ id = "bread", name = "Bread", price = 60, mass = 70, digestSeconds = 30, color = rgb(214, 170, 100) },
	{ id = "burger", name = "Burger", price = 400, mass = 520, digestSeconds = 60, color = rgb(160, 90, 40) },
	{ id = "pizza", name = "Pizza", price = 2500, mass = 3600, digestSeconds = 100, color = rgb(240, 180, 60) },
	{ id = "cake", name = "Cake", price = 15000, mass = 24000, digestSeconds = 160, color = rgb(245, 160, 200) },
	{ id = "turkey", name = "Turkey", price = 100000, mass = 180000, digestSeconds = 240, color = rgb(190, 110, 50) },
	{
		id = "goldsteak",
		name = "Golden Steak",
		price = 750000,
		mass = 1500000,
		digestSeconds = 360,
		color = rgb(255, 215, 0),
	},
} :: { Food }

Config.FoodsById = {} :: { [string]: Food }
for _, food in Config.Foods do
	Config.FoodsById[food.id] = food
end

return Config
