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

-- Machinista's transport, as seen on the virtual MIDI device: true after
-- START/CONTINUE, false after STOP, nil before either. Machinista sends clock
-- ticks only while it plays.
local transport = nil
local last_tick = -1
-- PLAY after STOP is a CONTINUE (with a song position) from Machinista.
-- norns' MIDI clock ignores CONTINUE: its beat ran on while stopped, the
-- first tick after the pause is dropped, and the second puts the beat back
-- where the ticks left off. Every clock.sync() scheduled meanwhile then waits
-- for a beat that is far ahead. At that second tick, reschedule the waiting
-- syncs from the true beat (switching the clock source away and back is the
-- only way to reach norns' scheduler from Lua) and send the transport start
-- that norns only sends after a START.
local resync = 0
local function resume()
  if not (midi_clock and params.lookup["clock_source"] and params:string("clock_source") == "midi") then return end
  clock.set_source("internal")
  clock.set_source("midi")
  _norns.clock.start()
end
local dispatch = _norns.midi.event
_norns.midi.event = function(id, data)
  local d = midi.devices[id]
  if d ~= nil and d.name == "virtual" then
    local status = data[1]
    if status == 0xfa then transport = true; resync = 0
    elseif status == 0xfb then transport = true; resync = 2
    elseif status == 0xfc then transport = false; resync = 0
    elseif status == 0xf8 then
      last_tick = util.time()
      if resync > 0 then
        resync = resync - 1
        if resync == 0 then
          dispatch(id, data)
          return resume()
        end
      end
    end
  end
  return dispatch(id, data)
end

local function machinista_playing()
  if transport ~= nil then return transport end
  return last_tick >= 0 and util.time() - last_tick < 0.5
end

-- Many scripts (Awake among them) start running when they load and only obey
-- the transport after a START or STOP arrives. A script loaded while
-- Machinista is stopped gets its STOP at once, so it waits for PLAY.
mod.hook.register("script_post_init", "machinista_bridge transport", function()
  if midi_clock and params.lookup["clock_source"] and params:string("clock_source") == "midi"
     and not machinista_playing() and clock.transport.stop then
    clock.transport.stop()
    print("MACHINISTA_BRIDGE_TRANSPORT stopped (Machinista is stopped)")
  end
end)

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
