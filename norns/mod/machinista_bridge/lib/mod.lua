-- machinista_bridge: exports the native norns framebuffer for Machinista.
-- Uses reserved system metro 34 (unused by norns core at 42df844) because
-- script loads call metro.free_all(), which frees script metros 1-30.
local mod = require "core/mods"
local export_ms = tonumber(os.getenv("NORNS_FRAME_EXPORT_MS") or "") or 100
local path = os.getenv("NORNS_FRAME_PATH") or "/frames/screen.png"
local timer = metro[34]
mod.hook.register("system_post_startup", "machinista_bridge frames", function()
  timer.time = export_ms / 1000
  timer.count = -1
  timer.event = function() _norns.screen_export_png(path) end
  timer:start()
  print("MACHINISTA_BRIDGE_FRAMES " .. export_ms .. "ms " .. path)
end)
