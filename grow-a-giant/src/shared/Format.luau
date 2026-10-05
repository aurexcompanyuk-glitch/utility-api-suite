-- Turns big numbers into short labels: 1234 -> "1.23K", 5e9 -> "5B".

local Format = {}

local SUFFIXES = { "", "K", "M", "B", "T", "Qa", "Qi", "Sx", "Sp", "Oc", "No", "Dc" }

function Format.number(n: number): string
	if n ~= n then
		return "0"
	end
	local sign = if n < 0 then "-" else ""
	n = math.abs(n)
	if n < 1000 then
		return sign .. tostring(math.floor(n))
	end

	local tier = math.min(math.floor(math.log10(n) / 3), #SUFFIXES - 1)
	local scaled = n / 10 ^ (tier * 3)
	local text = if scaled >= 100
		then string.format("%d", math.floor(scaled))
		elseif scaled >= 10 then string.format("%.1f", math.floor(scaled * 10) / 10)
		else string.format("%.2f", math.floor(scaled * 100) / 100)
	-- 1.50K reads better as 1.5K (only trim decimals, never "100" -> "1")
	if string.find(text, ".", 1, true) then
		text = (string.gsub(text, "0+$", ""))
		text = (string.gsub(text, "%.$", ""))
	end
	return sign .. text .. SUFFIXES[tier + 1]
end

function Format.cash(n: number): string
	return "$" .. Format.number(n)
end

function Format.height(meters: number): string
	if meters < 1000 then
		return string.format("%.1fm", meters)
	end
	return Format.number(meters) .. "m"
end

function Format.duration(seconds: number): string
	seconds = math.max(0, math.ceil(seconds))
	if seconds < 60 then
		return seconds .. "s"
	end
	local minutes = seconds // 60
	if minutes < 60 then
		return string.format("%dm %02ds", minutes, seconds % 60)
	end
	return string.format("%dh %02dm", minutes // 60, minutes % 60)
end

return Format
