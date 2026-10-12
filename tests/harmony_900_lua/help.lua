-- Load a configuration the way a Harmony 900 does at boot, press Help in an activity, and
-- print what the remote's Help engine asks about: one "<device> <state> <value>" a line.
--   lua5.1 help.lua <unpacked configuration> <activity id>
CONFIG_DIR = arg[1]
package.path = "./lua/?.lua;" .. package.path
require("env_svc"); require("TableSave")
io.write = function() end
dofile("./lua/HAO.lua"); main()
EVENTS = {}
local xml = "<Event><Payload><Name>Help</Name><Params><Id>" .. arg[2] .. "</Id></Params></Payload></Event>"
handleEventXML(xml, #xml)
for _, event in ipairs(EVENTS) do
  for device, state, value in event:gmatch("<Device>(.-)</Device><State>(.-)</State><Value>(.-)</Value>") do
    io.stderr:write(device, " ", state, " ", value, "\n")
  end
end
