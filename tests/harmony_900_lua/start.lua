-- Load a configuration the way a Harmony 900 does at boot, start activities one after
-- another, and print what each start sends: "<id> send <device> <command>" for a command
-- and "<id> delay <device> <ms>" for a wait, a line each.
--   lua5.1 start.lua <unpacked configuration> <activity id>...
CONFIG_DIR = arg[1]
package.path = "./lua/?.lua;" .. package.path
require("env_svc"); require("TableSave")
io.write = function() end
dofile("./lua/HAO.lua"); main()
for i = 2, #arg do
  IRSENT = {}
  local xml = "<Event><Payload><Name>StartActivity</Name><Params><Id>" .. arg[i] ..
              "</Id></Params></Payload></Event>"
  handleEventXML(xml, #xml)
  for _, sent in ipairs(IRSENT) do
    if sent[1] == "deviceDelay" then
      io.stderr:write(arg[i], " delay ", tostring(sent[2]), " ", tostring(sent[3]), "\n")
    elseif sent[1] ~= "flush" and sent[1] ~= "notifyDelay" and sent[1] ~= "notifyIrCommand" then
      local parts = {}
      for j, v in ipairs(sent) do parts[j] = tostring(v) end
      io.stderr:write(arg[i], " send ", table.concat(parts, " "), "\n")
    end
  end
end
