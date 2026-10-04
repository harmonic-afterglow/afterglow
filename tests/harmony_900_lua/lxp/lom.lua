-- Pure-Lua stand-in for lxp.lom: parse XML into LOM tables {tag=, attr={...}, children...}.
lxp = lxp or {}
local function decode(s)
  s = s:gsub("&#x(%x+);", function(h) return string.char(tonumber(h,16) % 256) end)
  s = s:gsub("&#(%d+);", function(d) return string.char(tonumber(d) % 256) end)
  return (s:gsub("&lt;","<"):gsub("&gt;",">"):gsub("&quot;",'"'):gsub("&apos;","'"):gsub("&amp;","&"))
end
local function parse(s)
  if type(s) ~= "string" then return nil end
  local stack, root = {{}}, nil
  local i, n = 1, #s
  while i <= n do
    local lt = s:find("<", i, true)
    if not lt then
      local text = s:sub(i); if #text > 0 and #stack > 1 then table.insert(stack[#stack], decode(text)) end
      break
    end
    if lt > i and #stack > 1 then table.insert(stack[#stack], decode(s:sub(i, lt-1))) end
    if s:sub(lt, lt+3) == "<!--" then i = s:find("-->", lt, true) + 3
    elseif s:sub(lt, lt+8) == "<![CDATA[" then
      local e = s:find("]]>", lt, true); table.insert(stack[#stack], s:sub(lt+9, e-1)); i = e + 3
    elseif s:sub(lt, lt+1) == "<?" or s:sub(lt, lt+1) == "<!" then i = s:find(">", lt, true) + 1
    elseif s:sub(lt, lt+1) == "</" then
      local e = s:find(">", lt, true); local el = table.remove(stack)
      if #stack == 1 then root = el end
      table.insert(stack[#stack], el); i = e + 1
    else
      local e = s:find(">", lt, true)
      local body = s:sub(lt+1, e-1); local selfclose = body:sub(-1) == "/"
      if selfclose then body = body:sub(1, -2) end
      local tag = body:match("^([%w_:%.%-]+)")
      local el = {tag = tag, attr = {}}
      for k, q, v in body:gmatch('([%w_:%.%-]+)%s*=%s*(["\'])(.-)%2') do
        table.insert(el.attr, k); el.attr[k] = decode(v)
      end
      if selfclose then table.insert(stack[#stack], el); if #stack == 1 then root = el end
      else table.insert(stack, el) end
      i = e + 1
    end
  end
  return root
end
lxp.lom = {parse = parse}
return lxp.lom
