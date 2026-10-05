-- Server entry point. Order matters: the map must exist before players get plots.

local Services = script.Parent.Services

require(Services.PlotService).init()
require(Services.GameService).init()

print("[GrowAGiant] Server started")
