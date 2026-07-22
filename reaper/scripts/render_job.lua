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

  -- Fresh project with one track routed to master
  reaper.Main_OnCommand(40023, 0) -- File: New project
  reaper.InsertTrackAtIndex(0, true) -- true: with defaults (incl. master send)
  local track = reaper.GetTrack(0, 0)
  if not track then error("could not create track", 0) end
  if reaper.SetMediaTrackInfo_Value then
    reaper.SetMediaTrackInfo_Value(track, "B_MAINSEND", 1) -- force master send on
    reaper.SetMediaTrackInfo_Value(track, "D_VOL", 1.0)    -- unity volume
    reaper.SetMediaTrackInfo_Value(track, "B_MUTE", 0)
  end

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
    if job.preset_index and tonumber(job.preset_index) and tonumber(job.preset_index) >= 0 then
      -- Index selection (from a preset scan): robust against name quirks
      local ok = reaper.TrackFX_SetPresetByIndex(track, fx, tonumber(job.preset_index))
      if not ok then
        error("could not select preset index " .. tostring(job.preset_index)
          .. " ('" .. tostring(job.preset) .. "') — re-run the preset scan", 0)
      end
    elseif job.preset and job.preset ~= "" then
      local ok = reaper.TrackFX_SetPreset(track, fx, job.preset)
      if not ok then
        error("preset not found: '" .. job.preset
          .. "'. For plugins with their own browser (Omnisphere), use an FX chain instead.", 0)
      end
    end
  end

  -- Pin the project tempo to the chunk's embedded tempo so seconds map
  -- exactly, whatever the user's default project template says.
  if reaper.SetCurrentBPM then reaper.SetCurrentBPM(0, 120, false) end

  -- Build the MIDI item. Primary method: stamp a complete item state
  -- chunk written by Python — one call, works on every Reaper version,
  -- cannot half-succeed. Fallback: per-note API insertion (observed
  -- unreliable on some setups, kept as a last resort).
  local take
  local chunk_body = read_file(script_dir() .. "current_chunk.txt")
  if chunk_body and reaper.AddMediaItemToTrack and reaper.SetItemStateChunk then
    local item = reaper.AddMediaItemToTrack(track)
    if not item then error("could not create media item", 0) end
    local okc = reaper.SetItemStateChunk(item, chunk_body, false)
    if not okc then error("SetItemStateChunk rejected the MIDI item chunk", 0) end
    if reaper.UpdateArrange then reaper.UpdateArrange() end
    take = reaper.GetActiveTake and reaper.GetActiveTake(item) or nil
  elseif reaper.CreateNewMIDIItemInProject then
    local item = reaper.CreateNewMIDIItemInProject(track, 0, job.total_seconds, false)
    if not item then error("could not create MIDI item", 0) end
    take = reaper.GetActiveTake(item)
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
  else
    error("no way to create a MIDI item (chunk file or API missing)", 0)
  end

  -- Verify events actually landed. Count defensively: docs say
  -- (retval, notecnt, ...) but be robust to either slot holding it.
  if take and reaper.MIDI_CountEvts then
    local a, b = reaper.MIDI_CountEvts(take)
    local cnt = 0
    if type(b) == "number" and b > cnt then cnt = b end
    if type(a) == "number" and a > cnt then cnt = a end
    if cnt == 0 then
      error("MIDI item created but 0 events counted — notes did not land", 0)
    end
  end

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

local function run()
  local ok, err = pcall(main)
  if not ok then
    write_file("render_result.txt", "ERROR: " .. tostring(err))
  end
  reaper.Main_OnCommand(40004, 0) -- File: Quit (controller kills us if a prompt blocks this)
end

write_file("render_started.txt", tostring(os.time()))
-- Command-line scripts execute during REAPER startup, before the API is
-- fully registered (observed: CreateNewMIDIItemInProject == nil). Defer
-- the real work until the event loop is alive and the API is complete.
if reaper.defer then
  reaper.defer(run)
else
  run()
end
