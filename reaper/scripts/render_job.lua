-- render_job.lua — headless render driver for VST Sampling Factory.
--
-- Invoked as:  reaper.exe -newinst -new -nosplash -ignoreerrors <this file>
-- Reads current_job.json (flat JSON) and current_events.txt (one note per
-- line: start_seconds TAB end_seconds TAB midi_note TAB velocity) from its
-- own directory. Writes render_started.txt immediately (so the controller
-- can tell "script never ran" from "script died"), then render_result.txt
-- with "OK: <path>" or "ERROR: <message>". Any Lua error is caught and
-- reported — this script must never die silently.

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

-- TrackFX_AddByName wants "VST:Name"/"VST3:Name"; the FX browser (and our
-- plugin scanner) shows "VSTi: Name"/"VST3i: Name". Try progressively
-- looser queries, including stripping a "(NN out)" channel suffix.
local function add_instrument(track, name)
  local candidates = {}
  local rest = name:match("^VSTi:%s*(.+)$")
  if rest then candidates[#candidates + 1] = "VST:" .. rest end
  rest = name:match("^VST3i:%s*(.+)$")
  if rest then candidates[#candidates + 1] = "VST3:" .. rest end
  candidates[#candidates + 1] = name
  rest = name:match("^%w+i?:%s*(.+)$")
  if rest then candidates[#candidates + 1] = rest end
  -- same set again without a trailing "(NN out)"
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

local function main()
  local job_path = script_dir() .. "current_job.json"
  local body = read_file(job_path)
  if not body then error("job file not found: " .. job_path, 0) end
  local job = parse_job(body)

  local events_body = read_file(script_dir() .. "current_events.txt")
  if not events_body then error("events file not found next to script", 0) end

  -- Fresh project with one track
  reaper.Main_OnCommand(40023, 0) -- File: New project
  reaper.InsertTrackAtIndex(0, false)
  local track = reaper.GetTrack(0, 0)
  if not track then error("could not create track", 0) end

  -- Instrument: either a saved FX chain or plugin by name (+ preset)
  if job.fxchain and job.fxchain ~= "" then
    local fx = reaper.TrackFX_AddByName(track, job.fxchain, false, -1000)
    if fx < 0 then error("could not load fx chain: " .. job.fxchain, 0) end
  else
    local fx = add_instrument(track, tostring(job.plugin))
    if fx < 0 then
      error("plugin not found in Reaper: '" .. tostring(job.plugin)
        .. "'. Open Reaper's FX browser and copy the exact name.", 0)
    end
    if job.preset and job.preset ~= "" then
      local ok = reaper.TrackFX_SetPreset(track, fx, job.preset)
      if not ok then
        error("preset not found: '" .. job.preset
          .. "'. For plugins with their own browser (Omnisphere), use an FX chain instead.", 0)
      end
    end
  end

  -- One MIDI item spanning the whole timeline; insert notes at exact seconds
  local item = reaper.CreateNewMIDIItemInProject(track, 0, job.total_seconds, false)
  if not item then error("could not create MIDI item", 0) end
  local take = reaper.GetActiveTake(item)
  if not take then error("could not get MIDI take", 0) end

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
  if inserted == 0 then error("no notes parsed from events file", 0) end
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
    error("output_wav must be a full path ending in .wav: " .. tostring(job.output_wav), 0)
  end
  reaper.GetSetProjectInfo_String(proj, "RENDER_FILE", out_dir, true)
  reaper.GetSetProjectInfo_String(proj, "RENDER_PATTERN", out_name, true)
  reaper.GetSetProjectInfo_String(proj, "RENDER_FORMAT", "evaw", true) -- WAV

  reaper.Main_OnCommand(41824, 0) -- File: Render project, using the most recent render settings

  if reaper.file_exists(job.output_wav) then
    write_file("render_result.txt", "OK: " .. job.output_wav)
  else
    error("render finished but output missing: " .. job.output_wav
      .. " (check Reaper's render settings dialog wasn't left in a custom state)", 0)
  end
end

write_file("render_started.txt", tostring(os.time()))
local ok, err = pcall(main)
if not ok then
  write_file("render_result.txt", "ERROR: " .. tostring(err))
end
reaper.Main_OnCommand(40004, 0) -- File: Quit (controller kills us if a prompt blocks this)
