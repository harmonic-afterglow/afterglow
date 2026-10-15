-- Load a configuration the way a Harmony 1100 does at boot, then start activities one
-- after another. A line per outcome: "BOOT ok" or "BOOT error <msg>", then for each
-- activity "<id> ok <commands sent>" or "<id> error <msg>". A Lua error is a remote that
-- stops answering.
--   lua5.1 run.lua <unpacked configuration> <activity id>...
CONFIG_DIR = arg[1]
package.path = "./lua/?.lua;" .. package.path
require("env_svc")
io.write = function() end
local function line(s) io.stderr:write((s:gsub("\n", " ")), "\n") end
local ok, err = pcall(dofile, "./lua/HAO.lua")
if ok then ok, err = pcall(main) end
if not ok then line("BOOT error " .. tostring(err)); os.exit(1) end
line("BOOT ok")
for i = 2, #arg do
  IRSENT = {}
  local xml = "<Event><Payload><Name>StartActivity</Name><Params><Id>" .. arg[i] ..
              "</Id></Params></Payload></Event>"
  ok, err = pcall(handleEventXML, xml, #xml)
  local sent = 0
  for _, entry in ipairs(IRSENT) do
    if tostring(entry[1]):match("^%d+$") then sent = sent + 1 end
  end
  line(arg[i] .. (ok and (" ok " .. sent) or (" error " .. tostring(err))))
end
