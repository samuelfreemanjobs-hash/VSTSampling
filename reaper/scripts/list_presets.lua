-- list_presets.lua — preset enumeration driver for VST Sampling Factory.
--
-- Invoked as:  reaper.exe -newinst -new -nosplash -ignoreerrors <this file>
-- Reads current_job.json ({"plugin": ...}) from its own directory, loads
-- the instrument, walks its preset list by index, and writes
-- presets_result.txt: one preset name per line, or "ERROR: <message>".
-- scan_started.txt is written immediately so the controller can tell
-- "script never ran" from "script died".

local function script_dir()
  local info = debug.getinfo(1, "S")
  return info.source:match("@?(.*[/\\])") or ""
end

local function write_file(name, msg)
  local f = io.open(script_dir() .. name, "w")
  if f then f:write(msg) f:close() end
end

local function read_file(path)
  local f = io.open(path, "r")
  if not f then return nil end
  local body = f:read("*a")
  f:close()
  return body
end

local function parse_job(body)
  local job = {}
  for key, value in body:gmatch('"([%w_]+)"%s*:%s*"(.-)"') do
    job[key] = value:gsub('\\\\', '\\')
  end
  for key, value in body:gmatch('"([%w_]+)"%s*:%s*([%d%.]+)') do
    if job[key] == nil then job[key] = tonumber(value) end
  end
  return job
end

local function add_instrument(track, name)
  local candidates = {}
  local rest = name:match("^VSTi:%s*(.+)$")
  if rest then candidates[#candidates + 1] = "VST:" .. rest end
  rest = name:match("^VST3i:%s*(.+)$")
  if rest then candidates[#candidates + 1] = "VST3:" .. rest end
  candidates[#candidates + 1] = name
  rest = name:match("^%w+i?:%s*(.+)$")
  if rest then candidates[#candidates + 1] = rest end
  local n = #candidates
  for i = 1, n do
    local stripped = candidates[i]:gsub("%s*%(%d+ out%)%s*$", "")
    if stripped ~= candidates[i] then candidates[#candidates + 1] = stripped end
  end
  for _, query in ipairs(candidates) do
    local fx = reaper.TrackFX_AddByName(track, query, false, -1000)
    if fx >= 0 then return fx end
  end
  return -1
end

local MAX_PRESETS = 2000

local function main()
  local body = read_file(script_dir() .. "current_job.json")
  if not body then error("job file not found", 0) end
  local job = parse_job(body)

  reaper.Main_OnCommand(40023, 0) -- new project
  reaper.InsertTrackAtIndex(0, true)
  local track = reaper.GetTrack(0, 0)
  if not track then error("could not create track", 0) end

  local fx = add_instrument(track, tostring(job.plugin))
  if fx < 0 then
    error("plugin not found in Reaper: '" .. tostring(job.plugin) .. "'", 0)
  end

  if not reaper.TrackFX_GetPresetIndex then
    error("preset API unavailable in this Reaper version", 0)
  end
  local _, count = reaper.TrackFX_GetPresetIndex(track, fx)
  count = tonumber(count) or 0
  if count <= 0 then
    write_file("presets_result.txt", "NONE")
    return
  end

  local capped = math.min(count, MAX_PRESETS)
  local names = {}
  for i = 0, capped - 1 do
    reaper.TrackFX_SetPresetByIndex(track, fx, i)
    local ok, name = reaper.TrackFX_GetPreset(track, fx, "")
    if ok and name and name ~= "" then
      names[#names + 1] = name
    else
      names[#names + 1] = "Preset " .. tostring(i + 1)
    end
  end
  local out = table.concat(names, "\n")
  if count > MAX_PRESETS then
    out = out .. "\n#CAPPED " .. tostring(count)
  end
  write_file("presets_result.txt", out)
end

local function run()
  local ok, err = pcall(main)
  if not ok then
    write_file("presets_result.txt", "ERROR: " .. tostring(err))
  end
  reaper.Main_OnCommand(40004, 0) -- quit
end

write_file("scan_started.txt", tostring(os.time()))
if reaper.defer then
  reaper.defer(run)
else
  run()
end
