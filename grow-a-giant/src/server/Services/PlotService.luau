--[[
	Builds the map (a ring of plots), hands each player a plot, and owns the
	placeholder Giant model standing on it.

	The Giant is made of plain blocks so Phase 1 needs no art. To swap in a
	real model later, replace buildGiantModel: anything works as long as the
	model's PrimaryPart sits at its feet, because ScaleTo grows the model
	around its pivot and that keeps the feet planted on the plot.
]]

local Workspace = game:GetService("Workspace")

local Shared = game:GetService("ReplicatedStorage").Shared
local Format = require(Shared.Format)
local GrowthMath = require(Shared.GrowthMath)

local PLOT_COUNT = 8
local PLOT_SIZE = 110
local RING_RADIUS = 230 -- plots are ~180 studs apart, room for a max-size Giant

type Plot = {
	index: number,
	base: BasePart,
	spawnCFrame: CFrame,
	owner: Player?,
	giant: Model?,
	label: TextLabel?,
	currentScale: number,
}

local PlotService = {}

local plots: { Plot } = {}
local plotByPlayer: { [Player]: Plot } = {}

local function part(props: { [string]: any }): Part
	local p = Instance.new("Part")
	p.Anchored = true
	p.TopSurface = Enum.SurfaceType.Smooth
	p.BottomSurface = Enum.SurfaceType.Smooth
	for key, value in props do
		(p :: any)[key] = value
	end
	return p
end

local function buildMap()
	local folder = Instance.new("Folder")
	folder.Name = "Plots"
	folder.Parent = Workspace

	-- Reuse the Baseplate from Studio's template if the place has one.
	if not Workspace:FindFirstChild("Ground") and not Workspace:FindFirstChild("Baseplate") then
		part({
			Name = "Ground",
			Size = Vector3.new(2048, 4, 2048),
			Position = Vector3.new(0, -2, 0),
			Color = Color3.fromRGB(90, 160, 80),
			Material = Enum.Material.Grass,
			Parent = Workspace,
		})
	end

	for index = 1, PLOT_COUNT do
		local angle = (index - 1) / PLOT_COUNT * math.pi * 2
		local center = Vector3.new(math.cos(angle) * RING_RADIUS, 0.5, math.sin(angle) * RING_RADIUS)
		-- Face the plot toward the middle of the map.
		local facing = CFrame.lookAt(center, Vector3.new(0, 0.5, 0))

		local base = part({
			Name = "Plot" .. index,
			Size = Vector3.new(PLOT_SIZE, 1, PLOT_SIZE),
			CFrame = facing,
			Color = Color3.fromRGB(200, 190, 160),
			Material = Enum.Material.Sand,
			Parent = folder,
		})

		table.insert(plots, {
			index = index,
			base = base,
			-- Players spawn at the front edge, looking back at their Giant.
			spawnCFrame = CFrame.lookAt(
				(facing * CFrame.new(0, 4, -PLOT_SIZE * 0.35)).Position,
				center + Vector3.new(0, 4, 0)
			),
			owner = nil,
			giant = nil,
			label = nil,
			currentScale = 1,
		})
	end
end

-- A 10-stud-tall blocky Giant. Root is an invisible part at the feet.
local function buildGiantModel(color: Color3): Model
	local model = Instance.new("Model")
	model.Name = "Giant"

	local root = part({
		Name = "Root",
		Size = Vector3.new(1, 0.2, 1),
		Transparency = 1,
		CanCollide = false,
		CFrame = CFrame.new(0, 0.1, 0),
		Parent = model,
	})
	model.PrimaryPart = root

	local skin = Color3.fromRGB(240, 200, 160)
	local pieces = {
		{ "LeftLeg", Vector3.new(1.4, 4, 1.4), Vector3.new(-0.8, 2, 0), color:Lerp(Color3.new(0, 0, 0), 0.4) },
		{ "RightLeg", Vector3.new(1.4, 4, 1.4), Vector3.new(0.8, 2, 0), color:Lerp(Color3.new(0, 0, 0), 0.4) },
		{ "Torso", Vector3.new(3.2, 3.5, 1.8), Vector3.new(0, 5.75, 0), color },
		{ "LeftArm", Vector3.new(1.1, 3.4, 1.1), Vector3.new(-2.2, 5.8, 0), skin },
		{ "RightArm", Vector3.new(1.1, 3.4, 1.1), Vector3.new(2.2, 5.8, 0), skin },
		{ "Head", Vector3.new(2.2, 2.2, 2.2), Vector3.new(0, 8.6, 0), skin },
		{ "LeftEye", Vector3.new(0.4, 0.4, 0.1), Vector3.new(-0.5, 8.9, -1.12), Color3.new(0.1, 0.1, 0.1) },
		{ "RightEye", Vector3.new(0.4, 0.4, 0.1), Vector3.new(0.5, 8.9, -1.12), Color3.new(0.1, 0.1, 0.1) },
	}
	for _, spec in pieces do
		part({
			Name = spec[1],
			Size = spec[2],
			CFrame = CFrame.new(spec[3]),
			Color = spec[4],
			Material = Enum.Material.SmoothPlastic,
			CanCollide = false,
			Parent = model,
		})
	end

	return model
end

local function makeLabel(head: BasePart): TextLabel
	local gui = Instance.new("BillboardGui")
	gui.Name = "GiantLabel"
	gui.Size = UDim2.fromOffset(240, 60)
	gui.StudsOffsetWorldSpace = Vector3.new(0, 3, 0)
	gui.AlwaysOnTop = true
	gui.MaxDistance = 600
	gui.Adornee = head
	gui.Parent = head

	local label = Instance.new("TextLabel")
	label.Size = UDim2.fromScale(1, 1)
	label.BackgroundTransparency = 1
	label.TextColor3 = Color3.new(1, 1, 1)
	label.TextStrokeTransparency = 0.3
	label.Font = Enum.Font.GothamBlack
	label.TextScaled = true
	label.Parent = gui
	return label
end

local function placeGiant(plot: Plot, model: Model)
	-- Stand on the plot surface, facing the same way as the plot.
	local top = plot.base.CFrame * CFrame.new(0, plot.base.Size.Y / 2, 0)
	model:PivotTo(top)
end

function PlotService.init()
	buildMap()
end

function PlotService.assign(player: Player): boolean
	for _, plot in plots do
		if not plot.owner then
			plot.owner = player
			plotByPlayer[player] = plot

			-- Each player gets a stable shirt color from their UserId.
			local hue = (player.UserId % 360) / 360
			local giant = buildGiantModel(Color3.fromHSV(hue, 0.6, 0.85))
			giant.Name = player.Name .. "_Giant"
			giant:SetAttribute("OwnerUserId", player.UserId)
			placeGiant(plot, giant)
			giant.Parent = Workspace.Plots
			plot.giant = giant
			plot.currentScale = 1
			plot.label = makeLabel(giant:FindFirstChild("Head") :: BasePart)
			return true
		end
	end
	return false
end

function PlotService.release(player: Player)
	local plot = plotByPlayer[player]
	if not plot then
		return
	end
	if plot.giant then
		plot.giant:Destroy()
	end
	plot.owner = nil
	plot.giant = nil
	plot.label = nil
	plotByPlayer[player] = nil
end

function PlotService.spawnCFrame(player: Player): CFrame?
	local plot = plotByPlayer[player]
	return plot and plot.spawnCFrame
end

-- Called every tick. Only rescales when the change is visible (>0.5%),
-- because ScaleTo touches every part in the model.
function PlotService.updateGiant(player: Player, height: number)
	local plot = plotByPlayer[player]
	if not plot or not plot.giant then
		return
	end

	local target = GrowthMath.visualScale(height)
	if math.abs(target - plot.currentScale) / plot.currentScale > 0.005 then
		plot.giant:ScaleTo(target)
		placeGiant(plot, plot.giant)
		plot.currentScale = target
	end

	if plot.label then
		plot.label.Text = player.DisplayName .. "'s Giant\n" .. Format.height(height)
	end
end

return PlotService
