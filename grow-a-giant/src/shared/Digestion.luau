--[[
	Advances a stomach by some number of seconds. Pure, so the same function
	handles the live 1-second tick and a whole night of offline time.

	Every item in the stomach digests at the same time, each at a steady rate
	of food.mass / food.digestSeconds, so a half-digested burger has given the
	Giant exactly half a burger of mass.
]]

export type StomachItem = {
	foodId: string,
	remaining: number, -- seconds left until fully digested
}

type FoodLike = { mass: number, digestSeconds: number }

local Digestion = {}

-- Returns the mass gained and a new stomach with finished items removed.
-- Items whose food no longer exists are dropped (e.g. removed from Config).
function Digestion.advance(
	stomach: { StomachItem },
	seconds: number,
	foodsById: { [string]: FoodLike }
): (number, { StomachItem })
	local gained = 0
	local left: { StomachItem } = {}
	seconds = math.max(seconds, 0)

	for _, item in stomach do
		local food = foodsById[item.foodId]
		if food then
			local step = math.min(seconds, item.remaining)
			gained += food.mass * (step / food.digestSeconds)
			local remaining = item.remaining - step
			if remaining > 1e-6 then
				table.insert(left, { foodId = item.foodId, remaining = remaining })
			end
		end
	end

	return gained, left
end

return Digestion
