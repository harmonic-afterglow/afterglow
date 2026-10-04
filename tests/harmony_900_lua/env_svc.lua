-- Stand-ins for the C services a Harmony 900 gives its Lua, for tests only.
-- httpget serves the unpacked configuration; whatever the touchscreen would receive is kept.
EVENTS = {}
CONFIG_DIR = CONFIG_DIR or "."
local files = {
  ["http://127.0.0.1/userconfig"] = "userconfig/UserConfiguration.xml",
  ["http://127.0.0.1/actionlist"] = "userconfig/ActionLists.xml",
  ["http://127.0.0.1/xmluserrfsetting"] = "platformconfig/XmlUserRfSetting.xml",
  ["http://127.0.0.1/system/helpdb"] = "platformconfig/help.db",
}
function httpget(url)
  local rel = files[url]; if not rel then io.write("[httpget unknown] ", url, "\n"); return nil end
  local f = io.open(CONFIG_DIR .. "/" .. rel, "rb"); if not f then return nil end
  local s = f:read("*a"); f:close(); return s
end
function httppost(host, path, data) return true end
function sendEvent(msg, len) table.insert(EVENTS, (msg:gsub("%z", ""))) end
function usleep() end
function getTime() return 0 end
function getTimeStamp() return 0 end
function getTimeRemaining() return 0 end
for _, name in ipairs({"env_set_backlight_segments","env_set_backlight_master_level",
    "env_get_backlight_segments","env_timer_arm","env_timer_clear","env_set_lcd_state",
    "env_set_backlight_master","env_set_app_busy_state","env_service_connect",
    "env_set_ui_busy_state","env_set_clock","env_set_backlight_dimmer_level",
    "env_get_usb_connection_state"}) do
  _G[name] = function() return 0 end
end
IRSENT = {}
function irqStringToPage(...) table.insert(IRSENT, {...}); return 0 end
function irqGetPage() return 0 end
function sendCommand(...) table.insert(IRSENT, {...}); return 0 end
for _, name in ipairs({"flush","deviceDelay","notifyDelay","notifyIrCommand","forwardAction","sendRFEvent"}) do
  _G[name] = function(...) table.insert(IRSENT, {name, ...}); return 0 end
end
return true
