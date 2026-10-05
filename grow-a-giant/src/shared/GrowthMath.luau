--[[
	The growth curve. Pure math with no Roblox APIs, so tests run it offline.

	mass   -> what food adds. Unbounded.
	height -> the number players brag about. Logarithmic in mass, so it keeps
	          climbing forever but each extra meter costs more food.
	scale  -> how big the 3D model is drawn. Eases toward a hard cap, so even a
	          Giant with an absurd height never outgrows its plot or the map.
	income -> cash per second, driven by height.
]]

local GrowthMath = {}

GrowthMath.BaseHeight = 10 -- meters at zero mass
GrowthMath.HeightPerLog = 25
GrowthMath.MassScale = 100

GrowthMath.MaxVisualScale = 12 -- model never exceeds 12x its starting size
GrowthMath.VisualSoftness = 150 -- meters of height to cover ~63% of the way to the cap

GrowthMath.BaseIncome = 1 -- cash per second at BaseHeight
GrowthMath.IncomeExponent = 2

function GrowthMath.heightFromMass(mass: number): number
	mass = math.max(mass, 0)
	return GrowthMath.BaseHeight + GrowthMath.HeightPerLog * math.log(1 + mass / GrowthMath.MassScale)
end

function GrowthMath.visualScale(height: number): number
	local grown = math.max(height - GrowthMath.BaseHeight, 0)
	local progress = 1 - math.exp(-grown / GrowthMath.VisualSoftness)
	return 1 + (GrowthMath.MaxVisualScale - 1) * progress
end

function GrowthMath.incomePerSecond(height: number): number
	local ratio = math.max(height, GrowthMath.BaseHeight) / GrowthMath.BaseHeight
	return GrowthMath.BaseIncome * ratio ^ GrowthMath.IncomeExponent
end

return GrowthMath
