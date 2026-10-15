-- The 1100's HAO.lua fetches its configuration with luasocket; serve it from httpget
-- (the 900's stand-in, env_svc.lua) instead.
local M = {}
function M.request(url) return httpget(url), 200, {} end
return M
