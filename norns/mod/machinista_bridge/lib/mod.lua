-- machinista_bridge: connects a norns instance to Machinista.
-- * Exports the native framebuffer for the MK3 displays. Uses reserved system
--   metro 34 (unused by norns core at 42df844) because script loads call
--   metro.free_all(), which frees script metros 1-30.
-- * Notes from the Norns Instrument arrive as OSC and play as MIDI (below);
--   KNOB 4/8 nudge reverb and output level through /machinista/param.
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

-- Notes from the Norns Instrument (the Sound's pads and patterns) arrive from
-- the bridge daemon as OSC /machinista/midi status data1 data2 (data2 = -1 for
-- a two-byte message). They are played as MIDI from the virtual device, so
-- scripts see them on port 1 like any MIDI input.
local function virtual_id()
  for id, d in pairs(midi.devices) do
    if d.name == "virtual" then return id end
  end
end
-- Notes held now (status|note -> true), so STOP in Machinista can release
-- any whose note-off got lost: /machinista/notes_off.
local held = {}
local function track(data)
  local kind, ch = data[1] & 0xf0, data[1] & 0x0f
  if kind == 0x90 and (data[3] or 0) > 0 then held[ch * 128 + data[2]] = true
  elseif kind == 0x80 or kind == 0x90 then held[ch * 128 + data[2]] = nil end
end
local osc_dispatch = _norns.osc.event
_norns.osc.event = function(path, args, from)
  if path == "/machinista/midi" then
    local id = virtual_id()
    if id ~= nil and args[1] ~= nil then
      local data = {args[1], args[2]}
      if args[3] ~= nil and args[3] >= 0 then data[3] = args[3] end
      track(data)
      _norns.midi.event(id, data)
    end
    return
  end
  if path == "/machinista/notes_off" then
    local id = virtual_id()
    if id ~= nil then
      for key in pairs(held) do
        _norns.midi.event(id, {0x80 | (key // 128), key % 128, 0})
      end
    end
    held = {}
    return
  end
  -- KNOB 4/8: /machinista/param <id> <steps> nudges a parameter (reverb
  -- return, or output level with SHIFT) by steps of 1% of its range.
  if path == "/machinista/param" then
    local id, steps = args[1], tonumber(args[2])
    if type(id) == "string" and steps ~= nil and params.lookup[id] ~= nil then
      params:delta(id, steps)
      -- Reverb return at its bottom (-inf) switches norns' reverb off, which
      -- saves its CPU; turning it up switches the reverb back on.
      if id == "rev_return_level" and params.lookup["reverb"] ~= nil then
        local on = params:get(id) > -math.huge
        if on ~= (params:get("reverb") == 2) then params:set("reverb", on and 2 or 1) end
      end
    end
    return
  end
  -- The MK3's keys and encoders go straight to norns. norns' own handler
  -- first calls the script's osc.event, and a script that assumes every OSC
  -- message is its own (amen indexes its voices by args[1]) raises an error
  -- there, so K3/E3 never arrived while amen was loaded.
  if path == "/remote/key" and #args > 1 then return _norns.key(args[1], args[2]) end
  if path == "/remote/enc" and #args > 1 then return _norns.enc(args[1], args[2]) end
  return osc_dispatch(path, args, from)
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
  -- A script resumed at startup runs init before norns has set
  -- _menu.redraw; amen calls it there and fails ("error: init"). Choosing
  -- the script from the menu never shows this, run-norns.sh restarts do.
  if _menu ~= nil and _menu.redraw == nil then _menu.redraw = function() end end
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
