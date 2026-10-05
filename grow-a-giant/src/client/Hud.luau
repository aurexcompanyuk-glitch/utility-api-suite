--[[
	The Phase 1 HUD, built in code: stats bar, food shop, stomach slots and
	toast messages. It only displays state the server sends and asks the
	server to do things; it never changes cash or mass itself.
]]

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local TweenService = game:GetService("TweenService")

local Shared = ReplicatedStorage:WaitForChild("Shared")
local Config = require(Shared:WaitForChild("Config"))
local Format = require(Shared:WaitForChild("Format"))

local Remotes = ReplicatedStorage:WaitForChild("Remotes")

local Hud = {}

local COLORS = {
	panel = Color3.fromRGB(28, 30, 40),
	panelLight = Color3.fromRGB(44, 47, 62),
	text = Color3.fromRGB(245, 245, 250),
	muted = Color3.fromRGB(170, 175, 195),
	cash = Color3.fromRGB(120, 230, 120),
	buy = Color3.fromRGB(60, 170, 90),
	feed = Color3.fromRGB(230, 140, 50),
	disabled = Color3.fromRGB(80, 82, 95),
	error = Color3.fromRGB(220, 70, 70),
	success = Color3.fromRGB(60, 170, 90),
	info = Color3.fromRGB(70, 120, 220),
}

local function make(className: string, props: { [string]: any }, children: { Instance }?): any
	local inst = Instance.new(className)
	for key, value in props do
		if key ~= "Parent" then
			(inst :: any)[key] = value
		end
	end
	if children then
		for _, child in children do
			child.Parent = inst
		end
	end
	inst.Parent = props.Parent
	return inst
end

local function corner(radius: number?): UICorner
	return make("UICorner", { CornerRadius = UDim.new(0, radius or 10) })
end

local function padding(px: number): UIPadding
	local p = UDim.new(0, px)
	return make("UIPadding", { PaddingTop = p, PaddingBottom = p, PaddingLeft = p, PaddingRight = p })
end

local function text(props: { [string]: any }): TextLabel
	props.BackgroundTransparency = props.BackgroundTransparency or 1
	props.TextColor3 = props.TextColor3 or COLORS.text
	props.Font = props.Font or Enum.Font.GothamBold
	props.TextScaled = if props.TextScaled == nil then true else props.TextScaled
	local maxSize = props.MaxTextSize or 28
	props.MaxTextSize = nil -- not a TextLabel property; it goes on the constraint
	return make("TextLabel", props, { make("UITextSizeConstraint", { MaxTextSize = maxSize }) })
end

local function button(label: string, color: Color3, props: { [string]: any }): TextButton
	props.Text = label
	props.BackgroundColor3 = color
	props.TextColor3 = COLORS.text
	props.Font = Enum.Font.GothamBold
	props.TextScaled = true
	props.AutoButtonColor = true
	return make("TextButton", props, { corner(8), make("UITextSizeConstraint", { MaxTextSize = 18 }) })
end

function Hud.start()
	local player = Players.LocalPlayer
	local gui = make("ScreenGui", {
		Name = "GrowAGiantHud",
		ResetOnSpawn = false,
		IgnoreGuiInset = false,
		ZIndexBehavior = Enum.ZIndexBehavior.Sibling,
		Parent = player:WaitForChild("PlayerGui"),
	})

	-----------------------------------------------------------------------
	-- Stats bar (top center)
	-----------------------------------------------------------------------
	local statsBar = make("Frame", {
		AnchorPoint = Vector2.new(0.5, 0),
		Position = UDim2.new(0.5, 0, 0, 8),
		Size = UDim2.new(0.5, 0, 0, 56),
		BackgroundColor3 = COLORS.panel,
		BackgroundTransparency = 0.15,
		Parent = gui,
	}, {
		corner(12),
		padding(6),
		make("UISizeConstraint", { MinSize = Vector2.new(300, 0), MaxSize = Vector2.new(560, math.huge) }),
		make("UIListLayout", {
			FillDirection = Enum.FillDirection.Horizontal,
			HorizontalAlignment = Enum.HorizontalAlignment.Center,
			VerticalAlignment = Enum.VerticalAlignment.Center,
			Padding = UDim.new(0, 12),
		}),
	})
	local cashLabel = text({ Size = UDim2.new(0.4, 0, 1, 0), TextColor3 = COLORS.cash, Text = "$0", Parent = statsBar })
	local incomeLabel =
		text({ Size = UDim2.new(0.25, 0, 0.7, 0), TextColor3 = COLORS.muted, Text = "+0/s", Parent = statsBar })
	local heightLabel = text({ Size = UDim2.new(0.3, 0, 1, 0), Text = "10.0m", Parent = statsBar })

	local savingWarning = text({
		AnchorPoint = Vector2.new(0.5, 0),
		Position = UDim2.new(0.5, 0, 0, 68),
		Size = UDim2.new(0.5, 0, 0, 20),
		TextColor3 = COLORS.error,
		Text = "Saving unavailable - progress won't be kept",
		MaxTextSize = 16,
		Visible = false,
		Parent = gui,
	})

	-----------------------------------------------------------------------
	-- Food shop (right side)
	-----------------------------------------------------------------------
	local shop = make("Frame", {
		AnchorPoint = Vector2.new(1, 0.5),
		Position = UDim2.new(1, -10, 0.5, 0),
		Size = UDim2.new(0.3, 0, 0.6, 0),
		BackgroundColor3 = COLORS.panel,
		BackgroundTransparency = 0.1,
		Parent = gui,
	}, {
		corner(12),
		padding(8),
		make("UISizeConstraint", { MinSize = Vector2.new(260, 220), MaxSize = Vector2.new(380, 600) }),
	})
	text({ Size = UDim2.new(1, 0, 0, 28), Text = "FOOD SHOP", Font = Enum.Font.GothamBlack, Parent = shop })

	local list = make("ScrollingFrame", {
		Position = UDim2.new(0, 0, 0, 34),
		Size = UDim2.new(1, 0, 1, -34),
		BackgroundTransparency = 1,
		BorderSizePixel = 0,
		ScrollBarThickness = 6,
		AutomaticCanvasSize = Enum.AutomaticSize.Y,
		CanvasSize = UDim2.new(),
		Parent = shop,
	}, {
		make("UIListLayout", { Padding = UDim.new(0, 6), SortOrder = Enum.SortOrder.LayoutOrder }),
	})

	type Row = { buy: TextButton, feed: TextButton, owned: TextLabel }
	local rows: { [string]: Row } = {}

	for order, food in Config.Foods do
		local row = make("Frame", {
			Size = UDim2.new(1, -8, 0, 64),
			BackgroundColor3 = COLORS.panelLight,
			LayoutOrder = order,
			Parent = list,
		}, { corner(8) })

		make("Frame", {
			Position = UDim2.fromOffset(8, 8),
			Size = UDim2.fromOffset(48, 48),
			BackgroundColor3 = food.color or COLORS.muted,
			Parent = row,
		}, { corner(24) })

		text({
			Position = UDim2.fromOffset(64, 6),
			Size = UDim2.new(1, -150, 0, 22),
			Text = food.name,
			TextXAlignment = Enum.TextXAlignment.Left,
			MaxTextSize = 18,
			Parent = row,
		})
		text({
			Position = UDim2.fromOffset(64, 28),
			Size = UDim2.new(1, -150, 0, 14),
			Text = string.format("%s  •  +%s mass", Format.cash(food.price), Format.number(food.mass)),
			TextColor3 = COLORS.muted,
			TextXAlignment = Enum.TextXAlignment.Left,
			Font = Enum.Font.Gotham,
			MaxTextSize = 14,
			Parent = row,
		})
		local owned = text({
			Position = UDim2.fromOffset(64, 44),
			Size = UDim2.new(1, -150, 0, 14),
			Text = "Owned: 0  •  " .. Format.duration(food.digestSeconds),
			TextColor3 = COLORS.muted,
			TextXAlignment = Enum.TextXAlignment.Left,
			Font = Enum.Font.Gotham,
			MaxTextSize = 14,
			Parent = row,
		})

		local buy = button("Buy", COLORS.buy, {
			AnchorPoint = Vector2.new(1, 0),
			Position = UDim2.new(1, -8, 0, 6),
			Size = UDim2.fromOffset(72, 24),
			Parent = row,
		})
		local feed = button("Feed", COLORS.feed, {
			AnchorPoint = Vector2.new(1, 1),
			Position = UDim2.new(1, -8, 1, -6),
			Size = UDim2.fromOffset(72, 24),
			Parent = row,
		})

		buy.Activated:Connect(function()
			Remotes.BuyFood:FireServer(food.id, 1)
		end)
		feed.Activated:Connect(function()
			Remotes.FeedFood:FireServer(food.id)
		end)

		rows[food.id] = { buy = buy, feed = feed, owned = owned }
	end

	-----------------------------------------------------------------------
	-- Stomach (bottom center)
	-----------------------------------------------------------------------
	local stomachFrame = make("Frame", {
		AnchorPoint = Vector2.new(0.5, 1),
		Position = UDim2.new(0.5, 0, 1, -12),
		Size = UDim2.fromOffset(Config.StomachSlots * 118 + 16, 92),
		BackgroundColor3 = COLORS.panel,
		BackgroundTransparency = 0.15,
		Parent = gui,
	}, { corner(12), padding(8) })
	text({ Size = UDim2.new(1, 0, 0, 16), Text = "STOMACH", TextColor3 = COLORS.muted, MaxTextSize = 14, Parent = stomachFrame })
	local slotHolder = make("Frame", {
		Position = UDim2.fromOffset(0, 20),
		Size = UDim2.new(1, 0, 1, -20),
		BackgroundTransparency = 1,
		Parent = stomachFrame,
	}, {
		make("UIListLayout", {
			FillDirection = Enum.FillDirection.Horizontal,
			HorizontalAlignment = Enum.HorizontalAlignment.Center,
			Padding = UDim.new(0, 6),
		}),
	})

	type Slot = { fill: Frame, name: TextLabel, time: TextLabel, tween: Tween? }
	local slots: { Slot } = {}
	for i = 1, Config.StomachSlots do
		local slot = make("Frame", {
			Size = UDim2.fromOffset(112, 52),
			BackgroundColor3 = COLORS.panelLight,
			ClipsDescendants = true,
			LayoutOrder = i,
			Parent = slotHolder,
		}, { corner(8) })
		local fill = make("Frame", {
			Size = UDim2.fromScale(0, 1),
			BackgroundColor3 = COLORS.feed,
			BackgroundTransparency = 0.4,
			BorderSizePixel = 0,
			Parent = slot,
		})
		local name = text({ Size = UDim2.new(1, 0, 0.55, 0), Text = "Empty", TextColor3 = COLORS.muted, MaxTextSize = 16, Parent = slot })
		local time = text({
			Position = UDim2.fromScale(0, 0.55),
			Size = UDim2.new(1, 0, 0.4, 0),
			Text = "",
			Font = Enum.Font.Gotham,
			MaxTextSize = 13,
			Parent = slot,
		})
		slots[i] = { fill = fill, name = name, time = time, tween = nil }
	end

	-----------------------------------------------------------------------
	-- Toasts
	-----------------------------------------------------------------------
	local toastHolder = make("Frame", {
		AnchorPoint = Vector2.new(0.5, 0),
		Position = UDim2.new(0.5, 0, 0, 96),
		Size = UDim2.new(0.5, 0, 0, 200),
		BackgroundTransparency = 1,
		Parent = gui,
	}, {
		make("UIListLayout", { HorizontalAlignment = Enum.HorizontalAlignment.Center, Padding = UDim.new(0, 6) }),
	})

	local function toast(message: string, kind: string)
		local frame = make("Frame", {
			Size = UDim2.new(1, 0, 0, 36),
			BackgroundColor3 = COLORS[kind] or COLORS.info,
			Parent = toastHolder,
		}, { corner(8), make("UISizeConstraint", { MaxSize = Vector2.new(480, 36) }) })
		local label = text({ Size = UDim2.fromScale(1, 1), Text = message, MaxTextSize = 16, Parent = frame })
		make("UIPadding", { PaddingLeft = UDim.new(0, 10), PaddingRight = UDim.new(0, 10), Parent = label })
		task.delay(3.5, function()
			local info = TweenInfo.new(0.4)
			TweenService:Create(frame, info, { BackgroundTransparency = 1 }):Play()
			TweenService:Create(label, info, { TextTransparency = 1 }):Play()
			task.wait(0.4)
			frame:Destroy()
		end)
	end
	Remotes.Notify.OnClientEvent:Connect(toast)

	-----------------------------------------------------------------------
	-- State from the server
	-----------------------------------------------------------------------
	Remotes.StateSync.OnClientEvent:Connect(function(state)
		cashLabel.Text = Format.cash(state.cash)
		incomeLabel.Text = "+" .. Format.number(state.income) .. "/s"
		heightLabel.Text = "📏 " .. Format.height(state.height)
		savingWarning.Visible = not state.saving

		local full = #state.stomach >= state.stomachSlots
		for _, food in Config.Foods do
			local row = rows[food.id]
			local count = state.inventory[food.id] or 0
			row.owned.Text = string.format("Owned: %d  •  %s", count, Format.duration(food.digestSeconds))
			row.buy.BackgroundColor3 = if state.cash >= food.price then COLORS.buy else COLORS.disabled
			row.feed.BackgroundColor3 = if count > 0 and not full then COLORS.feed else COLORS.disabled
		end

		for i, slot in slots do
			local item = state.stomach[i]
			local food = item and Config.FoodsById[item.foodId]
			if food then
				slot.name.Text = food.name
				slot.name.TextColor3 = COLORS.text
				slot.time.Text = Format.duration(item.remaining)
				slot.fill.BackgroundColor3 = food.color or COLORS.feed
				-- Animate over the next second so the bar fills smoothly.
				local progress = 1 - item.remaining / food.digestSeconds
				if slot.tween then
					slot.tween:Cancel()
				end
				slot.tween = TweenService:Create(slot.fill, TweenInfo.new(1, Enum.EasingStyle.Linear), {
					Size = UDim2.fromScale(progress, 1),
				})
				slot.tween:Play()
			else
				if slot.tween then
					slot.tween:Cancel()
					slot.tween = nil
				end
				slot.name.Text = "Empty"
				slot.name.TextColor3 = COLORS.muted
				slot.time.Text = ""
				slot.fill.Size = UDim2.fromScale(0, 1)
			end
		end
	end)

	Remotes.ClientReady:FireServer()
end

return Hud
