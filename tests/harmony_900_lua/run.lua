-- Load a configuration the way a Harmony 900 does at boot, then answer the touchscreen.
--   lua5.1 run.lua <unpacked configuration> <event xml>...
-- Run from a directory whose lua/ holds the remote's own scripts beside these stubs.
-- One line per outcome: "BOOT ok", "BOOT error <msg>", "<event> ok <n>" or
-- "<event> error <msg>". A Lua error means the touchscreen never gets its answer.
CONFIG_DIR = arg[1]
package.path = "./lua/?.lua;" .. package.path
require("env_svc"); require("TableSave")
local function line(s) io.stderr:write(s:gsub("\n", " "), "\n") end
local ok, err = pcall(dofile, "./lua/HAO.lua")
if not ok then line("BOOT error " .. tostring(err)); os.exit(1) end
ok, err = pcall(main)
if not ok then line("BOOT error " .. tostring(err)); os.exit(1) end
line("BOOT ok")
for i = 2, #arg do
  EVENTS = {}
  local name = arg[i]:match("<Name>(.-)</Name>")
  ok, err = pcall(function() return handleEventXML(arg[i], #arg[i]) end)
  if ok then line(name .. " ok " .. #EVENTS) else line(name .. " error " .. tostring(err)) end
end
