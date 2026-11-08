-- machinista_bridge: connects a norns instance to Machinista.
-- * Exports the native framebuffer for the MK3 displays. Uses reserved system
--   metro 34 (unused by norns core at 42df844) because script loads call
--   metro.free_all(), which frees script metros 1-30.
-- * MIDI: puts norns' virtual MIDI device (the Machinista patchbay's port for
--   this instance) on MIDI port 1, where scripts look by default, and makes
--   MIDI the clock source so every instance follows Machinista's tempo and
--   start/stop. NORNS_MIDI_CLOCK=0 leaves the clock alone.
--   This hook runs before norns restores system.state, which then wins, so
--   it only matters for a new instance with no saved state; run-norns.sh
--   writes the same settings into system.state before every start. The clock
--   source can still be changed in the norns menu until the next start.
local mod = require "core/mods"
local export_ms = tonumber(os.getenv("NORNS_FRAME_EXPORT_MS") or "") or 100
local path = os.getenv("NORNS_FRAME_PATH") or "/frames/screen.png"
local midi_clock = os.getenv("NORNS_MIDI_CLOCK") ~= "0"
local timer = metro[34]

local function has_virtual()
  for _, d in pairs(midi.devices) do
    if d.name == "virtual" then return true end
  end
  return false
end

mod.hook.register("system_post_startup", "machinista_bridge", function()
  timer.time = export_ms / 1000
  timer.count = -1
  timer.event = function() _norns.screen_export_png(path) end
  timer:start()
  print("MACHINISTA_BRIDGE_FRAMES " .. export_ms .. "ms " .. path)

  if not has_virtual() then
    print("MACHINISTA_BRIDGE_MIDI none (no ALSA sequencer in the container)")
    return
  end
  if midi.vports[1].name == "none" then
    midi.vports[1].name = "virtual"
    midi.update_devices()
  end
  if midi_clock then
    -- clock.add_params() takes its default from the state at every script load.
    norns.state.clock.source = 2
    clock.set_source(2)
  end
  print("MACHINISTA_BRIDGE_MIDI port1=" .. midi.vports[1].name .. " clock=" .. norns.state.clock.source)
end)
