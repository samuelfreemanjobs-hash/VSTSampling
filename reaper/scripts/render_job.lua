-- render_job.lua — headless render driver for VST Sampling Factory.
--
-- Invoked as:  reaper.exe -new -nosplash -script render_job.lua
-- The job file path is read from the RENDER_JOB_FILE ExtState, which the
-- Python controller sets by writing a tiny bootstrap .lua, or from the
-- fixed sibling path "current_job.json" next to this script.
--
-- Job JSON fields:
--   plugin        VSTi name as Reaper knows it, e.g. "VSTi: Omnisphere (Spectrasonics)"
--   preset       preset name to select (optional; empty = leave as loaded)
--   fxchain      path to a .RfxChain file to load instead of plugin+preset (optional)
--   midi_file    absolute path to the .mid timeline
--   output_wav   absolute path for the rendered WAV
--   sample_rate  e.g. 44100
--   bit_depth    16, 24, or 32
--   channels     1 or 2
--   total_seconds  timeline length to render

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

local function fail(msg)
  local f = io.open(script_dir() .. "render_result.txt", "w")
  if f then f:write("ERROR: " .. msg) f:close() end
  reaper.Main_OnCommand(40004, 0) -- File: Quit
end

local job_path = reaper.GetExtState("VSTSamplingFactory", "job_file")
if job_path == "" then job_path = script_dir() .. "current_job.json" end

local body = read_file(job_path)
if not body then return fail("job file not found: " .. job_path) end
local job = parse_job(body)

-- Fresh project
reaper.Main_OnCommand(40023, 0) -- File: New project
local track_index = 0
reaper.InsertTrackAtIndex(track_index, false)
local track = reaper.GetTrack(0, track_index)

-- Instrument: either a saved FX chain or plugin by name (+ preset)
if job.fxchain and job.fxchain ~= "" then
  local fx = reaper.TrackFX_AddByName(track, job.fxchain, false, -1000)
  if fx < 0 then return fail("could not load fx chain: " .. job.fxchain) end
else
  local fx = reaper.TrackFX_AddByName(track, job.plugin, false, -1000)
  if fx < 0 then return fail("plugin not found: " .. job.plugin) end
  if job.preset and job.preset ~= "" then
    local ok = reaper.TrackFX_SetPreset(track, fx, job.preset)
    if not ok then return fail("preset not found: " .. job.preset) end
  end
end

-- Insert the MIDI timeline at 0:00 on our track
reaper.SetOnlyTrackSelected(track)
reaper.SetEditCurPos(0, false, false)
local inserted = reaper.InsertMedia(job.midi_file, 0)
if inserted == 0 then return fail("could not insert midi: " .. job.midi_file) end

-- Render bounds = full timeline
reaper.GetSet_LoopTimeRange(true, false, 0, job.total_seconds, false)

-- Render settings
local proj = 0
reaper.GetSetProjectInfo(proj, "RENDER_SETTINGS", 0, true)          -- master mix
reaper.GetSetProjectInfo(proj, "RENDER_BOUNDSFLAG", 2, true)        -- time selection
reaper.GetSetProjectInfo(proj, "RENDER_SRATE", job.sample_rate, true)
reaper.GetSetProjectInfo(proj, "RENDER_CHANNELS", job.channels, true)
reaper.GetSetProjectInfo_String(proj, "RENDER_FILE", job.output_wav:match("(.*[/\\])"), true)
reaper.GetSetProjectInfo_String(proj, "RENDER_PATTERN", job.output_wav:match("([^/\\]+)%.wav$"), true)

-- WAV output format. "evaw" config blob: default WAV; bit depth via RENDER_FORMAT2
-- is fiddly from Lua, so we render with project default format configured by the
-- controller-side template project. Fallback: 24-bit WAV.
reaper.GetSetProjectInfo_String(proj, "RENDER_FORMAT", "evaw", true)

reaper.Main_OnCommand(42230, 0) -- File: Render project, using the most recent render settings, auto-close when finished

local f = io.open(script_dir() .. "render_result.txt", "w")
if f then f:write("OK: " .. job.output_wav) f:close() end

reaper.Main_OnCommand(40004, 0) -- File: Quit
