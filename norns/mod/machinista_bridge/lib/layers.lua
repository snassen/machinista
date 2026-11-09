-- MIDI layers from Machinista (DISPLAY 4/8 in NORNS mode) applied to
-- parameters, so a mapping doesn't depend on norns' PMAP (which belongs to
-- one script and is gone after switching scripts).
--
-- Machinista sends layer L's controls as CC on channel 1:
--   keys  CC 102 + 6(L-1) + 0..2  (127 on, 0 off)
--   knobs CC 102 + 6(L-1) + 3..5  (0-127)
-- Layer 1 is the same on every norns and every script (SYSTEM below: norns'
-- reverb and compressor). Layers 2 and 3 come from maps/<folder>.map (the
-- script's folder in dust/code), a Lua table chosen per script:
--   return { [2] = { {id=..., label=...}, ... six controls ... }, [3] = {...} }
-- A control is {id = "param", label = "NAME"}; keys may add on=/off= values,
-- and on_label=/off_label=. The CC is also passed on to the script as MIDI,
-- so learned PMAP mappings keep working.
-- The labels for the MK3 display go to <frames>/layers.txt:
--   layer \t control(1-6) \t off-label \t on-label
local M = {}

local FIRST_CC = 102
local MAPS = _path.code .. "machinista_bridge/maps/"
local frames = (os.getenv("NORNS_FRAME_PATH") or "/frames/screen.png"):match("^(.*)/") or "/frames"

local T = require "core/paramset"

local function set_fraction(id, f)
  local i = params.lookup[id]
  if i == nil then return end
  local p = params.params[i]
  f = util.clamp(f, 0, 1)
  if p.t == T.tCONTROL or p.t == T.tTAPER then
    params:set_raw(id, f)
  elseif p.t == T.tNUMBER then
    params:set(id, util.round(p.min + f * (p.max - p.min)))
  elseif p.t == T.tOPTION then
    params:set(id, 1 + util.round(f * (#p.options - 1)))
  elseif p.t == T.tBINARY then
    params:set(id, f >= 0.5 and 1 or 0)
  elseif p.t == T.tTRIGGER then
    if f > 0 then params:set(id, 1) end
  end
end

local function set_value(id, v)
  if params.lookup[id] ~= nil then params:set(id, v) end
end

local function default(id)
  local i = params.lookup[id]
  local p = i and params.params[i]
  if p and p.controlspec then return p.controlspec.default end
  return p and p.default
end

-- Layer 1, agreed 2026-11-09. Each entry: label(s) and apply(value 0-127).
local SYSTEM = {
  { off_label = "LF 200HZ", on_label = "LF 1KHZ",
    apply = function(v) set_value("rev_lf_fc", v > 0 and 1000 or 200) end },
  { off_label = "HF 6KHZ", on_label = "HF 20KHZ",
    apply = function(v) set_value("rev_hf_damping", v > 0 and 20000 or 6000) end },
  { off_label = "COMP FAST", on_label = "COMP SLOW",
    apply = function(v)
      set_value("comp_attack", v > 0 and 80 or 5)
      set_value("comp_release", v > 0 and 300 or (default("comp_release") or 50))
    end },
  { label = "MID TIME", apply = function(v) set_fraction("rev_mid_time", v / 127) end },
  { label = "COMPRESS",
    apply = function(v)
      -- One knob: off at the left; turning up switches the compressor on and
      -- raises mix, ratio, threshold depth and make-up gain together.
      if v == 0 then set_value("compressor", 1) return end
      local f = v / 127
      set_value("compressor", 2)
      set_value("comp_mix", f)
      set_value("comp_ratio", 1 + 19 * f)
      set_value("comp_threshold", -40 * f)
      set_value("comp_post_gain", 30 * f)
    end },
  { label = "REV SEND",
    -- How much of the script's engine and softcut goes into the reverb.
    apply = function(v)
      set_fraction("rev_eng_input", v / 127)
      set_fraction("rev_cut_input", v / 127)
    end },
}

local script_map = {}

local function load_map(name)
  script_map = {}
  if not name or name == "" then return end
  local file = MAPS .. name .. ".map"
  if not util.file_exists(file) then return end
  local ok, map = pcall(dofile, file)
  if ok and type(map) == "table" then
    script_map = map
  else
    print("MACHINISTA_BRIDGE_MAP failed " .. file .. ": " .. tostring(map))
  end
end

local function label_of(entry, on)
  if entry == nil then return "" end
  local text = on and (entry.on_label or entry.label) or (entry.off_label or entry.label)
  return tostring(text or entry.id or ""):gsub("[\t\n]", " "):upper()
end

function M.write_labels()
  local lines = {}
  for layer = 1, 3 do
    local controls = layer == 1 and SYSTEM or (script_map[layer] or {})
    for control = 1, 6 do
      local entry = controls[control]
      table.insert(lines, table.concat({layer, control, label_of(entry, false), label_of(entry, true)}, "\t"))
    end
  end
  local path = frames .. "/layers.txt"
  local f = io.open(path .. ".tmp", "w")
  if f then
    f:write(table.concat(lines, "\n") .. "\n")
    f:close()
    os.rename(path .. ".tmp", path)
  end
end

-- A new script is running: its map (if any) and labels.
function M.script_loaded()
  -- Maps are named after the script's folder in dust/code (3d's script is circle.lua).
  local folder = (norns.state.script or ""):match("/code/([^/]+)/")
  load_map(folder or norns.state.shortname)
  M.write_labels()
end

-- CC from Machinista: true when it belongs to a layer (it is passed on to
-- the script as MIDI either way).
function M.cc(number, value)
  local index = number - FIRST_CC
  if index < 0 or index >= 18 then return false end
  local layer, control = index // 6 + 1, index % 6 + 1
  if layer == 1 then
    local ok, err = pcall(SYSTEM[control].apply, value)
    if not ok then print("MACHINISTA_BRIDGE_LAYER " .. tostring(err)) end
    return true
  end
  local entry = (script_map[layer] or {})[control]
  if entry and entry.id then
    local ok, err = pcall(function()
      if control <= 3 and (entry.on ~= nil or entry.off ~= nil) then
        set_value(entry.id, value > 0 and entry.on or entry.off)
      else
        set_fraction(entry.id, value / 127)
      end
    end)
    if not ok then print("MACHINISTA_BRIDGE_LAYER " .. tostring(err)) end
  end
  return true
end

return M
