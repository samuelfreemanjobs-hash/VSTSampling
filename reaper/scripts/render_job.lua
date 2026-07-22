-- render_job.lua — headless render driver for VST Sampling Factory.
--
-- Invoked as:  reaper.exe -new -nosplash -script render_job.lua
-- Reads current_job.json (flat JSON) and current_events.txt (one note per
-- line: start_seconds TAB end_seconds TAB midi_note TAB velocity) from the
-- directory this script runs in, builds the project, renders, and writes
-- render_result.txt with "OK: <path>" or "ERROR: <message>".
--
-- Notes are inserted directly via the MIDI API (no .mid file import) so
-- no tempo-map import prompt can ever appear and timing is second-exact
-- regardless of project tempo.

local function script_dir()
  local info = debug.getinfo(1, "S")
  return info.source:match("@?(.*[/\\])") or ""
end

local function read_file(path)
  local f = io.open(path, "r")
  if not f then return nil end
  local body = f:read("*a")
  f:close()
  return body
end

local function write_result(msg)
  local f = io.open(script_dir() .. "render_result.txt", "w")
  if f then f:write(msg) f:close() end
end

local function fail(msg)
  write_result("ERROR: " .. msg)
  reaper.Main_OnCommand(40004, 0) -- File: Quit
end

-- Minimal JSON decoding for the flat job object (no nested tables).
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

local job_path = script_dir() .. "current_job.json"
local body = read_file(job_path)
if not body then return fail("job file not found: " .. job_path) end
local job = parse_job(body)

local events_path = script_dir() .. "current_events.txt"
local events_body = read_file(events_path)
if not events_body then return fail("events file not found: " .. events_path) end

-- Fresh project with one track
reaper.Main_OnCommand(40023, 0) -- File: New project
reaper.InsertTrackAtIndex(0, false)
local track = reaper.GetTrack(0, 0)
if not track then return fail("could not create track") end

-- TrackFX_AddByName wants "VST:Name" / "VST3:Name" prefixes; the FX
-- browser (and our plugin scanner) shows "VSTi: Name" / "VST3i: Name".
local function fx_query(name)
  local rest = name:match("^VSTi:%s*(.+)$")
  if rest then return "VST:" .. rest end
  rest = name:match("^VST3i:%s*(.+)$")
  if rest then return "VST3:" .. rest end
  return name
end

-- Instrument: either a saved FX chain or plugin by name (+ preset)
if job.fxchain and job.fxchain ~= "" then
  local fx = reaper.TrackFX_AddByName(track, job.fxchain, false, -1000)
  if fx < 0 then return fail("could not load fx chain: " .. job.fxchain) end
else
  local query = fx_query(job.plugin)
  local fx = reaper.TrackFX_AddByName(track, query, false, -1000)
  if fx < 0 then
    -- fall back to the raw name, then to the name without any prefix
    fx = reaper.TrackFX_AddByName(track, job.plugin, false, -1000)
  end
  if fx < 0 then
    local bare = job.plugin:match("^%w+i?:%s*(.+)$")
    if bare then fx = reaper.TrackFX_AddByName(track, bare, false, -1000) end
  end
  if fx < 0 then return fail("plugin not found in Reaper: '" .. tostring(job.plugin)
    .. "'. Open Reaper's FX browser and copy the exact name.") end
  if job.preset and job.preset ~= "" then
    local ok = reaper.TrackFX_SetPreset(track, fx, job.preset)
    if not ok then return fail("preset not found: '" .. job.preset
      .. "'. For plugins with their own browser (Omnisphere), use an FX chain instead.") end
  end
end

-- One MIDI item spanning the whole timeline; insert notes at exact seconds
local item = reaper.CreateNewMIDIItemInProject(track, 0, job.total_seconds, false)
if not item then return fail("could not create MIDI item") end
local take = reaper.GetActiveTake(item)
if not take then return fail("could not get MIDI take") end

local inserted = 0
for line in events_body:gmatch("[^\r\n]+") do
  local s, e, note, vel = line:match("^([%d%.]+)\t([%d%.]+)\t(%d+)\t(%d+)$")
  if s then
    local ppq_s = reaper.MIDI_GetPPQPosFromProjTime(take, tonumber(s))
    local ppq_e = reaper.MIDI_GetPPQPosFromProjTime(take, tonumber(e))
    reaper.MIDI_InsertNote(take, false, false, ppq_s, ppq_e, 0,
                           tonumber(note), tonumber(vel), true)
    inserted = inserted + 1
  end
end
if inserted == 0 then return fail("no notes parsed from events file") end
reaper.MIDI_Sort(take)

-- Render bounds = full timeline
reaper.GetSet_LoopTimeRange(true, false, 0, job.total_seconds, false)

-- Render settings on the project, then render without opening the dialog
local proj = 0
reaper.GetSetProjectInfo(proj, "RENDER_SETTINGS", 0, true)     -- master mix
reaper.GetSetProjectInfo(proj, "RENDER_BOUNDSFLAG", 2, true)   -- time selection
reaper.GetSetProjectInfo(proj, "RENDER_SRATE", job.sample_rate, true)
reaper.GetSetProjectInfo(proj, "RENDER_CHANNELS", job.channels, true)
local out_dir = job.output_wav:match("(.*[/\\])")
local out_name = job.output_wav:match("([^/\\]+)%.[Ww][Aa][Vv]$")
if not out_dir or not out_name then
  return fail("output_wav must be a full path ending in .wav: " .. tostring(job.output_wav))
end
reaper.GetSetProjectInfo_String(proj, "RENDER_FILE", out_dir, true)
reaper.GetSetProjectInfo_String(proj, "RENDER_PATTERN", out_name, true)
reaper.GetSetProjectInfo_String(proj, "RENDER_FORMAT", "evaw", true) -- WAV

reaper.Main_OnCommand(41824, 0) -- File: Render project, using the most recent render settings

if reaper.file_exists(job.output_wav) then
  write_result("OK: " .. job.output_wav)
else
  write_result("ERROR: render finished but output missing: " .. job.output_wav)
end

reaper.Main_OnCommand(40004, 0) -- File: Quit
